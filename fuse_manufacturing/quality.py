"""Quality — inspection at the three points stock changes hands.

ERPNext already ships the machinery: Quality Inspection with readings against a template,
`inspection_required_before_purchase` and `inspection_required_before_delivery` on the
Item, and links from Purchase Receipt Item, Stock Entry Detail and Delivery Note Item. It
also blocks a submit when a required inspection is missing.

What it does not do is any of the following, and each one is a clause somebody will be
audited against:

  * **7.1.5.2 Measurement traceability.** A result is only evidence if the instrument that
    produced it was in calibration when it was taken. ERPNext has no instrument register,
    so Fuse keeps one and refuses an inspection taken on an overdue instrument.
  * **8.6 Release of product.** Release has to be authorised by a named person, and no
    product goes out until that has happened. ERPNext leaves `verified_by` optional.
  * **8.5.1 / 8.4 at the point of work.** ERPNext's refusal is a framework error that names
    a document. The person holding the drum needs to be told which line, what is missing,
    and what to do about it.

Which items are inspected is NOT decided here. It is the Item's own flags, set per product
the way a spec sheet is — a client who inspects nothing has nothing switched on and never
meets any of this.
"""

import frappe
from frappe.utils import getdate

# The three points, and what ERPNext calls each one. Deliberately a straight mapping and
# not a guess: the reference type is what a Quality Inspection stores, and getting it
# wrong means the inspection exists but the document cannot find it.
INSPECTION_POINTS = {
	"Purchase Receipt": "Incoming",
	"Stock Entry": "In Process",
	"Delivery Note": "Outgoing",
}


def _module_on():
	from fuse_manufacturing import modules

	return modules.is_active("quality")


# ──────────────────────────────────────────────────────────────────────────────
# 7.1.5.2 — the instrument behind the reading
# ──────────────────────────────────────────────────────────────────────────────


def block_uncalibrated_instrument(doc, method=None):
	"""Refuse an inspection taken on an instrument that is out of calibration.

	Checked against the REPORT DATE, not today: an inspection entered a week late is
	evidence about the day the sample was taken, and the question is whether the meter was
	in calibration then.

	This is the rule the whole instrument register exists for. Without it the register is
	a list nobody reads, and a certificate can quote a pH from a meter last calibrated in
	2019.
	"""
	instrument_id = doc.get("custom_instrument")
	if not instrument_id:
		return

	instrument = frappe.get_doc("Fuse Measuring Instrument", instrument_id)

	if instrument.status != "Active":
		frappe.throw(
			f"{instrument.instrument_id} is marked {instrument.status.lower()}, so a result "
			"taken on it cannot be used.",
			title="Instrument not in service",
		)

	if not instrument.calibration_due:
		frappe.throw(
			f"{instrument.instrument_id} has no calibration due date, so there is nothing to "
			"say the reading is traceable. Record its calibration first.",
			title="Instrument not calibrated",
		)

	taken_on = getdate(doc.report_date or frappe.utils.nowdate())
	if taken_on > getdate(instrument.calibration_due):
		frappe.throw(
			f"{instrument.instrument_id} was out of calibration on {taken_on} — it was due on "
			f"{instrument.calibration_due}. A reading taken on it is not traceable, so it "
			"cannot support a release.",
			title="Instrument out of calibration",
		)


# ──────────────────────────────────────────────────────────────────────────────
# 8.6 — who authorised the release
# ──────────────────────────────────────────────────────────────────────────────


def require_release_authority(doc, method=None):
	"""An outgoing inspection has to name who authorised the release.

	Only outgoing. An incoming check is a decision about whether to accept someone else's
	goods, and an in-process check is a decision about whether to carry on — neither is a
	release to a customer, and requiring a second signature on them would be ceremony.

	`verified_by` is ERPNext's own field, left optional by them and made compulsory here
	rather than adding a second field that means the same thing.
	"""
	if doc.inspection_type != "Outgoing":
		return
	if doc.status != "Accepted":
		return
	if (doc.get("verified_by") or "").strip():
		return

	frappe.throw(
		"An outgoing inspection releases product to a customer, so it has to say who "
		"authorised it. Fill in Verified By.",
		title="Release not authorised",
	)


# ──────────────────────────────────────────────────────────────────────────────
# 8.4 / 8.5.1 / 8.6 — at the point of work
# ──────────────────────────────────────────────────────────────────────────────


