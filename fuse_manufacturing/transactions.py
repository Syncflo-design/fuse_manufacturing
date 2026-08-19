"""Which Intacct definition each Fuse process posts to.

Every Intacct company names its transaction definitions differently. Leadertread calls
its goods receipt "Goods received voucher"; the donor's company called the same thing
"PO Receiver-Inventory". A name that is right for one client is wrong for the next, and
the rejection it causes names no field — so nothing here is a constant and nothing is
defaulted from another client.

Two halves:

  * `Intacct Transaction Definition` mirrors what the company actually has, read from
    Intacct. That is the picker.
  * The Transactions table on Intacct Settings maps one Fuse process to one of those
    definitions. That is the client's choice.

`definition_for` is what the postings call. It refuses rather than guesses.
"""

import frappe

# Every process that posts a definition-driven document, in the order it appears on the
# settings page.
#
# `seed` is the name this process used while it was a constant in postings.py. It is a
# STARTING POINT for a site that already worked, not a default: it is written once, when
# the row is first created, and only if that definition actually exists on the company.
# A fresh client seeds nothing and must choose.
#
# `key` is permanent. The postings look definitions up by it, so renaming one unmaps the
# process without saying so.
PROCESSES = [
	{
		"key": "goods_receipt",
		"label": "Receiving goods",
		"description": "Converts a purchase order into a receipt when a delivery is booked in.",
		"source": "Purchasing",
		"seed": None,
		"required": 1,
	},
	{
		"key": "manufacture_produce",
		"label": "Production — finished goods in",
		"description": "The increase leg of a production run. Carries the cost, worked out from what was consumed.",
		"source": "Inventory",
		"seed": "Manufacturing Run Increase",
		"required": 1,
	},
	{
		"key": "manufacture_consume",
		"label": "Production — components out",
		"description": "The decrease leg of a production run. Sends no cost; Intacct values it at its own.",
		"source": "Inventory",
		"seed": "Manufacturing Backflush Decr",
		"required": 1,
	},
	{
		"key": "manufacture_unproduce",
		"label": "Production reversal — finished goods out",
		"description": "Undoes the increase leg when a production run is cancelled. Sends no cost.",
		"source": "Inventory",
		"seed": "Manufacturing Run Decrease",
		"required": 1,
	},
	{
		"key": "manufacture_unconsume",
		"label": "Production reversal — components back in",
		"description": "Undoes the decrease leg. Carries the cost the components left at — a zero here would overwrite Intacct's valuation, so it is refused rather than sent.",
		"source": "Inventory",
		"seed": "Manufacturing Backflush Incr",
		"required": 1,
	},
]

PROCESSES_BY_KEY = {process["key"]: process for process in PROCESSES}


def sync_processes():
	"""Make the settings table match the registry, without touching what is mapped.

	Runs on every migrate. A client's choice is never overwritten; only rows that do not
	exist yet are created, and only they take a seed.
	"""
	if not frappe.db.exists("DocType", "Intacct Transaction Mapping"):
		return

	settings = frappe.get_single("Intacct Settings")
	chosen = {
		row.process_key: row.definition for row in settings.get("transaction_mappings") or []
	}

	settings.set("transaction_mappings", [])
	for process in PROCESSES:
		definition = chosen.get(process["key"])

		# Seed only a row that has never existed, and only where the definition is really
		# on this company. Writing a name Intacct does not have would put a broken value
		# in front of an admin and look like a considered choice.
		if process["key"] not in chosen and process["seed"]:
			if frappe.db.exists("Intacct Transaction Definition", process["seed"]):
				definition = process["seed"]

		settings.append(
			"transaction_mappings",
			{
				"process_key": process["key"],
				"label": process["label"],
				"description": process["description"],
				"required": process["required"],
				"definition": definition,
			},
		)

	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


def definition_for(key):
	"""The Intacct definition this process posts to, or a refusal saying so.

	Refuses rather than falling back to the name that used to be hardcoded. A fallback
	would post to whatever the donor's company called it — silently, on a client where
	that name means nothing or, worse, means something else.
	"""
	settings = frappe.get_cached_doc("Intacct Settings")
	for row in settings.get("transaction_mappings") or []:
		if row.process_key == key and row.definition:
			return row.definition

	process = PROCESSES_BY_KEY.get(key, {})
	label = process.get("label", key)
	frappe.throw(
		f"No Intacct definition is mapped for “{label}”, so this cannot be posted.\n\n"
		"Set it under Transactions on Intacct Settings. The list shows the definitions "
		"this company actually has — run the definitions sync first if it is empty.",
		title="Intacct definition not mapped",
	)


@frappe.whitelist()
def mapping_status():
	"""What is mapped and what is not — for checking a new site before anyone posts."""
	settings = frappe.get_cached_doc("Intacct Settings")
	mapped = {
		row.process_key: row.definition for row in settings.get("transaction_mappings") or []
	}
	return {
		"processes": [
			{
				"key": process["key"],
				"label": process["label"],
				"required": bool(process["required"]),
				"definition": mapped.get(process["key"]),
				"ready": bool(mapped.get(process["key"])),
			}
			for process in PROCESSES
		],
		"unmapped": [
			process["label"]
			for process in PROCESSES
			if process["required"] and not mapped.get(process["key"])
		],
	}
