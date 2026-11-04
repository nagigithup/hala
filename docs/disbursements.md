# سند صرف — Hala Booking and POS Next

Implemented locally on `helohala.localhost`. Open `/desk/hala-booking` and choose
**سند صرف**. The existing receipt, deposit and booking interfaces remain available.

## Accounting and approvals

| Type | Standard document and accounting |
| --- | --- |
| رد مبلغ لعميل | Pay Payment Entry; refunds submitted customer receipts/available advances, draft-booking advances, or outstanding submitted Sales Return/Credit Notes. The original payment is reconciled through ERPNext's standard reverse-payment reconciliation. |
| دفع لمورد | Pay Payment Entry; allocates up to the Purchase Invoice's current outstanding amount. Excess or payments without an invoice remain standard supplier advances. |
| سلف موظفين | HRMS Employee Advance, followed by its standard linked Payment Entry after approval. Debits the employee advance account. Standard Expense Claim settlement remains available. |
| مصروفات عامة | Standard Journal Entry: debit the approved category's expense account, credit the actual cash/bank account. Only explicitly approved direct petty-cash categories are available. |

The Hala Disbursement record is a request/audit envelope and idempotency key. It
is not an accounting ledger. Amounts, company, source, cashier and accounting
links cannot be edited through its form. Status is derived from the standard
payment document: pending, paid, or cancelled. Draft requests do not move money.

Active Employee Advance, Payment Entry and Journal Entry workflows are respected.
Requests remain pending until standard approval; the history's **متابعة الدفع**
continues an approved employee advance. An authorized accountant can apply the
configured payment workflow while the originating cashier's drawer remains open.
If that shift closes before payment, the originating cashier must continue the
request in their current authorized shift. Standard document permissions still
apply to creating, submitting, reading, printing and cancelling accounting records.

Customer refund limits use submitted ledger balances/outstanding credit notes,
with source locks and a second check at submission. Refunds exclude deposits
(`استرداد تأمين`) and advances already converted to submitted booking invoices.
Refunding a booking advance updates its form, open-booking list, history, print
and closing totals to show the net paid amount. Return stock and tax documents
are not modified by the refund interface.

## Cashier closing

Existing POS Next logic already counts submitted Receive/Pay Payment Entries once
by opening shift and payment mode. All three Payment Entry paths reuse that logic.
A small optional closing adapter adds submitted expense Journal Entry cash lines.
It reads actual journal credits and checks the request's company, opening shift,
profile and cashier. These journals remain separate from the Payment Entry child
table. Reports show outgoing expense cash separately.

Bank payments have no drawer shift. Draft, unapproved, cancelled and duplicate
movements are excluded. Existing sales/tax/change calculations were preserved.
Two preliminary-closing test fixtures used an outdated summary dictionary; they
now use the existing summary initializer so their original cash/change assertions
can run against the current reporting fields.

## Required configuration

1. Assign the exact **سند الصرف** role to authorized users. System Manager also
   has feature access. Keep their normal Hala/POS, company, account and accounting
   document permissions. This feature role grants no financial submission rights.
2. Cashiers need their authorized POS Profile, its user assignment, a configured
   default Cash mode/account, and an active POS Opening Shift. Standard POS Next
   permissions, including POS Opening Shift read access, remain required.
3. Accountants can select permitted configured bank accounts and must supply a
   genuine bank reference. The quick form supports company currency; use the
   standard accounting editor for cross-currency transactions.
4. Accounts Manager/System Manager must create **Hala Expense Category** records
   with company, expense account, cost center, positive maximum amount and an
   accounting policy, then enable them. No live expense categories were invented
   or enabled automatically. Purchasing, stock, tax and approval requirements
   must use their standard purchasing/approval workflows.
5. **HRMS is not installed on `helohala.localhost`.** Install/configure a compatible
   HRMS app before using employee advances there. Configure the company's employee
   advance account as a Receivable account in the employee/company currency,
   employee records, HR permissions and any required approval workflow. No salary
   expense account is used as a substitute.
6. Customer advance refunds require standard Payment Reconciliation write access
   and write access to the original receipt. Accounting submission permissions
   are always required for actual payment.

## Installation

For a normal deployment, back up the site and run its standard migration, then
build Hala assets and clear cache. No Frappe or ERPNext core files were changed.
The optional scoped installer applies only these Hala DocTypes, fields, page roles
and print formats to an already installed site:

