(() => {
	"use strict";

	if (window.halaSmartPrint) return;

	const activeJobs = new Map();
	const cooldowns = new Map();
	const ERROR_MESSAGE = "تعذر تجهيز المستند للطباعة.";
	const LOAD_TIMEOUT_MS = 30000;
	const ASSET_TIMEOUT_MS = 10000;
	const CLEANUP_TIMEOUT_MS = 120000;
	const DOUBLE_PRINT_COOLDOWN_MS = 3000;

	function timeout(ms) {
		return new Promise((resolve) => window.setTimeout(resolve, ms));
	}

	function withTimeout(promise, ms, message) {
		return Promise.race([
			promise,
			new Promise((_, reject) => {
				window.setTimeout(() => reject(new Error(message)), ms);
			}),
		]);
	}

	function showPrintError() {
		if (window.frappe?.msgprint) {
			window.frappe.msgprint({
				title: window.__ ? window.__("Print Error") : "Print Error",
				message: ERROR_MESSAGE,
				indicator: "red",
			});
			return;
		}
		window.alert(ERROR_MESSAGE);
	}

	function waitForImages(doc) {
		const images = Array.from(doc.images || []);
		return Promise.all(
			images.map((image) => {
				if (image.complete) return Promise.resolve();
				return new Promise((resolve) => {
					image.addEventListener("load", resolve, {once: true});
					image.addEventListener("error", resolve, {once: true});
				});
			})
		);
	}

	async function waitForAssets(doc) {
		await withTimeout(waitForImages(doc), ASSET_TIMEOUT_MS, "Print images timed out");
		if (doc.fonts?.ready) {
			await Promise.race([doc.fonts.ready.catch(() => undefined), timeout(ASSET_TIMEOUT_MS)]);
		}
		await new Promise((resolve) => {
			window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
		});
	}

	function createPrintFrame() {
		const iframe = document.createElement("iframe");
		iframe.title = "Print document";
		iframe.setAttribute("aria-hidden", "true");
		iframe.style.cssText = [
			"position:fixed",
			"right:0",
			"bottom:0",
			"width:1px",
			"height:1px",
			"border:0",
			"opacity:0",
			"pointer-events:none",
		].join(";");
		document.body.appendChild(iframe);
		return iframe;
	}

	function loadFrame(iframe, url) {
		return withTimeout(
			new Promise((resolve, reject) => {
				iframe.addEventListener("load", resolve, {once: true});
				iframe.addEventListener("error", () => reject(new Error("Print view failed to load")), {
					once: true,
				});
				iframe.src = url;
			}),
			LOAD_TIMEOUT_MS,
			"Print view timed out"
		);
	}

	async function printDocument(doctype, docname, printFormat, options = {}) {
		if (![doctype, docname, printFormat].every((value) => typeof value === "string" && value.trim())) {
			showPrintError();
			throw new Error("A saved document and Print Format are required");
		}

		const key = `${doctype}::${docname}::${printFormat}`;
		if (activeJobs.has(key)) return activeJobs.get(key);
		if ((cooldowns.get(key) || 0) > Date.now()) return false;

		const job = (async () => {
			const iframe = createPrintFrame();
			let cleanupTimer;
			let cleaned = false;
			const cleanup = () => {
				if (cleaned) return;
				cleaned = true;
				window.clearTimeout(cleanupTimer);
				iframe.remove();
			};

			try {
				const params = new URLSearchParams({
					doctype,
					name: docname,
					format: printFormat,
					no_letterhead: options.letterhead ? "0" : "1",
				});
				if (options.letterhead) params.set("letterhead", options.letterhead);
				if (options.language) params.set("_lang", options.language);

				await loadFrame(iframe, `/printview?${params}`);
				const frameWindow = iframe.contentWindow;
				const frameDocument = iframe.contentDocument;
				if (
					!frameWindow ||
					!frameDocument?.body ||
					!frameDocument.querySelector(".print-format") ||
					frameWindow.location.origin !== window.location.origin ||
					frameWindow.location.pathname !== "/printview"
				) {
					throw new Error("Invalid print view response");
				}

				await waitForAssets(frameDocument);
				frameWindow.addEventListener(
					"afterprint",
					() => window.setTimeout(cleanup, 1000),
					{once: true}
				);
				cleanupTimer = window.setTimeout(cleanup, CLEANUP_TIMEOUT_MS);
				cooldowns.set(key, Date.now() + DOUBLE_PRINT_COOLDOWN_MS);
				frameWindow.focus();
				frameWindow.print();
				return true;
			} catch (error) {
				cleanup();
				showPrintError();
				throw error;
			}
		})();

		activeJobs.set(key, job);
		try {
			return await job;
		} finally {
			activeJobs.delete(key);
		}
	}

	window.halaSmartPrint = printDocument;
})();
