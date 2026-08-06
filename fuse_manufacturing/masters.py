"""Masters in — a one-way read-only mirror, Intacct → ERPNext.

Intacct owns these records. Nothing here writes back, and nothing here invents a value.
Run in order: warehouses → UOMs → items → bins. Items need the UOMs to exist first, and
bins hang off warehouses.

Every function is idempotent: run it twice and the second run changes nothing.
"""

import frappe

from fuse_manufacturing import gateway
from fuse_manufacturing.gateway import flag, number, val

# ──────────────────────────────────────────────────────────────────────────────
# Warehouses
# ──────────────────────────────────────────────────────────────────────────────

WAREHOUSE_FIELDS = ["RECORDNO", "LOCATIONID", "WAREHOUSEID", "NAME", "STATUS"]


@frappe.whitelist()
def sync_warehouses(company=None):
	"""Intacct WAREHOUSE → ERPNext Warehouse.

	Intacct carries two different codes for a warehouse and they are NOT guaranteed to
	be the same string: WAREHOUSEID is how other objects (bins, ITEMWAREHOUSEINFO,
	transaction lines) refer to it, LOCATIONID is the accounting location. Both are
	stored so neither has to be inferred later.
	"""
	company = company or _default_company()
	rows = gateway.query("WAREHOUSE", WAREHOUSE_FIELDS)

	created = updated = 0
	for row in rows:
		warehouse_id = val(row, "WAREHOUSEID")
		name = val(row, "NAME") or warehouse_id
		if not warehouse_id:
			continue

		existing = frappe.db.get_value(
			"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": company}, "name"
		)

		if existing:
			doc = frappe.get_doc("Warehouse", existing)
			updated += 1
		else:
			doc = frappe.new_doc("Warehouse")
			doc.company = company
			doc.is_group = 0
			created += 1

		doc.warehouse_name = name
		doc.disabled = 0 if (val(row, "STATUS") or "").lower() == "active" else 1
		doc.custom_intacct_warehouse_id = warehouse_id
		doc.custom_intacct_location_id = val(row, "LOCATIONID")
		doc.custom_intacct_recordno = val(row, "RECORDNO")
		doc.save(ignore_permissions=True)

	frappe.db.commit()
	return {"read": len(rows), "created": created, "updated": updated}


# ──────────────────────────────────────────────────────────────────────────────
# Bins
# ──────────────────────────────────────────────────────────────────────────────

BIN_FIELDS = ["RECORDNO", "BINID", "WAREHOUSEID", "STATUS"]


@frappe.whitelist()
def sync_bins():
	"""Intacct BIN → the default bin stored on each ERPNext Warehouse.

	ERPNext has no location-bin concept — its own "Bin" DocType is the per-item,
	per-warehouse quantity record, which is a different thing entirely. Intacct bins are
	not modelled as ERPNext records; the warehouse's default bin is stored against the
	Warehouse and stamped onto movements at post time, which is all a bin-enabled item
	needs to be accepted.

	"Default" is the lowest BINID, matching the donor, so the choice is deterministic
	rather than dependent on the order Intacct happens to return.
	"""
	rows = gateway.query("BIN", BIN_FIELDS)

	lowest = {}
	for row in rows:
		if (val(row, "STATUS") or "active").lower() != "active":
			continue
		warehouse_id = val(row, "WAREHOUSEID")
		bin_id = val(row, "BINID")
		if not warehouse_id or not bin_id:
			continue
		if warehouse_id not in lowest or bin_id < lowest[warehouse_id]:
			lowest[warehouse_id] = bin_id

	stamped = 0
	for warehouse_id, bin_id in lowest.items():
		name = frappe.db.get_value("Warehouse", {"custom_intacct_warehouse_id": warehouse_id}, "name")
		if not name:
			continue
		frappe.db.set_value("Warehouse", name, "custom_intacct_default_bin", bin_id, update_modified=False)
		stamped += 1

	frappe.db.commit()
	return {"read": len(rows), "warehouses_with_bins": len(lowest), "stamped": stamped}


