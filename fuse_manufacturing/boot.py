"""The BOM lock, worked out on the server and handed to the desk at boot.

bom_locked.js hides the New button where recipes come from Intacct. It used to read Intacct
Settings from the browser, and a login without read permission on that doctype was shown
"No permission for Intacct Settings" on every BOM list and form. Read here instead: the
answer is a yes/no every user may know, and only reading the settings record itself needs
the permission.

Nothing in here may raise: a boot hook that fails stops the whole desk from loading.
"""

import frappe


def extend(bootinfo):
	try:
		# The same condition as postings, which refuses the insert.
		bootinfo.fuse_boms_from_intacct = bool(frappe.get_cached_doc("Intacct Settings").get("boms_from_intacct"))
	except Exception:
		# No settings yet: nothing is locked, as on any site without Intacct.
		bootinfo.fuse_boms_from_intacct = False
