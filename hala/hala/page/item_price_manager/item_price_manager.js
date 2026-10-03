frappe.pages["item-price-manager"].on_page_load = function (wrapper) {
	wrapper.item_price_manager = new ItemPriceManager(wrapper);
};

frappe.pages["item-price-manager"].on_page_show = function (wrapper) {
	wrapper.item_price_manager.show();
};

class ItemPriceManager {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Item Price Manager"),
			single_column: true,
		});
		this.page.main.addClass("hala-item-price-manager-page");
		this.page_length = 50;
		this.start = 0;
		this.changes = new Map();
		this.cell_map = new Map();
		this.loaded = false;
		this.loading = false;
		this.saving = false;
		this.suppress_filter_change = false;
		this.styles = frappe.require("/assets/hala/css/item_price_manager.css");
		this.render_shell();
		this.make_controls();
		this.make_actions();
		this.bind_events();
		$(this.wrapper).on("hide.hala-item-price-manager", () => this.page_hidden());
		this.before_unload = (event) => {
			if (!this.changes.size) return;
			event.preventDefault();
			return (event.returnValue = __("There are unsaved price changes."));
		};
		window.addEventListener("beforeunload", this.before_unload, {capture: true});
	}

	escape(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	}

	render_shell() {
		this.page.main.html(`
			<div class="hala-ipm-shell">
				<section class="hala-ipm-filters">
					<div class="hala-ipm-filter-grid">
						<div data-field="search"></div>
						<div data-field="item_group"></div>
						<div data-field="price_list"></div>
						<div data-field="page_length"></div>
					</div>
					<div class="hala-ipm-filter-actions">
						<button class="btn btn-default btn-sm" data-action="refresh">
							${frappe.utils.icon("refresh-cw", "sm")} ${__("Refresh")}
						</button>
					</div>
				</section>
				<section class="hala-ipm-status" aria-live="polite"></section>
				<section class="hala-ipm-register">
					<div class="hala-ipm-table-wrap"></div>
				</section>
				<section class="hala-ipm-footer">
					<div class="hala-ipm-page-info text-muted"></div>
					<div class="hala-ipm-pagination">
						<button class="btn btn-default btn-sm" data-action="previous">${__("Previous")}</button>
						<button class="btn btn-default btn-sm" data-action="next">${__("Next")}</button>
					</div>
				</section>
			</div>
		`);
		this.$shell = this.page.main.find(".hala-ipm-shell");
		this.$status = this.$shell.find(".hala-ipm-status");
		this.$table = this.$shell.find(".hala-ipm-table-wrap");
		this.$page_info = this.$shell.find(".hala-ipm-page-info");
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
		this.make_control("search", {
			fieldtype: "Data",
			label: __("Search Item Code or Name"),
			placeholder: __("Type to search"),
		});
		this.make_control("item_group", {
			fieldtype: "Link",
			label: __("Item Group"),
			options: "Item Group",
		});
		this.make_control("price_list", {
			fieldtype: "Link",
			label: __("Price List"),
			options: "Price List",
			get_query: () => ({filters: {selling: 1, enabled: 1}}),
		});
		this.make_control("page_length", {
			fieldtype: "Select",
			label: __("Rows per page"),
			options: ["25", "50", "100"],
			default: "50",
		});
		this.committed_filters = this.filter_values();
	}

	make_actions() {
		this.$save = this.page.set_primary_action(
			__("Save Changes ({0})", [0]),
			() => this.save_changes(),
			"check",
			__("Saving"),
		);
		this.$discard = this.page.set_secondary_action(
			__("Discard Changes"),
			() => this.discard_changes(),
			"undo-2",
		);
		this.update_actions();
	}

	bind_events() {
		const debounced_search = frappe.utils.debounce(() => this.filter_changed(), 350);
		this.controls.search.$input.on("input", debounced_search);
		for (const fieldname of ["item_group", "price_list", "page_length"]) {
			this.controls[fieldname].$input.on("change", () => this.filter_changed());
		}
		this.$shell.on("click", '[data-action="refresh"]', () => this.refresh_clicked());
		this.$shell.on("click", '[data-action="previous"]', () => this.change_page(-1));
		this.$shell.on("click", '[data-action="next"]', () => this.change_page(1));
		this.$shell.on("input", ".hala-ipm-price-input", (event) => this.price_changed(event));
	}

	async show() {
		await this.styles;
		if (!this.loaded) await this.load_data();
	}

	filter_values() {
		return {
			search: String(this.controls?.search?.get_value() || "").trim(),
			item_group: this.controls?.item_group?.get_value() || "",
			price_list: this.controls?.price_list?.get_value() || "",
			page_length: Number(this.controls?.page_length?.get_value() || this.page_length),
		};
	}

	filters_equal(left, right) {
		return ["search", "item_group", "price_list", "page_length"].every(
			(key) => left[key] === right[key],
		);
	}

	async restore_filters() {
		this.suppress_filter_change = true;
		try {
			for (const fieldname of ["search", "item_group", "price_list", "page_length"]) {
				await this.controls[fieldname].set_value(this.committed_filters[fieldname] || "");
			}
		} finally {
			this.suppress_filter_change = false;
		}
	}

	filter_changed() {
		if (this.suppress_filter_change || this.loading) return;
		const next_filters = this.filter_values();
		if (this.filters_equal(next_filters, this.committed_filters)) return;
		if (!this.changes.size) {
			this.start = 0;
			this.load_data();
			return;
		}
		frappe.confirm(
			__("Discard the unsaved price changes and apply these filters?"),
			() => {
				this.clear_changes();
				this.start = 0;
				this.load_data();
			},
			() => this.restore_filters(),
		);
	}

	refresh_clicked() {
		if (!this.changes.size) {
			this.load_data();
			return;
		}
		frappe.confirm(__("Discard the unsaved price changes and refresh?"), () => {
			this.clear_changes();
			this.load_data();
		});
	}

	page_hidden() {
		if (!this.changes.size || this.leave_confirmation_open) return;
		this.leave_confirmation_open = true;
		frappe.confirm(
			__("You have unsaved price changes. Leave this page and discard them?"),
			() => {
				this.clear_changes();
				this.leave_confirmation_open = false;
			},
			() => {
				this.leave_confirmation_open = false;
				frappe.set_route("item-price-manager");
			},
		);
	}

	change_page(direction) {
		if (this.changes.size) {
			frappe.confirm(__("Discard the unsaved price changes and change page?"), () => {
				this.clear_changes();
				this.apply_page_change(direction);
			});
			return;
		}
		this.apply_page_change(direction);
	}

	apply_page_change(direction) {
		const next_start = this.start + direction * this.page_length;
		if (next_start < 0 || (direction > 0 && !this.data?.pagination?.has_more)) return;
		this.start = next_start;
		this.load_data();
	}

	async load_data() {
		if (this.loading || this.saving) return;
		this.loading = true;
		this.render_loading();
		try {
			const filters = this.filter_values();
			this.page_length = filters.page_length;
			const {message} = await frappe.call({
				method: "hala.api.item_price_manager.get_price_matrix",
				args: {...filters, start: this.start},
			});
			this.data = message;
			this.loaded = true;
			this.start = message.pagination.start;
			this.page_length = message.pagination.page_length;
			this.committed_filters = filters;
			this.clear_changes();
			this.render_table();
			this.render_pagination();
			this.render_permission_status();
		} finally {
			this.loading = false;
		}
	}

	render_loading() {
		this.$status.html(`<span class="text-muted">${__("Loading prices...")}</span>`);
		this.$table.html(`<div class="hala-ipm-loading">${frappe.utils.icon("loader", "md")} ${__("Loading")}</div>`);
	}

	render_permission_status() {
		const permissions = this.data.permissions;
		if (!permissions.can_write && !permissions.can_create) {
			this.$status.html(
				`<span class="text-muted">${__("Read only: you do not have permission to change Item Price records.")}</span>`,
			);
		} else {
			this.$status.empty();
		}
	}

	can_edit_cell(price, item) {
		if (item.has_variants) return false;
		return price ? this.data.permissions.can_write : this.data.permissions.can_create;
	}

	render_table() {
		this.cell_map.clear();
		const {items, price_lists, prices} = this.data;
		if (!price_lists.length) {
			this.$table.html(`<div class="hala-ipm-empty">${__("No enabled Selling Price Lists were found.")}</div>`);
			return;
		}
		if (!items.length) {
			this.$table.html(`<div class="hala-ipm-empty">${__("No active Items match the selected filters.")}</div>`);
			return;
		}

		const headers = price_lists
			.map(
				(price_list) => `
					<th class="hala-ipm-price-heading">
						<span>${this.escape(price_list.name)}</span>
						<small>${this.escape(price_list.currency)}</small>
					</th>`,
			)
			.join("");
		let cell_index = 0;
		const body = items
			.map((item) => {
				const item_prices = prices[item.item_code] || {};
				const cells = price_lists
					.map((price_list) => {
						const price = item_prices[price_list.name] || null;
						const cell_id = String(cell_index++);
						this.cell_map.set(cell_id, {
							item_code: item.item_code,
							uom: item.uom,
							price_list: price_list.name,
							item_price: price?.name || null,
							modified: price?.modified || null,
							original_rate: price ? Number(price.rate) : null,
						});
						const disabled = this.can_edit_cell(price, item) ? "" : "disabled";
						const value = price ? this.escape(price.rate) : "";
						const label = __("{0} price for {1}", [price_list.name, item.item_code]);
						return `
							<td class="hala-ipm-price-cell" data-cell-id="${cell_id}">
								<input class="form-control hala-ipm-price-input" type="number" min="0" step="any"
									inputmode="decimal" value="${value}" data-cell-id="${cell_id}"
									aria-label="${this.escape(label)}" ${disabled}>
							</td>`;
					})
					.join("");
				return `
					<tr data-item-code="${this.escape(item.item_code)}">
						<td class="hala-ipm-fixed hala-ipm-code"><a href="${this.escape(frappe.utils.get_form_link("Item", item.item_code))}">${this.escape(item.item_code)}</a></td>
						<td class="hala-ipm-fixed hala-ipm-name">${this.escape(item.item_name)}</td>
						<td class="hala-ipm-fixed hala-ipm-uom">${this.escape(item.uom)}</td>
						<td class="hala-ipm-fixed hala-ipm-group">${this.escape(item.item_group)}</td>
						${cells}
					</tr>`;
			})
			.join("");

		this.$table.html(`
			<table class="table table-bordered hala-ipm-table">
				<thead><tr>
					<th class="hala-ipm-fixed hala-ipm-code">${__("Item Code")}</th>
					<th class="hala-ipm-fixed hala-ipm-name">${__("Item Name")}</th>
					<th class="hala-ipm-fixed hala-ipm-uom">${__("UOM")}</th>
					<th class="hala-ipm-fixed hala-ipm-group">${__("Item Group")}</th>
					${headers}
				</tr></thead>
				<tbody>${body}</tbody>
			</table>
		`);
	}

	price_changed(event) {
		const $input = $(event.currentTarget);
		const cell_id = String($input.data("cell-id"));
		const cell = this.cell_map.get(cell_id);
		if (!cell) return;
		const raw = String($input.val()).trim();
		const rate = raw === "" ? null : Number(raw);
		const valid = rate !== null && Number.isFinite(rate) && rate >= 0;
		const unchanged =
			(cell.original_rate === null && raw === "") ||
			(valid && cell.original_rate !== null && rate === cell.original_rate);
		const $cell = $input.closest("td");

		if (unchanged) {
			this.changes.delete(cell_id);
			$cell.removeClass("hala-ipm-dirty hala-ipm-invalid");
		} else {
			this.changes.set(cell_id, {...cell, price_list_rate: rate, valid});
			$cell.addClass("hala-ipm-dirty").toggleClass("hala-ipm-invalid", !valid);
		}
		$input.closest("tr").toggleClass(
			"hala-ipm-row-dirty",
			$input.closest("tr").find(".hala-ipm-dirty").length > 0,
		);
		this.update_actions();
	}

	update_actions() {
		const count = this.changes.size;
		const can_save = count > 0 && !this.saving && [...this.changes.values()].every((row) => row.valid);
		this.$save
			?.prop("disabled", !can_save)
			.html(`${frappe.utils.icon("check", "sm")} <span>${__("Save Changes ({0})", [count])}</span>`);
		this.$discard?.prop("disabled", count === 0 || this.saving);
	}

	clear_changes() {
		this.changes.clear();
		this.$shell.find(".hala-ipm-dirty, .hala-ipm-invalid, .hala-ipm-row-dirty").removeClass(
			"hala-ipm-dirty hala-ipm-invalid hala-ipm-row-dirty",
		);
		this.update_actions();
	}

	discard_changes() {
		if (!this.changes.size) return;
		frappe.confirm(__("Discard all unsaved price changes?"), () => {
			this.clear_changes();
			this.render_table();
		});
	}

	async save_changes() {
		if (this.saving || !this.changes.size) return;
		const changes = [...this.changes.values()];
		if (changes.some((row) => !row.valid)) {
			frappe.msgprint({
				title: __("Invalid Price"),
				message: __("Enter a non-negative number in every modified price cell."),
				indicator: "red",
			});
			return;
		}

		this.saving = true;
		this.update_actions();
		try {
			const {message} = await frappe.call({
				method: "hala.api.item_price_manager.save_prices",
				type: "POST",
				args: {
					changes: changes.map((row) => ({
						item_code: row.item_code,
						price_list: row.price_list,
						uom: row.uom,
						price_list_rate: row.price_list_rate,
						item_price: row.item_price,
						modified: row.modified,
					})),
				},
				freeze: true,
				freeze_message: __("Saving Item Prices..."),
			});
			frappe.show_alert({
				message: __("Item Prices saved: {0} created, {1} updated.", [message.created, message.updated]),
				indicator: "green",
			});
			this.clear_changes();
			this.saving = false;
			await this.load_data();
		} finally {
			this.saving = false;
			this.update_actions();
		}
	}

	render_pagination() {
		const page_number = Math.floor(this.start / this.page_length) + 1;
		this.$page_info.text(__("Page {0} · {1} items shown", [page_number, this.data.items.length]));
		this.$shell.find('[data-action="previous"]').prop("disabled", this.start === 0);
		this.$shell.find('[data-action="next"]').prop("disabled", !this.data.pagination.has_more);
	}
}
