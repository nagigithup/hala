from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate
from frappe.utils.xlsxutils import build_xlsx_response, read_xlsx_file_from_attached_file


DEFAULT_PAGE_LENGTH = 50
MAX_PAGE_LENGTH = 2000
MAX_SAVE_CHANGES = 5000
MAX_EXPORT_ITEMS = 10000
FIXED_EXPORT_COLUMNS = ("Item Code", "Item Name", "UOM", "Item Group")
ITEM_SORT_FIELDS = {
	"item_code": "name",
	"item_name": "item_name",
	"uom": "stock_uom",
	"item_group": "item_group",
}


def _require_read_permissions() -> None:
	for doctype in ("Item", "Price List", "Item Price"):
		frappe.has_permission(doctype, "read", throw=True)


def _is_current(row, transaction_date=None) -> bool:
	transaction_date = getdate(transaction_date or nowdate())
	return (not row.get("valid_from") or getdate(row.valid_from) <= transaction_date) and (
		not row.get("valid_upto") or getdate(row.valid_upto) >= transaction_date
	)


def _is_generic(row) -> bool:
	return not any(
		(
			row.get("customer"),
			row.get("supplier"),
			row.get("batch_no"),
			cint(row.get("packing_unit")),
		)
	)


def _current_price_map(item_codes, price_lists, uoms=None):
	if not item_codes or not price_lists:
		return {}

	filters = {
		"item_code": ["in", list(item_codes)],
		"price_list": ["in", list(price_lists)],
		"selling": 1,
	}
	if uoms:
		filters["uom"] = ["in", list(uoms)]

	rows = frappe.get_list(
		"Item Price",
		filters=filters,
		fields=[
			"name",
			"item_code",
			"price_list",
			"price_list_rate",
			"uom",
			"currency",
			"valid_from",
			"valid_upto",
			"customer",
			"supplier",
			"batch_no",
			"packing_unit",
			"modified",
		],
		order_by="valid_from desc, creation desc",
		limit=0,
	)

	prices = {}
	for row in rows:
		key = (row.item_code, row.price_list, row.uom)
		if key not in prices and _is_generic(row) and _is_current(row):
			prices[key] = row
	return prices


def _item_filters(search, item_group):
	filters = {"disabled": 0}
	if item_group:
		filters["item_group"] = item_group

	search = (search or "").strip()
	or_filters = None
	if search:
		pattern = f"%{search}%"
		or_filters = {"name": ["like", pattern], "item_name": ["like", pattern]}
	return filters, or_filters


def _get_items(search, item_group, start, page_length, sort_by="item_code", sort_order="asc"):
	filters, or_filters = _item_filters(search, item_group)
	sort_field = ITEM_SORT_FIELDS.get(sort_by, ITEM_SORT_FIELDS["item_code"])
	sort_order = "desc" if str(sort_order).lower() == "desc" else "asc"

	rows = frappe.get_list(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=["name as item_code", "item_name", "stock_uom as uom", "item_group", "has_variants"],
		order_by=f"{sort_field} {sort_order}, name asc",
		offset=start,
		limit=page_length,
	)
	count = frappe.get_list(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=[{"COUNT": "name", "as": "total"}],
		limit=1,
	)
	total = cint(count[0].total) if count else 0
	return rows, total


def _get_price_lists(price_list=None):
	filters = {"selling": 1, "enabled": 1}
	if price_list:
		filters["name"] = price_list
	return frappe.get_list(
		"Price List",
		filters=filters,
		fields=["name", "currency", "price_not_uom_dependent"],
		order_by="name asc",
		limit=0,
	)


