"""Disbursement requests; all money is posted by standard ERPNext/HRMS controllers."""

from __future__ import annotations

import math
import frappe
from frappe.utils import flt, getdate, nowdate

from hala.api.booking import _active_shift
from hala.api.deposit import _cashier_context
from hala.cashier_profile import has_elevated_cashier_access

ROLE = "سند الصرف"
KINDS = ("رد مبلغ لعميل", "دفع لمورد", "سلف موظفين", "مصروفات عامة")
TOLERANCE = 0.005


def require_access():
	if frappe.session.user == "Guest" or not set(frappe.get_roles()).intersection({ROLE, "System Manager"}):
		frappe.throw("ليس لديك صلاحية سند الصرف.", frappe.PermissionError)


def _read(doctype, name, company=None, lock=False):
	if lock:
		# Only server-selected DocTypes are accepted by callers of this helper.
		frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE name=%s FOR UPDATE", name)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	if company and doc.get("company") != company:
		frappe.throw("المستند لا يتبع الشركة المختارة.", frappe.PermissionError)
	return doc


def _account(name, company, currency=None):
	doc = _read("Account", name, company)
	if doc.is_group or doc.disabled or (currency and doc.account_currency != currency):
		frappe.throw("الحساب غير صالح أو العملة غير مدعومة. استخدم شاشة المحاسبة للتحويل بين العملات.")
	return doc


def _context(company=None, payment_account=None, mode_of_payment=None):
	if not has_elevated_cashier_access():
		ctx = _cashier_context()
		account = _account(ctx.payment_account, ctx.company)
		if account.account_type != "Cash":
			frappe.throw("يلزم حساب نقدي معتمد لدرج الكاشير.")
		if (
			(company and company != ctx.company)
			or (payment_account and payment_account != account.name)
			or (mode_of_payment and mode_of_payment != ctx.mode_of_payment)
		):
			frappe.throw("لا يمكن الصرف من درج كاشير آخر.", frappe.PermissionError)
	else:
		if not company or not payment_account or not mode_of_payment:
			frappe.throw("اختر الشركة وحساب الصرف وطريقة الدفع.")
		account = _account(payment_account, company)
		ctx = frappe._dict(
			company=company,
			payment_account=account.name,
			currency=account.account_currency,
			mode_of_payment=mode_of_payment,
			shift=None,
			profile=None,
		)
		if account.account_type == "Cash":
			drawer = _cashier_context()
			if (
				drawer.company != company
				or drawer.payment_account != account.name
				or drawer.mode_of_payment != mode_of_payment
			):
				frappe.throw("الصرف النقدي يتطلب درجك المعتمد ووردية مفتوحة.")
			ctx = drawer
	company_doc = _read("Company", ctx.company)
	if ctx.currency != company_doc.default_currency:
		frappe.throw("الصرف السريع يدعم عملة الشركة فقط؛ استخدم شاشة المحاسبة للتحويل بين العملات.")
	mode = _read("Mode of Payment", ctx.mode_of_payment)
	if mode.get("enabled") == 0 or account.account_type not in ("Cash", "Bank"):
		frappe.throw("طريقة الدفع أو حساب الصرف غير صالح.")
	if (mode.type == "Cash") != (account.account_type == "Cash"):
		frappe.throw("نوع طريقة الدفع لا يطابق الحساب.")
	if (
		frappe.db.get_value(
			"Mode of Payment Account", {"parent": mode.name, "company": ctx.company}, "default_account"
		)
		!= account.name
	):
		frappe.throw("حساب الصرف يجب أن يكون الحساب المعتمد لطريقة الدفع.")
	if ctx.shift:
		_validate_drawer(ctx, frappe.session.user)
	return ctx


