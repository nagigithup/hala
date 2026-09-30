from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.sales_invoice import CASH_ONLY_PAYMENT_MESSAGE, validate_cash_only_customer_payment


class TestCashOnlyCustomer(IntegrationTestCase):
	def make_invoice(self, **values):
		invoice = frappe._dict(
			{
				"customer": "Cash Customer",
				"is_return": 0,
				"rounded_total": 100,
				"grand_total": 99.99,
				"paid_amount": 100,
			}
		)
		invoice.update(values)
		invoice.precision = lambda fieldname: 2
		return invoice

	def test_cash_only_customer_requires_full_rounded_total(self):
		invoice = self.make_invoice(paid_amount=99.99)
		with (
			patch("hala.api.sales_invoice._is_cash_only_customer", return_value=1),
			self.assertRaisesRegex(frappe.ValidationError, CASH_ONLY_PAYMENT_MESSAGE),
		):
			validate_cash_only_customer_payment(invoice)

	def test_cash_only_customer_can_submit_when_fully_paid(self):
		invoice = self.make_invoice(paid_amount=100)
		with patch("hala.api.sales_invoice._is_cash_only_customer", return_value=1):
			validate_cash_only_customer_payment(invoice)

	def test_grand_total_is_used_when_rounded_total_is_zero(self):
		invoice = self.make_invoice(rounded_total=0, grand_total=99.99, paid_amount=99.98)
		with (
			patch("hala.api.sales_invoice._is_cash_only_customer", return_value=1),
			self.assertRaises(frappe.ValidationError),
		):
			validate_cash_only_customer_payment(invoice)

	def test_returns_are_ignored(self):
		invoice = self.make_invoice(is_return=1, paid_amount=0)
		with patch("hala.api.sales_invoice._is_cash_only_customer") as is_cash_only_customer:
			validate_cash_only_customer_payment(invoice)
		is_cash_only_customer.assert_not_called()

	def test_normal_customer_is_unchanged(self):
		invoice = self.make_invoice(paid_amount=0)
		with patch("hala.api.sales_invoice._is_cash_only_customer", return_value=0):
			validate_cash_only_customer_payment(invoice)
