// Fuse Bin Transfer — the desk form.
//
// The warehouse transfer's smaller sibling: one warehouse, two bins. The banner says out
// loud what the screen cannot check, because nothing on either side knows what a bin
// holds and a screen that stayed quiet about it would imply it had looked.

const METHODS = "fuse_manufacturing.fuse_manufacturing.doctype.fuse_bin_transfer.fuse_bin_transfer";

frappe.ui.form.on("Fuse Bin Transfer", {
	setup(frm) {
		frm.set_query("item", "items", () => {
			// An alert, not a throw. Opening a picker is not a mistake worth an error
			// dialog — the list is simply empty until there is a warehouse to draw it from.
			if (!frm.doc.warehouse) {
				frappe.show_alert({
					message: __("Choose the warehouse first."),
					indicator: "orange",
				});
			}
			return {
				query: `${METHODS}.items_in_warehouse`,
				filters: { warehouse: frm.doc.warehouse },
			};
		});

		// Both bins come from the same warehouse. That is the whole point of the document,
		// and filtering both the same way is what makes it impossible to state otherwise.
		const bins = () => ({
			filters: { warehouse: frm.doc.warehouse || "__none__", status: "active" },
		});
		frm.set_query("source_bin", bins);
		frm.set_query("target_bin", bins);

		frm.set_query("warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
	},

	refresh(frm) {
		render_banner(frm);
		toggle_lot_column(frm);

		if (frm.doc.docstatus === 0) {
			add_scan_button(frm);
		}
	},

	warehouse(frm) {
		// The bins belonged to the old warehouse and the items were drawn from its stock.
		// Clearing silently would look like a glitch, so say what went and why.
		let cleared = 0;
		["source_bin", "target_bin"].forEach((field) => {
			if (frm.doc[field]) {
				frm.set_value(field, null);
				cleared += 1;
			}
		});

		if (cleared) {
			frappe.show_alert({
				message: __("Cleared the bins — they belonged to the old warehouse."),
				indicator: "orange",
			});
		}
	},

	scan_barcode(frm) {
		const code = (frm.doc.scan_barcode || "").trim();
		if (!code) {
			return;
		}

		frappe.call({
			method: `${METHODS}.item_from_barcode`,
			args: { barcode: code },
			callback: ({ message }) => {
				frm.set_value("scan_barcode", "");
				if (!message || !message.found) {
					frappe.show_alert({
						message: __("Not an item: {0}", [message?.label || code]),
						indicator: "orange",
					});
					return;
				}
				add_scanned_item(frm, message);
			},
		});
	},
});

frappe.ui.form.on("Fuse Bin Transfer Item", {
	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item) {
			return;
		}
		show_on_hand(frm, row);
		toggle_lot_column(frm);
	},

	items_remove(frm) {
		toggle_lot_column(frm);
	},
});

function render_banner(frm) {
	const wrapper = frm.fields_dict.route_section?.$wrapper;
	if (!wrapper) {
		return;
	}

	frm.$fuse_banner?.remove();
	if (frm.doc.docstatus !== 0) {
		return;
	}

	// Styled inline rather than from a stylesheet. It is one element, and a stylesheet
	// shipped in the app bundle has to be cache-busted on every change.
	frm.$fuse_banner = $(`
		<div style="
			border-left: 3px solid var(--primary, #2490ef);
			background: var(--fg-color, #fff);
			padding: 10px 14px;
			margin: 0 0 14px 0;
			border-radius: var(--border-radius-md, 6px);
			box-shadow: var(--card-shadow, none);
		">
			<div style="font-weight: 600; color: var(--text-color); margin-bottom: 2px;">
				${__("Move stock between bins in one warehouse")}
			</div>
			<div style="color: var(--text-muted); font-size: var(--text-sm, 12px);">
				${__("The warehouse total does not change, so this is recorded here and posted straight to Intacct. Quantities shown are for the whole warehouse — neither system tracks what is in a bin, so check the shelf.")}
			</div>
		</div>
	`).insertBefore(wrapper);
}

function add_scan_button(frm) {
	const scanning = frm.$fuse_scanning === true;

	frm.add_custom_button(scanning ? __("Done Scanning") : __("Scan Barcode"), () => {
		frm.$fuse_scanning = !scanning;
		frm.set_df_property("scan_barcode", "hidden", scanning ? 1 : 0);
		frm.refresh_field("scan_barcode");

		if (!scanning) {
			// Focus goes to the field so a handheld scanner's keystrokes land somewhere
			// useful without anyone having to click first.
			setTimeout(() => frm.fields_dict.scan_barcode?.$input?.focus(), 100);
		}
		frm.refresh();
	});
}

function add_scanned_item(frm, found) {
	const existing = (frm.doc.items || []).find((row) => row.item === found.item_code);

	if (existing) {
		frappe.model.set_value(existing.doctype, existing.name, "quantity", (existing.quantity || 0) + 1);
		frappe.show_alert({
			message: __("{0} — now {1}", [found.item_code, existing.quantity + 1]),
			indicator: "green",
		});
	} else {
		const row = frm.add_child("items", { item: found.item_code, quantity: 1 });
		frappe.model.set_value(row.doctype, row.name, "item", found.item_code);
		frappe.show_alert({ message: __("Added {0}", [found.item_code]), indicator: "green" });
	}

	frm.refresh_field("items");
	toggle_lot_column(frm);
}

function show_on_hand(frm, row) {
	frappe.call({
		method: `${METHODS}.stock_on_hand`,
		args: { item_code: row.item, warehouse: frm.doc.warehouse },
		callback: ({ message }) => {
			frappe.show_alert({
				message: __("{0}: {1} in {2}, across all bins", [row.item, message || 0, frm.doc.warehouse]),
				indicator: message > 0 ? "blue" : "red",
			});
		},
	});
}

function toggle_lot_column(frm) {
	const grid = frm.fields_dict.items?.grid;
	if (!grid) {
		return;
	}

	const items = (frm.doc.items || []).map((row) => row.item).filter(Boolean);
	if (!items.length) {
		set_lot_column(grid, false);
		return;
	}

	frappe.call({
		method: `${METHODS}.tracking`,
		args: { items: [...new Set(items)] },
		callback: ({ message }) => {
			set_lot_column(grid, Object.values(message || {}).some((row) => row.lot));
		},
	});
}

function set_lot_column(grid, show) {
	// A column nobody can fill is a column everyone asks about, so it stays out of the way
	// until something on the document is actually lot tracked.
	grid.update_docfield_property("lot", "hidden", show ? 0 : 1);
	grid.refresh();
}
