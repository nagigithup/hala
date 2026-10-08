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
	let reject;
	const promise = new Promise((done, fail) => {
		resolve = done;
		reject = fail;
	});
	return { promise, resolve, reject };
}

function createTimers() {
	let now = 0;
	let nextId = 1;
	const scheduled = new Map();
	return {
		now: () => now,
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
	visibleCount = Math.min(itemCount, 100),
	itemsPerPage = 100,
	duplicateRows = false,
	cartItems = [],
	nativeCustomerPricing = true,
	transportIgnoresAbort = false,
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
		async addItem(item, qty) {
			this.invoiceItems.push({ ...item, quantity: qty });
			return item;
		},
		recalculateItem() {},
		rebuildIncrementalCache() {},
		$subscribe(callback) {
			subscribers.cart = callback;
		},
	};
	if (nativeCustomerPricing) cart.effectivePriceList = null;
	const items = {
		posProfile: "Test POS",
		allItems: catalogItems,
		filteredItems: catalogItems.slice(0, visibleCount),
		searchResults: duplicateRows ? [...catalogItems] : [],
		searchTerm: "",
		itemsPerPage,
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
	const contextRequests = [];
	let serverPricingDate = "2026-10-07";
	let active = 0;
	let maxConcurrent = 0;

	function fetch(url, options = {}) {
		const request = deferred();
		const parsed = new URL(url, "https://local.test");
		if (parsed.pathname.includes("get_pricing_context")) {
			const entry = {
				settled: false,
				resolve(
					date = serverPricingDate,
					dateRefreshMs = 86_400_000,
					priceList = "Customer List",
				) {
					if (entry.settled) return;
					entry.settled = true;
					active--;
					request.resolve({
						ok: true,
						async json() {
							return {
								message: {
									price_list: priceList,
									pricing_date: date,
									date_refresh_ms: dateRefreshMs,
								},
							};
						},
					});
				},
			};
			active++;
			maxConcurrent = Math.max(maxConcurrent, active);
			contextRequests.push(entry);
			return request.promise;
		}
		const requestItems = JSON.parse(parsed.searchParams.get("items"));
		active++;
		maxConcurrent = Math.max(maxConcurrent, active);
		const entry = {
			url,
			customer: parsed.searchParams.get("customer"),
			items: requestItems,
			settled: false,
			aborted: false,
			resolve(rates = {}) {
				if (entry.settled) return;
				entry.settled = true;
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
						return {
							message: {
								prices,
								prices_by_request: pricesByRequest,
								price_list: "Customer List",
								pricing_date: serverPricingDate,
								date_refresh_ms: 86_400_000,
							},
						};
					},
				});
			},
			fail(message = "pricing failed") {
				if (entry.settled) return;
				entry.settled = true;
				active--;
				request.resolve({
					ok: false,
					async json() {
						return { message };
					},
				});
			},
		};
		options.signal?.addEventListener?.("abort", () => {
			entry.aborted = true;
			if (transportIgnoresAbort || entry.settled) return;
			entry.settled = true;
			active--;
			const error = new Error("aborted");
			error.name = "AbortError";
			request.reject(error);
		});
		requests.push(entry);
		return request.promise;
	}

	class FakeAbortController {
		constructor() {
			const listeners = [];
			this.signal = {
				aborted: false,
				addEventListener(name, callback) {
					if (name === "abort") listeners.push(callback);
				},
			};
			this.abort = () => {
				if (this.signal.aborted) return;
				this.signal.aborted = true;
				for (const callback of listeners) callback();
			};
		}
	}

	const RealDate = Date;
	class FakeDate extends RealDate {
		static now() {
			return timers.now();
		}
	}

	const context = vm.createContext({
		AbortController: FakeAbortController,
		console: { error() {} },
		Date: FakeDate,
		document: {
			currentScript: {
				dataset: {
					pricingDate: "2026-10-07",
					dateRefreshMs: "86400000",
				},
			},
			getElementById: () => app,
			querySelector: () => null,
		},
		fetch,
		Map,
		navigator: { onLine: true },
		URLSearchParams,
		setTimeout: timers.setTimeout,
		clearTimeout: timers.clearTimeout,
	});
	vm.runInContext(scriptSource, context, { filename: scriptPath.pathname });

	return {
		cart,
		contextRequests,
		items,
		pricingApi: context.halaPOSPricing,
		requests,
		subscribers,
		timers,
		setServerPricingDate(date) {
			serverPricingDate = date;
		},
		setVisibleRange(start, count = visibleCount) {
			items.filteredItems = items.allItems.slice(start, start + count);
			subscribers.items();
		},
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

test("pricing-output store mutations and ten minutes idle create zero requests", async () => {
	const harness = createHarness({ itemCount: 25, visibleCount: 25 });
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve();
	await flushPromises();

	for (let mutation = 0; mutation < 100; mutation++) {
		harness.subscribers.items();
		harness.subscribers.cart();
	}
	harness.timers.advance(10 * 60 * 1000);
	await flushPromises();
	assert.equal(harness.requests.length, 1);
});

test("only newly visible catalog rows are priced in a large catalog", async () => {
	const harness = createHarness({ itemCount: 1_074, visibleCount: 25 });
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 1);
	assert.equal(harness.requests[0].items.length, 25);
	harness.requests[0].resolve();
	await flushPromises();

	harness.setVisibleRange(25, 25);
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	assert.deepEqual(
		harness.requests[1].items.map((item) => item.item_code),
		harness.items.allItems.slice(25, 50).map((item) => item.item_code),
	);
	harness.requests[1].resolve();
	await flushPromises();
	assert.equal(harness.requests.length, 2);
});

