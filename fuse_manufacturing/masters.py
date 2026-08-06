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

# MEGAENTITYID is the entity a warehouse was created in — the only field that says which
# entity owns it. Blank means it lives at the top level and is shared by all entities.
# Note LOCATIONID is NOT the accounting location: Intacct labels both it and WAREHOUSEID
# "Warehouse ID" and they carry the same value. The real location link is LOC.LOCATIONID.
WAREHOUSE_FIELDS = [
	"RECORDNO",
	"WAREHOUSEID",
	"NAME",
	"STATUS",
	"PARENTID",
	"MEGAENTITYID",
	"LOC.LOCATIONID",
	"ENABLENEGATIVEINV",
]


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
		entity = gateway.entity_for_company(comp)

		created = updated = skipped = 0
		for row in rows:
			warehouse_id = val(row, "WAREHOUSEID")
			name = val(row, "NAME") or warehouse_id
			if not warehouse_id:
				continue

			# An entity-scoped session still returns warehouses belonging to OTHER
			# entities, so the query cannot be trusted to filter for us. Take the
			# warehouse only if it was created in this entity, or at the top level
			# (blank), which means it is shared. Without this, another entity's
			# warehouses land under this company and stock posts to the wrong books —
			# something Intacct will accept without complaint.
			owner_entity = val(row, "MEGAENTITYID")
			if owner_entity and entity and owner_entity != entity:
				skipped += 1
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
			doc.custom_intacct_location_id = val(row, "LOC.LOCATIONID")
			doc.custom_intacct_entity_id = owner_entity
			doc.custom_intacct_recordno = val(row, "RECORDNO")
			doc.save(ignore_permissions=True)

		# Intacct warehouses are themselves a tree (PARENTID). Reparent in a second pass
		# so a child is never processed before its parent exists.
		reparented = 0
		for row in rows:
			parent_id = val(row, "PARENTID")
			warehouse_id = val(row, "WAREHOUSEID")
			if not parent_id or not warehouse_id:
				continue
			child = frappe.db.get_value(
				"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": comp}, "name"
			)
			parent = frappe.db.get_value(
				"Warehouse", {"custom_intacct_warehouse_id": parent_id, "company": comp}, "name"
			)
			if not child or not parent or child == parent:
				continue
			parent_doc = frappe.get_doc("Warehouse", parent)
			if not parent_doc.is_group:
				parent_doc.is_group = 1
				parent_doc.save(ignore_permissions=True)
			child_doc = frappe.get_doc("Warehouse", child)
			if child_doc.parent_warehouse != parent:
				child_doc.parent_warehouse = parent
				child_doc.save(ignore_permissions=True)
				reparented += 1

		result[comp] = {
			"read": len(rows),
			"created": created,
			"updated": updated,
			"skipped_other_entity": skipped,
			"reparented": reparented,
		}

	frappe.db.commit()
	return result


# ──────────────────────────────────────────────────────────────────────────────
# Bins
# ──────────────────────────────────────────────────────────────────────────────

# Intacct's location cascade below the warehouse: Zone → Aisle → Row → Face → Bin.
# All of it is carried on the BIN record itself, so it mirrors as attributes rather than
# as extra levels of ERPNext warehouse — which keeps ERPNext's grain identical to Intacct's.
BIN_FIELDS = [
	"RECORDNO",
	"BINID",
	"BINDESC",
	"WAREHOUSEID",
	"STATUS",
	"ZONEID",
	"AISLEID",
	"ROWID",
	"FACEID",
	"SIZEID",
	"SEQUENCENO",
]


