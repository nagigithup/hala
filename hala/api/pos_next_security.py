"""Cashier-profile guards around POS Next's cashier-facing invoice APIs."""

from __future__ import annotations

import json

import frappe

from hala.cashier_profile import (
	get_current_cashier_context,
	get_current_cashier_profile,
	is_cashier_isolation_user,
	validate_cashier_profile,
)


def _invoice_profile(invoice_name):
	profile = frappe.db.get_value("Sales Invoice", invoice_name, "pos_profile")
	validate_cashier_profile(profile)
	return profile


def _validate_opening_shift(opening_shift):
	if not opening_shift or not is_cashier_isolation_user():
		return
	profile = frappe.db.get_value("POS Opening Shift", opening_shift, "pos_profile")
	validate_cashier_profile(profile)


def _secured_invoice_payload(value):
	payload = json.loads(value) if isinstance(value, str) else value
	if not isinstance(payload, dict) or not is_cashier_isolation_user():
		return value

	context = get_current_cashier_context()
	profile = context["pos_profile"].name
	incoming_profile = payload.get("pos_profile")
	if incoming_profile:
		validate_cashier_profile(incoming_profile)
	payload["pos_profile"] = profile
	payload["posa_pos_opening_shift"] = context["pos_opening_shift"].name

	if payload.get("name") and frappe.db.exists("Sales Invoice", payload["name"]):
		_invoice_profile(payload["name"])
	if payload.get("return_against"):
		_invoice_profile(payload["return_against"])
	return json.dumps(payload) if isinstance(value, str) else payload


def _filter_invoice_rows(rows):
	if not is_cashier_isolation_user() or not rows:
		return rows
	profile = get_current_cashier_profile()
	names = [row.get("name") for row in rows if row.get("name")]
	allowed = set(
		frappe.get_all(
			"Sales Invoice",
			filters={"name": ["in", names], "pos_profile": profile},
			pluck="name",
			ignore_permissions=True,
		)
	)
	return [row for row in rows if row.get("name") in allowed]


@frappe.whitelist()
def get_invoices(pos_profile, limit=100, start=0):
	from pos_next.api.invoices import get_invoices as original

	if is_cashier_isolation_user():
		validate_cashier_profile(pos_profile)
		pos_profile = get_current_cashier_profile()
	return original(pos_profile=pos_profile, limit=limit, start=start)


@frappe.whitelist()
def get_returnable_invoices(limit=50, pos_profile=None):
	from pos_next.api.invoices import get_returnable_invoices as original

	if is_cashier_isolation_user():
		if pos_profile:
			validate_cashier_profile(pos_profile)
		pos_profile = get_current_cashier_profile()
	return _filter_invoice_rows(original(limit=limit, pos_profile=pos_profile))


@frappe.whitelist()
def search_invoice_by_number(search_term, pos_profile=None):
	from pos_next.api.invoices import search_invoice_by_number as original

	if is_cashier_isolation_user():
		if pos_profile:
			validate_cashier_profile(pos_profile)
		pos_profile = get_current_cashier_profile()
	return _filter_invoice_rows(original(search_term=search_term, pos_profile=pos_profile))


@frappe.whitelist()
def check_invoice_return_validity(invoice_name):
	from pos_next.api.invoices import check_invoice_return_validity as original

	_invoice_profile(invoice_name)
	return original(invoice_name)


@frappe.whitelist()
def get_invoice_for_return(invoice_name):
	from pos_next.api.invoices import get_invoice_for_return as original

	_invoice_profile(invoice_name)
	return original(invoice_name)


@frappe.whitelist()
def validate_return_items(original_invoice_name, return_items, doctype="Sales Invoice"):
	from pos_next.api.invoices import validate_return_items as original

	if doctype == "Sales Invoice":
		_invoice_profile(original_invoice_name)
	return original(original_invoice_name, return_items, doctype=doctype)


@frappe.whitelist()
def prepare_return_invoice(invoice_name, pos_opening_shift=None):
	from pos_next.api.invoices import prepare_return_invoice as original

	_invoice_profile(invoice_name)
	_validate_opening_shift(pos_opening_shift)
	return original(invoice_name=invoice_name, pos_opening_shift=pos_opening_shift)


@frappe.whitelist()
def get_draft_invoices(pos_opening_shift, doctype="Sales Invoice"):
	from pos_next.api.invoices import get_draft_invoices as original

	_validate_opening_shift(pos_opening_shift)
	return original(pos_opening_shift=pos_opening_shift, doctype=doctype)


@frappe.whitelist()
def delete_invoice(invoice):
	from pos_next.api.invoices import delete_invoice as original

	_invoice_profile(invoice)
	return original(invoice)


@frappe.whitelist()
def search_invoices_for_return(**kwargs):
	from pos_next.api.invoices import search_invoices_for_return as original

	result = original(**kwargs)
	if not is_cashier_isolation_user() or not result.get("invoices"):
		return result
	result["invoices"] = _filter_invoice_rows(result["invoices"])
	# The upstream count is cross-profile; never expose that side channel.
	result["has_more"] = bool(result["has_more"] and result["invoices"])
	return result


@frappe.whitelist()
def submit_invoice(invoice=None, data=None):
	from pos_next.api.invoices import submit_invoice as original

	secured_invoice = invoice
	secured_data = data
	if invoice is not None:
		secured_invoice = _secured_invoice_payload(invoice)
	elif data is not None:
		parsed = json.loads(data) if isinstance(data, str) else data
		if isinstance(parsed, dict) and "invoice" in parsed:
			parsed["invoice"] = _secured_invoice_payload(parsed["invoice"])
		elif isinstance(parsed, dict) and ("name" in parsed or "doctype" in parsed):
			parsed = _secured_invoice_payload(parsed)
		secured_data = json.dumps(parsed) if isinstance(data, str) else parsed
	return original(invoice=secured_invoice, data=secured_data)
