"""What is on order from customers, and what that means for the shelf.

Two reports sit on this: Outstanding Orders (the order book, line by line, by item) and
Item Demand (the same book netted against stock and exploded through the BOMs). They share
the order query so that an order excluded from one is excluded from the other — the
planner ticks an order off once, and every figure downstream agrees.

Orders are mirrored from Intacct and are read-only here. The one thing a planner CAN
change is whether an order counts, and that is a flag on the order rather than a report
filter so it holds between runs and between people.
"""

import frappe
from frappe import _

from fuse_manufacturing import planning

# Who may take an order in or out of the plan. Wider than who may raise a works order:
# the person deciding what to make is often not the person recording that it was made.
PLANNING_ROLES = (
	"System Manager",
	"Manufacturing Manager",
	"Manufacturing User",
	"Stock Manager",
	"Stock Controller",
	"Sales Manager",
)

EXCLUDE_FIELD = "custom_exclude_from_planning"

# Order states that still owe the customer something. Closed is a decision; Completed is
# delivered; anything else with quantity left is live.
OPEN_STATUSES = ("Closed", "Completed", "Cancelled")


def open_order_lines(filters, include_excluded=False):
	"""Every undelivered sales-order line the filters allow, in stock units.

	`excluded` rows are those the planner has taken out. They are returned only when asked
	for, so the order book can show them greyed while the demand figures leave them out.
	"""
	conditions = [
		"so.docstatus = 1",
		"so.status not in %(closed)s",
		"(soi.qty - soi.delivered_qty) > 0",
	]
	values = {"closed": OPEN_STATUSES}

	if filters.get("company"):
		conditions.append("so.company = %(company)s")
		values["company"] = filters.company
	if filters.get("customer"):
		conditions.append("so.customer = %(customer)s")
		values["customer"] = filters.customer
	if filters.get("item_code"):
		conditions.append("soi.item_code = %(item_code)s")
		values["item_code"] = filters.item_code
	if filters.get("item_group"):
		conditions.append("item.item_group = %(item_group)s")
		values["item_group"] = filters.item_group
	if filters.get("due_before"):
		conditions.append("soi.delivery_date <= %(due_before)s")
		values["due_before"] = filters.due_before
	if not include_excluded:
		conditions.append(f"ifnull(so.{EXCLUDE_FIELD}, 0) = 0")

	return frappe.db.sql(
		f"""
		select
			so.name as sales_order, so.customer, so.customer_name, so.transaction_date,
			so.po_no, so.custom_intacct_so_id as intacct_order,
			ifnull(so.{EXCLUDE_FIELD}, 0) as excluded,
			soi.item_code, soi.item_name, soi.delivery_date, soi.warehouse,
			soi.qty, soi.delivered_qty,
			(soi.qty - soi.delivered_qty) as outstanding,
			(soi.qty - soi.delivered_qty) * ifnull(soi.conversion_factor, 1) as outstanding_stock_qty,
			soi.uom, soi.stock_uom
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` item on item.name = soi.item_code
		where {" and ".join(conditions)}
		order by soi.item_code, soi.delivery_date, so.name
		""",
		values,
		as_dict=True,
	)


def excluded_order_count(filters):
	"""How many open orders the planner has taken out, so a report can say so."""
	rows = open_order_lines(filters, include_excluded=True)
	return len({row.sales_order for row in rows if row.excluded})


@frappe.whitelist()
def set_planning_exclusion(sales_order, excluded):
	"""Take an order out of the plan, or put it back.

	Written straight to the field rather than through the document: the order is
	submitted and mirrored, and nothing else about it may change. The flag survives the
	hourly sync because a mirrored order is never rewritten once it exists.
	"""
	if not any(role in PLANNING_ROLES for role in frappe.get_roles()):
		frappe.throw(_("You do not have permission to change what is planned."), frappe.PermissionError)
	if not frappe.db.exists("Sales Order", {"name": sales_order, "docstatus": 1}):
		frappe.throw(_("Sales Order {0} is not a submitted order.").format(sales_order))

	flag = 1 if frappe.utils.cint(excluded) else 0
	frappe.db.set_value("Sales Order", sales_order, EXCLUDE_FIELD, flag)
	frappe.get_doc("Sales Order", sales_order).add_comment(
		"Info",
		_("Excluded from planning") if flag else _("Included in planning"),
	)
	return flag


# ---------------------------------------------------------------------------------------
# Inputs for the explosion


def demand_by_item(filters):
	"""Open customer demand per item, in stock units, excluded orders left out."""
	demand = {}
	for row in open_order_lines(filters):
		demand[row.item_code] = demand.get(row.item_code, 0.0) + float(row.outstanding_stock_qty or 0)
	return demand


