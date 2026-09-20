import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.utils import get_stock_balance

from hala.access import PORTAL_ROLE
from hala.api.quick_manufacturing import get_context, manufacture, preview


COMPANY = "_Test Company"
SOURCE_WAREHOUSE = "_Test Warehouse - _TC"
TARGET_WAREHOUSE = "_Test Warehouse 1 - _TC"


def make_test_item(item_code, stock_uom="Kg", valuation_rate=0, uoms=None):
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"description": item_code,
			"item_group": "Products",
			"is_stock_item": 1,
			"stock_uom": stock_uom,
			"valuation_rate": valuation_rate,
		}
	)
	for row in uoms or []:
		item.append("uoms", row)
	item.insert()
	return item


class TestQuickManufacturing(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def make_recipe(self):
		suffix = frappe.generate_hash(length=8)
		raw_material = make_test_item(
			f"_Test Hala QM RM {suffix}",
			stock_uom="Kg",
			valuation_rate=10,
			uoms=[{"uom": "Gram", "conversion_factor": 0.001}],
		)
		finished_item = make_test_item(
			f"_Test Hala QM FG {suffix}",
		)

		bom = frappe.new_doc("BOM")
		bom.update(
			{
				"item": finished_item.name,
				"company": COMPANY,
				"quantity": 1,
				"is_active": 1,
				"is_default": 1,
				"rm_cost_as_per": "Valuation Rate",
			}
		)
		bom.append(
			"items",
			{
				"item_code": raw_material.name,
				"qty": 300,
				"uom": "Gram",
				"stock_uom": "Kg",
				"conversion_factor": 0.001,
				"stock_qty": 0.3,
				"rate": 10,
			},
		)
		bom.insert()
		bom.submit()

		make_stock_entry(
			item_code=raw_material.name,
			to_warehouse=SOURCE_WAREHOUSE,
			qty=20,
			rate=10,
			company=COMPANY,
		)
		return raw_material, finished_item, bom

	def test_complete_manufacturing_flow_uses_standard_stock_entry(self):
		raw_material, finished_item, bom = self.make_recipe()
		context = get_context(item_code=finished_item.name)
		self.assertEqual(context["bom_no"], bom.name)
		self.assertEqual(context["finished_uom"], "Kg")

		five_kg = preview(
			finished_item.name,
			bom.name,
			5,
			SOURCE_WAREHOUSE,
			TARGET_WAREHOUSE,
		)
		self.assertFalse(five_kg["blocking_shortage"])
		self.assertEqual(five_kg["raw_materials_count"], 1)
		component = five_kg["components"][0]
		self.assertEqual(component["uom"], "Gram")
		self.assertEqual(component["stock_uom"], "Kg")
		self.assertAlmostEqual(component["required_qty"], 1500)
		self.assertAlmostEqual(component["required_stock_qty"], 1.5)
		self.assertAlmostEqual(component["available_qty"], 20)

		raw_before = get_stock_balance(raw_material.name, SOURCE_WAREHOUSE)
		finished_before = get_stock_balance(finished_item.name, TARGET_WAREHOUSE)
		entries = []
		for index, quantity in enumerate((1, 5, 0.5), start=1):
			request_id = f"hala-qm-{frappe.generate_hash(length=20)}-{index}"
			result = manufacture(
				finished_item.name,
				bom.name,
				quantity,
				SOURCE_WAREHOUSE,
				TARGET_WAREHOUSE,
				request_id,
				remarks="Hala quick manufacturing integration test",
			)
			self.assertFalse(result["duplicate_request"])
			stock_entry = frappe.get_doc("Stock Entry", result["stock_entry"])
			entries.append(stock_entry)
			self.assertEqual(stock_entry.docstatus, 1)
			self.assertEqual(stock_entry.purpose, "Manufacture")
			self.assertEqual(stock_entry.stock_entry_type, "Manufacture")
			self.assertEqual(stock_entry.bom_no, bom.name)
			self.assertAlmostEqual(stock_entry.fg_completed_qty, quantity)
			self.assertEqual(stock_entry.get("work_order"), None)
			self.assertEqual(stock_entry.custom_hala_manufacturing_request_id, request_id)
			self.assertTrue(any(row.s_warehouse == SOURCE_WAREHOUSE for row in stock_entry.items))
			self.assertTrue(any(row.t_warehouse == TARGET_WAREHOUSE for row in stock_entry.items))

			ledger_rows = frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_type": "Stock Entry", "voucher_no": stock_entry.name, "is_cancelled": 0},
				fields=["item_code", "actual_qty", "valuation_rate", "stock_value_difference"],
			)
			self.assertGreaterEqual(len(ledger_rows), 2)
			finished_ledger_row = next(
				row for row in ledger_rows if row.item_code == finished_item.name and row.actual_qty > 0
			)
			self.assertGreater(flt(finished_ledger_row.valuation_rate), 0)
			self.assertGreater(flt(finished_ledger_row.stock_value_difference), 0)
			self.assertTrue(any(row.item_code == raw_material.name and row.actual_qty < 0 for row in ledger_rows))

			if quantity == 1:
				duplicate = manufacture(
					finished_item.name,
					bom.name,
					quantity,
					SOURCE_WAREHOUSE,
					TARGET_WAREHOUSE,
					request_id,
				)
				self.assertTrue(duplicate["duplicate_request"])
				self.assertEqual(duplicate["stock_entry"], stock_entry.name)

		self.assertAlmostEqual(get_stock_balance(raw_material.name, SOURCE_WAREHOUSE), raw_before - 1.95)
		self.assertAlmostEqual(get_stock_balance(finished_item.name, TARGET_WAREHOUSE), finished_before + 6.5)

		entries[-1].cancel()
		self.assertAlmostEqual(get_stock_balance(raw_material.name, SOURCE_WAREHOUSE), raw_before - 1.8)
		self.assertAlmostEqual(get_stock_balance(finished_item.name, TARGET_WAREHOUSE), finished_before + 6)

		shortage = preview(
			finished_item.name,
			bom.name,
			1000,
			SOURCE_WAREHOUSE,
			TARGET_WAREHOUSE,
		)
		self.assertTrue(shortage["blocking_shortage"])
		self.assertGreater(shortage["components"][0]["shortage"], 0)
		with self.assertRaises(frappe.ValidationError):
			manufacture(
				finished_item.name,
				bom.name,
				1000,
				SOURCE_WAREHOUSE,
				TARGET_WAREHOUSE,
				f"hala-qm-{frappe.generate_hash(length=20)}",
			)

	def test_portal_role_alone_does_not_grant_manufacturing_permissions(self):
		user_email = f"hala-qm-{frappe.generate_hash(length=8)}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": user_email,
				"first_name": "Hala Quick Manufacturing Test",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles(PORTAL_ROLE)
		try:
			frappe.set_user(user_email)
			with self.assertRaises(frappe.PermissionError):
				get_context()
		finally:
			frappe.set_user("Administrator")

	def test_missing_bom_returns_an_empty_selection(self):
		item = make_test_item(
			f"_Test Hala QM No BOM {frappe.generate_hash(length=8)}",
		)
		context = get_context(item_code=item.name)
		self.assertIsNone(context["bom_no"])
		self.assertEqual(context["boms"], [])
