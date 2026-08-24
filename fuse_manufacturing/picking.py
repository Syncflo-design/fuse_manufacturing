"""Picking — find a sales order, open it, scan the goods out, process the delivery.

The mirror image of receiving.py, and deliberately the same shape: one API, two front
doors — the phone screen and the desk screen both call these functions. Neither posts to
Intacct itself. Each builds an ordinary Delivery Note and submits it, so
`postings.on_delivery_note_submit` fires and the shipper reaches Intacct before any stock
leaves here.

Sales orders are NEVER created here. They are mirrored from Intacct read-only; this module
only records what went out against them. The invoice is raised in Intacct against the
shipper this produces — nothing here touches value or the receivable.
"""

import json

import frappe
from frappe.utils import flt, getdate, nowdate

from fuse_manufacturing import scanning

# How many orders a search returns before the list stops being useful on a phone.
SEARCH_LIMIT = 50


def _guard():
	if not frappe.has_permission("Delivery Note", "create"):
		frappe.throw("You do not have permission to deliver goods.")


def _rows(rows):
	if isinstance(rows, str):
		rows = json.loads(rows)
	if not rows:
		frappe.throw("Nothing to deliver — capture at least one line.")
	return rows


# ──────────────────────────────────────────────────────────────────────────────
# Find
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def open_orders(term=None):
	"""Mirrored orders still waiting to go out.

	Matched on our number, Intacct's number and the customer, because the number on the
	paperwork in someone's hand could be any of the three.
	"""
	_guard()

	filters = {"docstatus": 1, "status": ("not in", ("Closed", "Completed")),
	           "custom_intacct_so_id": ("is", "set")}
	or_filters = None
	if term:
		like = f"%{term}%"
		or_filters = {
			"name": ("like", like),
			"custom_intacct_so_id": ("like", like),
			"customer": ("like", like),
			"customer_name": ("like", like),
		}

	orders = frappe.get_all(
		"Sales Order",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"custom_intacct_so_id",
			"customer",
			"customer_name",
			"delivery_date",
			"per_delivered",
		],
		order_by="delivery_date asc",
		limit_page_length=SEARCH_LIMIT,
	)

	# An order fully delivered has nothing left to pick. Filtered here rather than in the
	# query because per_delivered is maintained by ERPNext and rounds — 99.99% is done.
	return [order for order in orders if flt(order.per_delivered) < 99.99]


@frappe.whitelist()
def order_lines(sales_order):
	"""What is still to go out on one order, with what the picker has to supply.

	`outstanding` is ordered minus delivered, in stock units. `available` is what is
	actually on the shelf in that warehouse — a picker seeing "10 to pick, 4 available"
	stops and asks, instead of picking four and leaving a document that says ten.
	"""
	_guard()

	order = frappe.get_doc("Sales Order", sales_order)
	if not order.get("custom_intacct_so_id"):
		frappe.throw(
			f"{sales_order} did not come from Intacct. Only mirrored orders can be picked, "
			"because the delivery converts the Intacct document."
		)

	lines = []
	for row in order.items:
		outstanding = flt(row.qty) - flt(row.delivered_qty)
		if outstanding <= 0:
			continue

		item = frappe.db.get_value(
			"Item",
			row.item_code,
			[
				"item_name",
				"stock_uom",
				"custom_intacct_lot_tracked",
				"custom_intacct_bin_tracked",
				"inspection_required_before_delivery",
			],
			as_dict=True,
		)
		available = frappe.db.get_value(
			"Bin", {"item_code": row.item_code, "warehouse": row.warehouse}, "actual_qty"
		)

		lines.append(
			{
				"sales_order_item": row.name,
				"item_code": row.item_code,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"warehouse": row.warehouse,
				"ordered": flt(row.qty),
				"delivered": flt(row.delivered_qty),
				"outstanding": outstanding,
				"available": flt(available),
				# What the screen must ask for on this line. Lot and bin are driven by
				# Intacct's own flags, so a site that tracks neither is never asked for
				# either; the inspection is driven by the item's specification.
				"needs_lot": bool(item.custom_intacct_lot_tracked),
				"needs_bin": bool(item.custom_intacct_bin_tracked),
				"needs_inspection": bool(item.inspection_required_before_delivery),
			}
		)

	return {
		"sales_order": order.name,
		"intacct_so": order.custom_intacct_so_id,
		"customer": order.customer_name or order.customer,
		"customer_id": order.customer,
		"lines": lines,
		# Shown as a standing warning on the screen. Someone picking a full shift into a
		# system that is not posting would find out at month end.
		"posting_on": bool(frappe.db.get_single_value("Intacct Settings", "post_movements")),
	}


