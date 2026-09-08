"""Tiles this app contributes to the Fuse home page.

Almost every Fuse tile lives in fuse_theme, which is right: the home page is the theme's
job. Two belong here instead.

Warehouse Transfer normally opens ERPNext's Stock Entry form. With Use Simple Warehouse
Transfer switched on it opens Fuse Stock Transfer instead — a route that depends on a
setting this app owns, so this app replaces its own tile rather than the theme reading a
field it has no business knowing about.

Bin Transfer has no counterpart in the theme at all. It moves stock between bins inside
one warehouse, which only exists because Intacct tracks bins, so it belongs to the app
that talks to Intacct.
"""

import frappe

TRANSFER_ROLES = ["Stock Controller", "Stock User", "Stock Manager"]


def get_tiles():
	"""This app's tiles, in the shape the theme's own list uses.

	A tile returned here REPLACES a theme tile of the same key, which is how the transfer
	tile changes where it goes. The bin tile has a key of its own and is simply added; the
	theme switches it off through the Active Modules table like every other tile.
	"""
	tiles = []

	if _setting("use_simple_warehouse_transfer"):
		tiles.append(
			{
				"key": "item_transfer",
				"label": "Warehouse Transfer",
				"blurb": "Move stock between warehouses",
				"icon": "⇄",
				"route": ["new", "Fuse Stock Transfer"],
				"roles": TRANSFER_ROLES,
			}
		)

	tiles.append(
		{
			# The planner's way in: the order book first, Item Demand a button away from
			# it. Its own module switch (see modules.py) — it was briefly tied to
			# Production Plan, which Leader Rubber has off, and vanished with it.
			"key": "planning",
			"label": "Planning",
			"blurb": "Open orders, and what to make and buy for them",
			"icon": "📈",
			"route": ["query-report", "Outstanding Orders"],
			"roles": [
				"Stock Controller", "Stock Manager", "Manufacturing User", "Manufacturing Manager",
				"Purchase User", "Purchase Manager", "Sales Manager",
			],
		}
	)

	tiles.append(
		{
			# Sits next to Warehouse Transfer, and reads as its smaller sibling: same idea,
			# one warehouse. Switched off by default — see the bin_transfer module.
			"key": "bin_transfer",
			"label": "Bin Transfer",
			"blurb": "Move stock between bins in one warehouse",
			"icon": "⇅",
			"route": ["new", "Fuse Bin Transfer"],
			"roles": TRANSFER_ROLES,
		}
	)

	return tiles


def _setting(fieldname):
	"""One checkbox off Intacct Settings.

	Fails to FALSE, deliberately. Every way this can fail — settings not migrated yet, the
	field not created yet on a first load after a deploy — means the site is not yet set up
	for whatever the switch turns on, and the plainer answer is the safe one.
	"""
	try:
		return bool(frappe.db.get_single_value("Intacct Settings", fieldname))
	except Exception:
		return False
