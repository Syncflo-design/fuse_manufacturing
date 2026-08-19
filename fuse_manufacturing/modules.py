"""Which parts of Fuse a client has switched on.

This is a LAUNCHER preference, not a permission. Switching a module off takes its tile
off Fuse Home and nothing else: the doctypes behind it still work, and someone who
knows the URL or uses the awesome bar still gets there. Anything stronger belongs in
role permissions, which a deploy overwrites (see the 2026-05-20 gotcha), or in a guard
on the doctype itself — both bigger decisions than tidying a home page.

The registry lives here rather than in `fuse_theme` because these are Fuse's features;
the theme only draws tiles for them. The theme asks this module what is on, and works
without it — a site with no integration app shows everything.
"""

import frappe

# Every switchable part of Fuse, in the order it appears on the home page.
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

MODULES_BY_KEY = {module["key"]: module for module in MODULES}


def sync_modules():
	"""Make the settings table match the registry, without touching what is switched on.

	Runs on every migrate. New modules arrive switched ON, because a feature that ships
	invisible looks broken rather than optional. Retired ones are dropped, so the page
	never lists something that no longer exists.

	A client's own choice is never overwritten — that is the whole point of the table.
	"""
	if not frappe.db.exists("DocType", "Fuse Active Module"):
		return

	settings = frappe.get_single("Intacct Settings")
	chosen = {row.module_key: row.enabled for row in settings.get("active_modules") or []}

	settings.set("active_modules", [])
	for module in MODULES:
		settings.append(
			"active_modules",
			{
				"module_key": module["key"],
				"label": module["label"],
				"description": module["description"],
				# Present and set → keep it. Absent → new, so on.
				"enabled": chosen.get(module["key"], 1),
			},
		)

	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


@frappe.whitelist()
def active_modules():
	"""What is switched on, as {key: True/False}.

	A key missing from the table reads as ON. That matters on a site migrated before the
	table existed, and on the first load after a new module ships — in both cases the
	honest answer is "nobody has turned this off".
	"""
	settings = frappe.get_cached_doc("Intacct Settings")
	chosen = {row.module_key: bool(row.enabled) for row in settings.get("active_modules") or []}
	return {module["key"]: chosen.get(module["key"], True) for module in MODULES}


def is_active(key):
	"""Whether one module is switched on. Unknown keys are on, for the same reason."""
	return active_modules().get(key, True)


# ──────────────────────────────────────────────────────────────────────────────
# What switching a module off actually withdraws
# ──────────────────────────────────────────────────────────────────────────────

# Doctypes the Fuse role loses when a module is off. Re-applied on every migrate AND
# whenever the settings are saved, so a deploy re-asserting permissions (the
# 2026-05-20 gotcha) works FOR this rather than against it: the app JSON is the source
# of truth, and the source of truth now reads the client's choice.
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
