from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from hala.access import require_portal_access


# This is deliberately an allowlist. The portal never accepts an arbitrary
# DocType name from the browser.
DOCTYPE_CONFIG: dict[str, dict[str, Any]] = {
	"Item": {
		"label": "Items",
		"module": "items",
		"fields": ["name", "item_name", "item_group", "stock_uom", "current_stock", "standard_selling_rate", "disabled", "modified"],
		"search": ["name", "item_name", "item_group", "barcode"],
		"form": ["item_code", "item_name", "item_group", "stock_uom", "is_stock_item", "disabled", "standard_rate", "description"],
	},
	"Item Group": {"label": "Item Groups", "module": "items", "fields": ["name", "parent_item_group", "is_group", "modified"], "search": ["name"]},
	"UOM": {"label": "UOMs", "module": "items", "fields": ["name", "enabled", "must_be_whole_number", "modified"], "search": ["name"]},
	"Item Price": {"label": "Item Prices", "module": "items", "fields": ["name", "item_code", "price_list", "price_list_rate", "currency", "valid_from", "valid_upto", "modified"], "search": ["name", "item_code", "price_list"], "date": "valid_from", "form": ["item_code", "price_list", "price_list_rate", "currency", "uom", "valid_from", "valid_upto"]},
	"Price List": {"label": "Price Lists", "module": "items", "fields": ["name", "currency", "selling", "buying", "enabled", "modified"], "search": ["name"]},
	"Customer": {"label": "Customers", "module": "customers", "fields": ["name", "customer_name", "customer_group", "territory", "disabled", "modified"], "search": ["name", "customer_name", "mobile_no", "tax_id"], "form": ["customer_name", "customer_type", "customer_group", "territory", "mobile_no", "email_id", "tax_id", "default_currency", "disabled"]},
	"Customer Group": {"label": "Customer Groups", "module": "customers", "fields": ["name", "parent_customer_group", "is_group", "modified"], "search": ["name"]},
	"Supplier": {"label": "Suppliers", "module": "suppliers", "fields": ["name", "supplier_name", "supplier_group", "supplier_type", "disabled", "modified"], "search": ["name", "supplier_name", "mobile_no", "tax_id"], "form": ["supplier_name", "supplier_group", "supplier_type", "country", "mobile_no", "email_id", "tax_id", "default_currency", "disabled"]},
	"Supplier Group": {"label": "Supplier Groups", "module": "suppliers", "fields": ["name", "parent_supplier_group", "is_group", "modified"], "search": ["name"]},
	"Material Request": {"label": "Material Requests", "module": "purchasing", "fields": ["name", "material_request_type", "company", "transaction_date", "schedule_date", "status", "docstatus", "modified"], "search": ["name"], "date": "transaction_date", "form": ["naming_series", "material_request_type", "company", "transaction_date", "schedule_date", "set_warehouse", "items"], "child": {"items": ["item_code", "qty", "uom", "schedule_date", "warehouse"]}},
	"Request for Quotation": {"label": "Requests for Quotation", "module": "purchasing", "fields": ["name", "company", "transaction_date", "schedule_date", "status", "docstatus", "modified"], "search": ["name"], "date": "transaction_date", "form": ["naming_series", "company", "transaction_date", "schedule_date", "message_for_supplier", "suppliers", "items"], "child": {"suppliers": ["supplier"], "items": ["item_code", "qty", "uom", "schedule_date", "warehouse"]}},
	"Supplier Quotation": {"label": "Supplier Quotations", "module": "purchasing", "fields": ["name", "supplier", "company", "transaction_date", "valid_till", "grand_total", "currency", "status", "docstatus", "modified"], "search": ["name", "supplier"], "date": "transaction_date", "amount": "grand_total", "party": "supplier", "form": ["naming_series", "supplier", "company", "transaction_date", "valid_till", "currency", "buying_price_list", "items"], "child": {"items": ["item_code", "qty", "uom", "schedule_date", "rate", "warehouse"]}},
	"Purchase Order": {"label": "Purchase Orders", "module": "purchasing", "fields": ["name", "supplier", "company", "transaction_date", "schedule_date", "grand_total", "currency", "per_received", "per_billed", "status", "docstatus", "modified"], "search": ["name", "supplier"], "date": "transaction_date", "amount": "grand_total", "party": "supplier", "form": ["naming_series", "supplier", "company", "transaction_date", "schedule_date", "currency", "buying_price_list", "set_warehouse", "items", "taxes_and_charges", "terms"], "child": {"items": ["item_code", "qty", "uom", "schedule_date", "rate", "warehouse"]}},
	"Purchase Receipt": {"label": "Purchase Receipts", "module": "purchasing", "fields": ["name", "supplier", "company", "posting_date", "grand_total", "currency", "per_billed", "status", "docstatus", "modified"], "search": ["name", "supplier"], "date": "posting_date", "amount": "grand_total", "party": "supplier", "form": ["naming_series", "supplier", "company", "posting_date", "posting_time", "currency", "buying_price_list", "set_warehouse", "items", "taxes_and_charges"], "child": {"items": ["item_code", "qty", "received_qty", "uom", "rate", "warehouse", "purchase_order"]}},
	"Purchase Invoice": {"label": "Purchase Invoices", "module": "purchasing", "fields": ["name", "supplier", "company", "posting_date", "due_date", "grand_total", "outstanding_amount", "currency", "status", "docstatus", "modified"], "search": ["name", "supplier", "bill_no"], "date": "posting_date", "amount": "grand_total", "party": "supplier", "form": ["naming_series", "supplier", "company", "posting_date", "due_date", "bill_no", "bill_date", "currency", "buying_price_list", "set_warehouse", "update_stock", "items", "taxes_and_charges", "remarks"], "child": {"items": ["item_code", "qty", "uom", "rate", "warehouse", "purchase_order", "purchase_receipt"]}},
	"Sales Order": {"label": "Sales Orders", "module": "sales", "fields": ["name", "customer", "company", "transaction_date", "delivery_date", "grand_total", "currency", "per_delivered", "per_billed", "status", "docstatus", "modified"], "search": ["name", "customer"], "date": "transaction_date", "amount": "grand_total", "party": "customer", "form": ["naming_series", "customer", "company", "transaction_date", "delivery_date", "currency", "selling_price_list", "set_warehouse", "items", "taxes_and_charges", "terms"], "child": {"items": ["item_code", "qty", "uom", "delivery_date", "rate", "warehouse"]}},
	"Delivery Note": {"label": "Delivery Notes", "module": "sales", "fields": ["name", "customer", "company", "posting_date", "grand_total", "currency", "per_billed", "status", "docstatus", "modified"], "search": ["name", "customer"], "date": "posting_date", "amount": "grand_total", "party": "customer", "form": ["naming_series", "customer", "company", "posting_date", "posting_time", "currency", "selling_price_list", "set_warehouse", "items", "taxes_and_charges"], "child": {"items": ["item_code", "qty", "uom", "rate", "warehouse", "against_sales_order"]}},
	"Sales Invoice": {"label": "Sales Invoices", "module": "sales", "fields": ["name", "customer", "company", "posting_date", "due_date", "grand_total", "outstanding_amount", "currency", "status", "docstatus", "modified"], "search": ["name", "customer"], "date": "posting_date", "amount": "grand_total", "party": "customer", "form": ["naming_series", "customer", "company", "posting_date", "due_date", "currency", "selling_price_list", "set_warehouse", "update_stock", "items", "taxes_and_charges", "remarks"], "child": {"items": ["item_code", "qty", "uom", "rate", "warehouse", "sales_order", "delivery_note"]}},
	"BOM": {"label": "BOMs", "module": "manufacturing", "fields": ["name", "item", "company", "quantity", "currency", "total_cost", "is_active", "is_default", "docstatus", "modified"], "search": ["name", "item"], "amount": "total_cost", "form": ["naming_series", "item", "company", "quantity", "uom", "is_active", "is_default", "rm_cost_as_per", "items"], "child": {"items": ["item_code", "qty", "uom", "rate"]}},
	"Stock Entry": {"label": "Stock Entries", "module": "stock", "fields": ["name", "stock_entry_type", "purpose", "company", "posting_date", "total_outgoing_value", "total_incoming_value", "docstatus", "modified"], "search": ["name", "stock_entry_type", "purpose"], "date": "posting_date", "form": ["naming_series", "stock_entry_type", "purpose", "company", "posting_date", "posting_time", "from_warehouse", "to_warehouse", "bom_no", "fg_completed_qty", "items", "remarks"], "child": {"items": ["item_code", "s_warehouse", "t_warehouse", "qty", "uom", "basic_rate", "batch_no", "serial_no"]}},
	"Stock Reconciliation": {"label": "Stock Reconciliations", "module": "stock", "fields": ["name", "company", "posting_date", "purpose", "difference_amount", "docstatus", "modified"], "search": ["name"], "date": "posting_date", "amount": "difference_amount", "form": ["naming_series", "company", "posting_date", "posting_time", "purpose", "expense_account", "cost_center", "items"], "child": {"items": ["item_code", "warehouse", "qty", "valuation_rate"]}},
	"Warehouse": {"label": "Warehouses", "module": "stock", "fields": ["name", "company", "parent_warehouse", "is_group", "disabled", "modified"], "search": ["name", "company"]},
	"Payment Entry": {"label": "Payment Entries", "module": "payments", "fields": ["name", "payment_type", "party_type", "party", "company", "posting_date", "paid_amount", "received_amount", "difference_amount", "status", "docstatus", "modified"], "search": ["name", "party"], "date": "posting_date", "amount": "paid_amount", "party": "party", "form": ["naming_series", "payment_type", "company", "posting_date", "party_type", "party", "mode_of_payment", "paid_from", "paid_from_account_currency", "paid_to", "paid_to_account_currency", "paid_amount", "received_amount", "source_exchange_rate", "target_exchange_rate", "reference_no", "reference_date", "references", "deductions", "remarks"], "child": {"references": ["reference_doctype", "reference_name", "total_amount", "outstanding_amount", "allocated_amount", "exchange_rate"], "deductions": ["account", "cost_center", "amount"]}},
	"Journal Entry": {"label": "Journal Entries", "module": "journal", "fields": ["name", "voucher_type", "company", "posting_date", "total_debit", "total_credit", "difference", "docstatus", "modified"], "search": ["name", "user_remark", "cheque_no"], "date": "posting_date", "amount": "total_debit", "form": ["naming_series", "voucher_type", "company", "posting_date", "finance_book", "cheque_no", "cheque_date", "accounts", "user_remark"], "child": {"accounts": ["account", "party_type", "party", "debit_in_account_currency", "credit_in_account_currency", "cost_center", "project", "reference_type", "reference_name", "exchange_rate"]}},
}


