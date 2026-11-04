"""Native purchase accounting/stock checks on the dedicated isolated Hala test site."""

import unittest
from uuid import uuid4

import frappe
from frappe.utils import nowdate

from hala.api import quick_purchase as api
from hala.tests import test_disbursement as fixture


class TestQuickPurchase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		fixture.TestDisbursement.setUpClass()
		frappe.set_user("Administrator")
		from hala.setup import ensure_quick_purchase_fields

		ensure_quick_purchase_fields()
		for unit in ["Gram", "Kg"]:
			if not frappe.db.exists("UOM", unit):
				frappe.get_doc(dict(doctype="UOM", uom_name=unit)).insert()
		if not frappe.db.exists("Price List", "HDT Buying"):
			frappe.get_doc(
				dict(doctype="Price List", price_list_name="HDT Buying", buying=1, currency="SAR")
			).insert()
		frappe.db.set_single_value("Buying Settings", "buying_price_list", "HDT Buying")
		if not frappe.db.exists("Item", "HDT Purchase Sugar"):
			frappe.get_doc(
				dict(
					doctype="Item",
					item_code="HDT Purchase Sugar",
					item_name="سكر شراء",
					item_group="HDT Items",
					stock_uom="Gram",
					purchase_uom="Kg",
					is_stock_item=1,
					uoms=[dict(uom="Gram", conversion_factor=1), dict(uom="Kg", conversion_factor=1000)],
					barcodes=[dict(barcode="HDT-SUGAR-1000", uom="Kg")],
				)
			).insert()
		for user, roles in [
			("hdt-purchase@example.test", ["Purchase Manager", "Accounts User"]),
			("hdt-purchase-read@example.test", ["Purchase Manager"]),
		]:
			if not frappe.db.exists("User", user):
				frappe.get_doc(
					dict(
						doctype="User",
						email=user,
						first_name=user.split("@")[0],
						send_welcome_email=0,
						roles=[dict(role=role) for role in roles],
					)
				).insert()
		# Workflow fields are schema, so prepare before transaction savepoints.
		fixture.TestDisbursement.workflow("Purchase Invoice")
		frappe.db.set_value("Workflow", "HDT Purchase Invoice", "is_active", 0)
		frappe.clear_cache()
		frappe.db.commit()

	def setUp(self):
		self.base = fixture.TestDisbursement()
		self.base.setUp()

	def tearDown(self):
		self.base.tearDown()

	def native_invoice(self, paid=False, stock=False, bank=False):
		b = self.base
		doc = frappe.get_doc(
			dict(
				doctype="Purchase Invoice",
				company=b.company.name,
				supplier="HDT Supplier",
				posting_date=nowdate(),
				due_date=nowdate(),
				currency="SAR",
				buying_price_list="HDT Buying",
				is_paid=int(paid),
				update_stock=int(stock),
				custom_hala_quick_purchase=1,
				custom_hala_purchase_request_id=uuid4().hex,
				disable_rounded_total=1,
				mode_of_payment="HDT Bank" if bank else "HDT Cash" if paid else None,
				cash_bank_account=b.bank if bank else b.cash if paid else None,
				items=[
					dict(
						item_code="HDT Purchase Sugar",
						qty=5,
						uom="Kg",
						conversion_factor=1000,
						rate=25,
						price_list_rate=25,
						warehouse=b.warehouse,
						expense_account=b.expense,
						cost_center=b.cost_center,
					)
				],
			)
		)
		doc.set_missing_values()
		doc.set_taxes()
		doc.calculate_taxes_and_totals()
		if paid:
			doc.paid_amount = doc.grand_total
			doc.base_paid_amount = doc.base_grand_total
			doc.calculate_taxes_and_totals()
		return doc

	def test_new_native_checkboxes_default_unchecked(self):
		doc = frappe.new_doc("Purchase Invoice")
		self.assertFalse(doc.update_stock)
		self.assertFalse(doc.is_paid)

	def test_all_four_independent_combinations_and_exactly_one_native_movement(self):
		for paid, stock in [(False, False), (True, False), (False, True), (True, True)]:
			with self.subTest(paid=paid, stock=stock):
				frappe.db.savepoint("four_combinations")
				counts = {
					dt: frappe.db.count(dt)
					for dt in ["Payment Entry", "Journal Entry", "Purchase Receipt", "Stock Entry"]
				}
				doc = self.native_invoice(paid, stock)
				doc.insert()
				self.assertFalse(
					frappe.db.exists("GL Entry", dict(voucher_no=doc.name, voucher_type="Purchase Invoice"))
				)
				doc.submit()
				doc.reload()
				self.assertEqual(doc.is_paid, int(paid))
				self.assertEqual(doc.update_stock, int(stock))
				self.assertEqual(doc.items[0].stock_qty, 5000)
				self.assertEqual(doc.grand_total, 125)
				self.assertEqual(doc.outstanding_amount, 0 if paid else 125)
				self.assertEqual(self.base.gl(doc, self.base.cash), -125 if paid else 0)
				stock_rows = frappe.get_all(
					"Stock Ledger Entry",
					filters=dict(voucher_type="Purchase Invoice", voucher_no=doc.name, is_cancelled=0),
					fields=["actual_qty", "stock_value_difference"],
				)
				self.assertEqual(sum(r.actual_qty for r in stock_rows), 5000 if stock else 0)
				self.assertAlmostEqual(sum(r.stock_value_difference for r in stock_rows), 125 if stock else 0)
				self.assertEqual(self.base.cash_expected(), 375 if paid else 500)
				for dt, count in counts.items():
					self.assertEqual(frappe.db.count(dt), count, dt)
				frappe.db.rollback(save_point="four_combinations")
				frappe.clear_cache()

	def test_bank_payment_has_no_physical_drawer_outflow(self):
		doc = self.native_invoice(True, False, True)
		doc.insert()
		doc.submit()
		self.assertEqual(self.base.gl(doc, self.base.bank), -125)
		self.assertFalse(doc.custom_hala_purchase_shift)
		self.assertEqual(self.base.cash_expected(), 500)

	def test_paid_stock_cancellation_reverses_native_inventory_and_cash(self):
		doc = self.native_invoice(True, True)
		doc.insert()
		doc.submit()
		self.assertEqual(self.base.cash_expected(), 375)
		doc.cancel()
		self.assertEqual(self.base.cash_expected(), 500)
		self.assertEqual(
			frappe.db.get_value(
				"Bin", dict(item_code="HDT Purchase Sugar", warehouse=self.base.warehouse), "actual_qty"
			),
			0,
		)

	def test_draft_does_not_move_money_or_stock(self):
		doc = self.native_invoice(True, True)
		doc.insert()
		self.assertEqual(self.base.cash_expected(), 500)
		self.assertFalse(
			frappe.db.exists("GL Entry", dict(voucher_type="Purchase Invoice", voucher_no=doc.name))
		)
		self.assertFalse(
			frappe.db.exists("Stock Ledger Entry", dict(voucher_type="Purchase Invoice", voucher_no=doc.name))
		)

	def test_configured_uoms_barcode_and_rate_precision(self):
		units = api.get_item_uoms("HDT Purchase Sugar")
		self.assertEqual(units["purchase_uom"], "Kg")
		self.assertEqual(units["uoms"], {"Gram": 1, "Kg": 1000})
		from erpnext.stock.get_item_details import get_item_code

		self.assertEqual(get_item_code(barcode="HDT-SUGAR-1000"), "HDT Purchase Sugar")
		self.assertEqual(api.derive_rate("5", "125", "SAR")["rate"], 25)
		self.assertEqual(api.derive_rate("0.5", "12.5", "SAR")["rate"], 25)
		with self.assertRaises(frappe.ValidationError):
			api.derive_rate("3", "100", "SAR")
		for quantity, total in [(0, 10), (-1, 10), (1, "nan"), (1, -1), (1000000, "0.01")]:
			with self.assertRaises(frappe.ValidationError):
				api.derive_rate(quantity, total, "SAR")

	def test_native_permissions_and_feature_role(self):
		frappe.set_user("hdt-purchase@example.test")
		api.require_access("create")
		frappe.set_user("hdt-cashier@example.test")
		for endpoint, args in [
			(api.get_context, ()),
			(api.get_history, ()),
			(api.get_item_uoms, ("HDT Purchase Sugar",)),
			(api.derive_rate, (5, 125)),
		]:
			with self.assertRaises(frappe.PermissionError):
				endpoint(*args)
		frappe.set_user("hdt-purchase-read@example.test")
		with self.assertRaises(frappe.PermissionError):
			api.require_access("create")

	def test_native_stock_and_uom_validation_not_bypassed(self):
		doc = self.native_invoice(False, True)
		doc.items[0].warehouse = frappe.db.get_value(
			"Warehouse", {"company": self.base.company.name, "is_group": 1}, "name"
		)
		doc.set_warehouse = None
		doc.insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		doc = self.native_invoice(False, False)
		doc.items[0].uom = "Nos"
		doc.items[0].conversion_factor = 1
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_no_separate_supplier_payment_or_overpayment(self):
		doc = self.native_invoice(True, False)
		doc.custom_hala_supplier_payment = 1
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		doc = self.native_invoice(True, False)
		doc.paid_amount = 150
		doc.base_paid_amount = 150
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_unique_request_prevents_second_invoice_and_stock_payment(self):
		doc = self.native_invoice(True, True)
		doc.insert()
		doc.submit()
		other = self.native_invoice(True, True)
		other.custom_hala_purchase_request_id = doc.custom_hala_purchase_request_id
		with self.assertRaises(frappe.UniqueValidationError):
			other.insert()
		self.assertEqual(api.find_request(doc.custom_hala_purchase_request_id)["name"], doc.name)
		self.assertEqual(self.base.cash_expected(), 375)

	def test_native_workflow_keeps_invoice_draft_until_approval(self):
		fixture.TestDisbursement.workflow("Purchase Invoice")
		doc = self.native_invoice(True, True, True)
		doc.insert()
		frappe.set_user("hdt-purchase@example.test")
		with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
			doc.submit()
		frappe.set_user("Administrator")
		self.assertEqual(self.base.cash_expected(), 500)
		from frappe.model.workflow import apply_workflow

		doc.reload()
		apply_workflow(doc, "HDT Approve")
		self.assertEqual(self.base.cash_expected(), 500)
		self.assertEqual(self.base.gl(doc, self.base.bank), -125)

	def test_native_taxes_discounts_and_multiple_items(self):
		doc = self.native_invoice(False, False)
		account = frappe.db.get_value(
			"Account", dict(company=self.base.company.name, account_type="Tax", is_group=0), "name"
		)
		if not account:
			parent = frappe.db.get_value(
				"Account", dict(company=self.base.company.name, root_type="Liability", is_group=1), "name"
			)
			account = (
				frappe.get_doc(
					dict(
						doctype="Account",
						account_name="HDT Purchase VAT",
						company=self.base.company.name,
						parent_account=parent,
						account_type="Tax",
						account_currency="SAR",
					)
				)
				.insert()
				.name
			)
		doc.append(
			"items",
			dict(
				item_code="HDT Item",
				qty=2,
				uom="Nos",
				conversion_factor=1,
				rate=10,
				price_list_rate=10,
				warehouse=self.base.warehouse,
				expense_account=self.base.expense,
				cost_center=self.base.cost_center,
			),
		)
		doc.append(
			"taxes",
			dict(
				charge_type="On Net Total",
				account_head=account,
				description="Configured test VAT",
				rate=10,
				add_deduct_tax="Add",
				category="Total",
				cost_center=self.base.cost_center,
			),
		)
		doc.apply_discount_on = "Net Total"
		doc.additional_discount_percentage = 10
		doc.insert()
		doc.submit()
		self.assertAlmostEqual(doc.net_total, 130.5)
		self.assertAlmostEqual(doc.total_taxes_and_charges, 13.05)
		self.assertAlmostEqual(doc.grand_total, 143.55)
		self.assertEqual(self.base.cash_expected(), 500)

	def test_purchase_receipt_link_does_not_receive_stock_twice(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

		receipt = frappe.get_doc(
			dict(
				doctype="Purchase Receipt",
				company=self.base.company.name,
				supplier="HDT Supplier",
				posting_date=nowdate(),
				currency="SAR",
				buying_price_list="HDT Buying",
				items=[
					dict(
						item_code="HDT Purchase Sugar",
						qty=5,
						uom="Kg",
						conversion_factor=1000,
						rate=25,
						warehouse=self.base.warehouse,
					)
				],
			)
		).insert()
		receipt.submit()
		doc = make_purchase_invoice(receipt.name)
		doc.custom_hala_quick_purchase = 1
		doc.custom_hala_purchase_request_id = uuid4().hex
		doc.update_stock = 1
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		doc = make_purchase_invoice(receipt.name)
		doc.custom_hala_quick_purchase = 1
		doc.custom_hala_purchase_request_id = uuid4().hex
		doc.update_stock = 0
		doc.insert()
		doc.submit()
		self.assertFalse(
			frappe.db.exists("Stock Ledger Entry", dict(voucher_type="Purchase Invoice", voucher_no=doc.name))
		)
		self.assertEqual(
			frappe.db.get_value(
				"Bin", dict(item_code="HDT Purchase Sugar", warehouse=self.base.warehouse), "actual_qty"
			),
			5000,
		)

	def test_tax_inclusive_item_template_uses_native_purchase_engine(self):
		doc = self.native_invoice(False, False)
		parent = frappe.db.get_value(
			"Account", {"company": self.base.company.name, "root_type": "Asset", "is_group": 1}, "name"
		)
		account = (
			frappe.get_doc(
				dict(
					doctype="Account",
					account_name="HDT Inclusive Input Tax",
					company=self.base.company.name,
					parent_account=parent,
					account_type="Tax",
					account_currency="SAR",
				)
			)
			.insert()
			.name
		)
		template = frappe.get_doc(
			dict(
				doctype="Item Tax Template",
				title="HDT Inclusive Item Tax",
				company=self.base.company.name,
				taxes=[dict(tax_type=account, tax_rate=10)],
			)
		).insert()
		doc.items[0].item_tax_template = template.name
		doc.append(
			"taxes",
			dict(
				charge_type="On Net Total",
				account_head=account,
				description="Configured inclusive test tax",
				rate=10,
				included_in_print_rate=1,
				add_deduct_tax="Add",
				category="Total",
				cost_center=self.base.cost_center,
			),
		)
		doc.insert()
		doc.submit()
		self.assertEqual(doc.items[0].rate, 25)
		self.assertEqual(doc.items[0].amount, 125)
		self.assertAlmostEqual(doc.grand_total, 125)
		self.assertAlmostEqual(doc.net_total + doc.total_taxes_and_charges, 125)
		self.assertEqual(self.base.cash_expected(), 500)

	def test_other_cash_drawer_rejected_and_unassigned_petty_cash_permitted(self):
		parent = frappe.db.get_value(
			"Account", {"company": self.base.company.name, "root_type": "Asset", "is_group": 1}, "name"
		)
		account = frappe.get_doc(
			dict(
				doctype="Account",
				account_name="HDT Other Purchase Drawer",
				company=self.base.company.name,
				parent_account=parent,
				account_type="Cash",
				account_currency="SAR",
			)
		).insert()
		frappe.get_doc(
			dict(
				doctype="Mode of Payment",
				mode_of_payment="HDT Other Purchase Cash",
				type="Cash",
				accounts=[dict(company=self.base.company.name, default_account=account.name)],
			)
		).insert()
		# Permitted petty cash is not implicitly assigned to the current drawer.
		doc = self.native_invoice(True, False)
		doc.mode_of_payment = "HDT Other Purchase Cash"
		doc.cash_bank_account = account.name
		doc.insert()
		doc.submit()
		self.assertFalse(doc.custom_hala_purchase_shift)
		self.assertEqual(self.base.cash_expected(), 500)
		profile = frappe.copy_doc(frappe.get_doc("POS Profile", "HDT Profile"))
		profile.name = "HDT Other Purchase Profile"
		for row in profile.applicable_for_users:
			row.default = 0
		profile.set("payments", [dict(mode_of_payment="HDT Other Purchase Cash", default=1)])
		profile.insert()
		doc = self.native_invoice(True, False)
		doc.mode_of_payment = "HDT Other Purchase Cash"
		doc.cash_bank_account = account.name
		with self.assertRaises(frappe.PermissionError):
			doc.insert()

	def test_native_calculation_mismatch_is_reported_without_saving(self):
		doc = self.native_invoice(False, False)
		doc.hala_expected_item_amounts = [126]
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		self.assertFalse(
			frappe.db.exists(
				"Purchase Invoice", {"custom_hala_purchase_request_id": doc.custom_hala_purchase_request_id}
			)
		)

	def test_current_cash_drawer_is_resolved_when_card_is_profile_default(self):
		profile = frappe.get_doc("POS Profile", "HDT Profile")
		profile.set(
			"payments",
			[dict(mode_of_payment="HDT Cash", default=0), dict(mode_of_payment="HDT Bank", default=1)],
		)
		profile.posa_cash_mode_of_payment = "HDT Cash"
		profile.save()
		doc = self.native_invoice(True, False)
		doc.insert()
		doc.submit()
		self.assertEqual(doc.custom_hala_purchase_shift, self.base.shift.name)
		self.assertEqual(self.base.cash_expected(), 375)

	def test_configured_native_purchase_print_format_and_preview(self):
		doc = self.native_invoice(False, False)
		doc.insert()
		doc.submit()
		options = api.get_print_options(doc.name)
		self.assertEqual(
			options["print_format"], frappe.get_meta("Purchase Invoice").default_print_format or "Standard"
		)
		html = frappe.get_print("Purchase Invoice", doc.name, options["print_format"])
		self.assertIn(doc.name, html)
		self.assertIn("HDT Purchase Sugar", html)
		self.assertNotIn("custom_hala_purchase_request_id", html)
