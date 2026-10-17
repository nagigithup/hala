from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.deposit import _make_payment_entry
from hala.api.receipt import (
	_get_receipt,
	_receipt_summary,
	_validated_allocations,
	get_receipts,
)


class TestHalaCustomerReceipt(IntegrationTestCase):
	def setUp(self):
		self.context = frappe._dict(
			{
				"company": "Company",
				"currency": "SAR",
				"mode_of_payment": "Cash",
				"payment_account": "Cash - C",
				"party_account": "Debtors - C",
				"party_currency": "SAR",
				"shift": frappe._dict(name="POS-OPEN-1"),
				"profile": frappe._dict(name="Profile A", cost_center="Main - C"),
			}
		)

	def test_receipt_without_invoice_keeps_empty_standard_references(self):
		description = "دفعة من حساب العميل"
		pe = MagicMock()
		with (
			patch("hala.api.deposit.frappe.new_doc", return_value=pe),
			patch("hala.api.deposit.nowdate", return_value="2026-10-16"),
		):
			_make_payment_entry(
				context=self.context,
				customer="Customer",
				amount=250,
				description=description,
				references=[],
				is_deposit=False,
			)

		values = pe.update.call_args.args[0]
		self.assertEqual(values["payment_type"], "Receive")
		self.assertEqual(values["reference_no"], "POS-OPEN-1")
		self.assertEqual(values["custom_cashier_profile"], "Profile A")
		self.assertEqual(values["custom_is_deposit"], 0)
		self.assertEqual(values["custom_remarks"], 1)
		self.assertEqual(values["remarks"], description)
		pe.set.assert_called_once_with("references", [])
		pe.insert.assert_called_once_with()
		pe.submit.assert_called_once_with()

	def test_receipt_with_invoice_uses_standard_payment_entry_reference(self):
		references = [
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-0001",
				"total_amount": 500,
				"outstanding_amount": 200,
				"allocated_amount": 200,
				"exchange_rate": 1,
			}
		]
		pe = MagicMock()
		with (
			patch("hala.api.deposit.frappe.new_doc", return_value=pe),
			patch("hala.api.deposit.nowdate", return_value="2026-10-16"),
		):
			_make_payment_entry(
				context=self.context,
				customer="Customer",
				amount=200,
				description="Invoice payment",
				references=references,
				is_deposit=False,
			)

		values = pe.update.call_args.args[0]
		self.assertEqual(values["custom_remarks"], 1)
		self.assertEqual(values["remarks"], "Invoice payment")
		pe.set.assert_called_once_with("references", references)

	def test_erpnext_preserves_cashier_description_when_custom_remarks_is_enabled(self):
		description = "دفعة من حساب العميل"
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"custom_remarks": 1,
				"remarks": description,
			}
		)

		pe.set_remarks()

		self.assertEqual(pe.remarks, description)

	def test_reopening_and_printing_use_saved_cashier_description(self):
		description = "دفعة من حساب العميل"
		doc = frappe._dict(
			{
				"name": "ACC-PAY-TEST",
				"company": frappe.get_all("Company", pluck="name", limit=1)[0],
				"party": "Customer",
				"party_name": "Customer",
				"posting_date": "2026-10-17",
				"creation": "2026-10-17 10:00:00",
				"received_amount": 250,
				"paid_amount": 250,
				"unallocated_amount": 250,
				"paid_to_account_currency": "SAR",
				"remarks": description,
				"custom_cashier_profile": "Profile A",
				"owner": "Administrator",
				"reference_no": "POS-OPEN-1",
				"references": [],
			}
		)

		self.assertEqual(_receipt_summary(doc)["description"], description)
		print_format = frappe.get_doc("Print Format", "Hala Customer Receipt")
		html = frappe.render_template(print_format.html, {"doc": doc})
		self.assertIn(description, html)

	def test_deposit_payment_entry_does_not_enable_custom_remarks(self):
		pe = MagicMock()
		with (
			patch("hala.api.deposit.frappe.new_doc", return_value=pe),
			patch("hala.api.deposit.nowdate", return_value="2026-10-16"),
		):
			_make_payment_entry(
				context=self.context,
				customer="Customer",
				amount=250,
				description="Deposit description",
			)

		values = pe.update.call_args.args[0]
		self.assertEqual(values["custom_is_deposit"], 1)
		self.assertNotIn("custom_remarks", values)

	@patch(
		"erpnext.accounts.doctype.payment_entry.payment_entry.get_reference_details"
	)
	@patch("hala.api.receipt.frappe.get_all")
	@patch("hala.api.receipt.frappe.db.sql")
	def test_selected_invoice_is_validated_against_current_outstanding(
		self, _sql, get_all, get_reference_details
	):
		get_all.return_value = [
			frappe._dict(
				name="SINV-0001",
				docstatus=1,
				customer="Customer",
				company="Company",
				debit_to="Debtors - C",
				outstanding_amount=200,
			)
		]
		get_reference_details.return_value = frappe._dict(
			total_amount=500, outstanding_amount=200, exchange_rate=1
		)

		result = _validated_allocations(
			[{"invoice": "SINV-0001", "allocated_amount": 200}],
			"Customer",
			self.context,
			200,
		)

		self.assertEqual(result[0]["reference_doctype"], "Sales Invoice")
		self.assertEqual(result[0]["allocated_amount"], 200)

	def test_no_selection_is_valid_unallocated_receipt(self):
		self.assertEqual(_validated_allocations([], "Customer", self.context, 200), [])

	@patch("hala.api.receipt.frappe.get_all", return_value=[])
	@patch("hala.api.receipt.is_cashier_isolation_user", return_value=True)
	@patch("hala.api.receipt.require_portal_access")
	@patch("hala.api.receipt._cashier_context")
	def test_receipt_list_accepts_zero_or_unset_deposit_flag(
		self, cashier_context, _portal_access, _is_cashier, get_all
	):
		cashier_context.return_value = self.context

		get_receipts()

		call = get_all.call_args.kwargs
		self.assertNotIn("custom_is_deposit", call["filters"])
		self.assertEqual(call["filters"]["custom_cashier_profile"], "Profile A")
		self.assertEqual(
			call["or_filters"],
			[
				["custom_is_deposit", "=", 0],
				["custom_is_deposit", "is", "not set"],
			],
		)
		self.assertNotIn("references", call["filters"])

	@patch("hala.api.receipt.validate_cashier_document")
	@patch("hala.api.receipt.frappe.get_doc")
	def test_deposit_cannot_be_opened_as_customer_receipt(
		self, get_doc, _validate_cashier_document
	):
		get_doc.return_value = frappe._dict(
			name="ACC-PAY-DEPOSIT",
			docstatus=1,
			payment_type="Receive",
			party_type="Customer",
			custom_is_deposit=1,
			custom_booking_invoice=None,
		)

		with self.assertRaises(frappe.ValidationError):
			_get_receipt("ACC-PAY-DEPOSIT")
