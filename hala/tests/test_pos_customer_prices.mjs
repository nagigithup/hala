import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const scriptPath = new URL(
	"../public/js/pos_customer_prices.js",
	import.meta.url,
);
const scriptSource = await readFile(scriptPath, "utf8");

function deferred() {
	let resolve;
	const promise = new Promise((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

function createTimers() {
	let now = 0;
	let nextId = 1;
	const scheduled = new Map();
	return {
		setTimeout(callback, delay = 0) {
			const id = nextId++;
			scheduled.set(id, { callback, at: now + delay });
			return id;
		},
		clearTimeout(id) {
			scheduled.delete(id);
		},
		advance(milliseconds) {
			const end = now + milliseconds;
			for (;;) {
				const due = [...scheduled.entries()]
					.filter(([, task]) => task.at <= end)
					.sort((left, right) => left[1].at - right[1].at)[0];
				if (!due) break;
				const [id, task] = due;
				scheduled.delete(id);
				now = task.at;
				task.callback();
			}
			now = end;
		},
	};
}

async function flushPromises(rounds = 12) {
	for (let index = 0; index < rounds; index++) await Promise.resolve();
	await new Promise((resolve) => setImmediate(resolve));
}

function createHarness({
	itemCount = 1,
	duplicateRows = false,
	cartItems = [],
} = {}) {
	const timers = createTimers();
	const subscribers = { cart: null, items: null };
	const catalogItems = Array.from({ length: itemCount }, (_, index) => ({
		item_code: duplicateRows
			? "ITEM-001"
			: `ITEM-${String(index + 1).padStart(3, "0")}`,
		uom: "Nos",
		rate: 0,
	}));
	const cart = {
		posProfile: "Test POS",
		customer: { name: "Customer A" },
		invoiceItems: cartItems,
		effectivePriceList: null,
		$subscribe(callback) {
			subscribers.cart = callback;
		},
	};
	const items = {
		posProfile: "Test POS",
		allItems: catalogItems,
		searchResults: duplicateRows ? [...catalogItems] : [],
		invalidateCache() {},
		$subscribe(callback) {
			subscribers.items = callback;
		},
	};
	const pinia = {
		_s: new Map([
			["posCart", cart],
			["itemSearch", items],
		]),
	};
	const app = {
		__vue_app__: { _context: { provides: { [Symbol("pinia")]: pinia } } },
	};
	const requests = [];
	let active = 0;
	let maxConcurrent = 0;

	function fetch(url) {
		const request = deferred();
		const parsed = new URL(url, "https://local.test");
		const requestItems = JSON.parse(parsed.searchParams.get("items"));
		active++;
		maxConcurrent = Math.max(maxConcurrent, active);
		requests.push({
			url,
			customer: parsed.searchParams.get("customer"),
			items: requestItems,
			resolve(rates = {}) {
				active--;
				const prices = {};
				const pricesByRequest = {};
				for (const item of requestItems) {
					const rate = rates[item.item_code] ?? rates.default ?? 100;
					const price = { rate, uom: item.uom };
					prices[item.item_code] = price;
					pricesByRequest[item.request_key] = price;
				}
				request.resolve({
					ok: true,
					async json() {
						return { message: { prices, prices_by_request: pricesByRequest } };
					},
				});
			},
			fail(message = "pricing failed") {
				active--;
				request.resolve({
					ok: false,
					async json() {
						return { message };
					},
				});
			},
		});
		return request.promise;
	}

	const context = vm.createContext({
		console: { error() {} },
		Date,
		document: { getElementById: () => app },
		fetch,
		frappe: { datetime: { get_today: () => "2026-10-07" } },
		Map,
		navigator: { onLine: true },
		URLSearchParams,
		setTimeout: timers.setTimeout,
		clearTimeout: timers.clearTimeout,
	});
	vm.runInContext(scriptSource, context, { filename: scriptPath.pathname });

	return {
		cart,
		items,
		requests,
		subscribers,
		timers,
		get maxConcurrent() {
			return maxConcurrent;
		},
	};
}

test("rapid mutations and in-flight mutations collapse into one serial catalog cycle", async () => {
	const harness = createHarness({ itemCount: 50 });
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 1);

	for (let mutation = 0; mutation < 100; mutation++) {
		harness.subscribers.cart();
		harness.subscribers.items();
		harness.timers.advance(81);
	}
	await flushPromises();
	assert.equal(
		harness.requests.length,
		1,
		"mutations must not start parallel requests",
	);

	harness.requests[0].resolve();
	await flushPromises();
	assert.equal(
		harness.requests.length,
		2,
		"the second unique 25-item batch should run next",
	);
	harness.requests[1].resolve();
	await flushPromises();
	harness.timers.advance(81);
	await flushPromises();

	const uniqueUrls = new Set(harness.requests.map((request) => request.url));
	assert.equal(harness.requests.length, 2);
	assert.equal(uniqueUrls.size, 2);
	assert.equal(harness.maxConcurrent, 1);
	assert.ok(harness.items.allItems.every((item) => item.rate === 100));
	console.log(
		"POS pricing storm metrics:",
		JSON.stringify({
			triggers: 201,
			apiRequests: harness.requests.length,
			uniqueRequests: uniqueUrls.size,
			duplicateRequests: harness.requests.length - uniqueUrls.size,
			maxConcurrent: harness.maxConcurrent,
		}),
	);
});

test("the same pricing key repeated across stores is fetched once", async () => {
	const harness = createHarness({ itemCount: 20, duplicateRows: true });
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 1);
	assert.equal(harness.requests[0].items.length, 1);
	harness.requests[0].resolve({ "ITEM-001": 55 });
	await flushPromises();
	assert.ok(harness.items.allItems.every((item) => item.rate === 55));
});

test("a failed request clears pending state and a later mutation retries", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 1);
	harness.requests[0].fail();
	await flushPromises();

	harness.subscribers.items();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.requests[1].resolve({ "ITEM-001": 42 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 42);
});

test("customer changes isolate cache and make the in-flight response stale", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests[0].customer, "Customer A");

	harness.cart.customer = { name: "Customer B" };
	harness.subscribers.cart();
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	assert.equal(harness.requests[1].customer, "Customer B");
	assert.equal(
		harness.items.allItems[0].rate,
		0,
		"stale customer A price must not be applied",
	);

	harness.requests[1].resolve({ "ITEM-001": 90 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 90);
});

test("an effective price-list change does not reuse the old cache entry", async () => {
	const harness = createHarness();
	harness.cart.effectivePriceList = "Retail";
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 40 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 40);

	harness.cart.effectivePriceList = "Wholesale";
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.requests[1].resolve({ "ITEM-001": 70 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 70);
});

test("native POS Next cart pricing and discounts are not overwritten", async () => {
	const cartItem = {
		item_code: "ITEM-001",
		uom: "Nos",
		quantity: 3,
		rate: 80,
		price_list_rate: 100,
		discount_percentage: 20,
		discount_amount: 20,
	};
	const harness = createHarness({ cartItems: [cartItem] });
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 55 });
	await flushPromises();

	assert.equal(harness.items.allItems[0].rate, 55);
	assert.deepEqual(cartItem, {
		item_code: "ITEM-001",
		uom: "Nos",
		quantity: 3,
		rate: 80,
		price_list_rate: 100,
		discount_percentage: 20,
		discount_amount: 20,
	});
});
