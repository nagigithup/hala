import assert from "node:assert/strict";
import fs from "node:fs";
import {createRequire} from "node:module";
import path from "node:path";
import {fileURLToPath} from "node:url";

const require = createRequire(import.meta.url);
const {JSDOM} = require("../../../pos_next/POS/node_modules/jsdom");
const jquery = require("../../../frappe/node_modules/jquery");
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const bench = path.resolve(app, "../..");
const assets = JSON.parse(fs.readFileSync(path.join(bench, "sites/assets/assets.json"), "utf8"));
const url = assets["cashier_layout.bundle.js"];
assert.match(url, /^\/assets\/hala\/dist\/js\/cashier_layout\.bundle\.[A-Z0-9]+\.js$/);
const bundle = fs.readFileSync(path.join(app, "hala/public", url.split("/assets/hala/")[1]), "utf8");
const hooks = fs.readFileSync(path.join(app, "hala/hooks.py"), "utf8");
assert.ok(hooks.includes('"cashier_layout.bundle.js"'));
assert.ok(!hooks.includes('"/assets/hala/js/cashier_layout.js"'), "Desk must not request the immutable unversioned script");

const original = ["booking", "deposit", "receipt", "booking-history"];
const cases = [
	{roles: ["Hala Portal User"], actions: []},
	{roles: ["سند الصرف"], actions: ["disbursement"]},
	{roles: ["Purchase Manager"], actions: ["purchase"]},
	{roles: ["سند الصرف", "Purchase Manager"], actions: ["disbursement", "purchase"]},
	{roles: ["System Manager"], actions: ["disbursement", "purchase"]},
];

// Exercise the built asset across permissions, all existing pages and repeated mounts.
for (let reload = 0; reload < 2; reload++) for (const {roles, actions} of cases) {
	const {window} = new JSDOM("<main></main>", {url: "http://tag.localhost:8000/desk/hala-booking", runScripts: "outside-only"});
	const $ = jquery(window);
	window.$ = $;
	const routes = [], scripts = [], shown = [];
	window.frappe = {
		utils: {icon: name => `<svg data-icon="${name}"></svg>`},
		user: {has_role: role => roles.includes(role)},
		set_route: (...route) => routes.push(route),
		require: async script => scripts.push(script),
	};
	for (const [id, controller] of [["disbursement", "HalaDisbursement"], ["purchase", "HalaQuickPurchase"]]) {
		window[controller] = class {
			constructor(page) {this.page = page; this.dialog = {$wrapper: $("<div></div>")};}
			async show() {shown.push(id);}
		};
	}
	window.eval(bundle);
	const page = {main: $("main")};
	for (const active of original) {
		window.halaCashierLayout.mount({page, active, content: "<p>Page content</p>"});
		const links = $("[data-hala-nav]");
		assert.deepEqual(links.map((_, el) => el.dataset.halaNav).get(), ["booking", "deposit", "receipt", ...actions, "booking-history"]);
		assert.equal(links.last().text().trim(), "سجل فواتير الحجز");
		assert.equal(links.filter('[aria-current="page"]').attr("data-hala-nav"), active);
		assert.deepEqual(links.filter("a").map((_, el) => el.getAttribute("href")).get(), [
			"/desk/hala-booking", "/desk/hala-deposit", "/desk/hala-receipt", "/desk/hala-booking-history",
		]);
		links.filter("a").each((_, el) => $(el).trigger("click"));
		assert.deepEqual(routes.slice(-4).map(route => route[0]), ["hala-booking", "hala-deposit", "hala-receipt", "hala-booking-history"]);
		for (const id of ["disbursement", "purchase"]) {
			if (!actions.includes(id)) {
				const before = shown.length;
				await window.halaCashierLayout.show_action(page, id);
				assert.equal(shown.length, before, "hidden actions cannot be opened by the renderer");
				continue;
			}
			const button = links.filter(`[data-hala-nav="${id}"]`);
			assert.ok(button.is('button[type="button"]'));
			assert.equal(button.find("svg").attr("data-icon"), id === "purchase" ? "shopping-cart" : "banknote-arrow-up");
			button.trigger("click");
			await new Promise(setImmediate);
			assert.equal(shown.at(-1), id);
			assert.equal(scripts.at(-1), `/assets/hala/js/${id === "purchase" ? "quick_purchase" : "disbursement"}.js`);
			assert.equal(links.filter('[aria-current="page"]').attr("data-hala-nav"), id);
			const instance = page[`hala_nav_${id}`];
			assert.equal(instance.page, page);
			instance.dialog.$wrapper.trigger("hidden.bs.modal");
			assert.equal(links.filter('[aria-current="page"]').attr("data-hala-nav"), active);
			await window.halaCashierLayout.show_action(page, id);
			assert.equal(page[`hala_nav_${id}`], instance, "reopening uses the same feature controller");
			instance.dialog.$wrapper.trigger("hidden.bs.modal");
		}
	}
	window.close();
}
console.log(`PASS: hashed production asset ${url}; six ordered items, role visibility, original routes, existing dialog actions, active-state restoration and repeated mounts without duplicates.`);
