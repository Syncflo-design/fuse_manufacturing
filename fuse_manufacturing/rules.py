"""Decision logic, with no Frappe and no network.

Everything here is a pure function: given the inputs, the answer is fixed. That is the
point — it can be tested anywhere, in a second, without a site.

The rules that live here are the ones that have actually gone wrong: recipe signatures,
precision alignment, cost fallback, drift tolerance, unit conversions and kit build
order. Keeping them out of masters.py is what makes them testable at all.
"""

import hashlib

# Moved to fuse_core with the gateway, which is the only thing that depended on them.
# Re-exported here so the rest of this app still reads rules.intacct_date and the
# tests keep one import to reason about.
from fuse_core.rules import (  # noqa: F401
	control_id_for,
	intacct_date,
	rejection_errors,
	result_keys,
)

# Bump to force a full BOM rebuild when something OUTSIDE the recipe changes how a BOM is
# written. v2 = site float precision raised 3 → 4 to match Intacct's quantities.
SIGNATURE_VERSION = "v2"

# Valuation used when Intacct holds no cost at all. Never a plausible cost, obvious in any
# report, and the exact figure is the worklist.
NO_COST_SENTINEL = 0.01

# ERPNext's own default; going under it rounds quantities other parts of ERPNext keep.
MIN_FLOAT_PRECISION = 3
# Frappe's field allows up to 9.
MAX_FLOAT_PRECISION = 9


def recipe_signature(lines):
	"""Stable fingerprint of a recipe, for deciding whether anything actually changed.

	Hashed because a real compound recipe runs past a Data field's 140 characters. Order
	independent: Intacct may return the same recipe with its lines in a different order,
	and that is not a change.
	"""
	parts = sorted(
		f"{line['item_code']}:{float(line['qty']):.6f}:{line.get('uom') or ''}" for line in lines
	)
	return hashlib.sha1(f"{SIGNATURE_VERSION}|{'|'.join(parts)}".encode()).hexdigest()


def document_number_for(doctype, name, purpose, index=1):
	"""A document number for a definition Intacct will not number itself.

	Intacct rejects a document with no number (PL01000127) when its template has no
	numbering scheme attached. The forward manufacturing definitions have one; the two
	reversal definitions in leadertread-imp do not, and switching that on needs admin
	rights on the company. So Fuse supplies one.

	Deliberately NOT numeric and prefixed "FR-": Intacct's own sequences are numeric with a
	template prefix, so nothing we generate can ever collide with a number Intacct later
	issues — including if someone attaches a numbering scheme to these templates after the
	fact.

	Deterministic, so a retried reversal reuses the same number rather than creating a
	second document. `index` separates the legs of one reversal, which are two documents.

	Kept short — the human link back to ERPNext is the reference number, which carries the
	Stock Entry name in full.
	"""
	raw = f"{doctype}:{name}:{purpose}"
	return f"FR-{hashlib.sha1(raw.encode()).hexdigest()[:10]}-{int(index)}"


def decide_precision(seen_precisions, current):
	"""What to do about float precision, given what Intacct uses and what ERPNext is on.

	Only ever raises. Lowering would silently round every quantity already stored — a
	data change disguised as a setting change.
	"""
	values = []
	for value in seen_precisions or []:
		try:
			number = int(value)
		except (TypeError, ValueError):
			continue
		if number:
			values.append(number)

	if not values:
		return {"action": "none", "reason": "Intacct returned no INV_PRECISION values"}

	wanted = max(MIN_FLOAT_PRECISION, min(max(values), MAX_FLOAT_PRECISION))
	current = int(current or 0) or MIN_FLOAT_PRECISION

	if wanted == current:
		return {"action": "none", "precision": current}
	if wanted < current:
		return {"action": "warn", "precision": current, "intacct_precision": wanted}
	return {"action": "raise", "from": current, "to": wanted}


