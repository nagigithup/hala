import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {webcrypto} from "node:crypto";
import vm from "node:vm";
const require = createRequire(import.meta.url);
const {JSDOM} = require("../../../pos_next/POS/node_modules/jsdom");
const window = new JSDOM("<div></div>", {url: "http://hala-disbursement-test.localhost"}).window;
const $ = require("../../../frappe/node_modules/jquery")(window);
let creates = [], confirms = [], result = {name: "DISB-1", status: "مدفوع", paid: true}, failure;
class Dialog {
	constructor(options) {
		Object.assign(this, options);
		this.values = Object.fromEntries(options.fields.map(f => [f.fieldname, f.default ?? (f.fieldtype === "Select" ? (Array.isArray(f.options) ? f.options[0] : f.options.split("\n")[0]) : "")]));
		this.fields_dict = Object.fromEntries(options.fields.map(f => [f.fieldname, {df: {...f}, $wrapper: $("<div/>").html(f.options || "")} ]));
		this.$wrapper = $("<div/>");
	}
	get_value(key) { return this.values[key]; }
	async set_value(key, value) { this.values[key] = value; }
	set_df_property(key, prop, value) { this.fields_dict[key].df[prop] = value; }
	show() { this.is_visible = true; }
	hide() { this.is_visible = false; }
	disable_primary_action() { this.disabled = true; }
	enable_primary_action() { this.disabled = false; }
}
const frappe = {
	session: {user: "cashier@example.test"}, ui: {Dialog},
	utils: {escape_html: value => $("<div/>").text(value).html()}, datetime: {get_today: () => "2026-11-04"},
	msgprint() {}, confirm(message, yes) { confirms.push(yes); }, require: async () => {}, set_route() {},
	call: async ({method, args}) => {
		if (method.endsWith("get_context")) return {message: {company: "Test", payment_account: "Cash", mode_of_payment: "Cash", employee_supported: true, accountant: false}};
		if (method.endsWith("get_history")) return {message: []};
		if (method.endsWith("get_sources")) return {message: [{doctype: "Payment Entry", name: "PE-ADV", balance: 60, currency: "SAR"}]};
		if (method.endsWith("create_voucher")) {creates.push(JSON.parse(args.data)); if (failure) throw failure; return {message: result};}
		if (method.endsWith("get_print_options")) return {message: {doctype: "Journal Entry", name: "JE-1", print_format: "Hala Disbursement Expense"}};
		throw Error(method);
	},
};
const context = vm.createContext({window, $, frappe, crypto: webcrypto, localStorage: window.localStorage, console});
vm.runInContext(readFileSync(new URL("../public/js/disbursement.js", import.meta.url), "utf8"), context);
const page = new window.HalaDisbursement({});
await page.show();
assert.equal(page.dialog.$wrapper.attr("dir"), "rtl");
assert.deepEqual(Array.from(page.dialog.fields_dict.kind.df.options), ["رد مبلغ لعميل", "دفع لمورد", "سلف موظفين", "مصروفات عامة"]);
assert.equal(page.dialog.fields_dict.party.df.reqd, true);
assert.equal(page.dialog.fields_dict.source.df.reqd, true);
await page.dialog.set_value("kind", "مصروفات عامة"); await page.change_kind();
assert.equal(page.dialog.fields_dict.party.df.hidden, true);
assert.equal(page.dialog.fields_dict.expense_category.df.reqd, true);
assert.equal(page.dialog.fields_dict.beneficiary.df.reqd, true);
await page.dialog.set_value("kind", "سلف موظفين"); await page.change_kind();
assert.equal(page.dialog.get_value("party_type"), "Employee");
assert.equal(page.dialog.fields_dict.source.df.hidden, true);
await page.dialog.set_value("kind", "رد مبلغ لعميل"); await page.change_kind();
await page.dialog.set_value("party", "Customer"); await page.load_sources();
await page.dialog.set_value("source", "Payment Entry: PE-ADV"); page.show_balance();
assert.match(page.dialog.fields_dict.balance.$wrapper.text(), /60 SAR/);
const data = {kind: "رد مبلغ لعميل", amount: 20, party: "Customer", description: "Refund"};
await page.save(data); await page.save(data); // Two confirmation windows must still create just one intent.
confirms.splice(0).forEach(fn => fn());
await new Promise(resolve => setTimeout(resolve, 5));
assert.equal(creates.length, 1);
assert.equal(creates[0].source_name, "PE-ADV");
assert.equal(window.localStorage.getItem(page.pendingKey), null);

// Ambiguous network failure survives reload and retries the exact immutable request.
await page.show(); failure = new Error("network disconnected");
await page.save(data); confirms.shift()(); await new Promise(resolve => setTimeout(resolve, 5));
const intent = creates.at(-1);
assert.equal(page.dialog.disabled, true);
assert.equal(page.dialog.fields_dict.policy.$wrapper.find("[data-recover]").length, 1);
const reloaded = new window.HalaDisbursement({}); await reloaded.show();
assert.equal(reloaded.pending.request_id, intent.request_id);
failure = undefined;
await reloaded.send(reloaded.pending);
assert.equal(creates.at(-1).request_id, intent.request_id);
assert.equal(reloaded.pending, null);
// A definite validation rejection allows correction.
await reloaded.show(); failure = {status: 417};
await reloaded.save(data); confirms.shift()(); await new Promise(resolve => setTimeout(resolve, 5));
assert.equal(reloaded.pending, null); assert.equal(reloaded.dialog.disabled, false);
let printArgs;
window.halaBookingPOSPrint = (...args) => {printArgs = args;};
await reloaded.print("DISB-1");
assert.equal(printArgs[2].doctype, "Journal Entry");

// The shared QZ path handles standard accounting documents and falls back only before dispatch.
let beforePrint, preparationFailure = false, dispatchFailure = false, dispatched = 0;
window.halaSmartPrint = (doctype, name, format, options) => {assert.equal(doctype, "Journal Entry"); beforePrint = options.beforePrint;};
frappe.call = async ({method}) => ({message: method === "frappe.client.get" ? {name: "JE-1", docstatus: 1} : {silent_print: 1}});
const qz = {security: {setCertificatePromise() {}, setSignatureAlgorithm() {}, setSignaturePromise() {}},
	websocket: {isActive: () => false, async connect() {if (preparationFailure) throw Error("QZ offline");}},
	printers: {async find() {return ["Receipt"];}, async getDefault() {return "Receipt";}}, configs: {create: () => ({})},
	async print() {dispatched++; if (dispatchFailure) throw Error("ambiguous dispatch");}};
context.qz = qz; context.html2canvas = async () => ({toDataURL: () => "data:image/png;base64,aA=="});
delete window.halaBookingPOSPrint;
vm.runInContext(readFileSync(new URL("../public/js/booking_pos_print.bundle.js", import.meta.url), "utf8").replace(/^import .*;\n/gm, ""), context);
window.halaBookingPOSPrint("JE-1", "Hala Disbursement Expense", {doctype: "Journal Entry"});
const printDocument = {querySelector: () => ({scrollHeight: 100, offsetHeight: 100})};
preparationFailure = true; assert.equal(await beforePrint(printDocument), false); assert.equal(dispatched, 0);
preparationFailure = false; assert.equal(await beforePrint(printDocument), true); assert.equal(dispatched, 1);
dispatchFailure = true; await assert.rejects(beforePrint(printDocument), /ambiguous dispatch/); assert.equal(dispatched, 2);
console.log("PASS: four Arabic forms, source balances, confirmation double clicks, durable retry recovery, validation correction, accounting-document printing, QZ fallback and dispatch protection.");
