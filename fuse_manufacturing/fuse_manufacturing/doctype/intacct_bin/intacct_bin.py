from frappe.model.document import Document


class IntacctBin(Document):
	"""A bin as Intacct holds it.

	No create/write permission is granted to any role — the mirror writes with
	ignore_permissions, and nobody edits these by hand. Intacct is the golden source.
	"""

	pass
