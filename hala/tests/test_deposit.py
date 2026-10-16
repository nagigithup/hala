from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.deposit import (
	DEPOSIT_STATUS_OPEN,
	DEPOSIT_STATUS_PARTIAL,
	DEPOSIT_STATUS_REFUNDED,
	_deposit_state,
	_get_original_deposit,
	_make_payment_entry,
	_refund_cashier_selection,
	_resolve_refund_shift,
	get_deposits,
)
from pos_next.pos_next.doctype.pos_closing_shift.pos_closing_shift import (
	get_payments_entries,
	get_signed_payment_entry_amount,
)


class TestHalaDeposit(IntegrationTestCase):
	@patch("hala.api.deposit.frappe.get_all", return_value=[])
	@patch("hala.api.deposit.is_cashier_isolation_user", return_value=True)
	@patch("hala.api.deposit.require_portal_access")
	@patch("hala.api.deposit._cashier_context")
	def test_deposit_list_is_filtered_by_cashier_profile(
		self, cashier_context, _portal_access, _is_cashier, get_all
	):
		cashier_context.return_value = frappe._dict(
			company="Company", profile=frappe._dict(name="Profile A")
		)

		get_deposits()

		self.assertEqual(
			get_all.call_args.kwargs["filters"]["custom_cashier_profile"], "Profile A"
		)
		self.assertEqual(get_all.call_args.kwargs["filters"]["custom_is_deposit"], 1)

	@patch("hala.api.deposit.validate_cashier_document")
	@patch("hala.api.deposit.frappe.get_doc")
	def test_normal_customer_receipt_cannot_be_opened_as_deposit(
		self, get_doc, _validate_cashier_document
	):
		get_doc.return_value = frappe._dict(
			name="ACC-PAY-NORMAL",
			docstatus=1,
			payment_type="Receive",
			custom_is_deposit=0,
			custom_original_deposit_payment=None,
		)

		with self.assertRaises(frappe.ValidationError):
			_get_original_deposit("ACC-PAY-NORMAL")

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

	@patch("hala.api.deposit._eligible_refund_cashiers")
	@patch("hala.api.deposit.frappe.db.get_value", return_value="original@example.com")
	def test_original_cashier_is_default_when_active(self, _get_value, eligible):
		eligible.return_value = [
			frappe._dict(user="other@example.com"),
			frappe._dict(user="original@example.com"),
		]
		original = frappe._dict(reference_no="SHIFT-1")

		selection = _refund_cashier_selection(original)

		self.assertEqual(selection.default_cashier, "original@example.com")

	@patch("hala.api.deposit._eligible_refund_cashiers")
	@patch("hala.api.deposit.frappe.db.get_value", return_value="closed@example.com")
	def test_current_cashier_is_fallback_when_original_is_ineligible(self, _get_value, eligible):
		eligible.return_value = [frappe._dict(user=frappe.session.user)]
		original = frappe._dict(reference_no="CLOSED-SHIFT")

		selection = _refund_cashier_selection(original)

		self.assertEqual(selection.default_cashier, frappe.session.user)

	@patch("hala.api.deposit.frappe.get_doc")
	@patch("hala.api.deposit.frappe.db.sql", return_value=[("SHIFT-2",)])
	@patch("hala.api.deposit.frappe.db.has_column", return_value=True)
	@patch("hala.api.deposit._refund_cashier_selection")
	def test_selected_same_profile_cashier_resolves_own_shift(
		self, selection, _has_column, _sql, get_doc
	):
		selection.return_value = frappe._dict(
			cashiers=[
				frappe._dict(
					user="other@example.com",
					pos_opening_shift="SHIFT-2",
					pos_profile="Profile A",
				)
			],
			default_cashier=None,
		)
		get_doc.side_effect = lambda doctype, name: frappe._dict(doctype=doctype, name=name)
		original = frappe._dict(
			custom_cashier_profile="Profile A", company="Company", reference_no="SHIFT-1"
		)

		result = _resolve_refund_shift(original, "other@example.com")

		self.assertEqual(result.pos_opening_shift.name, "SHIFT-2")
		self.assertEqual(result.pos_profile.name, "Profile A")

	@patch("hala.api.deposit._refund_cashier_selection")
	def test_cross_profile_or_inactive_cashier_is_rejected(self, selection):
		selection.return_value = frappe._dict(
			cashiers=[frappe._dict(user="allowed@example.com")],
			default_cashier="allowed@example.com",
		)
		with self.assertRaises(frappe.PermissionError):
			_resolve_refund_shift(
				frappe._dict(custom_cashier_profile="Profile A", company="Company"),
				"other-branch@example.com",
			)

	@patch("hala.api.deposit._refund_cashier_selection")
	def test_refund_is_blocked_when_no_eligible_active_cashier_exists(self, selection):
		selection.return_value = frappe._dict(cashiers=[], default_cashier=None)
		with self.assertRaises(frappe.PermissionError):
			_resolve_refund_shift(
				frappe._dict(custom_cashier_profile="Profile A", company="Company")
			)

	@patch(
		"pos_next.pos_next.doctype.pos_closing_shift.pos_closing_shift.validate_official_closing_access"
	)
	@patch(
		"pos_next.pos_next.doctype.pos_closing_shift.pos_closing_shift.frappe.get_all",
		return_value=[],
	)
	def test_closing_includes_receive_and_pay_with_signed_refunds(self, get_all, _validate):
		get_payments_entries("SHIFT-2")
		self.assertEqual(
			get_all.call_args.kwargs["filters"]["payment_type"],
			["in", ["Receive", "Pay"]],
		)
		self.assertEqual(
			get_signed_payment_entry_amount(
				frappe._dict(payment_type="Receive", paid_amount=10)
			),
			10,
		)
		self.assertEqual(
			get_signed_payment_entry_amount(frappe._dict(payment_type="Pay", paid_amount=4)),
			-4,
		)

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
				"profile": frappe._dict({"name": "Profile A", "cost_center": "Main - C"}),
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
		self.assertEqual(values["custom_cashier_profile"], "Profile A")
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
				"profile": frappe._dict({"name": "Profile A", "cost_center": "Main - C"}),
			}
		)
		with (
			patch("hala.api.deposit.frappe.new_doc", return_value=pe),
			patch("hala.api.deposit.frappe.db.get_value", return_value="Profile A"),
			patch("hala.api.deposit.validate_cashier_profile"),
		):
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
		self.assertEqual(values["custom_cashier_profile"], "Profile A")
		pe.set.assert_called_once_with("references", [])
