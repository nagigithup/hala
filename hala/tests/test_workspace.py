import json
from pathlib import Path

import frappe
from frappe.boot import get_sidebar_items
from frappe.tests import IntegrationTestCase

from hala import hooks
from hala.access import PORTAL_ROLE


WORKSPACE_FILE = (
	Path(__file__).resolve().parents[1]
	/ "hala"
	/ "workspace"
	/ "hala"
	/ "hala.json"
)
SIDEBAR_FILE = Path(__file__).resolve().parents[1] / "workspace_sidebar" / "hala.json"
DESKTOP_ICON_FILE = Path(__file__).resolve().parents[1] / "desktop_icon" / "hala.json"


class TestHalaWorkspace(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_workspace_is_public_standard_and_source_controlled(self):
		self.assertTrue(WORKSPACE_FILE.exists())
		source = json.loads(WORKSPACE_FILE.read_text())
		self.assertEqual(source["name"], "Hala")
		self.assertEqual(source["module"], "Hala")
		self.assertEqual(source["app"], "hala")
		self.assertEqual(source["public"], 1)
		self.assertEqual(source["icon"], "store")
		json.loads(source["content"])

		workspace = frappe.get_doc("Workspace", "Hala")
		self.assertEqual(workspace.module, "Hala")
		self.assertEqual(workspace.app, "hala")
		self.assertEqual(workspace.public, 1)
		self.assertEqual(workspace.is_hidden, 0)

	def test_workspace_roles_do_not_grant_business_permissions(self):
		workspace = frappe.get_doc("Workspace", "Hala")
		self.assertEqual({row.role for row in workspace.roles}, {"System Manager", "Hala Portal User"})
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"role": "Hala Portal User"}))

	def test_apps_screen_opens_native_workspace(self):
		hala_entry = next(entry for entry in hooks.add_to_apps_screen if entry["name"] == "hala")
		self.assertEqual(hala_entry["route"], "/desk/hala")

		icon = frappe.get_doc("Desktop Icon", "Hala")
		self.assertEqual(icon.link_type, "Workspace Sidebar")
		self.assertEqual(icon.link_to, "Hala")
		self.assertEqual(icon.logo_url, "/assets/hala/hala-logo.svg")
		self.assertEqual(icon.standard, 1)

	def test_native_sidebar_is_source_controlled_and_collapsible(self):
		self.assertTrue(SIDEBAR_FILE.exists())
		self.assertTrue(DESKTOP_ICON_FILE.exists())
		source = json.loads(SIDEBAR_FILE.read_text())
		self.assertEqual(source["app"], "hala")
		self.assertEqual(source["module"], "Hala")
		self.assertEqual(source["standard"], 1)

		sections = [item for item in source["items"] if item["type"] == "Section Break"]
		self.assertEqual(
			[item["label"] for item in sections],
			[
				"Home",
				"Items and Stock",
				"Manufacturing",
				"Customers and Sales",
				"Suppliers and Purchasing",
				"Finance",
			],
		)
		self.assertTrue(all(item["collapsible"] for item in sections))
		self.assertTrue(all(item["indent"] for item in sections))

	def test_native_sidebar_targets_exist(self):
		sidebar = frappe.get_doc("Workspace Sidebar", "Hala")
		for item in sidebar.items:
			if item.type != "Link" or item.link_type == "URL":
				continue
			self.assertTrue(
				frappe.db.exists(item.link_type, item.link_to),
				f"Missing sidebar {item.link_type} target: {item.link_to}",
			)

	def test_sidebar_uses_native_permission_filtered_links(self):
		sidebar = frappe.get_doc("Workspace Sidebar", "Hala")
		self.assertFalse(any(item.link_type == "URL" for item in sidebar.items))
		self.assertEqual(sidebar.items[1].link_type, "Workspace")
		self.assertEqual(sidebar.items[1].link_to, "Hala")

	def test_sidebar_hides_business_links_without_erpnext_permissions(self):
		user_email = "_test_hala_sidebar@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": user_email,
				"first_name": "Hala Sidebar Test",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles(PORTAL_ROLE)

		try:
			frappe.set_user(user_email)
			frappe.clear_cache(user=user_email)
			items = get_sidebar_items(["Hala"])["hala"]["items"]
			visible_targets = {item["link_to"] for item in items if item["type"] == "Link"}
			self.assertIn("Hala", visible_targets)
			self.assertNotIn("Item", visible_targets)
			self.assertNotIn("Journal Entry", visible_targets)
		finally:
			frappe.set_user("Administrator")

	def test_every_workspace_link_target_exists(self):
		workspace = frappe.get_doc("Workspace", "Hala")
		for link in workspace.links:
			if link.type == "Card Break":
				continue
			self.assertTrue(
				frappe.db.exists(link.link_type, link.link_to),
				f"Missing {link.link_type} target: {link.link_to}",
			)

	def test_content_references_existing_workspace_components(self):
		workspace = frappe.get_doc("Workspace", "Hala")
		content = json.loads(workspace.content)
		shortcuts = {row.label for row in workspace.shortcuts}
		cards = {row.label for row in workspace.links if row.type == "Card Break"}
		number_cards = {row.number_card_name for row in workspace.number_cards}
		for block in content:
			data = block.get("data", {})
			if block["type"] == "shortcut":
				self.assertIn(data["shortcut_name"], shortcuts)
			elif block["type"] == "card":
				self.assertIn(data["card_name"], cards)
			elif block["type"] == "number_card":
				self.assertIn(data["number_card_name"], number_cards)

	def test_number_cards_are_standard_and_permission_aware(self):
		workspace = frappe.get_doc("Workspace", "Hala")
		self.assertEqual(len(workspace.number_cards), 8)
		for row in workspace.number_cards:
			card = frappe.get_doc("Number Card", row.number_card_name)
			self.assertEqual(card.module, "Hala")
			self.assertEqual(card.is_public, 1)
			self.assertEqual(card.is_standard, 1)
			self.assertTrue(frappe.has_permission(card.document_type, "read"))
