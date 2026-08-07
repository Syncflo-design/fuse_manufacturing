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
		["RECORDNO", "LOCATIONID", "NAME", "STATUS", "CURRENCY"],
		filter_xml="<equalto><field>STATUS</field><value>active</value></equalto>",
	)

	entities = [
		{
			"entity_id": val(row, "LOCATIONID"),
			"name": val(row, "NAME"),
			"recordno": val(row, "RECORDNO"),
			"currency": val(row, "CURRENCY"),
		}
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


def map_entities(company=None):
	"""Map Intacct entities onto ERPNext Companies, without anyone typing an ID.

	Auto-maps only when it is UNAMBIGUOUS — one active entity and one company. That is
	the normal shape (one client, one instance, one entity) and it removes the step most
	likely to be got wrong: an entity typed in by hand is how stock ends up posted to
	the wrong books, and Intacct will not complain.

	With several of either, it reports what it found and leaves the mapping alone.
	A wrong guess here is worse than no guess.
	"""
	entities = [e for e in list_entities()]
	companies = frappe.get_all("Company", pluck="name", order_by="name")

	if len(entities) == 1 and len(companies) == 1:
		entity_id = entities[0]["entity_id"]
		current = frappe.db.get_value("Company", companies[0], "custom_intacct_entity_id")
		if current == entity_id:
			return {
				"mapped": False,
				"reason": "already mapped",
				"company": companies[0],
				"entity": entity_id,
				"currency": _align_company_currency(companies[0], entities[0].get("currency")),
			}
		frappe.db.set_value("Company", companies[0], "custom_intacct_entity_id", entity_id)
		frappe.db.commit()
		result = {"mapped": True, "company": companies[0], "entity": entity_id, "was": current or None}
		result["currency"] = _align_company_currency(companies[0], entities[0].get("currency"))
		return result

	return {
		"mapped": False,
		"reason": "ambiguous — map each Company to its entity by hand",
		"entities": entities,
		"companies": companies,
	}


def _align_company_currency(company, intacct_currency):
	"""Match the ERPNext company's currency to the Intacct entity's base currency.

	Left to a human to fix rather than forced, if ERPNext will not allow it: changing a
	company's currency once transactions exist would revalue history, and ERPNext blocks
	it for exactly that reason.
	"""
	if not intacct_currency:
		return {"changed": False, "reason": "entity has no base currency"}

	current = frappe.db.get_value("Company", company, "default_currency")
	if current == intacct_currency:
		return {"changed": False, "currency": current}

	if not frappe.db.exists("Currency", intacct_currency):
		return {
			"changed": False,
			"currency": current,
			"warning": f"Intacct's base currency {intacct_currency} does not exist in ERPNext.",
		}

	try:
		doc = frappe.get_doc("Company", company)
		doc.default_currency = intacct_currency
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {"changed": True, "from": current, "to": intacct_currency}
	except Exception as exc:
		return {
			"changed": False,
			"currency": current,
			"intacct_currency": intacct_currency,
			"warning": f"ERPNext refused the change ({exc}). Almost certainly because transactions already exist — changing it now would revalue history.",
		}


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

			# Only write when something actually differs. Saving unconditionally bumped
			# every warehouse's modified timestamp and wrote a Version record on every
			# daily run — noise that buries the changes you would want to notice.
			if doc.is_new() or _has_changes(doc):
				doc.save(ignore_permissions=True)
			elif existing:
				updated -= 1

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

			# Same reasoning as warehouses: do not rewrite an unchanged mirror.
			if doc.is_new() or _has_changes(doc):
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
			"written": mirrored,
			"removed": removed,
			"warehouses_with_bins": len(lowest),
			"default_bin_stamped": stamped,
		}

	frappe.db.commit()
	return result


# ──────────────────────────────────────────────────────────────────────────────
# UOMs
# ──────────────────────────────────────────────────────────────────────────────


def sync_uoms():
	"""Create every unit string Intacct uses on items, spelled exactly as Intacct spells it.

	This is not cosmetic. A transaction line whose unit does not match the item's UOM
	character for character is rejected with BL03000018 "Missing unit". Intacct's strings
	are SA English — "Cubic metres", "Litres", "Kilograms" — and ERPNext ships none of
	them, so they have to be created rather than mapped to ERPNext's own spellings.
	"""
	rows = gateway.query(
		"ITEM",
		["RECORDNO", "BASEUOM", "UOM.POUOMDETAIL.UNIT", "UOM.SOUOMDETAIL.UNIT"],
	)

	# Every unit Intacct uses anywhere on an item, not just the stock unit — a purchase
	# unit that does not exist here means the conversion cannot be recorded and the
	# receipt is silently wrong.
	units = set()
	for row in rows:
		units.update(
			{
				val(row, "BASEUOM"),
				val(row, "UOM.POUOMDETAIL.UNIT"),
				val(row, "UOM.SOUOMDETAIL.UNIT"),
			}
		)
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
# Product lines → Item Groups
# ──────────────────────────────────────────────────────────────────────────────

