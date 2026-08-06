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
			"description": "LOCATIONID — the accounting location. Not guaranteed to equal the warehouse ID.",
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


def after_install():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	frappe.db.commit()
