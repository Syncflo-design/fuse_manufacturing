"""Item Demand — what to make and what to buy, from the order book down to raw materials.

Takes the open orders (less any the planner excluded), adds the stock level each item is
kept at, takes off what is on the shelf and what is already on a works order or a
purchase order, and carries the shortfall down the BOMs: finished goods, then the
compounds they need, then the raw materials the compounds need. Each level is netted
before the next is asked for, so compound already mixed does not create demand for the
rubber that went into it.

The Stage filter is how the planner reads it in three passes — finished goods to decide
what to make, sub-assemblies to decide what to mix, raw materials to decide what to buy.
The arithmetic lives in planning.py and is tested without a site.
"""

import frappe
from frappe import _

from fuse_manufacturing import demand


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = demand.item_demand(filters)

	stage = filters.get("stage")
	if stage and stage != "All":
		rows = [row for row in rows if row["stage"] == stage]
	if filters.get("shortages_only"):
		rows = [row for row in rows if row["net"] > 0]

	return get_columns(), rows, message(filters)


def get_columns():
	return [
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 110},
		{"label": _("Make / Buy"), "fieldname": "kind", "fieldtype": "Data", "width": 90},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 240},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link",
		 "options": "Item Group", "width": 150},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Data", "width": 90},
		{"label": _("Customer Demand"), "fieldname": "demand", "fieldtype": "Float", "width": 120},
		{"label": _("Needed by Parents"), "fieldname": "required", "fieldtype": "Float", "width": 130},
		{"label": _("Gross"), "fieldname": "gross", "fieldtype": "Float", "width": 100},
		{"label": _("Target Stock"), "fieldname": "target", "fieldtype": "Float", "width": 110},
		{"label": _("On Hand"), "fieldname": "on_hand", "fieldtype": "Float", "width": 110},
		{"label": _("On Works Orders"), "fieldname": "in_progress", "fieldtype": "Float", "width": 125},
		{"label": _("On Purchase Orders"), "fieldname": "on_order", "fieldtype": "Float", "width": 140},
		{"label": _("Net Requirement"), "fieldname": "net", "fieldtype": "Float", "width": 130},
		{"label": _("Level"), "fieldname": "level", "fieldtype": "Int", "width": 60},
	]


def message(filters):
	excluded = demand.excluded_order_count(filters)
	warehouses = filters.get("warehouses")
	if isinstance(warehouses, str):
		warehouses = frappe.parse_json(warehouses)
	where = (
		_("stock counted in {0} selected warehouse(s)").format(len(warehouses))
		if warehouses
		else _("stock counted in every warehouse except transit")
	)
	return _("{0} order(s) excluded from planning; {1}. Net = demand + target - on hand - open orders.").format(
		excluded, where
	)
