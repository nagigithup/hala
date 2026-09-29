"""Customer-aware pricing integration for POS Next.

The POS profile remains unchanged.  An effective selling price list is resolved
for each cart/customer and is revalidated when the invoice draft is created.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate


FINAL_FALLBACK_PRICE_LIST = "Standard Selling"


def _normalise_pos_profile(pos_profile):
	if isinstance(pos_profile, str):
		try:
			parsed = json.loads(pos_profile)
		except (TypeError, ValueError):
			parsed = pos_profile
		pos_profile = parsed

	if isinstance(pos_profile, dict):
		return pos_profile.get("name") or pos_profile.get("pos_profile")
	return pos_profile


def resolve_effective_price_list(customer=None, pos_profile=None):
	"""Resolve the selling price list without mutating Customer or POS Profile.

	Use the customer's own list, or Standard Selling when none is assigned.
	"""
	pos_profile = _normalise_pos_profile(pos_profile)
	price_list = None

	if customer:
		if not frappe.db.exists("Customer", customer):
			frappe.throw(_("Customer {0} does not exist").format(customer))
		customer_doc = frappe.get_cached_doc("Customer", customer)
		price_list = customer_doc.default_price_list

	if not price_list and frappe.db.exists("Price List", FINAL_FALLBACK_PRICE_LIST):
		price_list = FINAL_FALLBACK_PRICE_LIST

	if not price_list and pos_profile:
		if not frappe.db.exists("POS Profile", pos_profile):
			frappe.throw(_("POS Profile {0} does not exist").format(pos_profile))
		price_list = frappe.get_cached_value("POS Profile", pos_profile, "selling_price_list")

	if not price_list:
		price_list = frappe.get_single_value("Selling Settings", "selling_price_list")

	if not price_list:
		frappe.throw(_("No selling Price List is configured"))

	price_list_details = frappe.db.get_value(
		"Price List", price_list, ["enabled", "selling"], as_dict=True
	)
	if not price_list_details or not cint(price_list_details.enabled) or not cint(price_list_details.selling):
		frappe.throw(_("Price List {0} is disabled or is not a selling Price List").format(price_list))

	return price_list


@frappe.whitelist()
def get_effective_price_list(customer=None, pos_profile=None):
	"""Return the server-resolved price list for the current POS cart."""
	return {
		"price_list": resolve_effective_price_list(customer=customer, pos_profile=pos_profile)
	}


def _get_customer_item_details(
	item_code,
	pos_profile,
	customer=None,
	qty=1,
	uom=None,
	transaction_date=None,
):
	from pos_next.api.items import get_item_detail

	pos_profile = _normalise_pos_profile(pos_profile)
	if not pos_profile:
		frappe.throw(_("POS Profile is required"))

	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	item_doc = frappe.get_cached_doc("Item", item_code)
	if not item_doc.is_sales_item:
		frappe.throw(_("Item {0} is not allowed for sales").format(item_code))

	effective_price_list = resolve_effective_price_list(
		customer=customer, pos_profile=pos_profile
	)
	posting_date = transaction_date or nowdate()
	doc = frappe._dict(
		{
			"doctype": "Sales Invoice",
			"company": profile.company,
			"customer": customer,
			"selling_price_list": effective_price_list,
			"posting_date": posting_date,
			"transaction_date": posting_date,
			"is_pos": 1,
			"pos_profile": pos_profile,
		}
	)
	item = {
		"item_code": item_code,
		"has_batch_no": item_doc.has_batch_no,
		"has_serial_no": item_doc.has_serial_no,
		"is_stock_item": item_doc.is_stock_item,
		"pos_profile": pos_profile,
		"customer": customer,
		"qty": qty,
	}
	if uom:
		item["uom"] = uom

	details = get_item_detail(
		item=item,
		doc=doc,
		warehouse=profile.warehouse,
		price_list=effective_price_list,
		company=profile.company,
	)
	details["selling_price_list"] = effective_price_list
	details["effective_price_list"] = effective_price_list
	return details


@frappe.whitelist()
def get_item_details(
	item_code,
	pos_profile,
	customer=None,
	qty=1,
	uom=None,
	transaction_date=None,
):
	"""POS Next item details using the effective customer selling price list."""
	try:
		return _get_customer_item_details(
			item_code=item_code,
			pos_profile=pos_profile,
			customer=customer,
			qty=qty,
			uom=uom,
			transaction_date=transaction_date,
		)
	except Exception as error:
		frappe.log_error(frappe.get_traceback(), "Hala POS Item Details Error")
		frappe.throw(_("Error fetching item details: {0}").format(str(error)))


@frappe.whitelist()
def get_catalog_prices(customer=None, pos_profile=None, items=None):
	"""Return the effective list and display prices for visible POS items."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to use the POS"), frappe.PermissionError)

	items = json.loads(items) if isinstance(items, str) else items or []
	if not isinstance(items, list) or len(items) > 100:
		frappe.throw(_("Up to 100 items can be priced at once"), frappe.ValidationError)

	price_list = resolve_effective_price_list(customer=customer, pos_profile=pos_profile)
	prices = {}
	for item in items:
		if not isinstance(item, dict) or not item.get("item_code"):
			frappe.throw(_("An item code is required"), frappe.ValidationError)
		item_code = item["item_code"]
		details = _get_customer_item_details(
			item_code=item_code,
			pos_profile=pos_profile,
			customer=customer,
			uom=item.get("uom"),
		)
		prices[item_code] = {
			"rate": flt(details.get("price_list_rate") or details.get("rate") or 0),
			"uom": details.get("uom") or item.get("uom"),
		}
	return {"price_list": price_list, "prices": prices}


def _validate_submitted_price_list_rates(data, effective_price_list):
	"""Reject stale/tampered catalog rates while preserving allowed manual edits."""
	for item in data.get("items") or []:
		if cint(item.get("is_free_item")) or cint(item.get("is_rate_manually_edited")):
			continue

		details = _get_customer_item_details(
			item_code=item.get("item_code"),
			pos_profile=data.get("pos_profile"),
			customer=data.get("customer"),
			qty=item.get("qty") or 1,
			uom=item.get("uom"),
			transaction_date=data.get("posting_date") or data.get("transaction_date"),
		)
		expected_rate = flt(details.get("price_list_rate") or details.get("rate") or 0, 6)
		submitted_rate = flt(item.get("price_list_rate") or 0, 6)
		if abs(expected_rate - submitted_rate) > 0.000001:
			frappe.throw(
				_(
					"Price for item {0} is stale or does not match Price List {1}. "
					"Refresh the cart and try again."
				).format(item.get("item_code"), effective_price_list),
				frappe.ValidationError,
			)


@frappe.whitelist()
def update_invoice(data):
	"""Enforce customer price-list selection before POS Next saves a draft."""
	from pos_next.api.invoices import update_invoice as pos_next_update_invoice

	payload = json.loads(data) if isinstance(data, str) else dict(data)
	effective_price_list = resolve_effective_price_list(
		customer=payload.get("customer"), pos_profile=payload.get("pos_profile")
	)
	payload["selling_price_list"] = effective_price_list
	_validate_submitted_price_list_rates(payload, effective_price_list)
	return pos_next_update_invoice(payload)
