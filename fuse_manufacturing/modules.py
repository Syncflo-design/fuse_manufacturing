"""Which parts of Fuse Manufacturing a client has switched on.

This is a LAUNCHER preference, not a permission. Switching a module off takes its tile
off Fuse Home and nothing else: the doctypes behind it still work, and someone who knows
the URL or uses the awesome bar still gets there. Anything stronger belongs in role
permissions, which a deploy overwrites (see the 2026-05-20 gotcha), or in a guard on the
doctype itself — both bigger decisions than tidying a home page.

The TABLE and the rules for it live in fuse_core, which owns Intacct Settings. What lives
here is the list of features this app actually implements, handed to core through the
`fuse_modules` hook. That split is what lets Manufacturing and Projects be sold and
installed separately: core knows there are switches, not what they switch.
"""

# Read from core rather than reimplemented. Callers in this app — postings.py, install.py
# — go on using modules.is_active and modules.sync_modules exactly as before.
from fuse_core.modules import (  # noqa: F401
	active_modules,
	is_active,
	module_label,
	sync_modules,
)

# Every switchable part of this app, in the order it appears on the home page.
#
# `key` is what fuse_theme matches its tiles on and is permanent — renaming one orphans
# a client's setting and silently turns the module back on. The label and blurb are for
# the person reading the settings page, who is not the person who wrote the tile.
MODULES = [
	{
		"key": "material_request",
		"label": "Material Request",
		"description": "Request material to buy, move between warehouses, or make. The requisition step, raised by stores, a planner or the floor.",
	},
	{
		"key": "receiving",
		"label": "Receiving",
		"description": "Book supplier deliveries in against a mirrored purchase order.",
	},
	{
		"key": "boms",
		"label": "BOMs",
		"description": "What each product is made of, and what can be built from stock on hand.",
	},
	{
		"key": "production_plan",
		"label": "Production Plan",
		"description": "Explode demand through the BOMs and raise the works orders and material requests it calls for.",
	},
	{
		"key": "works_orders",
		"label": "Works Orders",
		"description": "Record production against a works order.",
	},
	{
		"key": "wip_issue",
		"label": "Issue to WIP",
		"description": "Move components from a store into a work-in-progress warehouse.",
	},
	{
		"key": "item_transfer",
		"label": "Warehouse Transfer",
		"description": "Move stock between warehouses.",
	},
	{
		# Off by default. Only a client whose items are bin-enabled in Intacct has anywhere
		# for this to move stock to, and on a site without bins the screen would offer an
		# empty picker and refuse everything put through it.
		"key": "bin_transfer",
		"label": "Bin Transfer",
		"description": "Move stock between bins inside one warehouse. The warehouse total does not change, so this is recorded in Fuse and posted to Intacct, which is where stock is held per bin.",
		"default": 0,
	},
	{
		"key": "quality",
		"label": "Quality",
		"description": "Inspect goods in, batches made and product going out, against the item's own specification. Off means the checks are not enforced anywhere.",
	},
	{
		"key": "picking",
		"label": "Picking",
		"description": "Pick and deliver against a mirrored sales order. Relieves stock in Intacct as a shipper — the invoice is still raised there.",
	},
	{
		# Off unless asked for. It lands on the same subject as Stock Control, which is the
		# curated version — two tiles onto one room is the confusion the tile grid exists to
		# remove. Left switchable for a client whose own administrator wants the full module.
		"key": "stock",
		"label": "Stock",
		"description": "ERPNext's own Stock workspace — the full module, for general stock management. Off by default; Stock Control covers the same ground, curated.",
		"default": 0,
	},
	{
		"key": "stock_control",
		"label": "Stock Control",
		"description": "Transfers, production and stock reports.",
	},
	{
		"key": "shop_floor",
		"label": "Shop Floor Screens",
		"description": "The phone and tablet screens, and the link to them from Fuse Home.",
	},
]


def get_modules():
	"""This app's switches, for core's `fuse_modules` hook.

	A copy, not the list itself: core merges what every app contributes, and a caller that
	edited the result would be editing this module's own registry.
	"""
	return [dict(module) for module in MODULES]


# ──────────────────────────────────────────────────────────────────────────────
# What switching a module off actually withdraws
# ──────────────────────────────────────────────────────────────────────────────

# Doctypes the Fuse role loses when a module is off. Re-applied on every migrate AND
# whenever the settings are saved — core announces that through the `fuse_modules_changed`
# hook — so a deploy re-asserting permissions (the 2026-05-20 gotcha) works FOR this
# rather than against it: the app JSON is the source of truth, and the source of truth now
# reads the client's choice.
MODULE_DOCTYPES = {
	"receiving": ["Purchase Receipt"],
	"picking": ["Delivery Note"],
	"works_orders": ["Work Order"],
	# Fuse's own transfer screens. These CAN be withdrawn by permission because each is a
	# doctype of its own — the Stock Entry the warehouse one raises cannot be, which is
	# why item_transfer appears in MODULE_PURPOSES below as well.
	"item_transfer": ["Fuse Stock Transfer"],
	"bin_transfer": ["Fuse Bin Transfer"],
	# Quality does not gate a movement document — it gates whether a movement is allowed
	# to happen without a passing inspection. What the switch withdraws is the ability to
	# record one at all.
	"quality": ["Quality Inspection", "Fuse Measuring Instrument"],
}

# Stock Entry serves three modules at once, so permissions cannot separate them — a
# role either raises Stock Entries or it does not. The purpose is what distinguishes
# them, and that is a per-document check, which is why these are guarded in code
# (postings.block_inactive_module) rather than by withdrawing the doctype.
MODULE_PURPOSES = {
	"Material Transfer for Manufacture": "wip_issue",
	"Material Transfer": "item_transfer",
	"Manufacture": "works_orders",
}


def purpose_module(purpose):
	"""Which module a Stock Entry purpose belongs to, or None if it belongs to none."""
	return MODULE_PURPOSES.get(purpose)
