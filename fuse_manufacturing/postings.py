"""Postings out — ERPNext movements into Intacct.

The contract, from the handoff: Intacct posts FIRST. If Intacct rejects it, the ERPNext
transaction does not stand. There is no local-only outcome, and ERPNext never invents a
value.

Nothing here is wired to a document hook yet. Each posting is a plain function taking
explicit arguments, so the desk form, a scheduled job and the mobile scanner all call the
same code — and so it can be run once, deliberately, and checked in Intacct.
"""

import xml.etree.ElementTree as ET

import frappe

from fuse_manufacturing import gateway, rules

# Intacct's transfer types. "Immediate" lands the stock in the destination on posting,
# which is what a store-to-store move is. "In transit" parks it until received.
IMMEDIATE = "Immediate"

# Valid ACTION depends on TRANSFERTYPE: Immediate → Draft|Post. Sending "Submit" fails
# with BL03002129 — proven on the donor.
POST = "Post"


def _text(parent, tag, value):
	ET.SubElement(parent, tag).text = str(value)


def build_transfer_xml(*, transaction_date, reference_no, description, legs, location_id,
                       transfer_type=IMMEDIATE, action=POST):
	"""The <create><ICTRANSFER> function element for a warehouse transfer.

	Separated from the posting so the exact XML can be inspected without sending it.
	"""
	function = ET.Element("function")
	create = ET.SubElement(function, "create")
	transfer = ET.SubElement(create, "ICTRANSFER")

	_text(transfer, "TRANSACTIONDATE", transaction_date)
	if reference_no:
		_text(transfer, "REFERENCENO", reference_no)
	if description:
		_text(transfer, "DESCRIPTION", description)
	_text(transfer, "TRANSFERTYPE", transfer_type)
	_text(transfer, "ACTION", action)

	items = ET.SubElement(transfer, "ICTRANSFERITEMS")
	for leg in legs:
		item = ET.SubElement(items, "ICTRANSFERITEM")
		# IN_OUT is "O"/"I", NOT "Out"/"In". An unrecognised value is rejected as
		# "The required field 'From Location' is missing", which points nowhere useful.
		_text(item, "IN_OUT", leg["in_out"])
		_text(item, "ITEMID", leg["item_id"])
		_text(item, "WAREHOUSEID", leg["warehouse_id"])
		_text(item, "QUANTITY", leg["quantity"])
		_text(item, "UNIT", leg["unit"])
		# LOCATIONID is required on EVERY line, not just the header.
		_text(item, "LOCATIONID", location_id)

	return function


# Manufacturing definitions, named exactly as Intacct holds them.
#
# The donor's code says the two reversal definitions are convert-only. In leadertread-imp
# both are active with CREATETYPE "New document or Convert", i.e. postable directly —
# checked against INVDOCUMENTPARAMS, not assumed. Definitions are per-company
# configuration, so the `definitions` job re-checks them on every client.
#
# Note the asymmetry in UPDATES_COST. It is the whole reason a reversal is not the forward
# document negated: the cost sits on the increase leg either way, so it moves from the
# finished goods to the components when the direction flips.
MANUFACTURING_PRODUCE = "Manufacturing Run Increase"      # Increase, UPDATES_COST=true
MANUFACTURING_CONSUME = "Manufacturing Backflush Decr"    # Decrease, UPDATES_COST=false
MANUFACTURING_UNPRODUCE = "Manufacturing Run Decrease"    # Decrease, UPDATES_COST=false
MANUFACTURING_UNCONSUME = "Manufacturing Backflush Incr"  # Increase, UPDATES_COST=true


