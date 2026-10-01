frappe.pages["hala-deposit"].on_page_load = function (wrapper) {
	wrapper.hala_deposit = new HalaDepositPage(wrapper);
};

frappe.pages["hala-deposit"].on_page_show = function (wrapper) {
	wrapper.hala_deposit.show();
};

class HalaDepositPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Receive Deposit"),
			single_column: true,
		});
		this.page.main.addClass("hala-deposit-desk-page");
		this.deposit = null;
		this.deposits = [];
		this.context = null;
		this.last_refund = null;
		this.busy = false;
		this.styles = frappe.require("/assets/hala/css/deposit.css");
		this.render_shell();
		this.make_controls();
		this.bind_events();
	}

	render_shell() {
		this.page.main.html(`
			<div class="hala-deposit-shell" dir="rtl">
				<section class="hala-deposit-card hala-deposit-heading">
					<div>
						<span class="hala-deposit-kicker">Hala</span>
						<h2>${__("Receive Deposit")}</h2>
						<p data-deposit-name>${__("New Deposit")}</p>
					</div>
					<div class="hala-deposit-actions" data-deposit-actions></div>
				</section>

				<section class="hala-deposit-card">
					<div class="hala-deposit-fields">
						<div data-field="customer"></div>
						<div data-field="item_code"></div>
						<div data-field="description"></div>
						<div data-field="qty"></div>
						<div data-field="amount"></div>
					</div>
					<div class="hala-deposit-summary" data-deposit-summary></div>
				</section>

				<section class="hala-deposit-card">
					<div class="hala-deposit-section-heading">
						<div>
							<h3>${__("Open Deposits")}</h3>
							<p>${__("Select a deposit receipt to view or refund it.")}</p>
						</div>
						<button class="btn btn-sm btn-default" data-action="refresh">
							${frappe.utils.icon("refresh-cw", "sm")} ${__("Refresh")}
						</button>
					</div>
					<div class="table-responsive">
						<table class="table hala-deposit-table">
							<thead><tr>
								<th>${__("Receipt No")}</th>
								<th>${__("Customer")}</th>
								<th>${__("Item / Description")}</th>
								<th>${__("Date")}</th>
								<th>${__("Original Amount")}</th>
								<th>${__("Refunded")}</th>
								<th>${__("Balance")}</th>
								<th>${__("Status")}</th>
							</tr></thead>
							<tbody data-open-deposits></tbody>
						</table>
					</div>
				</section>
			</div>
		`);
		this.$shell = this.page.main.find(".hala-deposit-shell");
		this.$actions = this.$shell.find("[data-deposit-actions]");
		this.$summary = this.$shell.find("[data-deposit-summary]");
		this.$deposits = this.$shell.find("[data-open-deposits]");
	}

	make_controls() {
		this.controls = {};
		const definitions = {
			customer: {fieldtype: "Link", label: __("Customer"), options: "Customer", reqd: 1},
			item_code: {
				fieldtype: "Link",
				label: __("Deposit Item"),
				options: "Item",
				get_query: () => ({filters: {disabled: 0}}),
			},
			description: {fieldtype: "Small Text", label: __("Description")},
			qty: {fieldtype: "Float", label: __("Qty"), default: 1},
			amount: {fieldtype: "Currency", label: __("Deposit Amount"), reqd: 1},
		};
		for (const [fieldname, df] of Object.entries(definitions)) {
			this.controls[fieldname] = frappe.ui.form.make_control({
				parent: this.$shell.find(`[data-field="${fieldname}"]`),
				df: {...df, fieldname},
				render_input: true,
			});
		}
	}

	bind_events() {
		this.$shell.on("click", '[data-action="receive"]', () => this.receive());
		this.$shell.on("click", '[data-action="new"]', () => this.new_deposit());
		this.$shell.on("click", '[data-action="refund"]', () => this.refund());
		this.$shell.on("click", '[data-action="print-deposit"]', () => this.print(this.deposit?.name));
		this.$shell.on("click", '[data-action="print-refund"]', () => this.print(this.last_refund));
		this.$shell.on("click", '[data-action="refresh"]', () => this.load_deposits());
		this.$shell.on("click", "[data-deposit]", (event) => {
			this.open_deposit($(event.currentTarget).attr("data-deposit"));
		});
	}

	async show() {
		await this.styles;
		if (!this.context) {
			this.context = await this.call("get_deposit_page_context");
			this.controls.amount.df.options = this.context.currency;
			this.controls.amount.refresh();
			await this.new_deposit(false);
		}
		await this.load_deposits();
		const name = frappe.get_route()[1];
		if (name && this.deposit?.name !== name) await this.open_deposit(name);
	}

	async call(method, args = {}) {
		const response = await frappe.call({method: `hala.api.deposit.${method}`, args});
		return response.message;
	}

	set_read_only(read_only) {
		for (const control of Object.values(this.controls)) {
			control.df.read_only = read_only ? 1 : 0;
			control.refresh();
		}
	}

	async new_deposit(update_route = true) {
		this.deposit = null;
		this.last_refund = null;
		this.set_read_only(false);
		await Promise.all([
			this.controls.customer.set_value(""),
			this.controls.item_code.set_value(""),
			this.controls.description.set_value(""),
			this.controls.qty.set_value(1),
			this.controls.amount.set_value(0),
		]);
		this.$shell.find("[data-deposit-name]").text(__("New Deposit"));
		this.$summary.empty().hide();
		this.render_actions();
		if (update_route && frappe.get_route()[1]) frappe.set_route("hala-deposit");
		this.controls.customer.$input.trigger("focus");
	}

	async render_deposit(deposit) {
		this.deposit = deposit;
		this.last_refund = null;
		await Promise.all([
			this.controls.customer.set_value(deposit.customer || ""),
			this.controls.item_code.set_value(deposit.item_code || ""),
			this.controls.description.set_value(deposit.description || ""),
			this.controls.qty.set_value(deposit.qty || 0),
			this.controls.amount.set_value(deposit.original_amount || 0),
		]);
		this.set_read_only(true);
		this.$shell.find("[data-deposit-name]").text(deposit.name);
		this.$summary.html(`
			<div><span>${__("Original Amount")}</span><strong>${this.money(deposit.original_amount)}</strong></div>
			<div><span>${__("Refunded")}</span><strong>${this.money(deposit.refunded_amount)}</strong></div>
			<div class="balance"><span>${__("Available Balance")}</span><strong>${this.money(deposit.balance)}</strong></div>
			<div><span>${__("Status")}</span><strong>${__(deposit.status)}</strong></div>
		`).show();
		this.render_actions();
	}

	render_actions() {
		if (!this.deposit) {
			this.$actions.html(`<button class="btn btn-primary" data-action="receive">${__("Save and Receive")}</button>`);
			return;
		}
		this.$actions.html(`
			<button class="btn btn-default" data-action="new">${frappe.utils.icon("plus", "sm")} ${__("New Deposit")}</button>
			<button class="btn btn-default" data-action="print-deposit">${__("Print Deposit Receipt")}</button>
			${this.deposit.balance > 0 ? `<button class="btn btn-primary" data-action="refund">${__("Refund Deposit")}</button>` : ""}
			${this.last_refund ? `<button class="btn btn-default" data-action="print-refund">${__("Print Deposit Refund Receipt")}</button>` : ""}
		`);
	}

	async load_deposits() {
		this.$deposits.html(`<tr><td colspan="8" class="text-muted text-center">${__("Loading...")}</td></tr>`);
		this.deposits = await this.call("get_deposits");
		if (!this.deposits.length) {
			this.$deposits.html(`<tr><td colspan="8" class="text-muted text-center">${__("No open deposits found.")}</td></tr>`);
			return;
		}
		const escape = frappe.utils.escape_html;
		this.$deposits.html(this.deposits.map((deposit) => `
			<tr data-deposit="${escape(deposit.name)}">
				<td><strong>${escape(deposit.name)}</strong></td>
				<td>${escape(deposit.customer_name || deposit.customer)}</td>
				<td>${escape(deposit.item_name || deposit.description || "—")}</td>
				<td>${escape(frappe.datetime.str_to_user(deposit.posting_date))}</td>
				<td>${format_currency(deposit.original_amount, deposit.currency)}</td>
				<td>${format_currency(deposit.refunded_amount, deposit.currency)}</td>
				<td class="hala-deposit-balance">${format_currency(deposit.balance, deposit.currency)}</td>
				<td>${__(deposit.status)}</td>
			</tr>
		`).join(""));
	}

	async open_deposit(name) {
		if (this.busy) return;
		this.busy = true;
		try {
			await this.render_deposit(await this.call("get_deposit", {name}));
			if (frappe.get_route()[1] !== name) frappe.set_route("hala-deposit", name);
			this.page.main.get(0)?.scrollIntoView({behavior: "smooth", block: "start"});
		} finally {
			this.busy = false;
		}
	}

	async receive() {
		if (this.busy || this.deposit) return;
		this.busy = true;
		try {
			const result = await this.call("create_deposit", {
				customer: this.controls.customer.get_value(),
				item_code: this.controls.item_code.get_value(),
				description: this.controls.description.get_value(),
				qty: this.controls.qty.get_value(),
				amount: this.controls.amount.get_value(),
				request_id: this.request_id(),
			});
			frappe.show_alert({message: __("Deposit received"), indicator: "green"});
			await this.render_deposit(result.deposit);
			await this.load_deposits();
			if (frappe.get_route()[1] !== result.deposit.name) {
				frappe.set_route("hala-deposit", result.deposit.name);
			}
		} finally {
			this.busy = false;
		}
	}

	refund() {
		if (this.busy || !this.deposit || this.deposit.balance <= 0) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Refund Deposit"),
			fields: [
				{fieldname: "available", fieldtype: "Currency", label: __("Available for Refund"),
					options: this.deposit.currency, read_only: 1, default: this.deposit.balance},
				{fieldname: "amount", fieldtype: "Currency", label: __("Refund Amount"),
					options: this.deposit.currency, reqd: 1, default: this.deposit.balance},
			],
			secondary_action_label: __("Cancel"),
			secondary_action: () => dialog.hide(),
			primary_action_label: __("Confirm Refund"),
			primary_action: async ({amount}) => {
				if (this.busy) return;
				this.busy = true;
				dialog.disable_primary_action();
				try {
					const result = await this.call("refund_deposit", {
						deposit_name: this.deposit.name,
						amount,
						request_id: this.request_id(),
					});
					dialog.hide();
					await this.render_deposit(result.deposit);
					this.last_refund = result.refund;
					this.render_actions();
					await this.load_deposits();
					frappe.show_alert({message: __("Deposit refund recorded"), indicator: "green"});
				} finally {
					this.busy = false;
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
		dialog.get_field("amount").$input.trigger("focus").select();
	}

	print(payment_entry) {
		if (!payment_entry) return;
		const params = new URLSearchParams({
			doctype: "Payment Entry",
			name: payment_entry,
			format: "Hala Deposit Receipt",
			no_letterhead: "1",
			trigger_print: "1",
		});
		window.open(`/printview?${params}`, "_blank", "width=480,height=720");
	}

	money(value) {
		return format_currency(flt(value), this.deposit?.currency || this.context?.currency || "SAR");
	}

	request_id() {
		if (window.crypto?.randomUUID) return window.crypto.randomUUID();
		return `hala_deposit_${Date.now()}_${Math.random().toString(36).slice(2)}`;
	}
}
