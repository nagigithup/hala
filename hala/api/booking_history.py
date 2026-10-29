"""Permission-scoped, read-only history of Hala-origin Sales Invoices."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from hala.access import require_portal_access
from hala.api.booking import _active_shift, _booking_payments, _paid_in_invoice_currency, _summary, _get_default_sales_invoice_print_format
from hala.cashier_profile import is_cashier_isolation_user, validate_cashier_document


def preserve_booking_origin(doc, method=None):
	if not cint(doc.get("custom_is_booking")):
		return
	doc.custom_hala_booking_origin = 1
	if doc.docstatus == 0:
		doc.custom_booking_delivery_time = doc.posting_time
	elif not doc.get("custom_booking_delivery_time") and not doc.is_new():
		# Confirmation replaces posting_time; retain the previously saved delivery time.
		doc.custom_booking_delivery_time = frappe.db.get_value("Sales Invoice", doc.name, "posting_time")


def backfill_booking_origins():
	"""Use explicit markers, linked booking payments or audited flag transitions only."""
	frappe.db.sql("""
		UPDATE `tabSales Invoice` si SET si.custom_hala_booking_origin = 1
		WHERE si.custom_is_booking = 1 OR EXISTS (
			SELECT 1 FROM `tabPayment Entry` pe WHERE pe.custom_booking_invoice = si.name
		)
	""")
	start = 0
	while True:
		versions = frappe.get_all("Version", filters={"ref_doctype": "Sales Invoice", "data": ["like", "%custom_is_booking%"]}, fields=["docname", "data"], order_by="name", start=start, page_length=500)
		for version in versions:
			data = frappe.parse_json(version.data) or {}
			if any(row[0] == "custom_is_booking" and (cint(row[1]) or cint(row[2])) for row in data.get("changed", []) if len(row) == 3):
				frappe.db.set_value("Sales Invoice", version.docname, "custom_hala_booking_origin", 1, update_modified=False)
		if len(versions) < 500:
			break
		start += 500
	frappe.db.sql("""
		UPDATE `tabSales Invoice` SET custom_booking_delivery_time = posting_time
		WHERE custom_hala_booking_origin = 1 AND docstatus = 0
		AND custom_booking_delivery_time IS NULL
	""")


def _scope():
	require_portal_access()
	frappe.has_permission("Sales Invoice", "read", throw=True)
	filters = {"custom_hala_booking_origin": 1}
	if is_cashier_isolation_user():
		profile = _active_shift(required=True)["pos_profile"]
		filters.update(pos_profile=profile.name, company=profile.company)
	return filters


def _payment_totals(doc):
	if cint(doc.docstatus) == 1:
		remaining = flt(doc.outstanding_amount)
		if doc.party_account_currency != doc.currency and flt(doc.conversion_rate):
			remaining /= flt(doc.conversion_rate)
		return flt(doc.grand_total) - remaining, remaining
	paid = _paid_in_invoice_currency(doc, _booking_payments(doc.name))
	return paid, max(flt(doc.grand_total) - paid, 0)


@frappe.whitelist()
def get_history(search="", status="all", start=0, page_length=20):
	filters = _scope()
	if status not in ("all", "open", "confirmed", "cancelled"):
		frappe.throw(_("Invalid status."))
	if status != "all":
		filters["docstatus"] = {"open": 0, "confirmed": 1, "cancelled": 2}[status]
	start, page_length = max(cint(start), 0), min(max(cint(page_length), 1), 50)
	search = str(search or "").strip()[:140]
	or_filters = []
	if search:
		pattern = "%" + search + "%"
		or_filters = [["name", "like", pattern], ["customer_name", "like", pattern], ["customer", "like", pattern], ["contact_mobile", "like", pattern]]
		# Customer permission rules still apply; phone matching never bypasses invoice scope.
		customers = frappe.get_list("Customer", filters={"mobile_no": ["like", pattern]}, pluck="name", limit_page_length=0)
		if customers:
			or_filters.append(["customer", "in", customers])
	rows = frappe.get_list("Sales Invoice", filters=filters, or_filters=or_filters,
		fields=["name", "customer", "customer_name", "creation", "posting_date", "custom_delivery_date", "docstatus", "grand_total", "outstanding_amount", "currency", "company_currency", "party_account_currency", "conversion_rate"],
		order_by="modified desc, name desc", start=start, page_length=page_length + 1)
	more = len(rows) > page_length
	rows = rows[:page_length]
	for row in rows:
		row.paid_amount, row.remaining_amount = _payment_totals(row)
	return {"rows": rows, "has_more": more, "start": start, "page_length": page_length}


def _authorized_booking(name):
	filters = _scope()
	# get_list applies both role/user permissions and the server-derived POS/company scope.
	if not frappe.get_list("Sales Invoice", filters={**filters, "name": name}, pluck="name", page_length=1):
		frappe.throw(_("Booking not found or not permitted."), frappe.PermissionError)
	doc = frappe.get_doc("Sales Invoice", name)
	doc.check_permission("read")
	validate_cashier_document(doc)
	return doc


@frappe.whitelist()
def get_details(name):
	doc = _authorized_booking(name)
	paid, remaining = _payment_totals(doc)
	return {**_summary(doc), "customer_name": doc.customer_name or doc.customer,
		"creation": doc.creation, "paid_amount": paid, "remaining_amount": remaining,
		"delivery_time": str(doc.get("custom_booking_delivery_time") or "").split(".", 1)[0]}


@frappe.whitelist()
def get_print_options(name):
	doc = _authorized_booking(name)
	doc.check_permission("print")
	print_format = _get_default_sales_invoice_print_format()
	if print_format != "Standard" and not frappe.db.exists("Print Format", {
		"name": print_format, "doc_type": "Sales Invoice", "disabled": 0,
	}):
		print_format = "Standard"
	return {"name": doc.name, "docstatus": doc.docstatus, "pos_profile": doc.pos_profile,
		"print_format": print_format, "a4_available": bool(frappe.db.exists("Print Format", {
			"name": "فاتورة مبيعات A4", "doc_type": "Sales Invoice", "disabled": 0,
		}))}
