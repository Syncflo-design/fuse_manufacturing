"""One line of a Fuse Stock Transfer: an item, how much of it, and where it sits.

No behaviour of its own. Every check that matters — enough stock in the source warehouse,
bins that belong to the warehouses being used, a lot where Intacct tracks one — is made on
the parent, because a line is only right or wrong in the context of the whole document.
The same item can appear twice, and each row looks fine on its own while the pair asks for
more than the warehouse holds.
"""

from frappe.model.document import Document


class FuseStockTransferItem(Document):
	pass