@frappe.whitelist()
def sync_bins(company=None):
	"""Intacct BIN → Intacct Bin records, one per bin. A mirror, nothing more.

	Bins are NOT modelled as ERPNext warehouses. ERPNext's Warehouse tree could hold
	them as leaf nodes, which would track stock per bin — finer than Intacct, which
	holds stock per warehouse with bin as line detail. Deliberately not done: Intacct is
	the golden source for locations, so ERPNext mirrors its grain rather than inventing
	a more detailed one that would then disagree.

	ERPNext's own "Bin" DocType is unrelated — it is the per-item, per-warehouse
	quantity record. Hence a separate Intacct Bin DocType.

	The lowest active BINID is also stamped on the Warehouse as its default, for
	movements where the operator does not pick one. Lowest, not first returned, so the
	choice does not depend on the order Intacct happens to answer in.
	"""
	result = {}

	for comp in _target_companies(company):
		rows = gateway.query("BIN", BIN_FIELDS, company=comp)

		lowest = {}
		mirrored = 0
		seen = set()

		for row in rows:
			warehouse_id = val(row, "WAREHOUSEID")
			bin_id = val(row, "BINID")
			if not warehouse_id or not bin_id:
				continue

			warehouse = frappe.db.get_value(
				"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": comp}, "name"
			)
			if not warehouse:
				# Warehouse not mirrored yet — sync_warehouses runs first for a reason.
				continue

			status = (val(row, "STATUS") or "active").lower()
			name = f"{warehouse}::{bin_id}"

			if frappe.db.exists("Intacct Bin", name):
				doc = frappe.get_doc("Intacct Bin", name)
			else:
				doc = frappe.new_doc("Intacct Bin")
				doc.warehouse = warehouse
				doc.bin_id = bin_id

			doc.company = comp
			doc.status = status
			doc.bin_description = val(row, "BINDESC")
			doc.zone_id = val(row, "ZONEID")
			doc.aisle_id = val(row, "AISLEID")
			doc.row_id = val(row, "ROWID")
			doc.face_id = val(row, "FACEID")
			doc.size_id = val(row, "SIZEID")
			doc.sequence_no = number(row, "SEQUENCENO", 0)
			doc.intacct_recordno = val(row, "RECORDNO")
			doc.save(ignore_permissions=True)
			mirrored += 1
			seen.add(name)

			if status == "active" and (warehouse_id not in lowest or bin_id < lowest[warehouse_id]):
				lowest[warehouse_id] = bin_id

		# Bins deleted in Intacct must not linger here — this is a mirror, not an archive.
		stale = frappe.get_all("Intacct Bin", filters={"company": comp}, pluck="name")
		removed = 0
		for name in stale:
			if name not in seen:
				frappe.delete_doc("Intacct Bin", name, ignore_permissions=True, force=True)
				removed += 1

		stamped = 0
		for warehouse_id, bin_id in lowest.items():
			name = frappe.db.get_value(
				"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": comp}, "name"
			)
			if not name:
				continue
			frappe.db.set_value("Warehouse", name, "custom_intacct_default_bin", bin_id, update_modified=False)
			stamped += 1

		result[comp] = {
			"read": len(rows),
			"mirrored": mirrored,
			"removed": removed,
			"warehouses_with_bins": len(lowest),
			"default_bin_stamped": stamped,
		}

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
	"WEIGHTUOM",
	"BASEUOM",
	"ENABLE_LOT_CATEGORY",
	"ENABLE_SERIALNO",
	"ENABLE_BINS",
	"ENABLE_EXPIRATION",
	"UPC",
	"EAN13",
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
		# Tracking switches are authoritative from Intacct, never set locally.
		# ERPNext refuses to change these once stock movements exist against the item,
		# so a switch flipped in Intacct after go-live will fail here rather than
		# silently diverge. That is the intended behaviour — it needs a human.
		doc.has_batch_no = 1 if flag(row, "ENABLE_LOT_CATEGORY") else 0
		doc.has_serial_no = 1 if flag(row, "ENABLE_SERIALNO") else 0
		# ERPNext only allows expiry on a batched item.
		doc.has_expiry_date = 1 if (doc.has_batch_no and flag(row, "ENABLE_EXPIRATION")) else 0

		# Weight only when there is one. ERPNext makes weight_uom mandatory as soon as
		# weight_per_unit is non-zero. Intacct carries its own WEIGHTUOM, so use that
		# where set and only fall back to the stock unit when it is empty.
		weight = number(row, "NETWEIGHT", 0)
		if weight:
			doc.weight_per_unit = weight
			weight_uom = val(row, "WEIGHTUOM")
			if weight_uom and frappe.db.exists("UOM", weight_uom):
				doc.weight_uom = weight_uom
			elif not doc.weight_uom:
				doc.weight_uom = uom or doc.stock_uom

		# Barcodes — the scanner flows need these, and Intacct already holds them.
		# Rebuilt from Intacct each run rather than appended, so a barcode removed
		# there disappears here instead of lingering and scanning to a stale item.
		barcodes = []
		upc = val(row, "UPC")
		ean = val(row, "EAN13")
		if upc:
			barcodes.append({"barcode": upc, "barcode_type": "UPC-A"})
		if ean and ean != upc:
			barcodes.append({"barcode": ean, "barcode_type": "EAN"})
		if barcodes or doc.get("barcodes"):
			doc.set("barcodes", barcodes)

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
# Kits → BOMs
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def sync_kits(company=None):
	"""Intacct kits → ERPNext BOMs.

	A kit in Intacct IS the finished good: an ITEM whose ITEMTYPE contains "Kit"
	("Kit" or "Stockable Kit"), with its recipe in ITEMCOMPONENT.

	TWO queries, never a read per kit. ITEMCOMPONENT is directly queryable even
	though the recipe also appears nested inside each item's COMPONENTINFO. The
	donor originally read each kit's full record — ~950ms each across ~680 kit items,
	an hour of API time per sync, which presented as the sync simply hanging.

	Intacct's recipe is single-level. Multi-level comes out naturally anyway: a
	sub-assembly is its own kit, gets its own BOM, and ERPNext explodes it — which is
	why BOMs are built in dependency order below.

	Idempotent by comparing a signature of the recipe. An unchanged kit is left
	completely alone, because the only way to change a submitted BOM is to cancel and
	replace it, and doing that on every run would churn the whole BOM history nightly.
	"""
	company = company or _target_companies()[0]

	kits = [
		row
		for row in gateway.query("ITEM", ["RECORDNO", "ITEMID", "NAME", "ITEMTYPE", "STATUS", "BASEUOM"])
		if "kit" in (val(row, "ITEMTYPE") or "").lower()
	]

	components = gateway.query(
		"ITEMCOMPONENT", ["ITEMID", "COMPONENTKEY", "QUANTITY", "UNIT", "LINE_NO"]
	)

	by_kit = {}
	for row in components:
		parent = val(row, "ITEMID")
		component = val(row, "COMPONENTKEY")
		if not parent or not component:
			continue
		by_kit.setdefault(parent, []).append(
			{
				"line": int(number(row, "LINE_NO", 0) or 0),
				"item_code": component,
				"qty": number(row, "QUANTITY", 0) or 0,
				"uom": val(row, "UNIT"),
			}
		)

	kit_codes = {val(k, "ITEMID") for k in kits}
	created = replaced = unchanged = 0
	skipped = []

	# Dependency order: a kit is only built once every kit it consumes already has a
	# BOM, so ERPNext can link the sub-assembly instead of treating it as a raw part.
	pending = [k for k in kits if val(k, "ITEMID") in by_kit]
	built = set()

	while pending:
		progressed = False
		still_pending = []

		for kit in pending:
			code = val(kit, "ITEMID")
			lines = sorted(by_kit.get(code, []), key=lambda x: x["line"])

			blockers = [
				line["item_code"]
				for line in lines
				if line["item_code"] in kit_codes and line["item_code"] not in built
			]
			if blockers:
				still_pending.append(kit)
				continue

			outcome = _build_bom(code, lines, company)
			progressed = True
			built.add(code)

			if outcome == "created":
				created += 1
			elif outcome == "replaced":
				replaced += 1
			elif outcome == "unchanged":
				unchanged += 1
			else:
				skipped.append({"kit": code, "reason": outcome})

		if not progressed:
			# Circular recipe — a kit that ultimately contains itself. Intacct allows
			# it to be saved; ERPNext cannot explode it and neither can a factory.
			for kit in still_pending:
				skipped.append({"kit": val(kit, "ITEMID"), "reason": "circular recipe"})
			break

		pending = still_pending

	frappe.db.commit()
	return {
		"kits_found": len(kits),
		"kits_with_recipe": len(by_kit),
		"created": created,
		"replaced": replaced,
		"unchanged": unchanged,
		"skipped": skipped,
	}


