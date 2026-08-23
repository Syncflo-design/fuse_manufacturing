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
		"key": "receiving",
		"label": "Receiving",
		"description": "Book supplier deliveries in against a mirrored purchase order.",
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
		"label": "Item Transfer",
		"description": "Move stock between warehouses.",
	},
	{
		"key": "stock",
		"label": "Stock",
		"description": "ERPNext's own Stock workspace — the full module, for general stock management.",
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
	"works_orders": ["Work Order"],
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
