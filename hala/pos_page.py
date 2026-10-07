from frappe.website.page_renderers.template_page import TemplatePage


class CustomerPricingPOSPage(TemplatePage):
	"""Add Hala's catalog pricing script to the POS Next website page."""

	def can_render(self):
		return self.path == "pos" and super().can_render()

	def get_html(self):
		html = super().get_html()
		# Bump the query version when changing this standalone script so cashier
		# browsers do not keep the pre-single-flight implementation after deploy.
		script = '<script defer src="/assets/hala/js/pos_customer_prices.js?v=3"></script>'
		return html.replace("</head>", f"{script}</head>", 1)