def _validate_drawer(ctx, cashier):
	profile = _read("POS Profile", ctx.profile.name, ctx.company)
	if profile.disabled or not any(row.user == cashier for row in profile.get("applicable_for_users") or []):
		frappe.throw("المستخدم غير معتمد على ملف الكاشير.", frappe.PermissionError)
	shift = _read("POS Opening Shift", ctx.shift.name, ctx.company, lock=True)
	if (
		shift.user != cashier
		or shift.docstatus != 1
		or shift.status != "Open"
		or shift.get("pos_closing_shift")
		or shift.get("custom_preliminary_closed")
	):
		frappe.throw("وردية الكاشير مغلقة.")
	if frappe.db.exists(
		"Cashier Preliminary Closing", {"pos_opening_shift": shift.name, "docstatus": ["<", 2]}
	) or frappe.db.exists("POS Closing Shift", {"pos_opening_shift": shift.name, "docstatus": ["<", 2]}):
		frappe.throw("بدأ إغلاق الوردية؛ لا يمكن تسجيل صرف جديد.")


def _amount(value):
	value = flt(value, 2)
	if not math.isfinite(value) or value <= 0:
		frappe.throw("المبلغ يجب أن يكون أكبر من صفر.")
	return value


def _workflow(doctype):
	return frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")


def _submit_if_authorized(doc):
	# Approvals stay in the standard Desk workflow; never infer an approval.
	if not _workflow(doc.doctype) and frappe.has_permission(doc.doctype, "submit", doc):
		doc.submit()
	return doc


def _request(name, lock=False):
	require_access()
	doc = _read("Hala Disbursement", name, lock=lock)
	_read("Company", doc.company)
	if not has_elevated_cashier_access() and doc.cashier != frappe.session.user:
		frappe.throw("السند لا يتبع الكاشير الحالي.", frappe.PermissionError)
	return doc


def _summary(doc):
	status = "بانتظار الموافقة / الدفع"
	payment = None
	if doc.payment_name:
		payment = _read(doc.payment_doctype, doc.payment_name, doc.company)
		status = {0: "بانتظار الموافقة", 1: "مدفوع", 2: "ملغى"}[payment.docstatus]
	elif doc.employee_advance:
		advance = _read("Employee Advance", doc.employee_advance, doc.company)
		if advance.docstatus == 2:
			status = "ملغى"
	return {
		**{
			key: doc.get(key)
			for key in (
				"name",
				"kind",
				"company",
				"posting_date",
				"amount",
				"currency",
				"beneficiary",
				"description",
				"source_doctype",
				"source_name",
				"employee_advance",
				"payment_doctype",
				"payment_name",
				"pos_profile",
				"pos_opening_shift",
				"cashier",
			)
		},
		"status": status,
		"paid": bool(payment and payment.docstatus == 1),
	}


def _source_balance(doc):
	if doc.doctype == "Payment Entry":
		if (
			doc.docstatus != 1
			or doc.payment_type != "Receive"
			or doc.party_type != "Customer"
			or doc.get("custom_is_deposit")
		):
			frappe.throw("اختر دفعة عميل معتمدة وليست تأميناً.")
		booking = doc.get("custom_booking_invoice")
		if booking:
			b = _read("Sales Invoice", booking, doc.company, lock=True)
			if b.docstatus != 0 or not b.get("custom_is_booking"):
				frappe.throw("رد دفعة الحجز متاح للحجز المسودة فقط؛ استخدم مرتجعاً معتمداً بعد الفوترة.")
		# Authoritative ledger includes reconciliations and refunds from every interface.
		balance = frappe.db.sql(
			"""SELECT COALESCE(SUM(amount_in_account_currency),0)
			FROM `tabPayment Ledger Entry` WHERE against_voucher_type='Payment Entry'
			AND against_voucher_no=%s AND party_type='Customer' AND party=%s
			AND company=%s AND account=%s AND delinked=0""",
			(doc.name, doc.party, doc.company, doc.paid_from),
		)[0][0]
		return max(-flt(balance), 0), doc.paid_from, doc.party
	if doc.docstatus != 1 or not doc.is_return or flt(doc.outstanding_amount) >= 0:
		frappe.throw("اختر إشعاراً دائناً / مرتجع مبيعات معتمداً وله رصيد قابل للرد.")
	return -flt(doc.outstanding_amount), doc.debit_to, doc.customer


