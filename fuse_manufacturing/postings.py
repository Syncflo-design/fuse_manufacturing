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
from frappe.utils import flt

from fuse_manufacturing import gateway, rules

# Intacct's transfer types. "Immediate" lands the stock in the destination on posting,
# which is what a store-to-store move is. "In transit" parks it until received.
IMMEDIATE = "Immediate"

# Both of ERPNext's transfer-shaped purposes. They differ only in intent — one stages
# components into a WIP warehouse ahead of a production run, the other is an ordinary move
# — and Intacct does not care about the intent: stock left one warehouse and arrived at
# another. Leaving the WIP one out meant it moved stock in ERPNext and posted nothing.
TRANSFER_PURPOSES = ("Material Transfer", "Material Transfer for Manufacture")

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

# Stock adjustments are NOT posted from Fuse.
#
# Authorised 2026-08-12: general stock adjustment is removed, and correcting on-hand
# quantities happens through Intacct's Cycle Count instead. The cycle count itself is
# raised in Intacct; Fuse's part will be running the counting process, and that is a
# separate piece of work.
#
# Because nothing here posts an adjustment, nothing here may make one either — a Material
# Receipt or Issue in ERPNext would move stock Intacct never sees. Both are blocked below,
# on the same reasoning as goods receipting.


def build_ictransaction_xml(*, definition, posting_date, reference_no, lines, location_id,
                            document_no=None):
	"""A <create_ictransaction> function element.

	One definition per document — which is why a production run is two of these, not one.

	`document_no` is only supplied for definitions Intacct will not number itself. Element
	order matters here: this is a legacy DTD-validated function, so documentno belongs
	between datecreated and referenceno, not wherever is convenient.
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

	if document_no:
		_text(transaction, "documentno", document_no)

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
	if doc.purpose not in TRANSFER_PURPOSES:
		frappe.throw(f"{stock_entry} is a {doc.purpose}, not a transfer.")

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
	split = rules.classify_manufacture_rows(
		[
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"is_finished_item": row.is_finished_item,
				"s_warehouse": row.s_warehouse,
				"t_warehouse": row.t_warehouse,
				"rate": row.valuation_rate or row.basic_rate or 0,
			}
			for row in doc.items
		]
	)
	if split["problems"]:
		# Refused, not worked around. Every one of these used to be a silently dropped row.
		frappe.throw(f"{doc.name} cannot be posted to Intacct:\n\n" + "\n\n".join(split["problems"]))

	# The unit must match the item's UOM character for character or the line is rejected
	# with BL03000018. Taken from the Item, never from the header — the header carries
	# ERPNext's own default, which is routinely "Nos" on an item measured in kilograms.
	def unit_for(item_code):
		return frappe.db.get_value("Item", item_code, "stock_uom")

	produced = dict(split["produced"])
	produced["uom"] = unit_for(produced["item_code"])
	produced["warehouse"] = produced["t_warehouse"]

	consumed = [
		{
			"item_code": row["item_code"],
			"qty": row["qty"],
			"uom": unit_for(row["item_code"]),
			"warehouse": _intacct_warehouse(row["s_warehouse"]),
			# The rate ERPNext holds came from Intacct's opening cost, so deriving the
			# produced cost from it is Intacct's own money, not a local invention.
			"rate": row["rate"],
			"bin": _default_bin(row["s_warehouse"], row["item_code"]),
		}
		for row in split["consumed"]
	]
	return consumed, produced


@frappe.whitelist()
def reverse_stock_entry_transfer(stock_entry, dry_run=False):
	"""Undo a posted warehouse transfer by posting the same move back the other way.

	A transfer is one document carrying both halves, so its reversal is simply the same
	document with the warehouses swapped. Value follows the quantity — nothing to restate.
	"""
	doc = frappe.get_doc("Stock Entry", stock_entry)
	if doc.purpose not in TRANSFER_PURPOSES:
		frappe.throw(f"{stock_entry} is a {doc.purpose}, not a transfer.")

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

	# Neither reversal definition has a numbering scheme attached in leadertread-imp, so
	# Intacct rejects them with PL01000127 unless Fuse supplies the number. Deterministic,
	# so a retry reuses it rather than creating a second document. If a client's Intacct
	# admin ever attaches a scheme, these can simply stop being sent — the "FR-" prefix
	# cannot collide with anything Intacct issues in the meantime.
	unproduce_fn = build_ictransaction_xml(
		definition=MANUFACTURING_UNPRODUCE,
		posting_date=doc.posting_date,
		reference_no=doc.name,
		document_no=rules.document_number_for("Stock Entry", doc.name, "manufacture-reverse", 1),
		lines=legs["unproduce"],
		location_id=entity,
	)
	unconsume_fn = build_ictransaction_xml(
		definition=MANUFACTURING_UNCONSUME,
		posting_date=doc.posting_date,
		reference_no=doc.name,
		document_no=rules.document_number_for("Stock Entry", doc.name, "manufacture-reverse", 2),
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
	**{purpose: post_stock_entry_transfer for purpose in TRANSFER_PURPOSES},
}

# And how each one is undone. Keyed the same way, so a purpose that can be posted but not
# reversed is visible as a gap here rather than discovered at a cancel.
REVERSED_PURPOSES = {
	"Manufacture": reverse_stock_entry_manufacture,
	**{purpose: reverse_stock_entry_transfer for purpose in TRANSFER_PURPOSES},
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


# ──────────────────────────────────────────────────────────────────────────────
# Goods receipt — blocked
# ──────────────────────────────────────────────────────────────────────────────

_RECEIPT_REFUSAL = (
	"Goods are received in Intacct, not in Fuse.\n\n"
	"Purchase orders are mirrored here read-only so that stock on order shows in "
	"projections and demand reporting. Receipting them here would add stock Intacct never "
	"saw, and receipting the same delivery in Intacct would then count it twice."
)


def block_goods_receipt(doc, method=None):
	"""Refuse any document that receives purchased goods into ERPNext.

	A blanket block, not a check against mirrored orders only. A submitted Purchase Order
	offers "Create → Purchase Receipt" one click away, and nothing about that button warns
	that receiving belongs to Intacct.

	If receipting ever moves to ERPNext — the handover model allows for it — this comes out
	deliberately, together with the posting that would send the receipt to Intacct. A hole
	left open now would be found by a user, not by us.
	"""
	frappe.throw(_RECEIPT_REFUSAL, title="Receipting happens in Intacct")


_ADJUSTMENT_REFUSAL = (
	"On-hand quantities are corrected in Intacct, not in Fuse.\n\n"
	"Use a Cycle Count in Intacct. Adjusting stock here would move it with Intacct none "
	"the wiser, and the two would disagree from that moment on."
)

# ERPNext purposes that change on-hand quantity without moving it anywhere.
ADJUSTMENT_PURPOSES = ("Material Receipt", "Material Issue")


def block_stock_adjustment(doc, method=None):
	"""Refuse a Stock Entry that adjusts quantity rather than moving it.

	Fuse posts transfers and production. It does NOT post general adjustments — that was
	removed on 2026-08-12 in favour of Intacct's Cycle Count. Since nothing here posts one,
	nothing here may make one: a Material Issue would take stock out of ERPNext that Intacct
	still believes it has.

	Transfers and production runs are untouched — they move stock and they post.
	"""
	if doc.purpose in ADJUSTMENT_PURPOSES:
		frappe.throw(_ADJUSTMENT_REFUSAL, title="Adjustments happen in Intacct")


def block_stock_updating_invoice(doc, method=None):
	"""The same block by the other door.

	A Purchase Invoice with "Update Stock" ticked receives goods without a Purchase
	Receipt ever existing — the same divergence, reached by a checkbox rather than a
	button. The invoice itself is not blocked, only its ability to move stock.
	"""
	if doc.get("update_stock"):
		frappe.throw(_RECEIPT_REFUSAL, title="Receipting happens in Intacct")


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


# ──────────────────────────────────────────────────────────────────────────────
# Goods receipt — a PO Receiver, converted from the purchase order
# ──────────────────────────────────────────────────────────────────────────────

# Intacct's receiving definition. A receipt is not a fresh document: it CONVERTS the
# purchase order, which is what moves that order to Partially Converted / Converted —
# the states the order sync reads to decide what is still outstanding.
PO_RECEIVER = "PO Receiver-Inventory"


def build_potransaction_xml(*, definition, posting_date, created_from, vendor_id, lines,
                            location_id, reference_no=None, vendor_doc_no=None,
                            document_no=None):
	"""A <create_potransaction> function element for a goods receipt.

	Element order follows Intacct's own documented sequence. This is a legacy
	DTD-validated function, so order is not cosmetic — a correct element in the wrong
	place is rejected as a missing one.

	`created_from` is the source order's full document id ("Purchase Order-Inventory-PO0051")
	and each line carries `sourcelinekey`, the ordered line's RECORDNO. The header link
	alone is not enough: without the line key Intacct cannot tell which ordered line was
	delivered, and the same item can legitimately appear on an order twice.
	"""
	function = ET.Element("function")
	transaction = ET.SubElement(function, "create_potransaction")

	_text(transaction, "transactiontype", definition)

	date = ET.SubElement(transaction, "datecreated")
	_text(date, "year", posting_date.year)
	_text(date, "month", posting_date.month)
	_text(date, "day", posting_date.day)

	_text(transaction, "createdfrom", created_from)
	_text(transaction, "vendorid", vendor_id)

	if document_no:
		_text(transaction, "documentno", document_no)
	if reference_no:
		_text(transaction, "referenceno", reference_no)
	# The supplier's own delivery note or invoice number. That is the number the people in
	# the warehouse and the people in accounts both quote, so it is worth carrying.
	if vendor_doc_no:
		_text(transaction, "vendordocno", vendor_doc_no)

	items = ET.SubElement(transaction, "potransitems")
	for line in lines:
		item = ET.SubElement(items, "potransitem")
		_text(item, "itemid", line["item_id"])
		_text(item, "warehouseid", line["warehouse_id"])
		_text(item, "quantity", line["quantity"])
		_text(item, "unit", line["unit"])
		_text(item, "sourcelinekey", line["source_line_key"])
		_text(item, "locationid", location_id)

		if line.get("bin") or line.get("lot"):
			details = ET.SubElement(item, "itemdetails")
			detail = ET.SubElement(details, "itemdetail")
			_text(detail, "quantity", line["quantity"])
			if line.get("lot"):
				_text(detail, "lotno", line["lot"])
			if line.get("bin"):
				_text(detail, "bin", line["bin"])

	return function


def _receipt_lines(doc):
	"""The receiver lines for a Purchase Receipt: accepted and rejected, separately.

	Rejected stock was still delivered and will still be invoiced, so it belongs on the
	receiver — it just lands somewhere else. Two lines against the same ordered line is
	how the donor did it, and it is the only way to say "18 good, 2 damaged" without
	losing one of the numbers.
	"""
	lines = []
	for row in doc.items:
		if not row.purchase_order_item:
			frappe.throw(
				f"Row {row.idx} ({row.item_code}) is not linked to a purchase order line. "
				"A receipt converts an ordered line, so a free-standing row has nothing to "
				"convert against."
			)

		source_line_key = frappe.db.get_value(
			"Purchase Order Item", row.purchase_order_item, "custom_intacct_line_recordno"
		)
		if not source_line_key:
			frappe.throw(
				f"Row {row.idx} ({row.item_code}): the ordered line carries no Intacct line "
				"key. Re-run the purchase order sync so the mirror picks it up, then receive "
				"again."
			)

		unit = frappe.db.get_value("Item", row.item_code, "stock_uom")
		lot = row.get("custom_intacct_lot") or None

		if flt(row.qty) > 0:
			lines.append(
				{
					"item_id": row.item_code,
					"warehouse_id": _intacct_warehouse(row.warehouse),
					"quantity": flt(row.qty),
					"unit": unit,
					"source_line_key": source_line_key,
					"bin": _default_bin(row.warehouse, row.item_code),
					"lot": lot,
				}
			)

		if flt(row.get("rejected_qty")) > 0:
			if not row.rejected_warehouse:
				frappe.throw(
					f"Row {row.idx} ({row.item_code}) has a rejected quantity but no reject "
					"warehouse. Set one on Intacct Settings."
				)
			lines.append(
				{
					"item_id": row.item_code,
					"warehouse_id": _intacct_warehouse(row.rejected_warehouse),
					"quantity": flt(row.rejected_qty),
					"unit": unit,
					"source_line_key": source_line_key,
					"bin": _default_bin(row.rejected_warehouse, row.item_code),
					"lot": lot,
				}
			)

	if not lines:
		# Intacct rejects an empty receiver with "potransitems: Missing child element",
		# which reads as a malformed request rather than as an empty one.
		frappe.throw("Nothing on this receipt has a quantity, so there is nothing to receive.")

	return lines


@frappe.whitelist()
def post_purchase_receipt(purchase_receipt, dry_run=False):
	"""Post an ERPNext Purchase Receipt to Intacct as a PO Receiver.

	`dry_run=True` returns the XML that WOULD be sent, without sending it, and works on a
	draft — the point is to read the envelope before the document is committed.
	"""
	doc = frappe.get_doc("Purchase Receipt", purchase_receipt)

	if not dry_run and doc.docstatus != 1:
		frappe.throw(f"{purchase_receipt} is not submitted (docstatus {doc.docstatus}).")

	# ERPNext is happy to receive several purchase orders on one receipt. Intacct is not:
	# `createdfrom` names a single source document. Refused rather than quietly split into
	# several receivers, because then one of them failing leaves a receipt half posted.
	orders = {row.purchase_order for row in doc.items if row.purchase_order}
	if len(orders) > 1:
		frappe.throw(
			"This receipt covers more than one purchase order: "
			+ ", ".join(sorted(orders))
			+ ". Intacct receives one order at a time — record a separate receipt for each."
		)
	if not orders:
		frappe.throw("This receipt is not linked to a purchase order, so there is nothing to convert.")

	order = orders.pop()
	created_from = frappe.db.get_value("Purchase Order", order, "custom_intacct_po_id")
	if not created_from:
		frappe.throw(
			f"{order} is not a mirrored Intacct order. Only orders that came from Intacct can "
			"be received, because the receipt converts the Intacct document."
		)

	vendor_id = frappe.db.get_value("Supplier", doc.supplier, "custom_intacct_vendor_id")
	if not vendor_id:
		frappe.throw(f"Supplier {doc.supplier} has no Intacct vendor ID — run the suppliers sync.")

	entity = gateway.entity_for_company(doc.company)
	lines = _receipt_lines(doc)

	function = build_potransaction_xml(
		definition=PO_RECEIVER,
		posting_date=doc.posting_date,
		created_from=created_from,
		vendor_id=vendor_id,
		lines=lines,
		location_id=entity,
		reference_no=doc.name,
		vendor_doc_no=doc.get("supplier_delivery_note") or None,
	)

	if dry_run:
		return {
			"dry_run": True,
			"entity": entity,
			"created_from": created_from,
			"lines": lines,
			"xml": ET.tostring(function, encoding="unicode"),
		}

	keys = gateway.execute_many(
		[function],
		company=doc.company,
		reference=("Purchase Receipt", doc.name),
		purpose="receipt",
	)
	return {"posted": True, "intacct_key": keys[0], "lines": len(lines)}


def on_purchase_receipt_submit(doc, method=None):
	"""Post the receipt to Intacct as part of submitting it.

	Same contract as every other movement: Intacct first, inside ERPNext's submit
	transaction, so a rejection rolls the receipt back and no stock lands here that
	Intacct has not accepted.
	"""
	settings = frappe.get_cached_doc("Intacct Settings")
	if not settings.post_movements:
		# Deliberately off — a site syncs masters long before it is ready to post.
		return

	result = post_purchase_receipt(doc.name)
	doc.db_set("custom_intacct_key", result.get("intacct_key"))
	doc.db_set("custom_intacct_posted_on", frappe.utils.now_datetime())


def on_purchase_receipt_cancel(doc, method=None):
	"""Refuse to cancel a receipt that has already posted.

	Undoing a PO Receiver means a reverse conversion in Intacct, and how this company's
	definitions handle one has not been established. Refusing is the honest answer while
	that is unknown: a local cancel would take stock out of ERPNext that Intacct still
	believes was delivered, and nobody would find out until a count.
	"""
	if not doc.get("custom_intacct_key"):
		return
	frappe.throw(
		f"{doc.name} was received into Intacct (key {doc.custom_intacct_key}) and cannot be "
		"cancelled here. Reverse the receiver in Intacct first — Fuse does not yet post a "
		"reverse conversion."
	)


def block_inactive_module(doc, method=None):
	"""Refuse a movement whose module the client has switched off.

	Permissions cannot do this one. All three movement modules raise the same document —
	a Stock Entry — and a role either may raise them or may not; the purpose is what
	tells them apart, and that is only knowable per document.

	Deliberately a refusal with a reason rather than a silent no-op. Someone who reached
	this form from a bookmark, the awesome bar or a report link has done nothing wrong,
	and "Item Transfer is switched off for this site" tells them who to ask.
	"""
	from fuse_manufacturing import modules

	key = modules.purpose_module(doc.purpose)
	if not key:
		return
	if modules.is_active(key):
		return

	label = modules.MODULES_BY_KEY.get(key, {}).get("label", key)
	frappe.throw(
		f"{label} is switched off for this site, so this movement cannot be recorded.\n\n"
		"An administrator can switch it back on under Active Modules in Intacct Settings.",
		title=f"{label} is switched off",
	)


def block_inactive_receiving(doc, method=None):
	"""The same refusal for a goods receipt.

	Receiving is withdrawn by permission as well, so most users never reach this. It
	still exists for the ones who hold another role that grants Purchase Receipt —
	Stock Manager, say — where the module switch would otherwise mean nothing.
	"""
	from fuse_manufacturing import modules

	if modules.is_active("receiving"):
		return
	frappe.throw(
		"Receiving is switched off for this site, so a delivery cannot be booked in.\n\n"
		"An administrator can switch it back on under Active Modules in Intacct Settings.",
		title="Receiving is switched off",
	)
