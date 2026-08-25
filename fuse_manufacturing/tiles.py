"""Tiles this app contributes to the Fuse home page.

Almost every Fuse tile lives in fuse_theme, which is right: the home page is the theme's
job. What belongs here is the one tile whose ROUTE depends on a setting this app owns.

Item Transfer normally opens ERPNext's Stock Entry form. With Use Simple Warehouse
Transfer switched on it opens Fuse Stock Transfer instead. The theme has no business
knowing that a manufacturing setting exists, so this app replaces its own tile rather
than the theme reading a field it does not own.
"""

import frappe


def get_tiles():
	"""The Item Transfer tile, but only when it needs to differ from the theme's.

	Returns nothing at all in the ordinary case. A tile returned here REPLACES the theme's
	tile of the same key, so returning one unconditionally would mean this app quietly
	owning a tile it has no reason to own.
	"""
	if not _simple_transfer_on():
		return []

	return [
		{
			"key": "item_transfer",
			"label": "Warehouse Transfer",
			"blurb": "Move stock between warehouses",
			"icon": "⇄",
			"route": ["new", "Fuse Stock Transfer"],
			"roles": ["Stock Controller", "Stock User", "Stock Manager"],
		}
	]


def _simple_transfer_on():
	"""Whether this site uses Fuse's own transfer screen.

	Fails to FALSE, deliberately. Every way this can fail — settings not migrated yet, the
	field not created yet on a first load after deploy — means the site is not yet set up
	for the simple screen, and the theme's own tile is the safe answer.
	"""
	try:
		return bool(
			frappe.db.get_single_value("Intacct Settings", "use_simple_warehouse_transfer")
		)
	except Exception:
		return False