def _reference(doctype, name, amount, party_type, party, currency):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_reference_details

	details = get_reference_details(doctype, name, currency, party_type=party_type, party=party)
	return dict(
		reference_doctype=doctype,
		reference_name=name,
		allocated_amount=amount,
		total_amount=details.total_amount,
		outstanding_amount=details.outstanding_amount,
		exchange_rate=details.exchange_rate or 1,
	)


def _party_payment(request, ctx):
	from erpnext.accounts.party import get_party_account

	kind = request.kind
	party_type = "Customer" if kind == KINDS[0] else "Supplier"
	party = request.party
	_read(party_type, party)
	account = get_party_account(party_type, party, ctx.company)
	refs = []
	if kind == KINDS[0]:
		if request.source_doctype not in ("Payment Entry", "Sales Invoice") or not request.source_name:
			frappe.throw("اختر الدفعة الأصلية أو إشعاراً دائناً معتمداً.")
		source = _read(request.source_doctype, request.source_name, ctx.company, lock=True)
		balance, account, customer = _source_balance(source)
		if customer != party or request.amount > balance + TOLERANCE:
			frappe.throw("المبلغ يتجاوز الرصيد المتاح للرد أو العميل غير مطابق.")
		if source.doctype == "Payment Entry":
			# ERPNext reconciles reverse payments after submission, rather than
			# accepting an original Payment Entry as an ordinary invoice reference.
			frappe.has_permission("Payment Reconciliation", "write", throw=True)
			source.check_permission("write")
		else:
			refs = [_reference(source.doctype, source.name, -request.amount, party_type, party, ctx.currency)]
	elif request.source_name:
		invoice = _read("Purchase Invoice", request.source_name, ctx.company, lock=True)
		if (
			request.source_doctype != "Purchase Invoice"
			or invoice.docstatus != 1
			or invoice.supplier != party
			or invoice.is_return
			or invoice.get("on_hold")
		):
			frappe.throw("فاتورة المورد غير متاحة للدفع.")
		account = invoice.credit_to
		allocation = min(max(flt(invoice.outstanding_amount), 0), request.amount)
		if allocation:
			refs = [_reference("Purchase Invoice", invoice.name, allocation, party_type, party, ctx.currency)]
	_account(account, ctx.company, ctx.currency)
	pe = frappe.new_doc("Payment Entry")
	pe.update(
		dict(
			payment_type="Pay",
			company=ctx.company,
			posting_date=request.posting_date,
			party_type=party_type,
			party=party,
			paid_from=ctx.payment_account,
			paid_to=account,
			paid_from_account_currency=ctx.currency,
			paid_to_account_currency=ctx.currency,
			paid_amount=request.amount,
			received_amount=request.amount,
			source_exchange_rate=1,
			target_exchange_rate=1,
			mode_of_payment=ctx.mode_of_payment,
			cost_center=ctx.profile.cost_center if ctx.profile else None,
			custom_remarks=1,
			remarks=request.description,
		)
	)
	pe.set("references", refs)
	if kind == KINDS[0] and source.doctype == "Payment Entry":
		pe.custom_booking_invoice = source.get("custom_booking_invoice")
	return pe


