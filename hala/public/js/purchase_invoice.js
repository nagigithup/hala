/* Supplier cash outflow belongs to Payment Entry, never invoice.paid_amount. */
(() => {
	const api = "hala.api.supplier_payment.";
	const escape = frappe.utils.escape_html;
	const call = async (method, args) => (await frappe.call({ method: api + method, args })).message;
	const storage_key = (invoice) => `hala:supplier-payment:${frappe.boot.sitename}:${frappe.session.user}:${invoice}`;
	const read_intent = (invoice) => JSON.parse(localStorage.getItem(storage_key(invoice)) || "null");
	const save_intent = (invoice, intent) => localStorage.setItem(storage_key(invoice), JSON.stringify(intent));

	function inline_preview(frm) {
		const enabled = !!frm.doc.custom_hala_supplier_payment;
		frm.set_df_property("is_paid", "read_only", enabled ? 1 : 0);
		const wrapper = frm.fields_dict?.custom_hala_supplier_payment_preview?.$wrapper;
		if (!wrapper) return;
		wrapper.empty();
		if (!enabled) return;
		const total = flt(frm.doc.rounded_total || frm.doc.grand_total);
		const due = Math.max(total - flt(frm.doc.total_advance) - flt(frm.doc.write_off_amount), 0);
		const amount = Math.max(flt(frm.doc.custom_hala_actual_supplier_payment), 0);
		for (const [label, value] of [
			["Invoice Grand Total", frm.doc.grand_total],
			["Amount Allocated to Invoice", Math.min(due, amount)],
			["Supplier Advance / Credit", Math.max(amount - due, 0)],
		]) {
			$("<p></p>").text(__(label) + ": " + format_currency(value, frm.doc.currency)).appendTo(wrapper);
		}
		$("<p class='text-muted small'></p>").text(__("Saving a draft does not post a payment. Submitting creates the supplier Payment Entry; any excess remains an advance.")).appendTo(wrapper);
	}

	async function enable_inline_payment(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.custom_hala_supplier_payment) {
			inline_preview(frm);
			return;
		}
		const values = { is_paid: 0, paid_amount: 0, base_paid_amount: 0 };
		if (!frm.doc.custom_hala_actual_supplier_payment && frm.doc.is_paid) {
			values.custom_hala_actual_supplier_payment = frm.doc.paid_amount;
		}
		if (!frm.doc.custom_hala_supplier_payment_account && frm.doc.cash_bank_account) {
			values.custom_hala_supplier_payment_account = frm.doc.cash_bank_account;
		}
		await frm.set_value(values);
		frm.refresh_fields();
		inline_preview(frm);
	}

	async function route_overpayment(frm) {
		const total = flt(frm.doc.rounded_total || frm.doc.grand_total);
		if (frm.doc.docstatus !== 0 || !frm.doc.is_paid || frm.doc.is_return || total <= 0 || flt(frm.doc.paid_amount) <= total) return;
		const amount = frm.doc.paid_amount;
		await frm.set_value({
			custom_hala_actual_supplier_payment: amount,
			custom_hala_supplier_payment_account: frm.doc.cash_bank_account,
			custom_hala_supplier_payment: 1,
		});
		await enable_inline_payment(frm);
	}

	function completed(frm, result) {
		frappe.msgprint({
			title: __("Supplier Payment"),
			message: `${frappe.utils.get_form_link("Payment Entry", result.name, true)}<br>` +
				`${escape(__("Amount Allocated to Invoice"))}: ${format_currency(result.allocated_amount, result.party_currency)}<br>` +
				`${escape(__("Supplier Advance / Credit"))}: ${format_currency(result.unallocated_amount, result.party_currency)}`,
			indicator: "green",
		});
		frm.reload_doc();
	}

	async function open_payment(frm, context, recovered = false) {
		let intent;
		try {
			intent = read_intent(frm.doc.name);
		} catch {
			frappe.throw(__("Browser storage is unavailable. Use Create > Payment to record this payment safely."));
		}
		if (intent?.completed && !recovered) {
			frappe.confirm(__("The previous supplier payment completed. Record another payment?"), () => {
				localStorage.removeItem(storage_key(frm.doc.name));
				open_payment(frm, context, true);
			});
			return;
		}
		let quote = null;
		let quote_version = 0;
		let busy = false;
		let pending = intent && !intent.completed;
		const values = pending ? intent.args : {};
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Supplier Payment"),
			fields: [
				{ fieldname: "invoice_currency", fieldtype: "Data", hidden: 1, default: context.invoice_currency },
				{ fieldname: "bank_currency", fieldtype: "Data", hidden: 1 },
				{ fieldname: "party_currency", fieldtype: "Data", hidden: 1, default: context.party_currency },
				{ fieldname: "invoice_total", fieldtype: "Currency", label: __("Invoice Grand Total"), read_only: 1, options: "invoice_currency", default: context.invoice_total },
				{ fieldname: "bank_account", fieldtype: "Link", options: "Account", label: __("Cash/Bank Account"), reqd: 1,
					default: values.bank_account || context.default_bank_account, read_only: pending,
					get_query: () => ({ filters: { company: context.company, account_type: ["in", ["Cash", "Bank"]], is_group: 0, disabled: 0 } }),
					onchange: () => update_quote() },
				{ fieldname: "actual_amount", fieldtype: "Currency", label: __("Actual Amount Paid to Supplier"), options: "bank_currency", reqd: 1,
					default: values.actual_amount || 0, read_only: pending, onchange: () => calculate() },
				{ fieldname: "outstanding", fieldtype: "Currency", label: __("Outstanding Amount"), options: "party_currency", read_only: 1, default: context.outstanding },
				{ fieldname: "allocated", fieldtype: "Currency", label: __("Amount Allocated to Invoice"), options: "party_currency", read_only: 1 },
				{ fieldname: "advance", fieldtype: "Currency", label: __("Supplier Advance / Credit"), options: "party_currency", read_only: 1 },
				{ fieldname: "reference_no", fieldtype: "Data", label: __("Reference No"), default: values.reference_no, read_only: pending },
				{ fieldname: "reference_date", fieldtype: "Date", label: __("Reference Date"), default: values.reference_date || frappe.datetime.get_today(), read_only: pending },
				{ fieldname: "notice", fieldtype: "HTML" },
			],
			primary_action_label: pending ? __("Retry Previous Payment") : __("Submit Payment"),
			async primary_action() {
				if (busy || (!quote && !pending)) return;
				const entered = dialog.get_values();
				if (!entered) return;
				busy = true;
				dialog.get_primary_btn().prop("disabled", true);
				let dispatched = false;
				try {
					if (!pending && !intent) {
						intent = { quote, args: {
							invoice: context.invoice, actual_amount: entered.actual_amount, bank_account: entered.bank_account,
							request_id: crypto.randomUUID(), expected_outstanding: quote.outstanding,
							source_exchange_rate: quote.source_exchange_rate, target_exchange_rate: quote.target_exchange_rate,
							reference_no: entered.reference_no || "", reference_date: entered.reference_date,
						} };
						// Persist before dispatch. An uncertain response always retries this
						// same request, including after a full page refresh.
						save_intent(context.invoice, intent);
					}
					dispatched = true;
					const result = await call("pay_supplier", intent.args);
					if (!result?.name || result.docstatus !== 1) {
						throw new Error("Supplier payment response did not confirm submission");
					}
					intent.completed = true;
					intent.result = result;
					try { save_intent(context.invoice, intent); } catch { /* The retained pending ID still deduplicates. */ }
					dialog.hide();
					completed(frm, result);
				} catch (error) {
					if (!dispatched) {
						intent = null;
						frappe.msgprint(__("Browser storage is unavailable. Use Create > Payment to record this payment safely."));
						return;
					}
					if (error?.responseJSON?.exc_type && !pending && !intent?.uncertain) {
						// A server error response rolls the transaction back. The user
						// can correct validation errors; network errors retain the ID.
						localStorage.removeItem(storage_key(context.invoice));
						intent = null;
						pending = false;
						for (const field of ["bank_account", "actual_amount", "reference_no", "reference_date"]) {
							dialog.set_df_property(field, "read_only", 0);
						}
						await update_quote();
						return;
					}
					// Frappe displays server validation errors. Keep the same immutable
					// intent for safe retries; never turn a failed request into a new one.
					if (intent) {
						intent.uncertain = true;
						try { save_intent(context.invoice, intent); } catch { /* Retain the original pending intent. */ }
					}
					dialog.fields_dict.notice.$wrapper.text(__("Payment was not confirmed. Retry this payment or review Payment Entries before starting another payment."));
					for (const field of ["bank_account", "actual_amount", "reference_no", "reference_date"]) {
						dialog.set_df_property(field, "read_only", 1);
					}
				} finally {
					busy = false;
					dialog.get_primary_btn().prop("disabled", false);
				}
			},
		});

		function calculate() {
			if (!dialog || !quote) return;
			const amount = flt(dialog.get_value("actual_amount"));
			const received = flt(amount * quote.source_exchange_rate / quote.target_exchange_rate, quote.received_precision);
			dialog.set_value("allocated", Math.min(Math.max(received, 0), quote.outstanding));
			dialog.set_value("advance", Math.max(flt(received - quote.outstanding, quote.allocation_precision), 0));
		}

		async function update_quote() {
			if (!dialog) return;
			const version = ++quote_version;
			quote = null;
			if (pending) {
				quote = intent.quote;
				await dialog.set_value("bank_currency", quote.bank_currency);
				await dialog.set_value("party_currency", quote.party_currency);
				await dialog.set_value("outstanding", quote.outstanding);
				dialog.fields_dict.notice.$wrapper.text(__("A previous payment request is pending. Retry it to check its result without creating a duplicate."));
				calculate();
				return;
			}
			dialog.get_primary_btn().prop("disabled", true);
			const account = dialog.get_value("bank_account");
			if (!account) return;
			try {
				const next = await call("get_context", { invoice: context.invoice, bank_account: account });
				if (version !== quote_version) return;
				quote = next;
				await dialog.set_value("bank_currency", next.bank_currency);
				await dialog.set_value("party_currency", next.party_currency);
				await dialog.set_value("outstanding", next.outstanding);
				dialog.set_df_property("actual_amount", "precision", next.amount_precision);
				dialog.fields_dict.notice.$wrapper.text(__("Only the outstanding amount is allocated. Any excess remains an unallocated supplier advance."));
				calculate();
				dialog.get_primary_btn().prop("disabled", false);
			} catch {
				dialog.fields_dict.notice.$wrapper.text(__("Unable to prepare this payment. Check the account or use Create > Payment."));
			}
		}
		dialog.show();
		await update_quote();
	}

	frappe.ui.form.on("Purchase Invoice", {
		setup(frm) {
			frm.set_query("custom_hala_supplier_payment_account", () => ({ filters: {
				company: frm.doc.company, account_type: ["in", ["Cash", "Bank"]],
				account_currency: frm.doc.currency, is_group: 0, disabled: 0,
			} }));
		},
		paid_amount: route_overpayment,
		async validate(frm) {
			await route_overpayment(frm);
			await enable_inline_payment(frm);
		},
		custom_hala_supplier_payment: enable_inline_payment,
		custom_hala_actual_supplier_payment: inline_preview,
		grand_total: inline_preview,
		total_advance: inline_preview,
		write_off_amount: inline_preview,
		async refresh(frm) {
			inline_preview(frm);
			frm.set_df_property("paid_amount", "description", __("Invoice settlement only. For the full cash/bank outflow and supplier advances, submit the invoice and use Supplier Payment."));
			if (frm.is_new() || frm.doc.docstatus === 2 || frm.doc.is_return) return;
			const invoice = frm.doc.name;
			try {
				const context = await call("get_context", { invoice });
				if (frm.doc.name !== invoice) return;
				frm.dashboard.parent.find(".hala-supplier-payments").remove();
				const body = frm.dashboard.add_section("", __("Supplier Payments"), "custom hala-supplier-payments");
				body.append($('<p></p>').text(__("Available Supplier Advance") + ": " + format_currency(context.available_advance, context.party_currency)));
				body.append($('<p class="text-muted small"></p>').text(frm.doc.docstatus === 0
					? __("Submit the invoice, then use Supplier Payment to record the actual amount paid. Existing advances can be applied explicitly with Get Advances.")
					: __("Use Payment Reconciliation to apply existing supplier advances. No credit is consumed automatically by Supplier Payment.")));
				frm.add_custom_button(__("Supplier Unallocated Payments"), () => {
					frappe.set_route("List", "Payment Entry", { company: context.company, party_type: "Supplier", party: context.supplier,
						payment_type: "Pay", docstatus: 1, paid_to_account_currency: context.party_currency, unallocated_amount: [">", 0] });
				}, __("View"));
				if (context.can_pay) {
					frm.add_custom_button(__("Supplier Payment"), () => open_payment(frm, context), __("Create"));
				} else if (frm.doc.docstatus === 1) {
					// A fully paid invoice must still allow recovery of a response lost
					// after the server successfully submitted its payment.
					const intent = read_intent(invoice);
					if (intent && !intent.completed) frm.add_custom_button(__("Retry Previous Payment"), () => open_payment(frm, context), __("Create"));
				}
			} catch {
				frm.dashboard.set_headline_alert(__("Unable to load supplier advances. Standard invoice and payment actions remain available."), "orange");
			}
		},
	});
})();