def choose_rate(average_cost, last_cost):
	"""Valuation for an opening stock line: average, then last, then the sentinel.

	Never returns zero. ERPNext refuses a stock line with no valuation rate, so a zero
	would drop the line and lose the quantity — the thing the factory actually needs.
	"""
	if average_cost:
		return float(average_cost), "AVERAGE_COST"
	if last_cost:
		return float(last_cost), "LAST_COST"
	return NO_COST_SENTINEL, "sentinel"


def is_drift(intacct_qty, erpnext_qty, precision):
	"""Whether two quantities genuinely disagree, or merely round differently.

	Intacct holds more decimals than ERPNext stores, so a raw float comparison reports
	drift on a clean import. A report that always cries wolf gets ignored.
	"""
	tolerance = 10.0**-int(precision or MIN_FLOAT_PRECISION)
	return abs(float(erpnext_qty) - float(intacct_qty)) > tolerance


def build_conversions(base_uom, purchase, sales, known_uoms):
	"""The UOM conversion table for an item, and any units missing from the site.

	`purchase`/`sales` are (unit, factor) pairs. The stock unit is always 1 and can never
	be overwritten by a purchase or sales factor.

	Returns (conversions, missing). Conversions is empty without a base unit: ERPNext
	requires the stock UOM present with factor 1, so a table without it fails validation.
	"""
	missing = set()
	if not base_uom:
		for unit, _factor in (purchase, sales):
			if unit and unit not in known_uoms:
				missing.add(unit)
		return {}, missing

	conversions = {base_uom: 1.0}
	for unit, factor in (purchase, sales):
		if not unit or not factor:
			continue
		if unit not in known_uoms:
			missing.add(unit)
			continue
		if unit != base_uom:
			conversions[unit] = float(factor)
	return conversions, missing


def is_stock_item(item_type):
	"""Whether ERPNext should hold stock for an Intacct item type.

	A Stockable Kit holds stock and MUST be a stock item — ERPNext cannot run a Work
	Order to produce a non-stock item, and that failure surfaces on the shop floor
	rather than at import.
	"""
	normalised = (item_type or "").strip().lower()
	return normalised == "inventory" or "stockable kit" in normalised


def transfer_legs(lines):
	"""Turn transfer lines into Intacct's two-leg form.

	Intacct models a transfer as ONE document carrying both halves: an "O" line leaving
	the source and an "I" line arriving at the destination. Sending only one side is an
	adjustment, not a transfer.

	Quantities are always POSITIVE — direction comes from IN_OUT, never from the sign.
	Send -10 and Intacct will take it literally.

	`lines` are dicts of item_code, qty, uom, from_warehouse, to_warehouse.
	Raises ValueError on anything Intacct would reject or, worse, silently accept wrongly.
	"""
	legs = []
	for line in lines:
		qty = float(line.get("qty") or 0)
		if qty <= 0:
			raise ValueError(f"{line.get('item_code')}: quantity must be positive, got {qty}")
		if not line.get("from_warehouse") or not line.get("to_warehouse"):
			raise ValueError(f"{line.get('item_code')}: both warehouses are required")
		if line["from_warehouse"] == line["to_warehouse"]:
			raise ValueError(f"{line.get('item_code')}: source and destination are the same warehouse")
		if not line.get("uom"):
			raise ValueError(f"{line.get('item_code')}: unit is required and must match the item's UOM exactly")

		for direction, warehouse in (("O", line["from_warehouse"]), ("I", line["to_warehouse"])):
			legs.append(
				{
					"in_out": direction,
					"item_id": line["item_code"],
					"warehouse_id": warehouse,
					"quantity": qty,
					"unit": line["uom"],
				}
			)
	return legs



