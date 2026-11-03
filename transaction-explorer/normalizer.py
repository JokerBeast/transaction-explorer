"""Lectura JSON exacta y transformación guiada por config.json.

El esquema público mantiene sus nueve campos. Los metadatos originales se
conservan fuera de él en ProcessingResult.originals, alineados por posición.
Un campo imposible de normalizar usa None (monto) o "" (texto) y es inválido.
"""

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any

from validator import split_transactions, validate_batch

BASE_DIR = Path(__file__).resolve().parent
NORMALIZED_FIELDS = (
    "transaction_id", "source", "amount", "currency", "status",
    "transaction_date", "transaction_type", "is_valid", "validation_errors",
)
DECIMAL_PATTERN = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")


class DataImportError(ValueError):
    """Error legible del documento de entrada, no de un registro individual."""


def _require_config(condition: bool) -> None:
    if not condition:
        raise ValueError("Regla de configuración inválida.")


def load_config(path: str | Path = BASE_DIR / "config.json") -> dict:
    """Carga y comprueba las reglas externas antes de procesar datos."""
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        _require_config(isinstance(config, dict))
        for key in ("supported_currencies", "normalized_statuses", "normalized_types"):
            _require_config(isinstance(config[key], list) and bool(config[key]))
            _require_config(all(isinstance(v, str) and bool(v) and v == v.strip().upper() for v in config[key]))
        _require_config(isinstance(config["sources"], dict) and bool(config["sources"]))
        for source, rule in config["sources"].items():
            _require_config(isinstance(source, str) and bool(source) and source == source.strip().upper())
            _require_config(set(rule["fields"]) == set(NORMALIZED_FIELDS[:7]) - {"source"})
            _require_config(all(isinstance(v, str) and bool(v) for v in rule["fields"].values()))
            for mapping, target in (("status_map", "normalized_statuses"), ("type_map", "normalized_types")):
                _require_config(bool(rule[mapping]) and all(v in config[target] for v in rule[mapping].values()))
                _require_config(all(isinstance(k, str) and bool(k) and k == k.strip().lower() for k in rule[mapping]))
            _require_config(rule["date"]["kind"] in {"date", "iso_datetime"})
            _require_config(isinstance(rule["date"]["format"], str) and bool(rule["date"]["format"]))
            _require_config(rule["amount"]["kind"] in {"units", "minor_units", "decimal_string"})
            if rule["amount"]["kind"] == "minor_units":
                divisors = rule["amount"]["divisors"]
                _require_config(all(c in divisors for c in config["supported_currencies"]))
                # Potencias de diez: división exacta sin redondeo.
                _require_config(all(re.fullmatch(r"10*", str(d)) for d in divisors.values()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("No se pudo cargar config.json: revise sus campos y reglas.") from exc
    return config


def _reject_constant(value: str) -> None:
    raise ValueError(f"Constante JSON no permitida: {value}")


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Clave JSON repetida: {key}")
        result[key] = value
    return result


def load_json(payload: str | bytes) -> list[Any]:
    """Acepta un array JSON UTF-8; los números decimales nunca pasan por float."""
    try:
        text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload.lstrip("\ufeff")
        if not text.strip():
            raise DataImportError("El archivo está vacío. Cargue un array JSON con transacciones.")
        data = json.loads(text, parse_float=Decimal, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except DataImportError:
        raise
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise DataImportError("JSON malformado o codificación incorrecta. Use un archivo UTF-8 con JSON válido.") from exc
    if not isinstance(data, list):
        raise DataImportError("La raíz del JSON debe ser una lista: [{...}, {...}].")
    if not data:
        raise DataImportError("El archivo contiene una lista vacía; no hay transacciones para procesar.")
    return data


def load_json_file(path: str | Path) -> list[Any]:
    try:
        return load_json(Path(path).read_bytes())
    except OSError as exc:
        raise DataImportError("No se pudo leer el archivo JSON.") from exc


def _text(value: Any, *, upper: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value.upper() if upper else value


def _identifier(value: Any) -> str:
    # Se admiten IDs enteros y strings; nunca booleanos, objetos ni decimales.
    return str(value) if type(value) is int else _text(value)


def _parse_amount(value: Any, currency: str, rule: dict) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("El monto está ausente o no es un número decimal interpretable.")
    if rule["kind"] == "decimal_string" and not isinstance(value, str):
        raise ValueError("Esta fuente requiere el monto como cadena decimal con punto.")
    if isinstance(value, str) and not DECIMAL_PATTERN.fullmatch(value.strip()):
        raise ValueError("El monto debe ser decimal, sin comas ni símbolos de moneda.")
    amount = Decimal(value.strip() if isinstance(value, str) else value)
    if not amount.is_finite():
        raise ValueError("El monto debe ser finito; no se admiten NaN ni infinito.")
    if rule["kind"] == "minor_units":
        if rule.get("integer_only") and amount != amount.to_integral_value():
            raise ValueError("El monto en unidades menores debe ser un número entero.")
        divisor = rule["divisors"].get(currency)
        if divisor is None:
            raise ValueError("No hay regla de unidades menores para esta moneda.")
        # scaleb usa contexto; se amplía para conservar cada dígito.
        with localcontext() as ctx:
            ctx.prec = max(28, len(amount.as_tuple().digits) + len(str(divisor)))
            amount = amount.scaleb(-(len(str(divisor)) - 1))
    return amount


def _parse_date(value: Any, rule: dict) -> str:
    if not isinstance(value, str):
        raise ValueError("La fecha está ausente o no es texto.")
    value = value.strip()
    if rule["kind"] == "date":
        parsed = datetime.strptime(value, rule["format"])
        if parsed.strftime(rule["format"]) != value:
            raise ValueError("La fecha no coincide exactamente con el formato de la fuente.")
        return parsed.date().isoformat()
    # Exige hora, separador T y offset; evita aceptar fechas simples o formatos compactos.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value):
        raise ValueError("La fecha debe ser ISO 8601 con hora, segundos y zona horaria.")
    if re.search(r"[+-]\d{2}:\d{2}$", value):
        offset = value[-5:]
        if int(offset[:2]) > 23 or int(offset[3:]) > 59:
            raise ValueError("La zona horaria es inválida.")
    parsed = datetime.fromisoformat(value)
    if rule.get("require_timezone") and parsed.utcoffset() is None:
        raise ValueError("Esta fuente requiere una zona horaria explícita.")
    return parsed.isoformat()


def normalize_transaction(raw: Any, config: Mapping[str, Any]) -> dict:
    """Normaliza un registro aislado; la validación por lote detecta duplicados."""
    result = {field: "" for field in NORMALIZED_FIELDS[:7]}
    result.update(amount=None, is_valid=False, validation_errors=[])
    errors = result["validation_errors"]
    if not isinstance(raw, dict):
        errors.append("El registro debe ser un objeto JSON con campos de transacción.")
        return validate_batch([result], config)[0]
    result["source"] = _text(raw.get("source"), upper=True)
    rule = config["sources"].get(result["source"])
    if rule is None:
        errors.append("No se pueden interpretar los campos de una fuente desconocida.")
        return validate_batch([result], config)[0]
    fields = rule["fields"]
    result["transaction_id"] = _identifier(raw.get(fields["transaction_id"]))
    result["currency"] = _text(raw.get(fields["currency"]), upper=True)
    result["status"] = rule["status_map"].get(_text(raw.get(fields["status"])).lower(), "")
    result["transaction_type"] = rule["type_map"].get(_text(raw.get(fields["transaction_type"])).lower(), "")
    try:
        result["amount"] = _parse_amount(raw.get(fields["amount"]), result["currency"], rule["amount"])
    except (ValueError, DecimalException, OverflowError) as exc:
        errors.append(f"Monto: {exc}")
    try:
        result["transaction_date"] = _parse_date(raw.get(fields["transaction_date"]), rule["date"])
    except (ValueError, TypeError, OverflowError) as exc:
        errors.append(f"Fecha: formato incompatible o fecha inexistente. {exc}")
    return validate_batch([result], config)[0]


@dataclass
class ProcessingResult:
    """Registros normalizados y originales alineados, sin alterar el esquema."""

    records: list[dict]
    originals: list[Any]

    @property
    def valid(self) -> list[dict]:
        return split_transactions(self.records)[0]

    @property
    def invalid(self) -> list[dict]:
        return split_transactions(self.records)[1]


def process_transactions(raw_records: list[Any], config: Mapping[str, Any]) -> ProcessingResult:
    normalized = [normalize_transaction(raw, config) for raw in raw_records]
    return ProcessingResult(validate_batch(normalized, config), deepcopy(raw_records))
