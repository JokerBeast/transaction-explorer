"""Datos ficticios mínimos compartidos por las pruebas."""

def bank(**changes):
    return {"source": "A", "id": "A-1", "amount": "12.50", "currency": "USD",
            "status": "completed", "date": "2026-01-02", "type": "payment", **changes}


def wallet(**changes):
    return {"source": "B", "transaction_id": "B-1", "value": 12345, "ccy": "EUR",
            "state": "success", "created_at": "02/01/2026", "operation": "topup", **changes}


def processor(**changes):
    return {"source": "C", "reference": "C-1", "total": "0.12345678901234567890123456789",
            "currency_code": "USD", "payment_status": "approved",
            "timestamp": "2026-01-02T08:30:01.123456-06:00", "category": "charge", **changes}
