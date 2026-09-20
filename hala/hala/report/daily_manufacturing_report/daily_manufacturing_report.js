frappe.query_reports["Daily Manufacturing Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "finished_item",
			label: __("Finished Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: () => ({filters: {is_stock_item: 1, disabled: 0}}),
		},
		{
			fieldname: "bom",
			label: __("BOM"),
			fieldtype: "Link",
			options: "BOM",
			get_query: () => ({filters: {docstatus: 1, is_active: 1}}),
		},
		{
			fieldname: "source_warehouse",
			label: __("Source Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({
				filters: {
					company: frappe.query_report.get_filter_value("company"),
					is_group: 0,
					disabled: 0,
				},
			}),
		},
		{
			fieldname: "target_warehouse",
			label: __("Target Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({
				filters: {
					company: frappe.query_report.get_filter_value("company"),
					is_group: 0,
					disabled: 0,
				},
			}),
		},
	],
	tree: true,
	name_field: "row_id",
	parent_field: "parent_row",
	initial_depth: 1,
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.indent === 0) {
			value = `<strong>${value}</strong>`;
		}
		return value;
	},
};
