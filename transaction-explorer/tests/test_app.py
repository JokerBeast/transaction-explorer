"""Integración Streamlit; se omite explícitamente si faltan sus dependencias."""

import csv
import importlib.util
import io
import unittest
from decimal import Decimal

from normalizer import BASE_DIR, load_config, process_transactions
from tests.helpers import bank, wallet

HAS_UI = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "pandas"))


@unittest.skipUnless(HAS_UI, "Faltan Streamlit/Pandas: instale requirements.txt para verificar la interfaz.")
class AppTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.app = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=20).run()
        self.assertFalse(self.app.exception)

    def test_dashboard_and_navigation(self):
        self.assertEqual([self.app.metric[i].value for i in range(4)], ["40", "23", "17", "57.5%"])
        for page in ["Explorador de transacciones", "Registros inválidos", "Importación de datos", "Dashboard"]:
            self.app.sidebar.radio[0].set_value(page).run()
            self.assertFalse(self.app.exception)

    def test_combined_filters_and_empty_selection(self):
        self.app.sidebar.radio[0].set_value("Explorador de transacciones").run()
        self.app.multiselect(key="filter_source").set_value(["A"]).run()
        self.app.multiselect(key="filter_currency").set_value(["USD"]).run()
        self.app.radio(key="validity").set_value("Válidas").run()
        self.assertFalse(self.app.exception)
        frame = self.app.dataframe[0].value
        self.assertEqual(set(frame["source"]), {"A"})
        self.assertEqual(set(frame["currency"]), {"USD"})
        self.assertTrue(all(frame["is_valid"]))
        self.app.multiselect(key="filter_source").set_value([]).run()
        self.assertTrue(any("No hay registros" in item.value for item in self.app.info))
        self.assertFalse(self.app.exception)

    def test_invalid_inspection(self):
        self.app.sidebar.radio[0].set_value("Registros inválidos").run()
        self.assertEqual(len(self.app.dataframe[0].value), 17)
        self.assertTrue(self.app.error)
        self.assertEqual(len(self.app.code), 2)
        self.assertFalse(self.app.exception)

    def test_empty_dataset_pages(self):
        self.app.session_state["raw_records"] = []
        for page in ["Dashboard", "Explorador de transacciones", "Registros inválidos", "Importación de datos"]:
            self.app.sidebar.radio[0].set_value(page).run()
            self.assertFalse(self.app.exception)

    def test_csv_exact_values_and_original_diagnostics(self):
        from app import export_csv
        result = process_transactions([bank(amount="10.123456789"), wallet(value=-1)], load_config())
        valid = list(csv.DictReader(io.StringIO(export_csv(result, valid=True).decode("utf-8-sig"))))
        invalid = list(csv.DictReader(io.StringIO(export_csv(result, valid=False).decode("utf-8-sig"))))
        self.assertEqual(len(valid), 1)
        self.assertEqual(Decimal(valid[0]["amount"]), Decimal("10.123456789"))
        self.assertNotIn("original_data", valid[0])
        self.assertEqual(len(invalid), 1)
        self.assertIn('"value": -1', invalid[0]["original_data"])
        self.assertIn("negativo", invalid[0]["validation_errors"])