@frappe.whitelist()
def get_price_matrix(
	search: str | None = None,
	item_group: str | None = None,
	price_list: str | None = None,
	start: int = 0,
	page_length: int = DEFAULT_PAGE_LENGTH,
	sort_by: str = "item_code",
	sort_order: str = "asc",
):
	_require_read_permissions()
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), MAX_PAGE_LENGTH)

	price_lists = _get_price_lists(price_list)
	items, total = _get_items(
		search,
		item_group,
		start,
		page_length,
		sort_by=sort_by,
		sort_order=sort_order,
	)
	prices = _current_price_map(
		[row.item_code for row in items],
		[row.name for row in price_lists],
		[row.uom for row in items],
	)

	price_matrix = {}
	for item in items:
		price_matrix[item.item_code] = {}
		for price_list in price_lists:
			row = prices.get((item.item_code, price_list.name, item.uom))
			if row:
				price_matrix[item.item_code][price_list.name] = {
					"name": row.name,
					"rate": flt(row.price_list_rate),
					"currency": row.currency or price_list.currency,
					"modified": str(row.modified),
				}

	return {
		"items": items,
		"price_lists": price_lists,
		"prices": price_matrix,
		"pagination": {
			"start": start,
			"page_length": page_length,
			"total": total,
			"has_more": start + len(items) < total,
		},
		"sorting": {
			"sort_by": sort_by if sort_by in ITEM_SORT_FIELDS else "item_code",
			"sort_order": "desc" if str(sort_order).lower() == "desc" else "asc",
		},
		"permissions": {
			"can_write": bool(frappe.has_permission("Item Price", "write")),
			"can_create": bool(frappe.has_permission("Item Price", "create")),
		},
	}


def _get_export_items(search, item_group, sort_by, sort_order):
	filters, or_filters = _item_filters(search, item_group)
	sort_field = ITEM_SORT_FIELDS.get(sort_by, ITEM_SORT_FIELDS["item_code"])
	sort_order = "desc" if str(sort_order).lower() == "desc" else "asc"
	items = frappe.get_list(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=["name as item_code", "item_name", "stock_uom as uom", "item_group"],
		order_by=f"{sort_field} {sort_order}, name asc",
		limit=MAX_EXPORT_ITEMS + 1,
	)
	if len(items) > MAX_EXPORT_ITEMS:
		frappe.throw(
			_("Excel export is limited to {0} Items. Apply more filters and try again.").format(
				MAX_EXPORT_ITEMS
			)
		)
	return items


def _build_export_rows(search=None, item_group=None, price_list=None, sort_by="item_code", sort_order="asc"):
	price_lists = _get_price_lists(price_list)
	items = _get_export_items(search, item_group, sort_by, sort_order)
	prices = _current_price_map(
		[row.item_code for row in items],
		[row.name for row in price_lists],
		[row.uom for row in items],
	)
	rows = [[*FIXED_EXPORT_COLUMNS, *[row.name for row in price_lists]]]
	for item in items:
		row = [item.item_code, item.item_name, item.uom, item.item_group]
		for price_list_row in price_lists:
			price = prices.get((item.item_code, price_list_row.name, item.uom))
			row.append(flt(price.price_list_rate) if price else None)
		rows.append(row)
	return rows


@frappe.whitelist(methods=["POST"])
def export_price_matrix(
	search: str | None = None,
	item_group: str | None = None,
	price_list: str | None = None,
	sort_by: str = "item_code",
	sort_order: str = "asc",
):
	_require_read_permissions()
	rows = _build_export_rows(search, item_group, price_list, sort_by, sort_order)
	build_xlsx_response(rows, "Item Price Manager")


