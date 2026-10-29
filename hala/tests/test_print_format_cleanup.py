from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from hala.print_format_cleanup import LEGACY_SALES_INVOICE_FORMATS, cleanup_legacy_sales_invoice_formats


class TestLegacyPrintCleanup(TestCase):
	def run_cleanup(self, overrides=None, fingerprint=None, referenced=False, exists=True):
		name, expected = next(iter(LEGACY_SALES_INVOICE_FORMATS.items()))
		doc = frappe._dict(doc_type="Sales Invoice", standard="No", module="Accounts", html="audited", css=None)
		doc.update(overrides or {})
		with patch("hala.print_format_cleanup.frappe.db", new_callable=MagicMock) as db, \
			patch("hala.print_format_cleanup.frappe.get_doc", return_value=doc), \
			patch("hala.print_format_cleanup.frappe.delete_doc") as delete, \
			patch("hala.print_format_cleanup.frappe.logger"), \
			patch("hala.print_format_cleanup.hashlib.sha256") as sha:
			db.exists.side_effect = lambda dt, *args: exists if dt == "Print Format" else referenced
			sha.return_value.hexdigest.return_value = fingerprint or expected
			removed = cleanup_legacy_sales_invoice_formats()
			return name, removed, delete.call_args_list

	def test_only_explicitly_approved_variant_is_deleted(self):
		self.assertEqual(set(LEGACY_SALES_INVOICE_FORMATS), {"فاتورة مبيعات A$"})
		name, removed, calls = self.run_cleanup()
		self.assertEqual(removed, [name])
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0].args, ("Print Format", name))
		self.assertNotIn("force", calls[0].kwargs)

	def test_absent_variant_is_an_idempotent_noop(self):
		_, removed, calls = self.run_cleanup(exists=False)
		self.assertEqual((removed, calls), ([], []))

	def test_core_other_doctypes_and_user_customizations_are_preserved(self):
		for overrides in ({"standard": "Yes"}, {"doc_type": "Payment Entry"}, {"module": "Other App"}, {"css": "custom CSS"}):
			with self.subTest(overrides=overrides):
				_, removed, calls = self.run_cleanup(overrides=overrides)
				self.assertEqual((removed, calls), ([], []))
		_, removed, calls = self.run_cleanup(fingerprint="different HTML")
		self.assertEqual((removed, calls), ([], []))

	def test_active_defaults_are_not_silently_reconfigured(self):
		_, removed, calls = self.run_cleanup(referenced=True)
		self.assertEqual((removed, calls), ([], []))
