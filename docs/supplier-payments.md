# Supplier overpayments on standard Purchase Invoices

## Cause and workflow

ERPNext's `PurchaseInvoice.validate_cash` rejects an invoice's `paid_amount` plus
write-off above its rounded/grand total. That field represents settlement inside
the invoice, not all cash handed to the supplier. The local Purchase Invoice has
no Client Script or Server Script overriding this behavior.

For a draft invoice, an overpayment typed into the native **Paid Amount** field
automatically enables **Supplier Payment on Submit / دفع المورد عند اعتماد الفاتورة**.
The full amount moves into **Actual Amount Paid to Supplier**, alongside its cash/
bank account. Native **Is Paid / Paid Amount** are cleared so ERPNext does not post
the same money inside the invoice. The standard validation remains intact.

Saving stores the payment instruction only. Submitting posts the normal invoice,
then its supplier Payment Entry in the same transaction. A payment failure rolls
the entire submission back. The checkbox can also be enabled explicitly for exact
or partial payments. A read-only summary shows total, allocation and excess.
The payment section uses three standard responsive form columns: actual amount;
cash/bank account and references; payment summary.

An already submitted invoice can still use **Create > Supplier Payment**
(**إنشاء > دفعة للمورد**). Existing standard native payments within the invoice's
permissible total remain supported. Additional payments allocate only the remaining
outstanding amount.

The dialog shows the read-only invoice total, editable actual bank/cash outflow,
read-only allocation, and read-only excess supplier advance. Currency labels
identify the invoice, bank and payable-account amounts. ERPNext supplies the
exchange rates. A changed balance/rate requires reopening and reviewing the quote.

A normal **Pay / Supplier Payment Entry** is inserted and submitted in one request
transaction with normal permissions and validations. Only the invoice's remaining
balance is allocated; the full payment leaves the cash/bank account. There is no
write-off or artificial journal. In separate-payment mode, invoice `paid_amount`
is zero: cash outflow is accounted for entirely by Payment Entry.

Invoices with withholding taxes or generated payment deductions/discounts retain
the full standard **Create > Payment** editor so their accounting can be reviewed.
Held invoices and returns cannot use the new action.
The inline amount requires matching invoice, cash/bank and payable currencies.
Cross-currency payments use the existing post-submission dialog with its explicit
rate quote. Bank payments require a genuine reference number.

## Accounting example

| Document | Debit | Credit |
| --- | ---: | ---: |
| Purchase Invoice: expense/inventory | SAR 87.50 | |
| Purchase Invoice: supplier payable | | SAR 87.50 |
| Payment Entry: supplier payable | SAR 100.00 | |
| Payment Entry: cash/bank | | SAR 100.00 |

Payment Entry allocation is SAR 87.50; unallocated amount is SAR 12.50. Invoice
outstanding is zero. Net supplier ledger balance is a SAR 12.50 debit (our advance
to the supplier); cash/bank decreases by SAR 100. Existing invoice taxes and totals
remain unchanged. Exact expense/inventory/tax postings follow the original invoice.

The dashboard's **Available Supplier Advance / الرصيد المقدم للمورد** uses ERPNext's
standard advance query against submitted Payment Entries. It filters company,
supplier, compatible payable/advance accounts, currency, and document permissions.
It is a live derived value, not a stored custom balance. **View > Supplier
Unallocated Payments** opens the standard list. Use standard **Get Advances** on a
draft invoice or **Payment Reconciliation** explicitly to apply credit. Existing
ERPNext FIFO policies remain intact; this extension never auto-consumes credit.

## Retry and failure behavior

The Purchase Invoice row is locked while creating a payment. Payment Entry has a
unique request ID and a link back to the invoice. Repeated requests with that ID
return the same submitted payment; a cancelled payment is never recreated.
Browser storage retains an immutable pending intent across refreshes/network
failures. After success, recording another payment requires an explicit action.
Definite server errors roll the request transaction back and allow correction.
Standard cancellation/reconciliation controls the ledger and remaining advance.

## Files

- `hala/hooks.py`: Purchase Invoice form script and draft/submit event hooks only.
- `hala/setup.py`: two provenance/idempotency Custom Fields on Payment Entry and
  nine fields for Purchase Invoice payment intent, references and UI, installed
  by existing install/migrate hooks; no supplier balance field or new DocType.
- `hala/api/supplier_payment.py`: authorized context/advance lookup and payment API.
- `hala/public/js/purchase_invoice.js`: standard form dashboard and payment dialog.
- `hala/translations/ar.csv`: Arabic labels and dialog guidance.
- `hala/tests/test_supplier_payment.py`: transactional accounting integration tests.
- `hala/tests/test_supplier_payment.mjs`: dialog calculations and retry behavior.
- `docs/supplier-payments.md`: this report.

## Local validation

All 13 accounting integration tests and the simulated form/dialog tests pass. All test
invoices, suppliers, items, payments and ledger entries are rolled back.
Tests use the current server date; the foreign-currency test fixes only its exchange
rate for deterministic accounting assertions.

- 87.50 / 100 -> allocation 87.50, advance 12.50, outstanding 0.
- 100 / 100 -> allocation 100, advance 0, outstanding 0.
- 100 / 50 -> allocation 50, advance 0, outstanding 50.
- 100 / 150 -> allocation 100, advance 50, outstanding 0.
- Explicit standard allocation of 30 from a 50 advance leaves 20; stale competing
  allocation is rejected. Other suppliers cannot see that credit.
- Cancellation restores invoice outstanding and reverses supplier/cash effects.
- SAR 562.50 payment for a USD 100 invoice at 3.75 allocates USD 100 and leaves
  USD 50 unallocated, using standard ERPNext currency and ledger handling.
- Duplicate requests return one Payment Entry; cancelled/reused IDs, stale quotes,
  invalid amounts, foreign-company accounts and unauthorized access are rejected.
- A submit failure rolls back the payment and leaves invoice outstanding unchanged.
- A VAT-bearing invoice keeps its net total, VAT, grand total and original GL
  postings unchanged after the overpayment.
- Draft 89.82 / payment 90 saves without posting cash, then submission allocates
  89.82 and leaves 0.18. Duplicate hook execution creates no second Payment Entry.
- A supplier payment failure during invoice submission rolls both documents and
  the invoice GL back; the invoice remains draft.
- On ACC-PINV-2026-00170 itself, the standard validation methods accept an
  in-memory payment of 90 after routing it to separate payment intent. This check
  does not save or submit the actual invoice or create its payment.
- Frontend checks cover read-only derived fields, double clicks, reload recovery,
  validation-error correction, draft overpayment capture and separation of actual
  cash from native invoice settlement.
- Existing POS Next cash tender/change regression passes. Two existing closing
  tests have outdated summary fixtures (missing newer reporting totals); their
  cash/change assertions are also checked with complete summary fixtures in the
  test harness, without modifying POS Next. POS Next and all Sales Invoice
  hooks/payment behavior are unchanged.

These are accounting integration and simulated frontend tests. They do not claim
an interactive browser walkthrough or a supplier payment posted permanently.

Reference: [ERPNext Payment Entry documentation](https://docs.frappe.io/erpnext/payment-entry).
