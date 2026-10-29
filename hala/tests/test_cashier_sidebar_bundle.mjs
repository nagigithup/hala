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
assert.ok(bundle.includes("hala-booking-history"), "production bundle must contain the fourth route");
const hooks = fs.readFileSync(path.join(app, "hala/hooks.py"), "utf8");
assert.ok(hooks.includes('"cashier_layout.bundle.js"'));
assert.ok(!hooks.includes('"/assets/hala/js/cashier_layout.js"'), "Desk must not request the immutable unversioned script");

// Test the built production asset, including repeated page mounts/reloads.
for (let reload = 0; reload < 2; reload++) {
	const {window} = new JSDOM("<main></main>", {url: "http://tag.localhost:8000/desk/hala-booking", runScripts: "outside-only"});
	const $ = jquery(window);
	const routes = [];
	window.frappe = {utils: {icon: () => ""}, set_route: (...route) => routes.push(route)};
	window.eval(bundle);
	const page = {main: $("main")};
	for (const active of ["booking", "deposit", "receipt", "booking-history"]) {
		window.halaCashierLayout.mount({page, active, content: "<p>Page content</p>"});
		const links = $("[data-hala-nav]");
		assert.equal(links.length, 4, "mounting another Hala page must not duplicate navigation");
		assert.deepEqual(links.map((_, element) => element.getAttribute("href")).get(), [
			"/desk/hala-booking", "/desk/hala-deposit", "/desk/hala-receipt", "/desk/hala-booking-history",
		]);
		assert.equal(links.eq(3).text().trim(), "سجل فواتير الحجز");
		assert.equal(links.filter('[aria-current="page"]').attr("data-hala-nav"), active);
		links.each((_, element) => $(element).trigger("click"));
		assert.deepEqual(routes.slice(-4).map(route => route[0]), ["hala-booking", "hala-deposit", "hala-receipt", "hala-booking-history"]);
	}
	window.close();
}
console.log(`PASS: hashed production asset ${url}; four ordered links, correct routes/active states, repeated mounts and reloads without duplicates.`);
