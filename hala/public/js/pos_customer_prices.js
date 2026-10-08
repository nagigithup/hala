(() => {
	const METHOD = "/api/method/hala.api.pos_pricing.get_catalog_prices";
	const CONTEXT_METHOD = "/api/method/hala.api.pos_pricing.get_pricing_context";
	const BATCH_SIZE = 25;
	const DEBOUNCE_MS = 80;
	// Five minutes keeps catalog navigation fast while bounding how long an
	// unchanged pricing context can be reused. 500 entries covers several full
	// catalog pages without allowing a long cashier session to grow forever.
	const CACHE_TTL_MS = 5 * 60 * 1000;
	const MAX_CACHE_ENTRIES = 500;
	const REQUEST_TIMEOUT_MS = 15 * 1000;
	const scriptElement =
		document.currentScript ||
		document.querySelector('script[src*="/hala/js/pos_customer_prices.js"]');
	let timer;
	let pricingDateTimer;
	let syncInFlight = null;
	let resyncRequested = false;
	let applyingPrices = false;
	let generation = 0;
	let lastSelection = "";
	let authoritativePricingDate = scriptElement?.dataset.pricingDate || "";
	const cachedPrices = new Map();
	const pendingPrices = new Map();
	const activeBatchRequests = new Map();
	let networkTail = Promise.resolve();
	let addItemWrapped = false;
	let manualRefreshActive = false;
	let manualRefreshPromise = null;

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

	function prunePriceCache(now = Date.now()) {
		for (const [key, entry] of cachedPrices) {
			if (entry.expiresAt <= now) cachedPrices.delete(key);
		}
		while (cachedPrices.size > MAX_CACHE_ENTRIES) {
			cachedPrices.delete(cachedPrices.keys().next().value);
		}
	}

	function getCachedEntry(key) {
		const cached = cachedPrices.get(key);
		if (!cached) return null;
		if (cached.expiresAt <= Date.now()) {
			cachedPrices.delete(key);
			return null;
		}
		// Map insertion order is the LRU order.
		cachedPrices.delete(key);
		cachedPrices.set(key, cached);
		return cached;
	}

	function cachePrice(key, price, selection) {
		cachedPrices.delete(key);
		const cached = {
			price,
			selection,
			expiresAt: Date.now() + CACHE_TTL_MS,
			token: `${Date.now()}:${generation}`,
		};
		cachedPrices.set(key, cached);
		prunePriceCache();
		return cached;
	}

	function invalidateSelection(selection) {
		if (!selection) return;
		for (const [key, entry] of cachedPrices) {
			if (entry.selection === selection) cachedPrices.delete(key);
		}
	}

	function getContext({ cart, items }) {
		const profile =
			cart.posProfile?.name || cart.posProfile || items.posProfile;
		const customer = cart.customer?.name || cart.customer || "";
		const priceListValue =
			cart.effectivePriceList?.value ?? cart.effectivePriceList;
		const effectivePriceList = priceListValue?.name || priceListValue || "";
		const transactionDate = authoritativePricingDate;
		const context = {
			profile,
			customer,
			effectivePriceList,
			transactionDate,
		};
		context.selection = getContextSelection(context);
		return context;
	}

	function getContextSelection(context) {
		return JSON.stringify([
			context.profile || "",
			context.customer,
			context.effectivePriceList,
			context.transactionDate,
		]);
	}

	function updateGeneration(stores) {
		const context = getContext(stores);
		if (context.selection !== lastSelection) {
			const previousSelection = lastSelection;
			lastSelection = context.selection;
			generation++;
			// Invalidate only the context being left. Returning A -> B -> A must
			// revalidate A, while ordinary mutations within A retain the cache.
			invalidateSelection(previousSelection);
		}
		prunePriceCache();
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
		if (manualRefreshActive) {
			resyncRequested = true;
			return;
		}
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

	async function fetchJson(url) {
		// AbortController is best-effort: a proxy/server may still finish work after
		// the browser aborts. The timeout still releases the logical queue, and the
		// generation checks ensure such late work can never update the POS state.
		const controller = globalThis.AbortController
			? new globalThis.AbortController()
			: null;
		let timeoutId;
		const timeout = new Promise((_, reject) => {
			timeoutId = setTimeout(() => {
				controller?.abort();
				const error = new Error("POS pricing request timed out");
				error.name = "TimeoutError";
				reject(error);
			}, REQUEST_TIMEOUT_MS);
		});
		const operation = (async () => {
			const response = await fetch(url, {
				credentials: "same-origin",
				...(controller ? { signal: controller.signal } : {}),
			});
			const body = await response.json();
			if (!response.ok || body.exc)
				throw new Error(body.message || "Unable to load POS prices");
			return body.message;
		})();
		try {
			return await Promise.race([operation, timeout]);
		} finally {
			clearTimeout(timeoutId);
		}
	}

	async function performFetch(context, entries) {
		const params = new URLSearchParams({
			customer: context.customer || "",
			pos_profile: context.profile,
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
		// The server deliberately owns the transaction date. The browser-provided
		// page date is only a cache partition and is verified by the response.
		return fetchJson(`${METHOD}?${params}`);
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

	function fetchPricingContext(context) {
		const params = new URLSearchParams({
			customer: context.customer || "",
			pos_profile: context.profile,
		});
		const signature = `context:${context.profile}:${context.customer}`;
		if (activeBatchRequests.has(signature))
			return activeBatchRequests.get(signature);
		const request = networkTail
			.catch(() => undefined)
			.then(() => fetchJson(`${CONTEXT_METHOD}?${params}`));
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

	function schedulePricingDateRefresh(stores, delay) {
		clearTimeout(pricingDateTimer);
		const milliseconds = Math.max(1000, Number(delay) || 60 * 1000);
		pricingDateTimer = setTimeout(async () => {
			try {
				const currentContext = getContext(stores);
				if (!currentContext.profile || !navigator.onLine) {
					schedulePricingDateRefresh(stores, 60 * 1000);
					return;
				}
				const data = await fetchPricingContext(currentContext);
				const previousDate = authoritativePricingDate;
				authoritativePricingDate = data?.pricing_date || previousDate;
				schedulePricingDateRefresh(stores, data?.date_refresh_ms);
				if (authoritativePricingDate !== previousDate) schedule(stores);
			} catch (error) {
				console.error(error);
				schedulePricingDateRefresh(stores, 60 * 1000);
			}
		}, milliseconds);
	}

	function getResponsePrice(data, entry, requestIndex) {
		return (
			data?.prices_by_request?.[String(requestIndex)] ||
			data?.prices?.[entry.item.item_code]
		);
	}

	async function fetchAndCache(context, entries, expectedGeneration) {
		const request = fetchPrices(context, entries);
		// Mark keys before yielding so another sync cannot enqueue the same work.
		for (const [index, entry] of entries.entries()) {
			pendingPrices.set(entry.key, { request, index });
		}
		try {
			const data = await request;
			if (
				expectedGeneration !== generation ||
				context.selection !== lastSelection ||
				(data?.pricing_date && data.pricing_date !== context.transactionDate)
			)
				return data;
			for (const [index, entry] of entries.entries()) {
				const price = getResponsePrice(data, entry, index);
				if (price) cachePrice(entry.key, price, context.selection);
			}
			return data;
		} finally {
			for (const entry of entries) {
				if (pendingPrices.get(entry.key)?.request === request)
					pendingPrices.delete(entry.key);
			}
		}
	}

	async function getOrFetchPrice(context, entry, expectedGeneration) {
		const cached = getCachedEntry(entry.key);
		if (cached) return cached.price;
		const pending = pendingPrices.get(entry.key);
		if (pending) {
			const data = await pending.request;
			if (expectedGeneration !== generation || context.selection !== lastSelection)
				return null;
			return (
				getCachedEntry(entry.key)?.price ||
				getResponsePrice(data, entry, pending.index)
			);
		}
		const data = await fetchAndCache(context, [entry], expectedGeneration);
		if (expectedGeneration !== generation || context.selection !== lastSelection)
			return null;
		return getCachedEntry(entry.key)?.price || getResponsePrice(data, entry, 0);
	}

	function getVisibleEntries(stores, context, includeCompatibilityCart = true) {
		const { cart, items } = stores;
		const hasNativeCustomerPricing = "effectivePriceList" in cart;
		return {
			hasNativeCustomerPricing,
			entries: [
				...(items.allItems || []).map((item) => makeEntry(item, context, false)),
				...(items.searchResults || []).map((item) =>
					makeEntry(item, context, false),
				),
				...(includeCompatibilityCart && !hasNativeCustomerPricing
					? (cart.invoiceItems || []).map((item) =>
							makeEntry(item, context, true),
						)
					: []),
			],
		};
	}

	function uniqueValidEntries(entries) {
		const unique = new Map();
		for (const entry of entries) {
			if (entry.item?.item_code) unique.set(entry.key, entry);
		}
		return [...unique.values()];
	}

	function getVisibleShape(entries) {
		return JSON.stringify(
			uniqueValidEntries(entries).map((entry) => [
				entry.item.item_code,
				entry.uom,
				entry.qty,
			]),
		);
	}

	function applyPrices(stores, context, preparedPrices = null) {
		const { cart, items } = stores;
		const hasNativeCustomerPricing = "effectivePriceList" in cart;
		const findPrice = (entry) =>
			preparedPrices?.get(entry.key) || getCachedEntry(entry.key);

		function priceRows(rows) {
			let changed = false;
			const result = rows.map((item) => {
				const entry = makeEntry(item, context, false);
				const cached = findPrice(entry);
				if (!cached || item.__hala_price_cache_token === cached.token)
					return item;
				const price = cached.price;
				changed = true;
				return {
					...item,
					rate: price.rate,
					price_list_rate: price.rate,
					price_list_rate_price_uom: price.rate,
					__hala_price_key: entry.key,
					__hala_price_cache_token: cached.token,
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
					const cached = findPrice(entry);
					if (!cached || item.__hala_price_cache_token === cached.token)
						continue;
					const price = cached.price;
					item.rate = price.rate;
					item.price_list_rate = price.rate;
					item.discount_percentage = 0;
					item.discount_amount = 0;
					item.is_rate_manually_edited = 0;
					item.original_rate = null;
					item.__hala_price_key = entry.key;
					item.__hala_price_cache_token = cached.token;
					cart.recalculateItem(item);
					cartChanged = true;
				}
				if (cartChanged) cart.rebuildIncrementalCache();
			}
		} finally {
			applyingPrices = false;
		}
	}

	async function syncPrices(stores) {
		const { items } = stores;
		const context = updateGeneration(stores);
		if (!context.profile || !navigator.onLine) return;
		const currentGeneration = generation;
		// Current POS Next prices cart lines itself with quantity/pricing-rule context.
		// The injected script only needs to price catalog/search rows there. Older
		// builds still use the compatibility cart path below.
		const { entries: visibleEntries } = getVisibleEntries(stores, context);
		const missing = new Map();
		for (const entry of visibleEntries) {
			if (!entry.item?.item_code) continue;
			if (!getCachedEntry(entry.key) && !pendingPrices.has(entry.key)) {
				missing.set(entry.key, entry);
			}
		}
		if (!visibleEntries.length) return;

		const requested = [...missing.values()];
		for (let offset = 0; offset < requested.length; offset += BATCH_SIZE) {
			const batch = requested.slice(offset, offset + BATCH_SIZE);
			const data = await fetchAndCache(context, batch, currentGeneration);
			if (data?.date_refresh_ms)
				schedulePricingDateRefresh(stores, data.date_refresh_ms);
			if (data?.pricing_date && data.pricing_date !== context.transactionDate) {
				authoritativePricingDate = data.pricing_date;
				updateGeneration(stores);
				resyncRequested = true;
				return;
			}
			if (generation !== currentGeneration) return;
		}
		if (generation !== currentGeneration) return;

		applyPrices(stores, context);
	}

	function finishManualRefresh(stores, shouldResync = false) {
		manualRefreshActive = false;
		manualRefreshPromise = null;
		const syncAfterFinish = shouldResync || resyncRequested;
		resyncRequested = false;
		if (syncAfterFinish) schedule(stores);
	}

	async function buildManualRefreshTransaction(stores, attempt = 0) {
		if (syncInFlight) {
			try {
				await syncInFlight;
			} catch {
				// The manual refresh is the explicit recovery path.
			}
		}
		const context = updateGeneration(stores);
		if (!context.profile || !navigator.onLine)
			throw new Error("POS pricing refresh is unavailable");
		const expectedGeneration = generation;
		const originalAllItems = stores.items.allItems;
		const originalSearchResults = stores.items.searchResults;
		const { entries } = getVisibleEntries(stores, context, false);
		const prepared = [];
		const requested = uniqueValidEntries(entries);
		const visibleSignature = getVisibleShape(entries);
		let resolvedPriceList = context.effectivePriceList;
		if (!requested.length) {
			const data = await fetchPricingContext(context);
			if (data?.date_refresh_ms)
				schedulePricingDateRefresh(stores, data.date_refresh_ms);
			resolvedPriceList = data?.price_list || resolvedPriceList;
			if (data?.pricing_date && data.pricing_date !== context.transactionDate) {
				if (attempt > 0) throw new Error("Pricing date changed during refresh");
				authoritativePricingDate = data.pricing_date;
				updateGeneration(stores);
				return buildManualRefreshTransaction(stores, attempt + 1);
			}
			if (
				expectedGeneration !== generation ||
				context.selection !== lastSelection
			)
				throw new Error("POS pricing context changed during refresh");
		}
		for (let offset = 0; offset < requested.length; offset += BATCH_SIZE) {
			const batch = requested.slice(offset, offset + BATCH_SIZE);
			const data = await fetchPrices(context, batch);
			if (data?.date_refresh_ms)
				schedulePricingDateRefresh(stores, data.date_refresh_ms);
			resolvedPriceList = data?.price_list || resolvedPriceList;
			if (data?.pricing_date && data.pricing_date !== context.transactionDate) {
				if (attempt > 0) throw new Error("Pricing date changed during refresh");
				authoritativePricingDate = data.pricing_date;
				updateGeneration(stores);
				return buildManualRefreshTransaction(stores, attempt + 1);
			}
			if (
				expectedGeneration !== generation ||
				context.selection !== lastSelection
			)
				throw new Error("POS pricing context changed during refresh");
			for (const [index, entry] of batch.entries()) {
				const price = getResponsePrice(data, entry, index);
				if (price) prepared.push({ entry, price });
			}
		}

		let finished = false;
		let committed = false;
		const hasCurrentBaseContext = () => {
			const current = getContext(stores);
			return (
				current.profile === context.profile &&
				current.customer === context.customer &&
				current.transactionDate === context.transactionDate &&
				visibleSignature ===
					getVisibleShape(getVisibleEntries(stores, current, false).entries)
			);
		};
		const isCurrent = () =>
			!finished &&
			expectedGeneration === generation &&
			hasCurrentBaseContext();
		return {
			priceList: resolvedPriceList,
			isCurrent,
			commit() {
				if (!isCurrent()) return false;
				const current = getContext(stores);
				const commitContext = {
					...context,
					effectivePriceList:
						resolvedPriceList || current.effectivePriceList,
				};
				commitContext.selection = getContextSelection(commitContext);
				lastSelection = commitContext.selection;
				const preparedCache = new Map();
				for (const { entry, price } of prepared) {
					const commitEntry = makeEntry(entry.item, commitContext, false);
					preparedCache.set(
						commitEntry.key,
						cachePrice(commitEntry.key, price, commitContext.selection),
					);
				}
				// Mark the transaction before touching the item store so the outer
				// coordinator can restore both catalog arrays if a store setter or
				// cache invalidation unexpectedly throws part-way through the commit.
				committed = true;
				applyPrices(stores, commitContext, preparedCache);
				finished = true;
				finishManualRefresh(stores, false);
				return true;
			},
			discard() {
				if (finished) return;
				finished = true;
				finishManualRefresh(stores, false);
			},
			rollback() {
				if (!committed) return;
				cachedPrices.clear();
				applyingPrices = true;
				try {
					stores.items.invalidateCache();
					stores.items.allItems = originalAllItems;
					stores.items.searchResults = originalSearchResults;
					lastSelection = getContext(stores).selection;
				} finally {
					applyingPrices = false;
					committed = false;
				}
			},
		};
	}

	function prepareManualRefresh(stores) {
		if (manualRefreshPromise) return manualRefreshPromise;
		manualRefreshActive = true;
		clearTimeout(timer);
		timer = null;
		cachedPrices.clear();
		generation++;
		resyncRequested = false;
		manualRefreshPromise = buildManualRefreshTransaction(stores).catch(
			(error) => {
				finishManualRefresh(stores, false);
				throw error;
			},
		);
		return manualRefreshPromise;
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
			const expectedGeneration = generation;
			const entry = makeEntry({ ...item, qty }, context, true);
			const price = await getOrFetchPrice(
				context,
				entry,
				expectedGeneration,
			);
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
		globalThis.halaPOSPricing = {
			prepareRefresh: () => prepareManualRefresh(stores),
		};
		schedulePricingDateRefresh(
			stores,
			scriptElement?.dataset.dateRefreshMs,
		);
		schedule(stores);
	}

	connect();
})();