def build_ictransaction_xml(*, definition, posting_date, reference_no, lines, location_id):
	"""A <create_ictransaction> function element.

	One definition per document — which is why a production run is two of these, not one.
	"""
	function = ET.Element("function")
	transaction = ET.SubElement(function, "create_ictransaction")

	# The definition name goes in transactiontype. This is what selects the behaviour:
	# same engine, different direction and costing.
	_text(transaction, "transactiontype", definition)

	date = ET.SubElement(transaction, "datecreated")
	_text(date, "year", posting_date.year)
	_text(date, "month", posting_date.month)
	_text(date, "day", posting_date.day)

	if reference_no:
		_text(transaction, "referenceno", reference_no)

	items = ET.SubElement(transaction, "ictransitems")
	for line in lines:
		item = ET.SubElement(items, "ictransitem")
		_text(item, "itemid", line["item_id"])
		_text(item, "warehouseid", line["warehouse_id"])
		# POSITIVE always — the definition applies its own sign.
		_text(item, "quantity", line["quantity"])
		_text(item, "unit", line["unit"])
		# Cost only where the definition values the movement. Sending one on a consume
		# leg would override Intacct's own valuation of the components.
		if line.get("cost") is not None:
			_text(item, "cost", line["cost"])
		_text(item, "locationid", location_id)

		# Bin, lot and serial detail only when the item carries it. A bin-enabled item
		# is rejected without a bin.
		if line.get("bin") or line.get("lot") or line.get("serial"):
			details = ET.SubElement(item, "itemdetails")
			detail = ET.SubElement(details, "itemdetail")
			_text(detail, "quantity", line["quantity"])
			if line.get("bin"):
				_text(detail, "bin", line["bin"])
			if line.get("lot"):
				_text(detail, "lotno", line["lot"])
			if line.get("serial"):
				_text(detail, "serialno", line["serial"])

	return function


def _intacct_warehouse(warehouse):
	code = frappe.db.get_value("Warehouse", warehouse, "custom_intacct_warehouse_id")
	if not code:
		frappe.throw(
			f"Warehouse {warehouse} has no Intacct Warehouse ID. It is not a warehouse "
			"Intacct knows about, so a movement through it cannot be posted."
		)
	return code


@frappe.whitelist()
def post_stock_entry_transfer(stock_entry, dry_run=False):
	"""Post an ERPNext Material Transfer to Intacct as one ICTRANSFER.

	`dry_run=True` returns the exact XML that WOULD be sent, without sending it. Use it
	to check a posting before it touches a real company.
	"""
	doc = frappe.get_doc("Stock Entry", stock_entry)

	# A dry run works on a DRAFT on purpose: the point is to read the XML before the
	# document is committed. Requiring a submitted document forced the entry to be
	# submitted first, which inverts the Intacct-posts-first contract.
	if not dry_run and doc.docstatus != 1:
		frappe.throw(f"{stock_entry} is not submitted (docstatus {doc.docstatus}).")
	if doc.purpose != "Material Transfer":
		frappe.throw(f"{stock_entry} is a {doc.purpose}, not a Material Transfer.")

	entity = gateway.entity_for_company(doc.company)

	lines = []
	for row in doc.items:
		lines.append(
			{
				"item_code": row.item_code,
				"qty": row.qty,
				# The unit must match the item's UOM character for character or the line
				# is rejected with BL03000018 "Missing unit". Taken from the Item, never
				# from the transaction header — the header carries ERPNext's own default.
				"uom": frappe.db.get_value("Item", row.item_code, "stock_uom"),
				"from_warehouse": _intacct_warehouse(row.s_warehouse),
				"to_warehouse": _intacct_warehouse(row.t_warehouse),
			}
		)

	legs = rules.transfer_legs(lines)

	function = build_transfer_xml(
		transaction_date=doc.posting_date.strftime("%m/%d/%Y"),
		reference_no=doc.name,
		# "Fuse" is what the client sees on the Intacct document — the product name, not the
		# platform it happens to run on.
		description=f"Fuse {doc.name}",
		legs=legs,
		location_id=entity,
	)

	if dry_run:
		return {
			"dry_run": True,
			"entity": entity,
			"legs": legs,
			"xml": ET.tostring(function, encoding="unicode"),
		}

	keys = gateway.execute_many(
		[function],
		company=doc.company,
		reference=("Stock Entry", doc.name),
		purpose="transfer",
	)
	return {"posted": True, "intacct_key": keys[0], "legs": len(legs)}


