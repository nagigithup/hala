"""Refundable customer deposits backed by standard ERPNext Payment Entries."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from hala.access import require_portal_access
from hala.api.booking import _active_shift, _default_payment_method
from hala.cashier_profile import (
	is_cashier_isolation_user,
	validate_cashier_document,
	validate_cashier_profile,
)


DEPOSIT_STATUS_OPEN = "Open"
DEPOSIT_STATUS_PARTIAL = "Partially Refunded"
DEPOSIT_STATUS_REFUNDED = "Fully Refunded"
AMOUNT_TOLERANCE = 0.005


def _deposit_state(original_amount, refunded_amount, precision=2):
	original_amount = max(flt(original_amount, precision), 0)
	refunded_amount = max(flt(refunded_amount, precision), 0)
	balance = max(flt(original_amount - refunded_amount, precision), 0)
	if balance <= AMOUNT_TOLERANCE:
		balance = 0
		status = DEPOSIT_STATUS_REFUNDED
	elif refunded_amount > AMOUNT_TOLERANCE:
		status = DEPOSIT_STATUS_PARTIAL
	else:
		status = DEPOSIT_STATUS_OPEN
	return frappe._dict(
		refunded_amount=refunded_amount,
		balance=balance,
		status=status,
	)


def _validate_request_id(request_id):
	if not request_id or len(request_id) > 80:
		frappe.throw(_("A valid deposit request ID is required."))
	return request_id


def _validate_customer(customer):
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer is required."))
	frappe.has_permission("Customer", "read", customer, throw=True)


def _validate_item(item_code):
	if not item_code:
		return
	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Deposit Item does not exist."))
	frappe.has_permission("Item", "read", item_code, throw=True)


def _cashier_context(customer=None, shift_data=None):
	"""Resolve the active POS Profile and its explicitly configured payment account."""
	shift_data = shift_data or _active_shift(required=True)
	shift = shift_data["pos_opening_shift"]
	profile = shift_data["pos_profile"]
	company = profile.company
	mode_of_payment = _default_payment_method(profile)

	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	account_details = get_bank_cash_account(mode_of_payment, company)
	if not account_details or not account_details.get("account"):
		frappe.throw(
			_("No cash or bank account is configured for payment method {0} in company {1}.").format(
				frappe.bold(mode_of_payment), frappe.bold(company)
			)
		)

	payment_account = account_details["account"]
	payment_currency = account_details.get("account_currency") or frappe.get_cached_value(
		"Account", payment_account, "account_currency"
	)
	profile_currency = profile.get("currency") or frappe.get_cached_value(
		"Company", company, "default_currency"
	)
	if payment_currency != profile_currency:
		frappe.throw(
			_("The configured cashier account currency must match the POS Profile currency.")
		)

	party_account = None
	party_currency = None
	if customer:
		from erpnext.accounts.party import get_party_account

		party_account = get_party_account("Customer", customer, company)
		party_currency = frappe.get_cached_value("Account", party_account, "account_currency")
		if party_currency != payment_currency:
			frappe.throw(
				_("The customer account currency must match the active cashier account currency.")
			)

	return frappe._dict(
		shift=shift,
		profile=profile,
		company=company,
		currency=payment_currency,
		mode_of_payment=mode_of_payment,
		payment_account=payment_account,
		party_account=party_account,
		party_currency=party_currency,
	)


def _eligible_refund_cashiers(original):
	"""Return active cashiers in the original deposit's POS Profile (branch scope)."""
	profile = original.get("custom_cashier_profile")
	if not profile:
		frappe.throw(_("The original deposit has no Cashier Profile."))

	preliminary_closed_condition = (
		"AND IFNULL(opening.custom_preliminary_closed, 0) = 0"
		if frappe.db.has_column("POS Opening Shift", "custom_preliminary_closed")
		else ""
	)
	rows = frappe.db.sql(
		f"""
			SELECT opening.name AS pos_opening_shift,
			       opening.user,
			       opening.pos_profile,
			       user.full_name
			FROM `tabPOS Opening Shift` opening
			INNER JOIN `tabPOS Profile` profile
			        ON profile.name = opening.pos_profile
			       AND profile.disabled = 0
			INNER JOIN `tabPOS Profile User` profile_user
			        ON profile_user.parent = opening.pos_profile
			       AND profile_user.parenttype = 'POS Profile'
			       AND profile_user.user = opening.user
			INNER JOIN `tabUser` user
			        ON user.name = opening.user
			       AND user.enabled = 1
			LEFT JOIN `tabCashier Preliminary Closing` preliminary
			       ON preliminary.pos_opening_shift = opening.name
			      AND preliminary.docstatus < 2
			LEFT JOIN `tabPOS Closing Shift` closing
			       ON closing.pos_opening_shift = opening.name
			      AND closing.docstatus < 2
			WHERE opening.pos_profile = %s
			  AND opening.company = %s
			  AND opening.docstatus = 1
			  AND opening.status = 'Open'
			  AND IFNULL(opening.pos_closing_shift, '') = ''
			  {preliminary_closed_condition}
			  AND preliminary.name IS NULL
			  AND closing.name IS NULL
			ORDER BY opening.period_start_date DESC, opening.name DESC
		""",
		(profile, original.company),
		as_dict=True,
	)

	# Match POS Next's one-current-shift-per-user behavior if historical data
	# contains more than one open shift for the same cashier.
	result = []
	seen = set()
	for row in rows:
		if row.user in seen:
			continue
		seen.add(row.user)
		result.append(
			frappe._dict(
				user=row.user,
				cashier_name=row.full_name or row.user,
				pos_profile=row.pos_profile,
				pos_opening_shift=row.pos_opening_shift,
			)
		)
	return result


