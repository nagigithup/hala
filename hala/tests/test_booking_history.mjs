import assert from "node:assert/strict";
import fs from "node:fs";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {JSDOM} = require("../../../pos_next/POS/node_modules/jsdom");
const jquery = require("../../../frappe/node_modules/jquery");
const {window} = new JSDOM("<div id='page'></div>", {url: "http://tag.localhost:8000/desk/hala-booking-history", runScripts: "outside-only"});
const $ = jquery(window);
const calls = [];
const record = {name: "BOOK-1", customer: "Customer", customer_name: "<script>unsafe</script>",
	docstatus: 0, currency: "SAR", creation: "2026-10-25 12:00:00", posting_date: "2026-10-29",
	delivery_date: "2026-10-30", delivery_time: "14:30:00", items: [{item_code: "ITEM", qty: 2, rate: 5, amount: 10}],
	net_total: 10, tax: 1.5, grand_total: 11.5, paid_amount: 5, remaining_amount: 6.5};
window.$ = $;
window.__ = value => value;
window.flt = value => Number(value) || 0;
window.format_currency = value => String(value || 0);
window.frappe = {
	utils: {icon: () => "", escape_html: value => $("<div>").text(value || "").html()},
	ui: {make_app_page: () => ({main: $("#page")}), form: {make_control({parent, df}) {
		const $input = $("<input>").prop("disabled", Boolean(df.read_only)).appendTo(parent);
		return {df, $input, async set_value(value) {$input.val(value);}, get_value() {return $input.val();},
			refresh() {$input.prop("disabled", Boolean(df.read_only));}};
	}}},
	require: async () => {}, datetime: {get_today: () => "2026-10-29", str_to_user: value => value},
	call: async ({method, args}) => {
		calls.push({method, args});
		if (method.endsWith("get_history")) return {message: {rows: [record], has_more: true}};
		if (method.endsWith("get_details")) return {message: {...record}};
		if (method.endsWith("get_print_options")) return {message: {name: args.name, docstatus: record.docstatus, print_format: "Configured Receipt", a4_available: true}};
		throw Error("Unexpected API: " + method);
	},
};
window.eval(fs.readFileSync(new URL("../public/js/cashier_layout.js", import.meta.url), "utf8"));
window.eval(fs.readFileSync(new URL("../public/js/booking_page.js", import.meta.url), "utf8"));
const page = new window.HalaBookingPage($("#page")[0], {history: true});
assert.equal($("[data-hala-nav]").eq(3).text().trim(), "سجل فواتير الحجز");
await page.show();
assert.equal(calls[0].method, "hala.api.booking_history.get_history");
assert.equal($("[data-history-rows] script").length, 0);
// Click a non-link cell: the whole invoice row must select the invoice.
$("[data-history-booking] td").eq(1).trigger("click");
assert.match($("[role='status']").text(), /جارٍ تحميل/);
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal($("[data-history-detail]").prop("hidden"), false);
assert.equal($("[data-history-detail] input:not(:disabled)").length, 0);
assert.equal($("[data-history-detail] [data-action='save'], [data-history-detail] [data-action='new-booking'], [data-history-detail] [data-action='finalize'], [data-history-detail] [data-action='pay']").length, 0);
assert.equal($("[data-history-detail] input, [data-history-detail] textarea, [data-history-detail] select").length, 0);
assert.equal($("[data-history-detail] [data-history-print]").length, 2);
let printed;
window.halaBookingPOSPrint = async (...args) => {printed = args;};
await page.print_history("pos");
assert.equal(printed[0], "BOOK-1");
assert.equal(printed[1], "Configured Receipt");
page.open_a4_print = name => {printed = name;};
await page.print_history("a4");
assert.equal(printed, "BOOK-1");
await page.render_booking({...record, docstatus: 1});
assert.equal($("[data-history-detail] [data-history-print]").length, 2);
const before = calls.length;
await page.save(); page.pay(); page.finalize(); await page.new_booking();
assert.equal(calls.length, before, "history actions cannot invoke write APIs");
page.history_start = 20;
await page.load_history();
assert.equal(calls.at(-1).args.start, 20);
$("[data-history-search]").val("555");
$("[data-history-status]").val("confirmed");
await page.load_history();
assert.equal(calls.at(-1).args.search, "555");
assert.equal(calls.at(-1).args.status, "confirmed");
const regularCall = window.frappe.call;
window.frappe.call = async ({method, args}) => {
	if (method.endsWith("get_details")) throw Error("Denied");
	return regularCall({method, args});
};
await page.load_history_details("DENIED");
assert.equal(page.booking, null);
assert.equal($("[data-history-detail]").prop("hidden"), true);
assert.match($("[role='status']").text(), /تعذر تحميل الفاتورة DENIED/);
assert.equal($("[data-history-retry]").length, 1);
// An older response must never replace the most recently selected invoice.
const pending = {};
window.frappe.call = ({args}) => new Promise(resolve => {pending[args.name] = resolve;});
const first = page.load_history_details("FIRST");
const second = page.load_history_details("SECOND");
pending.SECOND({message: {...record, name: "SECOND"}}); await second;
pending.FIRST({message: {...record, name: "FIRST"}}); await first;
assert.equal(page.booking.name, "SECOND");
window.frappe.call = regularCall;
await page.print_history("pos");
assert.equal(printed[0], "SECOND");
console.log("PASS: row-cell selection, visible loading/error/retry, stale-response rejection, static read-only preview, dynamic configured POS format, A4 selected invoice, no mutation APIs, pagination/search and escaped text.");
window.close();
