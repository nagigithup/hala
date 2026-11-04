(() => {
	"use strict";
	const api = "hala.api.disbursement.";
	const kinds = ["رد مبلغ لعميل", "دفع لمورد", "سلف موظفين", "مصروفات عامة"];
	const call = async (method, args) => (await frappe.call({method: api + method, args})).message;
	const escape = value => frappe.utils.escape_html(String(value ?? ""));

	window.HalaDisbursement = class HalaDisbursement {
		constructor(page) {
			this.page = page;
			this.sources = [];
			this.pendingKey = `hala-disbursement:${frappe.session.user}`;
		}
		async show() {
			this.context = await call("get_context");
			const partyQuery = () => ({filters: this.kind === kinds[2] ? {company: this.dialog.get_value("company"), status: "Active"} : {}});
			this.dialog = new frappe.ui.Dialog({title: "سند صرف", size: "large", fields: [
				{fieldname: "kind", fieldtype: "Select", label: "نوع الصرف", options: kinds, reqd: 1, onchange: () => this.change_kind()},
				{fieldname: "company", fieldtype: "Link", options: "Company", label: "الشركة", default: this.context.company, reqd: 1, read_only: !this.context.accountant, onchange: () => this.load_sources()},
				{fieldname: "payment_account", fieldtype: "Link", options: "Account", label: "حساب الصرف", default: this.context.payment_account, reqd: 1, read_only: !this.context.accountant, get_query: () => ({filters: {company: this.dialog.get_value("company"), is_group: 0, disabled: 0, account_type: ["in", ["Cash", "Bank"]]}})},
				{fieldname: "mode_of_payment", fieldtype: "Link", options: "Mode of Payment", label: "طريقة الدفع", default: this.context.mode_of_payment, reqd: 1, read_only: !this.context.accountant},
				{fieldname: "bank_reference", fieldtype: "Data", label: "رقم المرجع البنكي (للدفع البنكي)"},
				{fieldname: "party_type", fieldtype: "Select", options: "Customer\nSupplier\nEmployee", hidden: 1, default: "Customer"},
				{fieldname: "party", fieldtype: "Dynamic Link", options: "party_type", label: "العميل", get_query: partyQuery, onchange: () => this.load_sources()},
				{fieldname: "source", fieldtype: "Select", label: "المرجع الأصلي", options: [""], onchange: () => this.show_balance()},
				{fieldname: "balance", fieldtype: "HTML"},
				{fieldname: "expense_category", fieldtype: "Link", options: "Hala Expense Category", label: "فئة المصروف المعتمدة", get_query: () => ({filters: {company: this.dialog.get_value("company"), enabled: 1}})},
				{fieldname: "beneficiary", fieldtype: "Data", label: "المستفيد / المستلم"},
				{fieldname: "amount", fieldtype: "Currency", label: "المبلغ", reqd: 1},
				{fieldname: "posting_date", fieldtype: "Date", label: "التاريخ", default: frappe.datetime.get_today(), reqd: 1},
				{fieldname: "description", fieldtype: "Small Text", label: "البيان / الغرض", reqd: 1},
				{fieldname: "policy", fieldtype: "HTML", options: "<p>سلف الموظفين أرصدة قابلة للتسوية. المصروفات المباشرة للفئات المعتمدة فقط؛ استخدم المشتريات للمواد والضرائب والموافقات المطلوبة. لا يسجل الصرف قبل اعتماد الدفع.</p>"},
				{fieldname: "history", fieldtype: "HTML"},
			], primary_action_label: "حفظ وتنفيذ الصرف حسب الصلاحيات", primary_action: values => this.save(values)});
			this.dialog.$wrapper.attr("dir", "rtl");
			this.dialog.show();
			await this.change_kind();
			this.restore_pending();
			await this.history();
		}
		async change_kind() {
			if (!this.dialog) return;
			this.kind = this.dialog.get_value("kind");
			const expense = this.kind === kinds[3];
			const employee = this.kind === kinds[2];
			this.sources = [];
			this.sourceGeneration = (this.sourceGeneration || 0) + 1;
			await this.dialog.set_value("party_type", employee ? "Employee" : this.kind === kinds[1] ? "Supplier" : "Customer");
			await this.dialog.set_value("party", "");
			this.dialog.set_df_property("party", "label", employee ? "الموظف" : this.kind === kinds[1] ? "المورد" : "العميل");
			this.dialog.set_df_property("party", "hidden", expense);
			this.dialog.set_df_property("party", "reqd", !expense);
			this.dialog.set_df_property("expense_category", "hidden", !expense);
			this.dialog.set_df_property("expense_category", "reqd", expense);
			this.dialog.set_df_property("beneficiary", "reqd", expense);
			this.dialog.set_df_property("beneficiary", "hidden", !expense);
			this.dialog.set_df_property("source", "hidden", expense || employee);
			this.dialog.set_df_property("source", "reqd", this.kind === kinds[0]);
			this.dialog.set_df_property("source", "options", [""]);
			await this.dialog.set_value("source", "");
			this.show_balance();
			if (employee && !this.context.employee_supported) frappe.msgprint("HRMS غير مثبت على هذا الموقع. يلزم تثبيته وإعداد حساب السلف قبل استخدام سلف الموظفين.");
		}
		async load_sources() {
			if (!this.dialog) return;
			const generation = this.sourceGeneration = (this.sourceGeneration || 0) + 1;
			const party = this.dialog.get_value("party"), company = this.dialog.get_value("company");
			this.sources = [];
			this.dialog.set_df_property("source", "options", [""]);
			await this.dialog.set_value("source", "");
			if (!party || !company || ![kinds[0], kinds[1]].includes(this.kind)) return;
			const rows = await call("get_sources", {kind: this.kind, party, company});
			if (generation !== this.sourceGeneration) return;
			this.sources = rows;
			this.dialog.set_df_property("source", "options", ["", ...rows.map(row => `${row.doctype}: ${row.name}`)]);
			this.show_balance();
		}
		selected_source() { return this.sources.find(row => `${row.doctype}: ${row.name}` === this.dialog.get_value("source")); }
		show_balance() {
			const row = this.selected_source();
			this.dialog.fields_dict.balance.$wrapper.html(row ? `الرصيد المتاح: <strong>${escape(row.balance)} ${escape(row.currency)}</strong>` : "");
		}
		restore_pending() {
			try { this.pending = JSON.parse(localStorage.getItem(this.pendingKey) || "null"); } catch { this.pending = null; }
			this.dialog.fields_dict.policy.$wrapper.find("[data-recover]").remove();
			if (this.pending) {
				this.dialog.disable_primary_action();
				this.dialog.fields_dict.policy.$wrapper.append($("<button type='button' data-recover class='btn btn-warning'>استعادة نتيجة طلب الصرف السابق</button>").on("click", () => this.send(this.pending)));
			}
		}
		async save(values) {
			if (this.busy || this.pending) return;
			if (!(Number(values.amount) > 0)) return frappe.msgprint("أدخل مبلغاً موجباً.");
			const source = this.selected_source();
			const data = {...values, source_doctype: source?.doctype, source_name: source?.name,
				beneficiary: values.beneficiary || values.party, request_id: crypto.randomUUID()};
			frappe.confirm("تأكيد طلب الصرف؟ سيتم تنفيذ الدفع فقط حسب الصلاحيات والموافقات المحاسبية.", () => {
				if (this.busy || this.pending) return;
				this.pending = data;
				localStorage.setItem(this.pendingKey, JSON.stringify(data));
				this.send(data);
			});
		}
		async send(data) {
			if (this.busy) return;
			this.busy = true;
			this.dialog.disable_primary_action();
			try {
				const result = await call("create_voucher", {data: JSON.stringify(data)});
				localStorage.removeItem(this.pendingKey);
				this.pending = null;
				frappe.msgprint(`${escape(result.name)} — ${escape(result.status)}`);
				this.dialog.hide();
				await this.refresh_history();
			} catch (error) {
				// Preserve ambiguous network failures; a definite server rejection can be corrected.
				if (error?.exc || error?.responseJSON?.exc || error?.status === 417 || error?.status === 403) {
					localStorage.removeItem(this.pendingKey); this.pending = null;
				}
				frappe.msgprint("تعذر إكمال الطلب. راجع رسالة التحقق؛ إذا انقطع الاتصال استخدم استعادة النتيجة قبل إنشاء طلب آخر.");
			} finally {
				this.busy = false;
				if (!this.pending) this.dialog.enable_primary_action();
				else this.restore_pending();
			}
		}
		async history() {
			const rows = await call("get_history", {start: this.historyStart || 0});
			const $target = this.dialog.fields_dict.history.$wrapper;
			$target.html(`<h4>سندات الصرف الأخيرة</h4><div class="table-responsive"><table class="table"><thead><tr><th>السند</th><th>النوع</th><th>المستفيد</th><th>المبلغ</th><th>الحالة</th><th>الإجراء</th></tr></thead><tbody>${rows.map(row => `<tr><td>${escape(row.name)}</td><td>${escape(row.kind)}</td><td>${escape(row.beneficiary)}</td><td>${escape(row.amount)} ${escape(row.currency)}</td><td>${escape(row.status)}</td><td><button type="button" class="btn btn-xs btn-default" data-view="${escape(row.name)}">عرض</button> ${row.paid ? `<button type="button" class="btn btn-xs btn-default" data-print="${escape(row.name)}">طباعة</button>` : row.status !== "ملغى" ? `<button type="button" class="btn btn-xs btn-default" data-pay="${escape(row.name)}">متابعة الدفع</button>` : ""}</td></tr>`).join("")}</tbody></table></div><button type="button" class="btn btn-default" data-prev>السابق</button> <button type="button" class="btn btn-default" data-next>التالي</button>`);
			$target.off("click").on("click", "[data-print]", event => this.print(event.currentTarget.dataset.print))
				.on("click", "[data-view]", event => frappe.set_route("Form", "Hala Disbursement", event.currentTarget.dataset.view))
				.on("click", "[data-pay]", event => this.pay(event.currentTarget.dataset.pay))
				.on("click", "[data-prev]", () => {this.historyStart = Math.max(0, (this.historyStart || 0) - 20); this.history();})
				.on("click", "[data-next]", () => {if (rows.length === 20) {this.historyStart = (this.historyStart || 0) + 20; this.history();}});
		}
		async pay(name) {
			if (this.busy) return;
			frappe.confirm("متابعة الدفع بعد الموافقة؟ سيستخدم الدفع ورديتك الحالية.", async () => {
				if (this.busy) return;
				this.busy = true;
				try {const row = await call("pay_voucher", {name}); frappe.msgprint(escape(row.status)); await this.history();}
				finally {this.busy = false;}
			});
		}
		async refresh_history() { if (this.dialog?.is_visible) await this.history(); }
		async print(name) {
			const options = await call("get_print_options", {name});
			await frappe.require(["/assets/hala/js/smart_print.js", "booking_pos_print.bundle.js"]);
			return window.halaBookingPOSPrint(options.name, options.print_format, {doctype: options.doctype, pos_profile: options.pos_profile});
		}
	};
})();
