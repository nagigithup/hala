from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.cashier_profile import (
	enforce_transaction_cashier_profile,
	get_current_cashier_profile,
	has_transaction_permission,
	payment_entry_query_conditions,
	validate_cashier_profile,
)


class TestCashierProfileIsolation(IntegrationTestCase):
	@patch("pos_next.api.shifts.check_opening_shift")
	def test_resolver_uses_pos_next_active_opening_shift(self, check_shift):
		check_shift.return_value = {
			"pos_opening_shift": frappe._dict(name="OPEN-A", user="a@example.com"),
			"pos_profile": frappe._dict(name="Cashier Profile A"),
		}

		self.assertEqual(
			get_current_cashier_profile("a@example.com"), "Cashier Profile A"
		)
		check_shift.assert_called_once_with("a@example.com")

	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_same_profile_is_allowed(self, _is_cashier, _current):
		validate_cashier_profile("Profile A")

	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_different_profile_is_rejected(self, _is_cashier, _current):
		with self.assertRaises(frappe.PermissionError):
			validate_cashier_profile("Profile B")

	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_payment_entries_are_shared_by_profile_not_owner(self, _is_cashier, _current):
		doc = frappe._dict(
			doctype="Payment Entry",
			owner="first.cashier@example.com",
			custom_cashier_profile="Profile A",
		)
		self.assertTrue(
			has_transaction_permission(doc, user="second.cashier@example.com", permission_type="read")
		)

	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_payment_entry_query_is_profile_scoped(self, _is_cashier, _current):
		condition = payment_entry_query_conditions("cashier@example.com")
		self.assertIn("custom_cashier_profile", condition)
		self.assertIn("Profile A", condition)

	@patch("hala.api.booking.frappe.get_list", return_value=[])
	@patch("hala.api.booking.frappe.has_permission", return_value=True)
	@patch("hala.api.booking.require_portal_access")
	@patch("hala.api.booking.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.api.booking.is_cashier_isolation_user", return_value=True)
	def test_open_bookings_are_filtered_by_profile_not_owner(
		self, _is_cashier, _current, _portal_access, _permission, get_list
	):
		from hala.api.booking import get_open_bookings

		get_open_bookings()

		filters = get_list.call_args.kwargs["filters"]
		self.assertEqual(filters["pos_profile"], "Profile A")
		self.assertNotIn("owner", filters)

	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_new_payment_profile_is_server_managed(self, _is_cashier, _current):
		doc = frappe._dict(
			doctype="Payment Entry",
			custom_cashier_profile="Profile B",
			custom_booking_invoice=None,
			custom_original_deposit_payment=None,
		)
		doc.is_new = MagicMock(return_value=True)
		doc.set = MagicMock(side_effect=lambda field, value: doc.update({field: value}))

		enforce_transaction_cashier_profile(doc)

		self.assertEqual(doc.custom_cashier_profile, "Profile A")

	@patch("hala.cashier_profile.frappe.db.get_value", return_value="Profile A")
	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_booking_payment_inherits_booking_profile(
		self, _is_cashier, _current, _booking_profile
	):
		doc = frappe._dict(
			doctype="Payment Entry",
			custom_cashier_profile=None,
			custom_booking_invoice="BOOK-A",
			custom_original_deposit_payment=None,
		)
		doc.is_new = MagicMock(return_value=True)
		doc.set = MagicMock(side_effect=lambda field, value: doc.update({field: value}))

		enforce_transaction_cashier_profile(doc)

		self.assertEqual(doc.custom_cashier_profile, "Profile A")

	@patch("hala.cashier_profile.frappe.db.get_value", return_value="Profile B")
	@patch("hala.cashier_profile.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=True)
	def test_deposit_refund_from_other_profile_is_rejected(
		self, _is_cashier, _current, _source_profile
	):
		doc = frappe._dict(
			doctype="Payment Entry",
			custom_cashier_profile=None,
			custom_booking_invoice=None,
			custom_original_deposit_payment="PAY-B",
		)
		doc.is_new = MagicMock(return_value=True)

		with self.assertRaises(frappe.PermissionError):
			enforce_transaction_cashier_profile(doc)

	@patch("hala.cashier_profile.is_cashier_isolation_user", return_value=False)
	def test_elevated_users_are_not_restricted(self, _is_cashier):
		doc = frappe._dict(
			doctype="Sales Invoice", pos_profile="Any Profile", owner="someone@example.com"
		)
		self.assertTrue(
			has_transaction_permission(doc, user="manager@example.com", permission_type="read")
		)
		self.assertIsNone(payment_entry_query_conditions("manager@example.com"))

	@patch("pos_next.api.invoices.get_invoices", return_value=[])
	@patch("hala.api.pos_next_security.get_current_cashier_profile", return_value="Profile A")
	@patch("hala.api.pos_next_security.validate_cashier_profile")
	@patch("hala.api.pos_next_security.is_cashier_isolation_user", return_value=True)
	def test_invoice_management_uses_active_profile(
		self, _is_cashier, validate_profile, _current, original
	):
		from hala.api.pos_next_security import get_invoices

		get_invoices("Profile A", limit=20, start=0)

		validate_profile.assert_called_once_with("Profile A")
		original.assert_called_once_with(pos_profile="Profile A", limit=20, start=0)
