import unittest
from decimal import Decimal

from normalizer import load_config, normalize_transaction, process_transactions
from validator import split_transactions, validate_transaction
from tests.helpers import bank, wallet


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_negative_invalid_zero_valid(self):
        negative = normalize_transaction(bank(amount="-0.01"), self.config)
        self.assertFalse(negative["is_valid"])
        self.assertIn("El monto no puede ser negativo.", negative["validation_errors"])
        self.assertTrue(normalize_transaction(bank(amount=0), self.config)["is_valid"])

    def test_all_required_fields_are_checked(self):
        for field in ("id", "amount", "currency", "status", "date", "type", "source"):
            raw = bank()
            raw.pop(field)
            with self.subTest(field=field):
                r = normalize_transaction(raw, self.config)
                self.assertFalse(r["is_valid"])
                self.assertTrue(r["validation_errors"])

    def test_unknown_categories_and_source(self):
        for changes in ({"source": "Z"}, {"currency": "GBP"}, {"status": "mystery"}, {"type": "refund"}):
            with self.subTest(changes=changes):
                self.assertFalse(normalize_transaction(bank(**changes), self.config)["is_valid"])

    def test_all_errors_accumulate(self):
        r = normalize_transaction(bank(id=" ", amount=-1, currency="XXX", status="unknown",
                                       date="impossible", type="unknown"), self.config)
        self.assertGreaterEqual(len(r["validation_errors"]), 6)
        self.assertFalse(r["is_valid"])

    def test_duplicates_invalidate_all_occurrences(self):
        result = process_transactions([bank(), bank(amount=7), bank(id="A-2")], self.config)
        self.assertEqual([r["is_valid"] for r in result.records], [False, False, True])
        for r in result.invalid:
            self.assertTrue(any("duplicado" in e for e in r["validation_errors"]))

    def test_same_id_in_different_sources_is_allowed(self):
        result = process_transactions([bank(id="SAME"), wallet(transaction_id="SAME")], self.config)
        self.assertEqual(len(result.valid), 2)

    def test_duplicate_after_trimming_source_and_id(self):
        result = process_transactions([bank(id=" A-1 ", source=" a "), bank()], self.config)
        self.assertEqual(len(result.invalid), 2)

    def test_failed_state_can_be_valid(self):
        r = normalize_transaction(bank(status="failed"), self.config)
        self.assertEqual(r["status"], "FAILED")
        self.assertTrue(r["is_valid"])
        self.assertEqual(r["validation_errors"], [])

    def test_split_preserves_every_record(self):
        result = process_transactions([bank(), None, bank(id="A-2", amount=-1)], self.config)
        valid, invalid = split_transactions(result.records)
        self.assertEqual(len(valid) + len(invalid), 3)
        self.assertEqual(valid, result.valid)
        self.assertEqual(invalid, result.invalid)

    def test_numeric_identifier_supported_boolean_not_supported(self):
        self.assertEqual(normalize_transaction(bank(id=0), self.config)["transaction_id"], "0")
        self.assertTrue(normalize_transaction(bank(id=0), self.config)["is_valid"])
        self.assertFalse(normalize_transaction(bank(id=True), self.config)["is_valid"])

    def test_independent_validator_rejects_non_finite_amounts(self):
        r = normalize_transaction(bank(), self.config)
        for value in (Decimal("NaN"), Decimal("Infinity"), "10", None):
            with self.subTest(value=value):
                errors = validate_transaction({**r, "amount": value}, self.config)
                self.assertTrue(any("monto" in e for e in errors))
