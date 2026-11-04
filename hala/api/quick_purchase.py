"""A simplified view of the native Purchase Invoice form, not a payment controller."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe.utils import cint, flt

from hala.api.booking import _active_shift
from hala.api.deposit import _cashier_context

ROLES = {"Purchase Manager", "System Manager"}


def require_access(permission="read", doc=None):
	if frappe.session.user == "Guest" or not set(frappe.get_roles()).intersection(ROLES):
		frappe.throw("هذه الشاشة متاحة لمدير المشتريات ومدير النظام فقط.", frappe.PermissionError)
	frappe.has_permission("Purchase Invoice", permission, doc=doc, throw=True)


def _read(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return doc


def _company(company):
	if company:
		return _read("Company", company)


def _purchase_drawer_context(shift_data, required=True):
	"""Choose the profile's cash drawer, even when its default sale mode is a card."""
	profile = shift_data["pos_profile"]
	configured = profile.get("posa_cash_mode_of_payment")
	cash_rows = [
		row
		for row in profile.payments
		if frappe.get_cached_value("Mode of Payment", row.mode_of_payment, "type") == "Cash"
	]
	selected = (
		next((row for row in cash_rows if row.mode_of_payment == configured), None) if configured else None
	)
	if not configured:
		selected = next((row for row in cash_rows if cint(row.get("default"))), None)
		if not selected and len(cash_rows) == 1:
			selected = cash_rows[0]
	if not selected:
		if required:
			frappe.throw("حدد طريقة الدفع النقدي المعتمدة في ملف الكاشير.")
		return None
	# A private in-memory view lets the existing helper resolve the configured
	# Cash mode. It never changes the POS Profile or its normal sale defaults.
	view = frappe._dict(profile.as_dict())
	view.payments = [
		frappe._dict(row.as_dict(), default=int(row.name == selected.name)) for row in profile.payments
	]
	return _cashier_context(
		shift_data={"pos_opening_shift": shift_data["pos_opening_shift"], "pos_profile": view}
	)


@frappe.whitelist()
def get_context():
	require_access()
	shift = _active_shift(required=False)
	company = shift["pos_profile"].company if shift else frappe.defaults.get_user_default("Company")
	_company(company)
	drawer = _purchase_drawer_context(shift, required=False) if shift else None
	return {
		"company": company,
		"can_create": frappe.has_permission("Purchase Invoice", "create"),
		"workflow": bool(
			frappe.db.get_value("Workflow", {"document_type": "Purchase Invoice", "is_active": 1}, "name")
		),
		"drawer": dict(account=drawer.payment_account, mode_of_payment=drawer.mode_of_payment)
		if drawer
		else None,
	}


@frappe.whitelist()
def get_history(start=0):
	require_access()
	rows = frappe.get_list(
		"Purchase Invoice",
		fields=[
			"name",
			"supplier",
			"supplier_name",
			"posting_date",
			"grand_total",
			"currency",
			"is_paid",
			"paid_amount",
			"outstanding_amount",
			"owner",
			"docstatus",
			"status",
		],
		order_by="creation desc",
		start=max(cint(start), 0),
		page_length=20,
	)
	return rows


@frappe.whitelist()
def get_invoice(name):
	require_access()
	doc = _read("Purchase Invoice", name)
	_company(doc.company)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"can_write": doc.docstatus == 0 and frappe.has_permission(doc.doctype, "write", doc),
	}


@frappe.whitelist()
def find_request(request_id):
	require_access()
	name = frappe.db.get_value(
		"Purchase Invoice", {"custom_hala_purchase_request_id": str(request_id)[:80]}, "name"
	)
	return get_invoice(name) if name else None


@frappe.whitelist()
def get_item_uoms(item_code):
	require_access()
	item = _read("Item", item_code)
	if item.disabled or not item.is_purchase_item:
		frappe.throw("الصنف غير متاح للشراء.")
	uoms = {item.stock_uom: 1.0}
	for row in item.get("uoms") or []:
		if flt(row.conversion_factor) > 0:
			uoms[row.uom] = flt(row.conversion_factor)
	if item.purchase_uom and item.purchase_uom not in uoms:
		frappe.throw("وحدة الشراء غير مهيأة ضمن وحدات الصنف.")
	return {
		"stock_uom": item.stock_uom,
		"is_stock_item": bool(item.is_stock_item),
		"purchase_uom": item.purchase_uom or item.stock_uom,
		"uoms": uoms,
	}


