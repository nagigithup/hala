import frappe


PORTAL_ROLE = "Hala Portal User"


def can_open():
	"""Apps-screen permission callback. Business permissions stay with ERPNext."""
	if frappe.session.user == "Guest":
		return False
	roles = frappe.get_roles()
	return "System Manager" in roles or PORTAL_ROLE in roles


def require_portal_access():
	if not can_open():
		frappe.throw(
			frappe._("You do not have access to the Hala portal."),
			frappe.PermissionError,
		)

