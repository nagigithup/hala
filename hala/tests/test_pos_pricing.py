from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.pos_pricing import (
	_validate_submitted_price_list_rates,
	resolve_effective_price_list,
	update_invoice,
)


class TestPOSCustomerPriceList(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _resolver_patches(self, customer_lists, profile_list="Standard Selling", setting_list=None):
		def cached_doc(doctype, name):
			if doctype == "Customer":
				return frappe._dict(
					{
						"doctype": "Customer",
						"name": name,
						"default_price_list": customer_lists.get(name),
						"customer_group": "All Customer Groups",
					}
				)
			raise AssertionError(f"Unexpected document lookup: {doctype} {name}")

		def default_price_list(customer):
			return customer.default_price_list

		return (
			patch("hala.api.pos_pricing.frappe.db.exists", return_value=True),
			patch("hala.api.pos_pricing.frappe.get_cached_doc", side_effect=cached_doc),
			patch("hala.api.pos_pricing.get_default_price_list", side_effect=default_price_list),
			patch("hala.api.pos_pricing.frappe.get_cached_value", return_value=profile_list),
			patch("hala.api.pos_pricing.frappe.get_single_value", return_value=setting_list),
			patch(
				"hala.api.pos_pricing.frappe.db.get_value",
				return_value=frappe._dict({"enabled": 1, "selling": 1}),
			),
		)

	def _resolve_with_patches(self, customer, patches, pos_profile="Test POS"):
		with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
			return resolve_effective_price_list(customer, pos_profile)

	def test_customer_default_price_list_has_priority(self):
		for customer, expected in (("Retail Customer", "Retail"), ("Wholesale Customer", "Wholesale")):
			with self.subTest(customer=customer):
				patches = self._resolver_patches({customer: expected})
				self.assertEqual(self._resolve_with_patches(customer, patches), expected)

	def test_empty_customer_price_list_uses_normal_fallback_chain(self):
		patches = self._resolver_patches({"Customer": None}, profile_list="POS Selling")
		self.assertEqual(self._resolve_with_patches("Customer", patches), "POS Selling")

		patches = self._resolver_patches({"Customer": None}, profile_list=None, setting_list="Default Selling")
		self.assertEqual(self._resolve_with_patches("Customer", patches), "Default Selling")

		patches = self._resolver_patches({"Customer": None}, profile_list=None, setting_list=None)
		self.assertEqual(self._resolve_with_patches("Customer", patches), "Standard Selling")

	def test_customer_switching_resolves_a_b_a_without_cached_result(self):
		customer_lists = {"Customer A": "Retail", "Customer B": "Wholesale"}
		for customer, expected in (
			("Customer A", "Retail"),
			("Customer B", "Wholesale"),
			("Customer A", "Retail"),
		):
			patches = self._resolver_patches(customer_lists)
			self.assertEqual(self._resolve_with_patches(customer, patches), expected)

	def test_missing_item_price_does_not_accept_another_list_rate(self):
		payload = {
			"pos_profile": "Test POS",
			"customer": "Retail Customer",
			"items": [{"item_code": "ITEM-1", "qty": 1, "uom": "Nos", "price_list_rate": 99}],
		}
		with patch(
			"hala.api.pos_pricing._get_customer_item_details",
			return_value={"price_list_rate": 0, "rate": 0},
		):
			with self.assertRaises(frappe.ValidationError):
				_validate_submitted_price_list_rates(payload, "Retail")

			payload["items"][0]["price_list_rate"] = 0
			_validate_submitted_price_list_rates(payload, "Retail")

	def test_invoice_uses_server_resolved_price_list(self):
		payload = {
			"doctype": "Sales Invoice",
			"pos_profile": "Test POS",
			"customer": "Wholesale Customer",
			"selling_price_list": "Untrusted List",
			"items": [{"item_code": "ITEM-1", "price_list_rate": 80}],
		}
		with (
			patch("hala.api.pos_pricing.resolve_effective_price_list", return_value="Wholesale"),
			patch("hala.api.pos_pricing._validate_submitted_price_list_rates") as validate,
			patch("pos_next.api.invoices.update_invoice", side_effect=lambda data: data) as save,
		):
			result = update_invoice(payload)

		self.assertEqual(result["selling_price_list"], "Wholesale")
		self.assertEqual(save.call_args.args[0]["selling_price_list"], "Wholesale")
		validate.assert_called_once()