def _employee_advance(request, ctx):
	if "hrms" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", "Employee Advance"):
		frappe.throw("سلف الموظفين تتطلب تثبيت HRMS وإعداد حساب سلف الموظفين؛ لا يمكن تسجيلها كمصروف.")
	employee = _read("Employee", request.party, ctx.company)
	if employee.status != "Active":
		frappe.throw("الموظف غير نشط.")
	if not request.employee_advance:
		advance = frappe.new_doc("Employee Advance")
		advance.update(
			dict(
				employee=employee.name,
				company=ctx.company,
				posting_date=request.posting_date,
				purpose=request.description,
				advance_amount=request.amount,
				currency=ctx.currency,
				exchange_rate=1,
				advance_account=frappe.get_cached_value(
					"Company", ctx.company, "default_employee_advance_account"
				),
			)
		)
		_account(advance.advance_account, ctx.company, ctx.currency)
		advance.insert()
		request.db_set("employee_advance", advance.name)
		_submit_if_authorized(advance)
	else:
		advance = _read("Employee Advance", request.employee_advance, ctx.company, lock=True)
	if advance.docstatus != 1:
		return None
	if (
		advance.employee != request.party
		or advance.currency != ctx.currency
		or request.amount > flt(advance.advance_amount) - flt(advance.paid_amount) + TOLERANCE
	):
		frappe.throw("السلفة مدفوعة أو رصيدها غير كافٍ.")
	_account(advance.advance_account, ctx.company, ctx.currency)
	from hrms.overrides.employee_payment_entry import get_payment_entry_for_employee

	return get_payment_entry_for_employee(
		"Employee Advance",
		advance.name,
		party_amount=request.amount,
		bank_account=ctx.payment_account,
		bank_amount=request.amount,
	)


def _expense(request, ctx):
	category = _read("Hala Expense Category", request.expense_category, ctx.company)
	if not category.enabled or request.amount > flt(category.maximum_amount):
		frappe.throw("فئة المصروف غير معتمدة أو المبلغ يتجاوز الحد المعتمد؛ استخدم مسار المشتريات.")
	account = _account(category.expense_account, ctx.company, ctx.currency)
	if account.root_type != "Expense":
		frappe.throw("الفئة لا ترتبط بحساب مصروفات.")
	_read("Cost Center", category.cost_center, ctx.company)
	je = frappe.new_doc("Journal Entry")
	je.update(
		dict(
			company=ctx.company,
			posting_date=request.posting_date,
			voucher_type="Cash Entry" if ctx.shift else "Bank Entry",
			user_remark=request.description,
			cheque_no=request.bank_reference,
			cheque_date=request.posting_date if request.bank_reference else None,
		)
	)
	for values in [
		dict(account=account.name, debit_in_account_currency=request.amount),
		dict(account=ctx.payment_account, credit_in_account_currency=request.amount),
	]:
		je.append("accounts", {**values, "cost_center": category.cost_center})
	return je


def _pay(request, ctx):
	if request.payment_name:
		doc = _read(request.payment_doctype, request.payment_name, request.company, lock=True)
		if doc.docstatus == 0:
			doc.posting_date = request.posting_date
			if doc.doctype == "Payment Entry":
				doc.reference_no = request.pos_opening_shift or request.bank_reference
				doc.reference_date = request.posting_date
				doc.custom_cashier_profile = request.pos_profile
			doc.save()
			_submit_if_authorized(doc)
		return _summary(request)
	doc = (
		_employee_advance(request, ctx)
		if request.kind == KINDS[2]
		else (_expense(request, ctx) if request.kind == KINDS[3] else _party_payment(request, ctx))
	)
	if doc is None:
		return _summary(request)
	doc.posting_date = request.posting_date
	doc.custom_hala_disbursement = request.name
	if doc.doctype == "Payment Entry":
		doc.mode_of_payment = ctx.mode_of_payment
		doc.reference_no = ctx.shift.name if ctx.shift else request.bank_reference
		doc.reference_date = request.posting_date
		doc.custom_cashier_profile = ctx.profile.name if ctx.profile else None
	doc.insert()
	request.db_set({"payment_doctype": doc.doctype, "payment_name": doc.name})
	_submit_if_authorized(doc)
	return _summary(request)


@frappe.whitelist()
def get_context(company=None, payment_account=None, mode_of_payment=None):
	require_access()
	if has_elevated_cashier_access() and not company:
		shift = _active_shift(required=False)
		if not shift:
			return {"accountant": True, "employee_supported": "hrms" in frappe.get_installed_apps()}
		ctx = _cashier_context(shift_data=shift)
	else:
		ctx = _context(company, payment_account, mode_of_payment)
	return dict(
		company=ctx.company,
		currency=ctx.currency,
		payment_account=ctx.payment_account,
		mode_of_payment=ctx.mode_of_payment,
		accountant=has_elevated_cashier_access(),
		employee_supported="hrms" in frappe.get_installed_apps(),
	)