@frappe.whitelist()
def scan(sales_order, term):
	"""What was just scanned, answered in the context of this order.

	Resolution itself is `scanning.resolve_scan` — the same door every other screen uses,
	so a pallet label scanned here is recognised as a pallet rather than reported as an
	unknown item code. What this adds is the order: an item is only useful if it is
	actually still to go out on the order in front of you.
	"""
	_guard()
	found = scanning.resolve_scan(term)

	if found["type"] != "item":
		# Handed back untouched. The screen decides what a bin or a pallet means during
		# picking; this function's job is to say what it was, not to refuse it.
		return {"scan": found, "lines": []}

	lines = [
		line
		for line in order_lines(sales_order)["lines"]
		if line["item_code"] == found["value"]
	]

	if not lines:
		return {
			"scan": found,
			"lines": [],
			"message": f"{found['value']} is not outstanding on this order.",
		}

	# Several lines for one item is normal — different warehouses, different dates. The
	# screen asks which; it is not something to resolve by picking the first.
	return {"scan": found, "lines": lines}


# ──────────────────────────────────────────────────────────────────────────────
# Record
# ──────────────────────────────────────────────────────────────────────────────


def _over_deliveries(sales_order, rows):
	"""Lines picked for more than is outstanding, before anything is written.

	Reported rather than refused outright: over-delivery is a real thing that happens, and
	the person holding the stock is better placed to judge it than this function. What is
	not acceptable is finding out afterwards.
	"""
	outstanding = {
		line["sales_order_item"]: line["outstanding"] for line in order_lines(sales_order)["lines"]
	}

	over = []
	for row in rows:
		line = row.get("sales_order_item")
		qty = flt(row.get("qty"))
		if not line or qty <= 0:
			continue
		remaining = flt(outstanding.get(line))
		if qty > remaining:
			over.append(
				{
					"sales_order_item": line,
					"item_code": row.get("item_code"),
					"picked": qty,
					"outstanding": remaining,
					"excess": qty - remaining,
				}
			)
	return over


@frappe.whitelist()
def submit_delivery(sales_order, rows, posting_date=None, confirm_over_delivery=False):
	"""Record the pick: build a Delivery Note and submit it.

	Submitting posts the shipper to Intacct first. If Intacct rejects it, nothing stands
	here either — the picker fixes it and submits again.

	Over-delivery is caught here first: the call returns what exceeds the order and writes
	nothing, and the screen re-calls with `confirm_over_delivery` once the picker has said
	yes. Confirming does not guarantee it lands — ERPNext enforces its own ceiling through
	Stock Settings' over-delivery allowance, and an excess beyond that is refused there.
	This check exists so the picker is told which line and by how much, in stock terms,
	before meeting a framework error that says neither.
	"""
	_guard()
	rows = _rows(rows)

	# Comes over the wire as a string from the browser, so it is read as one.
	confirmed = str(confirm_over_delivery).strip().lower() in ("1", "true", "yes")

	over = _over_deliveries(sales_order, rows)
	if over and not confirmed:
		return {"confirm_required": "over_delivery", "over": over}

	order = frappe.get_doc("Sales Order", sales_order)

	note = frappe.new_doc("Delivery Note")
	note.company = order.company
	note.customer = order.customer
	note.posting_date = getdate(posting_date) if posting_date else getdate(nowdate())
	note.set_posting_time = 1

	for row in rows:
		qty = flt(row.get("qty"))
		if qty <= 0:
			continue

		so_item = row.get("sales_order_item")
		if not so_item:
			frappe.throw("Every line must say which ordered line it is against.")

		ordered = frappe.db.get_value(
			"Sales Order Item", so_item, ["item_code", "warehouse", "rate"], as_dict=True
		)
		if not ordered:
			frappe.throw(f"{so_item} is not a line on {sales_order}.")

		note.append(
			"items",
			{
				"item_code": ordered.item_code,
				# Both links matter: `against_sales_order` is what the posting reads to
				# find the Intacct document, and `so_detail` is what it converts against.
				"against_sales_order": sales_order,
				"so_detail": so_item,
				"qty": qty,
				"warehouse": row.get("warehouse") or ordered.warehouse,
				"rate": ordered.rate,
				"custom_intacct_lot": row.get("lot") or None,
				"custom_intacct_bin": row.get("bin") or None,
			},
		)

	if not note.items:
		frappe.throw("Nothing was captured against this order.")

	note.insert()

	# Between insert and submit, deliberately. A Quality Inspection stores the document it
	# belongs to, so the document has to exist — and the submit has to be the thing that
	# fails if a required inspection is missing or did not pass, rather than goods leaving
	# and a record being written afterwards.
	from fuse_manufacturing import quality

	quality.attach_inspections(
		note,
		{row.get("sales_order_item"): row for row in rows},
		"so_detail",
	)

	note.submit()

	return {
		"delivery_note": note.name,
		"intacct_key": note.get("custom_intacct_key"),
		"over_delivered": bool(over),
	}