@frappe.whitelist()
def post_stock_entry_manufacture(stock_entry, dry_run=False):
	"""Post an ERPNext Manufacture entry to Intacct as consume + produce.

	TWO documents in ONE atomic operation. They are separate transaction definitions so
	they cannot share a document, but they must not be able to half-post either: stock
	consumed with nothing produced is the put-away hole in a different costume.
	"""
	doc = frappe.get_doc("Stock Entry", stock_entry)

	# As above: a dry run reads a draft, so the XML can be checked before committing.
	if not dry_run and doc.docstatus != 1:
		frappe.throw(f"{stock_entry} is not submitted (docstatus {doc.docstatus}).")
	if doc.purpose != "Manufacture":
		frappe.throw(f"{stock_entry} is a {doc.purpose}, not a Manufacture.")

	entity = gateway.entity_for_company(doc.company)
	consumed, produced = _manufacture_rows(doc)

	legs = rules.manufacture_legs(
		consumed=consumed,
		produced_item=produced["item_code"],
		produced_qty=produced["qty"],
		produced_uom=produced["uom"],
		warehouse=_intacct_warehouse(produced["warehouse"]),
	)
	legs["produce"][0]["bin"] = _default_bin(produced["warehouse"], produced["item_code"])

	consume_fn = build_ictransaction_xml(
		definition=MANUFACTURING_CONSUME,
		posting_date=doc.posting_date,
		reference_no=doc.name,
		lines=legs["consume"],
		location_id=entity,
	)
	produce_fn = build_ictransaction_xml(
		definition=MANUFACTURING_PRODUCE,
		posting_date=doc.posting_date,
		reference_no=doc.name,
		lines=legs["produce"],
		location_id=entity,
	)

	if dry_run:
		return {
			"dry_run": True,
			"entity": entity,
			"unit_cost": legs["produce"][0]["cost"],
			"consume_xml": ET.tostring(consume_fn, encoding="unicode"),
			"produce_xml": ET.tostring(produce_fn, encoding="unicode"),
		}

	keys = gateway.execute_many(
		[consume_fn, produce_fn],
		company=doc.company,
		reference=("Stock Entry", doc.name),
		purpose="manufacture",
		atomic=True,
	)
	return {"posted": True, "intacct_keys": keys, "unit_cost": legs["produce"][0]["cost"]}


def _manufacture_rows(doc):
	"""The consumed and produced rows of a Manufacture entry, as the postings want them.

	Shared by the forward post and its reversal on purpose: the reversal has to return the
	components at the rate they left at, so reading them any other way is a chance for the
	two to disagree.
	"""
	consumed = []
	produced = None
	for row in doc.items:
		# The unit must match the item's UOM character for character or the line is
		# rejected with BL03000018. Taken from the Item, never from the header.
		unit = frappe.db.get_value("Item", row.item_code, "stock_uom")
		if row.is_finished_item:
			produced = {"item_code": row.item_code, "qty": row.qty, "uom": unit, "warehouse": row.t_warehouse}
			continue
		if not row.s_warehouse:
			continue
		consumed.append(
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"uom": unit,
				"warehouse": _intacct_warehouse(row.s_warehouse),
				# The rate ERPNext holds came from Intacct's opening cost, so deriving
				# the produced cost from it is Intacct's own money, not a local invention.
				"rate": row.valuation_rate or row.basic_rate or 0,
				"bin": _default_bin(row.s_warehouse, row.item_code),
			}
		)

	if not produced:
		frappe.throw(f"{doc.name} has no finished item — nothing was produced.")
	return consumed, produced


