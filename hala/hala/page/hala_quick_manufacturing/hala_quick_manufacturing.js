frappe.pages["hala-quick-manufacturing"].on_page_load = function (wrapper) {
	wrapper.quick_manufacturing = new HalaQuickManufacturing(wrapper);
};

frappe.pages["hala-quick-manufacturing"].on_page_show = function (wrapper) {
	wrapper.quick_manufacturing.show();
};

class HalaQuickManufacturing {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Quick Manufacturing"),
			single_column: true,
		});
		this.page.main.addClass("hala-quick-manufacturing-page");
		this.preview_data = null;
		this.preview_timer = null;
		this.submitting = false;
		this.request_id = null;
		this.loaded = false;
		this.styles = frappe.require("/assets/hala/css/quick_manufacturing.css");
		this.render_shell();
		this.make_controls();
		this.bind_events();
	}

	render_shell() {
		this.page.main.html(`
			<div class="hala-qm-shell">
				<section class="hala-qm-hero">
					<div>
						<span class="hala-qm-kicker">${__("Production Terminal")}</span>
						<h2>${__("Quick Manufacturing")}</h2>
						<p>${__("Select a finished item, quantity and warehouses. ERPNext will handle the stock entry and valuation.")}</p>
					</div>
					<div class="hala-qm-flow">${frappe.utils.icon("factory", "xl")}</div>
				</section>

				<section class="hala-qm-card hala-qm-form-card">
					<div class="hala-qm-grid">
						<div data-field="item_code"></div>
						<div data-field="bom_no"></div>
						<div data-field="quantity"></div>
						<div data-field="finished_uom"></div>
						<div data-field="source_warehouse"></div>
						<div data-field="target_warehouse"></div>
						<div data-field="posting_date"></div>
						<div data-field="posting_time"></div>
					</div>
					<div class="hala-qm-bom-actions">
						<button class="btn btn-xs btn-default" data-action="open-bom">${__("Open BOM")}</button>
						<button class="btn btn-xs btn-default" data-action="new-bom">${__("Create BOM")}</button>
					</div>
					<div data-field="remarks" class="hala-qm-remarks"></div>
				</section>

				<section class="hala-qm-card hala-qm-preview-card">
					<div class="hala-qm-section-heading">
						<div><h3>${__("Required Materials")}</h3><p>${__("Quantities and availability in the selected source warehouse")}</p></div>
						<button class="btn btn-sm btn-default" data-action="refresh-preview">${frappe.utils.icon("refresh-cw", "sm")} ${__("Refresh")}</button>
					</div>
					<div class="hala-qm-summary"></div>
					<div class="hala-qm-preview"><div class="hala-qm-empty">${__("Complete the fields above to preview required materials.")}</div></div>
				</section>

				<section class="hala-qm-actions">
					<div class="hala-qm-validation text-muted"></div>
					<button class="btn btn-primary btn-lg" data-action="manufacture" disabled>${frappe.utils.icon("factory", "sm")} ${__("Manufacture")}</button>
				</section>
				<section class="hala-qm-result hidden"></section>
			</div>
		`);
		this.$shell = this.page.main.find(".hala-qm-shell");
		this.$preview = this.$shell.find(".hala-qm-preview");
		this.$summary = this.$shell.find(".hala-qm-summary");
		this.$validation = this.$shell.find(".hala-qm-validation");
		this.$manufacture = this.$shell.find('[data-action="manufacture"]');
		this.$result = this.$shell.find(".hala-qm-result");
	}

	make_control(fieldname, df) {
		const control = frappe.ui.form.make_control({
			parent: this.$shell.find(`[data-field="${fieldname}"]`),
			df: {...df, fieldname},
			render_input: true,
		});
		this.controls[fieldname] = control;
		return control;
	}

	make_controls() {
		this.controls = {};
		this.make_control("item_code", {
			fieldtype: "Link", label: __("Finished Item"), options: "Item", reqd: 1,
			get_query: () => ({filters: {disabled: 0, is_stock_item: 1}}),
		});
		this.make_control("bom_no", {
			fieldtype: "Link", label: __("BOM"), options: "BOM", reqd: 1,
			get_query: () => ({filters: {item: this.value("item_code"), docstatus: 1, is_active: 1}}),
		});
		this.make_control("quantity", {
			fieldtype: "Float", label: __("Manufacturing Quantity"), reqd: 1, default: 1,
		});
		this.make_control("finished_uom", {
			fieldtype: "Data", label: __("Finished Item UOM"), read_only: 1,
		});
		this.make_control("source_warehouse", {
			fieldtype: "Link", label: __("Source Warehouse"), options: "Warehouse", reqd: 1,
			get_query: () => ({filters: {company: this.company, is_group: 0, disabled: 0}}),
		});
		this.make_control("target_warehouse", {
			fieldtype: "Link", label: __("Target Warehouse"), options: "Warehouse", reqd: 1,
			get_query: () => ({filters: {company: this.company, is_group: 0, disabled: 0}}),
		});
		this.make_control("posting_date", {
			fieldtype: "Date", label: __("Posting Date"), reqd: 1, default: frappe.datetime.get_today(),
		});
		this.make_control("posting_time", {
			fieldtype: "Time", label: __("Posting Time"), reqd: 1, default: frappe.datetime.now_time(),
		});
		this.make_control("remarks", {
			fieldtype: "Small Text", label: __("Remarks"),
		});
	}

	bind_events() {
		this.controls.item_code.$input.on("change", () => this.item_changed());
		for (const fieldname of ["bom_no", "quantity", "source_warehouse", "target_warehouse", "posting_date", "posting_time"]) {
			this.controls[fieldname].$input.on("change", () => this.schedule_preview());
		}
		this.$shell.on("click", '[data-action="refresh-preview"]', () => this.load_preview());
		this.$shell.on("click", '[data-action="open-bom"]', () => this.open_bom());
		this.$shell.on("click", '[data-action="new-bom"]', () => this.create_bom());
		this.$manufacture.on("click", () => this.confirm_manufacture());
	}

	async show() {
		await this.styles;
		if (!this.loaded) {
			this.loaded = true;
			await this.load_context();
		}
		const options = frappe.route_options || {};
		const bom = options.bom || frappe.utils.get_url_arg("bom");
		const item_code = options.item_code || frappe.utils.get_url_arg("item_code");
		if (bom || item_code) {
			frappe.route_options = null;
			await this.load_context(item_code, bom);
		}
	}

	value(fieldname) {
		return this.controls[fieldname].get_value();
	}

	set_value(fieldname, value) {
		return this.controls[fieldname].set_value(value || "");
	}

	async load_context(item_code = null, bom_no = null) {
		if (this.loading_context) return;
		this.loading_context = true;
		try {
			const {message} = await frappe.call({
				method: "hala.api.quick_manufacturing.get_context",
				args: {item_code: item_code || this.value("item_code"), bom_no},
				freeze: true,
				freeze_message: __("Loading manufacturing details..."),
			});
			this.context = message;
			this.company = message.company;
			if (message.item_code && this.value("item_code") !== message.item_code) {
				await this.set_value("item_code", message.item_code);
			}
			await this.set_value("finished_uom", message.finished_uom);
			await this.set_value("bom_no", message.bom_no);
			if (!this.value("posting_date")) await this.set_value("posting_date", message.posting_date);
			if (!this.value("posting_time")) await this.set_value("posting_time", message.posting_time);
			this.update_bom_actions();
			if (message.item_code && !message.boms.length) {
				this.show_missing_bom();
			} else {
				this.schedule_preview();
			}
		} finally {
			this.loading_context = false;
		}
	}

	async item_changed() {
		if (this.loading_context) return;
		this.clear_preview();
		await this.set_value("bom_no", "");
		await this.set_value("finished_uom", "");
		const item_code = this.value("item_code");
		if (item_code) await this.load_context(item_code);
	}

	update_bom_actions() {
		this.$shell.find('[data-action="open-bom"]').toggleClass("hidden", !this.value("bom_no"));
		this.$shell.find('[data-action="new-bom"]').toggleClass("hidden", !this.context?.can_create_bom);
	}

	show_missing_bom() {
		this.clear_preview();
		this.$validation.html(`<span class="text-danger">${__("No submitted BOM is available for this item.")}</span>`);
		frappe.msgprint({
			title: __("BOM Required"),
			message: __("No submitted BOM is available for this item."),
			indicator: "orange",
		});
	}

	open_bom() {
		if (this.value("bom_no")) frappe.set_route("Form", "BOM", this.value("bom_no"));
	}

	create_bom() {
		if (this.context?.can_create_bom) frappe.new_doc("BOM", {item: this.value("item_code")});
	}

	schedule_preview() {
		clearTimeout(this.preview_timer);
		this.preview_timer = setTimeout(() => this.load_preview(), 350);
	}

	preview_args() {
		return {
			item_code: this.value("item_code"),
			bom_no: this.value("bom_no"),
			quantity: this.value("quantity"),
			source_warehouse: this.value("source_warehouse"),
			target_warehouse: this.value("target_warehouse"),
			posting_date: this.value("posting_date"),
			posting_time: this.value("posting_time"),
		};
	}

	ready_for_preview() {
		const args = this.preview_args();
		return args.item_code && args.bom_no && flt(args.quantity) > 0 && args.source_warehouse && args.target_warehouse && args.posting_date && args.posting_time;
	}

	async load_preview() {
		if (!this.ready_for_preview()) {
			this.clear_preview();
			return;
		}
		this.$preview.html(`<div class="hala-qm-empty">${__("Calculating required materials...")}</div>`);
		this.$manufacture.prop("disabled", true);
		try {
			const {message} = await frappe.call({
				method: "hala.api.quick_manufacturing.preview",
				args: this.preview_args(),
			});
			this.preview_data = message;
			this.render_preview(message);
			this.$manufacture.prop("disabled", Boolean(message.blocking_shortage));
		} catch (error) {
			this.clear_preview();
			throw error;
		}
	}

	format_qty(value) {
		return format_number(value, null, 6);
	}

	render_preview(data) {
		const escape = frappe.utils.escape_html;
		this.$summary.html(`
			<div><span>${__("Expected Finished Quantity")}</span><strong>${this.format_qty(data.expected_finished_qty)} ${escape(data.finished_uom || "")}</strong></div>
			<div><span>${__("Raw Materials Count")}</span><strong>${data.raw_materials_count}</strong></div>
			<div><span>${__("Material Shortages")}</span><strong class="${data.shortages_count ? "text-danger" : "text-success"}">${data.shortages_count}</strong></div>
			<div><span>${__("Estimated Manufacturing Cost")}</span><strong>${format_currency(data.estimated_manufacturing_cost, data.currency)}</strong></div>
		`);
		const rows = data.components.map((row) => {
			const short = row.shortage > 0;
			const status = short
				? (row.negative_stock_allowed ? __("Shortage allowed by settings") : __("Short {0}", [this.format_qty(row.shortage)]))
				: __("Available");
			const stock_note = row.uom !== row.stock_uom
				? `<small>${this.format_qty(row.required_stock_qty)} ${escape(row.stock_uom)}</small>` : "";
			return `<tr class="${short ? "has-shortage" : ""}">
				<td><strong>${escape(row.item_code)}</strong><small>${escape(row.item_name || "")}</small></td>
				<td>${this.format_qty(row.required_qty)} ${escape(row.uom || "")} ${stock_note}</td>
				<td>${this.format_qty(row.available_qty)} ${escape(row.stock_uom || "")}</td>
				<td><span class="hala-qm-status ${short ? "short" : "available"}">${escape(status)}</span></td>
				<td>${escape(row.warehouse || "")}</td>
			</tr>`;
		}).join("");
		this.$preview.html(`<div class="table-responsive"><table class="table table-bordered hala-qm-table">
			<thead><tr><th>${__("Item")}</th><th>${__("Required Qty")}</th><th>${__("Stock Qty")}</th><th>${__("Difference / Shortage")}</th><th>${__("Warehouse")}</th></tr></thead>
			<tbody>${rows}</tbody></table></div>`);
		if (data.blocking_shortage) {
			this.$validation.html(`<span class="text-danger">${__("Available material quantity is lower than the required quantity.")}</span>`);
		} else if (data.negative_stock_enabled) {
			this.$validation.html(`<span class="text-warning">${__("Negative stock is allowed by ERPNext settings. The final submission will use standard validation.")}</span>`);
		} else {
			this.$validation.html(`<span class="text-success">${__("Materials are available for manufacturing.")}</span>`);
		}
	}

	clear_preview() {
		this.preview_data = null;
		this.$summary.empty();
		this.$preview.html(`<div class="hala-qm-empty">${__("Complete the fields above to preview required materials.")}</div>`);
		this.$manufacture.prop("disabled", true);
		this.$validation.empty();
	}

	make_request_id() {
		if (window.crypto?.randomUUID) return window.crypto.randomUUID().replaceAll("-", "_");
		return `hala_${Date.now()}_${Math.random().toString(36).slice(2)}`.replace(/[^A-Za-z0-9_-]/g, "_");
	}

	confirm_manufacture() {
		if (!this.preview_data || this.preview_data.blocking_shortage || this.submitting) return;
		const escape = frappe.utils.escape_html;
		const args = this.preview_args();
		frappe.confirm(
			`<p>${__("Raw materials will be consumed and the finished item will be added to stock. Do you want to continue?")}</p>
			<dl class="hala-qm-confirm">
				<dt>${__("Finished Item")}</dt><dd>${escape(args.item_code)}</dd>
				<dt>${__("Manufacturing Quantity")}</dt><dd>${this.format_qty(args.quantity)} ${escape(this.preview_data.finished_uom || "")}</dd>
				<dt>${__("Source Warehouse")}</dt><dd>${escape(args.source_warehouse)}</dd>
				<dt>${__("Target Warehouse")}</dt><dd>${escape(args.target_warehouse)}</dd>
			</dl>`,
			() => this.manufacture(),
			() => {},
			__("Confirm Manufacturing")
		);
	}

	async manufacture() {
		if (this.submitting) return;
		this.submitting = true;
		this.request_id = this.request_id || this.make_request_id();
		this.$manufacture.prop("disabled", true);
		try {
			const {message} = await frappe.call({
				method: "hala.api.quick_manufacturing.manufacture",
				args: {...this.preview_args(), remarks: this.value("remarks"), request_id: this.request_id},
				freeze: true,
				freeze_message: __("Creating and submitting Manufacture Stock Entry..."),
			});
			this.render_success(message);
		} finally {
			this.submitting = false;
			this.$manufacture.prop("disabled", Boolean(this.preview_data?.blocking_shortage));
		}
	}

	render_success(result) {
		const escape = frappe.utils.escape_html;
		this.$result.removeClass("hidden").html(`
			<div class="hala-qm-success-icon">${frappe.utils.icon("check", "lg")}</div>
			<div><h3>${__("Manufacturing completed successfully")}</h3>
			<p>${__("Stock Entry")}: <strong>${escape(result.stock_entry)}</strong> · ${escape(result.finished_item)} · ${this.format_qty(result.manufactured_qty)} ${frappe.utils.escape_html(this.preview_data.finished_uom || "")}</p></div>
			<div class="hala-qm-result-actions">
				<button class="btn btn-primary" data-result-action="view">${__("View Stock Entry")}</button>
				<button class="btn btn-default" data-result-action="new">${__("New Manufacturing")}</button>
			</div>`);
		this.$result.off("click.hala-qm").on("click.hala-qm", '[data-result-action="view"]', () => frappe.set_route("Form", "Stock Entry", result.stock_entry));
		this.$result.on("click.hala-qm", '[data-result-action="new"]', () => this.reset());
		this.$result[0].scrollIntoView({behavior: "smooth", block: "center"});
	}

	async reset() {
		this.request_id = null;
		this.$result.addClass("hidden").empty();
		for (const field of ["item_code", "bom_no", "finished_uom", "source_warehouse", "target_warehouse", "remarks"]) await this.set_value(field, "");
		await this.set_value("quantity", 1);
		await this.set_value("posting_date", frappe.datetime.get_today());
		await this.set_value("posting_time", frappe.datetime.now_time());
		this.clear_preview();
	}
}
