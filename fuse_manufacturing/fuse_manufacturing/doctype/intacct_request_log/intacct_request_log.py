from frappe.model.document import Document


class IntacctRequestLog(Document):
	"""One Intacct request and its response.

	Written by the gateway, never by hand. No role has create or write permission —
	an audit trail someone can edit is not an audit trail.
	"""

	pass
