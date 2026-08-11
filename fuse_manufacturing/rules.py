"""Decision logic, with no Frappe and no network.

Everything here is a pure function: given the inputs, the answer is fixed. That is the
point — it can be tested anywhere, in a second, without a site.

The rules that live here are the ones that have actually gone wrong: recipe signatures,
precision alignment, cost fallback, drift tolerance, unit conversions and kit build
order. Keeping them out of masters.py is what makes them testable at all.
"""

import hashlib
import xml.etree.ElementTree as ET

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


def control_id_for(doctype, name, purpose=""):
	"""A control ID that is the same every time for the same piece of work.

	With <uniqueid>true</uniqueid> this is what stops a retry posting a movement twice.
	"""
	raw = f"{doctype}:{name}:{purpose}".strip(":")
	return f"fuse-{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


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


def result_keys(root):
	"""The record key from each <result>, whichever form Intacct returned it in.

	Two shapes, and only handling one of them loses the key silently:
	  create_ictransaction and friends return <result><key>123</key></result>
	  the generic <create> returns the object itself —
	    <result><data><ictransfer><RECORDNO>23</RECORDNO></ictransfer></data></result>

	Observed live: the first warehouse transfer posted successfully and came back with
	no key at all, because only <key> was being read. The posting was fine; the
	traceability was not.

	One entry per result, in order, so a caller can line keys up with the functions it
	sent. None where a result carried no key.
	"""
	if isinstance(root, str):
		root = ET.fromstring(root)

	keys = []
	for result in root.iter("result"):
		key = result.findtext(".//key")
		if key is None:
			key = result.findtext(".//RECORDNO")
		keys.append(key.strip() if key else None)
	return keys


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
