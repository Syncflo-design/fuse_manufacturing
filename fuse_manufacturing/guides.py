"""The user guides this app ships.

Guides used to be uploaded by hand into Home/Fuse Training on each site, which meant a
new instance started with an empty Training page and nobody noticed until a client asked
where the help was. These travel with the app: install it and the guides are there.

They are served as app assets rather than stored as Files, so they cost nothing per site,
update with a deploy, and cannot be deleted by accident. A site can still upload its own
into the training folder — the Training page shows both, and an upload with the same
title wins, which is how a client puts their own screenshots in front of ours.

`title` is what the reader sees; the leading number in the filename is only there to fix
the order on disk. Keep the numbering in step with the order someone learns things in,
not with the order they were written.
"""

# Path is relative to /assets/fuse_manufacturing/files/.
GUIDES = [
	{"title": "Getting Started", "file": "training/01 Getting Started.pdf"},
	{"title": "Warehouse Transfer", "file": "training/02 Item Transfer.pdf"},
	{"title": "Issue to WIP", "file": "training/03 Issue to WIP.pdf"},
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