TRANSACTION_DOCTYPES = [
	"Purchase Order", "Purchase Receipt", "Purchase Invoice", "Sales Order", "Delivery Note",
	"Sales Invoice", "Stock Entry", "Payment Entry", "Journal Entry",
]


def _config(doctype: str) -> dict[str, Any]:
	if doctype not in DOCTYPE_CONFIG:
		frappe.throw(_("Document type is not available in Hala."), frappe.PermissionError)
	return DOCTYPE_CONFIG[doctype]


def _json(value, default):
	if value in (None, ""):
		return default
	return frappe.parse_json(value) if isinstance(value, str) else value


def _can(doctype: str, permission: str, doc=None) -> bool:
	return bool(frappe.has_permission(doctype, permission, doc=doc))


def _count(doctype: str, filters=None) -> int:
	if not _can(doctype, "read"):
		return 0
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=[{"COUNT": "*", "as": "count"}],
		limit=1,
	)
	return cint(rows[0].count) if rows else 0


def _sum(doctype: str, field: str, filters=None) -> float:
	if not _can(doctype, "read"):
		return 0
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=[{"SUM": field, "as": "total"}],
		limit=1,
	)
	return flt(rows[0].total) if rows else 0


@frappe.whitelist()
def boot():
	require_portal_access()
	companies = []
	if _can("Company", "read"):
		companies = frappe.get_list("Company", fields=["name", "abbr", "default_currency"], order_by="name", limit=0)
	permissions = {
		doctype: {action: _can(doctype, action) for action in ("read", "create", "write", "submit", "cancel", "print")}
		for doctype in DOCTYPE_CONFIG
	}
	user = frappe.get_cached_doc("User", frappe.session.user)
	return {
		"user": {"name": user.name, "full_name": user.full_name, "language": user.language or frappe.local.lang},
		"companies": companies,
		"default_company": frappe.defaults.get_user_default("Company"),
		"permissions": permissions,
		"doctypes": {key: {k: v for k, v in cfg.items() if k not in ("child",)} for key, cfg in DOCTYPE_CONFIG.items()},
		"notifications": _count("ToDo", {"allocated_to": frappe.session.user, "status": "Open"}),
		"today": nowdate(),
	}


