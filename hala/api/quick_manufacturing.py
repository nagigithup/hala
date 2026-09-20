from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, get_time, nowdate, nowtime

from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
from erpnext.stock.stock_ledger import is_negative_stock_allowed
from erpnext.stock.utils import get_stock_balance

from hala.access import require_portal_access


REQUEST_ID_FIELD = "custom_hala_manufacturing_request_id"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


def _posting_time(value: str | None = None):
	return get_time(value or nowtime()).replace(microsecond=0)


def _require_permissions(*, submit: bool = False) -> None:
	require_portal_access()
	for doctype in ("Item", "BOM", "Warehouse"):
		frappe.has_permission(doctype, "read", throw=True)
	frappe.has_permission("Stock Entry", "create", throw=True)
	if submit:
		frappe.has_permission("Stock Entry", "submit", throw=True)


def _get_valid_bom(bom_no: str, item_code: str | None = None):
	bom = frappe.get_doc("BOM", bom_no)
	frappe.has_permission("BOM", "read", doc=bom, throw=True)
	if bom.docstatus != 1 or not cint(bom.is_active):
		frappe.throw(_("Only an active submitted BOM can be used."))
	if item_code and bom.item != item_code:
		frappe.throw(_("The selected BOM does not belong to the finished item."))
	return bom


def _get_item(item_code: str):
	item = frappe.get_doc("Item", item_code)
	frappe.has_permission("Item", "read", doc=item, throw=True)
	if cint(item.disabled):
		frappe.throw(_("The finished item is disabled."))
	if not cint(item.is_stock_item):
		frappe.throw(_("The finished item must be a stock item."))
	return item


def _get_warehouse(warehouse: str, company: str):
	doc = frappe.get_doc("Warehouse", warehouse)
	frappe.has_permission("Warehouse", "read", doc=doc, throw=True)
	if cint(doc.is_group) or cint(doc.disabled):
		frappe.throw(_("Please select an enabled non-group warehouse."))
	if doc.company != company:
		frappe.throw(_("Warehouse {0} does not belong to company {1}.").format(warehouse, company))
	return doc


def _validate_inputs(
	item_code: str,
	bom_no: str,
	quantity: float,
	source_warehouse: str,
	target_warehouse: str,
	posting_date: str | None,
	posting_time: str | None,
):
	if not source_warehouse or not target_warehouse:
		frappe.throw(_("Please select the source and finished-goods warehouses."))
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw(_("Manufacturing quantity must be greater than zero."))

	item = _get_item(item_code)
	bom = _get_valid_bom(bom_no, item_code)
	_get_warehouse(source_warehouse, bom.company)
	_get_warehouse(target_warehouse, bom.company)
	return frappe._dict(
		item=item,
		bom=bom,
		quantity=quantity,
		posting_date=getdate(posting_date or nowdate()),
		posting_time=_posting_time(posting_time),
	)


def _build_stock_entry(
	item_code: str,
	bom_no: str,
	quantity: float,
	source_warehouse: str,
	target_warehouse: str,
	posting_date: str | None = None,
	posting_time: str | None = None,
	remarks: str | None = None,
):
	values = _validate_inputs(
		item_code,
		bom_no,
		quantity,
		source_warehouse,
		target_warehouse,
		posting_date,
		posting_time,
	)
	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.update(
		{
			"stock_entry_type": "Manufacture",
			"purpose": "Manufacture",
			"company": values.bom.company,
			"set_posting_time": 1,
			"posting_date": values.posting_date,
			"posting_time": values.posting_time,
			"from_bom": 1,
			"bom_no": values.bom.name,
			"fg_completed_qty": values.quantity,
			"use_multi_level_bom": 1,
			"from_warehouse": source_warehouse,
			"to_warehouse": target_warehouse,
			"remarks": remarks or _("Created using Hala Quick Manufacturing"),
		}
	)
	stock_entry.get_items()
	return stock_entry, values


