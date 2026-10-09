// BOMs are Intacct kits on a site configured that way, so the New button should not be
// there to press. The server refuses the insert regardless — this is so nobody meets that
// refusal by accident and thinks the system is broken.
//
// The answer comes from the server on frappe.boot (boot.py). Reading Intacct Settings from
// here needs a permission most logins do not have, and Frappe showed the refusal as an
// error on every BOM list and form before any catch could hide it.

function fuse_boms_locked(then) {
	then(!!frappe.boot.fuse_boms_from_intacct);
}

frappe.ui.form.on("BOM", {
	onload: function (frm) {
		fuse_boms_locked(function (locked) {
			if (!locked) return;

			// A mirrored BOM is still readable and still submittable by the sync; what goes
			// is the ability to start a new one from here.
			frm.page.clear_primary_action();
			frm.page.remove_inner_button && frm.page.remove_inner_button("New BOM");

			if (frm.is_new()) {
				frappe.msgprint({
					title: __("BOMs come from Intacct"),
					message: __(
						"Recipes are Intacct kits on this site and are brought across by the kit sync. " +
						"Add or change the kit in Intacct instead."
					),
					indicator: "orange",
				});
			}
		});
	},
});

// The list view's own Add button. Merged into whatever settings already exist rather than
// assigned over them — replacing frappe.listview_settings wholesale wipes indicators and
// formatters other code has set (CoWork_Helper gotcha, 2026-08-06).
frappe.listview_settings = frappe.listview_settings || {};
var fuse_bom_prev_onload = (frappe.listview_settings["BOM"] || {}).onload;
frappe.listview_settings["BOM"] = Object.assign({}, frappe.listview_settings["BOM"], {
	onload: function (listview) {
		if (fuse_bom_prev_onload) fuse_bom_prev_onload(listview);

		fuse_boms_locked(function (locked) {
			if (!locked) return;
			listview.page.clear_primary_action();
		});
	},
});