@frappe.whitelist()
def dashboard(company=None, from_date=None, to_date=None):
	require_portal_access()
	today = nowdate()
	company_filter = {"company": company} if company else {}
	def dated(date_field="posting_date", extra=None):
		filters = dict(company_filter)
		filters[date_field] = ["between", [from_date or today, to_date or today]]
		filters.update(extra or {})
		return filters

	metrics = {
		"active_items": _count("Item", {"disabled": 0}),
		"customers": _count("Customer", {"disabled": 0}),
		"suppliers": _count("Supplier", {"disabled": 0}),
		"sales_today": _sum("Sales Invoice", "grand_total", dated(extra={"docstatus": 1})),
		"purchases_today": _sum("Purchase Invoice", "grand_total", dated(extra={"docstatus": 1})),
		"received_today": _sum("Payment Entry", "received_amount", dated(extra={"docstatus": 1, "payment_type": "Receive"})),
		"paid_today": _sum("Payment Entry", "paid_amount", dated(extra={"docstatus": 1, "payment_type": "Pay"})),
		"low_stock": _count("Bin", {"projected_qty": ["<", 0]}) if _can("Bin", "read") else 0,
		"drafts": sum(_count(dt, {"docstatus": 0, **company_filter}) for dt in TRANSACTION_DOCTYPES),
	}
	recent = []
	for doctype in TRANSACTION_DOCTYPES:
		if not _can(doctype, "read"):
			continue
		filters = dict(company_filter)
		for row in frappe.get_list(doctype, filters=filters, fields=["name", "creation", "modified", "docstatus"], order_by="creation desc", limit=3):
			recent.append({"doctype": doctype, **row})
	recent.sort(key=lambda row: str(row.get("creation") or ""), reverse=True)
	return {"metrics": metrics, "recent": recent[:10]}


