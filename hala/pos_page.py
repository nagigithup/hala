from frappe.utils import now_datetime
from frappe.website.page_renderers.template_page import TemplatePage

from hala.api.pos_pricing import _pricing_date_metadata


class CustomerPricingPOSPage(TemplatePage):
	"""Add Hala's catalog pricing script to the POS Next website page."""

	def can_render(self):
		return self.path == "pos" and super().can_render()

	def get_html(self):
		html = super().get_html()
		date_context = _pricing_date_metadata(now_datetime())
		# The site-rendered date avoids using the cashier computer's timezone. The
		# refresh delay schedules an authoritative check just after site midnight.
		script = (
			'<script defer src="/assets/hala/js/pos_customer_prices.js?v=5" '
			f'data-pricing-date="{date_context["pricing_date"]}" '
			f'data-date-refresh-ms="{date_context["date_refresh_ms"]}"></script>'
		)
		return html.replace("</head>", f"{script}</head>", 1)
