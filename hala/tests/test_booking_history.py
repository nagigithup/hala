from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.booking_history import _payment_totals, get_details, get_history, get_print_options, preserve_booking_origin


class TestBookingHistory(IntegrationTestCase):
	@patch("hala.api.booking_history.frappe.db.exists", return_value=True)
	@patch("hala.api.booking_history._authorized_booking")
	def test_submitted_print_options_use_pos_receipt_and_require_print_permission(self, authorized, exists):
		doc = MagicMock(name="BOOK", docstatus=1, pos_profile="Profile")
		doc.name = "BOOK"
		authorized.return_value = doc
		options = get_print_options("BOOK")
		self.assertEqual(options["name"], "BOOK")
		self.assertEqual(options["print_format"], "POS Next Receipt")
		doc.check_permission.assert_called_once_with("print")
		authorized.assert_called_once_with("BOOK")

	@patch("hala.api.booking_history.frappe.db.exists", return_value=True)
	@patch("hala.api.booking_history._authorized_booking")
	def test_draft_print_options_use_booking_receipt(self, authorized, exists):
		doc = MagicMock(name="BOOK", docstatus=0, pos_profile="Profile")
		doc.name = "BOOK"
		authorized.return_value = doc
		options = get_print_options("BOOK")
		self.assertEqual(options["print_format"], "BOOKING")

	@patch("hala.api.booking_history._booking_payments", return_value=[frappe._dict(paid_amount=25)])
	def test_draft_payments_use_submitted_booking_advances(self, payments):
		doc = frappe._dict(name="BOOK", docstatus=0, currency="SAR", party_account_currency="SAR", grand_total=100)
		self.assertEqual(_payment_totals(doc), (25, 75))
		payments.assert_called_once_with("BOOK")

	def test_confirmed_amounts_use_ledger_outstanding_in_invoice_currency(self):
		doc = frappe._dict(docstatus=1, grand_total=100, outstanding_amount=150,
			currency="USD", party_account_currency="SAR", conversion_rate=3.75)
		self.assertEqual(_payment_totals(doc), (60, 40))

	def test_origin_and_delivery_time_are_retained_before_confirmation(self):
		doc = MagicMock(docstatus=0, posting_time="14:30:00")
		doc.get.side_effect = lambda key: {"custom_is_booking": 1}.get(key)
		preserve_booking_origin(doc)
		self.assertEqual(doc.custom_hala_booking_origin, 1)
		self.assertEqual(doc.custom_booking_delivery_time, "14:30:00")

	def test_ordinary_invoices_do_not_gain_booking_identity(self):
		doc = frappe._dict(custom_is_booking=0)
		preserve_booking_origin(doc)
		self.assertNotIn("custom_hala_booking_origin", doc)

	@patch("hala.api.booking_history.frappe.get_list", return_value=[])
	@patch("hala.api.booking_history._scope", return_value={"custom_hala_booking_origin": 1, "company": "A", "pos_profile": "POS A"})
	def test_pagination_status_and_scope_cannot_be_expanded_by_client(self, scope, get_list):
		get_history(status="confirmed", start=-10, page_length=100000)
		args = get_list.call_args.kwargs
		self.assertEqual(args["filters"], {"custom_hala_booking_origin": 1, "company": "A", "pos_profile": "POS A", "docstatus": 1})
		self.assertEqual(args["start"], 0)
		self.assertEqual(args["page_length"], 51)
		self.assertEqual(args["order_by"], "modified desc, name desc")

	@patch("hala.api.booking_history.frappe.get_list", return_value=[])
	@patch("hala.api.booking_history._scope", return_value={"custom_hala_booking_origin": 1})
	def test_detail_rejects_missing_or_out_of_scope_invoice(self, scope, get_list):
		with self.assertRaises(frappe.PermissionError):
			get_details("ORDINARY-OR-OTHER-COMPANY")

	@patch("hala.api.booking_history._active_shift", return_value={"pos_profile": frappe._dict(name="POS A", company="Company A")})
	@patch("hala.api.booking_history.is_cashier_isolation_user", return_value=True)
	@patch("hala.api.booking_history.frappe.has_permission")
	@patch("hala.api.booking_history.require_portal_access")
	def test_cashier_scope_is_resolved_on_server(self, access, permission, isolation, shift):
		from hala.api.booking_history import _scope
		self.assertEqual(_scope(), {"custom_hala_booking_origin": 1, "pos_profile": "POS A", "company": "Company A"})
		permission.assert_called_once_with("Sales Invoice", "read", throw=True)
