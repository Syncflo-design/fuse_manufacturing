"""Custom fields the integration needs on ERPNext's own DocTypes.

These are added as custom fields rather than by editing ERPNext, so they survive
upgrades. They exist for one reason: to hold the Intacct identity of a record, so a
later sync or posting can find it again without guessing from the name.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Item": [
		{
			"fieldname": "custom_intacct_section",
			"fieldtype": "Section Break",
			"label": "Intacct",
			"insert_after": "stock_uom",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_intacct_item_id",
			"fieldtype": "Data",
			"label": "Intacct Item ID",
			"insert_after": "custom_intacct_section",
			"read_only": 1,
			"unique": 1,
			"description": "Intacct ITEMID. The join key for every posting.",
		},
		{
			"fieldname": "custom_intacct_recordno",
			"fieldtype": "Data",
			"label": "Intacct RECORDNO",
			"insert_after": "custom_intacct_item_id",
			"read_only": 1,
		},
		{
			"fieldname": "custom_intacct_item_type",
			"fieldtype": "Data",
			"label": "Intacct Item Type",
			"insert_after": "custom_intacct_recordno",
			"read_only": 1,
			"description": "Raw ITEMTYPE from Intacct. Drives is_stock_item — Inventory and Stockable Kit hold stock, a plain Kit does not.",
		},
		{
			"fieldname": "custom_intacct_bin_tracked",
			"fieldtype": "Check",
			"label": "Intacct Bin Tracked",
			"insert_after": "custom_intacct_recordno",
			"read_only": 1,
			"description": "ENABLE_BINS on the Intacct item. A movement of a bin-enabled item is rejected unless it carries a bin.",
		},
	],
	"Warehouse": [
		{
			"fieldname": "custom_intacct_section",
			"fieldtype": "Section Break",
			"label": "Intacct",
			"insert_after": "company",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_intacct_warehouse_id",
			"fieldtype": "Data",
			"label": "Intacct Warehouse ID",
			"insert_after": "custom_intacct_section",
			"read_only": 1,
			"description": "WAREHOUSEID — how bins, stock and transaction lines refer to this warehouse.",
		},
		{
			"fieldname": "custom_intacct_location_id",
			"fieldtype": "Data",
			"label": "Intacct Location ID",
			"insert_after": "custom_intacct_warehouse_id",
			"read_only": 1,
			"description": "LOC.LOCATIONID — the warehouse's location. Note Intacct's own LOCATIONID field on WAREHOUSE is a duplicate of WAREHOUSEID, not the location.",
		},
		{
			"fieldname": "custom_intacct_entity_id",
			"fieldtype": "Data",
			"label": "Intacct Entity ID",
			"insert_after": "custom_intacct_location_id",
			"read_only": 1,
			"description": "MEGAENTITYID — the entity this warehouse belongs to. Blank means top-level, shared by all entities.",
		},
		{
			"fieldname": "custom_intacct_default_bin",
			"fieldtype": "Data",
			"label": "Intacct Default Bin",
			"insert_after": "custom_intacct_location_id",
			"read_only": 1,
			"description": "Lowest active BINID on this warehouse, stamped onto movements of bin-enabled items.",
		},
		{
			"fieldname": "custom_intacct_recordno",
			"fieldtype": "Data",
			"label": "Intacct RECORDNO",
			"insert_after": "custom_intacct_default_bin",
			"read_only": 1,
		},
	],
	"BOM": [
		{
			"fieldname": "custom_intacct_signature",
			"fieldtype": "Data",
			"label": "Intacct Recipe Signature",
			"insert_after": "item",
			"read_only": 1,
			"hidden": 1,
			"allow_on_submit": 1,
			"description": "SHA1 of the Intacct kit recipe this BOM was built from. Lets the sync tell a changed recipe from an unchanged one, so it does not cancel and rebuild every BOM on every run. Hashed because a real compound recipe runs well past a Data field's 140 characters.",
		},
	],
	"Stock Entry": [
		{
			"fieldname": "custom_intacct_section",
			"fieldtype": "Section Break",
			"label": "Intacct",
			"insert_after": "posting_time",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_intacct_key",
			"fieldtype": "Data",
			"label": "Intacct Key",
			"insert_after": "custom_intacct_section",
			"read_only": 1,
			"allow_on_submit": 1,
			"description": "Key of the Intacct document(s) this movement created. A production run makes two — a backflush decrease and a run increase — so this can hold both. Its presence is what makes a cancel reverse rather than simply cancel.",
		},
		{
			"fieldname": "custom_intacct_posted_on",
			"fieldtype": "Datetime",
			"label": "Posted to Intacct",
			"insert_after": "custom_intacct_key",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "custom_intacct_reversal_key",
			"fieldtype": "Data",
			"label": "Intacct Reversal Key",
			"insert_after": "custom_intacct_posted_on",
			"read_only": 1,
			"allow_on_submit": 1,
			"description": "Key of the Intacct document(s) that undid this movement. Intacct keeps both the original and the reversal — nothing is deleted. Its presence blocks a second reversal.",
		},
		{
			"fieldname": "custom_intacct_reversed_on",
			"fieldtype": "Datetime",
			"label": "Reversed in Intacct",
			"insert_after": "custom_intacct_reversal_key",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	],
	"Purchase Order": [
		{
			"fieldname": "custom_intacct_po_id",
			"fieldtype": "Data",
			"label": "Intacct PO",
			"insert_after": "supplier",
			"read_only": 1,
			"unique": 1,
			"allow_on_submit": 1,
			"description": "DOCID of the Intacct purchase order this mirrors. These orders are read-only — they exist so stock on order reaches projections and demand reporting. Receipting happens in Intacct.",
		},
		{
			"fieldname": "custom_intacct_synced_on",
			"fieldtype": "Datetime",
			"label": "Synced from Intacct",
			"insert_after": "custom_intacct_po_id",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	],
	"Supplier": [
		{
			"fieldname": "custom_intacct_vendor_id",
			"fieldtype": "Data",
			"label": "Intacct Vendor ID",
			"insert_after": "supplier_name",
			"read_only": 1,
			"unique": 1,
			"description": "VENDORID. Purchase order lines carry the supplier as this code, so it is the join back to Intacct — the name is not unique and changes.",
		},
		{
			"fieldname": "custom_intacct_recordno",
			"fieldtype": "Data",
			"label": "Intacct Record No",
			"insert_after": "custom_intacct_vendor_id",
			"read_only": 1,
			"hidden": 1,
		},
	],
	"Item Group": [
		{
			"fieldname": "custom_intacct_product_line",
			"fieldtype": "Data",
			"label": "Intacct Product Line",
			"insert_after": "item_group_name",
			"read_only": 1,
			"unique": 1,
			"description": "PRODUCTLINEID. Item Groups mirror Intacct's product line tree so items are filed the way Intacct files them.",
		},
	],
	"Company": [
		{
			"fieldname": "custom_intacct_entity_id",
			"fieldtype": "Data",
			"label": "Intacct Entity ID",
			"insert_after": "abbr",
			"description": "Sent as <locationid> on every gateway login. Manufacturing definitions are 'Entity only'.",
		},
	],
}


# The role the Fuse workspace is restricted to. A user holding only this role sees only
# that workspace, which makes it their landing page without any per-user setting to keep
# in step. Warehouse and Intacct Bin stay read-only for it — Intacct owns those.
ROLE = "Stock Controller"

# What the role can actually do. Creating the Role alone left it carrying almost nothing,
# so a user holding ONLY this role saw an empty workspace — it happened to work for people
# who also held Stock User or Manufacturing User, which hid the gap.
#
# Set here rather than clicked into the Role Permissions Manager, because a new client has
# to arrive configured. Live here rather than in the theme app: which documents a role may
# raise is integration behaviour, not look and feel.
_FULL = {
	"read": 1, "write": 1, "create": 1, "delete": 0,
	"submit": 1, "cancel": 1, "amend": 1,
	"print": 1, "email": 1, "report": 1, "export": 1, "share": 1,
}
_READ_ONLY = {
	"read": 1, "write": 0, "create": 0, "delete": 0,
	"submit": 0, "cancel": 0, "amend": 0,
	"print": 1, "email": 1, "report": 1, "export": 1, "share": 0,
}

ROLE_PERMISSIONS = {
	# The documents this role exists to raise. delete stays 0 deliberately — a posted
	# movement is REVERSED, never deleted, or Intacct keeps a document ERPNext has
	# forgotten.
	"Stock Entry": _FULL,
	"Work Order": _FULL,
	# Intacct owns these. Read is needed to raise the documents above; write is not, and an
	# edit would be overwritten by the next masters sync anyway.
	"Item": _READ_ONLY,
	"Warehouse": _READ_ONLY,
	"BOM": _READ_ONLY,
	"Item Alternative": _READ_ONLY,
	"Intacct Bin": _READ_ONLY,
	# READ ONLY DELIBERATELY. Stock Reconciliation does not post to Intacct — it is what
	# the opening stock sync uses. Create rights here would hand this role a way to change
	# stock that Intacct never sees, which is the one thing the whole app prevents.
	"Stock Reconciliation": _READ_ONLY,
}

# Query reports carry their own role list, separate from DocType permissions. These are the
# three on the Stock Control workspace.
ROLE_REPORTS = ("Stock Balance", "Stock Ledger", "Stock Projected Qty")


def _apply_role_permissions():
	"""Grant the role what it needs, and only read where Intacct owns the data."""
	from frappe.permissions import add_permission, update_permission_property

	for doctype, perms in ROLE_PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		add_permission(doctype, ROLE, 0)
		for ptype, value in perms.items():
			update_permission_property(doctype, ROLE, 0, ptype, value, validate=False)

	granted = []
	for report in ROLE_REPORTS:
		if not frappe.db.exists("Report", report):
			continue
		doc = frappe.get_doc("Report", report)
		if any(row.role == ROLE for row in doc.roles):
			continue
		doc.append("roles", {"role": ROLE})
		doc.save(ignore_permissions=True)
		granted.append(report)

	return granted


def after_install():
	"""Put the site's Fuse-owned configuration in step with this version of the app.

	Wired to after_install AND after_migrate, and safe to run at any time — everything here
	is idempotent, so re-running only closes gaps.

	It is also exposed as the `setup` sync job, because after_migrate has been observed NOT
	to fire on a Frappe Cloud deploy: on 2026-08-11 the code shipped and the field
	definitions did not, leaving a posting writing to a field that did not exist. Without a
	way to run this from the desk that needs bench access to repair, which on Frappe Cloud
	means a support ticket.
	"""
	created = create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)

	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": ROLE, "desk_access": 1, "is_custom": 1}
		).insert(ignore_permissions=True)

	reports = _apply_role_permissions()
	frappe.db.commit()

	return {
		"custom_fields": sum(len(fields) for fields in CUSTOM_FIELDS.values()),
		"doctypes": sorted(CUSTOM_FIELDS),
		"created_or_updated": created,
		"role": ROLE,
		"role_permissions": sorted(ROLE_PERMISSIONS),
		"reports_granted": reports,
	}
