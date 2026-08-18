"""Shop-floor screens — the server side.

The one place custom screens are justified (docs/03-decisions.md, 2026-08-06):
ERPNext's stock forms are desk-shaped, and a mixer operator with gloves on wants a
scan, a number and a green button.

Nothing here posts to Intacct. Every function builds an ordinary Stock Entry and
submits it, so `postings.on_stock_entry_submit` fires exactly as it does from the
desk form — Intacct posts first, and a rejection rolls the whole thing back. One
posting path, two front doors. That is the decision this file exists to honour.
"""

import json

import frappe
from frappe.utils import flt

# Only movements. Adjustments and receipting belong to Intacct and are refused at
# validate anyway (postings.block_stock_adjustment / block_goods_receipt), but this
# tuple means the floor screens cannot even ask.
FLOOR_PURPOSES = ("Material Transfer for Manufacture", "Material Transfer")

# How many item matches a search returns. A phone screen shows about six.
SEARCH_LIMIT = 20


def _guard():
	"""Refuse anyone who could not make the movement from the desk either.

	A whitelisted method is callable by any logged-in user, so the screens' own
	navigation is not a permission check. `insert()` would catch it later — this
	catches it before the operator has typed anything.
	"""
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw("You do not have permission to record stock movements.")


def _rows(rows):
	"""Accept the lines either as JSON (from the browser) or already parsed."""
	if isinstance(rows, str):
		rows = json.loads(rows)
	if not rows:
		frappe.throw("Nothing to record — add at least one line.")
	return rows


def _warehouse_company(warehouse):
	"""The company owning a warehouse.

	Never defaulted: the company decides which Intacct entity the movement posts to,
	and a guessed one posts correctly-formed stock into the wrong set of books.
	"""
	company = frappe.db.get_value("Warehouse", warehouse, "company")
	if not company:
		frappe.throw(f"{warehouse} is not a warehouse on this site.")
	return company


# ──────────────────────────────────────────────────────────────────────────────
# Reading
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def bootstrap():
	"""Everything the screens need to open: warehouses, and whether posting is on.

	Warehouses come from Intacct and are mirrored read-only, so this is a straight
	list — no filtering by name pattern. A site that renames its WIP warehouses must
	not need a code change.
	"""
	_guard()

	warehouses = frappe.get_all(
		"Warehouse",
		filters={"is_group": 0, "disabled": 0},
		fields=["name", "company"],
		order_by="name",
	)

	settings = frappe.get_cached_doc("Intacct Settings")
	return {
		"warehouses": warehouses,
		# Shown as a standing warning on every screen. An operator working a full
		# shift into a system that is not posting would find out at month end.
		"posting_on": bool(settings.post_movements),
		"user": frappe.session.user,
	}


@frappe.whitelist()
def find_item(term, warehouse=None):
	"""Resolve a scan or a typed fragment to items, with what is on hand.

	Three passes, cheapest first: the code itself, then a barcode, then a search.
	The barcode pass is deliberate even though no item carries one yet — the day
	labels are printed, the screens already read them with no deploy.
	"""
	_guard()
	term = (term or "").strip()
	if not term:
		return []

	base = {"disabled": 0, "is_stock_item": 1}
	fields = ["name as item_code", "item_name", "stock_uom"]

	matches = frappe.get_all("Item", filters=dict(base, name=term), fields=fields)

	if not matches:
		coded = frappe.get_all(
			"Item Barcode", filters={"barcode": term}, fields=["parent"], limit=SEARCH_LIMIT
		)
		if coded:
			matches = frappe.get_all(
				"Item",
				filters=dict(base, name=["in", [row.parent for row in coded]]),
				fields=fields,
			)

	if not matches:
		matches = frappe.get_all(
			"Item",
			filters=base,
			or_filters={
				"name": ["like", f"%{term}%"],
				"item_name": ["like", f"%{term}%"],
			},
			fields=fields,
			order_by="name",
			limit=SEARCH_LIMIT,
		)

	if warehouse:
		for match in matches:
			match["actual_qty"] = flt(
				frappe.db.get_value(
					"Bin",
					{"item_code": match["item_code"], "warehouse": warehouse},
					"actual_qty",
				)
			)

	return matches


@frappe.whitelist()
def open_work_orders():
	"""The orders an operator can record against, newest first.

	Not Started and In Process only — a Completed order has nothing left to make,
	and a Stopped one was stopped deliberately.
	"""
	_guard()
	return frappe.get_all(
		"Work Order",
		filters={"docstatus": 1, "status": ["in", ["Not Started", "In Process"]]},
		fields=[
			"name",
			"production_item",
			"item_name",
			"qty",
			"produced_qty",
			"stock_uom",
			"bom_no",
			"source_warehouse",
			"wip_warehouse",
			"fg_warehouse",
			"company",
			"status",
		],
		order_by="creation desc",
		limit=50,
	)