def _required_for(row, reference_type):
	"""Whether this line needs an inspection, per the Item's own flags.

	Purchase and delivery each have their own flag on the Item, and ERPNext has none for
	production — a made batch is checked when the client says the product is checked, which
	is the outgoing flag, because it is the same finished product either way.
	"""
	flags = frappe.db.get_value(
		"Item",
		row.item_code,
		["inspection_required_before_purchase", "inspection_required_before_delivery"],
		as_dict=True,
	)
	if not flags:
		return False

	if reference_type == "Purchase Receipt":
		return bool(flags.inspection_required_before_purchase)
	if reference_type == "Delivery Note":
		return bool(flags.inspection_required_before_delivery)
	# In process: only the finished item of a production run, not the components going in.
	return bool(flags.inspection_required_before_delivery) and bool(row.get("is_finished_item"))


def check_inspections(doc, method=None):
	"""Refuse a movement whose lines have not been inspected, and say which.

	ERPNext blocks this too. What it does not do is name the line, say whether the problem
	is a missing inspection or a rejected one, or mention that the item is flagged at all —
	its message sends a storeman to an administrator. This one is written for the person
	holding the drum.

	A REJECTED inspection is refused outright rather than warned about: shipping product
	that failed its own specification is the single thing a quality system exists to
	prevent. Releasing it anyway is a concession, which is a decision someone makes
	deliberately in the Non Conformance ERPNext already provides — not something to nod
	past on a phone.
	"""
	if not _module_on():
		return

	reference_type = doc.doctype
	if reference_type not in INSPECTION_POINTS:
		return

	missing, rejected = [], []
	for row in doc.get("items") or []:
		if not _required_for(row, reference_type):
			continue

		inspection = row.get("quality_inspection")
		if not inspection:
			missing.append(f"row {row.idx} ({row.item_code})")
			continue

		status = frappe.db.get_value("Quality Inspection", inspection, "status")
		if status != "Accepted":
			rejected.append(f"row {row.idx} ({row.item_code}) — {inspection} is {status or 'not accepted'}")

	if rejected:
		frappe.throw(
			"These lines have an inspection that did not pass:<br><br>"
			+ "<br>".join(rejected)
			+ "<br><br>Product that failed its specification cannot move on this document. "
			"Raise a Non Conformance to decide what happens to it.",
			title="Inspection failed",
		)

	if missing:
		frappe.throw(
			"These lines are flagged for inspection and have none:<br><br>"
			+ "<br>".join(missing)
			+ "<br><br>Record the inspection against the line, then submit again.",
			title="Inspection required",
		)


# ──────────────────────────────────────────────────────────────────────────────
# Recording one, from a screen
# ──────────────────────────────────────────────────────────────────────────────


def create_for_line(*, doc, row, captured):
	"""Build a Quality Inspection for one line of a movement, and attach it.

	Called between insert and submit. That ordering is not incidental: a Quality Inspection
	stores the document it belongs to, so the document has to exist first — and the submit
	has to be the thing that fails if the inspection does not pass, rather than a document
	going out and a record being written afterwards.

	`captured` is what the screen collected: readings by parameter, the instrument, and who
	authorised release. Missing readings are left blank rather than defaulted — a blank
	tells an auditor nobody measured it, and a zero tells them somebody did.
	"""
	reference_type = doc.doctype
	template = frappe.db.get_value("Item", row.item_code, "quality_inspection_template")

	inspection = frappe.new_doc("Quality Inspection")
	inspection.inspection_type = INSPECTION_POINTS.get(reference_type, "Incoming")
	inspection.reference_type = reference_type
	inspection.reference_name = doc.name
	inspection.item_code = row.item_code
	inspection.sample_size = captured.get("sample_size") or 1
	inspection.report_date = captured.get("report_date") or frappe.utils.nowdate()
	inspection.inspected_by = frappe.session.user
	inspection.company = doc.company
	inspection.quality_inspection_template = template
	inspection.custom_instrument = captured.get("instrument")
	inspection.remarks = captured.get("remarks")

	# The batch this is evidence about. Without it the certificate says a product passed,
	# not which drum did.
	batch = captured.get("batch_no") or row.get("batch_no")
	if batch:
		inspection.batch_no = batch

	if inspection.inspection_type == "Outgoing":
		inspection.verified_by = captured.get("verified_by")

	readings = captured.get("readings") or {}
	if template:
		for parameter in frappe.get_all(
			"Item Quality Inspection Parameter",
			filters={"parent": template},
			fields=["specification", "value", "min_value", "max_value", "numeric"],
			order_by="idx",
		):
			taken = readings.get(parameter.specification)
			line = {
				"specification": parameter.specification,
				"value": parameter.value,
				"numeric": parameter.numeric,
				"min_value": parameter.min_value,
				"max_value": parameter.max_value,
			}
			if taken not in (None, ""):
				if parameter.numeric:
					line["reading_value"] = taken
				else:
					line["reading_1"] = taken
			inspection.append("readings", line)

	# Accepted or not is the screen's call, because the person holding the sample is the
	# one who knows. ERPNext works the status out from the readings when they are numeric,
	# and this respects that by only overriding when the screen said so explicitly.
	if captured.get("status"):
		inspection.status = captured["status"]

	inspection.insert(ignore_permissions=True)
	inspection.submit()

	row.db_set("quality_inspection", inspection.name)
	return inspection.name


