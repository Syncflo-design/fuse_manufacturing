app_name        = "fuse_manufacturing"
app_title       = "Fuse Manufacturing"
app_publisher   = "Syncflo"
app_description = "Sage Intacct integration for ERPNext — masters in, stock postings out."
app_email       = "ops@syncflo.co.za"
app_license     = "MIT"

# The Intacct connection — gateway, credentials, request log and the module switch table —
# lives in fuse_core. Declared here so a bench cannot end up with this app and not that
# one, and so migrate runs core first: Intacct Settings has to belong to core before this
# app's custom fields are added to it.
required_apps = ["fuse_core"]

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
# Client scripts shipped with the app rather than typed into the site, so they survive a
# rebuild. Both point at the same file: it defines the form behaviour and the list
# behaviour, and keeping them together means the two cannot drift.
# The inspection dialog, desk-wide. Four screens call it — receiving and picking at a desk
# and on a phone, and a production run on the floor — and asking the same question four
# different ways would produce four different records.
app_include_js = "/assets/fuse_manufacturing/js/fuse_quality.js"

doctype_js = {"BOM": "public/js/bom_locked.js"}
doctype_list_js = {"BOM": "public/js/bom_locked.js"}

doc_events = {
	"Stock Entry": {
		# Material Receipt and Material Issue are refused: Fuse posts movements, not
		# general adjustments. On-hand corrections go through Intacct's Cycle Count.
		"validate": [
			"fuse_manufacturing.postings.block_stock_adjustment",
			# A switched-off module refuses its own movements. Permissions cannot separate
			# them: all three raise a Stock Entry and only the purpose tells them apart.
			"fuse_manufacturing.postings.block_inactive_module",
			# 8.5.1: a batch that has not passed its own check does not move on.
			"fuse_manufacturing.quality.check_inspections",
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
		"validate": [
			"fuse_manufacturing.postings.block_inactive_receiving",
			# 8.4: goods from a supplier are accepted only once they have been checked.
			"fuse_manufacturing.quality.check_inspections",
		],
		"on_submit": "fuse_manufacturing.postings.on_purchase_receipt_submit",
		"on_cancel": "fuse_manufacturing.postings.on_purchase_receipt_cancel",
	},
	# Goods OUT. A delivery posts a shipper, which relieves quantity in Intacct and nothing
	# else — the invoice is raised there against it. Same contract as receiving: Intacct
	# first, and a rejection rolls the delivery back.
	"Delivery Note": {
		"validate": [
			"fuse_manufacturing.postings.block_inactive_picking",
			# 8.6: nothing reaches a customer without a passing, authorised inspection.
			"fuse_manufacturing.quality.check_inspections",
		],
		"on_submit": "fuse_manufacturing.postings.on_delivery_note_submit",
		"on_cancel": "fuse_manufacturing.postings.on_delivery_note_cancel",
	},
	# The inspection itself. 7.1.5.2 — the instrument has to have been in calibration on the
	# day the reading was taken; 8.6 — an outgoing result has to name who authorised the
	# release. Both are checked before the record can be saved, because a quality record
	# that can be fixed up afterwards is not a record.
	"Quality Inspection": {
		"validate": [
			"fuse_manufacturing.quality.block_uncalibrated_instrument",
			"fuse_manufacturing.quality.require_release_authority",
		],
	},
	# Recipes are Intacct kits on a site configured that way, so a BOM built by hand is a
	# second recipe Intacct has never heard of. Refused at insert; the New button is also
	# hidden, so nobody meets this message by accident.
	"BOM": {
		"before_insert": "fuse_manufacturing.postings.block_bom_creation",
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

# This app's own switches, handed to core, which owns the table they live in. Core knows
# there are switches; it does not know what Receiving is.
fuse_modules = ["fuse_manufacturing.modules.get_modules"]

# The Intacct processes this app posts. Core owns the Transactions table on Intacct
# Settings and the picker behind it; what needs mapping belongs to the app that posts
# it, so the table grows as apps are added without core learning what a goods receipt
# is.
fuse_processes = ["fuse_manufacturing.transactions.get_processes"]

# The user guides this app ships, for the Training page. They travel with the app so a
# new instance is never installed without help — the old way was an upload per site,
# and a site nobody uploaded to had an empty Training page.
fuse_guides = ["fuse_manufacturing.guides.get_guides"]

# The home page tiles this app owns. Only one, and only when a setting makes it differ
# from the theme's own: see tiles.py.
fuse_tiles = ["fuse_manufacturing.tiles.get_tiles"]

# What this app does when a switch is toggled: withdraw or restore the doctypes behind it.
# Core announces the change — it cannot call this app directly, and must not know it is
# installed. Without this, turning Receiving off would take the tile away and leave the
# Purchase Receipt reachable until the next migrate.
fuse_modules_changed = ["fuse_manufacturing.install._apply_role_permissions"]
