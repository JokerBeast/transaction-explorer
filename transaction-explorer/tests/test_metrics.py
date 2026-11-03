import unittest
from decimal import Decimal, localcontext

from metrics import calculate_metrics, exact_sum, format_amount
from normalizer import load_config, process_transactions
from tests.helpers import bank, wallet


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_metrics_scope_and_separate_currencies(self):
        result = process_transactions([
            bank(id="A-1", amount="0.10"),
            bank(id="A-2", amount="0.20", status="pending"),
            wallet(value=10000, state="error", operation="cashout"),
            bank(id="A-3", amount="999999", date="bad"),
        ], self.config)
        m = calculate_metrics(result.records)
        self.assertEqual((m["total"], m["valid"], m["invalid"]), (4, 3, 1))
        self.assertEqual(m["valid_percentage"], Decimal("75"))
        self.assertEqual(m["by_source"], {"A": 3, "B": 1})
        self.assertEqual(m["by_status"], {"COMPLETED": 1, "PENDING": 1, "FAILED": 1})
        self.assertEqual(m["by_type"], {"PAYMENT": 2, "WITHDRAWAL": 1})
        self.assertEqual(m["totals_by_currency"], {"USD": Decimal("0.30"), "EUR": Decimal("100")})

    def test_no_records_no_division_by_zero(self):
        m = calculate_metrics([])
        self.assertEqual((m["total"], m["valid"], m["invalid"]), (0, 0, 0))
        self.assertEqual(m["valid_percentage"], Decimal("0"))
        self.assertEqual(m["totals_by_currency"], {})

    def test_only_invalid_records_never_add_amounts(self):
        result = process_transactions([bank(amount=-5), {"source": "X"}, None], self.config)
        m = calculate_metrics(result.records)
        self.assertEqual(m["valid"], 0)
        self.assertEqual(m["by_source"], {"A": 1, "X": 1, "SIN FUENTE": 1})
        self.assertEqual(m["by_status"], {})
        self.assertEqual(m["by_type"], {})
        self.assertEqual(m["totals_by_currency"], {})

    def test_duplicate_amounts_are_excluded(self):
        result = process_transactions([bank(), bank(), wallet(value=100)], self.config)
        self.assertEqual(calculate_metrics(result.records)["totals_by_currency"], {"EUR": Decimal("1")})

    def test_sum_keeps_precision_beyond_default_context(self):
        large = Decimal("123456789012345678901234567890.12")
        tiny = Decimal("0.00000000000000000000000000001")
        with localcontext() as ctx:
            ctx.prec = 6
            self.assertEqual(exact_sum([large, tiny]), Decimal("123456789012345678901234567890.12000000000000000000000000001"))
        self.assertEqual(exact_sum([]), Decimal("0"))

    def test_two_decimals_are_display_only(self):
        original = Decimal("10.125")
        self.assertEqual(format_amount(original), "10.13")
        self.assertEqual(original, Decimal("10.125"))
        self.assertEqual(format_amount(Decimal("0")), "0.00")
        self.assertEqual(format_amount(None), "—")
