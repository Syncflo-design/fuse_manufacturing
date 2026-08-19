"""Receiving — find an order, open it, scan the goods in, process the receipt.

One API, two front doors: the Shop Floor screen on a phone and the desk screen on Fuse
Home both call these functions. Neither posts to Intacct itself — each builds an ordinary
Purchase Receipt and submits it, so `postings.on_purchase_receipt_submit` fires and the PO
Receiver reaches Intacct before any stock lands here.

Purchase orders are NEVER created here. They are mirrored from Intacct read-only; this
module only records what arrived against them.
"""

import json

import frappe
from frappe.utils import flt, getdate, nowdate

from fuse_manufacturing import scanning

# How many orders a search returns before the list stops being useful on a phone.
SEARCH_LIMIT = 50


def _guard():
	if not frappe.has_permission("Purchase Receipt", "create"):
		frappe.throw("You do not have permission to receive goods.")


def _rows(rows):
	if isinstance(rows, str):
		rows = json.loads(rows)
	if not rows:
		frappe.throw("Nothing to receive — capture at least one line.")
	return rows


# ──────────────────────────────────────────────────────────────────────────────
# Find
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def open_orders(term=None):
	"""Mirrored orders still expecting a delivery.

	Matched on our number, Intacct's number and the supplier, because the number on the
	paperwork in the storeman's hand is Intacct's, not ours.
	"""
	_guard()

	filters = {
		"docstatus": 1,
		"custom_intacct_po_id": ("is", "set"),
		"status": ("not in", ("Closed", "Completed")),
	}
	fields = [
		"name",
		"supplier",
		"supplier_name",
		"custom_intacct_po_id",
		"transaction_date",
		"schedule_date",
		"status",
		"company",
		"per_received",
	]

	term = (term or "").strip()
	if term:
		like = f"%{term}%"
		orders = frappe.get_all(
			"Purchase Order",
			filters=filters,
			or_filters={
				"name": ["like", like],
				"custom_intacct_po_id": ["like", like],
				"supplier_name": ["like", like],
			},
			fields=fields,
			order_by="transaction_date desc",
			limit=SEARCH_LIMIT,
		)
	else:
		orders = frappe.get_all(
			"Purchase Order",
			filters=filters,
			fields=fields,
			order_by="transaction_date desc",
			limit=SEARCH_LIMIT,
		)

	# Fully received orders are dropped rather than shown greyed out: a storeman scanning
	# through a list wants what is still coming, and Intacct closes the order at its end
	# anyway once the last line converts.
	return [order for order in orders if flt(order.per_received) < 100]


# ──────────────────────────────────────────────────────────────────────────────
# Open
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def order_lines(purchase_order):
	"""What this order is still owed, line by line.

	`outstanding` is ordered minus already received, per LINE — not per item. The same
	item can appear on an order twice and the two lines convert separately in Intacct.
	"""
	_guard()

	order = frappe.get_doc("Purchase Order", purchase_order)
	if not order.get("custom_intacct_po_id"):
		frappe.throw(
			f"{purchase_order} is not a mirrored Intacct order, so it cannot be received here."
		)

	settings = frappe.get_cached_doc("Intacct Settings")
	lines = []

	for row in order.items:
		outstanding = flt(row.qty) - flt(row.received_qty)
		lines.append(
			{
				"purchase_order_item": row.name,
				"idx": row.idx,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"ordered_qty": flt(row.qty),
				"received_qty": flt(row.received_qty),
				"outstanding_qty": outstanding if outstanding > 0 else 0,
				"uom": row.stock_uom or row.uom,
				"warehouse": row.warehouse,
				"rate": flt(row.rate),
				# Read off the Item, which reads it off Intacct. Nothing here decides
				# whether an item is tracked.
				"lot_tracked": bool(
					frappe.db.get_value("Item", row.item_code, "custom_intacct_lot_tracked")
				),
				"bin_tracked": bool(
					frappe.db.get_value("Item", row.item_code, "custom_intacct_bin_tracked")
				),
				"intacct_line_key": row.get("custom_intacct_line_recordno"),
			}
		)

	return {
		"purchase_order": order.name,
		"intacct_po": order.custom_intacct_po_id,
		"supplier": order.supplier,
		"supplier_name": order.supplier_name,
		"company": order.company,
		"status": order.status,
		"lines": lines,
		"reject_warehouse": settings.get("reject_warehouse"),
		"posting_on": bool(settings.post_movements),
	}