def _changes_from_import_rows(rows):
	if not rows or len(rows) < 2:
		frappe.throw(_("The Excel file does not contain any Item rows."))
	header = [str(value or "").strip() for value in rows[0]]
	if tuple(header[: len(FIXED_EXPORT_COLUMNS)]) != FIXED_EXPORT_COLUMNS:
		frappe.throw(
			_("Use an Excel file exported from Item Price Manager. The fixed columns are not valid.")
		)
	price_list_names = header[len(FIXED_EXPORT_COLUMNS) :]
	while price_list_names and not price_list_names[-1]:
		price_list_names.pop()
	if not price_list_names:
		frappe.throw(_("The Excel file does not contain a Selling Price List column."))
	if any(not value for value in price_list_names):
		frappe.throw(_("Price List columns in the Excel file cannot be blank."))
	if len(price_list_names) != len(set(price_list_names)):
		frappe.throw(_("The Excel file contains duplicate Price List columns."))

	price_lists = _get_price_lists()
	active_price_lists = {row.name for row in price_lists}
	invalid_price_lists = set(price_list_names) - active_price_lists
	if invalid_price_lists:
		frappe.throw(
			_("These Price Lists are not enabled Selling Price Lists: {0}").format(
				", ".join(sorted(invalid_price_lists))
			)
		)

	data_rows = [row for row in rows[1:] if any(value not in (None, "") for value in row)]
	if len(data_rows) > MAX_EXPORT_ITEMS:
		frappe.throw(_("A maximum of {0} Item rows can be imported at once.").format(MAX_EXPORT_ITEMS))
	item_codes = [str(row[0] or "").strip() for row in data_rows if row]
	if not all(item_codes):
		frappe.throw(_("Every imported row must contain an Item Code."))
	if len(item_codes) != len(set(item_codes)):
		frappe.throw(_("The Excel file contains duplicate Item rows."))

	items = frappe.get_list(
		"Item",
		filters={"name": ["in", item_codes], "disabled": 0},
		fields=["name", "stock_uom", "has_variants"],
		limit=0,
	)
	items_by_name = {row.name: row for row in items}
	missing_items = set(item_codes) - set(items_by_name)
	if missing_items:
		frappe.throw(
			_("These Items are missing, disabled, or not permitted: {0}").format(
				", ".join(sorted(missing_items))
			)
		)

	changes = []
	for row_number, row in enumerate(data_rows, 2):
		item_code = str(row[0] or "").strip()
		item = items_by_name[item_code]
		for offset, price_list_name in enumerate(price_list_names, len(FIXED_EXPORT_COLUMNS)):
			value = row[offset] if offset < len(row) else None
			if value in (None, ""):
				continue
			changes.append(
				{
					"item_code": item_code,
					"price_list": price_list_name,
					"uom": item.stock_uom,
					"price_list_rate": _parse_rate(value, row_number),
				}
			)
	if not changes:
		frappe.throw(_("The Excel file does not contain any prices to import."))
	return changes


@frappe.whitelist(methods=["POST"])
def import_price_matrix():
	_require_read_permissions()
	file_name = str(frappe.local.uploaded_filename or "")
	content = frappe.local.uploaded_file
	if not content or not file_name.lower().endswith(".xlsx"):
		frappe.throw(_("Please upload an XLSX file exported from Item Price Manager."))
	rows = read_xlsx_file_from_attached_file(fcontent=content, read_only=True)
	result = save_prices(_changes_from_import_rows(rows))
	result["rows"] = max(len(rows) - 1, 0)
	return result


def _parse_rate(value, row_number: int) -> float:
	try:
		rate = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Row {0}: Price must be a valid number.").format(row_number))
	if not rate.is_finite() or rate < 0:
		frappe.throw(_("Row {0}: Price cannot be negative.").format(row_number))
	return float(rate)


def _normalize_changes(changes):
	changes = frappe.parse_json(changes)
	if not isinstance(changes, list):
		frappe.throw(_("Changes must be provided as a list."))
	if not changes:
		return []
	if len(changes) > MAX_SAVE_CHANGES:
		frappe.throw(_("A maximum of {0} prices can be saved at once.").format(MAX_SAVE_CHANGES))

	normalized = []
	seen = set()
	for row_number, change in enumerate(changes, 1):
		if not isinstance(change, dict):
			frappe.throw(_("Row {0}: Invalid price change.").format(row_number))
		item_code = str(change.get("item_code") or "").strip()
		price_list = str(change.get("price_list") or "").strip()
		uom = str(change.get("uom") or "").strip()
		if not item_code or not price_list or not uom:
			frappe.throw(_("Row {0}: Item, Price List, and UOM are required.").format(row_number))
		key = (item_code, price_list, uom)
		if key in seen:
			frappe.throw(_("The same Item, Price List, and UOM was included more than once."))
		seen.add(key)
		normalized.append(
			frappe._dict(
				item_code=item_code,
				price_list=price_list,
				uom=uom,
				price_list_rate=_parse_rate(change.get("price_list_rate"), row_number),
				item_price=str(change.get("item_price") or "").strip() or None,
				modified=str(change.get("modified") or "").strip() or None,
			)
		)
	return normalized