PRODUCTLINE_FIELDS = ["RECORDNO", "PRODUCTLINEID", "DESCRIPTION", "PARENTLINE", "STATUS"]


def sync_item_groups(company=None):
	"""Intacct PRODUCTLINE → ERPNext Item Group.

	Both are trees, so the hierarchy carries across. Without this every item lands in
	one catch-all group chosen by us — a guess that has to be corrected by hand on every
	new client instance, which is exactly what Intacct-as-source is meant to remove.

	Groups are created but never deleted: an Item Group with items under it cannot be
	removed, and a product line retired in Intacct does not make its history disappear.
	"""
	rows = gateway.query("PRODUCTLINE", PRODUCTLINE_FIELDS, company=company)

	# The root's parent is NULL on a fresh site and "" on some, and a dict filter of ""
	# will not match NULL — so ask for either.
	root = frappe.db.get_value(
		"Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]}, "name"
	)
	if not root:
		frappe.throw("No root Item Group found — cannot build the product line tree under it.")

	created = 0
	by_id = {}
	used_names = set(frappe.get_all("Item Group", pluck="item_group_name", limit_page_length=0))

	# Two passes: create everything flat first, then set parents. A product line can
	# reference a parent that appears later in the list.
	for row in rows:
		line_id = val(row, "PRODUCTLINEID")
		if not line_id:
			continue
		name = frappe.db.get_value("Item Group", {"custom_intacct_product_line": line_id}, "name")
		if not name:
			# Item Group is named by its label, so two product lines sharing a
			# description — or clashing with an ERPNext default like "Products" —
			# would collide. Fall back to the product line ID, which is unique.
			label = (val(row, "DESCRIPTION") or line_id).strip()[:140] or line_id
			if label in used_names:
				label = f"{label} ({line_id})"[:140]

			doc = frappe.new_doc("Item Group")
			doc.item_group_name = label
			doc.parent_item_group = root
			doc.is_group = 0
			doc.custom_intacct_product_line = line_id
			doc.insert(ignore_permissions=True)
			name = doc.name
			used_names.add(label)
			created += 1
		by_id[line_id] = name

	reparented = 0
	for row in rows:
		line_id = val(row, "PRODUCTLINEID")
		parent_id = val(row, "PARENTLINE")
		if not line_id or not parent_id:
			continue
		child, parent = by_id.get(line_id), by_id.get(parent_id)
		if not child or not parent or child == parent:
			continue
		parent_doc = frappe.get_doc("Item Group", parent)
		if not parent_doc.is_group:
			parent_doc.is_group = 1
			parent_doc.save(ignore_permissions=True)
		child_doc = frappe.get_doc("Item Group", child)
		if child_doc.parent_item_group != parent:
			child_doc.parent_item_group = parent
			child_doc.save(ignore_permissions=True)
			reparented += 1

	frappe.db.commit()
	return {"read": len(rows), "created": created, "reparented": reparented}


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
	# Intacct's own decimal precision for this item's inventory quantities. ERPNext's
	# float precision is aligned to the highest one seen rather than guessed — Intacct
	# is the source for this the same as for everything else.
	"INV_PRECISION",
	# Drives the ERPNext Item Group, so items are filed the way Intacct files them
	# instead of all landing in one group we picked.
	"PRODUCTLINEID",
	# Purchase and sales units, with their factor against the stock unit. Without these
	# an item bought in drums and stocked in kilograms is treated as 1:1 — a receipt of
	# 5 drums becomes 5 kg.
	"UOM.POUOMDETAIL.UNIT",
	"UOM.POUOMDETAIL.CONVFACTOR",
	"UOM.SOUOMDETAIL.UNIT",
	"UOM.SOUOMDETAIL.CONVFACTOR",
]

