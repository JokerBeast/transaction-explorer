"""Agregaciones exactas: conteos generales y métricas financieras válidas."""

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Iterable


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    """Suma exacta incluso si los importes superan la precisión Decimal usual."""
    values = list(values)
    if not values:
        return Decimal("0")
    smallest_exponent = min(v.as_tuple().exponent for v in values)
    highest_position = max(v.adjusted() for v in values)
    with localcontext() as ctx:
        ctx.prec = max(28, highest_position - smallest_exponent + len(str(len(values))) + 2)
        return sum(values, Decimal("0"))


def format_amount(value: Decimal | None) -> str:
    """Redondeo solo visual a dos decimales (mitades hacia arriba)."""
    if value is None:
        return "—"
    with localcontext() as ctx:
        ctx.prec = max(28, len(value.as_tuple().digits) + 2, value.adjusted() + 4)
        return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def calculate_metrics(records: Iterable[dict]) -> dict:
    records = list(records)
    valid = [r for r in records if r["is_valid"]]
    currencies = sorted({r["currency"] for r in valid})
    with localcontext() as ctx:
        ctx.prec = 28
        percentage = Decimal(len(valid)) * 100 / Decimal(len(records)) if records else Decimal("0")
    return {
        "total": len(records),
        "valid": len(valid),
        "invalid": len(records) - len(valid),
        "valid_percentage": percentage,
        "by_source": dict(Counter(r["source"] or "SIN FUENTE" for r in records)),
        "by_status": dict(Counter(r["status"] for r in valid)),
        "by_type": dict(Counter(r["transaction_type"] for r in valid)),
        "totals_by_currency": {
            currency: exact_sum(r["amount"] for r in valid if r["currency"] == currency)
            for currency in currencies
        },
    }
