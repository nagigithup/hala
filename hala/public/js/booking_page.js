window.HalaBookingPage = class HalaBookingPage {
	constructor(wrapper, {history = false} = {}) {
		this.history = history;
		this.wrapper = wrapper;
		this.embedded =
			window.self !== window.top &&
			new URLSearchParams(window.location.search).get("embedded") === "1";
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: history ? "سجل فواتير الحجز" : __("Booking Invoice"),
			single_column: true,
			hide_sidebar: true,
		});
		this.page.main.addClass("hala-booking-desk-page");
		this.booking = null;
		this.rows = [];
		this.open_bookings = [];
		this.open_booking_search = "";
		this.busy = false;
		this.styles = frappe.require("/assets/hala/css/booking.css");
		this.printer = frappe.require("/assets/hala/js/smart_print.js");
		this.render_shell();
		if (!history) this.make_header_controls();
		this.bind_events();
		if (history) this.make_history();
	}

	render_shell() {
		this.$shell = window.halaCashierLayout.mount({
			page: this.page,
			active: this.history ? "booking-history" : "booking",
			page_class: "hala-booking-shell",
			content: `
				<section class="hala-booking-card hala-booking-heading hala-cashier-card hala-cashier-heading">
					<div>
						<span class="hala-booking-kicker hala-cashier-kicker">Hala</span>
						<h2 data-booking-title>${__("Booking Invoice")}</h2>
						<p data-booking-name>${__("New Booking")}</p>
					</div>
					<div class="hala-booking-actions hala-cashier-actions" data-booking-actions></div>
				</section>

				<section class="hala-booking-card hala-cashier-card">
					<div class="hala-booking-fields">
						<div data-field="customer"></div>
						<div data-field="posting_date"></div>
						<div data-field="delivery_date"></div>
						<div data-field="posting_time"></div>
						<div data-field="booking_status"></div>
					</div>
				</section>

				<section class="hala-booking-card hala-cashier-card">
					<div class="hala-booking-section-heading hala-cashier-section-heading">
						<h3>${__("Items")}</h3>
						<button class="btn btn-sm btn-default" data-action="add-item">
							${frappe.utils.icon("plus", "sm")} ${__("Add Item")}
						</button>
					</div>
					<div class="table-responsive hala-booking-items-wrap">
						<table class="table table-bordered hala-booking-table">
							<thead><tr>
								<th>${__("Item Code")}</th>
								<th>${__("Item Name")}</th>
								<th>${__("Description")}</th>
								<th>${__("UOM")}</th>
								<th>${__("Qty")}</th>
								<th>${__("Rate")}</th>
								<th>${__("Amount")}</th>
								<th></th>
							</tr></thead>
							<tbody data-booking-items></tbody>
						</table>
					</div>
				</section>

				<div class="hala-booking-summary">
					<section class="hala-booking-card hala-booking-notes-card hala-cashier-card">
						<div data-field="notes"></div>
					</section>
					<section class="hala-booking-totals hala-cashier-totals">
						<div><span>${__("Subtotal")}</span><strong data-total="net_total">0</strong></div>
						<div><span>${__("Tax")}</span><strong data-total="tax">0</strong></div>
						<div class="grand"><span>${__("Grand Total")}</span><strong data-total="grand_total">0</strong></div>
						<div class="paid"><span>${__("Paid")}</span><strong data-total="paid_amount">0</strong></div>
						<div class="remaining"><span>${__("Remaining")}</span><strong data-total="remaining_amount">0</strong></div>
					</section>
				</div>

				<section class="hala-booking-card hala-open-bookings hala-cashier-card">
					<div class="hala-booking-section-heading hala-cashier-section-heading">
						<div><h3>${__("Open Bookings")}</h3><p>${__("Select a booking to continue working on it.")}</p></div>
						<div class="hala-open-bookings-tools">
							<div class="hala-open-bookings-search">
								${frappe.utils.icon("search", "sm")}
								<input type="search" class="form-control" data-open-bookings-search
									placeholder="${__("Search by customer name or booking number")}" autocomplete="off">
							</div>
							<button class="btn btn-sm btn-default" data-action="refresh-bookings">
								${frappe.utils.icon("refresh-cw", "sm")} ${__("Refresh")}
							</button>
						</div>
					</div>
					<div class="table-responsive">
						<table class="table hala-open-bookings-table">
							<thead><tr>
								<th>${__("Booking No")}</th>
								<th>${__("Customer")}</th>
								<th>${__("Date")}</th>
								<th>${__("Delivery Date")}</th>
								<th>${__("Booking Status")}</th>
								<th>${__("Grand Total")}</th>
								<th>${__("Paid")}</th>
								<th>${__("Remaining")}</th>
							</tr></thead>
							<tbody data-open-bookings></tbody>
						</table>
					</div>
				</section>
			`,
		});
		this.$items = this.$shell.find("[data-booking-items]");
		this.$actions = this.$shell.find("[data-booking-actions]");
		this.$open_bookings = this.$shell.find("[data-open-bookings]");
	}

	make_header_controls() {
		this.controls = {};
		const definitions = {
			customer: {fieldtype: "Link", label: __("Customer"), options: "Customer", reqd: 1},
			posting_date: {fieldtype: "Date", label: __("Invoice Date"), reqd: 1},
			delivery_date: {fieldtype: "Date", label: __("Delivery Date"), reqd: 1},
			posting_time: {fieldtype: "Time", label: __("Delivery Time"), reqd: 1},
			booking_status: {
				fieldtype: "Select",
				label: __("Booking Status"),
				options: ["تحت التجهيز", "تم الانتهاء", "ملغى", "مؤجل"].join("\n"),
				reqd: 1,
			},
			notes: {fieldtype: "Small Text", label: __("Notes")},
		};
		for (const [fieldname, df] of Object.entries(definitions)) {
			this.controls[fieldname] = frappe.ui.form.make_control({
				parent: this.$shell.find(`[data-field="${fieldname}"]`),
				df: {...df, fieldname},
				render_input: true,
			});
		}
		this.controls.customer.$input.on("change", () => this.refresh_all_items());
		this.controls.posting_date.$input.on("change", () => this.refresh_all_items());
	}

	bind_events() {
		this.$shell.on("click", '[data-action="add-item"]', () => this.add_row());
		this.$shell.on("click", '[data-action="save"]', () => this.save());
		this.$shell.on("click", '[data-action="pay"]', () => this.pay());
		this.$shell.on("click", '[data-action="finalize"]', () => this.finalize());
		this.$shell.on("click", '[data-action="print-pos"]', () => this.print());
		this.$shell.on("click", '[data-action="print-receipt"]', () => this.print_sales_invoice(this.booking));
		this.$shell.on("click", '[data-action="print-a4"]', () => this.print_a4());
		this.$shell.on("click", '[data-action="new-booking"]', () => this.new_booking());
		this.$shell.on("click", '[data-action="refresh-bookings"]', () => this.load_open_bookings());
		this.$shell.on("input", "[data-open-bookings-search]", (event) => {
			this.open_booking_search = event.currentTarget.value || "";
			this.render_open_bookings();
		});
		this.$shell.on("click", "[data-open-booking]", (event) => {
			this.open_booking($(event.currentTarget).attr("data-open-booking"));
		});
	}

	async show() {
		document.body.classList.toggle("hala-booking-embedded", this.embedded);
		await this.styles;
		if (this.history) return this.load_history();
		const name = frappe.get_route()[1] || null;
		if (!this.booking || (name && this.booking.name !== name) || (!name && this.booking.name)) {
			await this.load(name);
		}
		await this.load_open_bookings();
	}

	async call(method, args = {}) {
		const response = await frappe.call({method: `hala.api.booking.${method}`, args});
		return response.message;
	}

	async load(name = null) {
		if (this.busy) return;
		this.busy = true;
		try {
			await this.render_booking(await this.call("get_booking", {name}));
		} finally {
			this.busy = false;
		}
	}

	async render_booking(booking) {
		if (this.history) return this.render_history_preview(booking);
		this.booking = booking;
		const draft = !this.history && Number(booking.docstatus) === 0;
		this.$shell.find("[data-booking-title]").text(draft ? __("Booking Invoice") : __("Sales Invoice"));
		this.$shell.find("[data-booking-name]").text(booking.name || __("New Booking"));
		await this.controls.customer.set_value(booking.customer || "");
		await this.controls.posting_date.set_value(booking.posting_date || frappe.datetime.get_today());
		await this.controls.delivery_date.set_value(booking.delivery_date || frappe.datetime.get_today());
		await this.controls.posting_time.set_value((this.history ? booking.delivery_time : booking.posting_time) || "");
		await this.controls.booking_status.set_value(booking.booking_status || "تحت التجهيز");
		await this.controls.notes.set_value(booking.notes || "");
		for (const control of Object.values(this.controls)) {
			control.df.read_only = draft ? 0 : 1;
			control.refresh();
		}

		this.rows = [];
		this.$items.empty();
		for (const item of booking.items || []) this.add_row(item);
		if (draft && !this.rows.length) this.add_row();
		this.$shell.find('[data-action="add-item"]').toggle(draft);
		this.render_actions();
		this.update_totals(booking);
	}

	render_actions() {
		if (this.history) {
			this.$actions.html(`<button type="button" class="btn btn-default" data-history-print="pos">طباعة POS</button>
				<button type="button" class="btn btn-default" data-history-print="a4">طباعة A4</button>`);
			return;
		}
		const saved_draft = Number(this.booking.docstatus) === 0 && this.booking.name;
		const is_new = Number(this.booking.docstatus) === 0 && !this.booking.name;
		const submitted = Number(this.booking.docstatus) === 1 && this.booking.name;
		this.$actions.html(`
			<button class="btn btn-default" data-action="new-booking">${frappe.utils.icon("plus", "sm")} ${__("New Booking")}</button>
			${is_new || saved_draft ? `<button class="btn btn-primary" data-action="save">${__("Save")}</button>` : ""}
			${saved_draft ? `<button class="btn btn-default" data-action="pay">${__("Pay")}</button>` : ""}
			${saved_draft ? `<button class="btn btn-primary" data-action="finalize">${__("Generate Sales Invoice")}</button>` : ""}
			${saved_draft ? `<button class="btn btn-default" data-action="print-a4">${__("Print A4")}</button>` : ""}
			${saved_draft ? `<button class="btn btn-default" data-action="print-pos">${__("Print Booking")}</button>` : ""}
			${submitted ? `<button class="btn btn-default" data-action="print-receipt">${__("Print POS")}</button>` : ""}
		`);
	}

	async load_open_bookings() {
		this.$open_bookings.html(`<tr><td colspan="8" class="text-muted text-center">${__("Loading...")}</td></tr>`);
		this.open_bookings = await this.call("get_open_bookings");
		this.render_open_bookings();
	}

	render_open_bookings() {
		if (!this.open_bookings.length) {
			this.$open_bookings.html(`<tr><td colspan="8" class="text-muted text-center">${__("No open bookings found.")}</td></tr>`);
			return;
		}
		const query = this.open_booking_search.trim().toLocaleLowerCase();
		const bookings = query
			? this.open_bookings.filter((booking) =>
				[booking.name, booking.customer_name, booking.customer]
					.filter(Boolean)
					.some((value) => String(value).toLocaleLowerCase().includes(query))
			)
			: this.open_bookings;
		if (!bookings.length) {
			this.$open_bookings.html(`<tr><td colspan="8" class="text-muted text-center">${__("No matching open bookings found.")}</td></tr>`);
			return;
		}
		const escape = frappe.utils.escape_html;
		this.$open_bookings.html(bookings.map((booking) => `<tr data-open-booking="${escape(booking.name)}">
			<td><strong>${escape(booking.name)}</strong></td>
			<td>${escape(booking.customer_name || booking.customer)}</td>
			<td>${escape(frappe.datetime.str_to_user(booking.posting_date))}</td>
			<td>${escape(booking.delivery_date ? frappe.datetime.str_to_user(booking.delivery_date) : "—")}</td>
			<td>${escape(booking.booking_status || "تحت التجهيز")}</td>
			<td>${format_currency(booking.grand_total, booking.currency)}</td>
			<td class="text-success">${format_currency(booking.paid_amount, booking.currency)}</td>
			<td class="hala-booking-list-remaining">${format_currency(booking.remaining_amount, booking.currency)}</td>
		</tr>`).join(""));
	}

	async open_booking(name) {
		if (this.busy) return;
		if (frappe.get_route()[1] === name) await this.load(name);
		else frappe.set_route("hala-booking", name);
		this.page.main.get(0)?.scrollIntoView({behavior: "smooth", block: "start"});
	}

	async new_booking() {
		if (this.history || this.busy) return;
		if (frappe.get_route()[1]) frappe.set_route("hala-booking");
		else await this.load(null);
		this.page.main.get(0)?.scrollIntoView({behavior: "smooth", block: "start"});
	}

	add_row(item = {}) {
		const draft = !this.history && (!this.booking || Number(this.booking.docstatus) === 0);
		const row = {
			item_name: item.item_name || "",
			description: item.description || "",
			uom: item.uom || "",
			rate: flt(item.rate),
			amount: flt(item.amount),
			refresh_token: 0,
			initializing: true,
		};
		row.$row = $(`<tr>
			<td data-control="item_code"></td>
			<td class="hala-booking-item-name" data-value="item_name">—</td>
			<td class="hala-booking-description" data-control="description"></td>
			<td class="hala-booking-item-uom" data-value="uom">—</td>
			<td data-control="qty"></td>
			<td class="hala-booking-money" data-value="rate"></td>
			<td class="hala-booking-money" data-value="amount"></td>
			<td><button class="btn btn-xs btn-default" data-remove title="${__("Remove")}">${frappe.utils.icon("trash-2", "sm")}</button></td>
		</tr>`).appendTo(this.$items);
		row.item_code = frappe.ui.form.make_control({
			parent: row.$row.find('[data-control="item_code"]'),
			df: {fieldtype: "Link", options: "Item", fieldname: "item_code", read_only: draft ? 0 : 1,
				get_query: () => ({filters: {disabled: 0}}),
				change: () => !row.initializing && this.refresh_item(row, true)},
			render_input: true,
		});
		row.description = frappe.ui.form.make_control({
			parent: row.$row.find('[data-control="description"]'),
			df: {fieldtype: "Small Text", fieldname: "description", read_only: draft ? 0 : 1},
			render_input: true,
		});
		row.qty = frappe.ui.form.make_control({
			parent: row.$row.find('[data-control="qty"]'),
			df: {fieldtype: "Float", fieldname: "qty", reqd: 1, read_only: draft ? 0 : 1},
			render_input: true,
		});
		Promise.all([
			row.item_code.set_value(item.item_code || ""),
			row.description.set_value(item.description || ""),
			row.qty.set_value(item.qty || 1),
		]).finally(() => {
			row.initializing = false;
		});
		row.qty.$input.on("change", () => this.refresh_item(row));
		row.$row.find("[data-remove]").toggle(draft).on("click", () => {
			row.$row.remove();
			this.rows = this.rows.filter((candidate) => candidate !== row);
			this.update_draft_totals();
		});
		this.rows.push(row);
		this.render_row_values(row);
	}

	async refresh_item(row, refresh_description = false) {
		const refresh_token = ++row.refresh_token;
		const item_code = row.item_code.get_value();
		const qty = flt(row.qty.get_value());
		if (!item_code || qty <= 0) {
			row.item_name = "";
			if (refresh_description && !item_code) await row.description.set_value("");
			row.rate = 0;
			row.amount = 0;
			this.render_row_values(row);
			this.update_draft_totals();
			return;
		}
		const details = await this.call("get_booking_item", {
			item_code,
			customer: this.controls.customer.get_value(),
			qty,
			posting_date: this.controls.posting_date.get_value(),
		});
		if (refresh_token !== row.refresh_token) return;
		row.item_name = details.item_name || details.item_code || item_code;
		if (refresh_description) await row.description.set_value(details.description || "");
		row.uom = details.uom;
		row.rate = flt(details.rate);
		row.amount = row.rate * qty;
		this.render_row_values(row);
		this.update_draft_totals();
	}

	render_row_values(row) {
		row.$row.find('[data-value="item_name"]').text(row.item_name || "—");
		row.$row.find('[data-value="uom"]').text(row.uom || "—");
		row.$row.find('[data-value="rate"]').text(this.money(row.rate));
		row.$row.find('[data-value="amount"]').text(this.money(row.amount));
	}

	async refresh_all_items() {
		if (this.history) return;
		await Promise.all(this.rows.filter((row) => row.item_code.get_value()).map((row) => this.refresh_item(row)));
	}

	money(value) {
		return format_currency(flt(value), this.booking?.currency || "SAR");
	}

	update_totals(booking) {
		for (const fieldname of ["net_total", "tax", "grand_total", "paid_amount", "remaining_amount"]) {
			this.$shell.find(`[data-total="${fieldname}"]`).text(this.money(booking[fieldname]));
		}
	}

	update_draft_totals() {
		if (this.booking?.name) return;
		const subtotal = this.rows.reduce((total, row) => total + flt(row.amount), 0);
		this.update_totals({net_total: subtotal, tax: 0, grand_total: subtotal, paid_amount: 0, remaining_amount: subtotal});
	}

	payload() {
		return {
			name: this.booking.name,
			company: this.booking.company,
			customer: this.controls.customer.get_value(),
			posting_date: this.controls.posting_date.get_value(),
			delivery_date: this.controls.delivery_date.get_value(),
			posting_time: this.controls.posting_time.get_value(),
			booking_status: this.controls.booking_status.get_value(),
			notes: this.controls.notes.get_value(),
			items: this.rows
				.map((row) => ({
					item_code: row.item_code.get_value(),
					description: row.description.get_value(),
					qty: flt(row.qty.get_value()),
					uom: row.uom,
				}))
				.filter((row) => row.item_code),
		};
	}

	async save() {
		if (this.history || this.busy) return;
		this.busy = true;
		try {
			const booking = await this.call("save_booking", {booking: this.payload()});
			frappe.show_alert({message: __("Booking saved"), indicator: "green"});
			await this.render_booking(booking);
			await this.load_open_bookings();
			if (frappe.get_route()[1] !== booking.name) frappe.set_route("hala-booking", booking.name);
		} finally {
			this.busy = false;
		}
	}

	pay() {
		if (this.history || this.busy || !this.booking?.name) return;
		const outstanding = flt(this.booking.remaining_amount);
		const dialog = new frappe.ui.Dialog({
			title: __("Pay"),
			fields: [
				{fieldname: "invoice_amount", fieldtype: "Currency", label: __("Invoice Amount"),
					options: this.booking.currency, read_only: 1, default: this.booking.grand_total},
				{fieldname: "paid_amount", fieldtype: "Currency", label: __("Paid Amount"),
					options: this.booking.currency, reqd: 1, default: outstanding},
				{fieldname: "remaining_or_change", fieldtype: "Currency", label: __("Remaining / Change"),
					options: this.booking.currency, read_only: 1, default: 0},
			],
			primary_action_label: __("Confirm"),
			primary_action: async ({paid_amount}) => {
				if (this.busy) return;
				this.busy = true;
				dialog.disable_primary_action();
				try {
					const booking = await this.call("create_booking_payment", {
						booking_name: this.booking.name,
						amount: paid_amount,
						request_id: this.request_id(),
					});
					dialog.hide();
					frappe.show_alert({message: __("Payment recorded"), indicator: "green"});
					await this.render_booking(booking);
					await this.load_open_bookings();
				} finally {
					this.busy = false;
					dialog.enable_primary_action();
				}
			},
		});
		const paid_field = dialog.get_field("paid_amount");
		const balance_field = dialog.get_field("remaining_or_change");
		const update_balance = () => {
			const paid = Math.max(flt(paid_field.get_value()), 0);
			const is_change = paid > outstanding;
			balance_field.set_value(Math.abs(outstanding - paid));
			balance_field.set_description(is_change ? __("Change to Customer") : __("Remaining Due"));
		};
		paid_field.$input.on("input change", update_balance);
		dialog.show();
		update_balance();
		paid_field.$input.trigger("focus").select();
	}

	request_id() {
		if (window.crypto?.randomUUID) return window.crypto.randomUUID();
		return `hala_${Date.now()}_${Math.random().toString(36).slice(2)}`;
	}

	finalize() {
		if (this.history || this.busy || !this.booking?.name) return;
		frappe.confirm(__("Submit this booking as the Sales Invoice?"), async () => {
			if (this.busy) return;
			this.busy = true;
			try {
				const booking = await this.call("finalize_booking", {booking_name: this.booking.name});
				frappe.show_alert({message: __("Sales Invoice generated"), indicator: "green"});
				await this.render_booking(booking);
				await this.load_open_bookings();
				this.print_sales_invoice(booking);
			} finally {
				this.busy = false;
			}
		});
	}

	async print_sales_invoice(booking) {
		if (!booking?.name || Number(booking.docstatus) !== 1) return;
		try {
			await this.printer;
			this.receipt_printer ||= frappe.require("booking_pos_print.bundle.js");
			await this.receipt_printer;
			return await window.halaBookingPOSPrint(booking.name);
		} catch (error) {
			console.warn("Sales Invoice printing was unavailable:", error);
		}
	}

	async print() {
		if (!this.booking?.name || Number(this.booking.docstatus) !== 0) return;
		try {
			await this.printer;
			if (this.history) {
				this.receipt_printer ||= frappe.require("booking_pos_print.bundle.js");
				await this.receipt_printer;
				return await window.halaBookingPOSPrint(this.booking.name, "BOOKING");
			}
			return await window.halaSmartPrint("Sales Invoice", this.booking.name, "BOOKING");
		} catch (error) {
			console.warn("Booking printing was unavailable:", error);
		}
	}

	async print_a4() {
		if (!this.booking?.name) return;
		const name = this.booking.name;
		const print_format = "فاتورة مبيعات A4";
		await frappe.model.with_doctype("Sales Invoice");
		if (!frappe.meta.get_print_formats("Sales Invoice").includes(print_format)) {
			frappe.msgprint({
				title: __("Print Error"),
				message: __("Print Format {0} does not exist.", [print_format]),
				indicator: "red",
			});
			return;
		}

		return this.open_a4_print(name);
	}

	open_a4_print(name) {
		// Chrome's --kiosk-printing flag suppresses the print dialog for every
		// window in that browser process. Open this A4 print view in Windows'
		// normal Edge context instead; POS/80mm printing stays in the kiosk.
		const params = new URLSearchParams({
			doctype: "Sales Invoice",
			name,
			trigger_print: "1",
			format: "فاتورة مبيعات A4",
			no_letterhead: "1",
		});
		const print_url = frappe.urllib.get_full_url(`/printview?${params.toString()}`);
		const launcher = document.createElement("a");
		launcher.href = `microsoft-edge:${print_url}`;
		launcher.rel = "noopener noreferrer";
		launcher.style.display = "none";
		document.body.appendChild(launcher);
		launcher.click();
		launcher.remove();
	}

	make_history() {
		this.history_start = 0;
		this.history_token = 0;
		this.$detail = $('<div data-history-detail hidden></div>');
		this.$shell.children().appendTo(this.$detail);
		this.$detail.find(".hala-open-bookings").remove();
		this.$shell.append(`
			<section class="hala-booking-card hala-cashier-card">
				<h2>سجل فواتير الحجز</h2>
				<div class="hala-history-tools">
					<input class="form-control" type="search" data-history-search placeholder="رقم الحجز، اسم العميل أو رقم الهاتف" aria-label="بحث في سجل فواتير الحجز">
					<select class="form-control" data-history-status aria-label="الحالة">
						<option value="all">الكل</option><option value="open">مفتوح</option>
						<option value="confirmed">مؤكد</option><option value="cancelled">ملغي</option>
					</select>
				</div>
				<div class="table-responsive"><table class="table hala-history-table">
					<thead><tr><th>رقم الحجز</th><th>العميل</th><th>تاريخ الحجز</th><th>تاريخ التسليم</th><th>إجمالي الفاتورة</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th></tr></thead>
					<tbody data-history-rows></tbody>
				</table></div>
				<div class="hala-history-tools">
					<button class="btn btn-default" data-history-prev>السابق</button><span data-history-page></span>
					<button class="btn btn-default" data-history-next>التالي</button>
				</div>
			</section>
		`);
		this.$shell.append(this.$detail);
		this.$preview_status = $('<div class="hala-booking-card hala-cashier-card" role="status" aria-live="polite" hidden></div>').insertBefore(this.$detail);
		this.$shell.on("input", "[data-history-search]", () => {
			clearTimeout(this.history_timer);
			this.history_token++;
			this.history_timer = setTimeout(() => {this.history_start = 0; this.load_history();}, 300);
		});
		this.$shell.on("change", "[data-history-status]", () => {this.history_start = 0; this.load_history();});
		this.$shell.on("click", "[data-history-prev]", () => {this.history_start = Math.max(0, this.history_start - 20); this.load_history();});
		this.$shell.on("click", "[data-history-next]", () => {if (this.history_more) {this.history_start += 20; this.load_history();}});
		this.$shell.on("click", "[data-history-booking]", event => this.load_history_details(event.currentTarget.dataset.historyBooking));
		this.$shell.on("keydown", "[data-history-booking]", event => {
			if (event.target === event.currentTarget && ["Enter", " "].includes(event.key)) {
				event.preventDefault();
				this.load_history_details(event.currentTarget.dataset.historyBooking);
			}
		});
		this.$shell.on("click", "[data-history-print]", event => this.print_history(event.currentTarget.dataset.historyPrint));
		this.$shell.on("click", "[data-history-retry]", () => this.load_history_details(this.history_selected_name));
	}

	async load_history() {
		const token = ++this.history_token;
		const $rows = this.$shell.find("[data-history-rows]");
		$rows.html(`<tr><td colspan="8">${__("Loading...")}</td></tr>`);
		try {
			const {message} = await frappe.call({method: "hala.api.booking_history.get_history", args: {
				search: this.$shell.find("[data-history-search]").val(),
				status: this.$shell.find("[data-history-status]").val(), start: this.history_start,
			}});
			if (token !== this.history_token) return;
			const escape = frappe.utils.escape_html;
			const date = value => value ? escape(frappe.datetime.str_to_user(String(value).split(" ")[0])) : "—";
			$rows.html(message.rows.map(row => `<tr tabindex="0" data-history-booking="${escape(row.name)}" aria-label="عرض الفاتورة ${escape(row.name)}"><td><button type="button" class="btn btn-link">${escape(row.name)}</button></td>
				<td>${escape(row.customer_name || row.customer)}</td><td>${date(row.creation)}</td><td>${date(row.custom_delivery_date)}</td>
				<td>${format_currency(row.grand_total, row.currency)}</td><td>${format_currency(row.paid_amount, row.currency)}</td><td>${format_currency(row.remaining_amount, row.currency)}</td>
				<td>${["مفتوح", "مؤكد", "ملغي"][Number(row.docstatus)]}</td></tr>`).join("") || '<tr><td colspan="8">لا توجد فواتير حجز مطابقة.</td></tr>');
			this.history_more = message.has_more;
			this.$shell.find("[data-history-prev]").prop("disabled", !this.history_start);
			this.$shell.find("[data-history-next]").prop("disabled", !message.has_more);
			this.$shell.find("[data-history-page]").text(`صفحة ${this.history_start / 20 + 1}`);
		} catch (error) {
			if (token === this.history_token) $rows.html('<tr><td colspan="8">تعذر تحميل سجل الحجز.</td></tr>');
			throw error;
		}
	}

	async load_history_details(name) {
		const token = this.detail_token = (this.detail_token || 0) + 1;
		this.history_selected_name = name;
		this.booking = null;
		this.$detail.prop("hidden", true);
		this.$preview_status.prop("hidden", false).text(`جارٍ تحميل الفاتورة ${name}…`);
		this.$preview_status.get(0)?.scrollIntoView?.({behavior: "smooth", block: "start"});
		try {
			const {message} = await frappe.call({method: "hala.api.booking_history.get_details", args: {name}});
			if (token !== this.detail_token) return;
			if (!message || message.name !== name) throw new Error("لم تصل بيانات الفاتورة المحددة.");
			this.render_history_preview(message);
			this.$preview_status.prop("hidden", true);
			this.$detail.prop("hidden", false);
			this.$detail.get(0)?.scrollIntoView?.({behavior: "smooth", block: "start"});
		} catch (error) {
			if (token !== this.detail_token) return;
			this.$preview_status.empty().append($('<p></p>').text(
				`تعذر تحميل الفاتورة ${name}. تحقق من صلاحية الوصول واتصال الشبكة ثم أعد المحاولة.`
			), $('<button type="button" class="btn btn-default" data-history-retry>إعادة المحاولة</button>'));
			console.warn("Booking history preview failed:", error);
		}
	}

	render_history_preview(booking) {
		this.booking = booking;
		const escape = value => frappe.utils.escape_html(String(value ?? ""));
		const date = value => value ? frappe.datetime.str_to_user(value) : "—";
		this.$shell.find("[data-booking-title]").text("معاينة الفاتورة — للقراءة فقط");
		this.$shell.find("[data-booking-name]").text(booking.name);
		const fields = {
			customer: ["العميل", booking.customer_name || booking.customer],
			posting_date: ["تاريخ الفاتورة", date(booking.posting_date)],
			delivery_date: ["تاريخ التسليم", date(booking.delivery_date)],
			posting_time: ["وقت التسليم", booking.delivery_time || "—"],
			booking_status: ["حالة الحجز", booking.booking_status || ["مفتوح", "مؤكد", "ملغي"][Number(booking.docstatus)]],
			notes: ["ملاحظات", booking.notes || "—"],
		};
		for (const [field, [label, value]] of Object.entries(fields)) {
			this.$shell.find(`[data-field="${field}"]`).html(`<label class="control-label">${label}</label><div class="hala-history-value">${escape(value)}</div>`);
		}
		this.$shell.find('[data-action="add-item"]').hide();
		this.$items.html((booking.items || []).map(item => `<tr>
			<td>${escape(item.item_code)}</td><td>${escape(item.item_name || item.item_code)}</td><td>${escape(item.description)}</td>
			<td>${escape(item.uom)}</td><td>${escape(item.qty)}</td><td>${this.money(item.rate)}</td><td>${this.money(item.amount)}</td><td></td>
		</tr>`).join(""));
		this.update_totals(booking);
		this.render_actions();
	}

	async print_history(kind) {
		const selected = this.booking;
		if (!selected?.name || this.history_printing) return;
		this.history_printing = true;
		this.$actions.find("button").prop("disabled", true);
		try {
			const {message: options} = await frappe.call({method: "hala.api.booking_history.get_print_options", args: {name: selected.name}});
			if (options?.name !== selected.name) throw new Error("تعذر التحقق من الفاتورة المحددة.");
			if (kind === "a4") {
				if (!options.a4_available) throw new Error("نموذج الطباعة فاتورة مبيعات A4 غير متاح.");
				return this.open_a4_print(selected.name);
			}
			await this.printer;
			this.receipt_printer ||= frappe.require("booking_pos_print.bundle.js");
			await this.receipt_printer;
			return await window.halaBookingPOSPrint(selected.name, options.print_format || "Standard", {invoice: options});
		} catch (error) {
			frappe.msgprint({title: "تعذر طباعة الفاتورة", message: frappe.utils.escape_html(error?.message || "تحقق من الصلاحيات وإعدادات الطباعة ثم أعد المحاولة."), indicator: "red"});
		} finally {
			this.history_printing = false;
			this.$actions.find("button").prop("disabled", false);
		}
	}
};
