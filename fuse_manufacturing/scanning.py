"""One door for every scan.

A warehouse scanner is pointed at whatever is in front of it — a pallet label, a bin
label, an item barcode, a works order, a delivery note. The screen usually knows what
it *hopes* was scanned, but it must not assume: scanning a pallet into a box expecting
an item code is how an operator ends up recording the wrong thing entirely.

So every scan goes through `resolve_scan`, which answers "what did you just scan?"
rather than "was that the thing I wanted?". Screens decide what to do with the answer,
including refusing a type they cannot use — but they refuse knowingly, and can say what
it actually was.

Resolution runs most-specific first. Fuse-issued identifiers (handling units, documents)
are checked before item codes, because an item code is a free-text field a client
controls and could in principle collide with a document number.
"""

import frappe

# How many candidates a fuzzy search returns before it stops being useful on a phone.
SEARCH_LIMIT = 20


def _hit(kind, value, label, extra=None):
	found = {"type": kind, "value": value, "label": label}
	if extra:
		found.update(extra)
	return found


@frappe.whitelist()
def resolve_scan(term):
	"""Identify what a scanned or typed string refers to.

	Returns a dict with `type` — one of handling_unit, bin, work_order, purchase_order,
	item, ambiguous, unknown — and enough detail for a screen to act without a second
	round trip.
	"""
	term = (term or "").strip()
	if not term:
		return _hit("unknown", None, "Nothing scanned.")

	# ── Handling units — a pallet, case or box ────────────────────────────────
	# By barcode first: a supplier's own label lives in `barcode` while the name stays
	# the Fuse number, so the barcode is what a scanner actually reads.
	unit = frappe.db.get_value(
		"Fuse Handling Unit",
		{"barcode": term},
		["name", "unit_type", "status", "warehouse"],
		as_dict=True,
	) or frappe.db.get_value(
		"Fuse Handling Unit",
		{"name": term},
		["name", "unit_type", "status", "warehouse"],
		as_dict=True,
	)
	if unit:
		return _hit(
			"handling_unit",
			unit.name,
			f"{unit.unit_type} {unit.name}",
			{"unit_type": unit.unit_type, "status": unit.status, "warehouse": unit.warehouse},
		)

	# ── Bins — Intacct's, mirrored read-only ──────────────────────────────────
	# The name is "<warehouse>::<bin id>", so a bare bin label matches on bin_id. That
	# is only unique within a warehouse, which is why the ambiguous case is reported
	# rather than resolved to the first row.
	bins = frappe.get_all(
		"Intacct Bin",
		or_filters={"name": term, "bin_id": term},
		fields=["name", "bin_id", "warehouse"],
		limit=SEARCH_LIMIT,
	)
	if len(bins) == 1:
		return _hit(
			"bin",
			bins[0].name,
			f"Bin {bins[0].bin_id} in {bins[0].warehouse}",
			{"bin_id": bins[0].bin_id, "warehouse": bins[0].warehouse},
		)
	if len(bins) > 1:
		return _hit(
			"ambiguous",
			None,
			f"Bin {term} exists in more than one warehouse.",
			{"of_type": "bin", "matches": bins},
		)

	# ── Documents ─────────────────────────────────────────────────────────────
	work_order = frappe.db.get_value(
		"Work Order", {"name": term, "docstatus": 1}, ["name", "production_item", "status"], as_dict=True
	)
	if work_order:
		return _hit(
			"work_order",
			work_order.name,
			f"Works order {work_order.name} — {work_order.production_item}",
			{"status": work_order.status, "production_item": work_order.production_item},
		)

	# Either ERPNext's own name or the Intacct document it mirrors, because the number
	# printed on the supplier's paperwork is Intacct's, not ours.
	order = frappe.db.get_value(
		"Purchase Order", {"name": term, "docstatus": 1}, ["name", "supplier", "status"], as_dict=True
	) or frappe.db.get_value(
		"Purchase Order",
		{"custom_intacct_po_id": term, "docstatus": 1},
		["name", "supplier", "status"],
		as_dict=True,
	)
	if order:
		return _hit(
			"purchase_order",
			order.name,
			f"Purchase order {order.name} — {order.supplier}",
			{"status": order.status, "supplier": order.supplier},
		)

	# ── Items ─────────────────────────────────────────────────────────────────
	base = {"disabled": 0, "is_stock_item": 1}
	fields = ["name as item_code", "item_name", "stock_uom"]

	item = frappe.get_all("Item", filters=dict(base, name=term), fields=fields)
	if not item:
		coded = frappe.get_all("Item Barcode", filters={"barcode": term}, pluck="parent", limit=SEARCH_LIMIT)
		if coded:
			item = frappe.get_all("Item", filters=dict(base, name=["in", coded]), fields=fields)

	if len(item) == 1:
		return _hit(
			"item",
			item[0].item_code,
			f"{item[0].item_code} — {item[0].item_name or ''}".strip(" —"),
			{"item_name": item[0].item_name, "stock_uom": item[0].stock_uom},
		)
	if len(item) > 1:
		# One barcode on several items is a data fault, not a choice to make silently.
		return _hit(
			"ambiguous",
			None,
			f"{term} matches more than one item.",
			{"of_type": "item", "matches": item},
		)

	# ── Nothing matched ───────────────────────────────────────────────────────
	# A fuzzy list is offered so a mistyped code is one tap from being corrected, but
	# it is NOT a resolution: the caller is told plainly that nothing matched.
	suggestions = frappe.get_all(
		"Item",
		filters=base,
		or_filters={"name": ["like", f"%{term}%"], "item_name": ["like", f"%{term}%"]},
		fields=fields,
		order_by="name",
		limit=SEARCH_LIMIT,
	)
	return _hit("unknown", None, f"Nothing matches “{term}”.", {"suggestions": suggestions})
