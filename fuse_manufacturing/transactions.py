"""The Intacct processes this app posts, and nothing else.

The table, the picker and the rules for both live in `fuse_core.transactions`, which owns
Intacct Settings. What lives here is the list of processes THIS app posts, handed to core
through the `fuse_processes` hook — the same split as the module switches in modules.py.

That is what lets the Transactions table grow as apps are added: Projects will declare its
own processes the day it posts one, and core will not need to change to accommodate them.

Anything that needs to READ a mapping — the postings, mostly — calls
`fuse_core.transactions.definition_for`.
"""

# Every process this app posts a definition-driven document for, in the order it appears on
# the settings page.
#
# `seed` is the name this process used while it was a constant in postings.py. It is a
# STARTING POINT for a site that already worked, not a default: it is written once, when the
# row is first created, and only if that definition actually exists on the company. A fresh
# client seeds nothing and must choose.
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


def get_processes():
	"""This app's processes, for core's `fuse_processes` hook.

	A copy, not the list itself: core merges what every app contributes, and a caller that
	edited the result would be editing this module's own registry.
	"""
	return [dict(process) for process in PROCESSES]
