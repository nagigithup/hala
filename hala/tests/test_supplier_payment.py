"""Live accounting checks. Every test rolls back its invoices, payments and GL.

Run against a local site with a configured SAR company's cash/payable accounts.
No historical invoice or ledger entry is edited by these tests.
"""

import unittest
from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from hala.api.supplier_payment import get_context, pay_supplier


class TestSupplierPayment(unittest.TestCase):
	def setUp(self):
		self.user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.savepoint("supplier_payment_test")
		companies = frappe.get_all("Company", filters={"default_currency": "SAR"}, pluck="name")
		self.company = None
		for name in companies:
			company = frappe.get_doc("Company", name)
			if company.default_payable_account and company.default_expense_account and company.default_cash_account and company.cost_center:
				self.company = company
				break
		if not self.company:
			self.skipTest("A configured SAR company is required")
		self.supplier = self.make_supplier()
		self.item = frappe.get_doc({
			"doctype": "Item", "item_code": "HALA-PAY-TEST-" + uuid4().hex,
			"item_name": "Temporary supplier payment test", "is_stock_item": 0,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": frappe.db.get_value("UOM", {}, "name"),
		}).insert()

	def tearDown(self):
		frappe.db.rollback(save_point="supplier_payment_test")
		frappe.set_user(self.user)

	def make_supplier(self):
		return frappe.get_doc({
			"doctype": "Supplier", "supplier_name": "HALA-PAY-TEST-" + uuid4().hex,
			"supplier_type": "Company",
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
		}).insert()

	def invoice(self, total, supplier=None, submit=True, currency="SAR", conversion_rate=1, credit_to=None):
		doc = frappe.get_doc({
			"doctype": "Purchase Invoice", "company": self.company.name,
			"supplier": (supplier or self.supplier).name, "posting_date": nowdate(),
			"due_date": nowdate(), "currency": currency, "conversion_rate": conversion_rate,
			"update_stock": 0, "disable_rounded_total": 1, "is_paid": 0,
			"credit_to": credit_to or self.company.default_payable_account, "cost_center": self.company.cost_center,
			"allocate_advances_automatically": 0,
			"items": [{"item_code": self.item.name, "qty": 1, "rate": total,
				"expense_account": self.company.default_expense_account, "cost_center": self.company.cost_center}],
		}).insert()
		if submit:
			doc.submit()
		self.assertEqual(doc.grand_total, total)
		return doc

	def args(self, invoice, amount):
		context = get_context(invoice.name, self.company.default_cash_account)
		return dict(
			invoice=invoice.name, actual_amount=amount, bank_account=context["bank_account"],
			request_id=uuid4().hex, expected_outstanding=context["outstanding"],
			source_exchange_rate=context["source_exchange_rate"], target_exchange_rate=context["target_exchange_rate"],
			reference_date=nowdate(),
		)

	def pay(self, invoice, amount):
		return frappe.get_doc("Payment Entry", pay_supplier(**self.args(invoice, amount))["name"])

	def assert_ledger(self, pe, amount):
		gl = frappe.get_all("GL Entry", filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
			fields=["account", "party", "debit", "credit"])
		self.assertAlmostEqual(sum(row.debit for row in gl), amount)
		self.assertAlmostEqual(sum(row.credit for row in gl), amount)
		self.assertAlmostEqual(sum(row.credit - row.debit for row in gl if row.account == pe.paid_from), amount)
		self.assertAlmostEqual(sum(row.debit - row.credit for row in gl if row.party == self.supplier.name), amount)

	def test_four_payment_amounts_and_ledger(self):
		for total, amount, advance, outstanding in ((87.50, 100, 12.50, 0), (100, 100, 0, 0), (100, 50, 0, 50), (100, 150, 50, 0)):
			with self.subTest(total=total, amount=amount):
				invoice = self.invoice(total)
				pe = self.pay(invoice, amount)
				invoice.reload()
				self.assertEqual(pe.docstatus, 1)
				self.assertEqual(pe.payment_type, "Pay")
				self.assertEqual(pe.party_type, "Supplier")
				self.assertEqual(pe.paid_amount, amount)
				self.assertEqual(pe.total_allocated_amount, min(total, amount))
				self.assertEqual(pe.unallocated_amount, advance)
				self.assertEqual(invoice.outstanding_amount, outstanding)
				self.assertEqual(invoice.paid_amount, 0)
				self.assertEqual(invoice.write_off_amount, 0)
				self.assert_ledger(pe, amount)

	def test_explicit_standard_advance_allocation_and_supplier_isolation(self):
		first = self.invoice(100)
		pe = self.pay(first, 150)
		second = self.invoice(30, submit=False)
		self.assertEqual(get_context(second.name)["available_advance"], 50)
		self.assertEqual(second.total_advance, 0)  # Never consumed by our context API.
		other = self.invoice(30, supplier=self.make_supplier(), submit=False)
		self.assertEqual(get_context(other.name)["available_advance"], 0)
		second.set_advances()  # Explicit standard ERPNext action.
		self.assertEqual(sum(row.allocated_amount for row in second.advances), 30)
		competing = self.invoice(30, submit=False)
		competing.set_advances()  # Stale draft tries to use the same credit.
		second.save()
		second.submit()
		pe.reload()
		self.assertEqual(pe.unallocated_amount, 20)
		second.reload()
		self.assertEqual(second.outstanding_amount, 0)
		self.assertEqual(get_context(second.name)["available_advance"], 20)
		with self.assertRaises(frappe.ValidationError):
			competing.save()
			competing.submit()
		pe.reload()
		self.assertEqual(pe.unallocated_amount, 20)

	def test_cancel_payment_reverses_supplier_balance(self):
		invoice = self.invoice(87.50)
		pe = self.pay(invoice, 100)
		pe.cancel()
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 87.50)
		self.assertEqual(get_context(invoice.name)["available_advance"], 0)
		gl = frappe.get_all("GL Entry", filters={"voucher_type": "Payment Entry", "voucher_no": pe.name}, fields=["account", "party", "debit", "credit"])
		self.assertAlmostEqual(sum(row.debit - row.credit for row in gl if row.party == self.supplier.name), 0)
		self.assertAlmostEqual(sum(row.debit - row.credit for row in gl if row.account == pe.paid_from), 0)

	def test_taxed_invoice_totals_and_original_gl_are_preserved(self):
		tax_account = frappe.db.get_value("Account", {
			"company": self.company.name, "account_type": "Tax", "is_group": 0, "disabled": 0,
		}, "name")
		if not tax_account:
			self.skipTest("A tax account is required")
		invoice = self.invoice(76.08, submit=False)
		invoice.append("taxes", {
			"charge_type": "Actual", "account_head": tax_account, "description": "Temporary VAT test",
			"tax_amount": 11.42, "cost_center": self.company.cost_center,
		})
		invoice.save()
		invoice.submit()
		fields = ["name", "account", "debit", "credit", "party"]
		filters = {"voucher_type": "Purchase Invoice", "voucher_no": invoice.name}
		before = frappe.get_all("GL Entry", filters=filters, fields=fields, order_by="name")
		pe = self.pay(invoice, 100)
		invoice.reload()
		self.assertEqual(invoice.net_total, 76.08)
		self.assertEqual(invoice.total_taxes_and_charges, 11.42)
		self.assertEqual(invoice.grand_total, 87.50)
		self.assertEqual(pe.unallocated_amount, 12.50)
		self.assertEqual(frappe.get_all("GL Entry", filters=filters, fields=fields, order_by="name"), before)

	def test_foreign_party_currency_uses_standard_exchange_rates(self):
		payable = frappe.get_doc({
			"doctype": "Account", "account_name": "HALA-PAY-USD-" + uuid4().hex,
			"parent_account": frappe.db.get_value("Account", self.company.default_payable_account, "parent_account"),
			"company": self.company.name, "account_type": "Payable", "account_currency": "USD",
		}).insert()
		invoice = self.invoice(100, currency="USD", conversion_rate=3.75, credit_to=payable.name)
		with patch("erpnext.accounts.doctype.payment_entry.payment_entry.get_exchange_rate", return_value=3.75):
			pe = self.pay(invoice, 562.50)
		self.assertEqual(pe.paid_from_account_currency, "SAR")
		self.assertEqual(pe.paid_to_account_currency, "USD")
		self.assertEqual(pe.received_amount, 150)
		self.assertEqual(pe.total_allocated_amount, 100)
		self.assertEqual(pe.unallocated_amount, 50)
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 0)
		self.assertEqual(get_context(invoice.name)["available_advance"], 50)
		self.assert_ledger(pe, 562.50)

	def test_retries_return_same_payment_even_after_invoice_is_settled(self):
		invoice = self.invoice(87.50)
		args = self.args(invoice, 100)
		first = pay_supplier(**args)
		self.assertEqual(pay_supplier(**args)["name"], first["name"])
		self.assertEqual(frappe.db.count("Payment Entry", {"custom_hala_supplier_payment_request_id": args["request_id"]}), 1)
		with self.assertRaises(frappe.ValidationError):
			pay_supplier(**dict(args, actual_amount=101))
		pe = frappe.get_doc("Payment Entry", first["name"])
		pe.cancel()
		with self.assertRaises(frappe.ValidationError):
			pay_supplier(**args)

	def test_stale_quote_and_invalid_amounts_create_no_payment(self):
		invoice = self.invoice(100)
		args = self.args(invoice, 50)
		self.pay(invoice, 20)
		with self.assertRaises(frappe.ValidationError):
			pay_supplier(**args)
		for value in (0, -1, "nan", "inf", "abc", 1.001):
			with self.subTest(amount=value), self.assertRaises(frappe.ValidationError):
				pay_supplier(**dict(args, actual_amount=value))
		self.assertFalse(frappe.db.exists("Payment Entry", {"custom_hala_supplier_payment_request_id": args["request_id"]}))

	def test_draft_and_native_invoice_payment_validation_are_unchanged(self):
		invoice = self.invoice(87.50, submit=False)
		self.assertFalse(get_context(invoice.name)["can_pay"])
		with self.assertRaises(frappe.ValidationError):
			get_context(invoice.name, self.company.default_cash_account)
		invoice.is_paid = 1
		invoice.cash_bank_account = self.company.default_cash_account
		invoice.paid_amount = 87.50
		invoice.save()
		self.assertEqual(invoice.is_paid, 1)
		self.assertEqual(invoice.paid_amount, 87.50)
		self.assertFalse(invoice.get("custom_hala_supplier_payment"))

	def test_native_draft_overpayment_is_captured_then_posted_on_submit(self):
		invoice = self.invoice(89.82, submit=False)
		invoice.is_paid = 1
		invoice.cash_bank_account = self.company.default_cash_account
		invoice.paid_amount = 90
		invoice.save()
		self.assertEqual(invoice.custom_hala_actual_supplier_payment, 90)
		self.assertEqual(invoice.custom_hala_supplier_payment, 1)
		self.assertEqual(invoice.is_paid, 0)
		self.assertEqual(invoice.paid_amount, 0)
		self.assertFalse(frappe.db.exists("Payment Entry", {"custom_hala_purchase_invoice": invoice.name}))
		invoice.submit()
		pe = frappe.get_doc("Payment Entry", frappe.db.get_value("Payment Entry", {"custom_hala_purchase_invoice": invoice.name}, "name"))
		self.assertEqual(pe.paid_amount, 90)
		self.assertEqual(pe.total_allocated_amount, 89.82)
		self.assertEqual(pe.unallocated_amount, 0.18)
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 0)
		from hala.api.supplier_payment import submit_inline_payment
		submit_inline_payment(invoice)
		self.assertEqual(frappe.db.count("Payment Entry", {"custom_hala_purchase_invoice": invoice.name}), 1)

	def test_inline_payment_submits_atomically_for_full_and_partial_payments(self):
		for total, actual, advance, outstanding in ((87.5, 100, 12.5, 0), (100, 100, 0, 0), (100, 50, 0, 50), (100, 150, 50, 0)):
			with self.subTest(total=total, actual=actual):
				invoice = self.invoice(total, submit=False)
				invoice.custom_hala_supplier_payment = 1
				invoice.custom_hala_actual_supplier_payment = actual
				invoice.custom_hala_supplier_payment_account = self.company.default_cash_account
				invoice.save()
				invoice.submit()
				invoice.reload()
				pe = frappe.get_doc("Payment Entry", frappe.db.get_value("Payment Entry", {"custom_hala_purchase_invoice": invoice.name}, "name"))
				self.assertEqual(pe.unallocated_amount, advance)
				self.assertEqual(invoice.outstanding_amount, outstanding)
				self.assertEqual(invoice.paid_amount, 0)
				self.assert_ledger(pe, actual)

	def test_inline_submit_failure_rolls_back_invoice_and_payment(self):
		invoice = self.invoice(87.5, submit=False)
		invoice.custom_hala_supplier_payment = 1
		invoice.custom_hala_actual_supplier_payment = 100
		invoice.custom_hala_supplier_payment_account = self.company.default_cash_account
		invoice.save()
		frappe.db.savepoint("inline_supplier_failure")
		with patch("erpnext.accounts.doctype.payment_entry.payment_entry.PaymentEntry.on_submit", side_effect=frappe.ValidationError("Test payment failure")):
			with self.assertRaises(frappe.ValidationError):
				invoice.submit()
		frappe.db.rollback(save_point="inline_supplier_failure")
		invoice.reload()
		self.assertEqual(invoice.docstatus, 0)
		self.assertFalse(frappe.db.exists("Payment Entry", {"custom_hala_purchase_invoice": invoice.name}))
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_type": "Purchase Invoice", "voucher_no": invoice.name}))

	def test_company_account_and_permissions_remain_enforced(self):
		invoice = self.invoice(100)
		other_account = frappe.db.get_value("Account", {"company": ["!=", self.company.name], "account_type": "Cash", "is_group": 0}, "name")
		if other_account:
			with self.assertRaises(frappe.ValidationError):
				get_context(invoice.name, other_account)
		with patch("hala.api.supplier_payment.frappe.has_permission", return_value=False):
			self.assertEqual(get_context(invoice.name)["available_advance"], 0)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_context(invoice.name)
		frappe.set_user("Administrator")

	def test_failed_submit_rolls_back_no_false_success(self):
		invoice = self.invoice(100)
		args = self.args(invoice, 150)
		frappe.db.savepoint("failed_supplier_payment")
		with patch("erpnext.accounts.doctype.payment_entry.payment_entry.PaymentEntry.on_submit", side_effect=frappe.ValidationError("Test submit failure")):
			with self.assertRaises(frappe.ValidationError):
				pay_supplier(**args)
		# Frappe's request handler performs this rollback on an endpoint failure.
		frappe.db.rollback(save_point="failed_supplier_payment")
		self.assertFalse(frappe.db.exists("Payment Entry", {"custom_hala_supplier_payment_request_id": args["request_id"]}))
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 100)
