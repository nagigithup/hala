# Simplified Purchase Invoice in Hala Booking

Open `/desk/hala-booking` and choose **فاتورة مشتريات**. The action is available
to the existing **Purchase Manager** role and System Manager, subject to native
Purchase Invoice permissions. Ordinary cashiers do not receive purchase rights.

The simplified Arabic RTL pane contains the actual ERPNext Purchase Invoice
form. Supplier defaults, items, buying price lists, UOM conversion, taxes,
discounts, currency conversion, saving, submission and workflow actions continue
to use its native controllers and save endpoints.

## Independent checkboxes

| Visible checkbox | Native field | New invoice default |
| --- | --- | --- |
| تحديث المخزون | `update_stock` | Unchecked |
| مدفوعة | `is_paid` | Unchecked |

Changing either checkbox leaves the other unchanged. Update Stock displays the
receiving warehouse controls. Stock rows need a receiving warehouse; the header
can fill missing warehouses and per-row warehouses remain supported. Is Paid
displays the native payment mode, Cash/Bank Account and paid amount. Its payment
mode/account controls are required when enabled. The native paid amount remains
editable, including native partial settlement behavior.

For invoices linked to Purchase Receipts, the visible Update Stock control is
locked and the standard receipt link/stock validation is preserved. No Purchase
Receipt or Stock Entry is created by this feature.

## Rate, amount and UOM entry

The normal item link searches codes and names. The native barcode input handles
barcode selection. Item Name, quantity, configured UOM, rate, line amount,
warehouse and discount are available through the native item grid.

- Quantity or line amount edits derive the unit rate from amount / quantity.
- A rate edit lets ERPNext recalculate line amount.
- Quantity changes retain the entered line amount. UOM changes retain the entered
  numeric quantity and line amount, with the quantity explicitly belonging to
  the newly selected unit.
- The UOM selector lists only the selected item's configured units. ERPNext
  obtains the real conversion factor and stock quantity.
- The precision helper uses the native rate/amount precision. An amount that
  cannot be represented at that precision is reported for correction.
- Versioned row intents reject stale responses and prevent calculation loops.
  A transient, unpersisted amount snapshot checks the server's final native line
  calculation before saving. It never overrides native rate/amount calculation.

Example verified in the browser: 5 Kg, amount SAR 125 -> rate SAR 25/Kg,
stock quantity 5,000 Gram. Editing rate to 30 changes amount to 150; changing
quantity to 10 retains total 150 and derives rate 15. Selecting Gram updates the
native stock quantity to 10 Gram while retaining that entered quantity/total.

Tax-inclusive and exclusive behavior comes from the native tax configuration.
The pane displays its tax inclusion notice and native totals. Advanced settings
restore the full native form and workflow actions while preserving entered data.

## Native payment and cashier closing

Checked Is Paid uses the Purchase Invoice's own paid amount, payment account and
GL posting. The separate Hala supplier-overpayment helper is skipped for these
invoices, and combining it with the simplified native payment path is rejected.
This feature does not create Payment Entries, Journal Entries or direct GL rows.

A current drawer payment is attached to the logged-in user's active opening
shift, POS Profile, cashier, native mode and native Cash/Bank Account. The profile's
configured cash mode is used even when its default sale payment mode is a card.
Another drawer is rejected. Authorized managers may use other permitted
unassigned cash/bank accounts; bank payments have no physical drawer attribution.

The existing optional POS closing adapter now also reads actual submitted
Purchase Invoice cash GL credits. Movements are deduplicated by voucher type/name.
Reports show purchase outflows separately from expense journals. Draft, pending,
cancelled, bank and unassigned petty-cash payments do not affect the drawer.
The standard invoice/stock/payment posting controllers are unchanged.

An active Purchase Invoice approval workflow opens the native workflow controls.
The server requires a submitted workflow state before posting a marked purchase.
Native transition permissions continue to determine who can approve it.

## History, retry protection and printing

The recent-purchase list uses native document/company permissions and shows
invoice, supplier, date, total, payment status, outstanding and creator. Selecting
an invoice opens its actual form in the same pane. Native permissions and document
status control editing. Submitted invoices can be reprinted.

A unique request ID prevents a repeated new-invoice save from creating another
invoice or repeating its stock/payment posting. The recovery action finds the
permitted invoice after an uncertain save response. Native save locking remains
in effect, and form controls recover from validation failures.

Printing uses the Purchase Invoice's configured default format and letterhead.
QZ sends the native PDF with its configured paper sizing. Browser printing is the
fallback when QZ/PDF preparation is unavailable. Purchase invoices are not forced
into the POS 80mm receipt format. An ambiguous QZ dispatch failure does not trigger
a second browser print job. Physical printer hardware was not available to test.