# Never go below this, whatever Intacct says. ERPNext's own default is 3 and dropping
# under it would round quantities that other parts of ERPNext expect to keep.
MIN_FLOAT_PRECISION = 3
# Frappe's field allows up to 9.
MAX_FLOAT_PRECISION = 9


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
	group_by_line = {
		g.custom_intacct_product_line: g.name
		for g in frappe.get_all(
			"Item Group",
			fields=["name", "custom_intacct_product_line"],
			filters={"custom_intacct_product_line": ["is", "set"]},
			limit_page_length=0,
		)
	}

	created = updated = skipped = 0
	missing_uoms = set()
	precisions = set()

	for row in rows:
		precisions.add(val(row, "INV_PRECISION"))
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
			created += 1

		# Item Group follows Intacct's product line. The Settings default is only a
		# fallback for items Intacct has not filed — not the normal case.
		group = group_by_line.get(val(row, "PRODUCTLINEID"))
		if group:
			doc.item_group = group
		elif not doc.item_group:
			doc.item_group = default_group

		doc.item_name = (val(row, "NAME") or item_code)[:140]
		doc.disabled = 0 if (val(row, "STATUS") or "").lower() == "active" else 1

		# Intacct's ITEMTYPE decides whether ERPNext holds stock for the item.
		# "Inventory" is obvious. A **Stockable Kit** also holds stock — it is a kit that
		# is itself stocked — and it MUST be a stock item here, because ERPNext cannot
		# run a Work Order to produce a non-stock item. Getting this wrong is silent:
		# the BOM builds fine and only manufacturing fails, much later.
		# A plain (non-stocked) "Kit" is assembled on the fly and holds no stock.
		item_type = (val(row, "ITEMTYPE") or "").strip()
		normalised = item_type.lower()
		doc.is_stock_item = 1 if (normalised == "inventory" or "stockable kit" in normalised) else 0
		doc.custom_intacct_item_type = item_type
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

		# Unit conversions. The stock unit is always 1; purchase and sales units carry
		# Intacct's own factor. Rebuilt each run rather than appended, so a conversion
		# removed in Intacct does not linger here and quietly mis-convert a receipt.
		conversions = {}
		if uom:
			conversions[uom] = 1.0
		for unit_field, factor_field in (
			("UOM.POUOMDETAIL.UNIT", "UOM.POUOMDETAIL.CONVFACTOR"),
			("UOM.SOUOMDETAIL.UNIT", "UOM.SOUOMDETAIL.CONVFACTOR"),
		):
			unit = val(row, unit_field)
			factor = number(row, factor_field, 0)
			if not unit or not factor:
				continue
			if not frappe.db.exists("UOM", unit):
				missing_uoms.add(unit)
				continue
			# Never overwrite the stock unit's factor of 1.
			if unit != uom:
				conversions[unit] = factor

		# Only when the stock unit itself is present. ERPNext requires the stock UOM to
		# appear in this table with a factor of 1; writing a purchase unit without it
		# fails validation on every item that has no BASEUOM.
		if uom and conversions:
			doc.set(
				"uoms",
				[{"uom": u, "conversion_factor": f} for u, f in conversions.items()],
			)

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

		# 2,566 items rewritten hourly is 2,566 Version records an hour for nothing.
		if doc.is_new() or _has_changes(doc):
			doc.save(ignore_permissions=True)
		elif existing:
			updated -= 1

	frappe.db.commit()

	result = {"read": len(rows), "created": created, "updated": updated, "skipped": skipped}
	if missing_uoms:
		result["missing_uoms"] = sorted(missing_uoms)

	# Align decimal places to whatever Intacct actually uses, after the items are in.
	result["float_precision"] = align_float_precision(precisions)
	return result


# ──────────────────────────────────────────────────────────────────────────────
# Remove ERPNext's shipped defaults
# ──────────────────────────────────────────────────────────────────────────────


def _retire(doctype, name, field, off_value):
	"""Delete if possible, otherwise switch it off. Returns what happened.

	`field`/`off_value` differ per doctype and the polarity is easy to get backwards:
	Warehouse has `disabled` (off = 1), UOM has `enabled` (off = 0).

	ERPNext ships hundreds of UOMs and a handful of warehouses that Intacct has never
	heard of. Left in place they are selectable, and the first person to pick one
	creates stock or a unit that Intacct cannot reconcile.

	Deleting is preferred, but anything referenced by another record cannot be deleted —
	including ERPNext's own doctype defaults. Disabling achieves the same thing (not
	selectable) without breaking the reference, so it is the fallback rather than a
	failure.
	"""
	try:
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=False)
		return "deleted"
	except Exception:
		# Roll back the failed delete before touching the row again, or the next
		# statement runs inside a broken transaction.
		frappe.db.rollback()
		try:
			frappe.db.set_value(doctype, name, field, off_value, update_modified=False)
			frappe.db.commit()
			return "disabled"
		except Exception:
			frappe.db.rollback()
			return "kept"


