frappe.pages["hala-receipt"].on_page_load = function (wrapper) {
	wrapper.hala_receipt = new HalaReceiptPage(wrapper);
};

frappe.pages["hala-receipt"].on_page_show = function (wrapper) {
	wrapper.hala_receipt.show();
};

class HalaReceiptPage {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Customer Receipt"),
			single_column: true,
			hide_sidebar: true,
		});
		this.receipt = null;
		this.receipts = [];
		this.invoices = [];
		this.context = null;
		this.busy = false;
		this.suppress_customer_change = false;
		this.styles = frappe.require("/assets/hala/css/receipt.css");
		this.printer = frappe.require("/assets/hala/js/smart_print.js");
		this.render_shell();
		this.make_controls();
		this.bind_events();
	}

	render_shell() {
		this.$shell = window.halaCashierLayout.mount({
			page: this.page,
			active: "receipt",
			page_class: "hala-receipt-shell",
			content: `
				<section class="hala-cashier-card hala-cashier-heading">
					<div>
						<span class="hala-cashier-kicker">Hala</span>
						<h2>${__("Customer Receipt")}</h2>
						<p data-receipt-name>${__("New Customer Receipt")}</p>
					</div>
					<div class="hala-cashier-actions" data-receipt-actions></div>
				</section>

				<section class="hala-cashier-card">
					<div class="hala-receipt-fields">
						<div data-field="customer"></div>
						<div data-field="amount"></div>
						<div data-field="description"></div>
					</div>
				</section>

				<section class="hala-cashier-card" data-invoice-section>
					<div class="hala-cashier-section-heading">
						<div>
							<h3>${__("Outstanding Sales Invoices")}</h3>
							<p>${__("Optional: select only the invoices to allocate this receipt to.")}</p>
						</div>
					</div>
					<div class="table-responsive">
						<table class="table hala-receipt-table">
							<thead><tr>
								<th>${__("Select")}</th>
								<th>${__("Invoice")}</th>
								<th>${__("Date")}</th>
								<th>${__("Outstanding Amount")}</th>
								<th>${__("Allocation Amount")}</th>
							</tr></thead>
							<tbody data-outstanding-invoices></tbody>
						</table>
					</div>
					<div class="hala-receipt-allocation-summary" data-allocation-summary></div>
				</section>

				<section class="hala-cashier-card">
					<div class="hala-cashier-section-heading">
						<div>
							<h3>${__("Customer Receipts")}</h3>
							<p>${__("Select a receipt to view or print it.")}</p>
						</div>
						<button class="btn btn-sm btn-default" data-action="refresh">
							${frappe.utils.icon("refresh-cw", "sm")} ${__("Refresh")}
						</button>
					</div>
					<div class="table-responsive">
						<table class="table hala-receipt-table">
							<thead><tr>
								<th>${__("Receipt No")}</th>
								<th>${__("Customer")}</th>
								<th>${__("Date")}</th>
								<th>${__("Received Amount")}</th>
								<th>${__("Allocation")}</th>
							</tr></thead>
							<tbody data-receipts></tbody>
						</table>
					</div>
				</section>
			`,
		});
		this.$actions = this.$shell.find("[data-receipt-actions]");
		this.$invoiceSection = this.$shell.find("[data-invoice-section]");
		this.$invoices = this.$shell.find("[data-outstanding-invoices]");
		this.$allocationSummary = this.$shell.find("[data-allocation-summary]");
		this.$receipts = this.$shell.find("[data-receipts]");
	}

	make_controls() {
		this.controls = {};
		const definitions = {
			customer: {
				fieldtype: "Link",
				label: __("Customer"),
				options: "Customer",
				reqd: 1,
				onchange: () => {
					if (!this.suppress_customer_change && !this.receipt) this.load_invoices();
				},
			},
			amount: {
				fieldtype: "Currency",
				label: __("Received Amount"),
				reqd: 1,
				onchange: () => this.render_allocation_summary(),
			},
			description: {fieldtype: "Small Text", label: __("Description")},
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
		this.$shell.on("click", '[data-action="new"]', () => this.new_receipt());
		this.$shell.on("click", '[data-action="print"]', () => this.print());
		this.$shell.on("click", '[data-action="refresh"]', () => this.load_receipts());
		this.$shell.on("click", "[data-receipt]", (event) => {
			this.open_receipt($(event.currentTarget).attr("data-receipt"));
		});
		this.$shell.on("change", '[data-invoice-select]', (event) => this.toggle_invoice(event));
		this.$shell.on("input change", '[data-invoice-allocation]', () => this.render_allocation_summary());
	}

	async show() {
		await this.styles;
		if (!this.context) {
			this.context = await this.call("get_receipt_page_context");
			this.controls.amount.df.options = this.context.currency;
			this.controls.amount.refresh();
			await this.new_receipt(false);
		}
		await this.load_receipts();
		const name = frappe.get_route()[1];
		if (name && this.receipt?.name !== name) await this.open_receipt(name);
	}

	async call(method, args = {}) {
		const response = await frappe.call({method: `hala.api.receipt.${method}`, args});
		return response.message;
	}

	set_read_only(read_only) {
		for (const control of Object.values(this.controls)) {
			control.df.read_only = read_only ? 1 : 0;
			control.refresh();
		}
	}

	async new_receipt(update_route = true) {
		this.receipt = null;
		this.invoices = [];
		this.set_read_only(false);
		this.suppress_customer_change = true;
		await Promise.all([
			this.controls.customer.set_value(""),
			this.controls.amount.set_value(0),
			this.controls.description.set_value(""),
		]);
		this.suppress_customer_change = false;
		this.$shell.find("[data-receipt-name]").text(__("New Customer Receipt"));
		this.render_invoices();
		this.render_actions();
		if (update_route && frappe.get_route()[1]) frappe.set_route("hala-receipt");
		this.controls.customer.$input.trigger("focus");
	}

	async load_invoices() {
		const customer = this.controls.customer.get_value();
		this.invoices = [];
		if (!customer) {
			this.render_invoices();
			return;
		}
		this.$invoices.html(`<tr><td colspan="5" class="text-muted text-center">${__("Loading...")}</td></tr>`);
		this.invoices = await this.call("get_outstanding_invoices", {customer});
		this.render_invoices();
	}

	render_invoices() {
		if (!this.invoices.length) {
			this.$invoices.html(`<tr><td colspan="5" class="text-muted text-center">${__("No outstanding invoices found. You can still create an unallocated receipt.")}</td></tr>`);
			this.render_allocation_summary();
			return;
		}
		const escape = frappe.utils.escape_html;
		this.$invoices.html(this.invoices.map((invoice, index) => `
			<tr>
				<td><input type="checkbox" data-invoice-select="${index}" aria-label="${__("Select Invoice")}"></td>
				<td><strong>${escape(invoice.name)}</strong></td>
				<td>${escape(frappe.datetime.str_to_user(invoice.posting_date))}</td>
				<td>${format_currency(invoice.outstanding_amount, invoice.currency || this.context.currency)}</td>
				<td><input type="number" class="form-control input-sm" min="0" step="0.01"
					max="${flt(invoice.outstanding_amount)}" value="0" disabled
					data-invoice-allocation="${index}" aria-label="${__("Allocation Amount")}"></td>
			</tr>
		`).join(""));
		this.render_allocation_summary();
	}

	toggle_invoice(event) {
		const index = Number(event.currentTarget.dataset.invoiceSelect);
		const selected = event.currentTarget.checked;
		const $allocation = this.$invoices.find(`[data-invoice-allocation="${index}"]`);
		$allocation.prop("disabled", !selected);
		if (selected && flt($allocation.val()) <= 0) {
			const alreadyAllocated = this.allocations().reduce((sum, row) => sum + row.allocated_amount, 0);
			const remaining = Math.max(flt(this.controls.amount.get_value()) - alreadyAllocated, 0);
			$allocation.val(Math.min(flt(this.invoices[index].outstanding_amount), remaining));
		} else if (!selected) {
			$allocation.val(0);
		}
		this.render_allocation_summary();
	}

	allocations() {
		const allocations = [];
		this.$invoices.find("[data-invoice-select]:checked").each((_, checkbox) => {
			const index = Number(checkbox.dataset.invoiceSelect);
			allocations.push({
				invoice: this.invoices[index].name,
				allocated_amount: flt(this.$invoices.find(`[data-invoice-allocation="${index}"]`).val()),
			});
		});
		return allocations;
	}

	render_allocation_summary() {
		const allocated = this.allocations().reduce((sum, row) => sum + row.allocated_amount, 0);
		const received = flt(this.controls?.amount?.get_value());
		const message = allocated
			? `${__("Allocated")}: ${this.money(allocated)} / ${__("Received")}: ${this.money(received)}`
			: __("No invoice selected: the receipt will be recorded as an unallocated customer payment.");
		this.$allocationSummary.text(message);
	}

	async receive() {
		if (this.busy || this.receipt) return;
		this.busy = true;
		try {
			const result = await this.call("create_customer_receipt", {
				customer: this.controls.customer.get_value(),
				amount: this.controls.amount.get_value(),
				description: this.controls.description.get_value(),
				allocations: this.allocations(),
			});
			frappe.show_alert({message: __("Customer receipt created"), indicator: "green"});
			await this.render_receipt(result.receipt);
			await this.load_receipts();
			frappe.set_route("hala-receipt", result.receipt.name);
		} finally {
			this.busy = false;
		}
	}

	async render_receipt(receipt) {
		this.receipt = receipt;
		this.suppress_customer_change = true;
		await Promise.all([
			this.controls.customer.set_value(receipt.customer || ""),
			this.controls.amount.set_value(receipt.amount || 0),
			this.controls.description.set_value(receipt.description || ""),
		]);
		this.suppress_customer_change = false;
		this.set_read_only(true);
		this.invoices = (receipt.allocations || []).map((row) => ({
			name: row.invoice,
			posting_date: receipt.posting_date,
			outstanding_amount: row.allocated_amount,
			currency: receipt.currency,
		}));
		this.$shell.find("[data-receipt-name]").text(receipt.name);
		this.render_read_only_allocations(receipt.allocations || []);
		this.render_actions();
	}

	render_read_only_allocations(allocations) {
		if (!allocations.length) {
			this.$invoices.html(`<tr><td colspan="5" class="text-muted text-center">${__("Unallocated customer payment")}</td></tr>`);
		} else {
			const escape = frappe.utils.escape_html;
			this.$invoices.html(allocations.map((row) => `
				<tr><td>✓</td><td><strong>${escape(row.invoice)}</strong></td><td>—</td><td>—</td>
				<td>${this.money(row.allocated_amount)}</td></tr>
			`).join(""));
		}
		this.$allocationSummary.text(
			allocations.length ? __("Allocated to selected invoices") : __("Recorded without invoice allocation")
		);
	}

	render_actions() {
		if (!this.receipt) {
			this.$actions.html(`<button class="btn btn-primary" data-action="receive">${__("Save and Receive")}</button>`);
			return;
		}
		this.$actions.html(`
			<button class="btn btn-default" data-action="new">${frappe.utils.icon("plus", "sm")} ${__("New Customer Receipt")}</button>
			<button class="btn btn-primary" data-action="print">${__("Print Receipt")}</button>
		`);
	}

	async load_receipts() {
		this.$receipts.html(`<tr><td colspan="5" class="text-muted text-center">${__("Loading...")}</td></tr>`);
		this.receipts = await this.call("get_receipts");
		if (!this.receipts.length) {
			this.$receipts.html(`<tr><td colspan="5" class="text-muted text-center">${__("No customer receipts found.")}</td></tr>`);
			return;
		}
		const escape = frappe.utils.escape_html;
		this.$receipts.html(this.receipts.map((receipt) => `
			<tr data-receipt="${escape(receipt.name)}">
				<td><strong>${escape(receipt.name)}</strong></td>
				<td>${escape(receipt.customer_name || receipt.customer)}</td>
				<td>${escape(frappe.datetime.str_to_user(receipt.posting_date))}</td>
				<td>${format_currency(receipt.amount, receipt.currency)}</td>
				<td>${receipt.allocations.length ? escape(receipt.allocations.map((row) => row.invoice).join(", ")) : __("Unallocated")}</td>
			</tr>
		`).join(""));
	}

	async open_receipt(name) {
		if (this.busy) return;
		this.busy = true;
		try {
			await this.render_receipt(await this.call("get_receipt", {name}));
			if (frappe.get_route()[1] !== name) frappe.set_route("hala-receipt", name);
			this.page.main.get(0)?.scrollIntoView({behavior: "smooth", block: "start"});
		} finally {
			this.busy = false;
		}
	}

	async print() {
		if (!this.receipt?.name) return;
		await this.printer;
		return window.halaSmartPrint("Payment Entry", this.receipt.name, "Hala Customer Receipt");
	}

	money(value) {
		return format_currency(flt(value), this.receipt?.currency || this.context?.currency || "SAR");
	}
}
