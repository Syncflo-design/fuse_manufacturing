"""Demand netting and BOM explosion, with no Frappe and no site.

The reorder question, per item, is the one the planner already answers in a spreadsheet:

    net requirement = demand + target stock - (on hand + already coming)

What the spreadsheet cannot do is carry that answer DOWN the bill of materials. A finished
tread that is short creates demand for its compound; the compound that is short, once its
own stock and open works orders are taken off, creates demand for raw rubber and carbon
black. That is what `explode` does, level by level, netting at every level — the standard
MRP shape, kept deliberately small.

Pure functions over plain dicts so the arithmetic can be tested in a second without a
site. demand.py loads the inputs from ERPNext and formats the output; nothing here knows
what a DocType is.
"""

# Deeper than any real recipe. A BOM that references itself through a chain of
# sub-assemblies would otherwise loop forever; past this depth the walk stops and the
# item is left at the level it had.
MAX_DEPTH = 25

MAKE = "Make"
BUY = "Buy"

FINISHED = "Finished"
SUB_ASSEMBLY = "Sub-assembly"
RAW_MATERIAL = "Raw material"


def low_level_codes(top_items, boms):
	"""The deepest level each item appears at, starting from `top_items` at level 0.

	An item that is both a direct component of a finished good AND a component of one of
	its sub-assemblies takes the deeper level. Netting in ascending level order then
	guarantees every parent has been resolved before a child's requirement is summed —
	the low-level-code rule every MRP run rests on.

	`boms` is {parent_item: [(child_item, qty_per_unit_of_parent), ...]}.
	"""
	levels = {}
	stack = [(item, 0) for item in top_items]
	while stack:
		item, level = stack.pop()
		if level > MAX_DEPTH:
			continue
		if levels.get(item, -1) >= level:
			continue
		levels[item] = level
		for child, _qty in boms.get(item, ()):
			stack.append((child, level + 1))
	return levels


def explode(demand, boms, on_hand=None, target=None, in_progress=None, on_order=None):
	"""Net requirements at every level of the bill of materials.

	demand       {item: qty}   what customers want, in stock units — level 0 only
	boms         {parent: [(child, qty_per_unit), ...]}   default BOM of every made item
	on_hand      {item: qty}   stock counted as available
	target       {item: qty}   stock level to keep, on top of demand (the spreadsheet's Max)
	in_progress  {item: qty}   still to come off open works orders (made items)
	on_order     {item: qty}   still to arrive on open purchase orders (bought items)

	Returns one row per item touched, in level order. `required` is what parents ask for,
	`gross` is that plus customer demand, `net` is what has to be made or bought after
	stock and open orders are taken off. A net of zero still returns a row, so the planner
	sees WHY nothing is needed rather than an item simply missing from the list.

	Supply is taken by kind: a made item is covered by stock and works orders, a bought
	item by stock and purchase orders. An item with a BOM is made; without one it is
	bought. Netting uses the NET figure for children, not the gross — a compound already
	on the shelf does not generate demand for the rubber that went into it.
	"""
	on_hand = on_hand or {}
	target = target or {}
	in_progress = in_progress or {}
	on_order = on_order or {}

	levels = low_level_codes(list(demand), boms)
	required = {}
	rows = []

	for item in sorted(levels, key=lambda code: (levels[code], code)):
		level = levels[item]
		kind = MAKE if item in boms else BUY
		coming = in_progress.get(item, 0.0) if kind == MAKE else on_order.get(item, 0.0)

		# Customer demand counts wherever the item sits. A compound sold by the kilo AND
		# used in a tread takes a deeper level because of the tread, and must not lose
		# its own orders for it.
		customer = demand.get(item, 0.0)
		from_parents = required.get(item, 0.0)
		gross = customer + from_parents
		stock = on_hand.get(item, 0.0)
		keep = target.get(item, 0.0)
		net = max(0.0, gross + keep - stock - coming)

		rows.append(
			{
				"item_code": item,
				"level": level,
				"kind": kind,
				"stage": stage_of(level, kind, customer),
				"demand": customer,
				"required": from_parents,
				"gross": gross,
				"target": keep,
				"on_hand": stock,
				"in_progress": coming if kind == MAKE else 0.0,
				"on_order": coming if kind == BUY else 0.0,
				"net": net,
			}
		)

		if net and kind == MAKE:
			for child, qty_per_unit in boms[item]:
				required[child] = required.get(child, 0.0) + net * qty_per_unit

	return rows


def stage_of(level, kind, customer_demand=0.0):
	"""Where an item sits for the planner: sold, mixed, or bought.

	Anything a customer ordered is finished goods, whether it is made, a bought-in resale
	line, or a compound that also goes into a tread. Below that, anything with a recipe
	is a sub-assembly and anything without one is a raw material.
	"""
	if level == 0 or customer_demand:
		return FINISHED
	return SUB_ASSEMBLY if kind == MAKE else RAW_MATERIAL
