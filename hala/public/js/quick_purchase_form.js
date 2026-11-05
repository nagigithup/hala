(() => {
	"use strict";
	if (window.halaQuickPurchase) return;
	const api = "hala.api.quick_purchase.";
	const call = async (method, args) => (await frappe.call({method: api + method, args})).message;
	const enabled = () => window.name === "hala-quick-purchase" || new URLSearchParams(location.search).get("hala_quick_purchase") === "1";
	const settle = () => new Promise(resolve => setTimeout(() => frappe.after_ajax(resolve), 180));
	const labels = {
		company: "الشركة", supplier: "المورد", bill_no: "رقم فاتورة المورد", bill_date: "تاريخ فاتورة المورد",
		posting_date: "تاريخ الترحيل", due_date: "تاريخ الاستحقاق", scan_barcode: "بحث بالباركود",
		update_stock: "تحديث المخزون", is_paid: "مدفوعة", set_warehouse: "المستودع الافتراضي للأصناف المخزنية",
		mode_of_payment: "طريقة الدفع", cash_bank_account: "حساب النقد / البنك", paid_amount: "المبلغ المدفوع",
		taxes_and_charges: "قالب ضرائب ورسوم المشتريات", currency: "العملة", conversion_rate: "سعر التحويل",
		buying_price_list: "قائمة أسعار الشراء", apply_discount_on: "تطبيق الخصم على", discount_amount: "الخصم الإضافي",
		additional_discount_percentage: "نسبة الخصم الإضافي", items: "الأصناف", remarks: "البيان",
		item_code: "رمز الصنف / الاسم", item_name: "اسم الصنف", qty: "الكمية", uom: "الوحدة", rate: "سعر الوحدة",
		amount: "إجمالي السطر", warehouse: "المستودع", stock_qty: "كمية المخزون", stock_uom: "وحدة المخزون",
		discount_percentage: "نسبة الخصم", item_tax_template: "قالب ضريبة الصنف",
	};
	const escape = value => frappe.utils.escape_html(String(value ?? ""));

	class NativePurchasePane {
		constructor(frm) {
			this.frm = frm;
			this.desired = new Map(); this.versions = new Map(); this.jobs = new Map(); this.uoms = new Map();
			this.slots = new Map(); this.advanced = false;
		}
		async initialize() {
			this.context = await call("get_context");
			if (this.frm.is_new()) {
				if (!this.context.can_create) frappe.throw("لا تملك صلاحية إنشاء فاتورة مشتريات.");
				await this.frm.set_value({update_stock: 0, is_paid: 0, paid_amount: 0,
					custom_hala_quick_purchase: 1, custom_hala_purchase_request_id: crypto.randomUUID()});
				const company = new URLSearchParams(location.search).get("company") || this.context.company;
				if (company && !this.frm.doc.company) await this.frm.set_value("company", company);
			} else if (this.frm.doc.docstatus === 0 && !this.frm.doc.custom_hala_quick_purchase) {
				if (this.frm.doc.custom_hala_supplier_payment || this.frm.doc.is_return) {
					frappe.throw("هذه الفاتورة تحتاج الشاشة القياسية الكاملة؛ افتح الإعدادات المتقدمة من قائمة الفواتير.");
				}
				await this.frm.set_value({custom_hala_quick_purchase: 1,
					custom_hala_purchase_request_id: this.frm.doc.custom_hala_purchase_request_id || crypto.randomUUID()});
			}
			this.build();
			for (const row of this.frm.doc.items || []) if (row.item_code) {
				this.desired.set(row.name, Number(row.amount || 0));
				await this.load_uoms(row);
			}
			this.bind_input_intent();
			this.frm.$wrapper.on("render_complete.hala_purchase", () => setTimeout(() => this.refresh(), 0));
			this.refresh();
		}
		build() {
			const frm = this.frm;
			document.body.classList.add("hala-native-purchase");
			this.$layout = frm.$wrapper.find(".form-layout").first();
			this.$shell = $(`<div class="hala-native-purchase-pane" dir="rtl">
				<div class="hala-purchase-heading"><div><h2>فاتورة مشتريات</h2><div data-docname></div></div><div class="hala-purchase-tools">
				<button type="button" class="btn btn-primary" data-save>حفظ كمسودة</button>
				<button type="button" class="btn btn-primary" data-submit>اعتماد الفاتورة</button>
				<button type="button" class="btn btn-default" data-print>طباعة</button>
				<button type="button" class="btn btn-default" data-advanced>الإعدادات المتقدمة</button></div></div>
				<div class="hala-purchase-fields" data-header></div>
				<div class="hala-purchase-flags" data-flags></div>
				<div class="hala-purchase-fields" data-stock></div>
				<div class="hala-purchase-fields" data-payment></div>
				<div class="hala-purchase-items" data-items></div>
				<p class="text-muted hala-purchase-help">إجمالي السطر قبل ضرائب ورسوم المستند. تعديل الكمية أو الإجمالي يعيد حساب سعر الوحدة؛ تعديل السعر يعيد حساب الإجمالي. قد تتضمن الأسعار ضريبة حسب القالب.</p>
				<div class="hala-purchase-fields" data-tax></div>
				<div class="hala-purchase-totals" data-totals></div>
				<details class="hala-purchase-extra"><summary>العملة والخصومات وتفاصيل إضافية</summary><div class="hala-purchase-fields" data-extra></div></details>
				<div class="text-muted" data-notice role="status"></div>
			</div>`).insertBefore(this.$layout);
			const groups = {
				header: ["company", "supplier", "bill_no", "bill_date", "posting_date", "due_date"],
				flags: ["update_stock", "is_paid"], stock: ["set_warehouse"],
				payment: ["mode_of_payment", "cash_bank_account", "paid_amount"],
				items: ["scan_barcode", "items"], tax: ["taxes_and_charges"],
				extra: ["currency", "conversion_rate", "buying_price_list", "apply_discount_on", "additional_discount_percentage", "discount_amount", "remarks"],
			};
			for (const [group, fields] of Object.entries(groups)) for (const fieldname of fields) {
				const field = frm.fields_dict[fieldname]; if (!field) continue;
				const $slot = $("<span hidden></span>").insertBefore(field.$wrapper);
				this.slots.set(fieldname, $slot);
				field.$wrapper.appendTo(this.$shell.find(`[data-${group}]`));
				if (labels[fieldname]) frm.set_df_property(fieldname, "label", labels[fieldname]);
			}
			this.$layout.hide();
			const grid = frm.fields_dict.items.grid;
			for (const [fieldname, label] of Object.entries(labels)) if (grid.get_docfield(fieldname)) grid.update_docfield_property(fieldname, "label", label);
			for (const name of ["item_name", "uom", "warehouse", "discount_percentage"]) if (grid.get_docfield(name)) grid.update_docfield_property(name, "in_list_view", 1);
			grid.reset_grid();
			this.original_amount_read_only = grid.get_docfield("amount").read_only;
			grid.update_docfield_property("amount", "read_only", 0);
			// Native item link search matches codes and names; native scan_barcode handles barcodes.
			frm.set_query("uom", "items", (_doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				return {filters: {name: ["in", Object.keys(this.uoms.get(row.item_code)?.uoms || {})]}};
			});
			this.$shell.on("click", "[data-save]", () => this.save(false))
				.on("click", "[data-submit]", () => this.save(true))
				.on("click", "[data-print]", () => this.print())
				.on("click", "[data-advanced]", () => this.toggle_advanced());
		}
		refresh() {
			if (!this.$shell) return;
			const frm = this.frm, editable = frm.doc.docstatus === 0 && (frm.is_new() ? this.context.can_create : frm.get_perm(0, "write"));
			frm.set_df_property("paid_amount", "description", "المبلغ المسدد ضمن فاتورة المشتريات.");
			frm.set_df_property("update_stock", "description", "يسجل استلام المخزون عند الاعتماد. إذا وُجد إيصال شراء، استخدم الفاتورة المرتبطة به دون تحديث مخزون جديد.");
			const grid = frm.fields_dict.items.grid;
			grid.wrapper.children(".control-label").first().text("الأصناف");
			grid.wrapper.find(".grid-heading-row .row-index span").text("م");
			for (const [selector, label] of Object.entries({".grid-add-row": "إضافة صف", ".grid-add-multiple-rows": "إضافة أصناف", ".grid-download": "تنزيل", ".grid-upload": "رفع", ".grid-remove-rows": "حذف الصفوف"})) grid.wrapper.find(selector).text(label);
			for (const name of this.slots.keys()) if (labels[name] && frm.fields_dict[name].df.label !== labels[name]) frm.set_df_property(name, "label", labels[name]);
			this.$shell.find("[data-docname]").text(`${frm.is_new() ? "فاتورة جديدة" : frm.doc.name}${frm.doc.company ? " · " + frm.doc.company : ""}`);
			// Independent native flags: changing either one never sets the other.
			frm.toggle_display(["update_stock", "is_paid"], true);
			const linked_receipt = (frm.doc.items || []).some(row => row.purchase_receipt || row.pr_detail);
			frm.toggle_enable("update_stock", !linked_receipt);
			if (linked_receipt) frm.set_df_property("update_stock", "description", "الفاتورة مرتبطة بإيصال شراء؛ المخزون مسجل بإيصال الشراء.");
			frm.toggle_display("set_warehouse", !!Number(frm.doc.update_stock));
			for (const field of ["mode_of_payment", "cash_bank_account", "paid_amount"]) frm.toggle_display(field, !!Number(frm.doc.is_paid));
			for (const field of ["mode_of_payment", "cash_bank_account"]) frm.set_df_property(field, "reqd", !!Number(frm.doc.is_paid));
			this.warehouse_requirement();
			frm.fields_dict.items.grid.set_column_disp("warehouse", !!Number(frm.doc.update_stock));
			this.$shell.find("[data-save]").prop("disabled", !editable || this.busy);
			this.$shell.find("[data-submit]").prop("disabled", !editable || this.busy || (!this.context.workflow && !frm.get_perm(0, "submit")));
			this.$shell.find("[data-submit]").text(this.context.workflow ? "الموافقات" : "اعتماد الفاتورة");
			this.$shell.find("[data-print]").prop("disabled", frm.doc.docstatus !== 1);
			this.render_totals();
		}
		warehouse_requirement() {
			const doc = this.frm.doc;
			const missing = !!Number(doc.update_stock) && (doc.items || []).some(row => row.item_code && this.uoms.get(row.item_code)?.is_stock_item && !row.warehouse);
			// Per-row warehouses remain supported; the header fills missing ones.
			this.frm.set_df_property("set_warehouse", "reqd", missing);
		}
		render_totals() {
			if (!this.$shell) return;
			const doc = this.frm.doc;
			this.$shell.find("[data-totals]").html([
				["الصافي", doc.net_total], ["الضرائب والرسوم", doc.total_taxes_and_charges],
				["الإجمالي", doc.grand_total], ["الإجمالي المقرب", doc.rounded_total], ["المتبقي", doc.outstanding_amount],
			].map(([label, value]) => `<div><span>${label}</span><strong>${escape(format_currency(value || 0, doc.currency))}</strong></div>`).join(""));
			const inclusive = (doc.taxes || []).some(tax => Number(tax.included_in_print_rate));
			this.$shell.find("[data-notice]").text(inclusive ? "القالب يتضمن ضريبة داخل سعر الصنف. المجاميع محسوبة بواسطة ERPNext." : "إجمالي السطر قبل ضرائب ورسوم المستند. المجاميع محسوبة بواسطة ERPNext.");
		}
		async load_uoms(row) {
			if (!row.item_code) return;
			const code = row.item_code;
			const units = await call("get_item_uoms", {item_code: code});
			if (row.item_code === code) {this.uoms.set(code, units); this.warehouse_requirement();}
		}
		bind_input_intent() {
			this.input_listener = event => {
				if (this.advanced || this.frm.doc.docstatus !== 0) return;
				const input = event.target;
				const $row = $(input).closest(".grid-row");
				const name = $row.attr("data-name"), row = locals["Purchase Invoice Item"]?.[name];
				const field = $(input).closest("[data-fieldname]").attr("data-fieldname");
				if (!row || !["qty", "amount", "rate", "uom"].includes(field)) return;
				const current = this.desired.get(name) ?? Number(row.amount || 0);
				const total = field === "amount" ? flt(input.value) : field === "rate" ? flt(flt(input.value) * row.qty, precision("amount", row)) : current;
				this.schedule(row, total, field !== "rate");
			};
			document.addEventListener("change", this.input_listener, true);
		}
		schedule(row, total, derive = true) {
			const name = row.name, version = (this.versions.get(name) || 0) + 1;
			this.versions.set(name, version); this.desired.set(name, total);
			const job = (async () => {
				await settle(); // Native qty/UOM/default/pricing handlers run first.
				if (version !== this.versions.get(name) || !locals["Purchase Invoice Item"]?.[name]) return;
				if (derive) {
					const result = await call("derive_rate", {qty: row.qty, amount: total, currency: this.frm.doc.currency});
					if (version !== this.versions.get(name)) return;
					await frappe.model.set_value(row.doctype, name, "rate", result.rate);
					await settle();
				}
				if (version === this.versions.get(name)) this.verify_row(row, total);
				this.render_totals();
			})();
			// Retain a failed intent until the user corrects it; saving rechecks it.
			this.jobs.set(name, job); job.catch(() => {});
		}
		verify_row(row, total) {
			if (flt(row.amount, precision("amount", row)) !== flt(total, precision("amount", row))) {
				frappe.throw("تغير إجمالي السطر بعد حسابات ERPNext أو قاعدة تسعير. راجع السعر والخصم؛ لم يتم حفظ الفاتورة.");
			}
		}
		async validate() {
			await Promise.all(this.jobs.values());
			for (const row of this.frm.doc.items || []) if (!this.advanced && this.desired.has(row.name)) this.verify_row(row, this.desired.get(row.name));
		}
		async save(submit) {
			if (this.busy) return;
			if (submit && this.context.workflow) { this.toggle_advanced(true); return; }
			this.busy = true; this.refresh();
			try {
				await this.validate();
				if (!frappe.ui.form.check_mandatory(this.frm)) return;
				if (!submit && !this.frm.is_dirty()) return;
				localStorage.setItem(this.storage_key(), this.frm.doc.custom_hala_purchase_request_id);
				if (submit) {
					await new Promise(resolve => frappe.confirm("اعتماد فاتورة المشتريات؟ سيستخدم ERPNext خياري المخزون والدفع المحددين.", () => resolve(true), () => resolve(false))).then(async confirmed => {if (confirmed) await this.save_native("Submit");});
				} else await this.save_native("Save");
				if (!this.frm.is_new()) localStorage.removeItem(this.storage_key());
				window.parent.postMessage({type: "hala-purchase-saved"}, location.origin);
			} finally {this.busy = false; this.refresh();}
		}
		save_native(action) {
			return new Promise((resolve, reject) => {
				this.frm.save(action, response => response?.exc ? reject(new Error("لم يتم حفظ الفاتورة.")) : resolve(),
					null, () => reject(new Error("راجع رسالة التحقق قبل إعادة الحفظ.")));
			});
		}
		storage_key() {return `hala-purchase:${frappe.boot.sitename}:${frappe.session.user}`;}
		toggle_advanced(force) {
			const next = force === undefined ? !this.advanced : force;
			for (const [name, slot] of this.slots) {
				const field = this.frm.fields_dict[name];
				if (next) field.$wrapper.insertBefore(slot);
				else {
					const group = ["update_stock", "is_paid"].includes(name) ? "flags" : ["set_warehouse"].includes(name) ? "stock" : ["mode_of_payment", "cash_bank_account", "paid_amount"].includes(name) ? "payment" : ["scan_barcode", "items"].includes(name) ? "items" : name === "taxes_and_charges" ? "tax" : ["company", "supplier", "bill_no", "bill_date", "posting_date", "due_date"].includes(name) ? "header" : "extra";
					field.$wrapper.appendTo(this.$shell.find(`[data-${group}]`));
				}
			}
			this.frm.fields_dict.items.grid.update_docfield_property("amount", "read_only", next ? this.original_amount_read_only : 0);
			this.advanced = next;
			this.$layout.toggle(next); this.$shell.toggle(!next);
			document.body.classList.toggle("hala-purchase-advanced", next);
			if (next) {
				if (!this.$return) this.$return = $('<button type="button" class="btn btn-default hala-purchase-return">العودة إلى الشاشة المبسطة</button>').insertBefore(this.$layout).on("click", () => this.toggle_advanced(false));
				this.$return.show();
			} else {this.$return?.hide(); for (const row of this.frm.doc.items || []) this.desired.set(row.name, Number(row.amount || 0)); this.refresh();}
		}
		async print() {
			const options = await call("get_print_options", {name: this.frm.doc.name});
			await frappe.require(["/assets/hala/js/smart_print.js", "booking_pos_print.bundle.js"]);
			return window.halaNativePurchasePrint(options.name, options.print_format, options);
		}
	}

	window.halaQuickPurchase = {
		async mount(frm) {
			if (!enabled() || frm.doctype !== "Purchase Invoice") return;
			if (!frm.hala_native_purchase) {
				frm.hala_native_purchase = new NativePurchasePane(frm);
				await frm.hala_native_purchase.initialize();
			} else frm.hala_native_purchase.refresh();
		},
	};
	frappe.ui.form.on("Purchase Invoice", {
		refresh: frm => window.halaQuickPurchase.mount(frm),
		update_stock: frm => {setTimeout(() => frm.hala_native_purchase?.refresh(), 0);},
		is_paid: frm => {setTimeout(() => frm.hala_native_purchase?.refresh(), 0);},
		validate: frm => frm.hala_native_purchase?.validate(),
		before_save(frm) {
			const state = frm.hala_native_purchase;
			if (state && !state.advanced) frm.doc.hala_expected_item_amounts = frm.doc.items.map(row => state.desired.get(row.name) ?? Number(row.amount || 0));
		},
		after_save: frm => {frm.hala_native_purchase?.refresh(); window.parent.postMessage({type: "hala-purchase-saved"}, location.origin);},
	});
	const deferred_totals = frm => {setTimeout(async () => {await settle(); frm.hala_native_purchase?.render_totals();}, 0);};
	frappe.ui.form.on("Purchase Invoice", Object.fromEntries(["taxes_and_charges", "currency", "conversion_rate", "paid_amount", "discount_amount", "additional_discount_percentage", "apply_discount_on"].map(field => [field, deferred_totals])));
	frappe.ui.form.on("Purchase Invoice Item", {
		item_code(frm, cdt, cdn) {
			const state = frm.hala_native_purchase; if (!state) return;
			const row = locals[cdt][cdn], code = row.item_code;
			const version = (state.versions.get(cdn) || 0) + 1;
			state.versions.set(cdn, version); state.desired.delete(cdn);
			setTimeout(async () => {
				await settle();
				if (row.item_code) await state.load_uoms(row);
				if (row.item_code === code && state.versions.get(cdn) === version) state.desired.set(cdn, Number(row.amount || 0));
			}, 0);
		},
		warehouse(frm) {frm.hala_native_purchase?.warehouse_requirement();},
		items_remove(frm, cdt, cdn) {const state = frm.hala_native_purchase; if (state) {state.jobs.delete(cdn); state.desired.delete(cdn); state.versions.set(cdn, -1);}},
	});
})();