def remove_erpnext_defaults(company=None):
	"""Strip ERPNext's shipped UOMs and warehouses that Intacct does not use.

	Run AFTER the masters are in — it decides what to keep by what Intacct sent, so
	running it against an empty site would remove everything.
	"""
	company = company or _target_companies()[0]

	# ── UOMs ────────────────────────────────────────────────────────────────
	# Keep anything an Item actually references, whether as its stock unit or as a
	# purchase/sales conversion. Deleting a UOM in use would break those items.
	# UOM Conversion Detail is a child table, and Frappe refuses a get_all on one without
	# a parent filter — so read it directly. Missing these would disable the purchase and
	# sales units we just imported, which is the opposite of the intent.
	in_use = set(frappe.get_all("Item", pluck="stock_uom", limit_page_length=0))
	in_use.update(
		row[0]
		for row in frappe.db.sql(
			"select distinct uom from `tabUOM Conversion Detail` where uom is not null"
		)
	)
	in_use.discard(None)

	uom_result = {"deleted": 0, "disabled": 0, "kept": 0}
	for uom in frappe.get_all("UOM", pluck="name", limit_page_length=0):
		if uom in in_use:
			continue
		uom_result[_retire("UOM", uom, "enabled", 0)] += 1

	# ── Warehouses ──────────────────────────────────────────────────────────
	# Anything without an Intacct ID is ERPNext's own. The root group stays: it is the
	# tree node every Intacct warehouse hangs under.
	wh_result = {"deleted": 0, "disabled": 0, "kept": 0}
	for wh in frappe.get_all(
		"Warehouse",
		fields=["name", "is_group", "parent_warehouse", "custom_intacct_warehouse_id"],
		filters={"company": company},
		limit_page_length=0,
	):
		if wh.custom_intacct_warehouse_id:
			continue
		if wh.is_group and not wh.parent_warehouse:
			continue  # root of the tree
		wh_result[_retire("Warehouse", wh.name, "disabled", 1)] += 1

	frappe.db.commit()
	return {"uoms": uom_result, "warehouses": wh_result}


# ──────────────────────────────────────────────────────────────────────────────
# Stock on hand — opening balance once, drift report thereafter
# ──────────────────────────────────────────────────────────────────────────────

# ITEMWAREHOUSEINFO is the only place Intacct exposes item cost to the API. It is not
# on the ITEM object at all, so cost arrives here, per warehouse, or not at all.
STOCK_FIELDS = ["ITEMID", "WAREHOUSEID", "WONHAND", "AVERAGE_COST", "LAST_COST"]

# Rows per opening Stock Reconciliation.
#
# MUST stay at or below 100. Frappe defers submit() to a background job once a document
# has MORE than 100 child rows — submit() then returns having done nothing visible, the
# document sits at draft, and no stock ledger entries appear. It looks like a silent
# failure: the job reports success, the documents exist, and there is no stock.
# Observed on the first opening run at batch size 200 (all 10 documents left at draft).
OPENING_STOCK_BATCH_SIZE = 100

# Valuation used when Intacct holds no cost at all for an item. Same convention as the
# POS price safety-net: never a plausible value, obvious in any report, and the exact
# figure is the worklist — filter valuation rate = 0.01 to find every item still needing
# a real cost in Intacct.
NO_COST_SENTINEL = 0.01

# Bump to force a full BOM rebuild on the next kits sync, when the reason is outside the
# recipe itself. v2 = site float precision raised 3 → 4 to match Intacct's quantities.
SIGNATURE_VERSION = "v2"


def _read_intacct_stock(company):
	"""Intacct's on-hand per item/warehouse, keyed to ERPNext names."""
	rows = gateway.query("ITEMWAREHOUSEINFO", STOCK_FIELDS, company=company)

	warehouses = {
		w.custom_intacct_warehouse_id: w.name
		for w in frappe.get_all(
			"Warehouse",
			fields=["name", "custom_intacct_warehouse_id"],
			filters={"company": company, "custom_intacct_warehouse_id": ["is", "set"]},
		)
	}

	balances = {}
	for row in rows:
		item_code = val(row, "ITEMID")
		warehouse = warehouses.get(val(row, "WAREHOUSEID"))
		if not item_code or not warehouse:
			continue
		# AVERAGE_COST first, LAST_COST as fallback, then a sentinel.
		#
		# ERPNext refuses to submit a stock line with no valuation rate, so a zero-cost
		# item would otherwise be dropped and its quantity silently lost. Bringing the
		# stock in at NO_COST_SENTINEL keeps the quantity — which is the thing the
		# factory actually needs — and makes the missing cost findable rather than
		# invisible: filter valuation rate = 0.01 and you have the exact worklist.
		#
		# 0.01 is deliberate. It is never a plausible cost, it is glaring in any report,
		# and nothing else values at one cent. The visible wrongness IS the safeguard.
		rate = number(row, "AVERAGE_COST", 0) or 0
		source = "AVERAGE_COST"
		if not rate:
			rate = number(row, "LAST_COST", 0) or 0
			source = "LAST_COST"
		if not rate:
			rate = NO_COST_SENTINEL
			source = "sentinel"

		balances[(item_code, warehouse)] = {
			"qty": number(row, "WONHAND", 0) or 0,
			"rate": rate,
			"rate_source": source,
		}
	return balances


