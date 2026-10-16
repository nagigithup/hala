"""Cashier customer receipts backed by standard ERPNext Payment Entries."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from hala.access import require_portal_access
from hala.api.deposit import (
	AMOUNT_TOLERANCE,
	_cashier_context,
	_make_payment_entry,
	_validate_customer,
)
from hala.cashier_profile import is_cashier_isolation_user, validate_cashier_document


def _payload(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or [])


def _receipt_filters(context):
	filters = {
		"docstatus": 1,
		"payment_type": "Receive",
		"party_type": "Customer",
		"company": context.company,
		"custom_booking_invoice": ["is", "not set"],
		"reference_no": ["is", "set"],
	}
	if is_cashier_isolation_user():
		filters["custom_cashier_profile"] = context.profile.name
	return filters


def _receipt_summary(doc):
	currency = doc.paid_to_account_currency or frappe.get_cached_value(
		"Company", doc.company, "default_currency"
	)
	return {
		"name": doc.name,
		"customer": doc.party,
		"customer_name": doc.party_name or doc.party,
		"posting_date": doc.posting_date,
		"creation": doc.creation,
		"amount": flt(doc.received_amount or doc.paid_amount),
		"unallocated_amount": flt(doc.unallocated_amount),
		"description": doc.remarks or "",
		"currency": currency,
		"cashier": doc.get("custom_cashier_profile") or doc.owner,
		"pos_opening_shift": doc.reference_no,
		"allocations": [
			{
				"invoice": row.reference_name,
				"allocated_amount": flt(row.allocated_amount),
			}
			for row in doc.get("references") or []
			if row.reference_doctype == "Sales Invoice" and row.reference_name
		],
	}


def _get_receipt(name):
	doc = frappe.get_doc("Payment Entry", name)
	validate_cashier_document(doc)
	if (
		doc.docstatus != 1
		or doc.payment_type != "Receive"
		or doc.party_type != "Customer"
		or doc.get("custom_is_deposit")
		or doc.get("custom_booking_invoice")
	):
		frappe.throw(_("The selected Payment Entry is not a customer receipt."))
	return doc


def _validated_allocations(allocations, customer, context, amount):
	rows = []
	seen = set()
	for allocation in _payload(allocations):
		invoice = (allocation.get("invoice") or allocation.get("reference_name") or "").strip()
		allocated_amount = flt(allocation.get("allocated_amount"))
		if not invoice and not allocated_amount:
			continue
		if not invoice or allocated_amount <= 0:
			frappe.throw(_("Each selected invoice must have an allocation greater than zero."))
		if invoice in seen:
			frappe.throw(_("Sales Invoice {0} was selected more than once.").format(invoice))
		seen.add(invoice)
		rows.append((invoice, allocated_amount))

	# An empty selection is intentional: ERPNext records the whole receipt as
	# unallocated customer credit/advance using its normal Payment Entry logic.
	if not rows:
		return []

	total_allocated = flt(sum(row[1] for row in rows))
	if abs(total_allocated - amount) > AMOUNT_TOLERANCE:
		frappe.throw(_("The selected invoice allocations must equal the received amount."))

	invoice_names = [row[0] for row in rows]
	frappe.db.sql(
		"SELECT name FROM `tabSales Invoice` WHERE name IN %(names)s FOR UPDATE",
		{"names": tuple(invoice_names)},
	)
	invoices = {
		row.name: row
		for row in frappe.get_all(
			"Sales Invoice",
			filters={"name": ["in", invoice_names]},
			fields=[
				"name",
				"docstatus",
				"customer",
				"company",
				"debit_to",
				"outstanding_amount",
			],
			limit=0,
		)
	}
	validated = []
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_reference_details

	for invoice_name, allocated_amount in rows:
		invoice = invoices.get(invoice_name)
		if (
			not invoice
			or invoice.docstatus != 1
			or invoice.customer != customer
			or invoice.company != context.company
			or invoice.debit_to != context.party_account
		):
			frappe.throw(_("Sales Invoice {0} is not available for this receipt.").format(invoice_name))
		details = get_reference_details(
			"Sales Invoice",
			invoice.name,
			context.party_currency,
			party_type="Customer",
			party=customer,
		)
		outstanding = flt(details.outstanding_amount)
		if outstanding <= 0 or allocated_amount > outstanding + AMOUNT_TOLERANCE:
			frappe.throw(
				_("Allocation for Sales Invoice {0} cannot exceed its outstanding amount.").format(
					invoice_name
				)
			)
		validated.append(
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": invoice.name,
				"total_amount": flt(details.total_amount),
				"outstanding_amount": outstanding,
				"allocated_amount": allocated_amount,
				"exchange_rate": flt(details.exchange_rate or 1),
			}
		)
	return validated


@frappe.whitelist()
def get_receipt_page_context():
	require_portal_access()
	context = _cashier_context()
	return {
		"company": context.company,
		"currency": context.currency,
		"pos_profile": context.profile.name,
		"pos_opening_shift": context.shift.name,
	}


@frappe.whitelist()
def get_outstanding_invoices(customer):
	require_portal_access()
	_validate_customer(customer)
	context = _cashier_context(customer)
	frappe.has_permission("Sales Invoice", "read", throw=True)
	return frappe.get_all(
		"Sales Invoice",
		filters={
			"docstatus": 1,
			"customer": customer,
			"company": context.company,
			"debit_to": context.party_account,
			"outstanding_amount": [">", 0],
		},
		fields=["name", "posting_date", "grand_total", "outstanding_amount", "currency"],
		order_by="posting_date asc, name asc",
		limit=500,
	)


@frappe.whitelist()
def get_receipt(name):
	require_portal_access()
	context = _cashier_context()
	doc = _get_receipt(name)
	if doc.company != context.company:
		frappe.throw(_("The receipt company does not match the active POS cashier company."))
	return _receipt_summary(doc)


@frappe.whitelist()
def get_receipts():
	require_portal_access()
	context = _cashier_context()
	rows = frappe.get_all(
		"Payment Entry",
		filters=_receipt_filters(context),
		or_filters=[
			["custom_is_deposit", "=", 0],
			["custom_is_deposit", "is", "not set"],
		],
		fields=["name"],
		order_by="posting_date desc, creation desc",
		limit=500,
	)
	return [_receipt_summary(frappe.get_doc("Payment Entry", row.name)) for row in rows]


@frappe.whitelist(methods=["POST"])
def create_customer_receipt(customer, amount, description=None, allocations=None):
	require_portal_access()
	_validate_customer(customer)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Received amount must be greater than zero."))
	description = (description or "").strip()
	if len(description) > 500:
		frappe.throw(_("Description cannot exceed 500 characters."))

	context = _cashier_context(customer)
	references = _validated_allocations(allocations, customer, context, amount)
	pe = _make_payment_entry(
		context=context,
		customer=customer,
		amount=amount,
		description=description,
		references=references,
		is_deposit=False,
	)
	return {"receipt": _receipt_summary(pe)}
