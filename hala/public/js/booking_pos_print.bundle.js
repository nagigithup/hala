import qz from "../../../../pos_next/POS/node_modules/qz-tray/qz-tray.js";
import html2canvas from "../../../../pos_next/POS/node_modules/html2canvas/dist/html2canvas.esm.js";

(() => {
	"use strict";
	if (window.halaBookingPOSPrint) return;
	let qzReady;
	const call = async (method, args) => (await frappe.call({method, args})).message;

	async function getQZ() {
		if (!qzReady) {
			qzReady = Promise.resolve().then(() => {
				qz.security.setCertificatePromise((resolve, reject) => {
					call("pos_next.api.qz.get_certificate").then(resolve, reject);
				});
				qz.security.setSignatureAlgorithm("SHA512");
				qz.security.setSignaturePromise((message) => (resolve, reject) => {
					call("pos_next.api.qz.sign_message", {message}).then(resolve, reject);
				});
				return qz;
			}).catch((error) => {
				qzReady = null;
				throw error;
			});
		}
		return qzReady;
	}

	window.halaBookingPOSPrint = (name, printFormat = "POS Next Receipt", options = {}) => window.halaSmartPrint(
		options.doctype || "Sales Invoice", name, printFormat, {
			paperWidth: "80mm",
			beforePrint: async (printDocument) => {
				let qz, config, data;
				try {
					const doc = options.invoice || await call("frappe.client.get", {doctype: options.doctype || "Sales Invoice", name});
					if (doc.name !== name || Number(doc.docstatus) !== (options.invoice ? Number(options.invoice.docstatus) : (printFormat === "BOOKING" ? 0 : 1))) throw new Error("Invoice status does not match the selected booking print format.");
					const settings = await call("pos_next.pos_next.doctype.pos_settings.pos_settings.get_pos_settings", {
						pos_profile: options.pos_profile || doc.pos_profile || doc.custom_cashier_profile,
					});
					if (!Number(settings?.silent_print)) return false;
					qz = await getQZ();
					if (!qz.websocket.isActive()) await qz.websocket.connect();
					const printers = await qz.printers.find();
					const saved = localStorage.getItem("pos_qz_printer_name");
					const printer = saved && printers.includes(saved) ? saved : await qz.printers.getDefault();
					if (!printer) return false;
					// Like POS Next's rendered-image path, let the browser shape Arabic
					// and render the existing receipt's logo, QR and CSS before dispatch.
					const receipt = printDocument.querySelector(".print-format");
					const pixels = Math.max(receipt.scrollHeight, receipt.offsetHeight);
					const height = Math.max(40, Math.ceil(pixels * 25.4 / 96 + 3));
					const canvas = await html2canvas(receipt, {
						backgroundColor: "#ffffff", logging: false, scale: pixels > 8000 ? 1 : 2,
						useCORS: true, windowWidth: 80 * 96 / 25.4,
					});
					config = qz.configs.create(printer, {
						size: {width: 80, height, custom: true},
						units: "mm", orientation: "portrait", margins: 0,
						colorType: "grayscale", interpolation: "bicubic", rasterize: false,
						scaleContent: true, jobName: `POS Next Receipt ${name}`,
					});
					data = [{type: "pixel", format: "image", flavor: "base64", data: canvas.toDataURL("image/png").split(",", 2)[1]}];
				} catch (error) {
					console.warn("QZ receipt preparation unavailable; using browser printing:", error);
					return false;
				}
				// A dispatch error may mean the printer already received the job.
				// Let the caller report it; never send a second browser job here.
				await qz.print(config, data);
				return true;
			},
		}
	);

	// Purchase invoices keep their configured PDF paper and native print format.
	window.halaNativePurchasePrint = (name, printFormat, options = {}) => window.halaSmartPrint(
		"Purchase Invoice", name, printFormat, {
			language: "ar", letterhead: options.letterhead,
			beforePrint: async () => {
				let bridge, config, data;
				try {
					const settings = await call("pos_next.pos_next.doctype.pos_settings.pos_settings.get_pos_settings", {pos_profile: options.pos_profile});
					if (!Number(settings?.silent_print)) return false;
					bridge = await getQZ();
					if (!bridge.websocket.isActive()) await bridge.websocket.connect();
					const saved = localStorage.getItem("hala_purchase_printer");
					const printers = await bridge.printers.find();
					const printer = saved && printers.includes(saved) ? saved : await bridge.printers.getDefault();
					if (!printer) return false;
					const params = new URLSearchParams({doctype: "Purchase Invoice", name, format: printFormat, _lang: "ar", no_letterhead: options.letterhead ? "0" : "1"});
					if (options.letterhead) params.set("letterhead", options.letterhead);
					const response = await fetch(`/api/method/frappe.utils.print_format.download_pdf?${params}`);
					if (!response.ok || !response.headers.get("content-type")?.includes("application/pdf")) throw new Error("Native purchase PDF unavailable");
					const bytes = new Uint8Array(await response.arrayBuffer());
					let binary = "";
					for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
					config = bridge.configs.create(printer, {jobName: `Purchase Invoice ${name}`});
					data = [{type: "pixel", format: "pdf", flavor: "base64", data: btoa(binary)}];
				} catch (error) {
					console.warn("Purchase PDF preparation unavailable; using native browser printing:", error);
					return false;
				}
				await bridge.print(config, data); // Never issue a second job after ambiguous dispatch.
				return true;
			},
		}
	);
})();
