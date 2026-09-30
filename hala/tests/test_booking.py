from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.booking import (
	_apply_standard_sales_tax_defaults,
	COMPLETED_BOOKING_STATUS,
	_default_payment_method,
	_summary,
	allocate_booking_advances,
	finalize_booking,
)


class TestHalaBooking(IntegrationTestCase):
	@patch("erpnext.controllers.accounts_controller.get_taxes_and_charges")
	@patch("erpnext.accounts.party.get_party_details")
	def test_customer_tax_rule_takes_priority_over_company_default(self, party_details, get_taxes):
		party_details.return_value = frappe._dict(
			{"tax_category": "Retail", "taxes_and_charges": "Customer Tax Template"}
		)
		get_taxes.return_value = [{"charge_type": "On Net Total", "rate": 5}]
		doc = MagicMock()
		doc.customer = "Customer"
		doc.company = "Company"
		doc.posting_date = "2026-09-30"
		doc.selling_price_list = "Standard Selling"
		doc.currency = "SAR"
		doc.doctype = "Sales Invoice"

		with patch("hala.api.booking.frappe.db.get_value") as get_default:
			_apply_standard_sales_tax_defaults(doc)

		get_default.assert_not_called()
		self.assertEqual(doc.taxes_and_charges, "Customer Tax Template")
		get_taxes.assert_called_once_with("Sales Taxes and Charges Template", "Customer Tax Template")
		doc.set.assert_any_call("tax_category", "Retail")
		doc.set.assert_any_call("taxes", [{"charge_type": "On Net Total", "rate": 5}])

	@patch("erpnext.controllers.accounts_controller.get_taxes_and_charges", return_value=[])
	@patch("erpnext.accounts.party.get_party_details", return_value=frappe._dict())
	@patch("hala.api.booking.frappe.db.get_value", return_value="Company Default Tax")
	def test_company_default_tax_template_is_used_without_customer_tax_rule(
		self, get_default, _party_details, get_taxes
	):
		doc = MagicMock()
		doc.customer = "Customer"
		doc.company = "Company"
		doc.posting_date = "2026-09-30"
		doc.selling_price_list = "Standard Selling"
		doc.currency = "SAR"
		doc.doctype = "Sales Invoice"

		_apply_standard_sales_tax_defaults(doc)

		get_default.assert_called_once_with(
			"Sales Taxes and Charges Template", {"is_default": 1, "company": "Company"}
		)
		self.assertEqual(doc.taxes_and_charges, "Company Default Tax")
		get_taxes.assert_called_once_with("Sales Taxes and Charges Template", "Company Default Tax")

	def test_default_payment_method_uses_profile_default_flag(self):
		profile = frappe._dict(
			{
				"name": "Test POS",
				"payments": [
					frappe._dict({"idx": 1, "mode_of_payment": "Card", "default": 0}),
					frappe._dict({"idx": 2, "mode_of_payment": "Configured Cash", "default": 1}),
				],
			}
		)
		self.assertEqual(_default_payment_method(profile), "Configured Cash")

	def test_missing_default_payment_method_is_rejected(self):
		profile = frappe._dict(
			{
				"name": "Test POS",
				"payments": [frappe._dict({"idx": 1, "mode_of_payment": "Cash", "default": 0})],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			_default_payment_method(profile)

	@patch("hala.api.booking.require_portal_access")
	@patch("hala.api.booking._summary", return_value={})
	@patch("hala.api.booking._booking_payments", return_value=[])
	@patch("hala.api.booking._get_booking")
	@patch("hala.api.booking.frappe.db.sql")
	def test_finalize_marks_booking_completed_before_submit(
		self, _lock_booking, get_booking, _payments, _summary_result, _access
	):
		doc = MagicMock()
		doc.name = "SINV-BOOKING"
		doc.docstatus = 0
		doc.custom_is_booking = 1
		doc.customer = "Customer"
		doc.grand_total = 100
		doc.get.side_effect = lambda key: {
			"items": [frappe._dict({"qty": 1})],
		}.get(key)
		get_booking.return_value = doc

		finalize_booking(doc.name)

		self.assertEqual(doc.custom_booking_status, COMPLETED_BOOKING_STATUS)
		doc.submit.assert_called_once_with()

	@patch("hala.api.booking._booking_payments")
	def test_summary_is_derived_from_submitted_payment_entries(self, payments):
		payments.return_value = [
			frappe._dict({"name": "PAY-1", "paid_amount": 200, "base_paid_amount": 200}),
			frappe._dict({"name": "PAY-2", "paid_amount": 300, "base_paid_amount": 300}),
		]
		doc = frappe._dict(
			{
				"name": "SINV-BOOKING",
				"docstatus": 0,
				"custom_is_booking": 1,
				"customer": "Customer",
				"posting_date": "2026-09-30",
				"custom_delivery_date": "2026-10-01",
				"company": "Company",
				"currency": "SAR",
				"company_currency": "SAR",
				"party_account_currency": "SAR",
				"conversion_rate": 1,
				"net_total": 900,
				"total_taxes_and_charges": 100,
				"grand_total": 1000,
				"items": [],
			}
		)
		result = _summary(doc)
		self.assertEqual(result["paid_amount"], 500)
		self.assertEqual(result["remaining_amount"], 500)

	@patch("erpnext.accounts.utils.reconcile_against_document")
	@patch("hala.api.booking.frappe.get_cached_value", return_value="Exchange Gain/Loss")
	@patch("hala.api.booking._booking_payments")
	def test_submit_hook_reconciles_each_advance_and_clears_booking_flag(
		self, payments, _cached_value, reconcile
	):
		payments.return_value = [
			frappe._dict(
				{
					"name": "PAY-1",
					"paid_amount": 300,
					"unallocated_amount": 300,
					"source_exchange_rate": 1,
				}
			)
		]
		doc = MagicMock()
		doc.name = "SINV-BOOKING"
		doc.outstanding_amount = 1000
		doc.debit_to = "Debtors"
		doc.customer = "Customer"
		doc.company = "Company"
		doc.conversion_rate = 1
		doc.grand_total = 1000
		doc.posting_date = "2026-09-30"
		doc.get.side_effect = lambda key: {"custom_is_booking": 1, "cost_center": "Main"}.get(key)

		allocate_booking_advances(doc)

		entries = reconcile.call_args.args[0]
		self.assertEqual(entries[0].voucher_no, "PAY-1")
		self.assertEqual(entries[0].against_voucher, "SINV-BOOKING")
		self.assertEqual(entries[0].allocated_amount, 300)
		doc.db_set.assert_called_once_with("custom_is_booking", 0, update_modified=False)
