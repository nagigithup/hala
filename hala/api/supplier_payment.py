"""Standard Purchase Invoice payments, including unallocated supplier advances.

Payment Entry owns the cash outflow and allocation. Draft over-tender is kept
separately from native invoice settlement and posted only on confirmation.
"""

from __future__ import annotations

import math
import re
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.party import get_party_account
from erpnext.controllers.accounts_controller import get_advance_payment_entries


def prepare_inline_payment(doc, method=None):
	"""Capture over-tender before ERPNext validates native invoice settlement.

	Saving a draft stores intent only. Never cap a native payment and silently
	lose the excess; the complete amount will be posted by a Payment Entry.
	"""
	if doc.docstatus != 0 and doc.get("_action") != "submit":
		return
	total = flt(doc.rounded_total or doc.grand_total)
	if doc.is_paid and not doc.is_return and total > 0 and flt(doc.paid_amount) > total:
		doc.custom_hala_supplier_payment = 1
		doc.custom_hala_actual_supplier_payment = doc.paid_amount
		doc.custom_hala_supplier_payment_account = doc.cash_bank_account
	if doc.get("custom_hala_supplier_payment"):
		if doc.is_return:
			frappe.throw(_("Use the standard Payment Entry workflow for a return invoice."))
		doc.is_paid = 0
		doc.paid_amount = 0
		doc.base_paid_amount = 0


def validate_inline_payment(doc, method=None):
	if not doc.get("custom_hala_supplier_payment"):
		return
	amount = _number(doc.get("custom_hala_actual_supplier_payment"), _("Actual Amount Paid to Supplier"))
	if amount <= 0:
		frappe.throw(_("Actual Amount Paid to Supplier must be greater than zero."))
	if amount != flt(amount, doc.precision("custom_hala_actual_supplier_payment")):
		frappe.throw(_("Actual payment has more decimal places than the account currency permits."))
	if not doc.get("custom_hala_supplier_payment_account"):
		frappe.throw(_("Cash/Bank Account is required for Supplier Payment."))
	account = frappe.get_doc("Account", doc.custom_hala_supplier_payment_account)
	account.check_permission("read")
	if account.company != doc.company or account.is_group or account.disabled or account.account_type not in ("Cash", "Bank"):
		frappe.throw(_("Select an enabled cash or bank account in the invoice company."))
	# The inline amount is in invoice currency. Cross-currency payment remains
	# available in the existing post-submission dialog with an explicit rate quote.
	if account.account_currency != doc.currency or doc.party_account_currency != doc.currency:
		frappe.throw(_("For different invoice, bank or payable currencies, turn off Supplier Payment on Submit and use Create > Supplier Payment after submitting."))
	if account.account_type == "Bank" and not doc.get("custom_hala_supplier_payment_reference"):
		frappe.throw(_("Reference No is required for a bank payment."))


def submit_inline_payment(doc, method=None):
	"""Run after standard invoice GL posting, in the same request transaction."""
	if not doc.get("custom_hala_supplier_payment"):
		return
	request_id = "hala-pi-" + sha256(doc.name.encode()).hexdigest()[:40]
	quote = {"outstanding": 0, "source_exchange_rate": 1, "target_exchange_rate": 1}
	if not frappe.db.exists("Payment Entry", {"custom_hala_supplier_payment_request_id": request_id}):
		current = _invoice(doc.name)
		quote = _quote(current, _payment_template(current, doc.custom_hala_supplier_payment_account))
	pay_supplier(
		invoice=doc.name, actual_amount=doc.custom_hala_actual_supplier_payment,
		bank_account=doc.custom_hala_supplier_payment_account, request_id=request_id,
		expected_outstanding=quote["outstanding"], source_exchange_rate=quote["source_exchange_rate"],
		target_exchange_rate=quote["target_exchange_rate"],
		reference_no=doc.get("custom_hala_supplier_payment_reference"),
		reference_date=doc.get("custom_hala_supplier_payment_date"),
	)
	# Return the status calculated by ERPNext's Payment Entry, rather than the
	# stale pre-payment balance in the submission response.
	for field in ("outstanding_amount", "status"):
		doc.set(field, frappe.db.get_value("Purchase Invoice", doc.name, field))


