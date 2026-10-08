"""Customer-aware pricing integration for POS Next.

The POS profile remains unchanged.  An effective selling price list is resolved
for each cart/customer and is revalidated when the invoice draft is created.
"""

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate


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


def _pricing_date_metadata(current_datetime=None):
	"""Return the site date and delay to its next midnight."""
	current_datetime = current_datetime or now_datetime()
	next_midnight = current_datetime.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
		days=1
	)
	return {
		"pricing_date": current_datetime.date().isoformat(),
		# Refresh just after site midnight; client clock/timezone is irrelevant.
		"date_refresh_ms": max(
			1000, int((next_midnight - current_datetime).total_seconds() * 1000) + 1000
		),
	}


@frappe.whitelist()
def get_pricing_context(customer=None, pos_profile=None):
	"""Return server-authoritative context used by the POS pricing cache."""
	return {
		"price_list": resolve_effective_price_list(customer=customer, pos_profile=pos_profile),
		**_pricing_date_metadata(),
	}


def _build_pricing_context(customer=None, pos_profile=None, transaction_date=None):
	"""Resolve batch-wide pricing inputs once without changing ERPNext's item logic."""
	pos_profile = _normalise_pos_profile(pos_profile)
	if not pos_profile:
		frappe.throw(_("POS Profile is required"))

	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	price_list = resolve_effective_price_list(customer=customer, pos_profile=pos_profile)
	posting_date = transaction_date or nowdate()
	return frappe._dict(
		{
			"customer": customer,
			"pos_profile": pos_profile,
			"profile": profile,
			"price_list": price_list,
			"posting_date": posting_date,
			"doc": frappe._dict(
				{
					"doctype": "Sales Invoice",
					"company": profile.company,
					"customer": customer,
					"selling_price_list": price_list,
					"posting_date": posting_date,
					"transaction_date": posting_date,
					"is_pos": 1,
					"pos_profile": pos_profile,
				}
			),
		}
	)


def _get_customer_specific_price_list_rate(
	item_code,
	price_list,
	customer,
	transaction_date,
	qty,
	uom,
	stock_uom,
	conversion_factor=1,
	batch_no=None,
	variant_of=None,
	plc_conversion_rate=1,
	conversion_rate=1,
):
	"""Return an applicable party-specific Item Price, or ``None``.

	ERPNext intentionally lets both party-specific and generic Item Price rows
	participate in one query.  In the installed version, ``valid_from`` is sorted
	before party specificity, so a newer generic row can hide an older customer
	row.  Hala's configured contract is the opposite: an applicable customer row
	wins, while ERPNext remains responsible for eligibility, UOM conversion,
	currency conversion, and the generic fallback.
	"""
	if not customer or not price_list:
		return None

	from erpnext.stock.get_item_details import _get_item_price_query, _order_item_prices

	price_list_uom_dependant = cint(
		frappe.get_cached_value("Price List", price_list, "price_list_uom_dependant") or 0
	)
	requested_uom = uom or stock_uom or ""
	query_uoms = [requested_uom]
	if stock_uom and stock_uom != requested_uom:
		query_uoms.append(stock_uom)

	for candidate_item_code in filter(None, (item_code, variant_of)):
		for query_uom in query_uoms:
			price_context = frappe._dict(
				{
					"item_code": candidate_item_code,
					"price_list": price_list,
					"customer": customer,
					"uom": query_uom,
					"transaction_date": transaction_date,
					"batch_no": batch_no,
				}
			)
			query, item_price = _get_item_price_query(
				price_context, [candidate_item_code]
			)
			query = query.where(item_price.customer == customer).select(
				item_price.name,
				item_price.price_list_rate,
				item_price.uom,
				item_price.packing_unit,
			)
			candidates = _order_item_prices(query, item_price, price_context).run(
				as_dict=True
			)

			for candidate in candidates:
				packing_unit = flt(candidate.packing_unit)
				if packing_unit and flt(qty) % packing_unit:
					continue

				rate = flt(candidate.price_list_rate)
				if (candidate.uom or stock_uom) != requested_uom and not price_list_uom_dependant:
					rate *= flt(conversion_factor) or 1
				rate *= (flt(plc_conversion_rate) or 1) / (flt(conversion_rate) or 1)
				return rate

	return None