def post_opening_stock(company=None):
	"""Post Intacct's on-hand into ERPNext as opening Stock Reconciliations.

	Once per item/warehouse combination, and RESUMABLE: a run that dies halfway can be
	run again and continues from where it stopped. An earlier version refused outright
	if any stock movement existed, which sounded safe and was not — the first run posted
	one batch, stopped, and the retry was refused, leaving the opening 5% done with no
	way forward.

	From here ERPNext maintains its own quantities from the movements it posts, and
	`stock_drift_report` is how disagreement gets noticed. Re-reading Intacct on a
	schedule and silently correcting would hide the very bugs that cause drift.

	Valuation comes from Intacct (AVERAGE_COST, then LAST_COST); where Intacct holds no
	cost at all the line opens at NO_COST_SENTINEL so the quantity is never lost.
	"""
	company = company or _target_companies()[0]

	# Combinations that already hold stock, so a resumed run does not open them twice.
	#
	# Scoped by the company's actual warehouse list, NOT by a name pattern: warehouse
	# names only end in "- LRC" by ERPNext convention, and a synced Intacct name could
	# break that at any time. Filtering on actual_qty because ERPNext creates Bin rows
	# for things like reorder levels — a Bin alone does not mean stock was opened.
	company_warehouses = frappe.get_all(
		"Warehouse", filters={"company": company}, pluck="name", limit_page_length=0
	)
	already_open = {
		(b.item_code, b.warehouse)
		for b in frappe.get_all(
			"Bin",
			fields=["item_code", "warehouse"],
			filters={"warehouse": ["in", company_warehouses], "actual_qty": ["!=", 0]},
			limit_page_length=0,
		)
	}

	balances = _read_intacct_stock(company)

	# Every item in one query rather than two per row. At ~2,000 rows the per-row version
	# was ~4,000 round trips for data that fits in a single read.
	item_meta = {
		i.name: i
		for i in frappe.get_all(
			"Item",
			fields=["name", "is_stock_item", "has_batch_no", "has_serial_no"],
			filters={"name": ["in", list({code for code, _ in balances})]},
			limit_page_length=0,
		)
	}

	rows = []
	skipped = []
	no_cost = []

	resumed = 0
	for (item_code, warehouse), balance in sorted(balances.items()):
		if balance["qty"] <= 0:
			continue
		if (item_code, warehouse) in already_open:
			# Opened by an earlier run. Never open it twice.
			resumed += 1
			continue

		item = item_meta.get(item_code)
		if not item:
			skipped.append({"item": item_code, "reason": "item not synced"})
			continue
		if not item.is_stock_item:
			# Non-stock in ERPNext but holding a balance in Intacct. Reported rather than
			# dropped silently — it means the two systems disagree about what this is.
			skipped.append({"item": item_code, "warehouse": warehouse, "reason": "not a stock item"})
			continue
		if item.has_batch_no or item.has_serial_no:
			# A tracked item needs its batch or serial identities, which Intacct holds
			# per lot rather than as a warehouse total. Opening those blind would invent
			# tracking data, so they are reported and left for a deliberate decision.
			skipped.append({"item": item_code, "warehouse": warehouse, "reason": "batch or serial tracked"})
			continue

		if balance.get("rate_source") == "sentinel":
			no_cost.append({"item": item_code, "warehouse": warehouse, "qty": balance["qty"]})

		rows.append(
			{
				"item_code": item_code,
				"warehouse": warehouse,
				"qty": balance["qty"],
				"valuation_rate": balance["rate"],
			}
		)

	if not rows:
		return {
			"posted": 0,
			"already_open": resumed,
			"skipped": skipped,
			"note": "Nothing left to open — every balance is already in.",
		}

	# Batched, NOT one document. Leadertread has ~2,600 items across 53 warehouses, so a
	# single Stock Reconciliation could carry tens of thousands of rows — one enormous
	# transaction that times out, and if it fails at row 40,000 the whole opening is lost.
	# Batches also mean a failure is diagnosable: you know which slice broke.
	documents = []
	for start in range(0, len(rows), OPENING_STOCK_BATCH_SIZE):
		batch = rows[start : start + OPENING_STOCK_BATCH_SIZE]
		doc = frappe.new_doc("Stock Reconciliation")
		doc.company = company
		doc.purpose = "Opening Stock"
		for row in batch:
			doc.append("items", row)
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()
		if doc.docstatus != 1:
			# Never report a batch as posted when it is not. A deferred or refused submit
			# leaves a draft with no ledger entries, which is indistinguishable from
			# success unless it is checked.
			frappe.throw(
				f"{doc.name} did not submit (docstatus {doc.docstatus}). "
				f"Batch size is {OPENING_STOCK_BATCH_SIZE} — Frappe defers submit above 100 rows."
			)
		# Commit per batch so an interruption keeps the batches already posted. Combined
		# with the already_open check above, that is what makes a re-run resume rather
		# than duplicate.
		frappe.db.commit()
		documents.append(doc.name)

	return {
		"stock_reconciliations": documents,
		"posted": len(rows),
		"already_open": resumed,
		"batches": len(documents),
		"skipped_count": len(skipped),
		"skipped": skipped[:200],
		"no_cost_count": len(no_cost),
		"no_cost_sample": no_cost[:100],
		"no_cost_note": f"Opened at {NO_COST_SENTINEL} — filter Bin valuation rate = {NO_COST_SENTINEL} for the full list.",
	}


