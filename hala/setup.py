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
					"fieldname": "custom_cashier_profile",
					"label": "Cashier Profile",
					"fieldtype": "Link",
					"options": "POS Profile",
					"insert_after": "reference_date",
					"read_only": 1,
					"no_copy": 1,
					"search_index": 1,
				},
				{
					"fieldname": "custom_booking_invoice",
					"label": "Booking Invoice",
					"fieldtype": "Link",
					"options": "Sales Invoice",
					"insert_after": "custom_cashier_profile",
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
				{
					"fieldname": "custom_is_deposit",
					"label": "Insurance / Deposit",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "custom_booking_payment_request_id",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_item",
					"label": "Deposit Item",
					"fieldtype": "Link",
					"options": "Item",
					"insert_after": "custom_is_deposit",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_description",
					"label": "Deposit Description",
					"fieldtype": "Small Text",
					"insert_after": "custom_deposit_item",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_qty",
					"label": "Qty",
					"fieldtype": "Float",
					"insert_after": "custom_deposit_description",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_original_amount",
					"label": "Original Deposit Amount",
					"fieldtype": "Currency",
					"insert_after": "custom_deposit_qty",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_refunded_amount",
					"label": "Refunded Deposit Amount",
					"fieldtype": "Currency",
					"insert_after": "custom_deposit_original_amount",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_balance",
					"label": "Deposit Balance",
					"fieldtype": "Currency",
					"insert_after": "custom_deposit_refunded_amount",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_status",
					"label": "Deposit Status",
					"fieldtype": "Select",
					"options": "Open\nPartially Refunded\nFully Refunded",
					"insert_after": "custom_deposit_balance",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_original_deposit_payment",
					"label": "Original Deposit Payment",
					"fieldtype": "Link",
					"options": "Payment Entry",
					"insert_after": "custom_deposit_status",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_deposit_request_id",
					"label": "Deposit Request ID",
					"fieldtype": "Data",
					"insert_after": "custom_original_deposit_payment",
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