def _recipe_signature(lines):
	"""Stable fingerprint of a recipe, for deciding whether anything actually changed."""
	return "|".join(f"{line['item_code']}:{float(line['qty']):.6f}:{line['uom'] or ''}" for line in lines)


def _build_bom(kit_code, lines, company):
	"""Create or replace the BOM for one kit. Returns an outcome string."""
	if not frappe.db.exists("Item", kit_code):
		return "kit item not synced"

	missing = [line["item_code"] for line in lines if not frappe.db.exists("Item", line["item_code"])]
	if missing:
		return f"components not synced: {', '.join(sorted(set(missing))[:5])}"

	bad_uom = [line["uom"] for line in lines if line["uom"] and not frappe.db.exists("UOM", line["uom"])]
	if bad_uom:
		return f"unit not on site: {', '.join(sorted(set(bad_uom))[:5])}"

	signature = _recipe_signature(lines)

	existing = frappe.db.get_value(
		"BOM", {"item": kit_code, "docstatus": 1, "is_active": 1}, ["name", "custom_intacct_signature"]
	)
	if existing and existing[1] == signature:
		return "unchanged"

	doc = frappe.new_doc("BOM")
	doc.item = kit_code
	doc.company = company
	doc.quantity = 1
	doc.is_active = 1
	doc.is_default = 1
	doc.with_operations = 0
	# Valuation Rate resolves to zero here by design — perpetual inventory is off and
	# Intacct owns cost. Verified on this site that a zero-cost BOM both saves and submits.
	doc.rm_cost_as_per = "Valuation Rate"
	doc.custom_intacct_signature = signature

	for line in lines:
		row = {"item_code": line["item_code"], "qty": line["qty"]}
		if line["uom"]:
			row["uom"] = line["uom"]
		doc.append("items", row)

	doc.insert(ignore_permissions=True)
	doc.submit()

	if existing:
		# Replace only after the new one is safely in, so a failure never leaves the
		# kit with no active BOM at all.
		old = frappe.get_doc("BOM", existing[0])
		old.db_set("is_default", 0)
		old.db_set("is_active", 0)
		old.cancel()
		return "replaced"

	return "created"


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
		"kits": sync_kits(company=company),
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
