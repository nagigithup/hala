import frappe

from hala.access import require_portal_access


login_required = True
no_cache = 1


def get_context(context):
	require_portal_access()
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.boot = {
		"user": frappe.session.user,
		"language": frappe.local.lang,
	}
	return context

