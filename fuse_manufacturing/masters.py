"""Masters in — a one-way read-only mirror, Intacct → ERPNext.

Intacct owns these records. Nothing here writes back, and nothing here invents a value.
Run in order: warehouses → UOMs → items → bins. Items need the UOMs to exist first, and
bins hang off warehouses.

Every function is idempotent: run it twice and the second run changes nothing.
"""

import frappe

from fuse_manufacturing import gateway, rules
from fuse_manufacturing.gateway import flag, number, val

# The decision logic lives in rules.py, which imports no Frappe and is covered by tests
# that run in a second without a site. Re-exported here so callers keep one import.
NO_COST_SENTINEL = rules.NO_COST_SENTINEL
SIGNATURE_VERSION = rules.SIGNATURE_VERSION
MIN_FLOAT_PRECISION = rules.MIN_FLOAT_PRECISION
MAX_FLOAT_PRECISION = rules.MAX_FLOAT_PRECISION

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


def list_transaction_definitions(company=None):
	"""Every inventory transaction definition this Intacct company actually has.

	Reads, never writes. Every tenant is configured differently, and the definition names
	the postings use must match character for character — so they are verified against
	the company rather than assumed from another one.

	What matters per definition:
	  IN_OUT       Increase or Decrease — the direction the definition applies itself,
	               which is why quantities are always sent POSITIVE.
	  UPDATES_COST Whether it values the movement. Send a cost only where this is true;
	               on a consume leg it would override Intacct's own valuation.
	  CREATETYPE   Convert-only definitions cannot be posted through create_ictransaction
	               at all — they exist only by converting a source document.
	"""
	rows = gateway.query(
		"INVDOCUMENTPARAMS",
		["RECORDNO", "DOCID", "DESCRIPTION", "DOCCLASS", "IN_OUT", "UPDATES_COST",
		 "UPDATES_INV", "CREATETYPE", "STATUS", "ENABLE_SEQNUM", "SEQUENCE",
		 "INHERIT_SOURCE_DOCNO"],
		company=company,
	)

	definitions = [
		{
			"docid": val(row, "DOCID"),
			"description": val(row, "DESCRIPTION"),
			"class": val(row, "DOCCLASS"),
			"in_out": val(row, "IN_OUT"),
			"updates_cost": val(row, "UPDATES_COST"),
			"updates_inventory": val(row, "UPDATES_INV"),
			"create_type": val(row, "CREATETYPE"),
			"status": val(row, "STATUS"),
			# Whether Intacct numbers the document itself. Without a numbering scheme the
			# post is rejected with PL01000127 "Document Number is missing" — which says
			# nothing about numbering schemes and sends you looking at the line items.
			"auto_numbered": val(row, "ENABLE_SEQNUM"),
			"sequence": val(row, "SEQUENCE"),
			"inherits_source_docno": val(row, "INHERIT_SOURCE_DOCNO"),
		}
		for row in rows
	]
	definitions.sort(key=lambda d: (d["docid"] or "").lower())

	# Flag the ones the postings depend on, so a name mismatch is obvious rather than
	# surfacing later as a rejection nobody can place.
	from fuse_manufacturing import postings

	required = {
		postings.MANUFACTURING_CONSUME,
		postings.MANUFACTURING_PRODUCE,
		postings.MANUFACTURING_UNCONSUME,
		postings.MANUFACTURING_UNPRODUCE,
	}
	present = {d["docid"] for d in definitions}
	missing = sorted(required - present)

	# Present but unusable is the harder failure to place: the definition exists, the name
	# matches, and the post is still rejected. Reported alongside missing so a new client's
	# gaps are visible at sync time rather than at the first cancel.
	def is_true(value):
		# Intacct returns these as the STRINGS "true"/"false". Testing them for truthiness
		# passes "false", which is how a definition with no numbering read as fine.
		return str(value).strip().lower() in ("true", "1")

	# Fuse sends its own documentno on these, so Intacct not numbering them is expected
	# rather than a fault. INHERIT_SOURCE_DOCNO does not help — it only applies when a
	# document is created by converting another, and these are created directly.
	fuse_numbers = {postings.MANUFACTURING_UNCONSUME, postings.MANUFACTURING_UNPRODUCE}

	unnumbered = [d["docid"] for d in definitions if d["docid"] in required and not is_true(d["auto_numbered"])]
	not_numbered = sorted(docid for docid in unnumbered if docid not in fuse_numbers)
	numbered_by_fuse = sorted(docid for docid in unnumbered if docid in fuse_numbers)
	# CREATETYPE cannot be trusted for SYS- definitions. `SYS-CC Adjustment Increase` reports
	# "New document or Convert" and is still rejected at post time with "cannot be created
	# directly — use Cycle Count to create this document". They belong to Intacct's own
	# features and are only reachable through them, whatever the field says.
	unpostable = sorted(
		d["docid"] for d in definitions
		if d["docid"] in required
		and ("convert only" in (d["create_type"] or "").lower() or d["docid"].startswith("SYS-"))
	)

	problems = []
	if missing:
		problems.append(f"missing: {', '.join(missing)} — the name must match exactly")
	if not_numbered:
		problems.append(
			f"no numbering scheme: {', '.join(not_numbered)} — will be rejected with "
			"PL01000127 'Document Number is missing' until one is attached in Intacct"
		)
	if unpostable:
		problems.append(f"convert-only: {', '.join(unpostable)} — cannot be created directly")

	note = "; ".join(problems) if problems else "All definitions the postings use are present and usable."
	if numbered_by_fuse and not problems:
		note += (
			f" ({', '.join(numbered_by_fuse)} have no numbering scheme, so Fuse supplies the "
			"document number. Attach a scheme in Intacct and that can be dropped.)"
		)

	return {
		"count": len(definitions),
		"definitions": definitions,
		"required_by_postings": sorted(required),
		"missing": missing,
		"not_numbered": not_numbered,
		"numbered_by_fuse": numbered_by_fuse,
		"unpostable": unpostable,
		"note": note,
	}


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
# Open purchase orders → ERPNext Purchase Orders (stock on order)
# ──────────────────────────────────────────────────────────────────────────────