@frappe.whitelist(methods=["POST"])
def create_voucher(data):
	require_access()
	data = frappe._dict(frappe.parse_json(data) if isinstance(data, str) else data)
	request_id = str(data.get("request_id") or "")
	if not request_id or len(request_id) > 80:
		frappe.throw("معرف طلب صالح مطلوب.")
	# Serialize retries for a user, including the first request before a voucher exists.
	frappe.db.sql("SELECT name FROM `tabUser` WHERE name=%s FOR UPDATE", frappe.session.user)
	existing = frappe.db.get_value("Hala Disbursement", {"request_id": request_id}, "name")
	if existing:
		request = _request(existing, lock=True)
		if request.owner != frappe.session.user:
			frappe.throw("معرف الطلب مستخدم.", frappe.PermissionError)
		return _summary(request)
	if data.kind not in KINDS:
		frappe.throw("نوع الصرف غير صالح.")
	ctx = _context(data.company, data.payment_account, data.mode_of_payment)
	if ctx.shift and getdate(data.posting_date or nowdate()) != getdate(nowdate()):
		frappe.throw("الصرف من الدرج يسجل بتاريخ اليوم فقط.")
	if not ctx.shift and data.bank_reference and frappe.db.exists("POS Opening Shift", data.bank_reference):
		frappe.throw("استخدم مرجعاً بنكياً حقيقياً وليس رقم وردية.")
	if not ctx.shift and not data.bank_reference:
		frappe.throw("رقم المرجع البنكي مطلوب.")
	description = str(data.description or "").strip()
	if not description or len(description) > 500:
		frappe.throw("أدخل بياناً لا يتجاوز 500 حرف.")
	beneficiary = str(data.beneficiary or "").strip()
	if data.kind != KINDS[3]:
		party_type = {KINDS[0]: "Customer", KINDS[1]: "Supplier", KINDS[2]: "Employee"}[data.kind]
		if party_type == "Employee" and "hrms" not in frappe.get_installed_apps():
			frappe.throw("سلف الموظفين تتطلب تثبيت HRMS وإعداد حساب السلف.")
		party_doc = _read(party_type, data.party, ctx.company if party_type == "Employee" else None)
		beneficiary = party_doc.get(party_type.lower() + "_name") or party_doc.name
	if not beneficiary or len(beneficiary) > 140:
		frappe.throw("المستفيد مطلوب ولا يتجاوز 140 حرفاً.")
	request = frappe.get_doc(
		dict(
			doctype="Hala Disbursement",
			request_id=request_id,
			kind=data.kind,
			company=ctx.company,
			posting_date=data.posting_date or nowdate(),
			currency=ctx.currency,
			amount=_amount(data.amount),
			party=data.party,
			beneficiary=beneficiary,
			description=description,
			source_doctype=data.source_doctype,
			source_name=data.source_name,
			expense_category=data.expense_category,
			payment_account=ctx.payment_account,
			mode_of_payment=ctx.mode_of_payment,
			bank_reference=data.bank_reference,
			pos_profile=ctx.profile.name if ctx.profile else None,
			pos_opening_shift=ctx.shift.name if ctx.shift else None,
			cashier=frappe.session.user,
		)
	)
	# A request is an audit envelope, not an accounting permission grant.
	request.insert(ignore_permissions=True)
	return _pay(request, ctx)


@frappe.whitelist(methods=["POST"])
def pay_voucher(name):
	request = _request(name, lock=True)
	if request.payment_name:
		payment = _read(request.payment_doctype, request.payment_name, request.company)
		if payment.docstatus != 0:
			return _summary(request)
	ctx = _context(request.company, request.payment_account, request.mode_of_payment)
	# Approval may take days. Assign the actual payment to today's current drawer.
	if request.cashier != frappe.session.user:
		frappe.throw("يجب أن ينفذ الدفع صاحب السند.", frappe.PermissionError)
	request.db_set(
		dict(
			posting_date=nowdate(),
			pos_profile=ctx.profile.name if ctx.profile else None,
			pos_opening_shift=ctx.shift.name if ctx.shift else None,
		)
	)
	return _pay(request, ctx)