@frappe.whitelist()
def work_order_lines(work_order, qty):
	"""What ERPNext says a run of this size consumes — for the operator to correct.

	The explosion is ERPNext's own (`make_stock_entry`), never ours. The recipe came
	from Intacct and the arithmetic belongs to the framework; our job is to put it on
	a phone and let the operator say what actually went in.
	"""
	_guard()
	qty = flt(qty)
	if qty <= 0:
		frappe.throw("Enter how much you actually made.")

	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	entry = frappe.get_doc(make_stock_entry(work_order, "Manufacture", qty))

	consumed, produced = [], None
	for row in entry.items:
		line = {
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"uom": row.uom,
			"s_warehouse": row.s_warehouse,
			"t_warehouse": row.t_warehouse,
		}
		if row.get("is_finished_item"):
			produced = line
		else:
			consumed.append(line)

	return {"consumed": consumed, "produced": produced, "company": entry.company}


# ──────────────────────────────────────────────────────────────────────────────
# Writing
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def submit_transfer(purpose, rows, work_order=None):
	"""Record a move: store to WIP, or warehouse to warehouse.

	One document per submit however many lines, the same as the desk form and the
	same as one ICTRANSFER in Intacct.
	"""
	_guard()
	if purpose not in FLOOR_PURPOSES:
		frappe.throw(f"{purpose} cannot be recorded from the floor screens.")

	rows = _rows(rows)
	company = _warehouse_company(rows[0].get("s_warehouse"))

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = purpose
	entry.purpose = purpose
	entry.company = company
	if work_order:
		# Traceability only. The movement is identical either way — the donor's guide
		# says so, and it stays true here.
		entry.work_order = work_order

	for row in rows:
		source = row.get("s_warehouse")
		target = row.get("t_warehouse")
		item_code = row.get("item_code")
		if not source or not target:
			frappe.throw("Every line needs a from and a to warehouse.")
		if source == target:
			frappe.throw(f"{item_code}: from and to are the same warehouse.")
		if flt(row.get("qty")) <= 0:
			frappe.throw(f"{item_code}: quantity must be more than zero.")

		entry.append(
			"items",
			{
				"item_code": item_code,
				"qty": flt(row.get("qty")),
				"s_warehouse": source,
				"t_warehouse": target,
			},
		)

	# No rate is set anywhere above. ERPNext values the movement at what the stock is
	# already worth, which is what Intacct told us. A floor screen never prices.
	entry.insert()
	entry.submit()

	return {"stock_entry": entry.name, "intacct_key": entry.get("custom_intacct_key")}


@frappe.whitelist()
def submit_manufacture(work_order, qty, rows):
	"""Record a production run against a works order.

	Consumption and production reach Intacct as one atomic operation, so a run can
	never half-record — that is `postings.post_stock_entry_manufacture`'s job. This
	only decides what was consumed.
	"""
	_guard()
	qty = flt(qty)
	if qty <= 0:
		frappe.throw("Enter how much you actually made.")

	rows = _rows(rows)

	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	entry = frappe.get_doc(make_stock_entry(work_order, "Manufacture", qty))

	# What the operator confirmed, keyed by item. A component can legitimately appear
	# twice in one explosion (same material, two warehouses), so quantities are queued
	# and applied one per matching row rather than to every row.
	confirmed = {}
	for row in rows:
		confirmed.setdefault(row.get("item_code"), []).append(flt(row.get("qty")))

	kept = []
	for line in entry.items:
		if line.get("is_finished_item"):
			kept.append(line)
			continue

		pending = confirmed.get(line.item_code)
		if not pending:
			# Not on the operator's list — that is what removing it from the screen,
			# or zeroing it, meant.
			continue

		line.qty = pending.pop(0)
		if flt(line.qty) > 0:
			kept.append(line)

	# Whatever is left in `confirmed` the recipe did not have: a substitute, or an
	# extra. It comes out of the same warehouse the run draws from.
	source = None
	for line in kept:
		if line.s_warehouse:
			source = line.s_warehouse
			break

	for item_code, quantities in confirmed.items():
		for quantity in quantities:
			if flt(quantity) <= 0:
				continue
			if not source:
				frappe.throw(f"{item_code}: no source warehouse to take it from.")
			kept.append(
				entry.append(
					"items",
					{"item_code": item_code, "qty": flt(quantity), "s_warehouse": source},
				)
			)

	if len(kept) < 2:
		frappe.throw("A production run needs at least one component and the finished item.")

	entry.items = []
	for index, line in enumerate(kept, start=1):
		line.idx = index
		entry.items.append(line)

	entry.insert()
	entry.submit()

	return {"stock_entry": entry.name, "intacct_key": entry.get("custom_intacct_key")}