@frappe.whitelist()
def derive_rate(qty, amount, currency=None):
	"""Precision-aware UI helper; the native controller still calculates/stores amount."""
	require_access()
	try:
		quantity, total = Decimal(str(qty)), Decimal(str(amount))
	except (InvalidOperation, ValueError):
		frappe.throw("أدخل كمية ومبلغاً صالحين.")
	if not quantity.is_finite() or not total.is_finite() or quantity <= 0 or total < 0:
		frappe.throw("الكمية يجب أن تكون موجبة والمبلغ غير سالب.")
	doc = frappe.new_doc("Purchase Invoice")
	doc.currency = currency or frappe.defaults.get_user_default("Currency")
	row = doc.append("items", {})
	rate_precision, amount_precision = row.precision("rate"), row.precision("amount")
	quantum = Decimal(1).scaleb(-amount_precision)
	if total != total.quantize(quantum, rounding=ROUND_HALF_UP):
		frappe.throw("دقة المبلغ تتجاوز الدقة المحاسبية للعملة.")
	rate = (total / quantity).quantize(Decimal(1).scaleb(-rate_precision), rounding=ROUND_HALF_UP)
	actual = (rate * quantity).quantize(quantum, rounding=ROUND_HALF_UP)
	if actual != total:
		frappe.throw(
			"لا يمكن تمثيل الإجمالي بهذه الكمية ودقة سعر الوحدة؛ عدل الكمية أو الإجمالي أو أدخل السعر مباشرة."
		)
	return {
		"rate": float(rate),
		"amount": float(actual),
		"rate_precision": rate_precision,
		"amount_precision": amount_precision,
	}


@frappe.whitelist()
def get_print_options(name):
	require_access()
	doc = _read("Purchase Invoice", name)
	_company(doc.company)
	doc.check_permission("print")
	if doc.docstatus != 1:
		frappe.throw("اعتمد الفاتورة قبل طباعتها من الشاشة المبسطة.")
	return dict(
		name=doc.name,
		print_format=frappe.get_meta("Purchase Invoice").default_print_format or "Standard",
		letterhead=doc.get("letter_head"),
		pos_profile=doc.get("custom_hala_purchase_profile"),
	)


def _drawer_accounts(company):
	# Cash accounts configured on POS Profiles are drawers, not unassigned petty cash.
	return set(
		row[0]
		for row in frappe.db.sql(
			"""SELECT DISTINCT mpa.default_account
		FROM `tabPOS Payment Method` method JOIN `tabPOS Profile` profile ON profile.name=method.parent
		JOIN `tabMode of Payment Account` mpa ON mpa.parent=method.mode_of_payment AND mpa.company=profile.company
		JOIN `tabAccount` account ON account.name=mpa.default_account AND account.account_type='Cash'
		WHERE profile.company=%s AND profile.disabled=0""",
			company,
		)
	)


