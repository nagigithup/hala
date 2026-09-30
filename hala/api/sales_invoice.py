import frappe
from frappe.utils import cint, flt


CASH_ONLY_PAYMENT_MESSAGE = "هذا العميل نقدي فقط. يجب دفع كامل قيمة الفاتورة قبل اعتمادها."


def _is_cash_only_customer(customer):
	return cint(frappe.db.get_value("Customer", customer, "custom_cash_only"))


def validate_cash_only_customer_payment(doc, method=None):
	"""Require cash-only customers to fully pay non-return invoices before submission."""
	if cint(doc.is_return):
		return

	if not _is_cash_only_customer(doc.customer):
		return

	total_field = "rounded_total" if flt(doc.rounded_total) else "grand_total"
	precision = doc.precision(total_field)
	invoice_total = flt(doc.get(total_field), precision)
	paid_amount = flt(doc.paid_amount, precision)

	if paid_amount < invoice_total:
		frappe.throw(CASH_ONLY_PAYMENT_MESSAGE)
