from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import escape_html, flt, formatdate, get_link_to_form, getdate, nowdate


def execute(filters=None):
	frappe.has_permission("Stock Entry", "read", throw=True)
	filters = _validate_filters(filters)
	entries = _get_stock_entries(filters)
	details = _get_stock_entry_details([entry.name for entry in entries])
	transactions = _get_transactions(entries, details, filters)
	columns = _get_columns()
	data = _get_rows(transactions)
	message = _get_finished_item_summary(transactions)
	report_summary = _get_report_summary(transactions, filters)
	return columns, data, message, None, report_summary


def _validate_filters(filters):
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.from_date or nowdate())
	filters.to_date = getdate(filters.to_date or nowdate())
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date."))
	return filters


def _get_stock_entries(filters):
	entry_filters = {
		"docstatus": 1,
		"purpose": "Manufacture",
		"posting_date": ("between", [filters.from_date, filters.to_date]),
	}
	if filters.company:
		entry_filters["company"] = filters.company
	if filters.bom:
		entry_filters["bom_no"] = filters.bom

	return frappe.get_list(
		"Stock Entry",
		filters=entry_filters,
		fields=["name", "posting_date", "posting_time", "company", "bom_no", "work_order"],
		order_by="posting_date desc, posting_time desc, name desc",
		limit=0,
	)


def _get_stock_entry_details(stock_entries):
	if not stock_entries:
		return {}

	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ("in", stock_entries), "parenttype": "Stock Entry"},
		fields=[
			"name",
			"parent",
			"idx",
			"item_code",
			"item_name",
			"qty",
			"transfer_qty",
			"uom",
			"stock_uom",
			"s_warehouse",
			"t_warehouse",
			"is_finished_item",
			"basic_rate",
			"basic_amount",
		],
		order_by="parent, idx",
		limit=0,
	)
	details = defaultdict(list)
	for row in rows:
		details[row.parent].append(row)
	return details


def _get_transactions(entries, details, filters):
	transactions = []
	for entry in entries:
		entry_rows = details.get(entry.name, [])
		finished_rows = [row for row in entry_rows if row.is_finished_item and row.t_warehouse]
		raw_material_rows = [row for row in entry_rows if row.s_warehouse and not row.is_finished_item]
		if not finished_rows:
			continue
		if filters.finished_item and not any(
			row.item_code == filters.finished_item for row in finished_rows
		):
			continue
		if filters.source_warehouse and not any(
			row.s_warehouse == filters.source_warehouse for row in raw_material_rows
		):
			continue
		if filters.target_warehouse and not any(
			row.t_warehouse == filters.target_warehouse for row in finished_rows
		):
			continue

		currency = frappe.get_cached_value("Company", entry.company, "default_currency")
		transactions.append(
			frappe._dict(
				entry=entry,
				finished_rows=finished_rows,
				raw_material_rows=raw_material_rows,
				currency=currency,
				finished_value=sum(abs(flt(row.basic_amount)) for row in finished_rows),
				raw_material_value=sum(abs(flt(row.basic_amount)) for row in raw_material_rows),
			)
		)
	return transactions


def _get_rows(transactions):
	data = []
	for transaction in transactions:
		entry = transaction.entry
		finished = transaction.finished_rows[0]
		data.append(
			{
				"row_id": entry.name,
				"parent_row": None,
				"indent": 0,
				"posting_date": entry.posting_date,
				"posting_time": entry.posting_time,
				"stock_entry": entry.name,
				"finished_item": finished.item_code,
				"finished_item_name": finished.item_name,
				"manufactured_qty": flt(finished.qty),
				"finished_uom": finished.uom,
				"target_warehouse": finished.t_warehouse,
				"bom": entry.bom_no,
				"work_order": entry.work_order,
				"finished_goods_value": transaction.finished_value,
				"currency": transaction.currency,
				"is_group": bool(transaction.raw_material_rows),
			}
		)
		for raw_material in transaction.raw_material_rows:
			data.append(
				{
					"row_id": f"{entry.name}::{raw_material.name}",
					"parent_row": entry.name,
					"indent": 1,
					"raw_material_item": raw_material.item_code,
					"raw_material_item_name": raw_material.item_name,
					"consumed_qty": flt(raw_material.qty),
					"raw_material_uom": raw_material.uom,
					"source_warehouse": raw_material.s_warehouse,
					"basic_rate": flt(raw_material.basic_rate),
					"consumed_value": abs(flt(raw_material.basic_amount)),
					"currency": transaction.currency,
					"is_group": False,
				}
			)
	return data