def detailed_transfer_legs(lines):
	"""A warehouse transfer as TWO documents, for stock Intacct tracks in bins or lots.

	The plain ICTRANSFER used elsewhere is one document and cannot carry either: its line
	object has no bin and no lot field at all. So a tracked transfer is posted the way
	Intacct itself models one internally — an out document and an in document, against two
	transaction definitions:

	  transfer_out — stock leaves, NO cost. The definition does not value this leg, and a
	                 cost sent here would override Intacct's own costing of what left.
	  transfer_in  — stock arrives, WITH the unit cost it left at. The definition has
	                 UPDATES_COST=true, so whatever is sent becomes the arriving value.

	That cost is what keeps the move value-neutral. Omitting it does not mean "no change" —
	it means Intacct values the arrival itself, and the difference lands in the ledger as a
	revaluation nobody asked for. Hence a missing or zero cost is refused, not defaulted.

	`lines` are dicts of item_code, qty, uom, from_warehouse, to_warehouse, unit_cost, and
	optionally source_bin, target_bin, lot. Quantities are POSITIVE on both legs — each
	definition applies its own sign.
	"""
	out_legs = []
	in_legs = []

	for line in lines:
		item = line.get("item_code")
		qty = float(line.get("qty") or 0)
		if qty <= 0:
			raise ValueError(f"{item}: quantity must be positive, got {qty}")
		if not line.get("from_warehouse") or not line.get("to_warehouse"):
			raise ValueError(f"{item}: both warehouses are required")
		if line["from_warehouse"] == line["to_warehouse"]:
			raise ValueError(f"{item}: source and destination are the same warehouse")
		if not line.get("uom"):
			raise ValueError(f"{item}: unit is required and must match the item's UOM exactly")

		cost = float(line.get("unit_cost") or 0)
		if cost <= 0:
			raise ValueError(
				f"{item}: no unit cost for the stock leaving {line['from_warehouse']}. The "
				"arriving leg is valued at what is sent, so a zero would write the item's "
				"value down to nothing."
			)

		lot = (line.get("lot") or "").strip() or None

		out_legs.append(
			{
				"item_id": item,
				"warehouse_id": line["from_warehouse"],
				"quantity": qty,
				"unit": line["uom"],
				"bin": (line.get("source_bin") or "").strip() or None,
				"lot": lot,
			}
		)
		in_legs.append(
			{
				"item_id": item,
				"warehouse_id": line["to_warehouse"],
				"quantity": qty,
				"unit": line["uom"],
				"bin": (line.get("target_bin") or "").strip() or None,
				"lot": lot,
				"cost": cost,
			}
		)

	if not out_legs:
		raise ValueError("a transfer must move something")

	return {"out": out_legs, "in": in_legs}


def bin_transfer_legs(warehouse, source_bin, target_bin, lines):
	"""A move between two bins in ONE warehouse, as Intacct's two legs.

	The same out-and-in pair a warehouse transfer uses, with the warehouse identical on
	both sides and only the bin differing. Intacct is the only system that holds stock per
	bin, so this pair is the entire movement — there is no ERPNext side to keep in step.

	Both bins are required. A blank one here cannot fall back to the warehouse default the
	way a warehouse transfer's can: the default IS a bin, so falling back would produce a
	document that moves stock out of a bin and straight back into the same one.

	`lines` are dicts of item_code, qty, uom, unit_cost, and optionally lot.
	"""
	if not warehouse:
		raise ValueError("a bin transfer needs a warehouse")
	if not source_bin or not target_bin:
		raise ValueError("both bins are required")
	if source_bin == target_bin:
		raise ValueError(f"{source_bin} is both the source and the destination")

	out_legs = []
	in_legs = []

	for line in lines:
		item = line.get("item_code")
		qty = float(line.get("qty") or 0)
		if qty <= 0:
			raise ValueError(f"{item}: quantity must be positive, got {qty}")
		if not line.get("uom"):
			raise ValueError(f"{item}: unit is required and must match the item's UOM exactly")

		cost = float(line.get("unit_cost") or 0)
		if cost <= 0:
			raise ValueError(
				f"{item}: no unit cost for the stock in {warehouse}. The arriving leg is "
				"valued at what is sent, so a zero would write the item's value down to "
				"nothing."
			)

		lot = (line.get("lot") or "").strip() or None

		out_legs.append(
			{
				"item_id": item,
				"warehouse_id": warehouse,
				"quantity": qty,
				"unit": line["uom"],
				"bin": source_bin,
				"lot": lot,
			}
		)
		in_legs.append(
			{
				"item_id": item,
				"warehouse_id": warehouse,
				"quantity": qty,
				"unit": line["uom"],
				"bin": target_bin,
				"lot": lot,
				"cost": cost,
			}
		)

	if not out_legs:
		raise ValueError("a bin transfer must move something")

	return {"out": out_legs, "in": in_legs}

