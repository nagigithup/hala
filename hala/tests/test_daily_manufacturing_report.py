import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate, now_datetime

from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry as make_work_order_entry

from hala.api.quick_manufacturing import manufacture
from hala.hala.report.daily_manufacturing_report.daily_manufacturing_report import execute
from hala.tests import test_quick_manufacturing as quick_manufacturing_test


COMPANY = quick_manufacturing_test.COMPANY
SOURCE_WAREHOUSE = quick_manufacturing_test.SOURCE_WAREHOUSE
TARGET_WAREHOUSE = quick_manufacturing_test.TARGET_WAREHOUSE


class TestDailyManufacturingReport(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_quick_and_work_order_manufacturing_are_reported(self):
		raw_material, finished_item, bom = quick_manufacturing_test.TestQuickManufacturing.make_recipe()
		quick_result = manufacture(
			finished_item.name,
			bom.name,
			1,
			SOURCE_WAREHOUSE,
			TARGET_WAREHOUSE,
			f"hala-report-{frappe.generate_hash(length=20)}",
		)

		work_order = frappe.new_doc("Work Order")
		work_order.update(
			{
				"production_item": finished_item.name,
				"bom_no": bom.name,
				"qty": 2,
				"company": COMPANY,
				"stock_uom": "Kg",
				"source_warehouse": SOURCE_WAREHOUSE,
				"wip_warehouse": SOURCE_WAREHOUSE,
				"fg_warehouse": TARGET_WAREHOUSE,
				"skip_transfer": 1,
				"planned_start_date": now_datetime(),
				"transfer_material_against": "Work Order",
			}
		)
		work_order.get_items_and_operations_from_bom()
		for row in work_order.required_items:
			row.source_warehouse = SOURCE_WAREHOUSE
		work_order.insert()
		work_order.submit()

		standard_entry = frappe.get_doc(make_work_order_entry(work_order.name, "Manufacture", qty=2))
		standard_entry.insert()
		standard_entry.submit()
		cancelled_result = manufacture(
			finished_item.name,
			bom.name,
			0.5,
			SOURCE_WAREHOUSE,
			TARGET_WAREHOUSE,
			f"hala-report-cancelled-{frappe.generate_hash(length=20)}",
		)
		frappe.get_doc("Stock Entry", cancelled_result["stock_entry"]).cancel()

		columns, data, message, chart, summary = execute(
			{
				"from_date": nowdate(),
				"to_date": nowdate(),
				"company": COMPANY,
			}
		)
		self.assertIsNone(chart)
		self.assertTrue(any(column["fieldname"] == "stock_entry" for column in columns))
		parent_rows = [row for row in data if row["indent"] == 0]
		child_rows = [row for row in data if row["indent"] == 1]
		self.assertEqual({row["stock_entry"] for row in parent_rows}, {quick_result["stock_entry"], standard_entry.name})
		self.assertEqual(len(child_rows), 2)
		self.assertTrue(all(row["raw_material_item"] == raw_material.name for row in child_rows))
		self.assertTrue(all(row["source_warehouse"] == SOURCE_WAREHOUSE for row in child_rows))
		self.assertCountEqual([row["consumed_qty"] for row in child_rows], [0.3, 0.6])
		self.assertCountEqual([row["consumed_value"] for row in child_rows], [3, 6])

		quick_row = next(row for row in parent_rows if row["stock_entry"] == quick_result["stock_entry"])
		standard_row = next(row for row in parent_rows if row["stock_entry"] == standard_entry.name)
		self.assertEqual(quick_row["work_order"], None)
		self.assertEqual(standard_row["work_order"], work_order.name)
		self.assertEqual(standard_row["finished_item"], finished_item.name)
		self.assertAlmostEqual(quick_row["manufactured_qty"], 1)
		self.assertAlmostEqual(standard_row["manufactured_qty"], 2)
		self.assertGreater(quick_row["finished_goods_value"], 0)
		self.assertGreater(standard_row["finished_goods_value"], 0)

		summary_by_label = {row["label"]: row["value"] for row in summary}
		self.assertEqual(summary_by_label["Manufacturing Entries"], 2)
		self.assertAlmostEqual(summary_by_label["Total Finished Goods Qty"], 3)
		self.assertEqual(summary_by_label["Different Finished Items"], 1)
		self.assertAlmostEqual(summary_by_label["Total Raw Material Consumption Value"], 9)
		self.assertAlmostEqual(summary_by_label["Total Finished Goods Value"], 9)
		self.assertIn(finished_item.name, message)
		self.assertIn("3", message)

		for filter_name, filter_value in (
			("finished_item", finished_item.name),
			("bom", bom.name),
			("source_warehouse", SOURCE_WAREHOUSE),
			("target_warehouse", TARGET_WAREHOUSE),
		):
			filtered = execute(
				{
					"from_date": nowdate(),
					"to_date": nowdate(),
					"company": COMPANY,
					filter_name: filter_value,
				}
			)[1]
			self.assertEqual(len([row for row in filtered if row["indent"] == 0]), 2)

	def test_invalid_date_range_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"from_date": "2026-09-21", "to_date": "2026-09-20"})
