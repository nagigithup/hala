from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from hala.api.item_price_manager import get_price_matrix, save_prices


class TestItemPriceManager(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.currency = (
			frappe.db.get_single_value("Global Defaults", "default_currency")
			or frappe.db.get_value("Currency", {}, "name")
		)
		self.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		self.uom = frappe.db.get_value("UOM", {}, "name")

	def make_item(self, label="Item", item_group=None):
		item_code = f"_Test Hala IPM {label} {self.suffix}"
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"description": item_code,
				"item_group": item_group or self.item_group,
				"stock_uom": self.uom,
				"is_stock_item": 0,
			}
		).insert()

	def make_price_list(self, label="Retail"):
		name = f"_Test Hala IPM {label} {self.suffix}"
		return frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": name,
				"currency": self.currency,
				"enabled": 1,
				"selling": 1,
				"buying": 0,
			}
		).insert()

	def make_item_price(self, item, price_list, rate):
		return frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item.name,
				"price_list": price_list.name,
				"uom": item.stock_uom,
				"currency": price_list.currency,
				"price_list_rate": rate,
				"valid_from": nowdate(),
			}
		).insert()

	@staticmethod
	def change(item, price_list, rate, item_price=None):
		return {
			"item_code": item.name,
			"price_list": price_list.name,
			"uom": item.stock_uom,
			"price_list_rate": rate,
			"item_price": item_price.name if item_price else None,
			"modified": str(item_price.modified) if item_price else None,
		}

	def test_existing_item_price_is_updated(self):
		item = self.make_item()
		price_list = self.make_price_list()
		item_price = self.make_item_price(item, price_list, 100)

		result = save_prices([self.change(item, price_list, 110, item_price)])

		self.assertEqual(result, {"created": 0, "updated": 1, "unchanged": 0})
		self.assertEqual(frappe.db.get_value("Item Price", item_price.name, "price_list_rate"), 110)

	def test_missing_item_price_is_created(self):
		item = self.make_item()
		price_list = self.make_price_list()

		result = save_prices([self.change(item, price_list, 75)])

		self.assertEqual(result, {"created": 1, "updated": 0, "unchanged": 0})
		created = frappe.get_last_doc(
			"Item Price", filters={"item_code": item.name, "price_list": price_list.name}
		)
		self.assertEqual(created.uom, item.stock_uom)
		self.assertEqual(created.currency, price_list.currency)
		self.assertEqual(created.price_list_rate, 75)

	def test_missing_client_reference_reuses_a_current_item_price(self):
		item = self.make_item()
		price_list = self.make_price_list()
		item_price = self.make_item_price(item, price_list, 60)

		result = save_prices([self.change(item, price_list, 65)])

		self.assertEqual(result, {"created": 0, "updated": 1, "unchanged": 0})
		self.assertEqual(
			frappe.db.count(
				"Item Price",
				{"item_code": item.name, "price_list": price_list.name, "uom": item.stock_uom},
			),
			1,
		)
		self.assertEqual(frappe.db.get_value("Item Price", item_price.name, "price_list_rate"), 65)

	def test_multiple_items_and_price_lists_save_in_one_batch(self):
		item_one = self.make_item("One")
		item_two = self.make_item("Two")
		retail = self.make_price_list("Retail")
		dealer = self.make_price_list("Dealer")
		existing = self.make_item_price(item_one, retail, 10)

		result = save_prices(
			[
				self.change(item_one, retail, 11, existing),
				self.change(item_one, dealer, 9),
				self.change(item_two, retail, 20),
			]
		)

		self.assertEqual(result, {"created": 2, "updated": 1, "unchanged": 0})
		for item, price_list, expected in (
			(item_one, retail, 11),
			(item_one, dealer, 9),
			(item_two, retail, 20),
		):
			self.assertEqual(
				frappe.db.get_value(
					"Item Price", {"item_code": item.name, "price_list": price_list.name}, "price_list_rate"
				),
				expected,
			)

	def test_unchanged_price_is_not_written(self):
		item = self.make_item()
		price_list = self.make_price_list()
		item_price = self.make_item_price(item, price_list, 100)
		modified_before = item_price.modified

		result = save_prices([self.change(item, price_list, 100, item_price)])

		self.assertEqual(result, {"created": 0, "updated": 0, "unchanged": 1})
		self.assertEqual(str(frappe.db.get_value("Item Price", item_price.name, "modified")), modified_before)

	def test_invalid_price_is_rejected_without_writes(self):
		item = self.make_item()
		price_list = self.make_price_list()

		with self.assertRaises(frappe.ValidationError):
			save_prices([self.change(item, price_list, -1)])

		self.assertFalse(
			frappe.db.exists("Item Price", {"item_code": item.name, "price_list": price_list.name})
		)

	def test_user_without_item_price_permission_cannot_save(self):
		item = self.make_item()
		price_list = self.make_price_list()
		user_email = f"hala-ipm-{self.suffix}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": user_email,
				"first_name": "Hala Item Price Read Only",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		try:
			frappe.set_user(user.name)
			with self.assertRaises(frappe.PermissionError):
				save_prices([self.change(item, price_list, 50)])
		finally:
			frappe.set_user("Administrator")

	def test_read_only_permission_state_can_view_the_matrix(self):
		item = self.make_item()
		price_list = self.make_price_list()
		original_has_permission = frappe.has_permission

		def permission_check(doctype=None, ptype="read", *args, **kwargs):
			if doctype == "Item Price" and ptype in {"write", "create"}:
				return False
			return original_has_permission(doctype, ptype, *args, **kwargs)

		with patch("frappe.has_permission", side_effect=permission_check):
			matrix = get_price_matrix(search=item.name, page_length=25)

		self.assertEqual(matrix["items"][0].item_code, item.name)
		self.assertIn(price_list.name, [row.name for row in matrix["price_lists"]])
		self.assertEqual(matrix["permissions"], {"can_write": False, "can_create": False})

	def test_matrix_supports_item_group_search_and_pagination(self):
		items = [self.make_item(f"{self.suffix} Search {index}") for index in range(3)]
		price_list = self.make_price_list()
		price = self.make_item_price(items[0], price_list, 123)

		first_page = get_price_matrix(
			search=f"_Test Hala IPM {self.suffix} Search",
			item_group=self.item_group,
			start=0,
			page_length=2,
		)
		self.assertEqual(len(first_page["items"]), 2)
		self.assertTrue(first_page["pagination"]["has_more"])
		self.assertTrue(all(row.item_group == self.item_group for row in first_page["items"]))

		priced_cell = first_page["prices"].get(items[0].name, {}).get(price_list.name)
		if priced_cell:
			self.assertEqual(priced_cell["name"], price.name)
			self.assertEqual(priced_cell["rate"], 123)

		second_page = get_price_matrix(
			search=f"_Test Hala IPM {self.suffix} Search",
			item_group=self.item_group,
			start=2,
			page_length=2,
		)
		self.assertEqual(len(second_page["items"]), 1)
		self.assertFalse(second_page["pagination"]["has_more"])

	def test_selling_price_list_filter_returns_only_the_selected_column(self):
		item = self.make_item()
		retail = self.make_price_list("Retail")
		dealer = self.make_price_list("Dealer")
		self.make_item_price(item, retail, 100)
		self.make_item_price(item, dealer, 90)

		matrix = get_price_matrix(search=item.name, price_list=dealer.name, page_length=25)

		self.assertEqual([row.name for row in matrix["price_lists"]], [dealer.name])
		self.assertEqual(matrix["prices"][item.name][dealer.name]["rate"], 90)
		self.assertNotIn(retail.name, matrix["prices"][item.name])

	def test_buying_lists_and_customer_specific_prices_are_excluded(self):
		item = self.make_item()
		selling = self.make_price_list()
		buying_name = f"_Test Hala IPM Buying {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": buying_name,
				"currency": self.currency,
				"enabled": 1,
				"selling": 0,
				"buying": 1,
			}
		).insert()
		customer = frappe.db.get_value("Customer", {}, "name")
		if customer:
			customer_price = self.make_item_price(item, selling, 500)
			customer_price.customer = customer
			customer_price.save()

		matrix = get_price_matrix(search=item.name, page_length=25)

		self.assertIn(selling.name, [row.name for row in matrix["price_lists"]])
		self.assertNotIn(buying_name, [row.name for row in matrix["price_lists"]])
		if customer:
			self.assertNotIn(selling.name, matrix["prices"][item.name])
