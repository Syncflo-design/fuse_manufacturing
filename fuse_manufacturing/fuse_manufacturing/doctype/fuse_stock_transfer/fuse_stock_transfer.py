"""A warehouse-to-warehouse move, on one short screen.

Modelled on the Stock Transfer screen proven at Ardmore. The person moving the stock sees
a from, a to and a list of items; submitting builds an ordinary **Stock Entry** and submits
it, so `postings.on_stock_entry_submit` fires and Intacct is asked first exactly as it is
from the desk form or the shop floor.

One posting path, three front doors. This screen never talks to Intacct itself — if it
did, there would be a second place for the rules about costs, bins and lots to drift.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

TRANSFER = "Material Transfer"


class FuseStockTransfer(Document):
	def validate(self):
		self._check_module()
		self.date_issued = self.date_issued or now_datetime()

		if self.source_warehouse == self.target_warehouse:
			frappe.throw("The from and to warehouses are the same, so nothing would move.")

		for row in self.items:
			if flt(row.quantity) <= 0:
				frappe.throw(f"Row {row.idx} ({row.item}): enter how much is moving.")

		self._check_available()
		self._check_bins()

	def _check_module(self):
		"""Refuse the whole screen where Item Transfer is switched off.

		The Stock Entry this raises would be refused anyway, by the same switch. Refusing
		here means finding out before filling the form in rather than after submitting it.
		"""
		from fuse_manufacturing import modules

		if modules.is_active("item_transfer"):
			return

		label = modules.module_label("item_transfer")
		frappe.throw(
			f"{label} is switched off for this site, so a transfer cannot be recorded.\n\n"
			"An administrator can switch it back on under Active Modules in Intacct Settings.",
			title=f"{label} is switched off",
		)

	def _check_available(self):
		"""Refuse more than the source warehouse actually holds.

		Checked on the whole document rather than per row, because the same item can appear
		twice and each line looked fine on its own. Reported together so someone fixes the
		document once instead of meeting one error per line.
		"""
		wanted = {}
		for row in self.items:
			wanted[row.item] = wanted.get(row.item, 0) + flt(row.quantity)

		short = []
		for item_code, qty in wanted.items():
			available = flt(
				frappe.db.get_value(
					"Bin",
					{"item_code": item_code, "warehouse": self.source_warehouse},
					"actual_qty",
				)
			)
			if qty > available:
				short.append(f"{item_code}: moving {qty}, {available} on hand")

		if short:
			frappe.throw(
				f"{self.source_warehouse} does not hold enough:<br><br>" + "<br>".join(short),
				title="Not enough stock",
			)


	def _check_bins(self):
		"""A bin picked on a line has to belong to the warehouse that line is using.

		The picker filters by warehouse, so this only catches a bin that was right when it
		was chosen and became wrong when someone changed the warehouse afterwards. That is
		exactly the case worth catching: the line still looks filled in, and Intacct would
		either reject it or, worse, file the stock somewhere real but wrong.
		"""
		wrong = []
		for row in self.items:
			for label, bin_name, warehouse in (
				("From bin", row.source_bin, self.source_warehouse),
				("To bin", row.target_bin, self.target_warehouse),
			):
				if not bin_name:
					continue
				owner = frappe.db.get_value("Intacct Bin", bin_name, "warehouse")
				if owner != warehouse:
					wrong.append(
						f"Row {row.idx}: {label} {bin_name} belongs to {owner}, not {warehouse}."
					)

		if wrong:
			frappe.throw("<br>".join(wrong), title="Bin is in the wrong warehouse")

	def on_submit(self):
		"""Build the movement and let it post.

		The Stock Entry is what Fuse and Intacct both understand. Submitting it here means
		a rejection from Intacct raises inside this submit, so the transfer does not stand
		either — the same contract as every other movement.
		"""
		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = TRANSFER
		entry.purpose = TRANSFER
		entry.company = self.company
		entry.set_posting_time = 1
		entry.posting_date = frappe.utils.getdate(self.date_issued)
		entry.posting_time = frappe.utils.get_time(self.date_issued)

		for row in self.items:
			entry.append(
				"items",
				{
					"item_code": row.item,
					"qty": flt(row.quantity),
					"s_warehouse": self.source_warehouse,
					"t_warehouse": self.target_warehouse,
					# The raw Intacct IDs, because that is what a posting sends. The link
					# on the line is the mirrored bin record; its name carries the
					# warehouse too, which Intacct would reject.
					"custom_intacct_source_bin": _bin_id(row.source_bin),
					"custom_intacct_target_bin": _bin_id(row.target_bin),
					"custom_intacct_lot": (row.lot or "").strip() or None,
				},
			)

		entry.insert()
		entry.submit()

		self.db_set("stock_entry", entry.name)

	def on_cancel(self):
		"""Cancel the movement behind it, and let Fuse reverse in Intacct.

		Deliberately not a silent detach. Cancelling the Stock Entry runs
		`postings.on_stock_entry_cancel`, which posts the reversal — so a cancel here
		unwinds both systems rather than leaving Intacct holding a movement this document
		no longer admits to.
		"""
		if not self.stock_entry:
			return

		entry = frappe.get_doc("Stock Entry", self.stock_entry)
		if entry.docstatus == 1:
			entry.cancel()


def _bin_id(bin_name):
	"""The BINID out of a mirrored bin record, or None when no bin was picked."""
	if not bin_name:
		return None
	return frappe.db.get_value("Intacct Bin", bin_name, "bin_id")

# ──────────────────────────────────────────────────────────────────────────────
# What the screen asks
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def stock_on_hand(item_code, warehouse):
	"""What one item has in one warehouse, right now."""
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def items_in_warehouse(doctype, txt, searchfield, start, page_len, filters):
	"""Items actually held in the source warehouse, narrowed by what was typed.

	Both halves matter. Offering the whole item master means hunting through things that
	are not there; ignoring the typed text means the picker always shows the same first
	page, which reads as "this warehouse only has one kind of thing". Ardmore hit exactly
	that and it was reported twice as a stock problem before anyone suspected the search.
	"""
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
	"""The item a scanned code refers to, and what it needs captured.

	Goes through the same resolver every other Fuse screen uses, so a bin or pallet label
	scanned here is recognised for what it is rather than reported as an unknown item.
	"""
	from fuse_manufacturing import scanning

	found = scanning.resolve_scan(barcode)
	if found["type"] != "item":
		return {"found": False, "label": found.get("label"), "type": found["type"]}

	tracking = frappe.db.get_value(
		"Item",
		found["value"],
		["item_name", "stock_uom", "custom_intacct_lot_tracked", "custom_intacct_bin_tracked"],
		as_dict=True,
	)
	return {
		"found": True,
		"item_code": found["value"],
		"item_name": tracking.item_name,
		"uom": tracking.stock_uom,
		"lot_tracked": bool(tracking.custom_intacct_lot_tracked),
		"bin_tracked": bool(tracking.custom_intacct_bin_tracked),
	}


@frappe.whitelist()
def tracking(items):
	"""How Intacct tracks each of these items.

	The form asks once for the whole table rather than per row, so adding ten lines does
	not mean ten round trips — and so the bin and lot columns appear the moment the first
	tracked item is added, instead of a row later.
	"""
	items = frappe.parse_json(items) if isinstance(items, str) else items
	if not items:
		return {}

	rows = frappe.get_all(
		"Item",
		filters={"name": ("in", list(items))},
		fields=["name", "custom_intacct_lot_tracked", "custom_intacct_bin_tracked"],
	)
	return {
		row.name: {
			"lot": bool(row.custom_intacct_lot_tracked),
			"bin": bool(row.custom_intacct_bin_tracked),
		}
		for row in rows
	}
