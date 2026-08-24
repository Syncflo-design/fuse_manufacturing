import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class FuseMeasuringInstrument(Document):
	def validate(self):
		"""Calibration dates have to make sense before anyone relies on them.

		A due date before the calibration date is a typo, and a typo here quietly makes
		every reading taken with this instrument inadmissible.
		"""
		if self.calibrated_on and self.calibration_due:
			if getdate(self.calibration_due) < getdate(self.calibrated_on):
				frappe.throw("Calibration due cannot be before the date it was calibrated.")

	def is_in_calibration(self, on_date=None):
		"""Whether this instrument may be used to produce a result on a given date."""
		if self.status != "Active":
			return False
		if not self.calibration_due:
			return False
		return getdate(on_date or frappe.utils.nowdate()) <= getdate(self.calibration_due)