```bash
bench --site YOUR_SITE backup
bench --site YOUR_SITE execute hala.setup.install_disbursement
bench build --app hala
bench --site YOUR_SITE clear-cache
```

Restart production web/workers through the deployment's normal process manager.
The local development web server reloads the changed Python source automatically.
The installer preserves BOOKING branding/layout and changes its legacy payment
sum expressions to subtract refunds. Sites with a separately customized payment
sum expression should review that print calculation during deployment.

Applied locally after a successful database backup. Fingerprints of existing
Payment Entry, Sales Invoice, Purchase Invoice and Journal Entry records matched
before and after installation: names, statuses, modification times and financial
amounts were unchanged. No test financial transactions were posted to the live site.

## Verification

All financial integration tests run on the separate
`hala-disbursement-test.localhost` site with ERPNext, HRMS, POS Next and Hala.
Every financial test transaction is rolled back. Test fixtures and configuration
belong only to that isolated site.

- 19 new integration tests: real GL postings, partial supplier allocations,
  supplier advances, customer/booking/credit-note refund limits, cancellation,
  employee approval/payment/Expense Claim settlement, expense approval,
  role/drawer isolation, closed shifts, document tampering, printing, retries,
  bank exclusion and expected closing cash.
Test examples with an opening drawer of SAR 500:

| Scenario | Result |
| --- | --- |
| Supplier invoice 100, payment 40 | Invoice outstanding 60; drawer 460. |
| Customer receipt 100, refund 40 | Original credit remaining 60; drawer 560. |
| Expense 40 | Expense debit 40, cash credit 40; drawer 460. Cancellation restores 500. |
| Employee advance 40, then Expense Claim settlement 40 | Recoverable advance is paid and later claimed; drawer stays 460 after settlement. |
| Bank payment 40 | Bank credit 40; drawer stays 500. |

- Existing Python regressions: Booking 14, customer receipts 9, deposits 13,
  official closing 28, preliminary closing 21.
- Four Node test files pass: the new form/retry/QZ tests, supplier payments,
  booking history and cashier sidebar bundle.
- Authenticated Chromium verified the Booking button and all four Arabic RTL form
  states. Four 80mm receipts were rendered from submitted isolated test documents.
- QZ preparation fallback and ambiguous-dispatch protection were simulated.
  Physical QZ Tray/printer hardware was not available for a real printer test.
- Hala production assets build successfully. Ruff and Git whitespace checks pass.

Commands for the isolated test site:

```bash
bench --site hala-disbursement-test.localhost run-tests --module hala.tests.test_disbursement --skip-before-tests
node --test apps/hala/hala/tests/test_disbursement.mjs
```

Screenshots and receipt HTML/PDF previews are in
`/home/nagi/my-bench/artifacts/hala-disbursement/`. They contain isolated test data.

## Changed files

Hala:

- `hala/api/disbursement.py`: authorization, requests, standard accounting,
  source validation, history, printing and closing adapter.
- `hala/api/booking.py`: subtract actual booking refunds; allocate only receipts.
- `hala/setup.py`, `hala/hooks.py`: role/schema installation, document guards,
  reverse-payment reconciliation, print helper and closing integration hook.
- `hala/hala/doctype/__init__.py` and the `hala_disbursement/` and
  `hala_expense_category/` DocType directories: audit/configuration schemas and
  controllers.
- `hala/hala/page/hala_booking/hala_booking.json`, `hala/public/js/booking_page.js`:
  authorized Booking entry point.
- `hala/public/js/disbursement.js`: four Arabic forms, balances, history,
  persistent retry protection and printing.
- `hala/public/js/booking_pos_print.bundle.js`: reuse the existing QZ/browser
  print path for standard accounting documents.
- `hala/hala/print_format/hala_disbursement_payment/` and
  `hala/hala/print_format/hala_disbursement_expense/`: Arabic 80mm vouchers.
- `hala/fixtures/print_format.json`: BOOKING net payment total after refunds.
- `hala/tests/test_disbursement.py`, `hala/tests/test_disbursement.mjs`.
- `docs/disbursements.md`: this report.

POS Next (closing integration and relevant test fixtures only):

- `pos_next/pos_next/doctype/pos_closing_shift/pos_closing_shift.py`.
- `pos_next/pos_next/doctype/pos_closing_shift/closing_shift_details.html`.
- `pos_next/pos_next/doctype/cashier_preliminary_closing/test_cashier_preliminary_closing.py`.