@frappe.whitelist()
def module_dashboard(module, company=None, from_date=None, to_date=None):
	require_portal_access()
	if module not in ("purchasing", "sales"):
		frappe.throw(_("Unsupported dashboard."))
	company_filter = {"company": company} if company else {}
	period = ["between", [from_date or getdate(nowdate()).replace(day=1), to_date or nowdate()]]
	if module == "purchasing":
		return {
			"draft_documents": sum(_count(dt, {"docstatus": 0, **company_filter}) for dt in ("Material Request", "Request for Quotation", "Supplier Quotation", "Purchase Order", "Purchase Receipt", "Purchase Invoice")),
			"waiting_receipt": _count("Purchase Order", {"docstatus": 1, "per_received": ["<", 100], **company_filter}),
			"waiting_invoice": _count("Purchase Receipt", {"docstatus": 1, "per_billed": ["<", 100], **company_filter}),
			"unpaid_invoices": _count("Purchase Invoice", {"docstatus": 1, "outstanding_amount": [">", 0], **company_filter}),
			"overdue_invoices": _count("Purchase Invoice", {"docstatus": 1, "outstanding_amount": [">", 0], "due_date": ["<", nowdate()], **company_filter}),
			"period_total": _sum("Purchase Invoice", "grand_total", {"docstatus": 1, "posting_date": period, **company_filter}),
		}
	return {
		"draft_documents": sum(_count(dt, {"docstatus": 0, **company_filter}) for dt in ("Sales Order", "Delivery Note", "Sales Invoice")),
		"waiting_delivery": _count("Sales Order", {"docstatus": 1, "per_delivered": ["<", 100], **company_filter}),
		"waiting_invoice": _count("Delivery Note", {"docstatus": 1, "per_billed": ["<", 100], **company_filter}),
		"unpaid_invoices": _count("Sales Invoice", {"docstatus": 1, "outstanding_amount": [">", 0], **company_filter}),
		"overdue_invoices": _count("Sales Invoice", {"docstatus": 1, "outstanding_amount": [">", 0], "due_date": ["<", nowdate()], **company_filter}),
		"period_total": _sum("Sales Invoice", "grand_total", {"docstatus": 1, "posting_date": period, **company_filter}),
	}