def stock_drift_report(company=None):
	"""Compare ERPNext's on-hand against Intacct's. Read-only — corrects nothing.

	Drift means something is wrong: a movement that failed to post, a manual change,
	or a bug. The point is to see it, not to paper over it.
	"""
	company = company or _target_companies()[0]
	intacct = _read_intacct_stock(company)

	erp = {}
	for row in frappe.get_all(
		"Bin",
		fields=["item_code", "warehouse", "actual_qty"],
		filters={"warehouse": ["in", [w for (_, w) in intacct]]} if intacct else {},
	):
		erp[(row.item_code, row.warehouse)] = row.actual_qty

	# Ignore differences smaller than ERPNext can represent.
	#
	# Intacct holds quantities to 4 decimals, ERPNext stores 3. Comparing raw floats
	# reported 43 "drift" rows on a clean import, every one under a milligram — pure
	# rounding. A report that always shows drift gets ignored, which is worse than no
	# report: the one time it matters, nobody looks.
	from frappe.utils import cint

	precision = cint(frappe.db.get_default("float_precision")) or 3
	tolerance = 10.0**-precision

	drift = []
	rounding_only = 0
	for key in set(intacct) | set(erp):
		item_code, warehouse = key
		intacct_qty = intacct.get(key, {}).get("qty", 0)
		erp_qty = erp.get(key, 0)
		difference = erp_qty - intacct_qty
		if abs(difference) <= tolerance:
			if difference:
				rounding_only += 1
			continue
		drift.append(
			{
				"item": item_code,
				"warehouse": warehouse,
				"intacct": intacct_qty,
				"erpnext": erp_qty,
				"difference": difference,
			}
		)

	drift.sort(key=lambda d: abs(d["difference"]), reverse=True)
	return {
		"company": company,
		"compared": len(set(intacct) | set(erp)),
		"tolerance": tolerance,
		"rounding_only": rounding_only,
		"drift_count": len(drift),
		"drift": drift[:200],
	}


# ──────────────────────────────────────────────────────────────────────────────
# Kits → BOMs
# ──────────────────────────────────────────────────────────────────────────────


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
	"""Stable fingerprint of a recipe, for deciding whether anything actually changed.

	Hashed, not stored raw. A real compound recipe runs to a dozen-plus components and
	the readable form runs past 500 characters — well beyond a Data field. The value is
	only ever compared for equality, never read, so a digest loses nothing.

	Quantities are formatted to a fixed 6 decimals so 0.0085 and 0.00850000 do not
	produce different fingerprints for the same recipe.
	"""
	import hashlib

	readable = "|".join(
		f"{line['item_code']}:{float(line['qty']):.6f}:{line['uom'] or ''}" for line in lines
	)
	# Bump SIGNATURE_VERSION to force every BOM to be rebuilt on the next kits sync —
	# used when something OUTSIDE the recipe changes how a BOM is written. v2: site float
	# precision moved 3 → 4 to match Intacct, and BOMs built at 3 had already lost a digit
	# (0.0085 kg/kg was stored as 0.008 per unit — 8 kg instead of 8.5 on a 1,000 kg batch).
	return hashlib.sha1(f"{SIGNATURE_VERSION}|{readable}".encode()).hexdigest()


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

	# Only ever touch a BOM this sync created. Leadertread needs alternative BOMs for
	# raw-material substitution, and those are built by hand in ERPNext — Intacct has
	# no way to express a second recipe. Matching on "the active BOM for this item"
	# would find a substitution BOM and cancel it, silently destroying someone's work.
	# The Intacct signature is what marks a BOM as ours.
	existing = frappe.db.get_value(
		"BOM",
		{"item": kit_code, "docstatus": 1, "custom_intacct_signature": ["is", "set"]},
		["name", "custom_intacct_signature", "is_default"],
	)
	if existing and existing[1] == signature:
		return "unchanged"

	doc = frappe.new_doc("BOM")
	doc.item = kit_code
	doc.company = company
	doc.quantity = 1
	doc.is_active = 1
	# The Intacct recipe is ALWAYS the default. Substitution BOMs exist for when a raw
	# material is unavailable, and are chosen deliberately on the Work Order — they are
	# the exception, not the standing recipe. So a sync always restores Intacct's as
	# default, even if a substitution was made default in the meantime.
	doc.is_default = 1
	doc.with_operations = 0
	# Valuation Rate resolves to zero here by design — perpetual inventory is off and
	# Intacct owns cost. Verified on this site that a zero-cost BOM both saves and submits.
	doc.rm_cost_as_per = "Valuation Rate"
	doc.custom_intacct_signature = signature

	for line in lines:
		# Substitution is gated by the Item Alternative list, not by this flag: with no
		# approved pairing for a component, allowing alternatives on the line changes
		# nothing. So set it everywhere and let the approved-pairings list be the
		# control — one list to maintain instead of a flag per BOM line.
		row = {"item_code": line["item_code"], "qty": line["qty"], "allow_alternative_item": 1}
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


