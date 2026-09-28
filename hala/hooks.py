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

# POS Next keeps using its public API names. These overrides make the server the
# authority for customer-specific price lists without changing ERPNext core.
override_whitelisted_methods = {
	"pos_next.api.items.get_item_details": "hala.api.pos_pricing.get_item_details",
	"pos_next.api.invoices.update_invoice": "hala.api.pos_pricing.update_invoice",
}

fixtures = [
	{"dt": "Role", "filters": [["role_name", "=", "Hala Portal User"]]},
	{"dt": "Custom Field", "filters": [["name", "=", "Stock Entry-custom_hala_manufacturing_request_id"]]},
]
