"""One process-to-definition mapping row. No behaviour — transactions.py owns it."""

from frappe.model.document import Document


class IntacctTransactionMapping(Document):
	pass