@frappe.whitelist()
def list_records(doctype, page=1, page_size=20, search=None, company=None, status=None, from_date=None, to_date=None, sort_by="modified", sort_order="desc"):
	require_portal_access()
	cfg = _config(doctype)
	frappe.has_permission(doctype, "read", throw=True)
	page, page_size = max(cint(page), 1), min(max(cint(page_size), 1), 100)
	meta = frappe.get_meta(doctype)
	computed_fields = {"current_stock", "standard_selling_rate"}
	allowed_sort = {
		field for field in cfg["fields"]
		if field not in computed_fields and (field == "name" or meta.has_field(field))
	} | {"creation", "modified", "name", "docstatus"}
	if sort_by not in allowed_sort:
		sort_by = "modified"
	sort_order = "asc" if str(sort_order).lower() == "asc" else "desc"
	filters: dict[str, Any] = {}
	if company and meta.has_field("company"):
		filters["company"] = company
	if status:
		if status in ("0", "1", "2"):
			filters["docstatus"] = cint(status)
		elif meta.has_field("status"):
			filters["status"] = status
	if cfg.get("date") and (from_date or to_date):
		filters[cfg["date"]] = ["between", [from_date or "1900-01-01", to_date or nowdate()]]
	or_filters = []
	if search:
		term = f"%{search}%"
		or_filters = [[doctype, field, "like", term] for field in cfg.get("search", ["name"]) if field == "name" or meta.has_field(field)]
		if doctype == "Item" and _can("Item Barcode", "read"):
			barcode_items = frappe.get_list("Item Barcode", filters={"barcode": ["like", term]}, pluck="parent", limit=100)
			if barcode_items:
				or_filters.append([doctype, "name", "in", barcode_items])
	query_fields = [field for field in cfg["fields"] if field not in computed_fields and (field == "name" or field in ("creation", "modified", "docstatus") or meta.has_field(field))]
	rows = frappe.get_list(doctype, filters=filters, or_filters=or_filters, fields=query_fields, order_by=f"`tab{doctype}`.`{sort_by}` {sort_order}", start=(page - 1) * page_size, page_length=page_size)
	if doctype == "Item" and rows:
		_add_item_balances_and_prices(rows)
	count_rows = frappe.get_list(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=[{"COUNT": "*", "as": "count"}],
		limit=1,
	)
	return {"rows": rows, "total": cint(count_rows[0].count) if count_rows else 0, "page": page, "page_size": page_size, "fields": cfg["fields"], "can_create": _can(doctype, "create")}


def _add_item_balances_and_prices(rows):
	"""Enrich the current page in two grouped queries, never one query per row."""
	item_codes = [row.name for row in rows]
	stock_by_item = {}
	if _can("Bin", "read"):
		stock_by_item = {
			row.item_code: flt(row.current_stock)
			for row in frappe.get_list(
				"Bin",
				filters={"item_code": ["in", item_codes]},
				fields=["item_code", {"SUM": "actual_qty", "as": "current_stock"}],
				group_by="item_code",
				limit=0,
			)
		}
	price_by_item = {}
	if _can("Item Price", "read") and _can("Price List", "read"):
		price_lists = frappe.get_list("Price List", filters={"selling": 1, "enabled": 1}, pluck="name", order_by="name", limit=1)
		if price_lists:
			for price in frappe.get_list(
				"Item Price",
				filters={"item_code": ["in", item_codes], "price_list": price_lists[0], "selling": 1},
				fields=["item_code", "price_list_rate"],
				order_by="valid_from desc, modified desc",
				limit=0,
			):
				price_by_item.setdefault(price.item_code, flt(price.price_list_rate))
	for row in rows:
		row.current_stock = stock_by_item.get(row.name, 0)
		row.standard_selling_rate = price_by_item.get(row.name, 0)


def _safe_doc_dict(doc):
	meta = frappe.get_meta(doc.doctype)
	permitted = set(meta.get_permitted_fieldnames(permission_type="read"))
	permitted.update({"doctype", "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"})
	result = {}
	for key, value in doc.as_dict().items():
		field = meta.get_field(key)
		if key not in permitted or (field and field.fieldtype == "Password"):
			continue
		if isinstance(value, list):
			result[key] = [_safe_doc_dict(row) for row in value]
		else:
			result[key] = value
	return result


