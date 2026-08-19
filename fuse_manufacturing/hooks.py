app_name        = "fuse_manufacturing"
app_title       = "Fuse Manufacturing"
app_publisher   = "Syncflo"
app_description = "Sage Intacct integration for ERPNext — masters in, stock postings out."
app_email       = "ops@syncflo.co.za"
app_license     = "MIT"

after_install = "fuse_manufacturing.install.after_install"

# Custom fields have to be re-applied on every migrate, not only at install. A field
# added in a later release is otherwise never created on a site that already has the
# app, and the first sync that uses it fails on an unknown column.
# create_custom_fields is idempotent, so running it each migrate costs nothing.
after_migrate = "fuse_manufacturing.install.after_install"

# Masters are a one-way mirror, so the only question is how stale we tolerate them being.
# Items move (new codes, renames, tracking flags) — hourly, incremental.
# Warehouses, UOMs and bins are configuration someone changes deliberately — daily is
# plenty, and a full pull of each is seconds.
# Both jobs no-op when Intacct Settings is disabled.
# Intacct posts FIRST: on_submit runs inside ERPNext's submit transaction, so a rejection
# raises and the ERPNext document does not stand. Gated by "Post Stock Movements" on
# Intacct Settings — a site syncs masters long before it is ready to post.
doc_events = {
	"Stock Entry": {
		# Material Receipt and Material Issue are refused: Fuse posts movements, not
		# general adjustments. On-hand corrections go through Intacct's Cycle Count.
		"validate": [
			"fuse_manufacturing.postings.block_stock_adjustment",
			# A switched-off module refuses its own movements. Permissions cannot separate
			# them: all three raise a Stock Entry and only the purpose tells them apart.
			"fuse_manufacturing.postings.block_inactive_module",
		],
		"on_submit": "fuse_manufacturing.postings.on_stock_entry_submit",
		"on_cancel": "fuse_manufacturing.postings.on_stock_entry_cancel",
	},
	# Goods ARE received here, as of 2026-08-18. The receipt posts to Intacct as a PO
	# Receiver converted from the mirrored order, so the delivery is recorded once and
	# both systems see the same stock. The earlier blanket refusal was removed together
	# with the posting that replaces it — never one without the other, because a receipt
	# that submits without posting adds stock Intacct never saw.
	"Purchase Receipt": {
		"validate": "fuse_manufacturing.postings.block_inactive_receiving",
		"on_submit": "fuse_manufacturing.postings.on_purchase_receipt_submit",
		"on_cancel": "fuse_manufacturing.postings.on_purchase_receipt_cancel",
	},
	# Subcontracting is NOT receiving and has no posting behind it, so it stays refused.
	# Removing this alongside the block above would have opened a second door onto the
	# same divergence.
	"Subcontracting Receipt": {
		"validate": "fuse_manufacturing.postings.block_goods_receipt",
	},
	# Same divergence by the other door: a Purchase Invoice with "Update Stock" ticked
	# receives goods without a Purchase Receipt ever existing. The invoice is allowed; only
	# its ability to move stock is not.
	"Purchase Invoice": {
		"validate": "fuse_manufacturing.postings.block_stock_updating_invoice",
	},
}

scheduler_events = {
	"hourly_long": [
		"fuse_manufacturing.masters.scheduled_item_sync",
		"fuse_manufacturing.masters.scheduled_order_sync",
	],
	"daily_long": [
		"fuse_manufacturing.masters.scheduled_config_sync",
	],
}
