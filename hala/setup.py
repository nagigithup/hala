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
					"fieldname": "custom_hala_booking_origin",
					"label": "Hala Booking Origin",
					"fieldtype": "Check",
					"default": "0",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"search_index": 1,
					"insert_after": "custom_is_booking",
				},
				{
					"fieldname": "custom_booking_delivery_time",
					"label": "Booking Delivery Time",
					"fieldtype": "Time",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"insert_after": "custom_delivery_date",
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


def ensure_supplier_payment_fields():
	"""Payment provenance only; balances remain owned by ERPNext's ledgers."""
	create_custom_fields(
		{
			"Purchase Invoice": [
				{
					"fieldname": "custom_hala_supplier_payment",
					"label": "Supplier Payment on Submit",
					"fieldtype": "Check",
					"default": "0",
					"no_copy": 1,
					"insert_after": "is_paid",
					"description": "Record the actual supplier payment with a Payment Entry when submitting this invoice.",
				},
				{
					"fieldname": "custom_hala_supplier_payment_section",
					"label": "Supplier Payment",
					"fieldtype": "Section Break",
					"insert_after": "supplier_invoice_details",
					"depends_on": "custom_hala_supplier_payment",
				},
				{
					"fieldname": "custom_hala_actual_supplier_payment",
					"label": "Actual Amount Paid to Supplier",
					"fieldtype": "Currency",
					"options": "currency",
					"no_copy": 1,
					"insert_after": "custom_hala_supplier_payment_section",
				},
				{
					"fieldname": "custom_hala_supplier_payment_account_column",
					"fieldtype": "Column Break",
					"insert_after": "custom_hala_actual_supplier_payment",
				},
				{
					"fieldname": "custom_hala_supplier_payment_account",
					"label": "Cash/Bank Account",
					"fieldtype": "Link",
					"options": "Account",
					"no_copy": 1,
					"insert_after": "custom_hala_supplier_payment_account_column",
				},
				{
					"fieldname": "custom_hala_supplier_payment_reference",
					"label": "Reference No",
					"fieldtype": "Data",
					"no_copy": 1,
					"insert_after": "custom_hala_supplier_payment_account",
				},
				{
					"fieldname": "custom_hala_supplier_payment_date",
					"label": "Reference Date",
					"fieldtype": "Date",
					"no_copy": 1,
					"insert_after": "custom_hala_supplier_payment_reference",
				},
				{
					"fieldname": "custom_hala_supplier_payment_summary_column",
					"fieldtype": "Column Break",
					"insert_after": "custom_hala_supplier_payment_date",
				},
				{
					"fieldname": "custom_hala_supplier_payment_preview",
					"label": "Supplier Payment Summary",
					"fieldtype": "HTML",
					"insert_after": "custom_hala_supplier_payment_summary_column",
				},
			],
			"Payment Entry": [
				{
					"fieldname": "custom_hala_purchase_invoice",
					"label": "Hala Purchase Invoice",
					"fieldtype": "Link",
					"options": "Purchase Invoice",
					"insert_after": "reference_date",
					"read_only": 1,
					"no_copy": 1,
					"search_index": 1,
				},
				{
					"fieldname": "custom_hala_supplier_payment_request_id",
					"label": "Hala Supplier Payment Request ID",
					"fieldtype": "Data",
					"insert_after": "custom_hala_purchase_invoice",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"unique": 1,
					"length": 80,
				},
			],
		},
		update=True,
	)


def after_install():
	ensure_role()
	ensure_booking_fields()
	ensure_cash_only_customer_field()
	ensure_supplier_payment_fields()
	ensure_disbursement_setup()
	ensure_quick_purchase_fields()
	from hala.api.booking_history import backfill_booking_origins

	backfill_booking_origins()


def after_migrate():
	ensure_role()
	ensure_booking_fields()
	ensure_cash_only_customer_field()
	ensure_supplier_payment_fields()
	ensure_disbursement_setup()
	ensure_quick_purchase_fields()
	from hala.api.booking_history import backfill_booking_origins

	backfill_booking_origins()


def ensure_disbursement_setup():
	"""Install the access marker and standard-document audit link, without business grants."""
	if not frappe.db.exists("Role", "سند الصرف"):
		frappe.get_doc({"doctype": "Role", "role_name": "سند الصرف", "desk_access": 1}).insert(
			ignore_permissions=True
		)
	create_custom_fields(
		{
			doctype: [
				{
					"fieldname": "custom_hala_disbursement",
					"label": "Hala Disbursement",
					"fieldtype": "Link",
					"options": "Hala Disbursement",
					"read_only": 1,
					"no_copy": 1,
					"unique": 1,
					"insert_after": "company",
				}
			]
			for doctype in ("Payment Entry", "Journal Entry")
		},
		update=True,
	)


def install_disbursement():
	"""Apply only Hala's disbursement schema/prints to an existing local site."""
	if not frappe.db.exists("Role", "سند الصرف"):
		frappe.get_doc({"doctype": "Role", "role_name": "سند الصرف", "desk_access": 1}).insert(
			ignore_permissions=True
		)
	for name in ("hala_expense_category", "hala_disbursement"):
		frappe.reload_doc("hala", "doctype", name)
	ensure_disbursement_setup()
	for name in ("hala_disbursement_payment", "hala_disbursement_expense"):
		frappe.reload_doc("hala", "print_format", name)
	frappe.reload_doc("hala", "page", "hala_booking")
	if frappe.db.exists("Print Format", "BOOKING"):
		# Change just the payment-total expression; preserve the site's branding/layout.
		doc = frappe.get_doc("Print Format", "BOOKING")
		html = doc.html or ""
		for newline in ("\r\n", "\n") if "'payment_type': 'Receive'" in html else ():
			html = html.replace("'payment_type': 'Receive'", "'payment_type': ['in', ['Receive', 'Pay']]")
			html = html.replace(
				"'paid_amount'," + newline + "            'base_paid_amount'",
				"'payment_type',"
				+ newline
				+ "            'paid_amount',"
				+ newline
				+ "            'base_paid_amount'",
			)
			for attribute, indent in (("paid_amount", "    "), ("base_paid_amount", "            ")):
				old = "booking_payments" + newline + indent + "| sum(attribute='" + attribute + "')"
				new = (
					"(booking_payments | selectattr('payment_type', 'equalto', 'Receive') | sum(attribute='"
					+ attribute
					+ "'))"
					+ newline
					+ indent
					+ "- (booking_payments | selectattr('payment_type', 'equalto', 'Pay') | sum(attribute='"
					+ attribute
					+ "'))"
				)
				html = html.replace(old, new)
		if html != doc.html:
			doc.html = html
			doc.save(ignore_permissions=True)
	frappe.clear_cache()


def ensure_quick_purchase_fields():
	create_custom_fields(
		{
			"Purchase Invoice": [
				{
					"fieldname": "custom_hala_quick_purchase",
					"label": "Hala Quick Purchase",
					"fieldtype": "Check",
					"default": "0",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"print_hide": 1,
					"insert_after": "company",
				},
				{
					"fieldname": "custom_hala_purchase_request_id",
					"label": "Hala Purchase Request ID",
					"fieldtype": "Data",
					"unique": 1,
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"print_hide": 1,
					"insert_after": "custom_hala_quick_purchase",
				},
				{
					"fieldname": "custom_hala_purchase_shift",
					"label": "Purchase Cashier Shift",
					"fieldtype": "Link",
					"options": "POS Opening Shift",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"insert_after": "custom_hala_purchase_request_id",
				},
				{
					"fieldname": "custom_hala_purchase_profile",
					"label": "Purchase Cashier Profile",
					"fieldtype": "Link",
					"options": "POS Profile",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"insert_after": "custom_hala_purchase_shift",
				},
				{
					"fieldname": "custom_hala_purchase_cashier",
					"label": "Purchase Cashier",
					"fieldtype": "Link",
					"options": "User",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"insert_after": "custom_hala_purchase_profile",
				},
			]
		},
		update=True,
	)


def install_quick_purchase():
	ensure_quick_purchase_fields()
	frappe.reload_doc("hala", "page", "hala_booking")
	frappe.clear_cache()
