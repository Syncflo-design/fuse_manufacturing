"""Decision logic, with no Frappe and no network.

Everything here is a pure function: given the inputs, the answer is fixed. That is the
point — it can be tested anywhere, in a second, without a site.

The rules that live here are the ones that have actually gone wrong: recipe signatures,
precision alignment, cost fallback, drift tolerance, unit conversions and kit build
order. Keeping them out of masters.py is what makes them testable at all.
"""

import hashlib

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