# ──────────────────────────────────────────────────────────────────────────────
# UOMs
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def sync_uoms():
	"""Create every unit string Intacct uses on items, spelled exactly as Intacct spells it.

	This is not cosmetic. A transaction line whose unit does not match the item's UOM
	character for character is rejected with BL03000018 "Missing unit". Intacct's strings
	are SA English — "Cubic metres", "Litres", "Kilograms" — and ERPNext ships none of
	them, so they have to be created rather than mapped to ERPNext's own spellings.
	"""
	rows = gateway.query("ITEM", ["RECORDNO", "BASEUOM"])

	units = {val(row, "BASEUOM") for row in rows}
	units.discard(None)

	created = []
	for unit in sorted(units):
		if frappe.db.exists("UOM", unit):
			continue
		doc = frappe.new_doc("UOM")
		doc.uom_name = unit
		doc.enabled = 1
		doc.insert(ignore_permissions=True)
		created.append(unit)

	frappe.db.commit()
	return {"distinct_units": len(units), "created": created}


# ──────────────────────────────────────────────────────────────────────────────
# Items
# ──────────────────────────────────────────────────────────────────────────────

ITEM_FIELDS = [
	"RECORDNO",
	"ITEMID",
	"NAME",
	"STATUS",
	"ITEMTYPE",
	"NETWEIGHT",
	"BASEUOM",
	"ENABLE_LOT_CATEGORY",
	"ENABLE_BINS",
]


@frappe.whitelist()
def sync_items(modified_since=None):
	"""Intacct ITEM → ERPNext Item. Identity only.

	Cost is deliberately not read here: Intacct does not carry it on the ITEM object at
	all. The only place the API exposes item cost is ITEMWAREHOUSEINFO.AVERAGE_COST, per
	warehouse — so cost arrives with the stock pull, not with the item.

	`modified_since` is an Intacct-format timestamp, "MM/DD/YYYY HH:MM:SS".
	"""
	filter_xml = None
	if modified_since:
		filter_xml = (
			"<greaterthanorequalto>"
			"<field>WHENMODIFIED</field>"
			f"<value>{modified_since}</value>"
			"</greaterthanorequalto>"
		)

	rows = gateway.query("ITEM", ITEM_FIELDS, filter_xml=filter_xml)
	default_group = _default_item_group()

	created = updated = skipped = 0
	missing_uoms = set()

	for row in rows:
		item_code = val(row, "ITEMID")
		if not item_code:
			continue

		uom = val(row, "BASEUOM")
		if uom and not frappe.db.exists("UOM", uom):
			# Never substitute a near-match: the wrong string is rejected at post time,
			# so a silently mapped UOM would fail much later and much less obviously.
			missing_uoms.add(uom)
			skipped += 1
			continue

		existing = frappe.db.get_value("Item", {"item_code": item_code}, "name")
		if existing:
			doc = frappe.get_doc("Item", existing)
			updated += 1
		else:
			doc = frappe.new_doc("Item")
			doc.item_code = item_code
			doc.item_group = default_group
			created += 1

		doc.item_name = (val(row, "NAME") or item_code)[:140]
		doc.disabled = 0 if (val(row, "STATUS") or "").lower() == "active" else 1
		doc.is_stock_item = 1 if (val(row, "ITEMTYPE") or "").lower() == "inventory" else 0
		if uom:
			doc.stock_uom = uom
		doc.has_batch_no = 1 if flag(row, "ENABLE_LOT_CATEGORY") else 0
		doc.weight_per_unit = number(row, "NETWEIGHT", 0)

		doc.custom_intacct_item_id = item_code
		doc.custom_intacct_recordno = val(row, "RECORDNO")
		doc.custom_intacct_bin_tracked = 1 if flag(row, "ENABLE_BINS") else 0

		doc.save(ignore_permissions=True)

	frappe.db.commit()

	result = {"read": len(rows), "created": created, "updated": updated, "skipped": skipped}
	if missing_uoms:
		result["missing_uoms"] = sorted(missing_uoms)
	return result


# ──────────────────────────────────────────────────────────────────────────────
# Run everything, in order
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def sync_all(company=None):
	"""Full masters pull, in dependency order."""
	return {
		"warehouses": sync_warehouses(company=company),
		"uoms": sync_uoms(),
		"items": sync_items(),
		"bins": sync_bins(),
	}


# ──────────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────────


def _default_company():
	companies = frappe.get_all("Company", pluck="name", limit=2)
	if len(companies) != 1:
		frappe.throw(
			"Pass the company explicitly — this site has "
			f"{len(companies)} companies and one Intacct company maps to one of them."
		)
	return companies[0]


def _default_item_group():
	group = frappe.db.get_single_value("Intacct Settings", "default_item_group")
	if group and frappe.db.exists("Item Group", group):
		return group
	frappe.throw("Set a Default Item Group on Intacct Settings before syncing items.")