def produced_unit_cost(consumed, produced_qty):
	"""Unit cost of what was made, from the cost of what was actually consumed.

	Intacct values the produce leg (UPDATES_COST=true) and takes the cost we send, so
	this number has to be right. It is DERIVED, not invented: every component rate came
	from Intacct in the first place, so the total is Intacct's own money divided by the
	quantity actually produced.

	`consumed` is dicts of qty and rate. Returns a unit cost, never negative.
	"""
	produced_qty = float(produced_qty or 0)
	if produced_qty <= 0:
		raise ValueError(f"produced quantity must be positive, got {produced_qty}")

	total = sum(float(line.get("qty") or 0) * float(line.get("rate") or 0) for line in consumed)
	if total < 0:
		raise ValueError("consumed cost cannot be negative")
	return total / produced_qty


def manufacture_legs(consumed, produced_item, produced_qty, produced_uom, warehouse):
	"""The two legs of a production run, as Intacct wants them.

	They are SEPARATE transaction definitions, so they cannot share one document:
	  Manufacturing Backflush Decr — components consumed, no cost (the definition has
	                                 UPDATES_COST=false; sending a cost would override
	                                 Intacct's own valuation of the components)
	  Manufacturing Run Increase   — finished goods in, WITH unit cost

	Quantities are POSITIVE on both. Each definition applies its own sign — send a
	negative on a decrease definition and it double-negates, moving stock the wrong way.
	"""
	if not consumed:
		raise ValueError("a production run must consume something")
	produced_qty = float(produced_qty or 0)
	if produced_qty <= 0:
		raise ValueError(f"produced quantity must be positive, got {produced_qty}")
	if not produced_uom:
		raise ValueError("produced unit is required and must match the item's UOM exactly")

	for line in consumed:
		if float(line.get("qty") or 0) <= 0:
			raise ValueError(f"{line.get('item_code')}: consumed quantity must be positive")
		if not line.get("uom"):
			raise ValueError(f"{line.get('item_code')}: unit is required")

	return {
		"consume": [
			{
				"item_id": line["item_code"],
				"warehouse_id": line["warehouse"],
				"quantity": float(line["qty"]),
				"unit": line["uom"],
				"bin": line.get("bin"),
				# No cost. The definition does not value this leg.
			}
			for line in consumed
		],
		"produce": [
			{
				"item_id": produced_item,
				"warehouse_id": warehouse,
				"quantity": produced_qty,
				"unit": produced_uom,
				"cost": produced_unit_cost(consumed, produced_qty),
			}
		],
	}


def purchase_order_signature(lines):
	"""What a mirrored order currently says, for deciding whether it changed at all.

	Rebuilding an unchanged order every sync would cancel and recreate documents daily,
	and every rebuild takes Bin.ordered_qty off and puts it back — churn that makes the
	stock-on-order figure flicker for no reason.

	Order independent: Intacct may return the same lines in a different sequence, and that
	is not a change.
	"""
	return sorted(
		(
			line["item_code"],
			round(float(line["qty"]), 6),
			line["warehouse"],
			str(line["schedule_date"]),
		)
		for line in lines
	)