@frappe.whitelist()
def get_document(doctype, name):
	require_portal_access()
	_config(doctype)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	payload = _safe_doc_dict(doc)
	if doctype in ("Customer", "Supplier"):
		payload.update(_party_context(doctype, name))
	return {"doc": payload, "actions": _actions(doc), "links": linked_documents(doctype, name), "form": get_form_schema(doctype)}


def _party_context(party_type, party):
	result = {"outstanding_balance": 0, "contacts": [], "addresses": []}
	invoice_type = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
	party_field = party_type.lower()
	result["outstanding_balance"] = _sum(
		invoice_type,
		"outstanding_amount",
		{party_field: party, "docstatus": 1},
	)
	if _can("Dynamic Link", "read"):
		for parenttype, key, fields in (
			("Contact", "contacts", ["name", "first_name", "last_name", "email_id", "mobile_no", "phone"]),
			("Address", "addresses", ["name", "address_title", "address_type", "address_line1", "city", "country", "phone"]),
		):
			if not _can(parenttype, "read"):
				continue
			parents = frappe.get_list(
				"Dynamic Link",
				filters={"link_doctype": party_type, "link_name": party, "parenttype": parenttype},
				pluck="parent",
				distinct=True,
				limit=50,
			)
			if parents:
				result[key] = frappe.get_list(parenttype, filters={"name": ["in", parents]}, fields=fields, limit=50)
	return result


def _actions(doc):
	return {
		"write": doc.docstatus == 0 and _can(doc.doctype, "write", doc),
		"submit": doc.docstatus == 0 and bool(doc.meta.is_submittable) and _can(doc.doctype, "submit", doc),
		"cancel": doc.docstatus == 1 and _can(doc.doctype, "cancel", doc),
		"print": _can(doc.doctype, "print", doc),
	}


@frappe.whitelist()
def get_form_schema(doctype):
	require_portal_access()
	cfg = _config(doctype)
	meta = frappe.get_meta(doctype)
	fields = []
	for fieldname in cfg.get("form", []):
		df = meta.get_field(fieldname)
		if not df:
			continue
		item = {key: getattr(df, key, None) for key in ("fieldname", "label", "fieldtype", "options", "reqd", "read_only", "description")}
		if fieldname in cfg.get("child", {}):
			child_meta = frappe.get_meta(df.options)
			item["children"] = [
				{key: getattr(child_meta.get_field(child), key, None) for key in ("fieldname", "label", "fieldtype", "options", "reqd", "read_only")}
				for child in cfg["child"][fieldname] if child_meta.get_field(child)
			]
		fields.append(item)
	return {"doctype": doctype, "title_field": meta.title_field, "is_submittable": meta.is_submittable, "fields": fields}


@frappe.whitelist()
def new_document(doctype):
	require_portal_access()
	_config(doctype)
	frappe.has_permission(doctype, "create", throw=True)
	doc = frappe.new_doc(doctype)
	return {"doc": _safe_doc_dict(doc), "form": get_form_schema(doctype)}


@frappe.whitelist(methods=["POST"])
def save_document(doc):
	require_portal_access()
	payload = _json(doc, {})
	doctype = payload.get("doctype")
	_config(doctype)
	if cint(payload.get("docstatus")) != 0:
		frappe.throw(_("Use the explicit Submit or Cancel action to change document status."))
	name = payload.get("name")
	if name and frappe.db.exists(doctype, name):
		target = frappe.get_doc(doctype, name)
		target.check_permission("write")
		payload.pop("doctype", None)
		payload.pop("name", None)
		payload.pop("docstatus", None)
		target.update(payload)
		target.save()
	else:
		frappe.has_permission(doctype, "create", throw=True)
		payload.pop("name", None)
		payload["docstatus"] = 0
		target = frappe.get_doc(payload)
		target.insert()
	return {"doc": _safe_doc_dict(target), "actions": _actions(target)}


@frappe.whitelist(methods=["POST"])
def document_action(doctype, name, action):
	require_portal_access()
	_config(doctype)
	doc = frappe.get_doc(doctype, name)
	if action == "submit":
		doc.check_permission("submit")
		doc.submit()
	elif action == "cancel":
		doc.check_permission("cancel")
		doc.cancel()
	else:
		frappe.throw(_("Unsupported document action."))
	return {"doc": _safe_doc_dict(doc), "actions": _actions(doc)}


