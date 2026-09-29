(function () {
	"use strict";

	const METHOD = "/api/method/hala.api.pos_pricing.get_catalog_prices";
	let timer;
	let generation = 0;
	let lastSelection = "";
	const cachedPrices = new Map();
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

	function schedule(stores) {
		clearTimeout(timer);
		timer = setTimeout(() => syncPrices(stores).catch(console.error), 80);
	}

	async function fetchPrices(customer, profile, items) {
		const params = new URLSearchParams({
			customer: customer || "",
			pos_profile: profile,
			items: JSON.stringify(items),
		});
		const response = await fetch(`${METHOD}?${params}`, { credentials: "same-origin" });
		const body = await response.json();
		if (!response.ok || body.exc) throw new Error(body.message || "Unable to load POS prices");
		return body.message;
	}

	async function syncPrices({ cart, items }) {
		const profile = cart.posProfile?.name || cart.posProfile || items.posProfile;
		if (!profile || !navigator.onLine) return;
		const customer = cart.customer?.name || cart.customer || "";
		const selection = JSON.stringify([profile, customer]);
		if (selection !== lastSelection) {
			lastSelection = selection;
			generation++;
		}
		const currentGeneration = generation;
		const visible = [
			...(items.allItems || []),
			...(items.searchResults || []),
			...(cart.invoiceItems || []),
		];
		const missing = new Map();
		for (const item of visible) {
			if (!item?.item_code) continue;
			const key = JSON.stringify([selection, item.item_code, item.uom || item.stock_uom || ""]);
			if (item.__hala_price_key !== key) {
				if (!cachedPrices.has(key)) missing.set(key, item);
			}
		}
		if (!visible.length) return;

		const requested = [...missing.values()];
		for (let offset = 0; offset < requested.length; offset += 25) {
			const batch = requested.slice(offset, offset + 25);
			const data = await fetchPrices(
				customer,
				profile,
				batch.map((item) => ({ item_code: item.item_code, uom: item.uom || item.stock_uom }))
			);
			if (generation !== currentGeneration) return;
			for (const item of batch) {
				const key = JSON.stringify([selection, item.item_code, item.uom || item.stock_uom || ""]);
				cachedPrices.set(key, data.prices[item.item_code]);
			}
		}
		if (generation !== currentGeneration) return;

		function priceRows(rows) {
			let changed = false;
			const result = rows.map((item) => {
				const key = JSON.stringify([selection, item.item_code, item.uom || item.stock_uom || ""]);
				const price = cachedPrices.get(key);
				if (!price || item.__hala_price_key === key) return item;
				changed = true;
				return {
					...item,
					rate: price.rate,
					price_list_rate: price.rate,
					price_list_rate_price_uom: price.rate,
					__hala_price_key: key,
				};
			});
			return changed ? result : null;
		}

		const allItems = priceRows(items.allItems || []);
		const searchResults = priceRows(items.searchResults || []);
		if (allItems || searchResults) {
			items.invalidateCache();
			if (allItems) items.allItems = allItems;
			if (searchResults) items.searchResults = searchResults;
		}

		let cartChanged = false;
		for (const item of cart.invoiceItems || []) {
			if (item.is_free_item) continue;
			const key = JSON.stringify([selection, item.item_code, item.uom || item.stock_uom || ""]);
			const price = cachedPrices.get(key);
			if (!price || item.__hala_price_key === key) continue;
			item.rate = price.rate;
			item.price_list_rate = price.rate;
			item.discount_percentage = 0;
			item.discount_amount = 0;
			item.is_rate_manually_edited = 0;
			item.original_rate = null;
			item.__hala_price_key = key;
			cart.recalculateItem(item);
			cartChanged = true;
		}
		if (cartChanged) cart.rebuildIncrementalCache();
	}

	function wrapAddItem(stores) {
		// Newer POS Next builds already ask Hala for item details inside addItem.
		if (addItemWrapped || "effectivePriceList" in stores.cart) return;
		addItemWrapped = true;
		const originalAddItem = stores.cart.addItem.bind(stores.cart);
		stores.cart.addItem = async function (item, qty, ...rest) {
			if (!navigator.onLine || !item?.item_code) return originalAddItem(item, qty, ...rest);
			const profile = stores.cart.posProfile?.name || stores.cart.posProfile || stores.items.posProfile;
			const customer = stores.cart.customer?.name || stores.cart.customer || "";
			const data = await fetchPrices(customer, profile, [
				{ item_code: item.item_code, uom: item.uom || item.stock_uom },
			]);
			const price = data.prices[item.item_code];
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