test("barcode-selected items outside the visible catalog use on-demand pricing", async () => {
	const harness = createHarness({ itemCount: 0, nativeCustomerPricing: false });
	const add = harness.cart.addItem(
		{ item_code: "BARCODE-ITEM", uom: "Box", stock_uom: "Nos", rate: 0 },
		2,
	);
	await flushPromises();
	assert.equal(harness.requests.length, 1);
	assert.deepEqual(harness.requests[0].items[0], {
		item_code: "BARCODE-ITEM",
		uom: "Box",
		qty: 2,
		request_key: "0",
	});
	harness.requests[0].resolve({ "BARCODE-ITEM": 88 });
	await add;
	assert.equal(harness.cart.invoiceItems[0].rate, 88);
});

test("compatibility cart quantity and UOM changes are genuine pricing inputs", async () => {
	const cartItem = { item_code: "ITEM-001", uom: "Nos", quantity: 1, rate: 0 };
	const harness = createHarness({
		itemCount: 0,
		cartItems: [cartItem],
		nativeCustomerPricing: false,
	});
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();

	cartItem.quantity = 3;
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests[1].items[0].qty, 3);
	harness.requests[1].resolve({ "ITEM-001": 25 });
	await flushPromises();

	cartItem.uom = "Box";
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests[2].items[0].uom, "Box");
	harness.requests[2].resolve({ "ITEM-001": 75 });
	await flushPromises();
	assert.equal(cartItem.rate, 75);
});

test("four 1,074-item sessions remain idle after pricing their visible 25 rows", async () => {
	const sessions = Array.from({ length: 4 }, () =>
		createHarness({ itemCount: 1_074, visibleCount: 25 }),
	);
	for (const session of sessions) session.timers.advance(81);
	await flushPromises();
	for (const session of sessions) {
		assert.equal(session.requests.length, 1);
		session.requests[0].resolve();
	}
	await flushPromises();
	for (const session of sessions) {
		for (let mutation = 0; mutation < 20; mutation++)
			session.subscribers.items();
		session.timers.advance(10 * 60 * 1000);
	}
	await flushPromises();
	assert.equal(
		sessions.reduce((total, session) => total + session.requests.length, 0),
		4,
	);
	assert.ok(sessions.every((session) => session.maxConcurrent === 1));
	console.log(
		"POS pricing 4-session metrics:",
		JSON.stringify({
			catalogItemsPerSession: 1_074,
			visibleItemsPerSession: 25,
			apiRequests: 4,
			duplicateRequests: 0,
			idleRequests: 0,
			maxConcurrentPerSession: 1,
		}),
	);
});

test("a failed request clears pending state and a later genuine item change retries", async () => {
	const harness = createHarness({ itemCount: 2, visibleCount: 1 });
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 1);
	harness.requests[0].fail();
	await flushPromises();

	harness.setVisibleRange(1, 1);
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.requests[1].resolve({ "ITEM-002": 42 });
	await flushPromises();
	assert.equal(harness.items.allItems[1].rate, 42);
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

test("customer A is authoritatively revalidated after A to B to A", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();

	harness.cart.customer = { name: "Customer B" };
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[1].resolve({ "ITEM-001": 20 });
	await flushPromises();

	// Simulate an authoritative Customer A price change while B is selected.
	harness.cart.customer = { name: "Customer A" };
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(
		harness.requests.length,
		3,
		"returning to A must not reuse old A cache",
	);
	assert.equal(harness.requests[2].customer, "Customer A");
	harness.requests[2].resolve({ "ITEM-001": 30 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 30);
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

test("expired cache entries wait for genuine demand before being fetched again", async () => {
	const harness = createHarness({ itemCount: 2, visibleCount: 1 });
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 10);

	harness.timers.advance(5 * 60 * 1000 + 1);
	harness.subscribers.items();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 1, "TTL expiry alone must not fetch");

	harness.setVisibleRange(1, 1);
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[1].resolve({ "ITEM-002": 20 });
	await flushPromises();
	harness.setVisibleRange(0, 1);
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 3);
	harness.requests[2].resolve({ "ITEM-001": 25 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 25);
});

test("LRU eviction never independently schedules a pricing request", async () => {
	const harness = createHarness({ itemCount: 600, visibleCount: 100 });
	for (let page = 0; page < 6; page++) {
		if (page) harness.setVisibleRange(page * 100, 100);
		harness.timers.advance(81);
		await flushPromises();
		const firstRequest = page * 4;
		for (let batch = 0; batch < 4; batch++) {
			harness.requests[firstRequest + batch].resolve();
			await flushPromises();
		}
	}
	assert.equal(harness.requests.length, 24);
	harness.subscribers.items();
	harness.timers.advance(10 * 60 * 1000);
	await flushPromises();
	assert.equal(
		harness.requests.length,
		24,
		"eviction/output mutations must stay idle",
	);
});

test("site midnight invalidates date pricing without using the browser date", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(
		new URL(harness.requests[0].url, "https://local.test").searchParams.has(
			"transaction_date",
		),
		false,
	);
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();

	harness.setServerPricingDate("2026-10-08");
	harness.timers.advance(86_400_000);
	await flushPromises();
	assert.equal(harness.contextRequests.length, 1);
	harness.contextRequests[0].resolve("2026-10-08");
	await flushPromises();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.requests[1].resolve({ "ITEM-001": 40 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 40);
});

test("hung request times out, releases pending keys, and recovers once", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	harness.timers.advance(15_001);
	await flushPromises();
	assert.equal(harness.requests[0].aborted, true);
	harness.cart.customer = { name: "Customer B" };
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.requests[1].resolve({ "ITEM-001": 60 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 60);
});

test("late response after logical timeout cannot overwrite recovered pricing", async () => {
	const harness = createHarness({ transportIgnoresAbort: true });
	harness.timers.advance(81);
	await flushPromises();
	harness.timers.advance(15_001);
	await flushPromises();
	harness.cart.customer = { name: "Customer B" };
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.requests[1].resolve({ "ITEM-001": 70 });
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 5 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 70);
});

