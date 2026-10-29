"""Remove only explicitly approved, fingerprinted legacy Sales Invoice formats."""

import hashlib

import frappe


# Site-only older A4 variant audited and explicitly approved for removal.
# Never broaden this into "all formats except the retained three".
LEGACY_SALES_INVOICE_FORMATS = {
	"فاتورة مبيعات A$": "b9f19a6bc11774b8a4b27f3f7904c8a917c7df360d0e70e67c084758d9ddbf63",
}


def cleanup_legacy_sales_invoice_formats():
	removed = []
	for name, expected_hash in LEGACY_SALES_INVOICE_FORMATS.items():
		if not frappe.db.exists("Print Format", name):
			continue
		doc = frappe.get_doc("Print Format", name)
		fingerprint = hashlib.sha256((doc.html or "").encode()).hexdigest()
		if (doc.doc_type != "Sales Invoice" or doc.standard != "No" or doc.module != "Accounts"
			or doc.css or fingerprint != expected_hash):
			frappe.logger().warning("Preserving changed or non-legacy Print Format: %s", name)
			continue
		if (frappe.db.exists("POS Profile", {"print_format": name})
			or frappe.db.exists("Property Setter", {"property": "default_print_format", "value": name})):
			frappe.logger().warning("Preserving referenced legacy Print Format: %s", name)
			continue
		# Normal deletion retains Frappe's Deleted Document recovery record and link checks.
		frappe.delete_doc("Print Format", name, ignore_permissions=True)
		removed.append(name)
	return removed