@frappe.whitelist()
def link_options(doctype, txt=None, page_length=20, filters=None):
	require_portal_access()
	# Links may point outside the page allowlist, but the target must be a real
	# DocType and the current user must be allowed to read it.
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Invalid link target."))
	frappe.has_permission(doctype, "read", throw=True)
	meta = frappe.get_meta(doctype)
	search_fields = ["name"] + [field.strip() for field in (meta.search_fields or "").split(",") if field.strip()]
	or_filters = [[doctype, field, "like", f"%{txt}%"] for field in search_fields] if txt else []
	return frappe.get_list(doctype, filters=_json(filters, {}), or_filters=or_filters, fields=list(dict.fromkeys(search_fields))[:4], order_by="modified desc", page_length=min(cint(page_length) or 20, 50))


@frappe.whitelist()
def global_search(txt, limit=20):
	require_portal_access()
	if not txt or len(txt.strip()) < 2:
		return []
	results = []
	for doctype, cfg in DOCTYPE_CONFIG.items():
		if len(results) >= min(cint(limit), 50) or not _can(doctype, "read"):
			break
		meta = frappe.get_meta(doctype)
		or_filters = [[doctype, field, "like", f"%{txt}%"] for field in cfg.get("search", ["name"]) if field == "name" or meta.has_field(field)]
		for row in frappe.get_list(doctype, or_filters=or_filters, fields=["name"], limit=3):
			results.append({"doctype": doctype, "name": row.name, "label": cfg["label"]})
	return results[: min(cint(limit), 50)]


@frappe.whitelist()
def outstanding_invoices(company, party_type, party, party_account, payment_type="Receive", posting_date=None):
	require_portal_access()
	frappe.has_permission("Payment Entry", "create", throw=True)
	if party_type not in ("Customer", "Supplier"):
		frappe.throw(_("Party Type must be Customer or Supplier."))
	frappe.has_permission(party_type, "read", party, throw=True)
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_outstanding_reference_documents
	return get_outstanding_reference_documents({
		"company": company,
		"party_type": party_type,
		"party": party,
		"party_account": party_account,
		"payment_type": payment_type,
		"posting_date": posting_date or nowdate(),
		"get_outstanding_invoices": True,
	}) or []


@frappe.whitelist()
def linked_documents(doctype, name):
	require_portal_access()
	_config(doctype)
	frappe.has_permission(doctype, "read", name, throw=True)
	relations = {
		"Purchase Order": [("Purchase Receipt", "items", "purchase_order"), ("Purchase Invoice", "items", "purchase_order")],
		"Purchase Receipt": [("Purchase Invoice", "items", "purchase_receipt")],
		"Sales Order": [("Delivery Note", "items", "against_sales_order"), ("Sales Invoice", "items", "sales_order")],
		"Delivery Note": [("Sales Invoice", "items", "delivery_note")],
	}
	result = []
	party_relations = {
		"Customer": [("Sales Order", "customer"), ("Delivery Note", "customer"), ("Sales Invoice", "customer")],
		"Supplier": [("Purchase Order", "supplier"), ("Purchase Receipt", "supplier"), ("Purchase Invoice", "supplier")],
	}
	for target, party_field in party_relations.get(doctype, []):
		if _can(target, "read"):
			for row in frappe.get_list(target, filters={party_field: name}, fields=["name"], order_by="modified desc", limit=20):
				result.append({"doctype": target, "name": row.name})
	if doctype in party_relations and _can("Payment Entry", "read"):
		for row in frappe.get_list("Payment Entry", filters={"party_type": doctype, "party": name}, fields=["name"], order_by="modified desc", limit=20):
			result.append({"doctype": "Payment Entry", "name": row.name})
	for target, child_field, link_field in relations.get(doctype, []):
		if not _can(target, "read"):
			continue
		child_dt = frappe.get_meta(target).get_field(child_field).options
		parents = frappe.get_list(child_dt, filters={link_field: name, "parenttype": target}, pluck="parent", distinct=True, limit=50)
		for parent in parents:
			if frappe.has_permission(target, "read", parent):
				result.append({"doctype": target, "name": parent})
	return result