def sync_all(company=None):
	"""Full masters pull, in dependency order."""
	# Order matters and is not arbitrary: the entity must be mapped before anything can
	# open a session against it, item groups must exist before items are filed into
	# them, UOMs before items reference them, warehouses before bins hang off them, and
	# items before kits can reference them as components.
	return {
		"entities": map_entities(company=company),
		"item_groups": sync_item_groups(company=company),
		"warehouses": sync_warehouses(company=company),
		"uoms": sync_uoms(),
		"items": sync_items(),
		"bins": sync_bins(company=company),
		"kits": sync_kits(company=company),
		# Last, because it decides what to keep by what Intacct actually sent.
		"removed_defaults": remove_erpnext_defaults(company=company),
	}


# ──────────────────────────────────────────────────────────────────────────────
# Background execution
#
# A full sync will not fit in a web request. Leadertread has ~2,600 items and tens of
# thousands of component rows; kits alone means two large paged queries plus an insert
# and submit per BOM. Run it on the long queue and read the result off Intacct Settings.
# ──────────────────────────────────────────────────────────────────────────────

# The ONLY two ways to run a sync are enqueue_sync and run_now, both of which take the
# lock. The individual sync functions are deliberately NOT whitelisted: a direct API call
# to sync_items would open its own gateway session alongside whatever else is running and
# walk straight past the concurrency guard.
def _lock_busy_exceptions():
	"""Whatever this install raises when a filelock is already held.

	Named explicitly rather than assumed: Frappe wraps the `filelock` package and the
	exception has moved between versions. Catching the wrong class means the guard looks
	present in the code and does nothing at runtime — the worst kind of safety check.
	"""
	found = [TimeoutError]
	if hasattr(frappe, "LockTimeoutError"):
		found.append(frappe.LockTimeoutError)
	try:
		from filelock import Timeout

		found.append(Timeout)
	except ImportError:
		pass
	return tuple(found)


_LOCK_BUSY = _lock_busy_exceptions()

JOBS = {
	"entities": "list_entities",
	"map_entities": "map_entities",
	"item_groups": "sync_item_groups",
	"warehouses": "sync_warehouses",
	"uoms": "sync_uoms",
	"items": "sync_items",
	"bins": "sync_bins",
	"kits": "sync_kits",
	"all": "sync_all",
	"opening_stock": "post_opening_stock",
	"drift": "stock_drift_report",
	"remove_defaults": "remove_erpnext_defaults",
	# Used by the scheduler, not normally queued by hand.
	"items_incremental": "_sync_items_incremental",
	"config": "_sync_config",
}


@frappe.whitelist()
def enqueue_sync(job, company=None):
	"""Queue one sync to run in the background. Returns immediately.

	Read the outcome from Intacct Settings → Last Sync Result.
	"""
	if job not in JOBS:
		frappe.throw(f"Unknown job '{job}'. One of: {', '.join(sorted(JOBS))}")

	frappe.enqueue(
		"fuse_manufacturing.masters.run_sync",
		queue="long",
		timeout=3600,
		job_name=f"fuse-sync-{job}",
		job=job,
		company=company,
	)
	return {"queued": job}


@frappe.whitelist()
def run_now(job, company=None):
	"""Run one sync immediately, still behind the lock.

	For the small, quick ones — entities, uoms, drift. Anything that touches the full
	item or component master belongs on the queue: it will not fit in a web request.
	"""
	if job not in JOBS:
		frappe.throw(f"Unknown job '{job}'. One of: {', '.join(sorted(JOBS))}")
	return run_sync(job, company=company)


def run_sync(job, company=None):
	"""Run a named sync and record the outcome. Called by the queue, not directly.

	Serialised behind a single lock. Intacct allows only about FIVE concurrent
	connections per company and QUEUES the rest rather than rejecting them, so
	overlapping syncs do not fail loudly — they crawl, and then hit the 15-minute
	request timeout looking like an Intacct problem. The hourly item sync, the daily
	config sync and any manually queued job would otherwise happily run at once.
	"""
	import traceback

	from frappe.utils import now_datetime
	from frappe.utils.synchronization import filelock

	started = now_datetime()

	try:
		# Non-blocking: a second sync does not stack up behind the first, it stands down
		# and says so. Queueing them would just move the concurrency problem.
		with filelock("fuse_intacct_sync", timeout=1):
			try:
				fn = globals()[JOBS[job]]
				# sync_uoms and list_entities take no company — UOMs are shared across
				# the whole Intacct company, and entities ARE the list of companies.
				result = fn() if job in ("uoms", "entities") else fn(company=company)
				payload = {"job": job, "status": "ok", "result": result}
			except Exception:
				# Record the failure where it can be read, then re-raise so it also
				# lands in the Error Log with a full traceback.
				payload = {"job": job, "status": "failed", "error": traceback.format_exc()[-2000:]}
				_record_sync_result(payload, started)
				raise
	except _LOCK_BUSY:
		payload = {
			"job": job,
			"status": "skipped",
			"reason": "another Intacct sync is already running — not stacking a second one",
		}
		_record_sync_result(payload, started)
		return payload

	_record_sync_result(payload, started)
	return payload


