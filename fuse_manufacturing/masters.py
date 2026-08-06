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
# Entities
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def list_entities():
	"""Every active entity in the Intacct company — E100, E200 and so on.

	Read from LOCATIONENTITY, NOT LOCATION. LOCATION also returns ordinary locations
	nested under entities, so it over-reports and you end up mapping an ERPNext company
	onto something that is not an entity at all.

	This does not write anything. Use it to see what exists, then set the matching
	Intacct Entity ID on each ERPNext Company.
	"""
	rows = gateway.query(
		"LOCATIONENTITY",
		["RECORDNO", "LOCATIONID", "NAME", "STATUS"],
		filter_xml="<equalto><field>STATUS</field><value>active</value></equalto>",
	)

	entities = [
		{"entity_id": val(row, "LOCATIONID"), "name": val(row, "NAME"), "recordno": val(row, "RECORDNO")}
		for row in rows
	]

	mapped = {
		c.custom_intacct_entity_id: c.name
		for c in frappe.get_all(
			"Company",
			fields=["name", "custom_intacct_entity_id"],
			filters={"custom_intacct_entity_id": ["is", "set"]},
		)
	}
	for entity in entities:
		entity["erpnext_company"] = mapped.get(entity["entity_id"])

	return entities


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
	result = {}

	for comp in _target_companies(company):
		# Queried on that company's entity session — a warehouse belongs to an entity,
		# so reading E100's warehouses from an E200 session returns the wrong set.
		rows = gateway.query("WAREHOUSE", WAREHOUSE_FIELDS, company=comp)

		created = updated = 0
		for row in rows:
			warehouse_id = val(row, "WAREHOUSEID")
			name = val(row, "NAME") or warehouse_id
			if not warehouse_id:
				continue

			existing = frappe.db.get_value(
				"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": comp}, "name"
			)

			if existing:
				doc = frappe.get_doc("Warehouse", existing)
				updated += 1
			else:
				doc = frappe.new_doc("Warehouse")
				doc.company = comp
				doc.is_group = 0
				# Warehouse is a tree. Without a parent the new node becomes a second
				# root, which ERPNext rejects, so hang it off the company's own group.
				doc.parent_warehouse = _root_warehouse(comp)
				created += 1

			doc.warehouse_name = name
			doc.disabled = 0 if (val(row, "STATUS") or "").lower() == "active" else 1
			doc.custom_intacct_warehouse_id = warehouse_id
			doc.custom_intacct_location_id = val(row, "LOCATIONID")
			doc.custom_intacct_recordno = val(row, "RECORDNO")
			doc.save(ignore_permissions=True)

		result[comp] = {"read": len(rows), "created": created, "updated": updated}

	frappe.db.commit()
	return result


# ──────────────────────────────────────────────────────────────────────────────
# Bins
# ──────────────────────────────────────────────────────────────────────────────

BIN_FIELDS = ["RECORDNO", "BINID", "WAREHOUSEID", "STATUS"]


@frappe.whitelist()
def sync_bins(company=None):
	"""Intacct BIN → the default bin stored on each ERPNext Warehouse.

	ERPNext has no location-bin concept — its own "Bin" DocType is the per-item,
	per-warehouse quantity record, which is a different thing entirely. Intacct bins are
	not modelled as ERPNext records; the warehouse's default bin is stored against the
	Warehouse and stamped onto movements at post time, which is all a bin-enabled item
	needs to be accepted.

	"Default" is the lowest BINID, matching the donor, so the choice is deterministic
	rather than dependent on the order Intacct happens to return.
	"""
	result = {}

	for comp in _target_companies(company):
		rows = gateway.query("BIN", BIN_FIELDS, company=comp)

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
			name = frappe.db.get_value(
				"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": comp}, "name"
			)
			if not name:
				continue
			frappe.db.set_value("Warehouse", name, "custom_intacct_default_bin", bin_id, update_modified=False)
			stamped += 1

		result[comp] = {"read": len(rows), "warehouses_with_bins": len(lowest), "stamped": stamped}

	frappe.db.commit()
	return result


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

		# Weight only when there is one. ERPNext makes weight_uom mandatory as soon as
		# weight_per_unit is non-zero, and Intacct's NETWEIGHT carries no unit at all,
		# so a blind copy fails validation on every item that happens to have a weight.
		weight = number(row, "NETWEIGHT", 0)
		if weight:
			doc.weight_per_unit = weight
			if not doc.weight_uom:
				doc.weight_uom = uom or doc.stock_uom

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
		"entities": list_entities(),
		"warehouses": sync_warehouses(company=company),
		"uoms": sync_uoms(),
		"items": sync_items(),
		"bins": sync_bins(company=company),
	}


