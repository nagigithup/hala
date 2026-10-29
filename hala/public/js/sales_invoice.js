frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		frm.set_df_property("posting_date", "label", __("Invoice Date"));
	},
});