def _get_columns():
	return [
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 105},
		{"label": _("Posting Time"), "fieldname": "posting_time", "fieldtype": "Time", "width": 95},
		{
			"label": _("Stock Entry"),
			"fieldname": "stock_entry",
			"fieldtype": "Link",
			"options": "Stock Entry",
			"width": 165,
		},
		{
			"label": _("Finished Item Code"),
			"fieldname": "finished_item",
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
		{"label": _("Finished Item Name"), "fieldname": "finished_item_name", "width": 180},
		{
			"label": _("Manufactured Quantity"),
			"fieldname": "manufactured_qty",
			"fieldtype": "Float",
			"width": 135,
		},
		{
			"label": _("Finished Item UOM"),
			"fieldname": "finished_uom",
			"fieldtype": "Link",
			"options": "UOM",
			"width": 105,
		},
		{
			"label": _("Target Warehouse"),
			"fieldname": "target_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 170,
		},
		{"label": _("BOM"), "fieldname": "bom", "fieldtype": "Link", "options": "BOM", "width": 170},
		{
			"label": _("Work Order"),
			"fieldname": "work_order",
			"fieldtype": "Link",
			"options": "Work Order",
			"width": 160,
		},
		{
			"label": _("Finished Goods Value"),
			"fieldname": "finished_goods_value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 145,
		},
		{
			"label": _("Raw Material Item Code"),
			"fieldname": "raw_material_item",
			"fieldtype": "Link",
			"options": "Item",
			"width": 165,
		},
		{"label": _("Raw Material Item Name"), "fieldname": "raw_material_item_name", "width": 180},
		{"label": _("Consumed Qty"), "fieldname": "consumed_qty", "fieldtype": "Float", "width": 115},
		{
			"label": _("UOM"),
			"fieldname": "raw_material_uom",
			"fieldtype": "Link",
			"options": "UOM",
			"width": 90,
		},
		{
			"label": _("Source Warehouse"),
			"fieldname": "source_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 170,
		},
		{
			"label": _("Basic Rate"),
			"fieldname": "basic_rate",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 115,
		},
		{
			"label": _("Consumed Value"),
			"fieldname": "consumed_value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 125,
		},
	]


def _get_report_summary(transactions, filters):
	currency = (
		frappe.get_cached_value("Company", filters.company, "default_currency")
		if filters.company
		else frappe.defaults.get_global_default("currency")
	)
	finished_items = {
		row.item_code for transaction in transactions for row in transaction.finished_rows
	}
	return [
		{
			"label": _("Manufacturing Entries"),
			"value": len(transactions),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"label": _("Total Finished Goods Qty"),
			"value": sum(
				flt(row.qty) for transaction in transactions for row in transaction.finished_rows
			),
			"datatype": "Float",
			"indicator": "Green",
		},
		{
			"label": _("Different Finished Items"),
			"value": len(finished_items),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"label": _("Total Raw Material Consumption Value"),
			"value": sum(transaction.raw_material_value for transaction in transactions),
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Orange",
		},
		{
			"label": _("Total Finished Goods Value"),
			"value": sum(transaction.finished_value for transaction in transactions),
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Green",
		},
	]


def _get_finished_item_summary(transactions):
	grouped = {}
	for transaction in transactions:
		for finished in transaction.finished_rows:
			key = (transaction.entry.posting_date, finished.item_code, finished.uom)
			row = grouped.setdefault(
				key,
				{
					"posting_date": transaction.entry.posting_date,
					"item_code": finished.item_code,
					"item_name": finished.item_name,
					"uom": finished.uom,
					"qty": 0,
					"entries": set(),
				},
			)
			row["qty"] += flt(finished.qty)
			row["entries"].add(transaction.entry.name)

	if not grouped:
		return f'<div class="text-muted">{escape_html(_("No manufacturing entries found for the selected filters."))}</div>'

	sections = []
	for posting_date in sorted({key[0] for key in grouped}, reverse=True):
		rows = []
		for key, row in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
			if key[0] != posting_date:
				continue
			label = escape_html(f'{row["item_code"]} - {row["item_name"] or row["item_code"]}')
			item_link = get_link_to_form("Item", row["item_code"], label)
			rows.append(
				"<tr>"
				f"<td>{item_link}</td>"
				f'<td class="text-end">{row["qty"]:g}</td>'
				f'<td>{escape_html(row["uom"] or "")}</td>'
				f'<td class="text-end">{len(row["entries"])}</td>'
				"</tr>"
			)
		sections.append(
			f'<h5 class="mt-4">{escape_html(formatdate(posting_date))}</h5>'
			'<div class="table-responsive"><table class="table table-bordered table-sm">'
			"<thead><tr>"
			f"<th>{escape_html(_("Finished Item"))}</th>"
			f"<th>{escape_html(_("Total Manufactured Qty"))}</th>"
			f"<th>{escape_html(_("UOM"))}</th>"
			f"<th>{escape_html(_("Manufacturing Entries"))}</th>"
			"</tr></thead>"
			f'<tbody>{"".join(rows)}</tbody></table></div>'
		)

	return (
		'<div class="hala-daily-manufacturing-summary" dir="auto">'
		f'<h4>{escape_html(_("Manufacturing by Finished Item"))}</h4>'
		f'{"".join(sections)}</div>'
	)