@frappe.whitelist()
def get_voucher(name):
	return _summary(_request(name))


@frappe.whitelist()
def get_history(start=0):
	require_access()
	filters = {} if has_elevated_cashier_access() else {"cashier": frappe.session.user}
	rows = frappe.get_list(
		"Hala Disbursement",
		filters=filters,
		pluck="name",
		order_by="creation desc",
		start=max(int(start), 0),
		page_length=20,
	)
	return [_summary(_request(name)) for name in rows]


@frappe.whitelist()
def get_sources(kind, party, company):
	require_access()
	_read("Company", company)
	if kind == KINDS[0]:
		_read("Customer", party)
		rows = frappe.get_list(
			"Payment Entry",
			filters=dict(
				company=company,
				party_type="Customer",
				party=party,
				payment_type="Receive",
				docstatus=1,
				custom_is_deposit=0,
			),
			pluck="name",
			page_length=200,
		)
		result = []
		for name in rows:
			source = _read("Payment Entry", name, company)
			booking = source.get("custom_booking_invoice")
			if booking and frappe.db.get_value("Sales Invoice", booking, "docstatus") != 0:
				continue
			balance, account, _ = _source_balance(source)
			if balance > TOLERANCE:
				result.append(
					dict(
						doctype="Payment Entry",
						name=name,
						balance=balance,
						currency=source.paid_from_account_currency,
					)
				)
		for row in frappe.get_list(
			"Sales Invoice",
			filters=dict(
				company=company, customer=party, docstatus=1, is_return=1, outstanding_amount=["<", 0]
			),
			fields=["name", "outstanding_amount", "currency"],
			page_length=200,
		):
			result.append(
				dict(
					doctype="Sales Invoice",
					name=row.name,
					balance=-row.outstanding_amount,
					currency=row.currency,
				)
			)
		return result
	if kind == KINDS[1]:
		_read("Supplier", party)
		return [
			dict(
				doctype="Purchase Invoice",
				name=row.name,
				balance=row.outstanding_amount,
				currency=row.currency,
			)
			for row in frappe.get_list(
				"Purchase Invoice",
				filters=dict(
					company=company, supplier=party, docstatus=1, is_return=0, outstanding_amount=[">", 0]
				),
				fields=["name", "outstanding_amount", "currency"],
				page_length=200,
			)
		]
	return []