@frappe.whitelist()
def reverse_stock_entry_transfer(stock_entry, dry_run=False):
	"""Undo a posted warehouse transfer by posting the same move back the other way.

	A transfer is one document carrying both halves, so its reversal is simply the same
	document with the warehouses swapped. Value follows the quantity — nothing to restate.
	"""
	doc = frappe.get_doc("Stock Entry", stock_entry)
	if doc.purpose != "Material Transfer":
		frappe.throw(f"{stock_entry} is a {doc.purpose}, not a Material Transfer.")

	entity = gateway.entity_for_company(doc.company)

	# Swapped at the source, so transfer_legs still applies every check it applies going
	# forward — same warehouse both ends, missing unit, non-positive quantity.
	lines = [
		{
			"item_code": row.item_code,
			"qty": row.qty,
			"uom": frappe.db.get_value("Item", row.item_code, "stock_uom"),
			"from_warehouse": _intacct_warehouse(row.t_warehouse),
			"to_warehouse": _intacct_warehouse(row.s_warehouse),
		}
		for row in doc.items
	]
	legs = rules.transfer_legs(lines)

	function = build_transfer_xml(
		# The ORIGINAL date, so the pair nets to zero in the period it happened in. If that
		# period is closed Intacct rejects it — which is the right answer, not something to
		# route around by quietly dating the reversal today.
		transaction_date=doc.posting_date.strftime("%m/%d/%Y"),
		reference_no=doc.name,
		description=f"Reversal of Fuse {doc.name}",
		legs=legs,
		location_id=entity,
	)

	if dry_run:
		return {
			"dry_run": True,
			"reversal": True,
			"entity": entity,
			"legs": legs,
			"xml": ET.tostring(function, encoding="unicode"),
		}

	keys = gateway.execute_many(
		[function],
		company=doc.company,
		reference=("Stock Entry", doc.name),
		# A different purpose from the forward post, so the control ID differs and Intacct
		# does not mistake the reversal for a replay of the original.
		purpose="transfer-reverse",
	)
	return {"reversed": True, "intacct_keys": keys, "legs": len(legs)}


@frappe.whitelist()
def reverse_stock_entry_manufacture(stock_entry, dry_run=False):
	"""Undo a posted production run: finished goods back out, components back in.

	Two documents again, atomically, and again they are NOT the forward pair negated —
	see rules.manufacture_reversal_legs for why the cost changes sides.
	"""
	doc = frappe.get_doc("Stock Entry", stock_entry)
	if doc.purpose != "Manufacture":
		frappe.throw(f"{stock_entry} is a {doc.purpose}, not a Manufacture.")

	entity = gateway.entity_for_company(doc.company)
	consumed, produced = _manufacture_rows(doc)

	legs = rules.manufacture_reversal_legs(
		consumed=consumed,
		produced_item=produced["item_code"],
		produced_qty=produced["qty"],
		produced_uom=produced["uom"],
		warehouse=_intacct_warehouse(produced["warehouse"]),
	)
	legs["unproduce"][0]["bin"] = _default_bin(produced["warehouse"], produced["item_code"])

	unproduce_fn = build_ictransaction_xml(
		definition=MANUFACTURING_UNPRODUCE,
		posting_date=doc.posting_date,
		reference_no=doc.name,
		lines=legs["unproduce"],
		location_id=entity,
	)
	unconsume_fn = build_ictransaction_xml(
		definition=MANUFACTURING_UNCONSUME,
		posting_date=doc.posting_date,
		reference_no=doc.name,
		lines=legs["unconsume"],
		location_id=entity,
	)

	if dry_run:
		return {
			"dry_run": True,
			"reversal": True,
			"entity": entity,
			"unproduce_xml": ET.tostring(unproduce_fn, encoding="unicode"),
			"unconsume_xml": ET.tostring(unconsume_fn, encoding="unicode"),
		}

	# Finished goods out BEFORE components back in, mirroring the forward order. Atomic, so
	# it cannot half-undo and leave the components duplicated.
	keys = gateway.execute_many(
		[unproduce_fn, unconsume_fn],
		company=doc.company,
		reference=("Stock Entry", doc.name),
		purpose="manufacture-reverse",
		atomic=True,
	)
	return {"reversed": True, "intacct_keys": keys}


# ──────────────────────────────────────────────────────────────────────────────
# Document hooks
# ──────────────────────────────────────────────────────────────────────────────