def default_boms(company):
	"""{parent item: [(child item, qty per unit of parent), ...]} for every default BOM.

	One query for the whole site rather than a walk per item: 900 BOMs read in one go is
	nothing, and the explosion needs them all to find the levels anyway. Only stock items
	that go into manufacturing count — a BOM line for a non-stock overhead is not a
	requirement anyone can buy.
	"""
	rows = frappe.db.sql(
		"""
		select bom.item as parent, bi.item_code as child, bi.qty_consumed_per_unit as qty_per_unit
		from `tabBOM Item` bi
		inner join `tabBOM` bom on bom.name = bi.parent
		where bom.docstatus = 1 and bom.is_active = 1 and bom.is_default = 1
			and bom.company = %(company)s
			and ifnull(bi.include_item_in_manufacturing, 1) = 1
			and ifnull(bi.is_stock_item, 1) = 1
		""",
		{"company": company},
		as_dict=True,
	)
	boms = {}
	for row in rows:
		boms.setdefault(row.parent, []).append((row.child, float(row.qty_per_unit or 0)))
	return boms


def on_hand_by_item(company, warehouses=None):
	"""Stock per item across the warehouses that count as available.

	No warehouse chosen means every non-group warehouse in the company except transit —
	stock on a truck is not on the shelf. Consignment stock at customers, quality hold and
	the like are excluded by choosing warehouses, until the site has warehouse types to
	filter on.
	"""
	conditions = ["bin.actual_qty != 0", "wh.company = %(company)s", "wh.is_group = 0"]
	values = {"company": company}
	if warehouses:
		conditions.append("bin.warehouse in %(warehouses)s")
		values["warehouses"] = tuple(warehouses)
	else:
		conditions.append("ifnull(wh.warehouse_type, '') != 'Transit'")

	rows = frappe.db.sql(
		f"""
		select bin.item_code, sum(bin.actual_qty) as qty
		from `tabBin` bin
		inner join `tabWarehouse` wh on wh.name = bin.warehouse
		where {" and ".join(conditions)}
		group by bin.item_code
		""",
		values,
		as_dict=True,
	)
	return {row.item_code: float(row.qty or 0) for row in rows}


def target_by_item(company, warehouses=None):
	"""The level to keep per item — ERPNext's Item Reorder rows, summed over the warehouses.

	This is the spreadsheet's Max column. Whether it is typed here or synced from Intacct's
	reorder settings is a client decision; the report reads the same table either way.
	"""
	conditions = ["ir.warehouse_reorder_level > 0", "wh.company = %(company)s"]
	values = {"company": company}
	if warehouses:
		conditions.append("ir.warehouse in %(warehouses)s")
		values["warehouses"] = tuple(warehouses)

	rows = frappe.db.sql(
		f"""
		select ir.parent as item_code, sum(ir.warehouse_reorder_level) as qty
		from `tabItem Reorder` ir
		inner join `tabWarehouse` wh on wh.name = ir.warehouse
		where {" and ".join(conditions)}
		group by ir.parent
		""",
		values,
		as_dict=True,
	)
	return {row.item_code: float(row.qty or 0) for row in rows}


def in_progress_by_item(company):
	"""What open works orders still owe, per item."""
	rows = frappe.db.sql(
		"""
		select production_item as item_code, sum(qty - produced_qty) as qty
		from `tabWork Order`
		where docstatus = 1 and company = %(company)s
			and status not in ('Completed', 'Stopped', 'Closed', 'Cancelled')
			and qty > produced_qty
		group by production_item
		""",
		{"company": company},
		as_dict=True,
	)
	return {row.item_code: float(row.qty or 0) for row in rows}


def on_order_by_item(company):
	"""What open purchase orders still owe, per item, in stock units."""
	rows = frappe.db.sql(
		"""
		select poi.item_code, sum((poi.qty - poi.received_qty) * ifnull(poi.conversion_factor, 1)) as qty
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and po.company = %(company)s
			and po.status not in ('Closed', 'Completed')
			and poi.qty > poi.received_qty
		group by poi.item_code
		""",
		{"company": company},
		as_dict=True,
	)
	return {row.item_code: float(row.qty or 0) for row in rows}


def item_demand(filters):
	"""The exploded, netted requirement list the Item Demand report shows."""
	company = filters.company
	warehouses = filters.get("warehouses") or None
	if isinstance(warehouses, str):
		warehouses = frappe.parse_json(warehouses)

	rows = planning.explode(
		demand_by_item(filters),
		default_boms(company),
		on_hand=on_hand_by_item(company, warehouses),
		target=target_by_item(company, warehouses),
		in_progress=in_progress_by_item(company),
		on_order=on_order_by_item(company),
	)
	if not rows:
		return rows

	names = {
		item.name: item
		for item in frappe.get_all(
			"Item",
			filters={"name": ("in", [row["item_code"] for row in rows])},
			fields=["name", "item_name", "stock_uom", "item_group"],
		)
	}
	for row in rows:
		item = names.get(row["item_code"])
		row["item_name"] = item.item_name if item else ""
		row["stock_uom"] = item.stock_uom if item else ""
		row["item_group"] = item.item_group if item else ""
	return rows