# ──────────────────────────────────────────────────────────────────────────────
# Scan
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def scan(purchase_order, term):
	"""What was just scanned, answered in the context of this order.

	Resolution itself is `scanning.resolve_scan` — the same door every other screen uses,
	so a pallet label scanned here is recognised as a pallet rather than reported as an
	unknown item code. What this adds is the order: an item is only useful if it is
	actually on the order in front of you.
	"""
	_guard()
	found = scanning.resolve_scan(term)

	if found["type"] != "item":
		# Handed back untouched. The screen decides what a bin or a pallet means during
		# receiving; this function's job is to say what it was, not to refuse it.
		return {"scan": found, "lines": []}

	matches = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order, "item_code": found["value"], "docstatus": 1},
		fields=["name", "idx", "item_code", "qty", "received_qty", "stock_uom", "warehouse"],
		order_by="idx",
	)

	if not matches:
		return {
			"scan": found,
			"lines": [],
			"message": f"{found['value']} is not on this order.",
		}

	lines = [
		dict(row, outstanding_qty=max(flt(row.qty) - flt(row.received_qty), 0)) for row in matches
	]

	# Several lines for one item is normal — different warehouses, different dates. The
	# screen asks which; it is not something to resolve by picking the first.
	return {"scan": found, "lines": lines}


# ──────────────────────────────────────────────────────────────────────────────
# Process
# ──────────────────────────────────────────────────────────────────────────────


def _over_receipts(purchase_order, rows):
	"""Lines where more is being received than the order still expects."""
	over = []
	for row in rows:
		po_item = row.get("purchase_order_item")
		ordered, received = frappe.db.get_value(
			"Purchase Order Item", po_item, ["qty", "received_qty"]
		) or (0, 0)
		outstanding = flt(ordered) - flt(received)
		total = flt(row.get("qty")) + flt(row.get("rejected_qty"))
		if total > outstanding:
			over.append(
				{
					"purchase_order_item": po_item,
					"item_code": row.get("item_code"),
					"outstanding_qty": outstanding,
					"receiving_qty": total,
					"excess_qty": total - outstanding,
				}
			)
	return over


@frappe.whitelist()
def submit_receipt(purchase_order, rows, supplier_delivery_note=None, posting_date=None,
                   confirm_over_receipt=False):
	"""Record the delivery: build a Purchase Receipt and submit it.

	Submitting posts the PO Receiver to Intacct first. If Intacct rejects it, nothing
	stands here either — the storeman fixes it and submits again.

	Over-receipt is caught here first: the call returns what exceeds the order and writes
	nothing, and the screen re-calls with `confirm_over_receipt` once the storeman has
	said yes. Authorisation, if it is ever wanted, belongs at that confirmation.

	Confirming does NOT guarantee it lands. ERPNext enforces its own ceiling through
	Stock Settings' over-receipt allowance, which is 0 on this site by choice — so an
	excess is refused there, deliberately, and is managed by whoever owns that setting.
	This check exists so the storeman is told which line and by how much, in stock terms,
	before meeting a framework error that says neither.
	"""
	_guard()
	rows = _rows(rows)

	# Comes over the wire as a string from the browser, so it is read as one.
	confirmed = str(confirm_over_receipt).strip().lower() in ("1", "true", "yes")

	over = _over_receipts(purchase_order, rows)
	if over and not confirmed:
		return {"confirm_required": "over_receipt", "over": over}

	settings = frappe.get_cached_doc("Intacct Settings")
	order = frappe.get_doc("Purchase Order", purchase_order)

	receipt = frappe.new_doc("Purchase Receipt")
	receipt.company = order.company
	receipt.supplier = order.supplier
	receipt.posting_date = getdate(posting_date) if posting_date else getdate(nowdate())
	receipt.set_posting_time = 1
	if supplier_delivery_note:
		receipt.supplier_delivery_note = supplier_delivery_note

	for row in rows:
		accepted = flt(row.get("qty"))
		rejected = flt(row.get("rejected_qty"))
		if accepted <= 0 and rejected <= 0:
			continue

		po_item = row.get("purchase_order_item")
		if not po_item:
			frappe.throw("Every line must say which ordered line it is against.")

		ordered = frappe.db.get_value(
			"Purchase Order Item", po_item, ["item_code", "warehouse", "rate"], as_dict=True
		)
		if not ordered:
			frappe.throw(f"{po_item} is not a line on {purchase_order}.")

		if rejected > 0 and not settings.get("reject_warehouse"):
			frappe.throw(
				"A rejected quantity was captured but no receiving rejects warehouse is set. "
				"Set one on Intacct Settings — rejected stock must not go back into good stock."
			)

		receipt.append(
			"items",
			{
				"item_code": ordered.item_code,
				"purchase_order": purchase_order,
				"purchase_order_item": po_item,
				# ERPNext splits a delivery into accepted and rejected, and its own
				# validation wants the two to add up to what was received. Setting all
				# three keeps that arithmetic ours rather than inferred.
				"received_qty": accepted + rejected,
				"qty": accepted,
				"rejected_qty": rejected,
				"warehouse": row.get("warehouse") or ordered.warehouse,
				"rejected_warehouse": settings.get("reject_warehouse") if rejected > 0 else None,
				"rate": ordered.rate,
				"custom_intacct_lot": row.get("lot") or None,
			},
		)

	if not receipt.items:
		frappe.throw("Nothing was captured against this order.")

	receipt.insert()
	receipt.submit()

	return {
		"purchase_receipt": receipt.name,
		"intacct_key": receipt.get("custom_intacct_key"),
		"over_received": bool(over),
	}
