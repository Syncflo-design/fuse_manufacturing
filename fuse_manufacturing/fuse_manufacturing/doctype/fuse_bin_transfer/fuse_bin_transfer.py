"""Moving stock from one bin to another inside a single warehouse.

The sibling of Fuse Stock Transfer, and the one real difference is worth stating plainly:
**this document has no Stock Entry behind it.** ERPNext holds stock per warehouse, so a
bin move leaves every ERPNext quantity exactly as it was — there is nothing for a Stock
Entry to record. This document is the local record, and Intacct is where the movement
actually happens.

Two consequences fall out of that, and both are deliberate:

  * Submitting posts to Intacct directly, and refuses if posting is switched off. A bin
    transfer that never reaches Intacct has done nothing at all.
  * Nothing can check what a bin holds. ERPNext does not track stock at bin level, and
    Intacct exposes on-hand per warehouse, not per bin. So the screen checks what it can
    — the warehouse holds enough, the bins are real and belong to this warehouse — and
    Intacct is the one that accepts or refuses the rest.

That last point closes the day bins become ERPNext warehouses. Until then, say what is
true rather than implying a check that is not being made.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


class FuseBinTransfer(Document):
	def validate(self):
		self._check_module()
		self.date_issued = self.date_issued or now_datetime()

		if self.source_bin == self.target_bin:
			frappe.throw("The from and to bins are the same, so nothing would move.")

		for row in self.items:
			if flt(row.quantity) <= 0:
				frappe.throw(f"Row {row.idx} ({row.item}): enter how much is moving.")

		self._check_bins()
		self._check_available()

	def _check_module(self):
		"""Refuse the whole screen where Bin Transfer is switched off.

		Off by default: a client whose items are not bin-enabled in Intacct has nowhere for
		this to move stock to, and every document raised here would be rejected on posting.
		"""
		from fuse_manufacturing import modules

		if modules.is_active("bin_transfer"):
			return

		label = modules.module_label("bin_transfer")
		frappe.throw(
			f"{label} is switched off for this site, so a bin move cannot be recorded.\n\n"
			"An administrator can switch it back on under Active Modules in Intacct Settings.",
			title=f"{label} is switched off",
		)

	def _check_bins(self):
		"""Both bins have to belong to the warehouse this document is using.

		The pickers filter by warehouse, so this catches the case where a bin was right
		when it was chosen and became wrong when the warehouse changed underneath it. The
		line still looks filled in, which is exactly why it needs saying.
		"""
		wrong = []
		for label, bin_name in (("From bin", self.source_bin), ("To bin", self.target_bin)):
			if not bin_name:
				continue
			owner = frappe.db.get_value("Intacct Bin", bin_name, "warehouse")
			if owner != self.warehouse:
				wrong.append(f"{label} {bin_name} belongs to {owner}, not {self.warehouse}.")

		if wrong:
			frappe.throw("<br>".join(wrong), title="Bin is in the wrong warehouse")

	def _check_available(self):
		"""Refuse more than the WAREHOUSE holds. Not more than the bin holds.

		A weaker check than the warehouse transfer's, and honestly so: nothing on either
		side knows what is in a bin. What it does catch is the move that could not be right
		under any bin arrangement, which is worth catching before Intacct is asked.
		"""
		wanted = {}
		for row in self.items:
			wanted[row.item] = wanted.get(row.item, 0) + flt(row.quantity)

		short = []
		for item_code, qty in wanted.items():
			available = flt(
				frappe.db.get_value(
					"Bin", {"item_code": item_code, "warehouse": self.warehouse}, "actual_qty"
				)
			)
			if qty > available:
				short.append(f"{item_code}: moving {qty}, {available} in the warehouse")

		if short:
			frappe.throw(
				f"{self.warehouse} does not hold enough:<br><br>" + "<br>".join(short),
				title="Not enough stock",
			)


# ──────────────────────────────────────────────────────────────────────────────
# What the screen asks
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def stock_on_hand(item_code, warehouse):
	"""What one item has in one warehouse, right now.

	Per warehouse, not per bin — see the module docstring. Shown so the person moving
	stock has some idea of scale, not as a limit on what may go in a bin.
	"""
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def items_in_warehouse(doctype, txt, searchfield, start, page_len, filters):
	"""Items the warehouse actually holds, narrowed by what was typed."""
	warehouse = (filters or {}).get("warehouse")
	if not warehouse:
		return []

	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		SELECT b.item_code, i.item_name, b.actual_qty
		FROM `tabBin` b
		INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse = %(warehouse)s
			AND b.actual_qty > 0
			AND i.disabled = 0
			AND (b.item_code LIKE %(txt)s OR i.item_name LIKE %(txt)s)
		ORDER BY CASE WHEN b.item_code LIKE %(txt)s THEN 0 ELSE 1 END, b.item_code
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"warehouse": warehouse,
			"txt": like,
			"start": cint(start),
			"page_len": cint(page_len),
		},
	)


@frappe.whitelist()
def item_from_barcode(barcode):
	"""The item a scanned code refers to.

	Goes through the same resolver every other Fuse screen uses, so a bin or pallet label
	scanned here is recognised for what it is rather than reported as an unknown item.
	"""
	from fuse_manufacturing import scanning

	found = scanning.resolve_scan(barcode)
	if found["type"] != "item":
		return {"found": False, "label": found.get("label"), "type": found["type"]}

	tracking = frappe.db.get_value(
		"Item", found["value"], ["item_name", "stock_uom", "custom_intacct_lot_tracked"], as_dict=True
	)
	return {
		"found": True,
		"item_code": found["value"],
		"item_name": tracking.item_name,
		"uom": tracking.stock_uom,
		"lot_tracked": bool(tracking.custom_intacct_lot_tracked),
	}


@frappe.whitelist()
def tracking(items):
	"""Which of these items Intacct tracks lots on.

	Asked once for the whole table rather than per row, so the Lot column appears the
	moment the first tracked item is added instead of a row later.
	"""
	items = frappe.parse_json(items) if isinstance(items, str) else items
	if not items:
		return {}

	rows = frappe.get_all(
		"Item",
		filters={"name": ("in", list(items))},
		fields=["name", "custom_intacct_lot_tracked"],
	)
	return {row.name: {"lot": bool(row.custom_intacct_lot_tracked)} for row in rows}
