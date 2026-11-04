import frappe
from frappe.model.document import Document
from frappe.utils import flt


class HalaExpenseCategory(Document):
	def validate(self):
		account = frappe.get_doc("Account", self.expense_account)
		center = frappe.get_doc("Cost Center", self.cost_center)
		if (
			account.company != self.company
			or account.root_type != "Expense"
			or account.is_group
			or account.disabled
		):
			frappe.throw("اختر حساب مصروفات صالحاً للشركة.")
		if center.company != self.company or center.is_group or flt(self.maximum_amount) <= 0:
			frappe.throw("يلزم مركز تكلفة صالح وحد أقصى موجب.")
