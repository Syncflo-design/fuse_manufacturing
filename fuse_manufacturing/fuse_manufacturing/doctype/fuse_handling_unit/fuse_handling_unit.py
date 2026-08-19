"""A barcoded handling unit — a pallet, case, box or tote.

Intacct has no equivalent object, so this number is ours. That makes it the second
place Fuse invents a value (the first is the reversal document number), and the same
reasoning applies: it is an identifier, not a quantity or a cost, so nothing about
Intacct's books depends on it.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class FuseHandlingUnit(Document):
	def validate(self):
		self.set_barcode()
		self.validate_contents()
		self.validate_nesting()

	def set_barcode(self):
		"""Its own number is the barcode, unless the goods arrived already labelled.

		A supplier's label is kept as-is rather than relabelled: reprinting over a
		barcode the supplier's paperwork also quotes breaks the only link between the
		delivery and what is on the shelf.
		"""
		if not self.barcode:
			self.barcode = self.name

	def validate_contents(self):
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(f"Row {row.idx}: {row.item_code} needs a quantity above zero.")

	def validate_nesting(self):
		"""A unit cannot sit on itself, directly or through a chain.

		Cases go on pallets and pallets go in containers, so nesting is real — and a
		loop would make any walk of the tree run forever.
		"""
		if not self.parent_unit:
			return
		if self.parent_unit == self.name:
			frappe.throw("A handling unit cannot sit on itself.")

		seen, unit = {self.name}, self.parent_unit
		while unit:
			if unit in seen:
				frappe.throw(f"{unit} is already on this unit — handling units cannot loop.")
			seen.add(unit)
			unit = frappe.db.get_value("Fuse Handling Unit", unit, "parent_unit")
