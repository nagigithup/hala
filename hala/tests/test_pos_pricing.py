from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hala.api.pos_pricing import (
	_get_customer_item_details,
	_get_customer_specific_price_list_rate,
	_pricing_date_metadata,
	_validate_submitted_price_list_rates,
	get_catalog_prices,
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

		return (
			patch("hala.api.pos_pricing.frappe.db.exists", return_value=True),
			patch("hala.api.pos_pricing.frappe.get_cached_doc", side_effect=cached_doc),
			patch("hala.api.pos_pricing.frappe.get_cached_value", return_value=profile_list),
			patch("hala.api.pos_pricing.frappe.get_single_value", return_value=setting_list),
			patch(
				"hala.api.pos_pricing.frappe.db.get_value",
				return_value=frappe._dict({"enabled": 1, "selling": 1}),
			),
		)

	def _resolve_with_patches(self, customer, patches, pos_profile="Test POS"):
		with patches[0], patches[1], patches[2], patches[3], patches[4]:
			return resolve_effective_price_list(customer, pos_profile)

	def test_customer_default_price_list_has_priority(self):
		for customer, expected in (("Retail Customer", "Retail"), ("Wholesale Customer", "Wholesale")):
			with self.subTest(customer=customer):
				patches = self._resolver_patches({customer: expected})
				self.assertEqual(self._resolve_with_patches(customer, patches), expected)

	def test_empty_customer_price_list_uses_standard_selling(self):
		patches = self._resolver_patches({"Customer": None}, profile_list="POS Selling")
		self.assertEqual(self._resolve_with_patches("Customer", patches), "Standard Selling")

	def test_catalog_returns_customer_prices(self):
		with (
			patch(
				"hala.api.pos_pricing._build_pricing_context",
				return_value=frappe._dict(
					{
						"price_list": "Customer List",
						"pos_profile": "Test POS",
						"posting_date": "2026-10-07",
					}
				),
			),
			patch(
				"hala.api.pos_pricing._get_customer_item_details",
				return_value={"price_list_rate": 100, "uom": "Kg"},
			),
		):
			result = get_catalog_prices(
				customer="Customer", pos_profile="Test POS", items=[{"item_code": "ITEM-1", "uom": "Kg"}]
			)
		self.assertEqual(result["price_list"], "Customer List")
		self.assertEqual(result["prices"]["ITEM-1"]["rate"], 100)

	def test_customer_specific_item_price_beats_newer_generic_price(self):
		price_list = "__Hala Customer Price Priority"
		customer = "__Hala Price Customer"
		item_code = "__HALA-PRICE-ITEM"
		customer_group = "__Hala Price Customer Group"
		territory = "__Hala Price Territory"
		company_currency = frappe.get_cached_value("Company", "alnagi", "default_currency") or "SAR"

		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": price_list,
				"enabled": 1,
				"selling": 1,
				"currency": company_currency,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": customer_group,
				"parent_customer_group": "All Customer Groups",
				"is_group": 0,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Territory",
				"territory_name": territory,
				"parent_territory": "All Territories",
				"is_group": 0,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": customer,
				"customer_type": "Individual",
				"customer_group": customer_group,
				"territory": territory,
				"default_price_list": price_list,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_sales_item": 1,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"price_list": price_list,
				"item_code": item_code,
				"uom": "Nos",
				"price_list_rate": 50,
				"valid_from": "2026-10-03",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"price_list": price_list,
				"item_code": item_code,
				"uom": "Nos",
				"price_list_rate": 100,
				"customer": customer,
				"valid_from": "2026-08-23",
			}
		).insert()

		self.assertEqual(
			_get_customer_specific_price_list_rate(
				item_code=item_code,
				price_list=price_list,
				customer=customer,
				transaction_date="2026-10-08",
				qty=1,
				uom="Nos",
				stock_uom="Nos",
			),
			100,
		)

	def test_customer_specific_rate_reapplies_erpnext_pricing_rule(self):
		context = frappe._dict(
			{
				"customer": "Employee Customer",
				"pos_profile": "Test POS",
				"profile": frappe._dict(
					{"warehouse": "Main", "company": "Test Company", "currency": "SAR"}
				),
				"price_list": "Customer List",
				"posting_date": "2026-10-08",
				"doc": frappe._dict(
					{
						"doctype": "Sales Invoice",
						"company": "Test Company",
						"customer": "Employee Customer",
						"selling_price_list": "Customer List",
						"posting_date": "2026-10-08",
						"transaction_date": "2026-10-08",
						"is_pos": 1,
						"pos_profile": "Test POS",
					}
				),
			}
		)
		item_doc = frappe._dict(
			{
				"name": "ITEM-1",
				"stock_uom": "Nos",
				"variant_of": None,
				"is_sales_item": 1,
				"has_batch_no": 0,
				"has_serial_no": 0,
				"is_stock_item": 1,
			}
		)
		with (
			patch("hala.api.pos_pricing.frappe.get_cached_doc", return_value=item_doc),
			patch(
				"pos_next.api.items.get_item_detail",
				return_value={
					"price_list_rate": 50,
					"discount_percentage": 10,
					"discount_amount": 5,
					"uom": "Nos",
					"stock_uom": "Nos",
					"conversion_factor": 1,
					"price_list_currency": "SAR",
				},
			),
			patch(
				"hala.api.pos_pricing._get_customer_specific_price_list_rate",
				return_value=100,
			),
			patch(
				"erpnext.accounts.doctype.pricing_rule.pricing_rule.get_pricing_rule_for_item",
				return_value=frappe._dict(
					{
						"discount_percentage": 10,
						"discount_amount": 10,
						"pricing_rules": '["EMPLOYEE-RULE"]',
					}
				),
			),
		):
			result = _get_customer_item_details(
				item_code="ITEM-1",
				pos_profile="Test POS",
				customer="Employee Customer",
				qty=1,
				uom="Nos",
				pricing_context=context,
			)

		self.assertEqual(result["price_list_rate"], 100)
		self.assertEqual(result["discount_percentage"], 10)
		self.assertEqual(result["discount_amount"], 10)
		self.assertEqual(result["pricing_rules"], '["EMPLOYEE-RULE"]')

	def test_catalog_deduplicates_same_pricing_context(self):
		context = frappe._dict(
			{
				"price_list": "Customer List",
				"pos_profile": "Test POS",
				"posting_date": "2026-10-07",
			}
		)
		items = [
			{"item_code": "ITEM-1", "uom": "Kg", "qty": 2, "request_key": "first"},
			{"item_code": "ITEM-1", "uom": "Kg", "qty": 2, "request_key": "duplicate"},
		]
		with (
			patch("hala.api.pos_pricing._build_pricing_context", return_value=context),
			patch(
				"hala.api.pos_pricing._get_customer_item_details",
				return_value={"price_list_rate": 75, "uom": "Kg"},
			) as get_details,
		):
			result = get_catalog_prices(
				customer="Customer", pos_profile="Test POS", items=items, transaction_date="2026-10-07"
			)

		get_details.assert_called_once()
		self.assertEqual(result["prices"]["ITEM-1"]["rate"], 75)
		self.assertEqual(result["prices_by_request"]["first"], result["prices"]["ITEM-1"])
		self.assertEqual(result["prices_by_request"]["duplicate"], result["prices"]["ITEM-1"])

	def test_catalog_keeps_uom_and_quantity_pricing_contexts_distinct(self):
		context = frappe._dict(
			{
				"price_list": "Customer List",
				"pos_profile": "Test POS",
				"posting_date": "2026-10-07",
			}
		)

		def details(**kwargs):
			return {"price_list_rate": kwargs["qty"] * (10 if kwargs["uom"] == "Kg" else 20), "uom": kwargs["uom"]}

		with (
			patch("hala.api.pos_pricing._build_pricing_context", return_value=context),
			patch("hala.api.pos_pricing._get_customer_item_details", side_effect=details) as get_details,
		):
			result = get_catalog_prices(
				customer="Customer",
				pos_profile="Test POS",
				items=[
					{"item_code": "ITEM-1", "uom": "Kg", "qty": 1, "request_key": "kg-one"},
					{"item_code": "ITEM-1", "uom": "Kg", "qty": 3, "request_key": "kg-three"},
					{"item_code": "ITEM-1", "uom": "Box", "qty": 1, "request_key": "box-one"},
				],
			)

		self.assertEqual(get_details.call_count, 3)
		self.assertEqual(result["prices_by_request"]["kg-one"]["rate"], 10)
		self.assertEqual(result["prices_by_request"]["kg-three"]["rate"], 30)
		self.assertEqual(result["prices_by_request"]["box-one"]["rate"], 20)

	def test_alternate_uom_preserves_customer_quantity_and_price_list_context(self):
		context = frappe._dict(
			{
				"pos_profile": "Test POS",
				"profile": frappe._dict({"warehouse": "Main", "company": "Test Company"}),
				"price_list": "Customer List",
				"posting_date": "2026-10-08",
				"doc": frappe._dict(
					{
						"customer": "Customer A",
						"selling_price_list": "Customer List",
						"posting_date": "2026-10-08",
					}
				),
			}
		)
		item_doc = frappe._dict(
			{
				"is_sales_item": 1,
				"has_batch_no": 0,
				"has_serial_no": 0,
				"is_stock_item": 1,
			}
		)
		with (
			patch("hala.api.pos_pricing.frappe.get_cached_doc", return_value=item_doc),
			patch(
				"pos_next.api.items.get_item_detail",
				return_value={
					"rate": 80,
					"price_list_rate": 100,
					"discount_percentage": 20,
					"pricing_rules": "BOX-RULE",
					"uom": "Box",
				},
			) as get_detail,
		):
			result = _get_customer_item_details(
				item_code="ITEM-1",
				pos_profile="Test POS",
				customer="Customer A",
				qty=10,
				uom="Box",
				pricing_context=context,
			)

		request_item = get_detail.call_args.kwargs["item"]
		self.assertEqual(request_item["customer"], "Customer A")
		self.assertEqual(request_item["qty"], 10)
		self.assertEqual(request_item["uom"], "Box")
		self.assertEqual(get_detail.call_args.kwargs["price_list"], "Customer List")
		self.assertEqual(result["discount_percentage"], 20)
		self.assertEqual(result["pricing_rules"], "BOX-RULE")

	def test_catalog_uses_site_date_instead_of_untrusted_client_date(self):
		context = frappe._dict(
			{
				"price_list": "Customer List",
				"pos_profile": "Test POS",
				"posting_date": "2026-10-08",
			}
		)
		with (
			patch(
				"hala.api.pos_pricing._pricing_date_metadata",
				return_value={"pricing_date": "2026-10-08", "date_refresh_ms": 1000},
			),
			patch("hala.api.pos_pricing._build_pricing_context", return_value=context) as build_context,
			patch(
				"hala.api.pos_pricing._get_customer_item_details",
				return_value={"price_list_rate": 25, "uom": "Nos"},
			),
		):
			result = get_catalog_prices(
				customer="Customer",
				pos_profile="Test POS",
				items=[{"item_code": "ITEM-1"}],
				transaction_date="1999-12-31",
			)

		self.assertEqual(build_context.call_args.kwargs["transaction_date"], "2026-10-08")
		self.assertEqual(result["pricing_date"], "2026-10-08")

	def test_pricing_date_metadata_uses_site_midnight_boundary(self):
		before_midnight = _pricing_date_metadata(datetime(2026, 10, 7, 23, 59, 59, 500000))
		at_midnight = _pricing_date_metadata(datetime(2026, 10, 8, 0, 0, 0))

		self.assertEqual(before_midnight["pricing_date"], "2026-10-07")
		self.assertEqual(before_midnight["date_refresh_ms"], 1500)
		self.assertEqual(at_midnight["pricing_date"], "2026-10-08")
		self.assertEqual(at_midnight["date_refresh_ms"], 86_401_000)

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
