import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const { JSDOM } = require("../../../pos_next/POS/node_modules/jsdom");
const window = new JSDOM("<div id='dashboard'></div>", { url: "http://tag.localhost" }).window;
const $ = require("../../../frappe/node_modules/jquery")(window);
const handlers = {};
const dialogs = [];
const calls = [];
let pay;
let context = {
	invoice: "PINV-TEST", company: "Company", supplier: "Supplier", invoice_total: 87.5,
	invoice_currency: "SAR", bank_currency: "SAR", party_currency: "SAR", outstanding: 87.5,
	available_advance: 0, can_pay: true, default_bank_account: "Cash",
	bank_account: "Cash", source_exchange_rate: 1, target_exchange_rate: 1,
	amount_precision: 2, received_precision: 2, allocation_precision: 2,
};
class Dialog {
	constructor(options) {
		Object.assign(this, options);
		this.values = Object.fromEntries(options.fields.map(field => [field.fieldname, field.default]));
		this.fields_dict = Object.fromEntries(options.fields.map(field => [field.fieldname, { df: { ...field }, $wrapper: $("<div/>") }]));
		this.button = $("<button/>");
		dialogs.push(this);
	}
	get_values() { return { ...this.values }; }
	get_value(name) { return this.values[name]; }
	async set_value(name, value) { this.values[name] = value; }
	set_df_property(name, key, value) { this.fields_dict[name].df[key] = value; }
	get_primary_btn() { return this.button; }
	show() {}
	hide() { this.hidden = true; }
}
const frm = {
	doc: { name: "PINV-TEST", docstatus: 1, paid_amount: 0 }, buttons: new Map(),
	is_new: () => false, set_df_property() {}, reload_doc() {},
	add_custom_button(label, callback) { this.buttons.set(label, callback); },
	dashboard: {
		parent: $("#dashboard"), add_section() { return $("<div class='hala-supplier-payments'/>").appendTo("#dashboard"); },
		set_headline_alert(message) { throw new Error(message); },
	},
};
const frappe = {
	boot: { sitename: "tag.localhost" }, session: { user: "test-user" },
	ui: { form: { on(doctype, events) { assert.equal(doctype, "Purchase Invoice"); Object.assign(handlers, events); } }, Dialog },
	utils: { escape_html: text => String(text), get_form_link: (dt, name) => name },
	datetime: { get_today: () => new Date().toISOString().slice(0, 10) },
	async call({ method, args }) {
		calls.push({ method, args });
		return { message: method.endsWith("get_context") ? { ...context } : await pay(args) };
	},
	msgprint() {}, confirm(message, yes) { yes(); }, set_route() {},
	throw(message) { throw new Error(message); },
};
vm.runInNewContext(readFileSync(new URL("../public/js/purchase_invoice.js", import.meta.url), "utf8"), {
	frappe, $, localStorage: window.localStorage, crypto: webcrypto,
	__: text => text, format_currency: (value, currency) => `${currency} ${value}`,
	flt: (value, precision) => precision === undefined ? Number(value || 0) : Number(Number(value || 0).toFixed(precision)),
});

await handlers.refresh(frm);
assert.equal($(".hala-supplier-payments").length, 1);
await handlers.refresh(frm);
assert.equal($(".hala-supplier-payments").length, 1);
await frm.buttons.get("Supplier Payment")();
let dialog = dialogs.at(-1);
assert.equal(dialog.fields_dict.invoice_total.df.read_only, 1);
assert.equal(dialog.fields_dict.allocated.df.read_only, 1);
assert.equal(dialog.fields_dict.advance.df.read_only, 1);
assert.ok(!dialog.fields_dict.actual_amount.df.read_only);
await dialog.set_value("actual_amount", 100);
dialog.fields_dict.actual_amount.df.onchange();
assert.equal(dialog.values.allocated, 87.5);
assert.equal(dialog.values.advance, 12.5);

// A double click dispatches once. An uncertain response retains the immutable
// intent so a reload can safely retry the same request ID and amounts.
let fail;
pay = () => new Promise((resolve, reject) => { fail = reject; });
const first = dialog.primary_action();
await dialog.primary_action();
assert.equal(calls.filter(call => call.method.endsWith("pay_supplier")).length, 1);
const firstArgs = calls.at(-1).args;
fail(new Error("network disconnected"));
await first;
assert.equal(dialog.fields_dict.actual_amount.df.read_only, 1);
const saved = JSON.parse(window.localStorage.getItem(window.localStorage.key(0)));
assert.equal(saved.args.request_id, firstArgs.request_id);

// Simulate a successful server submission whose response was lost: the invoice
// is now settled, but the form must still expose the retry/recovery action.
context = { ...context, outstanding: 0, can_pay: false };
frm.buttons.clear();
await handlers.refresh(frm);
assert.ok(frm.buttons.has("Retry Previous Payment"));
await frm.buttons.get("Retry Previous Payment")();
dialog = dialogs.at(-1);
assert.equal(dialog.values.bank_currency, "SAR");
assert.equal(dialog.values.allocated, 87.5);
pay = async args => {
	assert.equal(args.request_id, firstArgs.request_id);
	assert.equal(args.actual_amount, 100);
	return { name: "PE-TEST", docstatus: 1, allocated_amount: 87.5, unallocated_amount: 12.5, party_currency: "SAR" };
};
await dialog.primary_action();
assert.ok(dialog.hidden);
assert.equal(JSON.parse(window.localStorage.getItem(window.localStorage.key(0))).completed, true);
assert.equal(frm.doc.paid_amount, 0);

// Definite server validation errors permit correction; no uncertain request ID
// is silently reused with changed financial inputs.
context = { ...context, outstanding: 50, can_pay: true };
await handlers.refresh(frm);
await frm.buttons.get("Supplier Payment")();
dialog = dialogs.at(-1);
await dialog.set_value("actual_amount", 50);
pay = async () => { throw { responseJSON: { exc_type: "ValidationError" } }; };
await dialog.primary_action();
assert.equal(window.localStorage.length, 0);
assert.equal(dialog.fields_dict.actual_amount.df.read_only, 0);
assert.equal(frm.doc.paid_amount, 0);

console.log("PASS: read-only calculated fields, allocations, duplicate click, persistent recovery after refresh, server-error correction, no invoice payment-field writes.");
