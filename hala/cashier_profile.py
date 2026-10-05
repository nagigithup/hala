"""Cashier-profile resolution and transaction isolation for Hala.

POS Next uses the standard ERPNext POS Profile as its cashier profile.  The
active POS Opening Shift is the authoritative mapping from a user to that
profile; document ownership is deliberately not part of this policy.
"""

from __future__ import annotations

import frappe
from frappe import _


CASHIER_ROLES = {"Cashier", "POSNext Cashier", "Hala Portal User"}
ELEVATED_ROLES = {"System Manager", "Accounts Manager", "Nexus POS Manager"}
PROFILE_FIELDS = {
	"Sales Invoice": "pos_profile",
	"Payment Entry": "custom_cashier_profile",
}


def has_elevated_cashier_access(user=None):
	user = user or frappe.session.user
	return bool(set(frappe.get_roles(user)).intersection(ELEVATED_ROLES))


def is_cashier_isolation_user(user=None):
	"""Return whether profile isolation applies to this user."""
	user = user or frappe.session.user
	if user == "Guest" or has_elevated_cashier_access(user):
		return False
	return bool(set(frappe.get_roles(user)).intersection(CASHIER_ROLES))


def get_current_cashier_context(user=None, required=True):
	"""Return POS Next's active shift context for a cashier user."""
	from pos_next.api.shifts import check_opening_shift

	user = user or frappe.session.user
	context = check_opening_shift(user)
	if not context and required:
		frappe.throw(
			_("No active POS opening shift found for this user.")
			+ "<br>"
			+ _("لا توجد وردية كاشير مفتوحة لهذا المستخدم."),
			frappe.PermissionError,
		)
	return context


def get_current_cashier_profile(user=None, required=True):
	"""Resolve the user's POS Profile through their active POS Opening Shift."""
	context = get_current_cashier_context(user=user, required=required)
	return context["pos_profile"].name if context else None


def get_document_cashier_profile(doc):
	fieldname = PROFILE_FIELDS.get(doc.doctype)
	return doc.get(fieldname) if fieldname else None


def validate_cashier_profile(profile, user=None):
	"""Reject a profile outside the current cashier's active POS Profile."""
	user = user or frappe.session.user
	if not is_cashier_isolation_user(user):
		return
	current_profile = get_current_cashier_profile(user=user)
	if not profile or profile != current_profile:
		frappe.throw(
			_("This transaction belongs to a different Cashier Profile."),
			frappe.PermissionError,
		)


def validate_cashier_document(doc, user=None):
	validate_cashier_profile(get_document_cashier_profile(doc), user=user)


def assign_current_cashier_profile(doc, user=None):
	"""Assign the server-resolved profile to a new Hala transaction."""
	user = user or frappe.session.user
	profile = get_current_cashier_profile(
		user=user, required=is_cashier_isolation_user(user)
	)
	fieldname = PROFILE_FIELDS.get(doc.doctype)
	if fieldname and profile:
		doc.set(fieldname, profile)
	return profile


def enforce_transaction_cashier_profile(doc, method=None):
	"""Derive and lock profile fields against crafted document writes."""
	if not is_cashier_isolation_user():
		return

	current_profile = get_current_cashier_profile()
	fieldname = PROFILE_FIELDS.get(doc.doctype)
	if not fieldname:
		return

	if not doc.is_new():
		stored_profile = frappe.db.get_value(doc.doctype, doc.name, fieldname)
		validate_cashier_profile(stored_profile)
		if doc.get(fieldname) != stored_profile:
			frappe.throw(
				_("Cashier Profile cannot be changed."), frappe.PermissionError
			)
		return

	profile = current_profile
	if doc.doctype == "Payment Entry" and doc.get("custom_booking_invoice"):
		profile = frappe.db.get_value(
			"Sales Invoice", doc.custom_booking_invoice, "pos_profile"
		)
	elif doc.doctype == "Payment Entry" and doc.get("custom_original_deposit_payment"):
		profile = frappe.db.get_value(
			"Payment Entry",
			doc.custom_original_deposit_payment,
			"custom_cashier_profile",
		)
	elif doc.doctype == "Sales Invoice" and doc.get("return_against"):
		profile = frappe.db.get_value("Sales Invoice", doc.return_against, "pos_profile")

	validate_cashier_profile(profile)
	doc.set(fieldname, profile)


def _query_condition(doctype, user=None):
	user = user or frappe.session.user
	if not is_cashier_isolation_user(user):
		return None
	profile = get_current_cashier_profile(user=user, required=False)
	if not profile:
		return "1=0"
	fieldname = PROFILE_FIELDS[doctype]
	return f"`tab{doctype}`.`{fieldname}` = {frappe.db.escape(profile)}"


def sales_invoice_query_conditions(user=None):
	return _query_condition("Sales Invoice", user=user)


def payment_entry_query_conditions(user=None):
	return _query_condition("Payment Entry", user=user)


def has_transaction_permission(doc, user=None, permission_type=None):
	"""Frappe has_permission hook for cashier-facing transaction documents."""
	user = user or frappe.session.user
	if not is_cashier_isolation_user(user):
		# Frappe permission hooks may only deny access: returning None is treated
		# as a controller-level denial.  Elevated/non-cashier users must return
		# True so the normal role permission system can continue its checks.
		return True
	if permission_type == "create":
		return bool(get_current_cashier_profile(user=user, required=False))
	profile = get_document_cashier_profile(doc)
	current_profile = get_current_cashier_profile(user=user, required=False)
	return bool(profile and current_profile and profile == current_profile)