def classify_manufacture_rows(rows):
	"""Split a Manufacture entry's rows into what was consumed and what was produced.

	Returns {"consumed": [...], "produced": row or None, "problems": [...]}. Problems are
	sentences for a human; a caller with any of them must refuse to post.

	The refusals exist because the first version classified by elimination — finished item,
	else anything with a source warehouse, else skip — and that quietly dropped rows:

	  TWO finished items       the second overwrote the first, so a co-product posted as if
	                           the other had never been made
	  a row with a destination
	  and no source            skipped entirely, so scrap output reached Intacct as nothing

	Both are refused rather than handled, because handling them means splitting one
	production cost across several outputs, and there is no non-arbitrary way to do that.
	Quantity-weighted is wrong the moment two outputs are worth different amounts. When a
	client actually needs co-products, someone decides the allocation rule and it gets
	built — until then a loud stop beats a wrong number in the accounts.
	"""
	consumed, produced, problems = [], None, []
	finished = [row for row in rows if row.get("is_finished_item")]

	if len(finished) > 1:
		names = ", ".join(str(row.get("item_code")) for row in finished)
		problems.append(
			f"This entry produces more than one finished item ({names}). Fuse cannot split "
			"one production cost across several outputs without inventing the split, so it "
			"will not post it. Produce them on separate entries."
		)
	elif finished:
		produced = finished[0]

	for row in rows:
		if row.get("is_finished_item"):
			continue
		if row.get("s_warehouse"):
			consumed.append(row)
			continue
		if row.get("t_warehouse"):
			# Output that is not the finished item: scrap, a by-product, a rework return.
			problems.append(
				f"{row.get('item_code')} is produced by this entry but is not the finished "
				"item, so Fuse has no cost for it and will not post it. Scrap and "
				"by-products are not supported yet."
			)
		else:
			problems.append(
				f"{row.get('item_code')} has neither a source nor a destination warehouse. "
				"Fuse cannot tell which way it moved."
			)

	if not produced and not problems:
		problems.append("This entry has no finished item — nothing was produced.")

	return {"consumed": consumed, "produced": produced, "problems": problems}


def classify_disassemble_rows(rows):
	"""Split a Disassemble entry into the item taken apart and the components returned.

	The mirror of `classify_manufacture_rows`, and deliberately NOT keyed on
	`is_finished_item`: taking something apart is not a production run and nothing sets
	that flag on one. Direction is the only reliable signal — exactly one row leaves
	stock, and the rest arrive.

	Returns {"taken": row or None, "returned": [...], "problems": [...]}. Problems are
	sentences for a human; a caller with any of them must refuse to post.
	"""
	taken, returned, problems = None, [], []

	for row in rows:
		source, target = row.get("s_warehouse"), row.get("t_warehouse")

		if source and target:
			problems.append(
				f"{row.get('item_code')} has both a source and a destination warehouse, so "
				"it is a move rather than a disassembly. Take it apart on its own entry."
			)
		elif source:
			if taken is not None:
				problems.append(
					f"This entry takes apart more than one item ({taken.get('item_code')}, "
					f"{row.get('item_code')}). Fuse has one cost to break up, not two, so it "
					"will not post it. Take them apart on separate entries."
				)
			else:
				taken = row
		elif target:
			returned.append(row)
		else:
			problems.append(
				f"{row.get('item_code')} has neither a source nor a destination warehouse. "
				"Fuse cannot tell which way it moved."
			)

	if not problems:
		if taken is None:
			problems.append("This entry takes nothing apart — no row leaves stock.")
		elif not returned:
			problems.append(
				f"{taken.get('item_code')} is taken apart but nothing comes back. A "
				"disassembly has to return the components it breaks into."
			)

	return {"taken": taken, "returned": returned, "problems": problems}


