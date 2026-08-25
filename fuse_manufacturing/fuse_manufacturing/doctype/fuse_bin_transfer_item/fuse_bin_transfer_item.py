"""One line of a Fuse Bin Transfer: an item, how much of it, and which lot.

No behaviour of its own — the bins live on the parent, because the whole document moves
between the same two bins. Every check is made there for the same reason it is on the
warehouse transfer: the same item can appear twice, and each row looks fine on its own.
"""

from frappe.model.document import Document


class FuseBinTransferItem(Document):
	pass
