import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

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


def ensure_booking_fields():
	"""Install the booking markers without changing ERPNext's standard DocTypes."""
	create_custom_fields(
		{
			"Sales Invoice": [
				{
					"fieldname": "custom_is_booking",
					"label": "Booking",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "is_pos",
					"no_copy": 1,
				},
				{
					"fieldname": "custom_delivery_date",
					"label": "Delivery Date",
					"fieldtype": "Date",
					"insert_after": "due_date",
				},
				{
					"fieldname": "custom_booking_status",
					"label": "Booking Status",
					"fieldtype": "Select",
					"options": "تحت التجهيز\nتم الانتهاء\nملغى\nمؤجل",
					"default": "تحت التجهيز",
					"insert_after": "custom_delivery_date",
					"no_copy": 1,
				},
			],
			"Payment Entry": [
				{
					"fieldname": "custom_booking_invoice",
					"label": "Booking Invoice",
					"fieldtype": "Link",
					"options": "Sales Invoice",
					"insert_after": "reference_date",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_booking_payment_request_id",
					"label": "Booking Payment Request ID",
					"fieldtype": "Data",
					"insert_after": "custom_booking_invoice",
					"hidden": 1,
					"read_only": 1,
					"unique": 1,
					"no_copy": 1,
					"length": 80,
				},
			],
		},
		update=True,
	)


def ensure_cash_only_customer_field():
	"""Install the customer-level cash-only marker."""
	create_custom_fields(
		{
			"Customer": [
				{
					"fieldname": "custom_cash_only",
					"label": "Cash Only",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "default_currency",
				},
			]
		},
		update=True,
	)


def after_install():
	ensure_role()
	ensure_booking_fields()
	ensure_cash_only_customer_field()


def after_migrate():
	ensure_role()
	ensure_booking_fields()
	ensure_cash_only_customer_field()
