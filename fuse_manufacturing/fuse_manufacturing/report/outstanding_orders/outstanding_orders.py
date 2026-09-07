"""Outstanding Orders — the customer order book, by item, with the orders under each.

The planner's starting point: what is still owed to customers, grouped the way the
spreadsheet they use today groups it — item first, orders beneath, a total per item. From
here they take orders in or out of the plan, then move on to Item Demand, which nets the
same book against stock and carries it down the BOMs.

Tree rather than flat so the item totals are the thing you see first and the order
detail is a click away. Excluded orders are shown greyed rather than hidden: an order
that has vanished from the list is a question, an order shown as excluded is an answer.
"""

import frappe
from frappe import _

from fuse_manufacturing import demand


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = demand.open_order_lines(filters, include_excluded=True)
	return get_columns(), build_tree(rows), message(rows)


def get_columns():
	return [
		{"label": _("Item / Order"), "fieldname": "name", "fieldtype": "Data", "width": 200},
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 240},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 220},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link",
		 "options": "Sales Order", "width": 150},
		{"label": _("Intacct Order"), "fieldname": "intacct_order", "fieldtype": "Data", "width": 180},
		{"label": _("Customer Ref"), "fieldname": "po_no", "fieldtype": "Data", "width": 120},
		{"label": _("Ordered On"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
		{"label": _("Due"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 100},
		{"label": _("Ordered"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{"label": _("Delivered"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Float", "width": 110},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 90},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link",
		 "options": "Warehouse", "width": 200},
		{"label": _("Planning"), "fieldname": "planning", "fieldtype": "Data", "width": 110},
	]


def build_tree(rows):
	"""Item rows at the top level, order lines beneath, item totals over included lines only."""
	by_item = {}
	for row in rows:
		by_item.setdefault(row.item_code, []).append(row)

	data = []
	for item_code, lines in by_item.items():
		included = [line for line in lines if not line.excluded]
		orders = {line.sales_order for line in included}
		data.append(
			{
				"name": item_code,
				"parent_name": None,
				"indent": 0,
				"is_item": 1,
				"item_code": item_code,
				"item_name": lines[0].item_name,
				"customer_name": _("{0} order(s)").format(len(orders)),
				"outstanding": sum(float(line.outstanding or 0) for line in included),
				"uom": lines[0].uom,
			}
		)
		for index, line in enumerate(lines):
			data.append(
				{
					"name": f"{line.sales_order}#{index}",
					"parent_name": item_code,
					"indent": 1,
					"is_item": 0,
					"item_code": line.item_code,
					"item_name": "",
					"customer_name": line.customer_name,
					"sales_order": line.sales_order,
					"intacct_order": line.intacct_order,
					"po_no": line.po_no,
					"transaction_date": line.transaction_date,
					"delivery_date": line.delivery_date,
					"qty": line.qty,
					"delivered_qty": line.delivered_qty,
					"outstanding": line.outstanding,
					"uom": line.uom,
					"warehouse": line.warehouse,
					"excluded": int(line.excluded or 0),
					# Rendered as the toggle by the report's formatter.
					"planning": _("Excluded") if line.excluded else _("Included"),
				}
			)
	return data


def message(rows):
	orders = {row.sales_order for row in rows}
	excluded = {row.sales_order for row in rows if row.excluded}
	return _("{0} open order(s), {1} excluded from planning.").format(len(orders), len(excluded))
