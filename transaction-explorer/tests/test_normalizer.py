import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from normalizer import (BASE_DIR, NORMALIZED_FIELDS, DataImportError, load_config,
                        load_json, load_json_file, normalize_transaction, process_transactions)
from tests.helpers import bank, processor, wallet


class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_bank_normalization_and_public_schema(self):
        r = normalize_transaction(bank(currency=" usd ", status=" Completed "), self.config)
        self.assertEqual(set(r), set(NORMALIZED_FIELDS))
        self.assertEqual(r["amount"], Decimal("12.50"))
        self.assertIsInstance(r["amount"], Decimal)
        self.assertEqual(r["currency"], "USD")
        self.assertEqual(r["transaction_date"], "2026-01-02")
        self.assertEqual(r["status"], "COMPLETED")
        self.assertEqual(r["transaction_type"], "PAYMENT")
        self.assertTrue(r["is_valid"])

    def test_minor_units_both_currencies(self):
        for currency in ("USD", "EUR"):
            with self.subTest(currency=currency):
                r = normalize_transaction(wallet(ccy=currency), self.config)
                self.assertEqual(r["amount"], Decimal("123.45"))
                self.assertEqual(r["transaction_date"], "2026-01-02")
                self.assertEqual(r["transaction_type"], "DEPOSIT")
                self.assertTrue(r["is_valid"])

    def test_processor_retains_precision_and_timezone(self):
        r = normalize_transaction(processor(), self.config)
        self.assertEqual(r["amount"], Decimal("0.12345678901234567890123456789"))
        self.assertEqual(r["transaction_date"], "2026-01-02T08:30:01.123456-06:00")
        self.assertTrue(r["is_valid"])

    def test_utc_z_is_normalized_to_offset(self):
        r = normalize_transaction(processor(timestamp="2026-01-02T00:00:00Z"), self.config)
        self.assertEqual(r["transaction_date"], "2026-01-02T00:00:00+00:00")

    def test_all_state_maps(self):
        for factory, field, pairs in (
            (bank, "status", [("completed", "COMPLETED"), ("pending", "PENDING"), ("failed", "FAILED")]),
            (wallet, "state", [("success", "COMPLETED"), ("processing", "PENDING"), ("error", "FAILED")]),
            (processor, "payment_status", [("approved", "COMPLETED"), ("waiting", "PENDING"), ("rejected", "FAILED")]),
        ):
            for raw, expected in pairs:
                with self.subTest(field=field, raw=raw):
                    r = normalize_transaction(factory(**{field: raw}), self.config)
                    self.assertEqual(r["status"], expected)
                    self.assertTrue(r["is_valid"])

    def test_all_type_maps(self):
        for factory, field, values in (
            (bank, "type", ["deposit", "withdrawal", "payment"]),
            (wallet, "operation", ["topup", "cashout", "purchase"]),
            (processor, "category", ["credit", "debit", "charge"]),
        ):
            for value, expected in zip(values, ["DEPOSIT", "WITHDRAWAL", "PAYMENT"]):
                with self.subTest(value=value):
                    self.assertEqual(normalize_transaction(factory(**{field: value}), self.config)["transaction_type"], expected)

    def test_dates_reject_impossible_or_incompatible_formats(self):
        for raw in (bank(date="2026-02-29"), bank(date="2026-1-02"),
                    bank(date="02/01/2026"), wallet(created_at="31/04/2026"),
                    wallet(created_at="2026-01-02"), processor(timestamp="2026-01-02"),
                    processor(timestamp="2026-01-02T00:00:00"),
                    processor(timestamp="2026-01-02T00:00:00+01:99"),
                    processor(timestamp="2026-02-30T00:00:00Z")):
            with self.subTest(raw=raw):
                r = normalize_transaction(raw, self.config)
                self.assertFalse(r["is_valid"])
                self.assertTrue(any("fecha" in e.lower() for e in r["validation_errors"]))

    def test_leap_date_preserves_date_only(self):
        for raw in (bank(date="2024-02-29"), wallet(created_at="29/02/2024")):
            r = normalize_transaction(raw, self.config)
            self.assertTrue(r["is_valid"])
            self.assertEqual(r["transaction_date"], "2024-02-29")

    def test_invalid_amounts_do_not_stop_batch(self):
        bad = [None, True, [], {}, "abc", "12,30", "NaN", "Infinity", "1_000", 0.1]
        result = process_transactions([bank(id=f"X-{i}", amount=v) for i, v in enumerate(bad)] + [bank()], self.config)
        self.assertEqual(len(result.invalid), len(bad))
        self.assertEqual(len(result.valid), 1)

    def test_provider_amount_rules_are_enforced(self):
        for raw in (wallet(value="1.5"), wallet(ccy="GBP"), processor(total=12)):
            self.assertFalse(normalize_transaction(raw, self.config)["is_valid"])

    def test_long_minor_units_are_exact(self):
        value = 1234567890123456789012345678901
        r = normalize_transaction(wallet(value=value), self.config)
        self.assertEqual(r["amount"], Decimal("12345678901234567890123456789.01"))

    def test_external_configuration_is_actually_used(self):
        config = copy.deepcopy(self.config)
        config["sources"]["A"]["fields"]["amount"] = "custom_amount"
        config["sources"]["A"]["type_map"]["transfer"] = "DEPOSIT"
        config["sources"]["A"]["date"]["format"] = "%d.%m.%Y"
        with patch.object(Path, "read_text", return_value=json.dumps(config)):
            config = load_config()
        r = normalize_transaction(bank(custom_amount="8.01", type="transfer", date="02.01.2026"), config)
        self.assertEqual(r["amount"], Decimal("8.01"))
        self.assertEqual(r["transaction_type"], "DEPOSIT")
        self.assertTrue(r["is_valid"])

    def test_bad_configuration_is_reported(self):
        with patch.object(Path, "read_text", return_value='{"sources": []}'):
            with self.assertRaisesRegex(ValueError, "config.json"):
                load_config()

    def test_json_parsing_never_uses_float(self):
        values = load_json('[{"amount": 0.12345678901234567890123456789}]')
        self.assertEqual(values[0]["amount"], Decimal("0.12345678901234567890123456789"))
        self.assertIsInstance(values[0]["amount"], Decimal)

    def test_empty_malformed_and_wrong_root_json(self):
        for payload in ("", "   ", "[]", "{}", "null", "[", "[{bad}]", b"\xff", '[NaN]',
                        '[Infinity]', '[{"id": "one", "id": "two"}]'):
            with self.subTest(payload=payload), self.assertRaises(DataImportError):
                load_json(payload)

    def test_bom_and_non_object_entries(self):
        raw = load_json(b'\xef\xbb\xbf[null, 42, [], "bad", {"source": "A"}]')
        result = process_transactions(raw, self.config)
        self.assertEqual(len(result.invalid), 5)
        self.assertEqual(result.originals, raw)

    def test_originals_are_preserved_independently(self):
        raw = [bank(currency=" usd ")]
        result = process_transactions(raw, self.config)
        raw[0]["currency"] = "EUR"
        self.assertEqual(result.originals[0]["currency"], " usd ")
        self.assertEqual(result.records[0]["currency"], "USD")

    def test_sample_dataset(self):
        result = process_transactions(load_json_file(BASE_DIR / "data" / "sample_transactions.json"), self.config)
        self.assertEqual(len(result.records), 40)
        self.assertEqual(len(result.valid), 23)
        self.assertEqual(len(result.invalid), 17)
        self.assertEqual({r["source"] for r in result.valid}, {"A", "B", "C"})

    def test_missing_file_is_readable_error(self):
        with self.assertRaises(DataImportError):
            load_json_file(BASE_DIR / "data" / "does_not_exist.json")
