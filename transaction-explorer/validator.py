"""Reglas de validez independientes de la interfaz y de los proveedores."""

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def validate_transaction(record: Mapping[str, Any], config: Mapping[str, Any]) -> list[str]:
    """Acumula errores sin confundir el estado FAILED con datos inválidos."""
    errors = list(record.get("validation_errors", []))
    if not record.get("transaction_id"):
        errors.append("Falta el identificador de la transacción.")
    if record.get("source") not in config["sources"]:
        errors.append("La fuente no está reconocida en la configuración.")
    amount = record.get("amount")
    if not isinstance(amount, Decimal) or not amount.is_finite():
        errors.append("El monto debe ser un número decimal finito y estar presente.")
    elif amount < 0:
        errors.append("El monto no puede ser negativo.")
    if record.get("currency") not in config["supported_currencies"]:
        errors.append("La moneda no está soportada; consulte config.json.")
    if record.get("status") not in config["normalized_statuses"]:
        errors.append("El estado es desconocido o está ausente.")
    value = record.get("transaction_date")
    try:
        if not isinstance(value, str) or not value:
            raise ValueError
        if "T" in value:
            datetime.fromisoformat(value)
        else:
            date.fromisoformat(value)
    except ValueError:
        errors.append("La fecha es inválida, inexistente o está ausente.")
    if record.get("transaction_type") not in config["normalized_types"]:
        errors.append("El tipo de operación es desconocido o está ausente.")
    return list(dict.fromkeys(errors))


def validate_batch(records: Iterable[dict], config: Mapping[str, Any]) -> list[dict]:
    """Invalida TODAS las apariciones duplicadas del par (fuente, ID)."""
    records = list(records)
    counts = Counter(
        (r["source"], r["transaction_id"]) for r in records if r["transaction_id"]
    )
    result = []
    for record in records:
        errors = validate_transaction(record, config)
        if record["transaction_id"] and counts[(record["source"], record["transaction_id"])] > 1:
            errors.append("Identificador duplicado dentro de la misma fuente.")
        errors = list(dict.fromkeys(errors))
        result.append({**record, "validation_errors": errors, "is_valid": not errors})
    return result


def split_transactions(records: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Devuelve (válidas, inválidas), conservando el orden y los diagnósticos."""
    valid, invalid = [], []
    for record in records:
        (valid if record["is_valid"] else invalid).append(record)
    return valid, invalid
