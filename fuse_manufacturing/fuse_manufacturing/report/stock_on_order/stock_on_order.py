"""Stock on Order — what suppliers still owe us, line by line.

Written rather than reusing ERPNext's Purchase Order Analysis, because that report is
built for a business that receipts and bills in ERPNext. Here it does neither: goods are
received in Intacct and invoices are raised there, so Received Qty, Billed Amount and
Amount to Bill are permanently zero — and its chart plots Amount to Bill, which is why it
draws one flat ring that says nothing.

What a stock controller actually needs is narrower: what is still coming, to which
warehouse, and when it was due. That is this.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Due"), "fieldname": "schedule_date", "fieldtype": "Date", "width": 95},
		{"label": _("Overdue"), "fieldname": "overdue_by", "fieldtype": "Data", "width": 90},
		{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link",
		 "options": "Purchase Order", "width": 150},
		{"label": _("Intacct PO"), "fieldname": "intacct_po", "fieldtype": "Data", "width": 190},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link",
		 "options": "Supplier", "width": 200},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link",
		 "options": "Item", "width": 130},
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 220},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link",
		 "options": "Warehouse", "width": 210},
		{"label": _("On Order"), "fieldname": "qty", "fieldtype": "Float", "width": 105},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 90},
	]


def get_data(filters):
	conditions = ["po.docstatus = 1", "po.status != 'Closed'", "po.custom_intacct_po_id is not null"]
	values = {}

	if filters.get("company"):
		conditions.append("po.company = %(company)s")
		values["company"] = filters.company
	if filters.get("supplier"):
		conditions.append("po.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("warehouse"):
		conditions.append("item.warehouse = %(warehouse)s")
		values["warehouse"] = filters.warehouse
	if filters.get("item_code"):
		conditions.append("item.item_code = %(item_code)s")
		values["item_code"] = filters.item_code
	# Deliberately a "due before" rather than a from/to range. The question this report
	# answers is "what is coming", and nobody asks that about a window that has closed.
	if filters.get("due_before"):
		conditions.append("item.schedule_date <= %(due_before)s")
		values["due_before"] = filters.due_before
	if filters.get("overdue_only"):
		conditions.append("item.schedule_date < %(today)s")
		values["today"] = frappe.utils.nowdate()

	rows = frappe.db.sql(
		"""
		select
			item.schedule_date, item.item_code, item.item_name, item.warehouse,
			item.qty, item.uom, po.name as purchase_order, po.supplier,
			po.custom_intacct_po_id as intacct_po
		from `tabPurchase Order Item` item
		inner join `tabPurchase Order` po on po.name = item.parent
		where {conditions}
		order by item.schedule_date asc, po.name asc
		""".format(conditions=" and ".join(conditions)),
		values,
		as_dict=True,
	)

	today = frappe.utils.getdate()
	for row in rows:
		days = frappe.utils.date_diff(today, row.schedule_date) if row.schedule_date else 0
		# Shown as a word rather than a number so it reads without a legend. A negative
		# figure meaning "not yet due" is the kind of thing people misread at a glance.
		row.overdue_by = f"{days} days" if days > 0 else ""

	return rows
