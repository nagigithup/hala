(() => {
	"use strict";
	if (window.HalaQuickPurchase) return;
	const api = "hala.api.quick_purchase.";
	const call = async (method, args) => (await frappe.call({method: api + method, args})).message;
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	window.HalaQuickPurchase = class HalaQuickPurchase {
		async show() {
			this.context = await call("get_context");
			await frappe.require("/assets/hala/css/quick_purchase.css");
			if (!this.dialog) {
				this.dialog = new frappe.ui.Dialog({title: "فاتورة مشتريات", size: "extra-large", fields: [{fieldname: "pane", fieldtype: "HTML"}]});
				this.dialog.$wrapper.attr("dir", "rtl");
				this.$pane = this.dialog.fields_dict.pane.$wrapper;
				this.$pane.html(`<div class="hala-purchase-tools"><button class="btn btn-primary" data-new>فاتورة جديدة</button><button class="btn btn-default" data-refresh>تحديث القائمة</button><button class="btn btn-default" data-recover>استعادة آخر طلب حفظ</button></div><iframe name="hala-quick-purchase" class="hala-purchase-iframe" title="فاتورة مشتريات"></iframe><section class="hala-purchase-history"><h4>فواتير المشتريات الأخيرة</h4><div data-history></div></section>`);
				this.$pane.on("click", "[data-new]", () => this.open())
					.on("click", "[data-refresh]", () => this.history())
					.on("click", "[data-invoice]", event => this.open(event.currentTarget.dataset.invoice))
					.on("click", "[data-recover]", () => this.recover())
					.on("click", "[data-prev]", () => {this.start = Math.max(0, (this.start || 0) - 20); this.history();})
					.on("click", "[data-next]", () => {this.start = (this.start || 0) + 20; this.history();});
				window.addEventListener("message", event => {
					if (event.origin === location.origin && event.source === this.$pane.find("iframe")[0].contentWindow && event.data?.type === "hala-purchase-saved") this.history();
				});
			}
			this.$pane.find("[data-new]").prop("disabled", !this.context.can_create);
			this.dialog.show();
			await this.open(); await this.history();
		}
		async open(name) {
			if (name) await call("get_invoice", {name});
			else if (!this.context.can_create) {this.$pane.find("iframe").hide();return;}
			const params = new URLSearchParams({hala_quick_purchase: "1", embedded: "1", _lang: "ar"});
			if (this.context.company) params.set("company", this.context.company);
			const route = name || `new-purchase-invoice-${crypto.randomUUID()}`;
			this.$pane.find("iframe").show().attr("src", `/desk/purchase-invoice/${encodeURIComponent(route)}?${params}`);
		}
		async recover() {
			const key = `hala-purchase:${frappe.boot.sitename}:${frappe.session.user}`;
			const request_id = localStorage.getItem(key);
			if (!request_id) return frappe.msgprint("لا يوجد طلب حفظ سابق معلق.");
			const saved = await call("find_request", {request_id});
			if (saved) {await this.open(saved.name); localStorage.removeItem(key); await this.history();}
			else frappe.msgprint("لم يتم العثور على فاتورة محفوظة لهذا الطلب. راجع النموذج وأعد الحفظ بنفس معرف الطلب؛ لا تنشئ دفعة أو استلاماً إضافياً.");
		}
		async history() {
			const rows = await call("get_history", {start: this.start || 0});
			this.$pane.find("[data-history]").html(`<table class="table table-bordered"><thead><tr><th>الفاتورة</th><th>المورد</th><th>التاريخ</th><th>الإجمالي</th><th>حالة الدفع</th><th>المتبقي</th><th>أنشئت بواسطة</th></tr></thead><tbody>${rows.map(row => `<tr><td><button type="button" class="btn btn-link" data-invoice="${escape(row.name)}">${escape(row.name)}</button></td><td>${escape(row.supplier_name || row.supplier)}</td><td>${escape(row.posting_date)}</td><td>${escape(format_currency(row.grand_total, row.currency))}</td><td>${row.docstatus === 0 ? "مسودة" : row.docstatus === 2 ? "ملغاة" : Number(row.outstanding_amount) === 0 ? "مسددة" : Number(row.paid_amount) > 0 ? "مسددة جزئياً" : "غير مسددة"}</td><td>${escape(format_currency(row.outstanding_amount, row.currency))}</td><td>${escape(row.owner)}</td></tr>`).join("")}</tbody></table><button type="button" class="btn btn-default" data-prev>السابق</button> <button type="button" class="btn btn-default" data-next ${rows.length < 20 ? "disabled" : ""}>التالي</button>`);
		}
	};
})();