test("repeated timeouts require mutations and do not create an automatic storm", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	harness.timers.advance(15_001);
	await flushPromises();
	harness.cart.customer = { name: "Customer B" };
	harness.subscribers.cart();
	harness.timers.advance(81);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	harness.timers.advance(15_001 + 1_000);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
});

test("separate POS tabs keep bounded independent request coordinators", async () => {
	const firstTab = createHarness();
	const secondTab = createHarness();
	firstTab.timers.advance(81);
	secondTab.timers.advance(81);
	await flushPromises();
	assert.equal(firstTab.requests.length, 1);
	assert.equal(secondTab.requests.length, 1);
	firstTab.requests[0].resolve({ "ITEM-001": 11 });
	secondTab.requests[0].resolve({ "ITEM-001": 22 });
	await flushPromises();
	assert.equal(firstTab.items.allItems[0].rate, 11);
	assert.equal(secondTab.items.allItems[0].rate, 22);
	assert.equal(firstTab.maxConcurrent, 1);
	assert.equal(secondTab.maxConcurrent, 1);
});

test("manual refresh bypasses TTL, clears cache, and commits new catalog prices atomically", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();
	assert.equal(harness.items.allItems[0].rate, 10);

	const first = harness.pricingApi.prepareRefresh();
	const duplicate = harness.pricingApi.prepareRefresh();
	assert.equal(duplicate, first);
	await flushPromises();
	assert.equal(harness.requests.length, 2);
	assert.equal(
		harness.items.allItems[0].rate,
		10,
		"prepared prices must not apply early",
	);
	harness.requests[1].resolve({ "ITEM-001": 35 });
	const transaction = await first;
	assert.equal(harness.items.allItems[0].rate, 10);
	assert.equal(transaction.commit(), true);
	assert.equal(harness.items.allItems[0].rate, 35);
	assert.equal(
		harness.requests.length,
		2,
		"duplicate clicks must share one request",
	);
	transaction.rollback();
	assert.equal(harness.items.allItems[0].rate, 10);
});

test("manual refresh resolves the latest Price List when no catalog rows are visible", async () => {
	const harness = createHarness({ itemCount: 0 });
	const refresh = harness.pricingApi.prepareRefresh();
	await flushPromises();
	assert.equal(harness.requests.length, 0);
	assert.equal(harness.contextRequests.length, 1);
	harness.contextRequests[0].resolve("2026-10-07", 86_400_000, "New List");
	const transaction = await refresh;
	assert.equal(transaction.priceList, "New List");
	assert.equal(transaction.commit(), true);
});

test("failed manual refresh leaves displayed prices intact and can be retried", async () => {
	const harness = createHarness();
	harness.timers.advance(81);
	await flushPromises();
	harness.requests[0].resolve({ "ITEM-001": 10 });
	await flushPromises();

	const failedRefresh = harness.pricingApi.prepareRefresh();
	await flushPromises();
	harness.requests[1].fail();
	await assert.rejects(failedRefresh);
	assert.equal(harness.items.allItems[0].rate, 10);

	const retry = harness.pricingApi.prepareRefresh();
	await flushPromises();
	assert.equal(harness.requests.length, 3);
	harness.requests[2].resolve({ "ITEM-001": 45 });
	const transaction = await retry;
	assert.equal(transaction.commit(), true);
	assert.equal(harness.items.allItems[0].rate, 45);
});