PO_LINE_FIELDS = [
	"DOCHDRID", "DOCPARID", "LINE_NO", "ITEMID", "UNIT", "QTY_REMAINING",
	"WAREHOUSE.LOCATION_NO", "VENDORID", "PRICE",
]
PO_HEADER_FIELDS = ["DOCID", "WHENCREATED", "WHENDUE", "CURRENCY", "STATE"]


def _order_templates(company=None):
	"""Intacct document templates that are purchase ORDERS, read from Intacct.

	Not a hardcoded "Inventory purchase order": the name differs per client, and both the
	inventory and non-inventory templates report UPDATES_INV = No, so that field cannot
	separate them either. DOCCLASS = Order is what makes a template an order rather than a
	requisition, receipt or invoice; whether a LINE matters for stock is then decided by
	the item, which is the honest test.
	"""
	rows = gateway.query("PODOCUMENTPARAMS", ["DOCID", "DOCCLASS", "STATUS"], company=company)
	return {
		val(row, "DOCID")
		for row in rows
		if (val(row, "DOCCLASS") or "").strip().lower() == "order"
		and (val(row, "STATUS") or "").strip().lower() == "active"
	}


def sync_purchase_orders(company=None):
	"""Intacct open purchase orders → ERPNext Purchase Orders.

	The point is stock ON ORDER: a submitted Purchase Order is the only thing that fills
	Bin.ordered_qty, which is what Stock Projected Qty and demand reporting read. Nothing
	is ever received here — receipting belongs to Intacct and is blocked outright.

	Quantity is QTY_REMAINING, so an order partly received in Intacct shows only what is
	still coming. When nothing is outstanding the ERPNext order is CLOSED, which drops it
	out of ordered_qty while keeping the document.
	"""
	templates = _order_templates(company)
	if not templates:
		return {"skipped": "no active order templates in Intacct"}

	rows = gateway.query(
		"PODOCUMENTENTRY",
		PO_LINE_FIELDS,
		filter_xml="<greaterthan><field>QTY_REMAINING</field><value>0</value></greaterthan>",
		company=company,
	)

	target = frappe.defaults.get_user_default("Company") or _target_companies(company)[0]

	orders, problems = {}, []
	for row in rows:
		if val(row, "DOCPARID") not in templates:
			continue

		item_code = val(row, "ITEMID")
		warehouse_id = val(row, "WAREHOUSE.LOCATION_NO")

		# The item decides whether a line is stock at all. A non-inventory order buys
		# services and expenses; those items are not stock items here, and an order line
		# without a warehouse has nowhere to arrive.
		if not frappe.db.get_value("Item", item_code, "is_stock_item"):
			continue
		if not warehouse_id:
			continue

		warehouse = frappe.db.get_value(
			"Warehouse", {"custom_intacct_warehouse_id": warehouse_id, "company": target}, "name"
		)
		if not warehouse:
			problems.append(f"{val(row, 'DOCHDRID')}: warehouse {warehouse_id} is not in ERPNext")
			continue

		orders.setdefault(val(row, "DOCHDRID"), {"vendor": val(row, "VENDORID"), "lines": []})
		orders[val(row, "DOCHDRID")]["lines"].append(
			{
				"item_code": item_code,
				"qty": float(val(row, "QTY_REMAINING") or 0),
				# From the Item, not the order line — the same rule the postings follow.
				"uom": frappe.db.get_value("Item", item_code, "stock_uom"),
				"warehouse": warehouse,
				"rate": float(val(row, "PRICE") or 0),
				"schedule_date": None,  # filled from the header below
			}
		)

	headers = {}
	if orders:
		for row in gateway.query("PODOCUMENT", PO_HEADER_FIELDS, company=company):
			if val(row, "DOCID") in orders:
				headers[val(row, "DOCID")] = row

	created = updated = closed = unchanged = 0

	for doc_id, order in orders.items():
		header = headers.get(doc_id)
		due = rules.intacct_date(val(header, "WHENDUE")) if header else None
		if not due:
			problems.append(f"{doc_id}: no due date on the Intacct order, skipped")
			continue
		for line in order["lines"]:
			line["schedule_date"] = due

		supplier = frappe.db.get_value("Supplier", {"custom_intacct_vendor_id": order["vendor"]}, "name")
		if not supplier:
			problems.append(f"{doc_id}: supplier {order['vendor']} is not in ERPNext — run the suppliers sync")
			continue

		existing = frappe.db.get_value("Purchase Order", {"custom_intacct_po_id": doc_id, "docstatus": 1}, "name")
		if existing:
			current = frappe.get_doc("Purchase Order", existing)
			live = [
				{
					"item_code": row.item_code,
					"qty": row.qty,
					"warehouse": row.warehouse,
					"schedule_date": str(row.schedule_date),
				}
				for row in current.items
			]
			if rules.purchase_order_signature(live) == rules.purchase_order_signature(
				[dict(line, schedule_date=str(line["schedule_date"])) for line in order["lines"]]
			):
				unchanged += 1
				continue

			# Quantities moved. There is no receipt history here to preserve — nothing is
			# ever received in ERPNext — so cancelling and rebuilding is simpler and always
			# correct, where editing a submitted order in place is neither.
			current.cancel()
			updated += 1
		else:
			created += 1

		po = frappe.new_doc("Purchase Order")
		po.supplier = supplier
		po.company = target
		# The date Intacct raised the order, NOT today. Dating a mirrored order today puts
		# it after its own due date whenever the due date has passed, and ERPNext refuses
		# that with "Required By cannot be before Date". It is also simply wrong — the
		# order was placed when it was placed.
		raised = rules.intacct_date(val(header, "WHENCREATED")) or due
		po.transaction_date = min(raised, due)
		po.schedule_date = due
		po.custom_intacct_po_id = doc_id
		po.custom_intacct_synced_on = frappe.utils.now_datetime()

		currency = val(header, "CURRENCY")
		if currency and frappe.db.exists("Currency", currency):
			po.currency = currency

		for line in order["lines"]:
			po.append("items", line)

		po.flags.ignore_permissions = True
		po.insert(ignore_permissions=True)
		po.submit()

	# Orders mirrored earlier that Intacct no longer reports as outstanding have been
	# received there. Closed, not cancelled: the order did happen, and closing is what
	# takes it out of ordered_qty.
	for name, doc_id in frappe.get_all(
		"Purchase Order",
		filters={"custom_intacct_po_id": ("is", "set"), "docstatus": 1, "status": ("not in", ("Closed",))},
		fields=["name", "custom_intacct_po_id"],
		as_list=True,
	):
		if doc_id not in orders:
			frappe.get_doc("Purchase Order", name).update_status("Closed")
			closed += 1

	return {
		"open_orders": len(orders),
		"created": created,
		"rebuilt": updated,
		"unchanged": unchanged,
		"closed": closed,
		"problems": problems,
	}


