app_name = "hala"
app_title = "Hala"
app_publisher = "Hala"
app_description = "Modern ERPNext business portal for Hala Shop"
app_email = "admin@example.com"
app_license = "mit"

required_apps = ["erpnext"]

website_route_rules = [
	{"from_route": "/hala", "to_route": "hala"},
	{"from_route": "/hala/<path:app_path>", "to_route": "hala"},
]

add_to_apps_screen = [
	{
		"name": "hala",
		"logo": "/assets/hala/hala-logo.svg",
		"title": "Hala",
		"route": "/desk/hala",
		"has_permission": "hala.access.can_open",
	}
]

after_install = "hala.setup.after_install"
after_migrate = "hala.setup.after_migrate"

doctype_js = {
	"BOM": "public/js/bom.js",
}

doc_events = {
	"Sales Invoice": {
		"before_validate": "hala.cashier_profile.enforce_transaction_cashier_profile",
		"before_submit": "hala.api.sales_invoice.validate_cash_only_customer_payment",
		"on_submit": "hala.api.booking.allocate_booking_advances",
		"before_trash": "hala.api.booking.prevent_booking_deletion_with_payments",
	},
	"Payment Entry": {
		"before_validate": "hala.cashier_profile.enforce_transaction_cashier_profile",
		"on_submit": "hala.api.deposit.sync_deposit_balance",
		"on_cancel": "hala.api.deposit.sync_deposit_balance",
	},
}

permission_query_conditions = {
	"Sales Invoice": "hala.cashier_profile.sales_invoice_query_conditions",
	"Payment Entry": "hala.cashier_profile.payment_entry_query_conditions",
}

has_permission = {
	"Sales Invoice": "hala.cashier_profile.has_transaction_permission",
	"Payment Entry": "hala.cashier_profile.has_transaction_permission",
}

# POS Next keeps using its public API names. These overrides make the server the
# authority for customer-specific price lists without changing ERPNext core.
override_whitelisted_methods = {
	"pos_next.api.items.get_item_details": "hala.api.pos_pricing.get_item_details",
	"pos_next.api.invoices.update_invoice": "hala.api.pos_pricing.update_invoice",
	"pos_next.api.invoices.submit_invoice": "hala.api.pos_next_security.submit_invoice",
	"pos_next.api.invoices.get_invoices": "hala.api.pos_next_security.get_invoices",
	"pos_next.api.invoices.get_returnable_invoices": "hala.api.pos_next_security.get_returnable_invoices",
	"pos_next.api.invoices.search_invoice_by_number": "hala.api.pos_next_security.search_invoice_by_number",
	"pos_next.api.invoices.check_invoice_return_validity": "hala.api.pos_next_security.check_invoice_return_validity",
	"pos_next.api.invoices.get_invoice_for_return": "hala.api.pos_next_security.get_invoice_for_return",
	"pos_next.api.invoices.validate_return_items": "hala.api.pos_next_security.validate_return_items",
	"pos_next.api.invoices.prepare_return_invoice": "hala.api.pos_next_security.prepare_return_invoice",
	"pos_next.api.invoices.get_draft_invoices": "hala.api.pos_next_security.get_draft_invoices",
	"pos_next.api.invoices.delete_invoice": "hala.api.pos_next_security.delete_invoice",
	"pos_next.api.invoices.search_invoices_for_return": "hala.api.pos_next_security.search_invoices_for_return",
}

# Add customer-aware catalog prices to the existing POS Next page without
# copying or changing its frontend bundle.
page_renderer = ["hala.pos_page.CustomerPricingPOSPage"]

fixtures = [
	{"dt": "Role", "filters": [["role_name", "=", "Hala Portal User"]]},
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Customer-custom_cash_only",
					"Stock Entry-custom_hala_manufacturing_request_id",
					"Sales Invoice-custom_is_booking",
					"Sales Invoice-custom_delivery_date",
					"Sales Invoice-custom_booking_status",
					"Payment Entry-custom_cashier_profile",
					"Payment Entry-custom_booking_invoice",
					"Payment Entry-custom_booking_payment_request_id",
					"Payment Entry-custom_is_deposit",
					"Payment Entry-custom_deposit_item",
					"Payment Entry-custom_deposit_description",
					"Payment Entry-custom_deposit_qty",
					"Payment Entry-custom_deposit_original_amount",
					"Payment Entry-custom_deposit_refunded_amount",
					"Payment Entry-custom_deposit_balance",
					"Payment Entry-custom_deposit_status",
					"Payment Entry-custom_original_deposit_payment",
					"Payment Entry-custom_deposit_request_id",
				],
			]
		],
	},
	{
		"dt": "Print Format",
		"filters": [
			[
				"name",
				"in",
				[
					"BOOKING",
					"Hala Deposit Receipt",
					"payment recive",
				],
			]
		],
	},
]
