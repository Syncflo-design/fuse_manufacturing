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
scheduler_events = {
	"hourly_long": [
		"fuse_manufacturing.masters.scheduled_item_sync",
	],
	"daily_long": [
		"fuse_manufacturing.masters.scheduled_config_sync",
	],
}
