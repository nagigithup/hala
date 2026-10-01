from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.deposit import (
	DEPOSIT_STATUS_OPEN,
	DEPOSIT_STATUS_PARTIAL,
	DEPOSIT_STATUS_REFUNDED,
	_deposit_state,
	_make_payment_entry,
)


class TestHalaDeposit(IntegrationTestCase):
	def test_deposit_schema_page_and_receipt_are_installed(self):
		for fieldname in (
			"custom_is_deposit",
			"custom_deposit_item",
			"custom_deposit_description",
			"custom_deposit_qty",
			"custom_deposit_original_amount",
			"custom_deposit_refunded_amount",
			"custom_deposit_balance",
			"custom_deposit_status",
			"custom_original_deposit_payment",
		):
			self.assertTrue(frappe.get_meta("Payment Entry").has_field(fieldname))
		self.assertTrue(frappe.db.exists("Page", "hala-deposit"))
		print_format = frappe.get_doc("Print Format", "Hala Deposit Receipt")
		self.assertEqual(print_format.doc_type, "Payment Entry")

		doc = frappe._dict(
			{
				"name": "TEST-DEPOSIT",
				"company": frappe.get_all("Company", pluck="name", limit=1)[0],
				"owner": "Administrator",
				"party": "Test Customer",
				"party_name": "Test Customer",
				"posting_date": "2026-10-01",
				"paid_to_account_currency": "SAR",
				"received_amount": 500,
				"custom_deposit_original_amount": 500,
				"custom_deposit_balance": 500,
			}
		)
		html = frappe.render_template(print_format.html, {"doc": doc})
		self.assertIn("سند استلام تأمين", html)
		self.assertIn("المبلغ قابل للاسترداد", html)

	def test_deposit_state_is_open_without_refunds(self):
		state = _deposit_state(500, 0)
		self.assertEqual(state.refunded_amount, 0)
		self.assertEqual(state.balance, 500)
		self.assertEqual(state.status, DEPOSIT_STATUS_OPEN)

	def test_deposit_state_supports_partial_and_full_refunds(self):
		partial = _deposit_state(500, 200)
		self.assertEqual(partial.balance, 300)
		self.assertEqual(partial.status, DEPOSIT_STATUS_PARTIAL)
		full = _deposit_state(500, 500)
		self.assertEqual(full.balance, 0)
		self.assertEqual(full.status, DEPOSIT_STATUS_REFUNDED)

	def test_receive_payment_is_unallocated_and_linked_to_shift(self):
		pe = MagicMock()
		context = frappe._dict(
			{
				"company": "Company",
				"currency": "SAR",
				"mode_of_payment": "Cash",
				"payment_account": "Cash - C",
				"party_account": "Debtors - C",
				"party_currency": "SAR",
				"shift": frappe._dict({"name": "POS-OPEN-1"}),
				"profile": frappe._dict({"cost_center": "Main - C"}),
			}
		)
		with patch("hala.api.deposit.frappe.new_doc", return_value=pe):
			_make_payment_entry(
				context=context,
				customer="Customer",
				amount=500,
				request_id="request-1",
				item_code="TRAY",
				description="Tray deposit",
				qty=2,
			)

		values = pe.update.call_args.args[0]
		self.assertEqual(values["payment_type"], "Receive")
		self.assertEqual(values["paid_from"], "Debtors - C")
		self.assertEqual(values["paid_to"], "Cash - C")
		self.assertEqual(values["reference_no"], "POS-OPEN-1")
		self.assertEqual(values["custom_deposit_balance"], 500)
		pe.set.assert_called_once_with("references", [])
		pe.insert.assert_called_once_with()
		pe.submit.assert_called_once_with()

	def test_refund_reverses_cash_direction_and_links_original(self):
		pe = MagicMock()
		context = frappe._dict(
			{
				"company": "Company",
				"currency": "SAR",
				"mode_of_payment": "Cash",
				"payment_account": "Cash - C",
				"party_account": "Debtors - C",
				"party_currency": "SAR",
				"shift": frappe._dict({"name": "POS-OPEN-1"}),
				"profile": frappe._dict({"cost_center": "Main - C"}),
			}
		)
		with patch("hala.api.deposit.frappe.new_doc", return_value=pe):
			_make_payment_entry(
				context=context,
				customer="Customer",
				amount=200,
				request_id="request-2",
				original_payment="ACC-PAY-1",
			)

		values = pe.update.call_args.args[0]
		self.assertEqual(values["payment_type"], "Pay")
		self.assertEqual(values["paid_from"], "Cash - C")
		self.assertEqual(values["paid_to"], "Debtors - C")
		self.assertEqual(values["custom_original_deposit_payment"], "ACC-PAY-1")
		pe.set.assert_called_once_with("references", [])
