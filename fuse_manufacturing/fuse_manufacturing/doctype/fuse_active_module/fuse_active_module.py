"""One switchable part of Fuse. No behaviour — the parent and modules.py own it."""

from frappe.model.document import Document


class FuseActiveModule(Document):
	pass