def _record_sync_result(payload, started):
	import json

	frappe.db.set_single_value(
		"Intacct Settings",
		{
			"last_sync_result": json.dumps(payload, indent=2, default=str)[:9000],
			"last_sync_at": started,
		},
	)
	frappe.db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Scheduled entry points
# ──────────────────────────────────────────────────────────────────────────────

# How far back to re-read on an incremental item sync, on top of the last run time.
# Intacct stamps WHENMODIFIED in the company's own timezone, which is not guaranteed to
# match the site's. An hour of deliberate overlap costs one extra page and removes a
# whole class of silently-missed records. The sync is idempotent, so re-reading is free.
ITEM_SYNC_OVERLAP_HOURS = 1


def scheduled_item_sync():
	"""Hourly. Incremental on WHENMODIFIED, with an hour of overlap.

	Goes through run_sync so it takes the same lock as everything else — the hourly job
	must never overlap the daily one, or a manual pull, and open competing sessions.
	"""
	if not _enabled():
		return
	return run_sync("items_incremental")


def _sync_items_incremental(company=None):
	from frappe.utils import add_to_date, get_datetime, now_datetime

	last = frappe.db.get_single_value("Intacct Settings", "last_item_sync")
	since = None
	if last:
		# A cleared watermark can come back as something that parses to year 1, and
		# subtracting the overlap from that overflows — which crashed this job every
		# hour until it was noticed. Anything implausible means "no watermark", so fall
		# back to a full read rather than failing.
		parsed = get_datetime(last)
		if parsed and parsed.year >= 2000:
			since = add_to_date(parsed, hours=-ITEM_SYNC_OVERLAP_HOURS).strftime("%m/%d/%Y %H:%M:%S")

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
	return run_sync("config")


def _sync_config(company=None):
	return {
		"item_groups": sync_item_groups(company=company),
		"warehouses": sync_warehouses(company=company),
		"uoms": sync_uoms(),
		"bins": sync_bins(company=company),
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


def align_float_precision(seen_precisions):
	"""Set ERPNext's float precision from Intacct's own INV_PRECISION.

	Intacct is the source for decimal places as it is for everything else, so this reads
	the highest precision any item uses and matches it rather than hardcoding a number.

	ONLY EVER RAISES IT. Lowering the precision would silently round every quantity
	already stored — a data change disguised as a setting change. If Intacct's precision
	drops, that is reported and left for a human.
	"""
	from frappe.utils import cint

	wanted = max([cint(p) for p in seen_precisions if cint(p)] or [0])
	if not wanted:
		return {"changed": False, "reason": "Intacct returned no INV_PRECISION values"}

	wanted = max(MIN_FLOAT_PRECISION, min(wanted, MAX_FLOAT_PRECISION))
	current = cint(frappe.db.get_single_value("System Settings", "float_precision")) or 3

	if wanted == current:
		return {"changed": False, "precision": current}

	if wanted < current:
		return {
			"changed": False,
			"precision": current,
			"intacct_precision": wanted,
			"warning": (
				f"Intacct's precision ({wanted}) is LOWER than ERPNext's ({current}). "
				"Not lowered automatically — that would round every quantity already stored. "
				"Change it deliberately if that is really what you want."
			),
		}

	frappe.db.set_single_value("System Settings", "float_precision", str(wanted))
	frappe.clear_cache()
	return {
		"changed": True,
		"from": current,
		"to": wanted,
		"note": "Records written before this change keep their old rounding — re-import to rebuild them.",
	}


def _has_changes(doc):
	"""True when an in-memory doc differs from what is stored.

	Frappe tracks this itself via get_doc_before_save, but only after a load; comparing
	the loaded values directly is simpler and does not depend on that being populated.
	"""
	if doc.is_new():
		return True
	stored = frappe.db.get_value(doc.doctype, doc.name, "*", as_dict=True) or {}
	for field in doc.meta.get_valid_columns():
		if field in ("modified", "modified_by", "creation", "owner", "idx", "_user_tags",
		             "_comments", "_assign", "_liked_by", "docstatus"):
			continue
		if str(stored.get(field) or "") != str(doc.get(field) or ""):
			return True
	return False


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
