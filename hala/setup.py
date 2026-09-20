import frappe

from hala.access import PORTAL_ROLE


def ensure_role():
	"""Create the access marker role without granting business permissions."""
	if not frappe.db.exists("Role", PORTAL_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": PORTAL_ROLE,
				"desk_access": 1,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)


def after_install():
	ensure_role()


def after_migrate():
	ensure_role()

