"""Interfaz local de Transaction Explorer. Iniciar con streamlit run app.py."""

import csv
import io
import json
import math

import pandas as pd
import streamlit as st

from metrics import calculate_metrics, format_amount
from normalizer import (
    BASE_DIR, NORMALIZED_FIELDS, DataImportError, ProcessingResult,
    load_config, load_json, load_json_file, process_transactions,
)

LABELS = {
    "transaction_id": "Identificador", "source": "Fuente", "amount": "Monto",
    "currency": "Moneda", "status": "Estado", "transaction_date": "Fecha ISO 8601",
    "transaction_type": "Tipo de operación", "is_valid": "Válida",
    "validation_errors": "Errores de validación",
}


def diagnostic_json(value) -> str:
    """Representación legible; Decimal se serializa como texto para no perder dígitos."""
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


def make_table(records: list[dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        row = {**record, "amount": format_amount(record["amount"]),
               "validation_errors": " | ".join(record["validation_errors"])}
        rows.append(row)
    return pd.DataFrame(rows, columns=NORMALIZED_FIELDS)


def show_table(records: list[dict]) -> None:
    st.dataframe(make_table(records), hide_index=True, use_container_width=True,
                 column_config=LABELS)


def filter_transactions(records: list[dict], selections: dict, validity: str) -> list[dict]:
    """Filtros combinados por intersección; una selección vacía no muestra filas."""
    return [r for r in records
            if all(r[field] in selected for field, selected in selections.items())
            and (validity == "Todas" or r["is_valid"] == (validity == "Válidas"))]


def export_csv(result: ProcessingResult, *, valid: bool) -> bytes:
    """CSV UTF-8 BOM, montos exactos y diagnóstico original para inválidas."""
    output = io.StringIO(newline="")
    fields = list(NORMALIZED_FIELDS) + ([] if valid else ["original_index", "original_data"])
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for index, record in enumerate(result.records):
        if record["is_valid"] != valid:
            continue
        row = dict(record)
        row["amount"] = str(row["amount"]) if row["amount"] is not None else ""
        row["validation_errors"] = json.dumps(row["validation_errors"], ensure_ascii=False)
        if not valid:
            row.update(original_index=index + 1, original_data=diagnostic_json(result.originals[index]))
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def count_chart(title: str, counts: dict, color: str) -> None:
    st.subheader(title)
    if counts:
        frame = pd.DataFrame({"Categoría": list(counts), "Transacciones": list(counts.values())})
        st.bar_chart(frame, x="Categoría", y="Transacciones", color=color, horizontal=True)
    else:
        st.info("No hay transacciones válidas para esta distribución.")


def dashboard(result: ProcessingResult) -> None:
    st.header("Dashboard")
    st.write("Una vista general de la calidad y composición del conjunto activo.")
    metrics = calculate_metrics(result.records)
    cards = st.columns(4)
    for card, label, value in zip(cards, ["Total procesadas", "Válidas", "Inválidas", "Porcentaje de validez"],
                                  [metrics["total"], metrics["valid"], metrics["invalid"], f'{metrics["valid_percentage"]:.1f}%']):
        card.metric(label, value)
    st.caption("Tarjetas y conteo por fuente: todos los registros. Estados, tipos e importes: solo válidas. "
               "Los importes incluyen COMPLETED, PENDING y FAILED; no representan saldo ni liquidación.")
    left, right = st.columns(2)
    with left:
        count_chart("Distribución por estado", metrics["by_status"], "#2563EB")
    with right:
        count_chart("Distribución por fuente", metrics["by_source"], "#0D9488")
    left, right = st.columns(2)
    with left:
        st.subheader("Totales por moneda")
        if metrics["totals_by_currency"]:
            for currency, total in metrics["totals_by_currency"].items():
                st.metric(currency, format_amount(total))
                # Vega representa números gráficos mediante punto flotante.
                # Esta conversión es exclusivamente visual, después de agregar con Decimal.
                try:
                    visual = float(total)
                    if math.isfinite(visual):
                        st.bar_chart(pd.DataFrame({"Moneda": [currency], "Importe": [visual]}),
                                     x="Moneda", y="Importe", color="#0D9488", height=160)
                    else:
                        st.caption("Importe fuera del rango de representación gráfica; consulte el total exacto exportado.")
                except OverflowError:
                    st.caption("Importe fuera del rango gráfico; consulte el total exacto exportado.")
            st.caption("Cada moneda tiene su propio gráfico. No se aplican tipos de cambio.")
        else:
            st.info("No hay importes válidos para mostrar.")
    with right:
        count_chart("Distribución por tipo de operación", metrics["by_type"], "#6366F1")


def explorer(result: ProcessingResult) -> None:
    st.header("Explorador de transacciones")
    st.write("Combine filtros para consultar el esquema normalizado.")
    fields = ["source", "currency", "status", "transaction_type"]
    selections = {}
    for column, field in zip(st.columns(4), fields):
        options = sorted({r[field] for r in result.records})
        selections[field] = column.multiselect(LABELS[field], options, default=options,
                                               format_func=lambda value: value or "Sin normalizar",
                                               key=f"filter_{field}")
    validity = st.radio("Validez", ["Todas", "Válidas", "Inválidas"], horizontal=True, key="validity")
    filtered = filter_transactions(result.records, selections, validity)
    st.caption(f"{len(filtered)} de {len(result.records)} registros · Vaciar un filtro no muestra filas.")
    if filtered:
        show_table(filtered)
    else:
        st.info("No hay registros que coincidan con los filtros seleccionados.")
    st.caption("Montos presentados con dos decimales. El procesamiento y los CSV conservan la precisión original.")


def invalid_records(result: ProcessingResult) -> None:
    st.header("Registros inválidos")
    st.write("Cada registro conserva todas sus causas de invalidez y sus datos de origen.")
    indexes = [i for i, record in enumerate(result.records) if not record["is_valid"]]
    if not indexes:
        st.success("Todos los registros del conjunto activo son válidos.")
        return
    show_table(result.invalid)
    def label(index):
        record = result.records[index]
        return f'Fila {index + 1} · {record["source"] or "Sin fuente"} · {record["transaction_id"] or "Sin identificador"}'
    index = st.selectbox("Seleccione un registro para inspeccionar", indexes, format_func=label)
    record = result.records[index]
    for error in record["validation_errors"]:
        st.error(error)
    left, right = st.columns(2)
    with left:
        st.subheader("Datos originales")
        st.code(diagnostic_json(result.originals[index]), language="json")
    with right:
        st.subheader("Campos normalizados disponibles")
        st.code(diagnostic_json(record), language="json")
    st.caption("En el diagnóstico JSON, Decimal se representa como texto para conservar sus dígitos.")


def replace_dataset(raw: list, name: str) -> None:
    st.session_state["raw_records"] = raw
    st.session_state["dataset_name"] = name
    for field in ("source", "currency", "status", "transaction_type"):
        st.session_state.pop(f"filter_{field}", None)


def import_data(result: ProcessingResult, config: dict) -> None:
    st.header("Importación de datos")
    st.write("Cargue un archivo JSON UTF-8 con una lista de objetos. Cada objeto debe incluir source: A, B o C.")
    st.caption("La importación reemplaza el conjunto activo y comprueba duplicados dentro de ese archivo. Máximo: 10 MB.")
    uploaded = st.file_uploader("Archivo de transacciones", type=["json"])
    if st.button("Procesar archivo", type="primary", disabled=uploaded is None):
        try:
            if uploaded.size > 10 * 1024 * 1024:
                raise DataImportError("El archivo supera el límite de 10 MB.")
            raw = load_json(uploaded.getvalue())
            replace_dataset(raw, uploaded.name)
            st.session_state["import_notice"] = f"Archivo procesado: {len(raw)} registros."
            st.rerun()
        except DataImportError as exc:
            st.error(str(exc))
            st.info("El conjunto activo se conserva. Corrija el archivo y vuelva a procesarlo.")
    if st.button("Utilizar datos de ejemplo"):
        try:
            replace_dataset(load_json_file(BASE_DIR / "data" / "sample_transactions.json"), "Datos de ejemplo")
            st.session_state["import_notice"] = "Se cargaron los datos de ejemplo."
            st.rerun()
        except DataImportError as exc:
            st.error(str(exc))
    with st.expander("Consultar las estructuras admitidas"):
        st.write("Los nombres de campos, estados, tipos, formatos de fecha y reglas monetarias se leen de config.json.")
        st.json(config)
    st.divider()
    st.subheader("Exportar el conjunto activo")
    st.caption("Las descargas incluyen el conjunto completo, independientemente de los filtros del explorador.")
    left, right = st.columns(2)
    left.download_button("Descargar válidas · CSV", export_csv(result, valid=True),
                         file_name="transacciones_validas.csv", mime="text/csv", use_container_width=True)
    right.download_button("Descargar reporte de inválidas · CSV", export_csv(result, valid=False),
                          file_name="registros_invalidos.csv", mime="text/csv", use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Transaction Explorer", page_icon="📊", layout="wide")
    try:
        config = load_config()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    if "raw_records" not in st.session_state:
        try:
            replace_dataset(load_json_file(BASE_DIR / "data" / "sample_transactions.json"), "Datos de ejemplo")
        except DataImportError as exc:
            replace_dataset([], "Sin datos")
            st.warning(f"No se pudieron cargar los ejemplos: {exc} Puede importar su propio JSON.")
    result = process_transactions(st.session_state["raw_records"], config)
    with st.sidebar:
        st.title("Transaction Explorer")
        st.caption("NORMALIZACIÓN MULTIFUENTE")
        page = st.radio("Navegación", ["Dashboard", "Explorador de transacciones", "Registros inválidos", "Importación de datos"], key="navigation")
        st.divider()
        st.write("Conjunto activo")
        st.info(st.session_state["dataset_name"])
        st.caption(f"{len(result.records)} registros · {len(result.valid)} válidos")
        st.caption("Procesamiento local · USD / EUR · Sin conversión de monedas")
    if "import_notice" in st.session_state:
        st.success(st.session_state.pop("import_notice"))
    if page == "Dashboard":
        dashboard(result)
    elif page == "Explorador de transacciones":
        explorer(result)
    elif page == "Registros inválidos":
        invalid_records(result)
    else:
        import_data(result, config)


if __name__ == "__main__":
    main()