def manufacture_reversal_legs(consumed, produced_item, produced_qty, produced_uom, warehouse):
	"""The two legs that undo a production run.

	NOT the forward legs negated. The cost moves to the OTHER leg, because the pairs are
	asymmetric in Intacct:

	  forward   Backflush Decr  components out, no cost   Run Increase  goods in, WITH cost
	  reversal  Run Decrease    goods out, no cost        Backflush Incr components in, WITH cost

	So putting components back means telling Intacct what each one costs, and it must be
	the rate they were consumed at. Get that wrong and the reversal leaves a valuation
	residue behind — the quantity returns, the money does not.

	`consumed` is dicts of item_code, qty, uom, warehouse, rate, bin — the same rows the
	forward post used, read before the cancel rewrites them.

	Quantities are POSITIVE on both legs, as always: each definition applies its own sign.
	"""
	if not consumed:
		raise ValueError("a production run must consume something, so its reversal must return something")
	produced_qty = float(produced_qty or 0)
	if produced_qty <= 0:
		raise ValueError(f"produced quantity must be positive, got {produced_qty}")
	if not produced_uom:
		raise ValueError("produced unit is required and must match the item's UOM exactly")

	for line in consumed:
		if float(line.get("qty") or 0) <= 0:
			raise ValueError(f"{line.get('item_code')}: consumed quantity must be positive")
		if not line.get("uom"):
			raise ValueError(f"{line.get('item_code')}: unit is required")
		# A zero cost here is not merely wrong, it is destructive: the increase definition
		# has UPDATES_COST=true, so Intacct would take the zero and overwrite the item's
		# real valuation with it. Refuse rather than send it.
		if float(line.get("rate") or 0) <= 0:
			raise ValueError(
				f"{line.get('item_code')}: no cost to return it at. Sending zero on a "
				"cost-updating definition would overwrite Intacct's valuation."
			)

	return {
		"unproduce": [
			{
				"item_id": produced_item,
				"warehouse_id": warehouse,
				"quantity": produced_qty,
				"unit": produced_uom,
				# No cost. Intacct removes it at its own current valuation, which is the
				# honest answer — we do not know what it has cost since.
			}
		],
		"unconsume": [
			{
				"item_id": line["item_code"],
				"warehouse_id": line["warehouse"],
				"quantity": float(line["qty"]),
				"unit": line["uom"],
				"cost": float(line["rate"]),
				"bin": line.get("bin"),
			}
			for line in consumed
		],
	}


def kit_build_order(kit_codes, recipes):
	"""Order kits so every kit is built after the kits it consumes.

	Returns (order, circular). Cancellation must use the exact reverse: ERPNext refuses
	to cancel a BOM another BOM still links to, so a sub-assembly cannot go until every
	parent consuming it has gone.
	"""
	order = []
	placed = set()
	pending = [code for code in kit_codes if code in recipes]

	while pending:
		still_pending = []
		for code in pending:
			blocked = any(
				line["item_code"] in kit_codes and line["item_code"] not in placed
				for line in recipes.get(code, [])
			)
			if blocked:
				still_pending.append(code)
			else:
				order.append(code)
				placed.add(code)

		if len(still_pending) == len(pending):
			# Nothing moved: everything left is in a cycle.
			return order, still_pending
		pending = still_pending

	return order, []


def barcode_type(value):
	"""The ERPNext Item Barcode type for a code, or None if it is not a GTIN.

	ERPNext validates the length AND the check digit of anything tagged UPC-A or
	EAN. That validation runs on save, so a tag we cannot stand behind does not
	merely fail to scan — it fails the whole item, and the items sync reports the
	item as an error every hour until someone fixes Intacct.

	Clients number their own stock, their own works orders and their own bins, and
	none of those are GTINs. An untyped barcode is not a lesser barcode: ERPNext
	stores it, the scanner reads it, and `floor.find_item` matches it exactly the
	same way. So the type is claimed only when the number really is one, and left
	blank otherwise.

	>>> barcode_type("4006381333931")   # a real EAN-13
	'EAN'
	>>> barcode_type("036000291452")    # a real UPC-A
	'UPC-A'
	>>> barcode_type("WO-2026-00014")   # a client's own numbering
	>>> barcode_type("4006381333930")   # right shape, wrong check digit
	"""
	digits = (value or "").strip()
	if not digits.isdigit():
		return None

	if len(digits) == 12:
		kind = "UPC-A"
	elif len(digits) == 13:
		kind = "EAN"
	else:
		return None

	# GTIN check digit: weight the body 3,1,3,1… from the right, and the total plus
	# the check digit must reach the next multiple of ten.
	total = 0
	for position, char in enumerate(reversed(digits[:-1])):
		total += int(char) * (3 if position % 2 == 0 else 1)

	if (10 - total % 10) % 10 != int(digits[-1]):
		return None

	return kind