def validate_payment(doc, method=None):
	"""Enforce the envelope again for standard Desk/API submissions and edits."""
	if not frappe.get_meta(doc.doctype).has_field("custom_hala_disbursement"):
		return
	stored = (
		frappe.db.get_value(doc.doctype, doc.name, "custom_hala_disbursement") if not doc.is_new() else None
	)
	if stored and stored != doc.get("custom_hala_disbursement"):
		frappe.throw("لا يمكن تغيير ارتباط سند الصرف.")
	if not doc.get("custom_hala_disbursement"):
		return
	require_access()
	request = _request(doc.custom_hala_disbursement, lock=True)
	if request.payment_name and (request.payment_doctype != doc.doctype or request.payment_name != doc.name):
		frappe.throw("تم إنشاء مستند الدفع مسبقاً.")
	if doc.company != request.company or getdate(doc.posting_date) != getdate(request.posting_date):
		frappe.throw("الشركة أو التاريخ لا يطابق سند الصرف.")
	if doc.doctype == "Payment Entry":
		if (
			doc.payment_type != "Pay"
			or doc.paid_from != request.payment_account
			or abs(flt(doc.paid_amount) - request.amount) > TOLERANCE
			or abs(flt(doc.received_amount) - request.amount) > TOLERANCE
			or doc.mode_of_payment != request.mode_of_payment
			or doc.get("deductions")
		):
			frappe.throw("مستند الدفع لا يطابق سند الصرف.")
		if request.kind == KINDS[2]:
			expected = _employee_advance(
				request,
				frappe._dict(
					company=request.company,
					currency=request.currency,
					payment_account=request.payment_account,
				),
			)
			if expected is None:
				frappe.throw("السلفة لم تعتمد بعد.")
		else:
			expected = _party_payment(
				request,
				frappe._dict(
					company=request.company,
					currency=request.currency,
					payment_account=request.payment_account,
					mode_of_payment=request.mode_of_payment,
					profile=None,
				),
			)
		if (
			doc.party != expected.party
			or doc.party_type != expected.party_type
			or doc.paid_to != expected.paid_to
			or (doc.get("custom_booking_invoice") or None) != (expected.get("custom_booking_invoice") or None)
			or doc.get("custom_is_deposit")
			or (doc.get("custom_cashier_profile") or None) != (request.pos_profile or None)
			or doc.paid_from_account_currency != request.currency
			or doc.paid_to_account_currency != request.currency
			or flt(doc.source_exchange_rate) != 1
			or flt(doc.target_exchange_rate) != 1
			or doc.get("taxes")
		):
			frappe.throw("الطرف أو الحساب لا يطابق سند الصرف.")
		actual = [(r.reference_doctype, r.reference_name, flt(r.allocated_amount, 2)) for r in doc.references]
		target = [
			(r.reference_doctype, r.reference_name, flt(r.allocated_amount, 2)) for r in expected.references
		]
		if actual != target:
			frappe.throw("تغير رصيد المرجع؛ راجع السند قبل الاعتماد.")
	else:
		ctx = frappe._dict(
			company=request.company,
			currency=request.currency,
			payment_account=request.payment_account,
			shift=request.pos_opening_shift,
		)
		expected = _expense(request, ctx)
		actual = [
			(
				r.account,
				flt(r.debit_in_account_currency, 2),
				flt(r.credit_in_account_currency, 2),
				r.cost_center,
				r.party_type or None,
				r.party or None,
				r.reference_type or None,
				r.reference_name or None,
			)
			for r in doc.accounts
		]
		target = [
			(
				r.account,
				flt(r.debit_in_account_currency, 2),
				flt(r.credit_in_account_currency, 2),
				r.cost_center,
				r.party_type or None,
				r.party or None,
				r.reference_type or None,
				r.reference_name or None,
			)
			for r in expected.accounts
		]
		if actual != target:
			frappe.throw("القيد لا يطابق فئة المصروف المعتمدة.")
	if method == "before_submit":
		if request.payment_name != doc.name or request.payment_doctype != doc.doctype:
			frappe.throw("مستند الدفع غير مرتبط بسند الصرف.")
		if request.cashier != frappe.session.user:
			if not has_elevated_cashier_access() or not _workflow(doc.doctype):
				frappe.throw(
					"اعتماد دفع كاشير آخر يتطلب محاسباً مخولاً ومسار موافقات معتمداً.", frappe.PermissionError
				)
			if request.pos_opening_shift:
				from hala.cashier_profile import get_current_cashier_context

				ctx = _cashier_context(shift_data=get_current_cashier_context(user=request.cashier))
				_validate_drawer(ctx, request.cashier)
				if (
					ctx.payment_account != request.payment_account
					or ctx.company != request.company
					or ctx.mode_of_payment != request.mode_of_payment
				):
					frappe.throw("تغير إعداد درج الكاشير؛ راجع السند قبل الاعتماد.")
			else:
				ctx = _context(request.company, request.payment_account, request.mode_of_payment)
		else:
			ctx = _context(request.company, request.payment_account, request.mode_of_payment)
		if (ctx.shift.name if ctx.shift else None) != request.pos_opening_shift:
			frappe.throw("أعد تنفيذ الدفع من سند الصرف في ورديتك الحالية.")
		if doc.doctype == "Payment Entry" and doc.reference_no != (
			request.pos_opening_shift or request.bank_reference
		):
			frappe.throw("مرجع الدفع لا يطابق الوردية / المرجع البنكي.")


