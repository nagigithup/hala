import json
from pathlib import Path
from unittest import TestCase


class TestHalaPrintFormatSources(TestCase):
	def test_hala_owns_only_booking_and_a4_sales_formats(self):
		app = Path(__file__).resolve().parents[1]
		fixture = json.loads((app / "fixtures/print_format.json").read_text())
		self.assertEqual(
			{fmt["name"] for fmt in fixture if fmt.get("doc_type") == "Sales Invoice"},
			{"BOOKING", "فاتورة مبيعات A4"},
		)
		self.assertNotIn("POS Next Receipt", [fmt["name"] for fmt in fixture])
