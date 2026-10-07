(() => {
	const METHOD = "/api/method/hala.api.pos_pricing.get_catalog_prices";
	const BATCH_SIZE = 25;
	const DEBOUNCE_MS = 80;
	let timer;
	let syncInFlight = null;
	let resyncRequested = false;
	let applyingPrices = false;
	let generation = 0;
	let lastSelection = "";
	const cachedPrices = new Map();
	const pendingPrices = new Map();
	const activeBatchRequests = new Map();
	let networkTail = Promise.resolve();
	let addItemWrapped = false;

	function findStores() {
		const app = document.getElementById("app")?.__vue_app__;
		const provides = app?._context?.provides;
		if (!provides) return null;
		// Pinia's production build uses an anonymous Symbol(), so locate it by
		// the store registry shape instead of relying on the symbol description.
		const pinia = Reflect.ownKeys(provides)
			.map((key) => provides[key])
			.find((value) => value?._s instanceof Map);
		const stores = pinia?._s;
		const cart = stores?.get("posCart");
		const items = stores?.get("itemSearch");
		return cart && items ? { cart, items } : null;
	}

	function getPricingDate() {
		if (globalThis.frappe?.datetime?.get_today)
			return globalThis.frappe.datetime.get_today();
		const today = new Date();
		const year = today.getFullYear();
		const month = String(today.getMonth() + 1).padStart(2, "0");
		const day = String(today.getDate()).padStart(2, "0");
		return `${year}-${month}-${day}`;
	}

	function getContext({ cart, items }) {
		const profile =
			cart.posProfile?.name || cart.posProfile || items.posProfile;
		const customer = cart.customer?.name || cart.customer || "";
		const priceListValue =
			cart.effectivePriceList?.value ?? cart.effectivePriceList;
		const effectivePriceList = priceListValue?.name || priceListValue || "";
		const transactionDate = getPricingDate();
		return {
			profile,
			customer,
			effectivePriceList,
			transactionDate,
			selection: JSON.stringify([
				profile || "",
				customer,
				effectivePriceList,
				transactionDate,
			]),
		};
	}

	function updateGeneration(stores) {
		const context = getContext(stores);
		if (context.selection !== lastSelection) {
			lastSelection = context.selection;
			generation++;
		}
		return context;
	}

	function getQuantity(item, includeQuantity) {
		if (!includeQuantity) return 1;
		const quantity = Number(item.quantity ?? item.qty ?? 1);
		return Number.isFinite(quantity) && quantity > 0 ? quantity : 1;
	}

	function makeEntry(item, context, includeQuantity) {
		const uom = item.uom || item.stock_uom || "";
		const qty = getQuantity(item, includeQuantity);
		return {
			item,
			uom,
			qty,
			key: JSON.stringify([
				context.profile || "",
				context.customer,
				context.effectivePriceList,
				context.transactionDate,
				item.item_code,
				uom,
				qty,
			]),
		};
	}

	function schedule(stores) {
		if (applyingPrices) return;
		// Advance the generation immediately. A customer/profile change while a
		// request is in flight must make that response stale before it can touch UI.
		updateGeneration(stores);
		resyncRequested = true;
		if (syncInFlight) return;
		clearTimeout(timer);
		timer = setTimeout(() => {
			timer = null;
			startSync(stores).catch(console.error);
		}, DEBOUNCE_MS);
	}

	async function startSync(stores) {
		if (syncInFlight) {
			resyncRequested = true;
			return syncInFlight;
		}

		resyncRequested = false;
		syncInFlight = syncPrices(stores);
		try {
			await syncInFlight;
		} finally {
			syncInFlight = null;
			// Mutations during the request are coalesced into one debounced follow-up.
			// Cached/pending keys ensure the follow-up only requests genuinely new work.
			if (resyncRequested) schedule(stores);
		}
	}

	async function performFetch(context, entries) {
		const params = new URLSearchParams({
			customer: context.customer || "",
			pos_profile: context.profile,
			transaction_date: context.transactionDate,
			items: JSON.stringify(
				entries.map((entry, index) => ({
					item_code: entry.item.item_code,
					uom: entry.uom,
					qty: entry.qty,
					// Keep the query string compact; this only correlates rows inside
					// the current batch. The full pricing key remains client-side.
					request_key: String(index),
				})),
			),
		});
		const response = await fetch(`${METHOD}?${params}`, {
			credentials: "same-origin",
		});
		const body = await response.json();
		if (!response.ok || body.exc)
			throw new Error(body.message || "Unable to load POS prices");
		return body.message;
	}

	function fetchPrices(context, entries) {
		const signature = JSON.stringify([
			context.profile,
			context.customer,
			context.effectivePriceList,
			context.transactionDate,
			entries.map((entry) => entry.key),
		]);
		if (activeBatchRequests.has(signature))
			return activeBatchRequests.get(signature);

		// Serialize even different batches. This is a final guard around every call
		// from this script, including the compatibility addItem wrapper below.
		const request = networkTail
			.catch(() => undefined)
			.then(() => performFetch(context, entries));
		networkTail = request.then(
			() => undefined,
			() => undefined,
		);
		activeBatchRequests.set(signature, request);
		const cleanup = () => {
			if (activeBatchRequests.get(signature) === request)
				activeBatchRequests.delete(signature);
		};
		request.then(cleanup, cleanup);
		return request;
	}

	function getResponsePrice(data, entry, requestIndex) {
		return (
			data?.prices_by_request?.[String(requestIndex)] ||
			data?.prices?.[entry.item.item_code]
		);
	}

	async function fetchAndCache(context, entries) {
		const request = fetchPrices(context, entries);
		// Mark keys before yielding so another sync cannot enqueue the same work.
		for (const [index, entry] of entries.entries()) {
			pendingPrices.set(entry.key, { request, index });
		}
		try {
			const data = await request;
			for (const [index, entry] of entries.entries()) {
				const price = getResponsePrice(data, entry, index);
				if (price) cachedPrices.set(entry.key, price);
			}
			return data;
		} finally {
			for (const entry of entries) {
				if (pendingPrices.get(entry.key)?.request === request)
					pendingPrices.delete(entry.key);
			}
		}
	}

	async function getOrFetchPrice(context, entry) {
		if (cachedPrices.has(entry.key)) return cachedPrices.get(entry.key);
		const pending = pendingPrices.get(entry.key);
		if (pending) {
			const data = await pending.request;
			return (
				cachedPrices.get(entry.key) ||
				getResponsePrice(data, entry, pending.index)
			);
		}
		const data = await fetchAndCache(context, [entry]);
		return cachedPrices.get(entry.key) || getResponsePrice(data, entry, 0);
	}

	async function syncPrices(stores) {
		const { cart, items } = stores;
		const context = updateGeneration(stores);
		if (!context.profile || !navigator.onLine) return;
		const currentGeneration = generation;
		// Current POS Next prices cart lines itself with quantity/pricing-rule context.
		// The injected script only needs to price catalog/search rows there. Older
		// builds still use the compatibility cart path below.
		const hasNativeCustomerPricing = "effectivePriceList" in cart;
		const visibleEntries = [
			...(items.allItems || []).map((item) => makeEntry(item, context, false)),
			...(items.searchResults || []).map((item) =>
				makeEntry(item, context, false),
			),
			...(hasNativeCustomerPricing
				? []
				: (cart.invoiceItems || []).map((item) =>
						makeEntry(item, context, true),
					)),
		];
		const missing = new Map();
		for (const entry of visibleEntries) {
			if (!entry.item?.item_code || entry.item.__hala_price_key === entry.key)
				continue;
			if (!cachedPrices.has(entry.key) && !pendingPrices.has(entry.key)) {
				missing.set(entry.key, entry);
			}
		}
		if (!visibleEntries.length) return;

		const requested = [...missing.values()];
		for (let offset = 0; offset < requested.length; offset += BATCH_SIZE) {
			const batch = requested.slice(offset, offset + BATCH_SIZE);
			await fetchAndCache(context, batch);
			if (generation !== currentGeneration) return;
		}
		if (generation !== currentGeneration) return;

		function priceRows(rows) {
			let changed = false;
			const result = rows.map((item) => {
				const entry = makeEntry(item, context, false);
				const price = cachedPrices.get(entry.key);
				if (!price || item.__hala_price_key === entry.key) return item;
				changed = true;
				return {
					...item,
					rate: price.rate,
					price_list_rate: price.rate,
					price_list_rate_price_uom: price.rate,
					__hala_price_key: entry.key,
				};
			});
			return changed ? result : null;
		}

		applyingPrices = true;
		try {
			const allItems = priceRows(items.allItems || []);
			const searchResults = priceRows(items.searchResults || []);
			if (allItems || searchResults) {
				items.invalidateCache();
				if (allItems) items.allItems = allItems;
				if (searchResults) items.searchResults = searchResults;
			}

			if (!hasNativeCustomerPricing) {
				let cartChanged = false;
				for (const item of cart.invoiceItems || []) {
					if (item.is_free_item) continue;
					const entry = makeEntry(item, context, true);
					const price = cachedPrices.get(entry.key);
					if (!price || item.__hala_price_key === entry.key) continue;
					item.rate = price.rate;
					item.price_list_rate = price.rate;
					item.discount_percentage = 0;
					item.discount_amount = 0;
					item.is_rate_manually_edited = 0;
					item.original_rate = null;
					item.__hala_price_key = entry.key;
					cart.recalculateItem(item);
					cartChanged = true;
				}
				if (cartChanged) cart.rebuildIncrementalCache();
			}
		} finally {
			applyingPrices = false;
		}
	}

	function wrapAddItem(stores) {
		// Newer POS Next builds already ask Hala for item details inside addItem.
		if (addItemWrapped || "effectivePriceList" in stores.cart) return;
		addItemWrapped = true;
		const originalAddItem = stores.cart.addItem.bind(stores.cart);
		stores.cart.addItem = async (item, qty, ...rest) => {
			if (!navigator.onLine || !item?.item_code)
				return originalAddItem(item, qty, ...rest);
			const context = updateGeneration(stores);
			const entry = makeEntry({ ...item, qty }, context, true);
			const price = await getOrFetchPrice(context, entry);
			const pricedItem = price
				? { ...item, rate: price.rate, price_list_rate: price.rate }
				: item;
			return originalAddItem(pricedItem, qty, ...rest);
		};
	}

	function connect() {
		const stores = findStores();
		if (!stores) {
			setTimeout(connect, 200);
			return;
		}
		wrapAddItem(stores);
		stores.cart.$subscribe(() => schedule(stores));
		stores.items.$subscribe(() => schedule(stores));
		schedule(stores);
	}

	connect();
})();