# ──────────────────────────────────────────────────────────────────────────────
# Scheduled entry points
# ──────────────────────────────────────────────────────────────────────────────

# How far back to re-read on an incremental item sync, on top of the last run time.
# Intacct stamps WHENMODIFIED in the company's own timezone, which is not guaranteed to
# match the site's. An hour of deliberate overlap costs one extra page and removes a
# whole class of silently-missed records. The sync is idempotent, so re-reading is free.
ITEM_SYNC_OVERLAP_HOURS = 1


def scheduled_item_sync():
	"""Hourly. Incremental on WHENMODIFIED, with an hour of overlap."""
	if not _enabled():
		return

	from frappe.utils import add_to_date, get_datetime, now_datetime

	last = frappe.db.get_single_value("Intacct Settings", "last_item_sync")
	since = None
	if last:
		since = add_to_date(get_datetime(last), hours=-ITEM_SYNC_OVERLAP_HOURS)
		since = since.strftime("%m/%d/%Y %H:%M:%S")

	started = now_datetime()
	result = sync_items(modified_since=since)

	# Stamped only after a clean run. A failure leaves the old watermark in place so the
	# next attempt covers the same window rather than skipping over it.
	frappe.db.set_single_value("Intacct Settings", "last_item_sync", started)
	frappe.db.commit()
	return result


def scheduled_config_sync():
	"""Daily. Warehouses, UOMs and bins — configuration, not data."""
	if not _enabled():
		return

	return {
		"warehouses": sync_warehouses(),
		"uoms": sync_uoms(),
		"bins": sync_bins(),
	}


# Items and UOMs are read once for the whole Intacct company rather than per entity:
# the item master is shared across entities, so pulling it per entity would just
# re-read the same rows N times. The session still has to be opened against some
# entity — Intacct rejects a top-level login — so it uses the default on Settings.


def _enabled():
	return bool(frappe.db.get_single_value("Intacct Settings", "enabled"))


# ──────────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────────


def _target_companies(company=None):
	"""Which ERPNext companies to sync — one per Intacct entity.

	An Intacct company holds many entities (E100, E200...). Each one maps to its own
	ERPNext Company carrying that entity ID, because warehouses, stock and postings all
	belong to an entity rather than to the company as a whole.
	"""
	if company:
		return [company]

	# "is set" rather than ["not in", ["", None]] — the latter becomes
	# `NOT IN ('', NULL)` in SQL, which evaluates to unknown for every row and returns
	# nothing at all, even when the field is populated.
	companies = frappe.get_all(
		"Company",
		pluck="name",
		filters={"custom_intacct_entity_id": ["is", "set"]},
		order_by="name",
	)
	if not companies:
		frappe.throw(
			"No ERPNext Company has an Intacct Entity ID set. "
			"Run fuse_manufacturing.masters.list_entities to see the entities available, "
			"then set the matching one on each Company."
		)
	return companies


def _root_warehouse(company):
	"""The company's top-level warehouse group, to parent new warehouses under."""
	root = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ""}, "name")
	if not root:
		root = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name")
	if not root:
		frappe.throw(f"Company {company} has no group warehouse to create warehouses under.")
	return root


def _default_item_group():
	group = frappe.db.get_single_value("Intacct Settings", "default_item_group")
	if group and frappe.db.exists("Item Group", group):
		return group
	frappe.throw("Set a Default Item Group on Intacct Settings before syncing items.")