# ──────────────────────────────────────────────────────────────────────────────
# Vendors → Suppliers
# ──────────────────────────────────────────────────────────────────────────────

VENDOR_FIELDS = [
	"RECORDNO", "VENDORID", "NAME", "STATUS", "CURRENCY", "TERMNAME", "VENDTYPE", "ONETIME",
]

# Where suppliers land when Intacct gives no vendor type. ERPNext makes supplier_group
# mandatory, so something has to be chosen — this is the one place a name is invented, and
# only for suppliers Intacct itself has not classified.
UNCLASSIFIED_SUPPLIER_GROUP = "Intacct — Unclassified"


def _supplier_group(vendor_type):
	"""Mirror Intacct's vendor type as an ERPNext Supplier Group, creating it if new.

	Vendor type is Intacct's own classification, so it is the honest source for the group
	rather than filing every supplier under one default of our choosing.
	"""
	name = (vendor_type or "").strip() or UNCLASSIFIED_SUPPLIER_GROUP

	if not frappe.db.exists("Supplier Group", name):
		frappe.get_doc(
			{
				"doctype": "Supplier Group",
				"supplier_group_name": name,
				# Supplier Group is a tree; a new node without a parent becomes a second
				# root, which ERPNext rejects.
				"parent_supplier_group": _root_supplier_group(),
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	return name


def _root_supplier_group():
	root = frappe.db.get_value("Supplier Group", {"is_group": 1, "parent_supplier_group": ("in", ("", None))}, "name")
	if not root:
		frappe.throw("No root Supplier Group exists on this site — ERPNext setup is incomplete.")
	return root


def sync_suppliers(company=None):
	"""Intacct VENDOR → ERPNext Supplier.

	Needed before purchase orders can be mirrored: an ERPNext Purchase Order requires a
	Supplier, and PO lines identify one only by VENDORID.

	Read-only mirror, like every other master. Suppliers are disabled rather than deleted
	when Intacct retires them — a supplier with purchase history cannot be removed, and the
	history does not stop being true.
	"""
	rows = gateway.query("VENDOR", VENDOR_FIELDS, company=company)

	created = updated = 0
	for row in rows:
		vendor_id = val(row, "VENDORID")
		if not vendor_id:
			continue

		existing = frappe.db.get_value("Supplier", {"custom_intacct_vendor_id": vendor_id}, "name")
		if existing:
			doc = frappe.get_doc("Supplier", existing)
			updated += 1
		else:
			doc = frappe.new_doc("Supplier")
			created += 1

		doc.supplier_name = val(row, "NAME") or vendor_id
		doc.custom_intacct_vendor_id = vendor_id
		doc.custom_intacct_recordno = val(row, "RECORDNO")
		doc.supplier_group = _supplier_group(val(row, "VENDTYPE"))
		doc.disabled = 0 if (val(row, "STATUS") or "").lower() == "active" else 1

		# Only where the currency exists on the site. Intacct may name one ERPNext has not
		# been given, and an unknown link fails the whole save for a field nothing depends
		# on yet.
		currency = val(row, "CURRENCY")
		if currency and frappe.db.exists("Currency", currency):
			doc.default_currency = currency

		if doc.is_new() or _has_changes(doc):
			doc.save(ignore_permissions=True)
		elif existing:
			updated -= 1

	return {"read": len(rows), "created": created, "updated": updated}


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
	# One read, not one per item per unit — this loop runs 2,600 times.
	known_uoms = set(frappe.get_all("UOM", pluck="name", limit_page_length=0))

	# Precision FIRST, before a single item is written.
	#
	# This used to run at the end, which meant a fresh install imported every item at
	# ERPNext's default precision and only then raised it — leaving 2,566 items rounded
	# and needing a full re-import. Exactly the misalignment a self-configuring install
	# is meant to prevent. The rows are already in memory, so this costs nothing.
	precision_result = align_float_precision({val(row, "INV_PRECISION") for row in rows})

	for row in rows:
		item_code = val(row, "ITEMID")
		if not item_code:
			continue

		uom = val(row, "BASEUOM")
		if uom and uom not in known_uoms:
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
		doc.is_stock_item = 1 if rules.is_stock_item(item_type) else 0
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
		conversions, unknown = rules.build_conversions(
			uom,
			(val(row, "UOM.POUOMDETAIL.UNIT"), number(row, "UOM.POUOMDETAIL.CONVFACTOR", 0)),
			(val(row, "UOM.SOUOMDETAIL.UNIT"), number(row, "UOM.SOUOMDETAIL.CONVFACTOR", 0)),
			known_uoms,
		)
		missing_uoms.update(unknown)

		if conversions:
			doc.set(
				"uoms",
				[{"uom": u, "conversion_factor": f} for u, f in conversions.items()],
			)

		# Barcodes — the scanner flows need these, and Intacct already holds them.
		# Rebuilt from Intacct each run rather than appended, so a barcode removed
		# there disappears here instead of lingering and scanning to a stale item.
		barcodes = []
		for value in (val(row, "UPC"), val(row, "EAN13")):
			if not value or any(existing["barcode"] == value for existing in barcodes):
				continue
			# The type is only claimed when the number actually is one. See
			# rules.barcode_type — a client's internal code scans exactly the same
			# with no type, and tagging it would fail the item save outright.
			barcodes.append({"barcode": value, "barcode_type": rules.barcode_type(value) or ""})
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
	result["float_precision"] = precision_result
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

	Refuses to run unless the masters are already in. It decides what to KEEP from what
	Intacct sent, so against an empty or half-synced site it would conclude that nothing
	is in use and remove everything. That must not depend on anyone remembering to run
	it in the right order.
	"""
	company = company or _target_companies()[0]

	items = frappe.db.count("Item")
	warehouses = frappe.db.count("Warehouse", {"custom_intacct_warehouse_id": ["is", "set"]})
	if not items or not warehouses:
		frappe.throw(
			f"Refusing to remove defaults: the site has {items} items and {warehouses} "
			"Intacct warehouses. Run the masters sync first — this decides what to keep "
			"from what Intacct sent, and against an empty site that is nothing."
		)

	# ── UOMs ────────────────────────────────────────────────────────────────
	# Keep anything an Item actually references, whether as its stock unit or as a
	# purchase/sales conversion. Deleting a UOM in use would break those items.
	# UOM Conversion Detail is a child table, and Frappe refuses a get_all on one without
	# a parent filter — so read it directly. Missing these would disable the purchase and
	# sales units we just imported, which is the opposite of the intent.
	in_use = set(frappe.get_all("Item", pluck="stock_uom", limit_page_length=0))

	# Also every unit any existing document already uses. Disabling one that a BOM or a
	# stock movement references does not break the stored record, but it does break the
	# next validation of it — and those documents are history we do not get to edit.
	for table, column in (
		("tabUOM Conversion Detail", "uom"),
		("tabBOM Item", "uom"),
		("tabBOM", "uom"),
		("tabStock Entry Detail", "uom"),
		("tabStock Reconciliation Item", "uom"),
		("tabWork Order Item", "stock_uom"),
	):
		try:
			in_use.update(
				row[0]
				for row in frappe.db.sql(
					f"select distinct `{column}` from `{table}` where `{column}` is not null"
				)
			)
		except Exception:
			# A doctype that does not exist on this site is not an error — the app must
			# install on instances without every ERPNext module in play.
			frappe.db.rollback()

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
		rate, source = rules.choose_rate(number(row, "AVERAGE_COST", 0), number(row, "LAST_COST", 0))

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

	precision = cint(frappe.db.get_default("float_precision")) or rules.MIN_FLOAT_PRECISION

	drift = []
	rounding_only = 0
	for key in set(intacct) | set(erp):
		item_code, warehouse = key
		intacct_qty = intacct.get(key, {}).get("qty", 0)
		erp_qty = erp.get(key, 0)
		difference = erp_qty - intacct_qty
		if not rules.is_drift(intacct_qty, erp_qty, precision):
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
		"tolerance": 10.0**-precision,
		"rounding_only": rounding_only,
		"drift_count": len(drift),
		"drift": drift[:200],
	}


# ──────────────────────────────────────────────────────────────────────────────
# Kits → BOMs
# ──────────────────────────────────────────────────────────────────────────────


def sync_kits(company=None, rebuild=False):
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

	# ── Pass 1: work out the dependency order ───────────────────────────────
	# A kit can only be built once every kit it consumes has a BOM, so ERPNext links the
	# sub-assembly instead of treating it as a raw part. Establish that order FIRST,
	# without touching anything, because cancellation needs the exact reverse of it.
	build_order, circular = rules.kit_build_order(kit_codes, by_kit)
	for code in circular:
		# A kit that ultimately contains itself. Intacct allows it to be saved; ERPNext
		# cannot explode it and neither can a factory.
		skipped.append({"kit": code, "reason": "circular recipe"})

	# ── Pass 2: decide what to build, then clear what it replaces ───────────
	to_build = {}
	changed = []
	for code in build_order:
		lines = sorted(by_kit.get(code, []), key=lambda x: x["line"])
		signature = _recipe_signature(lines)
		existing = frappe.db.get_value(
			"BOM",
			{"item": code, "docstatus": 1, "custom_intacct_signature": ["is", "set"]},
			["name", "custom_intacct_signature"],
		)
		if existing and existing[1] == signature:
			unchanged += 1
			continue

		if existing and not rebuild:
			# The recipe changed in Intacct but a BOM already exists. REPORTED, NOT
			# REPLACED — replacing means cancelling, and ERPNext refuses to cancel a BOM
			# with open Work Orders against it, which on a live site is the normal state.
			# Forcing it would fail routinely; failing quietly would leave production
			# running a recipe Intacct has changed. Both are worse than telling someone.
			changed.append({"kit": code, "bom": existing[0], "components": len(lines)})
			continue

		to_build[code] = existing[0] if existing else None

	# Cancel outgoing BOMs PARENTS FIRST — only on an explicit rebuild.
	# ERPNext refuses to cancel a BOM another BOM still links to, so a sub-assembly
	# cannot go until every parent consuming it has gone. That is the exact reverse of
	# the build order.
	blocked = []
	if rebuild:
		for code in reversed(build_order):
			old = to_build.get(code)
			if not old:
				continue
			try:
				doc = frappe.get_doc("BOM", old)
				doc.db_set("is_default", 0)
				doc.db_set("is_active", 0)
				doc.cancel()
				# COMMIT THE CANCEL BEFORE ATTEMPTING THE DELETE. If the delete fails and
				# rolls back an uncommitted cancel, the BOM returns to submitted, a
				# replacement gets built anyway, and the kit ends up with two active BOMs
				# — the exact mess this ordering exists to prevent.
				frappe.db.commit()

				# Delete rather than leave it cancelled. These are mirror artefacts of an
				# Intacct recipe, not records of anything that happened. If the delete is
				# refused the cancel still stands and the rebuild proceeds.
				try:
					frappe.delete_doc("BOM", old, ignore_permissions=True, force=False)
					frappe.db.commit()
				except Exception:
					frappe.db.rollback()
			except Exception as exc:
				# Almost always an open Work Order against it. Report and leave the
				# existing BOM alone — do NOT build a replacement it cannot displace,
				# or the kit ends up with two active BOMs and no clear default.
				frappe.db.rollback()
				blocked.append({"kit": code, "bom": old, "reason": str(exc)[:200]})
				to_build.pop(code, None)

	# ── Pass 3: build the new ones, children first ──────────────────────────
	for code in build_order:
		if code not in to_build:
			continue
		lines = sorted(by_kit.get(code, []), key=lambda x: x["line"])
		outcome = _build_bom(code, lines, company)
		if outcome == "created":
			if to_build[code]:
				replaced += 1
			else:
				created += 1
		else:
			skipped.append({"kit": code, "reason": outcome})

	frappe.db.commit()
	result = {
		"kits_found": len(kits),
		"kits_with_recipe": len(by_kit),
		"created": created,
		"replaced": replaced,
		"unchanged": unchanged,
		"skipped": skipped,
	}
	if changed:
		result["changed_in_intacct_count"] = len(changed)
		result["changed_in_intacct"] = changed[:200]
		result["changed_note"] = (
			"These recipes changed in Intacct but their BOM was NOT replaced — replacing "
			"means cancelling, and ERPNext refuses that with open Work Orders. Review, "
			"then run the 'kits_rebuild' job to replace them."
		)
	if blocked:
		result["blocked_count"] = len(blocked)
		result["blocked"] = blocked[:200]
		result["blocked_note"] = "Could not be cancelled — almost always an open Work Order. Left as they were."
	return result


def rebuild_kits(company=None):
	"""Replace every Intacct-sourced BOM, cancelling parents before children.

	Deliberate and disruptive: use it when something outside the recipe changes how BOMs
	must be written — a precision change, for instance — or to apply recipe changes that
	the normal sync has reported but not applied.

	During the rebuild a kit briefly has no active BOM. Unavoidable: ERPNext will not let
	the old and new both be active, nor let the old go while a parent links to it. Run it
	outside production hours.
	"""
	return sync_kits(company=company, rebuild=True)


_recipe_signature = rules.recipe_signature


def _build_bom(kit_code, lines, company):
	"""Create the BOM for one kit. Returns an outcome string.

	Only creates. Anything it replaces has already been cancelled and deleted by
	sync_kits, in parent-first order.
	"""
	if not frappe.db.exists("Item", kit_code):
		return "kit item not synced"

	missing = [line["item_code"] for line in lines if not frappe.db.exists("Item", line["item_code"])]
	if missing:
		return f"components not synced: {', '.join(sorted(set(missing))[:5])}"

	bad_uom = [line["uom"] for line in lines if line["uom"] and not frappe.db.exists("UOM", line["uom"])]
	if bad_uom:
		return f"unit not on site: {', '.join(sorted(set(bad_uom))[:5])}"

	signature = _recipe_signature(lines)

	# Any outgoing BOM has already been cancelled by the caller, parents first — see
	# sync_kits. Cancelling here would fail the moment a recipe has any depth, because
	# ERPNext refuses to cancel a BOM another BOM still links to.
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
		# Independent of the stock masters, but before purchase orders can be mirrored:
		# a Purchase Order needs a Supplier, and PO lines name one only by VENDORID.
		"suppliers": sync_suppliers(company=company),
		# After suppliers, items and warehouses — an order line needs all three to land.
		"purchase_orders": sync_purchase_orders(company=company),
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
	"definitions": "list_transaction_definitions",
	"map_entities": "map_entities",
	"item_groups": "sync_item_groups",
	"suppliers": "sync_suppliers",
	"purchase_orders": "sync_purchase_orders",
	"warehouses": "sync_warehouses",
	"uoms": "sync_uoms",
	"items": "sync_items",
	"bins": "sync_bins",
	"kits": "sync_kits",
	"kits_rebuild": "rebuild_kits",
	"all": "sync_all",
	"opening_stock": "post_opening_stock",
	"drift": "stock_drift_report",
	"remove_defaults": "remove_erpnext_defaults",
	# Re-applies the app's own custom fields and roles. Needed because after_migrate does
	# not reliably fire on a Frappe Cloud deploy — the code ships and the field definitions
	# do not. Idempotent, so running it is never wrong.
	"setup": "_run_setup",
	# Used by the scheduler, not normally queued by hand.
	"items_incremental": "_sync_items_incremental",
	"config": "_sync_config",
}


def _run_setup(company=None):
	"""Re-apply the custom fields and roles this version of the app expects."""
	from fuse_manufacturing.install import after_install

	return after_install()


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


def scheduled_order_sync():
	"""Hourly. Suppliers first, then open purchase orders.

	Stock on order goes stale continuously — Intacct receives against these orders through
	the day and the outstanding quantity falls with each receipt. An hour behind is
	immaterial for planning, and the work is small: only lines with quantity remaining are
	read, and an order that has not changed is left alone.

	Suppliers go first in the SAME job because a purchase order needs one. A supplier added
	in Intacct this morning would otherwise block its own order until someone noticed.

	Through run_sync so it takes the same lock as every other sync — two jobs opening
	competing Intacct sessions is the thing the lock exists to prevent.
	"""
	if not _enabled():
		return
	return {
		"suppliers": run_sync("suppliers"),
		"purchase_orders": run_sync("purchase_orders"),
	}


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

	current = cint(frappe.db.get_single_value("System Settings", "float_precision"))
	decision = rules.decide_precision(seen_precisions, current)

	if decision["action"] == "none":
		return {"changed": False, **{k: v for k, v in decision.items() if k != "action"}}

	if decision["action"] == "warn":
		return {
			"changed": False,
			"precision": decision["precision"],
			"intacct_precision": decision["intacct_precision"],
			"warning": (
				f"Intacct's precision ({decision['intacct_precision']}) is LOWER than "
				f"ERPNext's ({decision['precision']}). Not lowered automatically — that "
				"would round every quantity already stored."
			),
		}

	frappe.db.set_single_value("System Settings", "float_precision", str(decision["to"]))
	frappe.clear_cache()
	return {
		"changed": True,
		"from": decision["from"],
		"to": decision["to"],
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

	# Child tables too. Comparing only the parent row missed changes that live entirely
	# in a child table — a UOM conversion factor or a barcode — so an item whose purchase
	# unit changed in Intacct would be read, compared, judged unchanged, and never saved.
	for table_field in doc.meta.get_table_fields():
		rows = doc.get(table_field.fieldname) or []
		stored_rows = frappe.get_all(
			table_field.options,
			filters={"parent": doc.name, "parentfield": table_field.fieldname},
			fields=["*"],
			limit_page_length=0,
		)
		if len(rows) != len(stored_rows):
			return True

		compare_fields = [
			f.fieldname
			for f in frappe.get_meta(table_field.options).fields
			if f.fieldtype not in frappe.model.no_value_fields
		]
		def as_key(row, fields=compare_fields):
			return tuple(str(row.get(f) or "") for f in fields)

		if sorted(as_key(r) for r in rows) != sorted(as_key(r) for r in stored_rows):
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