def _preview(stock_entry, values):
	direct_recipe_rows = get_bom_items_as_dict(
		values.bom.name,
		values.bom.company,
		qty=values.quantity,
		fetch_exploded=0,
		fetch_qty_in_stock_uom=False,
	)
	direct_recipe_by_item = {}
	ambiguous_recipe_items = set()
	for recipe_row in direct_recipe_rows.values():
		if recipe_row.item_code in ambiguous_recipe_items:
			continue
		existing = direct_recipe_by_item.get(recipe_row.item_code)
		if not existing:
			direct_recipe_by_item[recipe_row.item_code] = frappe._dict(
				qty=flt(recipe_row.qty), uom=recipe_row.uom
			)
		elif existing.uom == recipe_row.uom:
			existing.qty += flt(recipe_row.qty)
		else:
			# Ambiguous mixed recipe UOMs are displayed in the Stock Entry UOM.
			direct_recipe_by_item.pop(recipe_row.item_code, None)
			ambiguous_recipe_items.add(recipe_row.item_code)

	components = []
	blocking_shortage = False
	for row in stock_entry.items:
		if not row.s_warehouse:
			continue
		available = flt(
			get_stock_balance(
				row.item_code,
				row.s_warehouse,
				stock_entry.posting_date,
				stock_entry.posting_time,
			)
		)
		required_stock_qty = flt(row.transfer_qty)
		recipe_row = direct_recipe_by_item.get(row.item_code)
		difference = available - required_stock_qty
		shortage = max(-difference, 0)
		negative_allowed = bool(is_negative_stock_allowed(item_code=row.item_code))
		if shortage and not negative_allowed:
			blocking_shortage = True
		components.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"required_qty": flt(recipe_row.qty if recipe_row else row.qty),
				"uom": recipe_row.uom if recipe_row else row.uom,
				"conversion_factor": flt(row.conversion_factor),
				"required_stock_qty": required_stock_qty,
				"stock_uom": row.stock_uom,
				"available_qty": available,
				"difference": difference,
				"shortage": shortage,
				"warehouse": row.s_warehouse,
				"negative_stock_allowed": negative_allowed,
			}
		)

	finished_row = next((row for row in stock_entry.items if row.is_finished_item), None)
	estimated_cost = sum(flt(row.basic_amount) for row in stock_entry.items if row.s_warehouse)
	return {
		"item_code": values.item.name,
		"item_name": values.item.item_name,
		"bom_no": values.bom.name,
		"bom_output_qty": flt(values.bom.quantity),
		"finished_uom": values.item.stock_uom,
		"expected_finished_qty": flt(finished_row.transfer_qty if finished_row else values.quantity),
		"components": components,
		"raw_materials_count": len(components),
		"shortages_count": sum(bool(row["shortage"]) for row in components),
		"blocking_shortage": blocking_shortage,
		"estimated_manufacturing_cost": estimated_cost,
		"currency": frappe.get_cached_value("Company", values.bom.company, "default_currency"),
		"company": values.bom.company,
		"negative_stock_enabled": not blocking_shortage and any(
			row["shortage"] and row["negative_stock_allowed"] for row in components
		),
	}


@frappe.whitelist()
def get_context(item_code: str | None = None, bom_no: str | None = None):
	_require_permissions()
	if bom_no:
		bom = _get_valid_bom(bom_no)
		item_code = bom.item

	result = {
		"item_code": item_code,
		"bom_no": None,
		"boms": [],
		"finished_uom": None,
		"company": frappe.defaults.get_user_default("Company"),
		"posting_date": nowdate(),
		"posting_time": _posting_time().strftime("%H:%M:%S"),
		"can_create_bom": frappe.has_permission("BOM", "create"),
	}
	if not item_code:
		return result

	item = _get_item(item_code)
	boms = frappe.get_list(
		"BOM",
		filters={"item": item_code, "docstatus": 1, "is_active": 1},
		fields=["name", "item", "company", "quantity", "uom", "is_default", "total_cost"],
		order_by="is_default desc, modified desc",
		limit=0,
	)
	selected = bom_no if bom_no and any(row.name == bom_no for row in boms) else None
	if not selected and boms:
		selected = next((row.name for row in boms if row.is_default), boms[0].name)
	result.update(
		{
			"item_name": item.item_name,
			"finished_uom": item.stock_uom,
			"bom_no": selected,
			"boms": boms,
			"company": next((row.company for row in boms if row.name == selected), result["company"]),
		}
	)
	return result


@frappe.whitelist()
def preview(
	item_code: str,
	bom_no: str,
	quantity: float,
	source_warehouse: str,
	target_warehouse: str,
	posting_date: str | None = None,
	posting_time: str | None = None,
):
	_require_permissions()
	stock_entry, values = _build_stock_entry(
		item_code,
		bom_no,
		quantity,
		source_warehouse,
		target_warehouse,
		posting_date,
		posting_time,
	)
	return _preview(stock_entry, values)


def _existing_result(request_id: str):
	name = frappe.db.get_value("Stock Entry", {REQUEST_ID_FIELD: request_id}, "name")
	if not name:
		return None
	doc = frappe.get_doc("Stock Entry", name)
	frappe.has_permission("Stock Entry", "read", doc=doc, throw=True)
	return {
		"stock_entry": doc.name,
		"docstatus": doc.docstatus,
		"finished_item": frappe.db.get_value("BOM", doc.bom_no, "item"),
		"manufactured_qty": flt(doc.fg_completed_qty),
		"duplicate_request": True,
	}


@frappe.whitelist()
def manufacture(
	item_code: str,
	bom_no: str,
	quantity: float,
	source_warehouse: str,
	target_warehouse: str,
	request_id: str,
	posting_date: str | None = None,
	posting_time: str | None = None,
	remarks: str | None = None,
):
	_require_permissions(submit=True)
	if not REQUEST_ID_PATTERN.fullmatch(request_id or ""):
		frappe.throw(_("Invalid manufacturing request identifier."))

	lock_name = f"hala:quick-manufacturing:{request_id}"
	with frappe.cache.lock(lock_name, timeout=120, blocking_timeout=15):
		if existing := _existing_result(request_id):
			return existing

		stock_entry, values = _build_stock_entry(
			item_code,
			bom_no,
			quantity,
			source_warehouse,
			target_warehouse,
			posting_date,
			posting_time,
			remarks,
		)
		availability = _preview(stock_entry, values)
		if availability["blocking_shortage"]:
			frappe.throw(
				_("Available material quantity is lower than the required quantity."),
				title=_("Insufficient Stock"),
			)

		stock_entry.set(REQUEST_ID_FIELD, request_id)
		stock_entry.insert()
		stock_entry.submit()
		return {
			"stock_entry": stock_entry.name,
			"docstatus": stock_entry.docstatus,
			"finished_item": values.item.name,
			"manufactured_qty": flt(stock_entry.fg_completed_qty),
			"duplicate_request": False,
		}