def query_conditions(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if not roles.intersection({ROLE, "System Manager"}):
		return "1=0"
	from hala.cashier_profile import has_elevated_cashier_access

	if not has_elevated_cashier_access(user):
		return f"`tabHala Disbursement`.cashier = {frappe.db.escape(user)}"


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if not set(frappe.get_roles(user)).intersection({ROLE, "System Manager"}):
		return False
	return has_elevated_cashier_access(user) or doc.cashier == user


def get_expense_cash_movements(closing_shift):
	"""Closing-only adapter. Submitted standard JEs are the source of truth."""
	if not frappe.db.has_column("Journal Entry", "custom_hala_disbursement"):
		return []
	return frappe.db.sql(
		"""SELECT je.name, je.posting_date, req.mode_of_payment, req.payment_account,
		SUM(line.credit - line.debit) AS amount
		FROM `tabJournal Entry` je
		JOIN `tabHala Disbursement` req ON req.name=je.custom_hala_disbursement
		AND req.payment_name=je.name AND req.payment_doctype='Journal Entry'
		JOIN `tabJournal Entry Account` line ON line.parent=je.name AND line.account=req.payment_account
		JOIN `tabAccount` account ON account.name=line.account AND account.account_type='Cash'
		WHERE je.docstatus=1 AND je.company=%s AND req.company=je.company
		AND req.pos_opening_shift=%s AND req.pos_profile=%s AND req.cashier=%s
		AND req.kind=%s GROUP BY je.name, je.posting_date, req.mode_of_payment, req.payment_account
		HAVING amount>0""",
		(
			closing_shift.company,
			closing_shift.pos_opening_shift,
			closing_shift.pos_profile,
			closing_shift.user,
			KINDS[3],
		),
		as_dict=True,
	)


@frappe.whitelist()
def get_print_options(name):
	request = _request(name)
	if not _summary(request)["paid"]:
		frappe.throw("الطباعة متاحة لسندات الصرف المدفوعة فقط.")
	doc = _read(request.payment_doctype, request.payment_name, request.company)
	doc.check_permission("print")
	return dict(
		doctype=doc.doctype,
		name=doc.name,
		pos_profile=request.pos_profile,
		print_format="Hala Disbursement Payment"
		if doc.doctype == "Payment Entry"
		else "Hala Disbursement Expense",
	)


def disbursement_print_data(doc):
	request = _request(doc.get("custom_hala_disbursement"))
	if doc.docstatus != 1 or request.payment_doctype != doc.doctype or request.payment_name != doc.name:
		frappe.throw("سند الصرف غير مدفوع أو ملغى.")
	return request


def reconcile_customer_refund(doc, method=None):
	if not doc.get("custom_hala_disbursement"):
		return
	request = _request(doc.custom_hala_disbursement, lock=True)
	if request.kind != KINDS[0] or request.source_doctype != "Payment Entry":
		return
	frappe.has_permission("Payment Reconciliation", "write", throw=True)
	source = _read("Payment Entry", request.source_name, request.company, lock=True)
	source.check_permission("write")
	from erpnext.accounts.utils import reconcile_against_document

	reconcile_against_document(
		[
			frappe._dict(
				voucher_type="Payment Entry",
				voucher_no=source.name,
				voucher_detail_no=None,
				against_voucher_type="Payment Entry",
				against_voucher=doc.name,
				account=doc.paid_to,
				party_type="Customer",
				party=doc.party,
				is_advance="Yes",
				dr_or_cr="credit_in_account_currency",
				unreconciled_amount=source.unallocated_amount,
				unadjusted_amount=source.unallocated_amount,
				allocated_amount=request.amount,
				difference_amount=0,
				exchange_rate=1,
				grand_total=request.amount,
				outstanding_amount=request.amount,
				difference_account=None,
				difference_posting_date=doc.posting_date,
				cost_center=doc.cost_center,
				dimensions={},
			)
		]
	)