def _refund_cashier_selection(original):
	cashiers = _eligible_refund_cashiers(original)
	original_cashier = frappe.db.get_value(
		"POS Opening Shift", original.reference_no, "user"
	)
	eligible_users = {row.user for row in cashiers}
	default_cashier = None
	if original_cashier in eligible_users:
		default_cashier = original_cashier
	elif frappe.session.user in eligible_users:
		default_cashier = frappe.session.user
	return frappe._dict(cashiers=cashiers, default_cashier=default_cashier)


def _resolve_refund_shift(original, cashier=None):
	selection = _refund_cashier_selection(original)
	if not selection.cashiers:
		frappe.throw(
			_("No eligible cashier with an active shift exists for this deposit branch."),
			frappe.PermissionError,
		)

	cashier = cashier or selection.default_cashier
	if not cashier:
		frappe.throw(_("Select an eligible cashier with an active shift."))
	selected = next((row for row in selection.cashiers if row.user == cashier), None)
	if not selected:
		frappe.throw(
			_("The selected cashier is not authorized for this deposit branch or has no active shift."),
			frappe.PermissionError,
		)

	# Lock and recheck the authoritative shift before resolving its accounts.
	preliminary_closed_condition = (
		"AND IFNULL(opening.custom_preliminary_closed, 0) = 0"
		if frappe.db.has_column("POS Opening Shift", "custom_preliminary_closed")
		else ""
	)
	locked = frappe.db.sql(
		f"""
			SELECT opening.name
			FROM `tabPOS Opening Shift` opening
			WHERE opening.name = %s
			  AND opening.user = %s
			  AND opening.pos_profile = %s
			  AND opening.company = %s
			  AND opening.docstatus = 1
			  AND opening.status = 'Open'
			  AND IFNULL(opening.pos_closing_shift, '') = ''
			  {preliminary_closed_condition}
			  AND EXISTS (
				SELECT 1 FROM `tabPOS Profile` profile
				WHERE profile.name = opening.pos_profile
				  AND profile.company = opening.company
				  AND profile.disabled = 0
			  )
			  AND EXISTS (
				SELECT 1 FROM `tabPOS Profile User` profile_user
				WHERE profile_user.parent = opening.pos_profile
				  AND profile_user.parenttype = 'POS Profile'
				  AND profile_user.user = opening.user
			  )
			  AND EXISTS (
				SELECT 1 FROM `tabUser` user
				WHERE user.name = opening.user
				  AND user.enabled = 1
			  )
			  AND NOT EXISTS (
				SELECT 1 FROM `tabCashier Preliminary Closing` preliminary
				WHERE preliminary.pos_opening_shift = opening.name
				  AND preliminary.docstatus < 2
			  )
			  AND NOT EXISTS (
				SELECT 1 FROM `tabPOS Closing Shift` closing
				WHERE closing.pos_opening_shift = opening.name
				  AND closing.docstatus < 2
			  )
			FOR UPDATE
		""",
		(
			selected.pos_opening_shift,
			selected.user,
			original.custom_cashier_profile,
			original.company,
		),
	)
	if not locked:
		frappe.throw(_("The selected cashier no longer has an active shift."))

	return frappe._dict(
		pos_opening_shift=frappe.get_doc("POS Opening Shift", selected.pos_opening_shift),
		pos_profile=frappe.get_doc("POS Profile", selected.pos_profile),
	)


