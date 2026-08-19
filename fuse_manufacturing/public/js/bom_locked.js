// BOMs are Intacct kits on a site configured that way, so the New button should not be
// there to press. The server refuses the insert regardless — this is so nobody meets that
// refusal by accident and thinks the system is broken.
//
// The setting is read once and cached on frappe.boot, because both the form and the list
// need it and neither should cost a round trip on every render.

function fuse_boms_locked(then) {
	if (frappe.boot.fuse_boms_from_intacct !== undefined) {
		then(frappe.boot.fuse_boms_from_intacct);
		return;
	}
	frappe.db
		.get_single_value("Intacct Settings", "boms_from_intacct")
		.then(function (value) {
			frappe.boot.fuse_boms_from_intacct = !!value;
			then(frappe.boot.fuse_boms_from_intacct);
		})
		.catch(function () {
			// No settings, or no permission to read them: leave ERPNext as it is rather
			// than hiding a button on a guess.
			frappe.boot.fuse_boms_from_intacct = false;
			then(false);
		});
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