def _validate_master_data(changes):
	item_codes = {row.item_code for row in changes}
	price_list_names = {row.price_list for row in changes}

	items = frappe.get_list(
		"Item",
		filters={"name": ["in", list(item_codes)], "disabled": 0},
		fields=["name", "stock_uom", "has_variants"],
		limit=0,
	)
	items_by_name = {row.name: row for row in items}
	if len(items_by_name) != len(item_codes):
		frappe.throw(_("One or more Items are missing, disabled, or not permitted."))

	price_lists = frappe.get_list(
		"Price List",
		filters={"name": ["in", list(price_list_names)], "selling": 1, "enabled": 1},
		fields=["name", "currency"],
		limit=0,
	)
	price_lists_by_name = {row.name: row for row in price_lists}
	if len(price_lists_by_name) != len(price_list_names):
		frappe.throw(_("One or more Price Lists are disabled, not selling, or not permitted."))

	for row in changes:
		item = items_by_name[row.item_code]
		if cint(item.has_variants):
			frappe.throw(_("Item {0} is a template and cannot have an Item Price.").format(row.item_code))
		if item.stock_uom != row.uom:
			frappe.throw(
				_("The stock UOM for Item {0} changed. Refresh the page and try again.").format(
					row.item_code
				)
			)
	return items_by_name, price_lists_by_name


def _prepare_documents(changes, price_lists_by_name):
	current_prices = _current_price_map(
		{row.item_code for row in changes},
		{row.price_list for row in changes},
		{row.uom for row in changes},
	)
	prepared = []

	for row in changes:
		key = (row.item_code, row.price_list, row.uom)
		current = current_prices.get(key)
		if row.item_price and (not current or current.name != row.item_price):
			frappe.throw(
				_("The price for Item {0} in {1} changed. Refresh the page and try again.").format(
					row.item_code, row.price_list
				)
			)

		if current:
			doc = frappe.get_doc("Item Price", current.name)
			frappe.has_permission("Item Price", "write", doc=doc, throw=True)
			if row.modified and str(doc.modified) != row.modified:
				frappe.throw(
					_("The price for Item {0} in {1} was modified by another user.").format(
						row.item_code, row.price_list
					)
				)
			action = "update"
		else:
			doc = frappe.new_doc("Item Price")
			doc.update(
				{
					"item_code": row.item_code,
					"price_list": row.price_list,
					"uom": row.uom,
					"currency": price_lists_by_name[row.price_list].currency,
					"valid_from": nowdate(),
				}
			)
			frappe.has_permission("Item Price", "create", doc=doc, throw=True)
			action = "create"

		doc.price_list_rate = row.price_list_rate
		prepared.append((action, doc))

	# Validate the complete batch before the first write. Request rollback remains the
	# final safety net for validation or database errors raised during insert/save.
	for _action, doc in prepared:
		doc.run_method("validate")
	return prepared


@frappe.whitelist(methods=["POST"])
def save_prices(changes):
	_require_read_permissions()
	changes = _normalize_changes(changes)
	if not changes:
		return {"created": 0, "updated": 0, "unchanged": 0}

	lock_name = "hala:item-price-manager:save"
	with frappe.cache.lock(lock_name, timeout=120, blocking_timeout=15):
		_items, price_lists = _validate_master_data(changes)
		prepared = _prepare_documents(changes, price_lists)
		result = {"created": 0, "updated": 0, "unchanged": 0}
		frappe.db.savepoint("hala_item_price_manager")
		try:
			for action, doc in prepared:
				precision = doc.precision("price_list_rate")
				if action == "update" and flt(doc.get_db_value("price_list_rate"), precision) == flt(
					doc.price_list_rate, precision
				):
					result["unchanged"] += 1
					continue
				if action == "create":
					doc.insert()
					result["created"] += 1
				else:
					doc.save()
					result["updated"] += 1
		except Exception:
			frappe.db.rollback(save_point="hala_item_price_manager")
			raise
		finally:
			frappe.db.release_savepoint("hala_item_price_manager")
	return result