def _submitted_refund_total(original_payment):
	return flt(
		frappe.db.sql(
			"""
				SELECT COALESCE(SUM(paid_amount), 0)
				FROM `tabPayment Entry`
				WHERE custom_original_deposit_payment = %s
				  AND custom_is_deposit = 1
				  AND payment_type = 'Pay'
				  AND docstatus = 1
			""",
			(original_payment,),
		)[0][0]
	)


def _sync_original_deposit(original_payment):
	original = frappe.db.get_value(
		"Payment Entry",
		original_payment,
		[
			"name",
			"docstatus",
			"payment_type",
			"custom_is_deposit",
			"custom_deposit_original_amount",
			"received_amount",
		],
		as_dict=True,
	)
	if not original or original.payment_type != "Receive" or not cint(original.custom_is_deposit):
		return None

	original_amount = flt(original.custom_deposit_original_amount or original.received_amount)
	state = _deposit_state(original_amount, _submitted_refund_total(original.name))
	frappe.db.set_value(
		"Payment Entry",
		original.name,
		{
			"custom_deposit_original_amount": original_amount,
			"custom_deposit_refunded_amount": state.refunded_amount,
			"custom_deposit_balance": state.balance,
			"custom_deposit_status": state.status,
		},
		update_modified=False,
	)
	return state


def sync_deposit_balance(doc, method=None):
	"""Keep display fields current after deposit/refund submission or cancellation."""
	if not cint(doc.get("custom_is_deposit")):
		return
	original_payment = doc.get("custom_original_deposit_payment")
	if original_payment:
		_sync_original_deposit(original_payment)
	elif doc.payment_type == "Receive" and doc.docstatus == 1:
		_sync_original_deposit(doc.name)


