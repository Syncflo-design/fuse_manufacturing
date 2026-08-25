// Fuse Stock Transfer — the desk form.
//
// Modelled on the Stock Transfer screen proven at Ardmore: a from, a to, and a short list
// of items. Everything here is about keeping that list honest — you can only pick items
// the source warehouse actually holds, you see what is on hand as you pick, and the bin
// and lot columns only appear for stock Intacct tracks that way.

const METHODS = "fuse_manufacturing.fuse_manufacturing.doctype.fuse_stock_transfer.fuse_stock_transfer";

frappe.ui.form.on("Fuse Stock Transfer", {
	setup(frm) {
		// Items are offered from what the source warehouse holds, not from the item master.
		// Hunting through things that are not there is how a transfer gets raised for stock
		// that was never in that warehouse.
		frm.set_query("item", "items", () => {
			// An alert, not a throw. Opening a picker is not a mistake worth an error
			// dialog — the list is simply empty until there is a warehouse to draw it from.
			if (!frm.doc.source_warehouse) {
				frappe.show_alert({
					message: __("Choose the warehouse the stock is coming from first."),
					indicator: "orange",
				});
			}
			return {
				query: `${METHODS}.items_in_warehouse`,
				filters: { warehouse: frm.doc.source_warehouse },
			};
		});

		frm.set_query("source_bin", "items", () => bin_query(frm.doc.source_warehouse));
		frm.set_query("target_bin", "items", () => bin_query(frm.doc.target_warehouse));

		frm.set_query("source_warehouse", () => warehouse_query(frm));
		frm.set_query("target_warehouse", () => warehouse_query(frm));
	},

	refresh(frm) {
		render_banner(frm);
		toggle_tracking_columns(frm);

		if (frm.doc.docstatus === 0) {
			add_scan_button(frm);
		}

		if (frm.doc.docstatus === 1 && frm.doc.stock_entry) {
			frm.add_custom_button(__("Stock Entry"), () =>
				frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry)
			);
		}
	},

	source_warehouse(frm) {
		// The list of items was drawn from the old warehouse, so it no longer means
		// anything. Clearing it silently would look like a glitch, so say so.
		clear_lines_for_warehouse_change(frm, "source_bin");
	},

	target_warehouse(frm) {
		clear_lines_for_warehouse_change(frm, "target_bin");
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

frappe.ui.form.on("Fuse Stock Transfer Item", {
	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item) {
			return;
		}
		show_on_hand(frm, row);
		toggle_tracking_columns(frm);
	},

	items_remove(frm) {
		toggle_tracking_columns(frm);
	},
});

function warehouse_query(frm) {
	return {
		filters: {
			company: frm.doc.company,
			is_group: 0,
		},
	};
}

function bin_query(warehouse) {
	// No warehouse yet means no bin can be right, so offer nothing rather than the whole
	// bin list of every warehouse.
	return {
		filters: {
			warehouse: warehouse || "__none__",
			status: "active",
		},
	};
}

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
	// shipped in the app bundle has to be cache-busted on every change — which is exactly
	// how a layout change once shipped and did not appear.
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
				${__("Move stock between warehouses")}
			</div>
			<div style="color: var(--text-muted); font-size: var(--text-sm, 12px);">
				${__("Pick where it is coming from and going to, then add what is moving. Submitting posts the movement to Intacct.")}
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
	toggle_tracking_columns(frm);
}

function show_on_hand(frm, row) {
	frappe.call({
		method: `${METHODS}.stock_on_hand`,
		args: { item_code: row.item, warehouse: frm.doc.source_warehouse },
		callback: ({ message }) => {
			frappe.show_alert({
				message: __("{0}: {1} on hand in {2}", [row.item, message || 0, frm.doc.source_warehouse]),
				indicator: message > 0 ? "blue" : "red",
			});
		},
	});
}

function clear_lines_for_warehouse_change(frm, bin_field) {
	const lines = frm.doc.items || [];
	if (!lines.length) {
		return;
	}

	// Only the bins are wrong. The items themselves may still be fine, and throwing away
	// somebody's typed list to re-clear a column they can see is worse than telling them.
	let cleared = 0;
	lines.forEach((row) => {
		if (row[bin_field]) {
			frappe.model.set_value(row.doctype, row.name, bin_field, null);
			cleared += 1;
		}
	});

	if (cleared) {
		frappe.show_alert({
			message: __("Cleared {0} bin(s) — they belonged to the old warehouse.", [cleared]),
			indicator: "orange",
		});
	}
	frm.refresh_field("items");
}

function toggle_tracking_columns(frm) {
	const grid = frm.fields_dict.items?.grid;
	if (!grid) {
		return;
	}

	const items = (frm.doc.items || []).map((row) => row.item).filter(Boolean);
	if (!items.length) {
		set_columns(grid, { bin: false, lot: false });
		return;
	}

	frappe.call({
		method: `${METHODS}.tracking`,
		args: { items: [...new Set(items)] },
		callback: ({ message }) => {
			const tracked = Object.values(message || {});
			set_columns(grid, {
				bin: tracked.some((row) => row.bin),
				lot: tracked.some((row) => row.lot),
			});
		},
	});
}

function set_columns(grid, show) {
	// A column nobody can fill is a column everyone asks about, so bins and lots stay out
	// of the way until something on the document actually needs them.
	grid.update_docfield_property("source_bin", "hidden", show.bin ? 0 : 1);
	grid.update_docfield_property("target_bin", "hidden", show.bin ? 0 : 1);
	grid.update_docfield_property("lot", "hidden", show.lot ? 0 : 1);
	grid.refresh();
}
