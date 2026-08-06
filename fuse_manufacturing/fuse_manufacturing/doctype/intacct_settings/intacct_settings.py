import frappe
from frappe.model.document import Document


class IntacctSettings(Document):
	def validate(self):
		if self.page_size and self.page_size > 1000:
			frappe.msgprint(
				"Intacct's own guidance is to keep queries under about 1000 records. "
				"Larger pages tend to time out rather than fail cleanly."
			)