## Accounting and inventory verification

Tests use the isolated `hala-disbursement-test.localhost` site. Financial test
transactions are rolled back. Browser saving created only isolated draft records.
No test purchase or payment was submitted to the live site.

For a SAR 125 invoice, quantity 5 Kg, conversion 1 Kg = 1,000 Gram, opening cash 500:

| Is Paid | Update Stock | Cash credit | New stock movement/value | Payable outstanding | Expected drawer |
| --- | --- | ---: | --- | ---: | ---: |
| No | No | 0 | None | 125 | 500 |
| Yes | No | 125 | None | 0 | 375 |
| No | Yes | 0 | +5,000 Gram / SAR 125 | 125 | 500 |
| Yes | Yes | 125 | +5,000 Gram / SAR 125 | 0 | 375 |

All four cases create only their normal Purchase Invoice postings. No additional
Payment Entry, Journal Entry, Stock Entry or Purchase Receipt is created.
A bank payment credits bank 125 and leaves drawer cash at 500. Cancellation restores
the native stock balance and drawer expectation. A linked Purchase Receipt stays
at 5,000 Gram; its Purchase Invoice does not receive those goods again.

18 new backend tests cover these combinations, actual stock valuation, UOM/barcode
selection, precision errors, native taxes/discounts/item tax templates, approvals,
role/account restrictions, cash/card profile configuration, duplicate requests,
amount mismatches, cancellation and configured print rendering.

117 existing regressions pass: disbursements 19, supplier payments 13, Booking 14,
customer receipts 9, deposits 13, official closing 28 and preliminary closing 21.
Five Node test files pass, including the native purchase PDF/QZ path and existing
voucher, supplier payment, booking history and sidebar behavior.

Authenticated Chromium verified all four checkbox combinations, conditional
warehouse/payment fields, item/rate/UOM calculations, native draft save/history,
Purchase Manager access without the Hala Portal role, and the ordinary cashier's
hidden purchase action. Screenshots and successful logs are saved under:
`/home/nagi/my-bench/artifacts/hala-purchase/`.

## Local installation and configuration

Applied to `helohala.localhost` after a successful backup and asset build.
Fingerprints of existing invoices, payments, journals, general ledger and stock
ledger records matched before and after setup. Existing financial/stock records
were unchanged.

Required configuration remains the normal ERPNext configuration: permitted
supplier/accounts, warehouses, buying defaults, taxes, stock requirements and
approval workflows. Purchase Manager is the existing role; it must also carry
appropriate native Purchase Invoice rights, such as those supplied by Accounts
User/Accounts Manager. No additional financial permissions are granted here.
Drawer payments additionally require the user's authorized POS Profile and open
shift, with a configured cash mode/account. This purchase feature does not require
HRMS.

For another already installed site, use its normal migration or the scoped setup:

```bash
bench --site YOUR_SITE backup
bench --site YOUR_SITE execute hala.setup.install_quick_purchase
bench build --app hala
bench --site YOUR_SITE clear-cache
```

Restart production processes through the deployment's usual process manager.
Refresh the browser after installation.

## Files changed for this task

Hala:

- `hala/api/quick_purchase.py`: role checks, permitted history/UOMs, precision,
  native-form guards, approval checks, request recovery, print options and closing
  GL adapter.
- `hala/public/js/quick_purchase.js`: Booking purchase pane and recent invoices.
- `hala/public/js/quick_purchase_form.js`: native form layout, independent flags,
  amount/rate input intents, validation, save/submit/print and advanced view.
- `hala/public/css/quick_purchase.css`: Arabic RTL and responsive layout.
- `hala/public/js/booking_page.js`, `hala/hala/page/hala_booking/hala_booking.json`:
  authorized entry point and Purchase Manager page access.
- `hala/public/js/purchase_invoice.js`, `hala/api/supplier_payment.py`: isolate the
  separate overpayment helper from marked native quick purchases.
- `hala/public/js/booking_pos_print.bundle.js`: native Purchase Invoice PDF/QZ path.
- `hala/setup.py`, `hala/hooks.py`: five hidden/read-only provenance/idempotency
  fields, setup hooks and feature-scoped validations/closing adapter.
- `hala/tests/test_quick_purchase.py`, `hala/tests/test_quick_purchase.mjs`.
- `docs/quick-purchase.md`: this report.

POS Next:

- `pos_next/pos_next/doctype/pos_closing_shift/pos_closing_shift.py`: recognize
  additional native purchase cash movements, per-type totals and deduplication.
- `pos_next/pos_next/doctype/pos_closing_shift/closing_shift_details.html`:
  voucher type and outgoing purchase/expense detail.

Frappe and ERPNext core source trees were unchanged. Earlier voucher work was
preserved.