def _invoice(name):
	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("read")
	frappe.get_doc("Company", doc.company).check_permission("read")
	frappe.get_doc("Supplier", doc.supplier).check_permission("read")
	return doc


def _number(value, label):
	try:
		number = float(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a valid number.").format(label))
	if not math.isfinite(number):
		frappe.throw(_("{0} must be a valid number.").format(label))
	return number


def _available_advances(doc):
	"""Use ERPNext's advance query, then apply normal document read permissions."""
	if not frappe.has_permission("Payment Entry", "read"):
		return []
	accounts = get_party_account("Supplier", doc.supplier, doc.company, include_advance=True)
	rows = get_advance_payment_entries(
		"Supplier", doc.supplier, [doc.credit_to], "Purchase Order",
		default_advance_account=accounts[1] if len(accounts) > 1 else None,
		condition={"company": doc.company},
	)
	if not rows:
		return []
	permitted = set(frappe.get_list(
		"Payment Entry", filters={"name": ["in", [row.reference_name for row in rows]]},
		pluck="name", limit_page_length=0,
	))
	return [
		{"name": row.reference_name, "amount": flt(row.amount), "currency": row.currency}
		for row in rows
		if row.reference_name in permitted and row.currency == doc.party_account_currency
	]


def _payment_template(doc, bank_account=None):
	if doc.docstatus != 1 or doc.is_return or flt(doc.outstanding_amount) <= 0:
		frappe.throw(_("Submit a non-return Purchase Invoice with an outstanding amount before paying."))
	if doc.invoice_is_blocked():
		frappe.throw(_("This Purchase Invoice is on hold."))
	if bank_account:
		account = frappe.get_doc("Account", bank_account)
		account.check_permission("read")
		if account.company != doc.company or account.is_group or account.disabled or account.account_type not in ("Cash", "Bank"):
			frappe.throw(_("Select an enabled cash or bank account in the invoice company."))
	pe = get_payment_entry("Purchase Invoice", doc.name, bank_account=bank_account)
	# Discounts, withholding and tax-specific payments retain the full standard
	# Payment Entry editor, where the user can review their accounting explicitly.
	if pe.deductions or pe.taxes or doc.apply_tds:
		frappe.throw(_("Use Create > Payment for invoices with payment discounts, deductions or withholding taxes."))
	frappe.get_doc("Account", pe.paid_from).check_permission("read")
	if pe.company != doc.company or pe.party != doc.supplier or pe.paid_to != doc.credit_to:
		frappe.throw(_("The payment account is incompatible with this Purchase Invoice."))
	return pe


def _quote(doc, pe):
	return {
		"bank_account": pe.paid_from,
		"bank_currency": pe.paid_from_account_currency,
		"party_currency": pe.paid_to_account_currency,
		"source_exchange_rate": pe.source_exchange_rate,
		"target_exchange_rate": pe.target_exchange_rate,
		"amount_precision": pe.precision("paid_amount"),
		"received_precision": pe.precision("received_amount"),
		"allocation_precision": pe.precision("allocated_amount", "references"),
		"outstanding": flt(doc.outstanding_amount),
	}


@frappe.whitelist()
def get_context(invoice, bank_account=None):
	doc = _invoice(invoice)
	advances = _available_advances(doc)
	can_pay = bool(
		doc.docstatus == 1 and not doc.is_return and flt(doc.outstanding_amount) > 0
		and frappe.has_permission("Payment Entry", "create")
		and frappe.has_permission("Payment Entry", "submit")
	)
	result = {
		"invoice": doc.name, "company": doc.company, "supplier": doc.supplier,
		"invoice_total": doc.grand_total, "invoice_currency": doc.currency,
		"party_currency": doc.party_account_currency, "outstanding": flt(doc.outstanding_amount),
		"advances": advances, "available_advance": sum(row["amount"] for row in advances),
		"can_pay": can_pay,
		"default_bank_account": doc.cash_bank_account or frappe.get_cached_value(
			"Company", doc.company, "default_cash_account"
		) or frappe.get_cached_value("Company", doc.company, "default_bank_account"),
	}
	if bank_account:
		result.update(_quote(doc, _payment_template(doc, bank_account)))
	return result


def _result(pe):
	return {
		"name": pe.name, "docstatus": pe.docstatus,
		"paid_amount": pe.paid_amount, "currency": pe.paid_from_account_currency,
		"allocated_amount": sum(
			flt(row.allocated_amount) for row in pe.references
			if row.reference_doctype == "Purchase Invoice" and row.reference_name == pe.custom_hala_purchase_invoice
		),
		"unallocated_amount": pe.unallocated_amount, "party_currency": pe.paid_to_account_currency,
	}


@frappe.whitelist(methods=["POST"])
def pay_supplier(invoice, actual_amount, bank_account, request_id, expected_outstanding,
				 source_exchange_rate, target_exchange_rate, reference_no=None, reference_date=None):
	"""Insert and submit one normal Payment Entry in the request transaction.

	A locked invoice serializes concurrent payments. The unique request ID is
	retained on Payment Entry across retries, refreshes, reconciliation and cancel.
	No commit or permission/validation bypass is used here.
	"""
	if not re.fullmatch(r"[A-Za-z0-9-]{16,80}", request_id or ""):
		frappe.throw(_("A valid supplier payment request ID is required."))
	doc = _invoice(invoice)
	doc.flags.for_update = True
	doc.reload()
	amount = _number(actual_amount, _("Actual Amount Paid to Supplier"))
	if amount <= 0:
		frappe.throw(_("Actual Amount Paid to Supplier must be greater than zero."))
	existing = frappe.db.get_value(
		"Payment Entry", {"custom_hala_supplier_payment_request_id": request_id}, "name"
	)
	if existing:
		pe = frappe.get_doc("Payment Entry", existing)
		pe.check_permission("read")
		if (
			pe.custom_hala_purchase_invoice != doc.name or pe.company != doc.company
			or pe.party_type != "Supplier" or pe.party != doc.supplier or pe.payment_type != "Pay"
			or pe.paid_from != bank_account or flt(pe.paid_amount, pe.precision("paid_amount")) != amount
			or (reference_no and pe.reference_no != reference_no)
			or (reference_date and getdate(pe.reference_date) != getdate(reference_date))
		):
			frappe.throw(_("This request ID was already used for a different supplier payment."))
		if pe.docstatus != 1:
			frappe.throw(_("The previous payment is draft or cancelled. Review it before starting a new payment."))
		return _result(pe)
	pe = _payment_template(doc, bank_account)
	pe.check_permission("create")
	pe.check_permission("submit")
	if amount != flt(amount, pe.precision("paid_amount")):
		frappe.throw(_("Actual payment has more decimal places than the account currency permits."))
	# A stale dialog must be reviewed, rather than silently becoming an advance
	# when another payment or reconciliation has changed the invoice balance.
	for actual, expected in (
		(doc.outstanding_amount, expected_outstanding),
		(pe.source_exchange_rate, source_exchange_rate),
		(pe.target_exchange_rate, target_exchange_rate),
	):
		if abs(flt(actual) - _number(expected, _("Payment quote"))) > 0.00000001:
			frappe.throw(_("The outstanding amount or exchange rate changed. Reopen Supplier Payment and review it."))
	pe.paid_amount = amount
	pe.received_amount = flt(
		amount * pe.source_exchange_rate / pe.target_exchange_rate, pe.precision("received_amount")
	)
	remaining = min(pe.received_amount, flt(doc.outstanding_amount))
	for row in pe.references:
		row.allocated_amount = min(max(flt(row.allocated_amount), 0), remaining)
		remaining = flt(remaining - row.allocated_amount, row.precision("allocated_amount"))
	if remaining > 0:
		frappe.throw(_("The standard payment schedule could not allocate this amount. Use Create > Payment."))
	pe.reference_no = reference_no
	pe.reference_date = reference_date or nowdate()
	pe.custom_hala_purchase_invoice = doc.name
	pe.custom_hala_supplier_payment_request_id = request_id
	pe.set_amounts()
	pe.insert()
	pe.submit()
	return _result(pe)
