frappe.ui.form.on("BOM", {
	refresh(frm) {
		if (
			frm.doc.docstatus !== 1 ||
			!frm.doc.is_active ||
			!frappe.user.has_role(["System Manager", "Stock User", "Stock Manager", "Manufacturing User", "Manufacturing Manager"]) ||
			!frappe.model.can_create("Stock Entry")
		) return;

		frm.add_custom_button(__("Quick Manufacture"), () => {
			frappe.route_options = {bom: frm.doc.name, item_code: frm.doc.item};
			frappe.set_route("hala-quick-manufacturing");
		}, __("Create"));
	},
});
