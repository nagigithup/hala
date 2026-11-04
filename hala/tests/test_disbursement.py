"""Accounting integration tests. Run ONLY on hala-disbursement-test.localhost.

Uses real standard controllers/ledgers and rolls back every test. No live company
or historical invoice is touched. Fixture company and users belong to this site.
"""

import unittest
from uuid import uuid4

import frappe
from frappe.utils import flt, nowdate, now_datetime
from hala.api import disbursement as api


class TestDisbursement(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if frappe.local.site != "hala-disbursement-test.localhost":
			raise unittest.SkipTest("Dedicated isolated test site required")
		frappe.set_user("Administrator")
		for doctype, name, values in [
			("Warehouse Type", "Transit", {"name": "Transit"}),
			("UOM", "Nos", {"uom_name": "Nos"}),
			("Party Type", "Customer", {"party_type": "Customer", "account_type": "Receivable"}),
			("Party Type", "Supplier", {"party_type": "Supplier", "account_type": "Payable"}),
			("Party Type", "Employee", {"party_type": "Employee", "account_type": "Receivable"}),
			("Gender", "Male", {"gender": "Male"}),
			(
				"Customer Group",
				"All Customer Groups",
				{"customer_group_name": "All Customer Groups", "is_group": 1},
			),
			(
				"Supplier Group",
				"All Supplier Groups",
				{"supplier_group_name": "All Supplier Groups", "is_group": 1},
			),
			("Item Group", "All Item Groups", {"item_group_name": "All Item Groups", "is_group": 1}),
			("Territory", "All Territories", {"territory_name": "All Territories", "is_group": 1}),
			(
				"Customer Group",
				"HDT Customers",
				{"customer_group_name": "HDT Customers", "parent_customer_group": "All Customer Groups"},
			),
			(
				"Supplier Group",
				"HDT Suppliers",
				{"supplier_group_name": "HDT Suppliers", "parent_supplier_group": "All Supplier Groups"},
			),
			(
				"Item Group",
				"HDT Items",
				{"item_group_name": "HDT Items", "parent_item_group": "All Item Groups"},
			),
			(
				"Territory",
				"HDT Territory",
				{"territory_name": "HDT Territory", "parent_territory": "All Territories"},
			),
		]:
			if not frappe.db.exists(doctype, name):
				frappe.get_doc(dict(doctype=doctype, **values)).insert()
		if not frappe.db.exists("Company", "Hala Disbursement Test"):
			frappe.get_doc(
				dict(
					doctype="Company",
					company_name="Hala Disbursement Test",
					abbr="HDT",
					default_currency="SAR",
					country="Saudi Arabia",
					chart_of_accounts="Standard",
				)
			).insert()
		cls.company = frappe.get_doc("Company", "Hala Disbursement Test")
		cls.cash = cls.company.default_cash_account
		cls.cost_center = cls.company.cost_center
		cls.expense = cls.company.default_expense_account
		cls.payable = cls.company.default_payable_account
		cls.receivable = cls.company.default_receivable_account
		asset = frappe.db.get_value(
			"Account",
			{
				"company": cls.company.name,
				"root_type": "Asset",
				"is_group": 1,
				"account_name": "Current Assets",
			},
			"name",
		)
		for name, kind in [("Test Bank", "Bank"), ("Test Employee Advances", "Receivable")]:
			account_name = name + " - HDT"
			if not frappe.db.exists("Account", account_name):
				frappe.get_doc(
					dict(
						doctype="Account",
						account_name=name,
						parent_account=asset,
						company=cls.company.name,
						account_type=kind,
						account_currency="SAR",
					)
				).insert()
		cls.bank = "Test Bank - HDT"
		cls.advance_account = "Test Employee Advances - HDT"
		cls.company.db_set("default_employee_advance_account", cls.advance_account)
		for name, kind, account in [("HDT Cash", "Cash", cls.cash), ("HDT Bank", "Bank", cls.bank)]:
			if not frappe.db.exists("Mode of Payment", name):
				frappe.get_doc(
					dict(
						doctype="Mode of Payment",
						mode_of_payment=name,
						type=kind,
						accounts=[dict(company=cls.company.name, default_account=account)],
					)
				).insert()
		if not frappe.db.exists("Fiscal Year", "HDT Fiscal Year"):
			year = nowdate()[:4]
			frappe.get_doc(
				dict(
					doctype="Fiscal Year",
					year="HDT Fiscal Year",
					year_start_date=year + "-01-01",
					year_end_date=year + "-12-31",
				)
			).insert()
		cls.warehouse = frappe.db.get_value("Warehouse", {"company": cls.company.name, "is_group": 0}, "name")
		if not frappe.db.exists("POS Profile", "HDT Profile"):
			frappe.get_doc(
				dict(
					doctype="POS Profile",
					name="HDT Profile",
					company=cls.company.name,
					currency="SAR",
					warehouse=cls.warehouse,
					cost_center=cls.cost_center,
					write_off_account=cls.expense,
					write_off_cost_center=cls.cost_center,
					payments=[dict(mode_of_payment="HDT Cash", default=1)],
					applicable_for_users=[dict(user="Administrator", default=1)],
				)
			).insert()
		for doctype, name, values in [
			(
				"Customer",
				"HDT Customer",
				dict(
					customer_name="HDT Customer",
					customer_type="Individual",
					customer_group="HDT Customers",
					territory="HDT Territory",
				),
			),
			(
				"Supplier",
				"HDT Supplier",
				dict(
					supplier_name="HDT Supplier",
					supplier_type="Company",
					supplier_group="HDT Suppliers",
				),
			),
			(
				"Item",
				"HDT Item",
				dict(
					item_code="HDT Item",
					item_name="HDT Item",
					is_stock_item=0,
					item_group="HDT Items",
					stock_uom="Nos",
				),
			),
			(
				"Hala Expense Category",
				"HDT Cleaning",
				dict(
					category_name="HDT Cleaning",
					company=cls.company.name,
					expense_account=cls.expense,
					cost_center=cls.cost_center,
					enabled=1,
					maximum_amount=200,
					policy="Approved direct cleaning petty cash without tax or purchasing requirement",
				),
			),
		]:
			if not frappe.db.exists(doctype, name):
				frappe.get_doc(dict(doctype=doctype, **values)).insert()
		if not frappe.db.exists("Employee", {"first_name": "HDT Employee"}):
			frappe.get_doc(
				dict(
					doctype="Employee",
					first_name="HDT Employee",
					company=cls.company.name,
					status="Active",
					gender="Male",
					date_of_birth="1990-01-01",
					date_of_joining="2020-01-01",
					salary_currency="SAR",
				)
			).insert()
		cls.employee = frappe.db.get_value("Employee", {"first_name": "HDT Employee"}, "name")
		if not frappe.db.exists("Price List", "HDT Selling"):
			frappe.get_doc(
				dict(doctype="Price List", price_list_name="HDT Selling", selling=1, currency="SAR")
			).insert()
		for email, roles in [
			("hdt-cashier@example.test", ["سند الصرف", "Accounts User", "Cashier", "Hala Portal User"]),
			("hdt-approver@example.test", ["System Manager", "Accounts Manager"]),
			("hdt-viewer@example.test", ["Hala Portal User"]),
		]:
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					dict(
						doctype="User",
						email=email,
						first_name=email.split("@")[0],
						send_welcome_email=0,
						roles=[dict(role=role) for role in roles],
					)
				).insert()
		frappe.get_doc("User", "hdt-cashier@example.test").add_roles("POSNext Cashier")
		# Clean up operational test shifts retained by an interrupted prior run.
		frappe.db.set_value(
			"POS Opening Shift", {"company": cls.company.name, "status": "Open"}, "status", "Closed"
		)
		profile = frappe.get_doc("POS Profile", "HDT Profile")
		if not any(row.user == "hdt-cashier@example.test" for row in profile.applicable_for_users):
			profile.append("applicable_for_users", dict(user="hdt-cashier@example.test"))
			profile.save()
		# Workflows create schema fields (DDL); prepare them outside test savepoints.
		for doctype in ("Employee Advance", "Journal Entry"):
			cls.workflow(doctype)
			frappe.db.set_value("Workflow", "HDT " + doctype, "is_active", 0)
		frappe.clear_cache()
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("disbursement_test")
		self.shift = frappe.get_doc(
			dict(
				doctype="POS Opening Shift",
				company=self.company.name,
				pos_profile="HDT Profile",
				user="Administrator",
				period_start_date=now_datetime(),
				posting_date=nowdate(),
				balance_details=[dict(mode_of_payment="HDT Cash", opening_amount=500, amount=500)],
			)
		).insert()
		self.shift.submit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="disbursement_test")
		frappe.clear_cache()

	def data(self, kind, **kwargs):
		return dict(
			request_id=uuid4().hex,
			kind=api.KINDS[kind],
			company=self.company.name,
			payment_account=self.cash,
			mode_of_payment="HDT Cash",
			posting_date=nowdate(),
			amount=40,
			description="اختبار صرف معزول",
			**kwargs,
		)

	def create(self, kind, **kwargs):
		return api.create_voucher(self.data(kind, **kwargs))

	def payment(self, result):
		return frappe.get_doc(result["payment_doctype"], result["payment_name"])

	def gl(self, doc, account):
		rows = frappe.get_all(
			"GL Entry",
			filters=dict(voucher_type=doc.doctype, voucher_no=doc.name, account=account, is_cancelled=0),
			fields=["debit", "credit"],
		)
		return sum(flt(r.debit) - flt(r.credit) for r in rows)

	def closing(self):
		from pos_next.pos_next.doctype.pos_closing_shift.pos_closing_shift import build_closing_snapshot

		doc = frappe.get_doc(
			dict(
				doctype="POS Closing Shift",
				pos_opening_shift=self.shift.name,
				company=self.company.name,
				pos_profile="HDT Profile",
				user="Administrator",
			)
		)
		return build_closing_snapshot(doc)

	def cash_expected(self):
		return next(
			r["expected_amount"]
			for r in self.closing()["reconciliation"]["modes"]
			if r["mode_of_payment"] == "HDT Cash"
		)

	def receipt(self, booking=None, deposit=False):
		pe = frappe.get_doc(
			dict(
				doctype="Payment Entry",
				payment_type="Receive",
				company=self.company.name,
				party_type="Customer",
				party="HDT Customer",
				paid_from=self.receivable,
				paid_to=self.cash,
				paid_amount=100,
				received_amount=100,
				source_exchange_rate=1,
				target_exchange_rate=1,
				mode_of_payment="HDT Cash",
				reference_no=self.shift.name,
				reference_date=nowdate(),
				custom_cashier_profile="HDT Profile",
				custom_booking_invoice=booking,
				custom_is_deposit=int(deposit),
			)
		).insert()
		pe.submit()
		return pe

	def invoice(self, doctype="Purchase Invoice", **kwargs):
		doc = frappe.get_doc(
			dict(
				doctype=doctype,
				company=self.company.name,
				posting_date=nowdate(),
				due_date=nowdate(),
				supplier="HDT Supplier" if doctype == "Purchase Invoice" else None,
				customer="HDT Customer" if doctype == "Sales Invoice" else None,
				currency="SAR",
				selling_price_list="HDT Selling",
				price_list_currency="SAR",
				plc_conversion_rate=1,
				credit_to=self.payable,
				debit_to=self.receivable,
				cost_center=self.cost_center,
				items=[
					dict(
						item_code="HDT Item",
						qty=1,
						rate=100,
						expense_account=self.expense,
						income_account=self.company.default_income_account,
						cost_center=self.cost_center,
					)
				],
				**kwargs,
			)
		).insert()
		return doc

	def test_supplier_partial_and_advance(self):
		invoice = self.invoice()
		invoice.submit()
		data = self.data(1, party="HDT Supplier", source_doctype="Purchase Invoice", source_name=invoice.name)
		row = api.create_voucher(data)
		pe = self.payment(row)
		self.assertTrue(row["paid"])
		self.assertEqual(pe.references[0].allocated_amount, 40)
		self.assertEqual(self.gl(pe, self.cash), -40)
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 60)
		self.assertEqual(self.cash_expected(), 460)
		row = self.create(1, party="HDT Supplier")
		self.assertEqual(self.payment(row).unallocated_amount, 40)
		self.assertEqual(self.cash_expected(), 420)

	def test_expense_posts_once_and_cancel_restores_drawer(self):
		data = self.data(3, beneficiary="عامل النظافة", expense_category="HDT Cleaning")
		row = api.create_voucher(data)
		je = self.payment(row)
		self.assertTrue(row["paid"])
		self.assertEqual(self.gl(je, self.expense), 40)
		self.assertEqual(self.gl(je, self.cash), -40)
		self.assertEqual(api.create_voucher(data)["name"], row["name"])
		self.assertEqual(self.cash_expected(), 460)
		self.assertEqual(self.closing()["cash_disbursements"]["expenses"], 40)
		je.cancel()
		self.assertEqual(self.cash_expected(), 500)
		self.assertEqual(api.get_voucher(row["name"])["status"], "ملغى")

	def test_customer_credit_refund_limits_and_cancellation(self):
		source = self.receipt()
		row = self.create(0, party="HDT Customer", source_doctype="Payment Entry", source_name=source.name)
		pe = self.payment(row)
		source.reload()
		self.assertEqual(source.references[0].reference_name, pe.name)
		self.assertEqual(source.unallocated_amount, 60)
		self.assertEqual(api._source_balance(source)[0], 60)
		self.assertEqual(self.cash_expected(), 560)
		data = self.data(0, party="HDT Customer", source_doctype="Payment Entry", source_name=source.name)
		data["amount"] = 61
		with self.assertRaises(frappe.ValidationError):
			api.create_voucher(data)
		pe.cancel()
		self.assertEqual(api._source_balance(source)[0], 100)

	def test_draft_booking_advance_refund(self):
		booking = self.invoice("Sales Invoice", custom_is_booking=1, pos_profile="HDT Profile")
		source = self.receipt(booking.name)
		row = self.create(0, party="HDT Customer", source_doctype="Payment Entry", source_name=source.name)
		self.assertTrue(row["paid"])
		source.reload()
		self.assertEqual(source.references[0].reference_name, row["payment_name"])
		from hala.api.booking import _booking_payments, _paid_in_invoice_currency

		self.assertEqual(_paid_in_invoice_currency(booking, _booking_payments(booking.name)), 60)
		from hala.api.booking import get_open_bookings

		self.assertEqual(
			next(row["paid_amount"] for row in get_open_bookings() if row["name"] == booking.name), 60
		)
		format_doc = frappe.get_doc("Print Format", "BOOKING")
		html = frappe.render_template(format_doc.html, {"doc": booking})
		self.assertIn("60.00", html.split('<tr class="paid-row">', 1)[1].split("</tr>", 1)[0])

	def test_deposit_refund_is_excluded(self):
		source = self.receipt(deposit=True)
		with self.assertRaises(frappe.ValidationError):
			self.create(0, party="HDT Customer", source_doctype="Payment Entry", source_name=source.name)

	def test_submitted_credit_note_refund(self):
		invoice = self.invoice("Sales Invoice")
		invoice.submit()
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		credit = make_sales_return(invoice.name)
		credit.insert()
		credit.submit()
		row = self.create(0, party="HDT Customer", source_doctype="Sales Invoice", source_name=credit.name)
		self.assertTrue(row["paid"])
		credit.reload()
		self.assertEqual(credit.outstanding_amount, -60)
		self.assertEqual(self.payment(row).references[0].reference_name, credit.name)

	def test_employee_advance_payment_and_settlement_reference(self):
		row = self.create(2, party=self.employee)
		self.assertTrue(row["paid"])
		advance = frappe.get_doc("Employee Advance", row["employee_advance"])
		pe = self.payment(row)
		self.assertEqual(advance.paid_amount, 40)
		self.assertEqual(advance.status, "Paid")
		self.assertEqual(pe.references[0].reference_doctype, "Employee Advance")
		self.assertEqual(pe.references[0].reference_name, advance.name)
		self.assertEqual(self.gl(pe, self.advance_account), 40)
		self.assertEqual(self.gl(pe, self.expense), 0)
		self.assertEqual(self.cash_expected(), 460)
		from hrms.hr.doctype.expense_claim.expense_claim import get_advances

		self.assertTrue(
			any(
				r.employee_advance == advance.name
				for r in get_advances(
					dict(
						doctype="Expense Claim",
						employee=self.employee,
						company=self.company.name,
						currency="SAR",
					)
				)
			)
		)
		pe.cancel()
		advance.reload()
		self.assertEqual(advance.paid_amount, 0)

	@staticmethod
	def workflow(doctype):
		if frappe.db.exists("Workflow", "HDT " + doctype):
			frappe.db.set_value("Workflow", "HDT " + doctype, "is_active", 1)
			frappe.clear_cache()
			return frappe.get_doc("Workflow", "HDT " + doctype)
		for state in ["HDT Draft", "HDT Approved"]:
			if not frappe.db.exists("Workflow State", state):
				frappe.get_doc(dict(doctype="Workflow State", workflow_state_name=state)).insert()
		if not frappe.db.exists("Workflow Action Master", "HDT Approve"):
			frappe.get_doc(
				dict(doctype="Workflow Action Master", workflow_action_name="HDT Approve")
			).insert()
		return frappe.get_doc(
			dict(
				doctype="Workflow",
				workflow_name="HDT " + doctype,
				document_type=doctype,
				is_active=1,
				workflow_state_field="workflow_state",
				states=[
					dict(state="HDT Draft", doc_status=0, allow_edit="System Manager"),
					dict(state="HDT Approved", doc_status=1, allow_edit="System Manager"),
				],
				transitions=[
					dict(
						state="HDT Draft",
						action="HDT Approve",
						next_state="HDT Approved",
						allowed="System Manager",
						allow_self_approval=1,
					)
				],
			)
		).insert()

	def test_employee_approval_pending_has_no_cash_and_then_pays_once(self):
		self.workflow("Employee Advance")
		row = self.create(2, party=self.employee)
		self.assertFalse(row["paid"])
		self.assertIsNone(row["payment_name"])
		self.assertEqual(self.cash_expected(), 500)
		from frappe.model.workflow import apply_workflow

		advance = frappe.get_doc("Employee Advance", row["employee_advance"])
		apply_workflow(advance, "HDT Approve")
		paid = api.pay_voucher(row["name"])
		self.assertTrue(paid["paid"])
		self.assertEqual(self.cash_expected(), 460)
		self.assertEqual(api.pay_voucher(row["name"])["payment_name"], paid["payment_name"])

	def test_expense_approval_pending_and_standard_workflow_submit(self):
		self.workflow("Journal Entry")
		row = self.create(3, beneficiary="Cleaning", expense_category="HDT Cleaning")
		self.assertFalse(row["paid"])
		self.assertEqual(self.cash_expected(), 500)
		from frappe.model.workflow import apply_workflow

		apply_workflow(self.payment(row), "HDT Approve")
		self.assertEqual(self.cash_expected(), 460)

	def test_bank_payment_excluded_from_physical_drawer(self):
		for kind, extra in [
			(1, dict(party="HDT Supplier")),
			(3, dict(beneficiary="Cleaning", expense_category="HDT Cleaning")),
		]:
			data = self.data(kind, **extra)
			data.update(payment_account=self.bank, mode_of_payment="HDT Bank", bank_reference=uuid4().hex)
			row = api.create_voucher(data)
			self.assertTrue(row["paid"])
			self.assertIsNone(row["pos_opening_shift"])
			self.assertEqual(self.gl(self.payment(row), self.bank), -40)
		self.assertEqual(self.cash_expected(), 500)

	def test_role_security(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.get_history()
		with self.assertRaises(frappe.PermissionError):
			api.create_voucher({})

	def test_unapproved_category_and_tampered_account_rejected(self):
		frappe.db.set_value("Hala Expense Category", "HDT Cleaning", "enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			self.create(3, beneficiary="Cleaning", expense_category="HDT Cleaning")
		with self.assertRaises(frappe.ValidationError):
			data = self.data(1, party="HDT Supplier")
			data["payment_account"] = self.expense
			api.create_voucher(data)

	def test_print_paid_and_cancelled(self):
		row = self.create(1, party="HDT Supplier")
		options = api.get_print_options(row["name"])
		html = frappe.get_print(options["doctype"], options["name"], options["print_format"])
		self.assertIn("سند صرف", html)
		self.assertIn(row["name"], html)
		self.payment(row).cancel()
		with self.assertRaises(frappe.ValidationError):
			api.get_print_options(row["name"])

	def test_cashier_cannot_use_another_account_or_view_another_cashier_voucher(self):
		row = self.create(1, party="HDT Supplier")
		opening = frappe.get_doc(
			dict(
				doctype="POS Opening Shift",
				company=self.company.name,
				pos_profile="HDT Profile",
				user="hdt-cashier@example.test",
				period_start_date=now_datetime(),
				posting_date=nowdate(),
				balance_details=[dict(mode_of_payment="HDT Cash", amount=100)],
			)
		).insert()
		opening.submit()
		frappe.set_user("hdt-cashier@example.test")
		with self.assertRaises(frappe.PermissionError):
			api.get_voucher(row["name"])
		data = self.data(1, party="HDT Supplier")
		data.update(payment_account=self.bank, mode_of_payment="HDT Bank", bank_reference="BANK-OTHER")
		with self.assertRaises(frappe.PermissionError):
			api.create_voucher(data)
		own = self.create(1, party="HDT Supplier")
		self.assertTrue(own["paid"])
		self.assertEqual(own["cashier"], "hdt-cashier@example.test")
		self.assertEqual(own["pos_opening_shift"], opening.name)

	def test_hala_portal_role_alone_does_not_grant_disbursement_access(self):
		frappe.set_user("hdt-viewer@example.test")
		with self.assertRaises(frappe.PermissionError):
			api.get_context()
		with self.assertRaises(frappe.PermissionError):
			api.get_history()

	def test_closing_shift_prevents_further_cash_disbursement(self):
		self.shift.db_set("status", "Closed")
		with self.assertRaises(frappe.PermissionError):
			self.create(1, party="HDT Supplier")

	def test_standard_draft_cannot_change_amount_or_remove_voucher_link(self):
		self.workflow("Journal Entry")
		row = self.create(3, beneficiary="Cleaning", expense_category="HDT Cleaning")
		journal = self.payment(row)
		journal.accounts[0].debit_in_account_currency = 50
		journal.accounts[1].credit_in_account_currency = 50
		with self.assertRaises(frappe.ValidationError):
			journal.save()
		journal.reload()
		journal.custom_hala_disbursement = None
		with self.assertRaises(frappe.ValidationError):
			journal.save()

	def test_accountant_can_apply_configured_workflow_without_stealing_drawer(self):
		self.workflow("Journal Entry")
		row = self.create(3, beneficiary="Cleaning", expense_category="HDT Cleaning")
		frappe.set_user("hdt-approver@example.test")
		from frappe.model.workflow import apply_workflow

		apply_workflow(self.payment(row), "HDT Approve")
		self.assertTrue(api.get_voucher(row["name"])["paid"])
		frappe.set_user("Administrator")
		self.assertEqual(self.cash_expected(), 460)

	def test_employee_advance_settlement_uses_standard_expense_claim(self):
		row = self.create(2, party=self.employee)
		frappe.get_doc(
			dict(
				doctype="Expense Claim Type",
				expense_type="HDT Travel",
				accounts=[dict(company=self.company.name, default_account=self.expense)],
			)
		).insert()
		from hrms.hr.doctype.expense_claim.expense_claim import get_expense_claim

		claim = get_expense_claim(row["employee_advance"])
		claim.payable_account = self.payable
		claim.approval_status = "Approved"
		claim.exchange_rate = 1
		claim.is_paid = 0
		claim.append(
			"expenses",
			dict(
				expense_type="HDT Travel",
				expense_date=nowdate(),
				amount=40,
				sanctioned_amount=40,
				default_account=self.expense,
				cost_center=self.cost_center,
				currency="SAR",
			),
		)
		claim.insert()
		claim.submit()
		advance = frappe.get_doc("Employee Advance", row["employee_advance"])
		self.assertEqual(advance.claimed_amount, 40)
		self.assertEqual(advance.status, "Claimed")
		self.assertEqual(claim.advances[0].reference_name, row["payment_name"])
		self.assertEqual(self.cash_expected(), 460)  # Settlement creates no second drawer movement.