def _make_payment_entry(
	*,
	context,
	customer,
	amount,
	request_id=None,
	item_code=None,
	description=None,
	qty=0,
	original_payment=None,
	is_deposit=True,
	references=None,
):
	payment_type = "Pay" if original_payment else "Receive"
	cashier_profile = context.profile.name
	if original_payment:
		cashier_profile = frappe.db.get_value(
			"Payment Entry", original_payment, "custom_cashier_profile"
		)
		validate_cashier_profile(cashier_profile)
	pe = frappe.new_doc("Payment Entry")
	values = {
			"payment_type": payment_type,
			"company": context.company,
			"posting_date": nowdate(),
			"party_type": "Customer",
			"party": customer,
			"mode_of_payment": context.mode_of_payment,
			"reference_no": context.shift.name,
			"reference_date": nowdate(),
			"paid_from": context.party_account if payment_type == "Receive" else context.payment_account,
			"paid_to": context.payment_account if payment_type == "Receive" else context.party_account,
			"paid_from_account_currency": (
				context.party_currency if payment_type == "Receive" else context.currency
			),
			"paid_to_account_currency": (
				context.currency if payment_type == "Receive" else context.party_currency
			),
			"paid_amount": amount,
			"received_amount": amount,
			"cost_center": context.profile.get("cost_center"),
			"custom_cashier_profile": cashier_profile,
			"custom_is_deposit": 1 if is_deposit else 0,
		}
	if is_deposit:
		values.update(
			{
				"custom_deposit_item": item_code,
				"custom_deposit_description": description,
				"custom_deposit_qty": qty,
				"custom_deposit_original_amount": amount if payment_type == "Receive" else 0,
				"custom_deposit_refunded_amount": 0,
				"custom_deposit_balance": amount if payment_type == "Receive" else 0,
				"custom_deposit_status": DEPOSIT_STATUS_OPEN if payment_type == "Receive" else None,
				"custom_original_deposit_payment": original_payment,
				"custom_deposit_request_id": request_id,
				"remarks": (
					_("Refund of customer deposit {0}").format(original_payment)
					if original_payment
					else _("Refundable customer deposit")
				),
			}
		)
	else:
		values["remarks"] = description
	pe.update(values)
	pe.set("references", references or [])
	pe.flags.ignore_permissions = True
	pe.insert()
	pe.submit()
	return pe


def _get_original_deposit(name, for_update=False):
	if for_update:
		frappe.db.sql("SELECT name FROM `tabPayment Entry` WHERE name = %s FOR UPDATE", (name,))
	doc = frappe.get_doc("Payment Entry", name)
	validate_cashier_document(doc)
	if (
		doc.docstatus != 1
		or doc.payment_type != "Receive"
		or not cint(doc.custom_is_deposit)
		or doc.get("custom_original_deposit_payment")
	):
		frappe.throw(_("The selected receipt is not an active customer deposit."))
	return doc


def _validate_deposit_company(doc, context):
	if doc.company != context.company:
		frappe.throw(_("The deposit company does not match the active POS cashier company."))


def _deposit_summary(doc):
	original_amount = flt(doc.custom_deposit_original_amount or doc.received_amount)
	state = _deposit_state(original_amount, _submitted_refund_total(doc.name))
	currency = doc.paid_to_account_currency or frappe.get_cached_value(
		"Company", doc.company, "default_currency"
	)
	return {
		"name": doc.name,
		"customer": doc.party,
		"customer_name": doc.party_name or doc.party,
		"posting_date": doc.posting_date,
		"item_code": doc.custom_deposit_item,
		"item_name": (
			frappe.get_cached_value("Item", doc.custom_deposit_item, "item_name")
			if doc.custom_deposit_item
			else None
		),
		"description": doc.custom_deposit_description,
		"qty": flt(doc.custom_deposit_qty),
		"original_amount": original_amount,
		"refunded_amount": state.refunded_amount,
		"balance": state.balance,
		"status": state.status,
		"currency": currency,
		"cashier": doc.owner,
		"pos_opening_shift": doc.reference_no,
	}


@frappe.whitelist()
def get_deposit_page_context():
	require_portal_access()
	context = _cashier_context()
	return {
		"company": context.company,
		"currency": context.currency,
		"pos_profile": context.profile.name,
		"pos_opening_shift": context.shift.name,
	}


@frappe.whitelist()
def get_deposit(name):
	require_portal_access()
	context = _cashier_context()
	doc = _get_original_deposit(name)
	_validate_deposit_company(doc, context)
	return _deposit_summary(doc)


@frappe.whitelist()
def get_refund_cashiers(deposit_name):
	"""List valid active refund cashiers, scoped to the deposit's POS Profile."""
	require_portal_access()
	context = _cashier_context()
	doc = _get_original_deposit(deposit_name)
	_validate_deposit_company(doc, context)
	selection = _refund_cashier_selection(doc)
	if not selection.cashiers:
		frappe.throw(
			_("No eligible cashier with an active shift exists for this deposit branch."),
			frappe.PermissionError,
		)
	return selection


