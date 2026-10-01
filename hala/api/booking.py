"""Hala's draft Sales Invoice booking workflow."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from hala.access import require_portal_access
from hala.api.pos_pricing import resolve_effective_price_list


AMOUNT_TOLERANCE = 0.005
BOOKING_STATUS_OPTIONS = ("تحت التجهيز", "تم الانتهاء", "ملغى", "مؤجل")
DEFAULT_BOOKING_STATUS = BOOKING_STATUS_OPTIONS[0]
COMPLETED_BOOKING_STATUS = BOOKING_STATUS_OPTIONS[1]


def _payload(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or {})


def _active_shift(required=True):
	from pos_next.api.shifts import check_opening_shift

	data = check_opening_shift(frappe.session.user)
	if not data and required:
		frappe.throw(
			_("No active POS opening shift found for this user.")
			+ "<br>"
			+ _("لا توجد وردية كاشير مفتوحة لهذا المستخدم.")
		)
	if data and data["pos_opening_shift"].user != frappe.session.user:
		frappe.throw(_("The active POS opening shift does not belong to this user."), frappe.PermissionError)
	return data


def _link_booking_to_pos_session(doc, shift_data):
	"""Expose a booking to POS Next without creating a POS payment."""
	shift = shift_data["pos_opening_shift"]
	profile = shift_data["pos_profile"]
	if profile.company != doc.company:
		frappe.throw(_("The active POS Profile company does not match the booking company."))

	doc.is_pos = 1
	doc.pos_profile = profile.name
	doc.posa_pos_opening_shift = shift.name
	# Booking payments are standalone Payment Entries. POS Profile payment rows
	# must never make saving a booking look like the cashier collected payment.
	doc.set("payments", [])


def _default_payment_method(profile):
	defaults = sorted(
		(row for row in profile.get("payments") or [] if cint(row.get("default"))),
		key=lambda row: row.idx,
	)
	if not defaults:
		frappe.throw(_("No default payment method is configured for POS Profile {0}.").format(profile.name))
	return defaults[0].mode_of_payment


def _booking_payments(name, for_update=False):
	lock = " FOR UPDATE" if for_update else ""
	return frappe.db.sql(
		f"""
			SELECT name, paid_amount, base_paid_amount, unallocated_amount,
			       paid_from, source_exchange_rate
			FROM `tabPayment Entry`
			WHERE custom_booking_invoice = %s
			  AND docstatus = 1
			  AND payment_type = 'Receive'
			ORDER BY creation, name{lock}
		""",
		(name,),
		as_dict=True,
	)


def _paid_in_invoice_currency(doc, payments):
	paid = sum(flt(row.paid_amount) for row in payments)
	if doc.get("party_account_currency") == doc.currency:
		return paid
	if doc.currency != doc.get("company_currency") and flt(doc.conversion_rate):
		return sum(flt(row.base_paid_amount) for row in payments) / flt(doc.conversion_rate)
	return paid


def _calculate_booking_payment(tendered, outstanding, precision=2):
	"""Split cash received into accounting payment, remaining due, and change."""
	tendered = flt(tendered, precision)
	outstanding = max(flt(outstanding, precision), 0)
	accounting_amount = min(tendered, outstanding)
	return {
		"accounting_amount": flt(accounting_amount, precision),
		"remaining_amount": flt(max(outstanding - accounting_amount, 0), precision),
		"change_amount": flt(max(tendered - accounting_amount, 0), precision),
	}


def _get_default_sales_invoice_print_format():
	"""Return the configured Sales Invoice default used by every print path."""
	return frappe.get_meta("Sales Invoice").default_print_format or "Standard"


def _apply_standard_sales_tax_defaults(doc):
	"""Apply the same party tax rule/default template used by a Sales Invoice form."""
	from erpnext.accounts.party import get_party_details
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	party_details = get_party_details(
		party=doc.customer,
		party_type="Customer",
		company=doc.company,
		posting_date=doc.posting_date,
		price_list=doc.selling_price_list,
		currency=doc.currency,
		doctype=doc.doctype,
	)
	for fieldname in (
		"customer_name",
		"customer_group",
		"territory",
		"tax_category",
		"customer_address",
		"address_display",
		"shipping_address_name",
		"shipping_address",
		"company_address",
		"company_address_display",
		"debit_to",
		"due_date",
		"currency",
		"selling_price_list",
		"payment_terms_template",
	):
		if fieldname in party_details:
			doc.set(fieldname, party_details.get(fieldname))

	# A matching Tax Rule (including customer/tax-category/address rules) takes
	# priority. Without one, use ERPNext's normal company default template.
	tax_template = party_details.get("taxes_and_charges") or frappe.db.get_value(
		"Sales Taxes and Charges Template", {"is_default": 1, "company": doc.company}
	)
	doc.taxes_and_charges = tax_template
	doc.set(
		"taxes",
		get_taxes_and_charges("Sales Taxes and Charges Template", tax_template) if tax_template else [],
	)


def _make_booking_taxes_inclusive(doc):
	"""Treat catalog prices as VAT-inclusive for Hala bookings."""
	for tax in doc.get("taxes") or []:
		# ERPNext cannot include a fixed Actual charge in an item's print rate.
		tax.included_in_print_rate = 0 if tax.charge_type == "Actual" else 1


@frappe.whitelist()
def get_open_bookings():
	require_portal_access()
	frappe.has_permission("Sales Invoice", "read", throw=True)
	bookings = frappe.get_list(
		"Sales Invoice",
		filters={"docstatus": 0, "custom_is_booking": 1},
		fields=[
			"name",
			"customer",
			"customer_name",
			"posting_date",
			"custom_delivery_date",
			"custom_booking_status",
			"grand_total",
			"currency",
			"company_currency",
			"party_account_currency",
			"conversion_rate",
		],
		order_by="creation desc",
		limit=0,
	)
	if not bookings:
		return []

	payment_rows = frappe.db.sql(
		"""
			SELECT custom_booking_invoice, paid_amount, base_paid_amount
			FROM `tabPayment Entry`
			WHERE custom_booking_invoice IN %(bookings)s
			  AND docstatus = 1
			  AND payment_type = 'Receive'
		""",
		{"bookings": tuple(row.name for row in bookings)},
		as_dict=True,
	)
	payments_by_booking = {}
	for payment in payment_rows:
		payments_by_booking.setdefault(payment.custom_booking_invoice, []).append(payment)

	result = []
	for booking in bookings:
		paid = _paid_in_invoice_currency(booking, payments_by_booking.get(booking.name, []))
		result.append(
			{
				"name": booking.name,
				"customer": booking.customer,
				"customer_name": booking.customer_name or booking.customer,
				"posting_date": booking.posting_date,
				"delivery_date": booking.custom_delivery_date,
				"booking_status": booking.custom_booking_status or DEFAULT_BOOKING_STATUS,
				"grand_total": flt(booking.grand_total),
				"paid_amount": paid,
				"remaining_amount": max(flt(booking.grand_total) - paid, 0),
				"currency": booking.currency,
			}
		)
	return result


def _summary(doc):
	payments = _booking_payments(doc.name) if doc.name else []
	paid = _paid_in_invoice_currency(doc, payments)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"custom_is_booking": cint(doc.get("custom_is_booking")),
		"customer": doc.customer,
		"posting_date": doc.posting_date,
		"delivery_date": doc.get("custom_delivery_date"),
		"booking_status": doc.get("custom_booking_status") or DEFAULT_BOOKING_STATUS,
		"company": doc.company,
		"currency": doc.currency,
		"net_total": flt(doc.net_total),
		"tax": flt(doc.total_taxes_and_charges),
		"grand_total": flt(doc.grand_total),
		"paid_amount": paid,
		"remaining_amount": max(flt(doc.grand_total) - paid, 0),
		"print_format": _get_default_sales_invoice_print_format(),
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"uom": row.uom,
				"rate": flt(row.rate),
				"amount": flt(row.amount),
			}
			for row in doc.get("items") or []
		],
		"payments": payments,
	}


def _get_booking(name, permission="read"):
	doc = frappe.get_doc("Sales Invoice", name)
	doc.check_permission(permission)
	if doc.docstatus == 0 and not cint(doc.get("custom_is_booking")):
		frappe.throw(_("Sales Invoice {0} is not a Hala booking.").format(name))
	return doc


@frappe.whitelist()
def get_booking(name=None, company=None):
	require_portal_access()
	if name:
		return _summary(_get_booking(name))

	frappe.has_permission("Sales Invoice", "create", throw=True)
	shift = _active_shift(required=False)
	profile = shift["pos_profile"] if shift else None
	company = profile.company if profile else (company or frappe.defaults.get_user_default("Company"))
	return {
		"name": None,
		"docstatus": 0,
		"custom_is_booking": 1,
		"customer": None,
		"posting_date": nowdate(),
		"delivery_date": nowdate(),
		"booking_status": DEFAULT_BOOKING_STATUS,
		"company": company,
		"currency": (
			profile.currency
			if profile
			else frappe.get_cached_value("Company", company, "default_currency")
		),
		"net_total": 0,
		"tax": 0,
		"grand_total": 0,
		"paid_amount": 0,
		"remaining_amount": 0,
		"items": [],
		"payments": [],
	}


@frappe.whitelist()
def get_booking_item(item_code, customer=None, qty=1, posting_date=None):
	require_portal_access()
	frappe.has_permission("Item", "read", item_code, throw=True)
	shift = _active_shift(required=True)
	from hala.api.pos_pricing import _get_customer_item_details

	details = _get_customer_item_details(
		item_code=item_code,
		pos_profile=shift["pos_profile"].name,
		customer=customer,
		qty=flt(qty) or 1,
		transaction_date=posting_date or nowdate(),
	)
	return {
		"item_code": item_code,
		"item_name": details.get("item_name") or item_code,
		"uom": details.get("uom"),
		"rate": flt(details.get("rate") or details.get("price_list_rate")),
	}


@frappe.whitelist(methods=["POST"])
def save_booking(booking):
	require_portal_access()
	data = _payload(booking)
	name = data.get("name")
	if name:
		doc = _get_booking(name, "write")
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft booking can be edited."))
		existing_payments = _booking_payments(doc.name)
		if existing_payments and data.get("customer") != doc.customer:
			frappe.throw(_("The customer cannot be changed after a booking payment exists."))
	else:
		frappe.has_permission("Sales Invoice", "create", throw=True)
		doc = frappe.new_doc("Sales Invoice")

	if not data.get("customer"):
		frappe.throw(_("Customer is required."))
	frappe.has_permission("Customer", "read", data["customer"], throw=True)
	items = data.get("items") or []
	if not items:
		frappe.throw(_("At least one item is required."))

	shift = _active_shift(required=True)
	profile = shift["pos_profile"]
	company = profile.company
	if not company:
		frappe.throw(_("Company is required."))

	doc.company = company
	doc.customer = data["customer"]
	doc.posting_date = data.get("posting_date") or nowdate()
	doc.custom_delivery_date = data.get("delivery_date") or doc.posting_date
	doc.custom_is_booking = 1
	booking_status = data.get("booking_status") or DEFAULT_BOOKING_STATUS
	if booking_status not in BOOKING_STATUS_OPTIONS:
		frappe.throw(_("Invalid booking status."))
	doc.custom_booking_status = booking_status
	doc.selling_price_list = resolve_effective_price_list(
		customer=doc.customer, pos_profile=profile.name
	)
	_apply_standard_sales_tax_defaults(doc)
	_make_booking_taxes_inclusive(doc)
	doc.set_warehouse = profile.warehouse
	_link_booking_to_pos_session(doc, shift)
	doc.set("items", [])
	for item in items:
		qty = flt(item.get("qty"))
		if qty <= 0:
			frappe.throw(_("Quantity must be greater than zero for item {0}.").format(item.get("item_code")))
		frappe.has_permission("Item", "read", item.get("item_code"), throw=True)
		doc.append("items", {"item_code": item.get("item_code"), "qty": qty, "uom": item.get("uom")})

	if name:
		doc.save()
	else:
		doc.insert()
	paid = _paid_in_invoice_currency(doc, _booking_payments(doc.name))
	if paid > flt(doc.grand_total) + AMOUNT_TOLERANCE:
		frappe.throw(_("The updated booking total cannot be less than its submitted payments."))
	return _summary(doc)


@frappe.whitelist(methods=["POST"])
def create_booking_payment(booking_name, amount, request_id):
	require_portal_access()
	if not request_id or len(request_id) > 80:
		frappe.throw(_("A valid payment request ID is required."))

	frappe.db.sql("SELECT name FROM `tabSales Invoice` WHERE name = %s FOR UPDATE", (booking_name,))
	doc = _get_booking(booking_name, "write")
	if doc.docstatus != 0 or not cint(doc.custom_is_booking):
		frappe.throw(_("Payments can only be added to a draft booking."))

	existing = frappe.db.get_value(
		"Payment Entry",
		{"custom_booking_payment_request_id": request_id},
		["name", "custom_booking_invoice"],
		as_dict=True,
	)
	if existing:
		if existing.custom_booking_invoice != doc.name:
			frappe.throw(_("This payment request ID has already been used."))
		return {"payment_entry": existing.name, **_summary(doc)}

	precision = doc.precision("grand_total")
	tendered_amount = flt(amount, precision)
	if tendered_amount <= 0:
		frappe.throw(_("Amount must be greater than zero."))
	paid = _paid_in_invoice_currency(doc, _booking_payments(doc.name, for_update=True))
	maximum = max(flt(doc.grand_total, precision) - flt(paid, precision), 0)
	payment = _calculate_booking_payment(tendered_amount, maximum, precision)
	accounting_amount = payment["accounting_amount"]
	if accounting_amount <= 0:
		frappe.throw(_("This booking is already fully paid."))

	shift_data = _active_shift(required=True)
	shift = shift_data["pos_opening_shift"]
	profile = shift_data["pos_profile"]
	if profile.company != doc.company:
		frappe.throw(_("The active POS Profile company does not match the booking company."))
	mode_of_payment = _default_payment_method(profile)

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	payment_account = get_bank_cash_account(mode_of_payment, doc.company)["account"]
	party_amount = accounting_amount
	if doc.get("party_account_currency") != doc.currency:
		party_amount = accounting_amount * flt(doc.conversion_rate or 1)
	pe = get_payment_entry(
		"Sales Invoice",
		doc.name,
		party_amount=party_amount,
		bank_account=payment_account,
		reference_date=nowdate(),
	)
	# get_payment_entry supplies the correct party/account/currency details, but a
	# draft invoice must never be persisted as an accounting reference.
	pe.set("references", [])
	pe.set("deductions", [])
	pe.paid_amount = party_amount
	pe.received_amount = (
		party_amount * flt(pe.source_exchange_rate or 1) / flt(pe.target_exchange_rate or 1)
	)
	pe.update(
		{
			"posting_date": nowdate(),
			"mode_of_payment": mode_of_payment,
			"reference_no": shift.name,
			"reference_date": nowdate(),
			"custom_booking_invoice": doc.name,
			"custom_booking_payment_request_id": request_id,
			"remarks": _("Advance payment for Hala booking {0}").format(doc.name),
		}
	)
	pe.set_amounts()
	pe.flags.ignore_permissions = True
	pe.insert()
	pe.submit()
	return {
		"payment_entry": pe.name,
		"tendered_amount": tendered_amount,
		"accounting_amount": accounting_amount,
		"change_amount": payment["change_amount"],
		**_summary(doc),
	}


@frappe.whitelist(methods=["POST"])
def finalize_booking(booking_name):
	require_portal_access()
	frappe.db.sql("SELECT name FROM `tabSales Invoice` WHERE name = %s FOR UPDATE", (booking_name,))
	doc = _get_booking(booking_name, "submit")
	if doc.docstatus != 0 or not cint(doc.custom_is_booking):
		frappe.throw(_("Only a draft booking can be finalized."))
	if not doc.customer:
		frappe.throw(_("Customer is required."))
	if not doc.get("items"):
		frappe.throw(_("At least one item is required."))
	if any(flt(row.qty) <= 0 for row in doc.get("items")):
		frappe.throw(_("Every item quantity must be greater than zero."))
	_link_booking_to_pos_session(doc, _active_shift(required=True))
	doc.calculate_taxes_and_totals()
	paid = _paid_in_invoice_currency(doc, _booking_payments(doc.name, for_update=True))
	if paid > flt(doc.grand_total) + AMOUNT_TOLERANCE:
		frappe.throw(_("Booking payments exceed the Sales Invoice grand total."))
	doc.custom_booking_status = COMPLETED_BOOKING_STATUS
	# POS Next's existing credit-sale validation flag allows a POS invoice with
	# no payment rows. It does not create a payment or customer credit balance.
	doc.flags.pos_next_credit_sale = 1
	doc.submit()
	doc.reload()
	return _summary(doc)


def allocate_booking_advances(doc, method=None):
	"""Sales Invoice on_submit hook: reconcile linked advances using ERPNext's ledger API."""
	if not cint(doc.get("custom_is_booking")):
		return

	from erpnext.accounts.utils import reconcile_against_document

	outstanding = flt(doc.outstanding_amount)
	entries = []
	for payment in _booking_payments(doc.name, for_update=True):
		available = flt(payment.unallocated_amount)
		allocated = min(available, outstanding)
		if allocated <= 0:
			continue
		entries.append(
			frappe._dict(
				{
					"voucher_type": "Payment Entry",
					"voucher_no": payment.name,
					"voucher_detail_no": None,
					"against_voucher_type": "Sales Invoice",
					"against_voucher": doc.name,
					"account": doc.debit_to,
					"party_type": "Customer",
					"party": doc.customer,
					"is_advance": "Yes",
					"dr_or_cr": "credit_in_account_currency",
					"unreconciled_amount": available,
					"unadjusted_amount": available,
					"allocated_amount": allocated,
					"difference_amount": 0,
					"exchange_rate": flt(doc.conversion_rate or 1),
					"grand_total": flt(doc.grand_total),
					"outstanding_amount": outstanding,
					"difference_account": frappe.get_cached_value(
						"Company", doc.company, "exchange_gain_loss_account"
					),
					"difference_posting_date": doc.posting_date,
					"cost_center": doc.get("cost_center"),
					"dimensions": {},
				}
			)
		)
		outstanding -= allocated
	if entries:
		reconcile_against_document(entries)
	doc.db_set("custom_is_booking", 0, update_modified=False)


def prevent_booking_deletion_with_payments(doc, method=None):
	if cint(doc.get("custom_is_booking")) and _booking_payments(doc.name):
		frappe.throw(
			_(
				"Booking {0} has submitted advance payments and cannot be deleted. "
				"Handle those Payment Entries using standard ERPNext accounting rules first."
			).format(doc.name)
		)