# Which Stock Entry purposes post, and how.
POSTED_PURPOSES = {
	"Manufacture": post_stock_entry_manufacture,
	"Material Transfer": post_stock_entry_transfer,
}

# And how each one is undone. Keyed the same way, so a purpose that can be posted but not
# reversed is visible as a gap here rather than discovered at a cancel.
REVERSED_PURPOSES = {
	"Manufacture": reverse_stock_entry_manufacture,
	"Material Transfer": reverse_stock_entry_transfer,
}


def on_stock_entry_submit(doc, method=None):
	"""Post the movement to Intacct as part of submitting it.

	INTACCT POSTS FIRST. This runs inside ERPNext's submit transaction, so if Intacct
	rejects the movement this raises, the submit rolls back, and the ERPNext document
	does not stand. That is the contract — there is no local-only outcome.

	The reverse ambiguity is real and handled by the control ID: if Intacct commits and
	something later in the submit fails, ERPNext rolls back while Intacct keeps the
	posting. Re-submitting carries the same deterministic control ID, so Intacct rejects
	the replay rather than posting it twice.
	"""
	handler = POSTED_PURPOSES.get(doc.purpose)
	if not handler:
		return

	settings = frappe.get_cached_doc("Intacct Settings")
	if not settings.post_movements:
		# Deliberately off. A site can be installed and syncing masters long before it
		# is ready to post — but this must be a decision someone made, not a silent
		# default, or stock moves locally with Intacct none the wiser.
		return

	result = handler(doc.name)

	# A production run is TWO Intacct documents and both keys matter — keeping only the
	# first left the produce leg traceable in the request log and nowhere else. Joined,
	# because anyone reconciling needs to find either document from the Stock Entry.
	keys = result.get("intacct_keys") or [result.get("intacct_key")]
	doc.db_set("custom_intacct_key", ", ".join(str(key) for key in keys if key))
	doc.db_set("custom_intacct_posted_on", frappe.utils.now_datetime())


def on_stock_entry_cancel(doc, method=None):
	"""Reverse the movement in Intacct as part of cancelling it.

	INTACCT REVERSES FIRST, for the same reason it posts first: if Intacct will not accept
	the reversal — a closed period, a warehouse since deactivated — the ERPNext cancel must
	not stand either, or the two systems end up disagreeing about stock that physically
	moved.

	The reversal is a NEW pair of documents, not a deletion. Intacct keeps the original and
	the undo, which is what an audit trail is for.
	"""
	handler = REVERSED_PURPOSES.get(doc.purpose)
	if not handler:
		return
	if not doc.get("custom_intacct_key"):
		# Never posted — nothing in Intacct to undo. Cancel freely.
		return

	if doc.get("custom_intacct_reversal_key"):
		frappe.throw(
			f"{doc.name} has already been reversed in Intacct "
			f"(key {doc.custom_intacct_reversal_key}). Reversing it twice would put the "
			"stock back a second time."
		)

	settings = frappe.get_cached_doc("Intacct Settings")
	if not settings.post_movements:
		# Posting is off but this document carries an Intacct key, so it was posted while
		# it was on. Cancelling now would strand that posting with nothing to undo it.
		frappe.throw(
			f"{doc.name} was posted to Intacct (key {doc.custom_intacct_key}) but posting "
			"is now switched off, so it cannot be reversed. Turn Post Stock Movements back "
			"on to cancel this, or reverse it in Intacct by hand."
		)

	result = handler(doc.name)

	doc.db_set("custom_intacct_reversal_key", ", ".join(str(key) for key in result.get("intacct_keys") or [] if key))
	doc.db_set("custom_intacct_reversed_on", frappe.utils.now_datetime())


def _default_bin(warehouse, item_code):
	"""The warehouse's default bin, but only for items Intacct tracks bins on.

	A bin-enabled item is rejected without one; a non-bin item is rejected WITH one.
	"""
	if not warehouse or not frappe.db.get_value("Item", item_code, "custom_intacct_bin_tracked"):
		return None
	return frappe.db.get_value("Warehouse", warehouse, "custom_intacct_default_bin")
