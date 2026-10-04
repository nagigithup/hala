"""Backfill only Hala payments whose POS Profile is unambiguous."""

import frappe


def execute():
	# Ensure the target column exists even on sites migrating from an older Hala
	# version where this patch runs before after_migrate.
	from hala.setup import ensure_booking_fields

	ensure_booking_fields()

	# A booking payment inherits the profile already stored on its Sales Invoice.
	frappe.db.sql(
		"""
		UPDATE `tabPayment Entry` payment
		INNER JOIN `tabSales Invoice` booking
		        ON booking.name = payment.custom_booking_invoice
		SET payment.custom_cashier_profile = booking.pos_profile
		WHERE IFNULL(payment.custom_cashier_profile, '') = ''
		  AND IFNULL(payment.custom_booking_invoice, '') != ''
		  AND IFNULL(booking.pos_profile, '') != ''
		"""
	)

	# Hala deposits record the POS Opening Shift in reference_no.  Restrict this
	# derivation to explicit deposit rows; reference_no has unrelated meanings on
	# ordinary historical Payment Entries and must never be guessed from.
	frappe.db.sql(
		"""
		UPDATE `tabPayment Entry` payment
		INNER JOIN `tabPOS Opening Shift` opening
		        ON opening.name = payment.reference_no
		SET payment.custom_cashier_profile = opening.pos_profile
		WHERE IFNULL(payment.custom_cashier_profile, '') = ''
		  AND payment.custom_is_deposit = 1
		  AND IFNULL(payment.custom_original_deposit_payment, '') = ''
		  AND IFNULL(opening.pos_profile, '') != ''
		"""
	)

	# Refunds inherit from the original receipt, never from the refunding user.
	frappe.db.sql(
		"""
		UPDATE `tabPayment Entry` refund
		INNER JOIN `tabPayment Entry` original
		        ON original.name = refund.custom_original_deposit_payment
		SET refund.custom_cashier_profile = original.custom_cashier_profile
		WHERE IFNULL(refund.custom_cashier_profile, '') = ''
		  AND IFNULL(refund.custom_original_deposit_payment, '') != ''
		  AND IFNULL(original.custom_cashier_profile, '') != ''
		"""
	)
