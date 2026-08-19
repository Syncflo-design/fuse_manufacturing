import frappe
from frappe.model.document import Document


class IntacctSettings(Document):
	def validate(self):
		if self.page_size and self.page_size > 1000:
			frappe.msgprint(
				"Intacct's own guidance is to keep queries under about 1000 records. "
				"Larger pages tend to time out rather than fail cleanly."
			)

	def on_update(self):
		"""Re-apply the role's permissions whenever the module switches change.

		Without this a switch would only take effect at the next migrate, so an admin
		would turn Receiving off, watch the tile vanish, and find the document still
		reachable — which reads as the setting not working.

		Only when something actually changed: re-applying permissions on every save of
		an unrelated field is churn, and permission writes are not free.
		"""
		before = self.get_doc_before_save()
		if before is not None:
			was = {row.module_key: row.enabled for row in before.get("active_modules") or []}
			now = {row.module_key: row.enabled for row in self.get("active_modules") or []}
			if was == now:
				return

		from fuse_manufacturing.install import _apply_role_permissions

		_apply_role_permissions()