@frappe.whitelist()
def get_deposits(include_refunded=0):
	require_portal_access()
	context = _cashier_context()
	filters = {
		"docstatus": 1,
		"payment_type": "Receive",
		"custom_is_deposit": 1,
		"custom_original_deposit_payment": ["is", "not set"],
		"company": context.company,
	}
	if is_cashier_isolation_user():
		filters["custom_cashier_profile"] = context.profile.name
	rows = frappe.get_all(
		"Payment Entry",
		filters=filters,
		fields=["name"],
		order_by="posting_date desc, creation desc",
		limit=500,
	)
	deposits = [_deposit_summary(frappe.get_doc("Payment Entry", row.name)) for row in rows]
	if not cint(include_refunded):
		deposits = [row for row in deposits if row["balance"] > AMOUNT_TOLERANCE]
	return deposits


@frappe.whitelist(methods=["POST"])
def create_deposit(customer, amount, request_id, item_code=None, description=None, qty=0):
	require_portal_access()
	request_id = _validate_request_id(request_id)
	existing = frappe.db.get_value(
		"Payment Entry", {"custom_deposit_request_id": request_id}, ["name", "payment_type"], as_dict=True
	)
	if existing:
		if existing.payment_type != "Receive":
			frappe.throw(_("This deposit request ID has already been used."))
		return {"deposit": _deposit_summary(_get_original_deposit(existing.name)), "receipt": existing.name}

	_validate_customer(customer)
	_validate_item(item_code)
	description = (description or "").strip()
	if len(description) > 500:
		frappe.throw(_("Deposit description cannot exceed 500 characters."))
	if not item_code and not description:
		frappe.throw(_("Select a deposit item or enter a description."))
	qty = flt(qty)
	if qty < 0:
		frappe.throw(_("Quantity cannot be negative."))
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Deposit amount must be greater than zero."))

	context = _cashier_context(customer)
	pe = _make_payment_entry(
		context=context,
		customer=customer,
		amount=amount,
		request_id=request_id,
		item_code=item_code,
		description=description,
		qty=qty,
	)
	_sync_original_deposit(pe.name)
	return {"deposit": _deposit_summary(pe), "receipt": pe.name}


@frappe.whitelist(methods=["POST"])
def refund_deposit(deposit_name, amount, request_id, cashier=None):
	require_portal_access()
	request_id = _validate_request_id(request_id)
	existing = frappe.db.get_value(
		"Payment Entry",
		{"custom_deposit_request_id": request_id},
		["name", "payment_type", "custom_original_deposit_payment"],
		as_dict=True,
	)
	if existing:
		if existing.payment_type != "Pay" or existing.custom_original_deposit_payment != deposit_name:
			frappe.throw(_("This deposit request ID has already been used."))
		return {
			"deposit": _deposit_summary(_get_original_deposit(deposit_name)),
			"refund": existing.name,
		}

	original = _get_original_deposit(deposit_name, for_update=True)
	_validate_customer(original.party)
	state = _deposit_state(
		original.custom_deposit_original_amount or original.received_amount,
		_submitted_refund_total(original.name),
	)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Refund amount must be greater than zero."))
	if amount > state.balance + AMOUNT_TOLERANCE:
		frappe.throw(_("Refund amount cannot exceed the available deposit balance."))

	shift_data = _resolve_refund_shift(original, cashier)
	context = _cashier_context(original.party, shift_data=shift_data)
	_validate_deposit_company(original, context)
	refund = _make_payment_entry(
		context=context,
		customer=original.party,
		amount=amount,
		request_id=request_id,
		item_code=original.custom_deposit_item,
		description=original.custom_deposit_description,
		qty=original.custom_deposit_qty,
		original_payment=original.name,
	)
	_sync_original_deposit(original.name)
	original.reload()
	return {"deposit": _deposit_summary(original), "refund": refund.name}