def attach_inspections(doc, rows_by_key, key_field):
	"""Create an inspection for every captured line on a freshly inserted document.

	`rows_by_key` is what the screen sent, keyed the way that screen identifies a line —
	the ordered line for receiving and picking. Rows with nothing captured are skipped; the
	validate check then refuses the submit if one was required, which is the correct
	outcome and the same one a desk user gets.
	"""
	if not _module_on():
		return []

	created = []
	for row in doc.get("items") or []:
		captured = (rows_by_key.get(row.get(key_field)) or {}).get("inspection")
		if not captured:
			continue
		created.append(create_for_line(doc=doc, row=row, captured=captured))
	return created


# ──────────────────────────────────────────────────────────────────────────────
# What the screens ask
# ──────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def line_requirement(item_code, reference_type):
	"""Whether a screen should ask for an inspection on this item, and with what.

	Returns the template so a screen can show the parameters and their limits without a
	second round trip — a picker deciding whether to call the lab wants to see what is
	being asked for.
	"""
	flags = frappe.db.get_value(
		"Item",
		item_code,
		[
			"inspection_required_before_purchase",
			"inspection_required_before_delivery",
			"quality_inspection_template",
		],
		as_dict=True,
	)
	if not flags:
		return {"required": False}

	required = (
		bool(flags.inspection_required_before_purchase)
		if reference_type == "Purchase Receipt"
		else bool(flags.inspection_required_before_delivery)
	)
	if not required:
		return {"required": False}

	parameters = []
	if flags.quality_inspection_template:
		parameters = frappe.get_all(
			"Item Quality Inspection Parameter",
			filters={"parent": flags.quality_inspection_template},
			fields=["specification", "value", "min_value", "max_value", "numeric"],
			order_by="idx",
		)

	return {
		"required": True,
		"inspection_type": INSPECTION_POINTS.get(reference_type, "Incoming"),
		"template": flags.quality_inspection_template,
		"parameters": parameters,
	}


@frappe.whitelist()
def instruments(instrument_type=None):
	"""Instruments a reading may be taken on today.

	Overdue ones are left out rather than listed and then refused — offering a choice that
	will be rejected two screens later is how people learn to distrust a system.
	"""
	filters = {"status": "Active", "calibration_due": (">=", frappe.utils.nowdate())}
	if instrument_type:
		filters["instrument_type"] = instrument_type

	return frappe.get_all(
		"Fuse Measuring Instrument",
		filters=filters,
		fields=["name", "instrument_id", "instrument_name", "instrument_type", "calibration_due"],
		order_by="instrument_name",
	)


@frappe.whitelist()
def calibration_due(days=30):
	"""Instruments falling due, so calibration is arranged before it stops production.

	The register is only useful if somebody looks at it before the due date rather than on
	the morning a batch cannot be released.
	"""
	return frappe.get_all(
		"Fuse Measuring Instrument",
		filters={
			"status": "Active",
			"calibration_due": ("<=", frappe.utils.add_days(frappe.utils.nowdate(), int(days))),
		},
		fields=["name", "instrument_id", "instrument_name", "instrument_type", "calibration_due"],
		order_by="calibration_due",
	)