def validate_native_form(doc, method=None):
	"""Guard the simplified entry point and attach provenance; never post a payment."""
	if not doc.meta.has_field("custom_hala_quick_purchase"):
		return
	stored = (
		frappe.db.get_value("Purchase Invoice", doc.name, "custom_hala_quick_purchase")
		if not doc.is_new()
		else None
	)
	if stored and not doc.get("custom_hala_quick_purchase"):
		frappe.throw("لا يمكن إزالة علامة الفاتورة المبسطة.")
	if not doc.get("custom_hala_quick_purchase"):
		return
	require_access("create" if doc.is_new() else "write", doc)
	_company(doc.company)
	_read("Supplier", doc.supplier)
	if doc.is_return:
		frappe.throw("استخدم شاشة المرتجع القياسية للمردودات.")
	if method == "before_submit":
		workflow_name = frappe.db.get_value(
			"Workflow", {"document_type": "Purchase Invoice", "is_active": 1}, "name"
		)
		if workflow_name:
			workflow = frappe.get_doc("Workflow", workflow_name)
			approved_states = {row.state for row in workflow.states if cint(row.doc_status) == 1}
			if doc.get(workflow.workflow_state_field) not in approved_states:
				frappe.throw("الفاتورة بانتظار الموافقة؛ استخدم إجراء مسار العمل المعتمد.")
	request_id = str(doc.get("custom_hala_purchase_request_id") or "")
	if not request_id or len(request_id) > 80:
		frappe.throw("معرف طلب الفاتورة مطلوب لمنع التكرار.")
	if not doc.is_new():
		old = frappe.db.get_value("Purchase Invoice", doc.name, "custom_hala_purchase_request_id")
		if old and old != request_id:
			frappe.throw("لا يمكن تغيير معرف الطلب.")
	if doc.get("custom_hala_supplier_payment"):
		frappe.throw("تستخدم الشاشة المبسطة خيار مدفوعة القياسي فقط؛ لا تجمعه مع دفعة المورد المنفصلة.")
	for row in doc.items if method != "before_validate" else []:
		if flt(row.qty) <= 0:
			frappe.throw("كمية الصنف يجب أن تكون أكبر من صفر.")
		units = get_item_uoms(row.item_code)["uoms"]
		if row.uom not in units:
			frappe.throw("اختر وحدة من وحدات الصنف المهيأة فقط.")
		if flt(row.conversion_factor) != flt(units[row.uom]):
			frappe.throw("معامل التحويل لا يطابق إعدادات الصنف.")
		if row.warehouse:
			warehouse = _read("Warehouse", row.warehouse)
			if warehouse.company != doc.company:
				frappe.throw("المستودع لا يتبع شركة الفاتورة.", frappe.PermissionError)
	# Optional, non-persisted UI intent. Compare after native calculations, never override them.
	expected = doc.get("hala_expected_item_amounts")
	if method == "validate" and expected is not None:
		if not isinstance(expected, list) or len(expected) != len(doc.items):
			frappe.throw("تغيرت صفوف الفاتورة؛ راجع المجاميع قبل الحفظ.")
		for row, amount in zip(doc.items, expected):
			if flt(row.amount, row.precision("amount")) != flt(amount, row.precision("amount")):
				frappe.throw("اختلف إجمالي السطر بعد حسابات ERPNext؛ راجع السعر والكمية والخصم قبل الحفظ.")
	if not doc.is_paid:
		if flt(doc.paid_amount):
			frappe.throw("ألغ المبلغ المدفوع عند إلغاء خيار مدفوعة.")
		for field in (
			"custom_hala_purchase_shift",
			"custom_hala_purchase_profile",
			"custom_hala_purchase_cashier",
		):
			doc.set(field, None)
		return
	if not doc.mode_of_payment or not doc.cash_bank_account:
		frappe.throw("اختر طريقة الدفع وحساب النقد / البنك.")
	_read("Mode of Payment", doc.mode_of_payment)
	account = _read("Account", doc.cash_bank_account)
	if (
		account.company != doc.company
		or account.is_group
		or account.disabled
		or account.account_type not in ("Cash", "Bank")
	):
		frappe.throw("اختر حساب نقد أو بنك صالحاً للشركة.")
	# The simplified view must never be routed into Hala's separate overpayment helper.
	if flt(doc.paid_amount) > flt(doc.rounded_total or doc.grand_total) and flt(doc.grand_total) > 0:
		frappe.throw("المبلغ المدفوع يتجاوز الإجمالي؛ استخدم المبلغ القياسي الصحيح دون دفعة منفصلة.")
	for field in (
		"custom_hala_purchase_shift",
		"custom_hala_purchase_profile",
		"custom_hala_purchase_cashier",
	):
		doc.set(field, None)
	if account.account_type == "Cash" and account.name in _drawer_accounts(doc.company):
		shift_data = _active_shift(required=True)
		ctx = _purchase_drawer_context(shift_data)
		from hala.api.disbursement import _validate_drawer

		_validate_drawer(ctx, frappe.session.user)
		if (
			ctx.company != doc.company
			or ctx.payment_account != account.name
			or ctx.mode_of_payment != doc.mode_of_payment
		):
			frappe.throw("لا يمكن الدفع من درج كاشير آخر أو بطريقة غير معتمدة.", frappe.PermissionError)
		doc.custom_hala_purchase_shift = ctx.shift.name
		doc.custom_hala_purchase_profile = ctx.profile.name
		doc.custom_hala_purchase_cashier = frappe.session.user


def get_purchase_cash_movements(closing_shift):
	"""Read the native invoice's submitted cash credit, with no extra posting."""
	if not frappe.db.has_column("Purchase Invoice", "custom_hala_purchase_shift"):
		return []
	return frappe.db.sql(
		"""SELECT pi.name, 'Purchase Invoice' AS doctype, pi.posting_date,
		pi.mode_of_payment, pi.cash_bank_account AS payment_account,
		SUM(gl.credit-gl.debit) AS amount
		FROM `tabPurchase Invoice` pi JOIN `tabGL Entry` gl ON gl.voucher_type='Purchase Invoice'
		AND gl.voucher_no=pi.name AND gl.account=pi.cash_bank_account AND gl.is_cancelled=0
		JOIN `tabAccount` account ON account.name=pi.cash_bank_account AND account.account_type='Cash'
		WHERE pi.docstatus=1 AND pi.is_paid=1 AND pi.custom_hala_quick_purchase=1
		AND pi.company=%s AND gl.company=pi.company AND pi.custom_hala_purchase_shift=%s
		AND pi.custom_hala_purchase_profile=%s AND pi.custom_hala_purchase_cashier=%s
		GROUP BY pi.name, pi.posting_date, pi.mode_of_payment, pi.cash_bank_account HAVING amount>0""",
		(
			closing_shift.company,
			closing_shift.pos_opening_shift,
			closing_shift.pos_profile,
			closing_shift.user,
		),
		as_dict=True,
	)
