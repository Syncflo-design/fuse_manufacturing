"""The user guides this app ships.

Guides used to be uploaded by hand into Home/Fuse Training on each site, which meant a
new instance started with an empty Training page and nobody noticed until a client asked
where the help was. These travel with the app: install it and the guides are there.

They are served as app assets rather than stored as Files, so they cost nothing per site,
update with a deploy, and cannot be deleted by accident. A site can still upload its own
into the training folder — the Training page shows both, and an upload with the same
title wins, which is how a client puts their own screenshots in front of ours.

WRITTEN in `docs/training/*.md`, SERVED from `public/files/training/*.html`. Run
`python docs/build_guides.py` after editing any of them; the HTML is generated and a hand
edit to it is lost on the next build.

HTML rather than PDF because a PDF step needs Word or LibreOffice on whoever's machine is
publishing. Seven finished guides sat unpublished for exactly that reason. The three
originals are still PDFs and still listed — there is no need to convert what already works.

`title` is what the reader sees; the leading number in the filename only fixes the order on
disk. The Training page itself sorts alphabetically by title, so the number is for whoever
maintains these, not for the reader.
"""

# Path is relative to /assets/fuse_manufacturing/files/.
GUIDES = [
	{"title": "Getting Started", "file": "training/01 Getting Started.pdf"},
	{"title": "Warehouse Transfer", "file": "training/02 Warehouse Transfer.html"},
	{"title": "Issue to WIP", "file": "training/03 Issue to WIP.pdf"},
	{"title": "Creating a Works Order", "file": "training/04 Creating a Works Order.html"},
	{
		"title": "Works Orders - Recording Production",
		"file": "training/05 Works Orders - Recording Production.html",
	},
	{"title": "Stock Control", "file": "training/06 Stock Control.html"},
	{"title": "Receiving", "file": "training/07 Receiving.html"},
	{"title": "User Setup and Passwords", "file": "training/08 User Setup and Passwords.html"},
	{"title": "Shop Floor Screens", "file": "training/09 Shop Floor Screens.html"},
	{"title": "Intacct Settings", "file": "training/10 Intacct Settings.html"},
	{"title": "Bin Transfer", "file": "training/11 Bin Transfer.html"},
	{"title": "Picking", "file": "training/12 Picking.html"},
	{"title": "Quality Inspection", "file": "training/13 Quality Inspection.html"},
	{"title": "Quality Setup", "file": "training/14 Quality Setup.html"},
	{"title": "Material Request", "file": "training/15 Material Request.html"},
	{"title": "BOMs", "file": "training/16 BOMs.html"},
	{"title": "Production Plan", "file": "training/17 Production Plan.html"},
	{"title": "Planning", "file": "training/18 Planning.html"},
]


def get_guides():
	"""This app's guides, for the theme's `fuse_guides` hook.

	Copies, not the list itself: the theme merges what every app contributes, and a caller
	that edited the result would be editing this module's own registry.
	"""
	return [
		{
			"title": guide["title"],
			"url": f"/assets/fuse_manufacturing/files/{guide['file']}",
			"is_pdf": guide["file"].lower().endswith(".pdf"),
		}
		for guide in GUIDES
	]