def _apply_customer_specific_price(details, item_doc, context, qty, uom):
	"""Prefer a valid customer Item Price, then re-run ERPNext Pricing Rules."""
	from erpnext.accounts.doctype.pricing_rule.pricing_rule import (
		get_pricing_rule_for_item,
		set_transaction_type,
	)
	from erpnext.stock.get_item_details import remove_standard_fields

	requested_uom = uom or details.get("uom") or item_doc.stock_uom
	price_list_rate = _get_customer_specific_price_list_rate(
		item_code=item_doc.name,
		variant_of=item_doc.variant_of,
		price_list=context.price_list,
		customer=context.customer,
		transaction_date=context.posting_date,
		qty=qty,
		uom=requested_uom,
		stock_uom=item_doc.stock_uom,
		conversion_factor=details.get("conversion_factor") or 1,
		batch_no=details.get("batch_no"),
		plc_conversion_rate=details.get("plc_conversion_rate") or 1,
		conversion_rate=details.get("conversion_rate") or 1,
	)
	if price_list_rate is None:
		return details

	details["price_list_rate"] = price_list_rate
	pricing_args = frappe._dict(context.doc.copy())
	pricing_args.update(details)
	pricing_args.update(
		{
			"item_code": item_doc.name,
			"qty": qty,
			"uom": requested_uom,
			"price_list": context.price_list,
			"selling_price_list": context.price_list,
			"price_list_rate": price_list_rate,
			"transaction_date": context.posting_date,
			"posting_date": context.posting_date,
			"customer": context.customer,
			"is_pos": 1,
			"pos_profile": context.pos_profile,
			"currency": details.get("price_list_currency")
			or context.profile.get("currency"),
		}
	)
	set_transaction_type(pricing_args)
	pricing_details = get_pricing_rule_for_item(
		pricing_args, doc=frappe._dict(context.doc.copy())
	)
	if pricing_details:
		details.update(remove_standard_fields(pricing_details))
	return details


def _get_customer_item_details(
	item_code,
	pos_profile,
	customer=None,
	qty=1,
	uom=None,
	transaction_date=None,
	pricing_context=None,
):
	from pos_next.api.items import get_item_detail

	context = pricing_context or _build_pricing_context(
		customer=customer,
		pos_profile=pos_profile,
		transaction_date=transaction_date,
	)
	pos_profile = context.pos_profile
	profile = context.profile
	item_doc = frappe.get_cached_doc("Item", item_code)
	if not item_doc.is_sales_item:
		frappe.throw(_("Item {0} is not allowed for sales").format(item_code))

	effective_price_list = context.price_list
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
		# POS Next enriches the invoice context with currency fields. Keep a fresh
		# object per item so one calculation cannot leak mutable state into another.
		doc=frappe._dict(context.doc.copy()),
		warehouse=profile.warehouse,
		price_list=effective_price_list,
		company=profile.company,
	)
	_apply_customer_specific_price(details, item_doc, context, qty, uom)
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
def get_catalog_prices(customer=None, pos_profile=None, items=None, transaction_date=None):
	"""Return the effective list and display prices for visible POS items."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to use the POS"), frappe.PermissionError)

	items = json.loads(items) if isinstance(items, str) else items or []
	if not isinstance(items, list) or len(items) > 100:
		frappe.throw(_("Up to 100 items can be priced at once"), frappe.ValidationError)

	# Validate and deduplicate before entering the expensive ERPNext pricing path.
	# Quantity is part of the key because Pricing Rules may use quantity slabs.
	normalized_items = []
	unique_items = {}
	for item in items:
		if not isinstance(item, dict) or not item.get("item_code"):
			frappe.throw(_("An item code is required"), frappe.ValidationError)
		item_code = item["item_code"]
		uom = item.get("uom") or ""
		qty = flt(item.get("qty") or 1)
		pricing_key = (item_code, uom, qty)
		normalized_items.append((item, pricing_key))
		unique_items.setdefault(
			pricing_key,
			{"item_code": item_code, "uom": uom or None, "qty": qty},
		)

	date_metadata = _pricing_date_metadata()
	context = _build_pricing_context(
		customer=customer,
		pos_profile=pos_profile,
		# Kept in the method signature for API compatibility, but catalog pricing
		# always uses the site's current date instead of a cashier/browser value.
		transaction_date=date_metadata["pricing_date"],
	)
	price_list = context.price_list
	calculated_prices = {}
	for pricing_key, item in unique_items.items():
		details = _get_customer_item_details(
			item_code=item["item_code"],
			pos_profile=context.pos_profile,
			customer=customer,
			qty=item["qty"],
			uom=item["uom"],
			transaction_date=context.posting_date,
			pricing_context=context,
		)
		calculated_prices[pricing_key] = {
			"rate": flt(details.get("price_list_rate") or details.get("rate") or 0),
			"uom": details.get("uom") or item["uom"],
		}

	# Keep the existing item-code map unchanged for old clients. The request-key
	# map lets the new client distinguish the same item requested with another UOM
	# or quantity without changing the public response contract.
	prices = {}
	prices_by_request = {}
	for item, pricing_key in normalized_items:
		price = calculated_prices[pricing_key]
		prices[item["item_code"]] = price
		request_key = item.get("request_key")
		if isinstance(request_key, str) and request_key:
			prices_by_request[request_key] = price

	return {
		"price_list": price_list,
		**date_metadata,
		"prices": prices,
		"prices_by_request": prices_by_request,
	}


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
	from hala.api.pos_next_security import _secured_invoice_payload

	payload = _secured_invoice_payload(data)
	payload = json.loads(payload) if isinstance(payload, str) else dict(payload)
	effective_price_list = resolve_effective_price_list(
		customer=payload.get("customer"), pos_profile=payload.get("pos_profile")
	)
	payload["selling_price_list"] = effective_price_list
	_validate_submitted_price_list_rates(payload, effective_price_list)
	return pos_next_update_invoice(payload)
