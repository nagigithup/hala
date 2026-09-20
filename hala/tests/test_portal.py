import frappe
from frappe import PermissionError, ValidationError
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate, set_request
from frappe.website.serve import get_response_content
from frappe.website.path_resolver import resolve_path

from hala.api.portal import DOCTYPE_CONFIG, boot, document_action, get_form_schema, save_document


class TestHalaPortal(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_boot_uses_standard_doctypes(self):
		data = boot()
		self.assertIn("Item", data["doctypes"])
		self.assertTrue(data["permissions"]["Item"]["read"])

	def test_all_configured_doctypes_exist(self):
		missing = [doctype for doctype in DOCTYPE_CONFIG if not frappe.db.exists("DocType", doctype)]
		self.assertEqual(missing, [])

	def test_journal_entry_schema_has_accounts(self):
		schema = get_form_schema("Journal Entry")
		accounts = next(field for field in schema["fields"] if field["fieldname"] == "accounts")
		self.assertIn("debit_in_account_currency", [field["fieldname"] for field in accounts["children"]])
		self.assertIn("credit_in_account_currency", [field["fieldname"] for field in accounts["children"]])

	def test_portal_role_has_no_automatic_business_permissions(self):
		self.assertFalse(
			frappe.db.exists("Custom DocPerm", {"role": "Hala Portal User"}),
			"Portal access role must not grant blanket ERP permissions",
		)

	def test_guest_cannot_boot_portal(self):
		frappe.set_user("Guest")
		with self.assertRaises(PermissionError):
			boot()

	def test_hala_page_and_nested_route_render_for_authorized_user(self):
		content = get_response_content("/hala")
		self.assertIn('id="hala-app"', content)
		set_request(path="/hala/list/Item")
		self.assertEqual(resolve_path("hala/list/Item"), "hala")
		nested = get_response_content(resolve_path("hala/list/Item"))
		self.assertIn('id="hala-app"', nested)

	def test_portal_role_does_not_imply_item_access(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"hala-no-erp-{frappe.generate_hash(length=8)}@example.com",
				"first_name": "Hala",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles("Hala Portal User")
		frappe.set_user(user.name)
		data = boot()
		self.assertFalse(data["permissions"]["Item"]["read"])
		self.assertFalse(data["permissions"]["Journal Entry"]["create"])

	def test_item_draft_is_created_through_standard_item_controller(self):
		item_code = frappe.generate_hash(length=10)
		result = save_document(
			{
				"doctype": "Item",
				"item_code": f"HALA-TEST-{item_code}",
				"item_name": "Hala Portal Test Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		)
		self.assertTrue(frappe.db.exists("Item", result["doc"]["name"]))

	def test_balanced_journal_entry_draft_and_unbalanced_rejection(self):
		balanced = {
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": "alnagi",
			"posting_date": nowdate(),
			"accounts": [
				{"doctype": "Journal Entry Account", "account": "Cash - A", "debit_in_account_currency": 10},
				{"doctype": "Journal Entry Account", "account": "Sales - A", "credit_in_account_currency": 10},
			],
		}
		result = save_document(balanced)
		self.assertEqual(result["doc"]["docstatus"], 0)
		unbalanced = dict(balanced)
		unbalanced["accounts"] = [
			{"doctype": "Journal Entry Account", "account": "Cash - A", "debit_in_account_currency": 10},
			{"doctype": "Journal Entry Account", "account": "Sales - A", "credit_in_account_currency": 9},
		]
		unbalanced_result = save_document(unbalanced)
		with self.assertRaises(ValidationError):
			document_action("Journal Entry", unbalanced_result["doc"]["name"], "submit")
