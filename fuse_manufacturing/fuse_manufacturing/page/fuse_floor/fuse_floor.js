// Fuse — shop floor screens for a phone or tablet.
//
// The desk forms stay exactly as they are; this is a second front door onto the
// same movements. Every submit goes through fuse_manufacturing/floor.py, which
// builds an ordinary Stock Entry — so Intacct still posts first and a rejection
// still rolls the movement back.
//
// Mounted inside page.body (a jQuery object in v16, per CoWork_Helper gotcha
// 2026-05-10-frappe-v16-page-api-drift). HTML is assembled as string arrays
// joined with "\n" — the page-bundle rule from nest_crm_mobile.

frappe.pages['fuse-floor'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Shop Floor',
		single_column: true
	});

	var BUILD_MARKER = 'v0.6.0-2026-08-18-receiving';
	console.log('Fuse Shop Floor loaded:', BUILD_MARKER);

	if (!document.getElementById('fuse-floor-stylesheet')) {
		var link = document.createElement('link');
		link.id = 'fuse-floor-stylesheet';
		link.rel = 'stylesheet';
		link.href = '/assets/fuse_manufacturing/css/fuse_floor.css?v=' + encodeURIComponent(BUILD_MARKER);
		document.head.appendChild(link);
	}

	wrapper.fuseFloor = window.fuseFloor = new FuseFloor(page);
};

frappe.pages['fuse-floor'].on_page_show = function (wrapper) {
	if (!wrapper.fuseFloor) return;
	wrapper.fuseFloor.collapse_sidebar();
	wrapper.fuseFloor.reload_context();
};

// ---------------------------------------------------------------------------

var FF_WIP = 'Material Transfer for Manufacture';
var FF_MOVE = 'Material Transfer';

// What the operator picked last, so the second batch of the shift is three taps
// instead of six. Per purpose — the store you issue from is rarely the warehouse
// you move between.
function ff_remembered(purpose, side) {
	try {
		return localStorage.getItem('fuse_floor:' + purpose + ':' + side) || '';
	} catch (e) {
		return '';
	}
}

function ff_remember(purpose, side, value) {
	try {
		localStorage.setItem('fuse_floor:' + purpose + ':' + side, value || '');
	} catch (e) {
		// A locked-down browser is not a reason to stop working.
	}
}

function ff_escape(value) {
	return frappe.utils.escape_html(value == null ? '' : String(value));
}

// Quantities are shown as the operator would say them: 25, not 25.000.
function ff_qty(value) {
	var number = flt(value);
	return String(parseFloat(number.toFixed(4)));
}

// Inline SVG, one stroke weight, one visual language (Lucide). Not emoji —
// emoji render differently on every Android skin, cannot take a colour from the
// stylesheet, and would be read aloud by a screen reader as their own name.
//
// Every icon here sits beside a text label, so none of them needs a label of its
// own; they are marked aria-hidden and the text carries the meaning.
var FF_ICONS = {
	back: 'M19 12H5M12 19l-7-7 7-7',
	scan: 'M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10',
	orders: 'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM8 11h8M8 15h5',
	wip: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM3.27 6.96L12 12.01l8.73-5.05M12 22.08V12',
	transfer: 'M8 3L4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4',
	tick: 'M20 6L9 17l-5-5',
	remove: 'M18 6L6 18M6 6l12 12',
	warn: 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01',
	receive: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'
};

function ff_icon(name) {
	return (
		'<svg class="ff-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
		'<path d="' + FF_ICONS[name] + '"></path></svg>'
	);
}

// Recording a run is three moves — choose the order, say how much, confirm what
// went in — and the middle one happens in a dialog. Without a marker the operator
// has no idea whether the screen in front of them is the last one.
function ff_step(current, total, label) {
	return [
		'<div class="ff-step">',
		'  <span>Step ' + current + ' of ' + total + ' · ' + ff_escape(label) + '</span>',
		'  <span class="ff-step-bar">',
		'    <span class="ff-step-fill" style="width: ' + Math.round((current / total) * 100) + '%"></span>',
		'  </span>',
		'</div>'
	].join('\n');
}

// ---------------------------------------------------------------------------

function FuseFloor(page) {
	this.page = page;
	this.context = null;
	this.$root = $('<div class="ff-root"></div>').appendTo(page.body);
	this.collapse_sidebar();
	this.reload_context();
}

// Get the desk sidebar out of the way on arrival.
//
// Clicks Frappe's OWN toggle rather than hiding the element, so the operator can
// click it again to bring the sidebar back, and so nothing is left in a state the
// desk does not know about. Only ever collapses, never force-expands — a tablet
// user who deliberately opened it keeps it open on the next screen.
//
// The selector list is defensive across v15/v16 desk markup, and the poll covers
// the sidebar rendering after the page does. Borrowed from nest_home.
FuseFloor.prototype.collapse_sidebar = function () {
	var tries = 0;
	var timer = setInterval(function () {
		tries++;
		var $toggle = $('.sidebar-toggle-btn, .collapse-sidebar, .sidebar-toggle')
			.filter(':visible')
			.first();

		if ($toggle.length) {
			var $sidebar = $('.body-sidebar-container, .desk-sidebar').first();
			var collapsed = $('body').is('.sidebar-collapsed') ||
				$sidebar.is('.sidebar-collapsed, .collapsed');
			if (!collapsed) $toggle.get(0).click();
			clearInterval(timer);
		} else if (tries > 15) {
			clearInterval(timer);
		}
	}, 120);
};

FuseFloor.prototype.reload_context = function () {
	var self = this;
	frappe.call({
		method: 'fuse_manufacturing.floor.bootstrap',
		callback: function (r) {
			if (!r || !r.message) return;
			self.context = r.message;
			self.home();
		}
	});
};

// The banner every screen carries. Posting switched off is not a detail — a shift
// recorded while it is off moves stock here and nowhere else.
FuseFloor.prototype.warning_html = function () {
	if (!this.context || this.context.posting_on) return '';
	return [
		'<div class="ff-warn" role="alert">',
		ff_icon('warn'),
		'  <span>Posting to Intacct is switched off. Nothing recorded here will reach the books.</span>',
		'</div>'
	].join('\n');
};

FuseFloor.prototype.render = function (html) {
	this.$root.html(this.warning_html() + html);
	this.$root.scrollTop(0);
};

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

function ff_tile(go, icon, title, blurb) {
	return [
		'  <button class="ff-tile" data-go="' + go + '">',
		'    <span class="ff-tile-mark">' + ff_icon(icon) + '</span>',
		'    <span class="ff-tile-text">',
		'      <span class="ff-tile-title">' + ff_escape(title) + '</span>',
		'      <span class="ff-tile-sub">' + ff_escape(blurb) + '</span>',
		'    </span>',
		'  </button>'
	].join('\n');
}

FuseFloor.prototype.home = function () {
	var self = this;
	this.basket = [];

	this.render([
		'<div class="ff-menu">',
		ff_tile('run', 'orders', 'Works Orders', 'Record what you made against a works order'),
		ff_tile('wip', 'wip', 'Issue to WIP', 'Move components from a store onto the floor'),
		ff_tile('move', 'transfer', 'Item Transfer', 'Warehouse to warehouse'),
		ff_tile('receive', 'receive', 'Receiving', 'Book a delivery in against a purchase order'),
		'</div>'
	].join('\n'));

	this.$root.find('[data-go]').on('click', function () {
		var go = $(this).data('go');
		if (go === 'run') self.work_orders();
		else if (go === 'wip') self.transfer(FF_WIP);
		else if (go === 'receive') self.receiving();
		else self.transfer(FF_MOVE);
	});
};

FuseFloor.prototype.header_html = function (title, subtitle) {
	return [
		'<div class="ff-head">',
		'  <button class="ff-back" data-back="1" aria-label="Back">' + ff_icon('back') + '</button>',
		'  <div class="ff-head-text">',
		'    <div class="ff-title">' + ff_escape(title) + '</div>',
		'    <div class="ff-sub">' + ff_escape(subtitle || '') + '</div>',
		'  </div>',
		'</div>'
	].join('\n');
};

FuseFloor.prototype.bind_back = function (handler) {
	var self = this;
	this.$root.find('[data-back]').on('click', function () {
		if (handler) handler.call(self);
		else self.home();
	});
};

// ---------------------------------------------------------------------------
// Transfer — issue to WIP, and plain warehouse moves. One flow, two purposes.
// ---------------------------------------------------------------------------

FuseFloor.prototype.transfer = function (purpose) {
	var self = this;
	var wip = purpose === FF_WIP;
	this.basket = [];
	this.purpose = purpose;
	this.source = ff_remembered(purpose, 'from');
	this.target = ff_remembered(purpose, 'to');

	function options(selected) {
		var html = ['<option value="">Choose…</option>'];
		(self.context.warehouses || []).forEach(function (w) {
			html.push(
				'<option value="' + ff_escape(w.name) + '"' +
				(w.name === selected ? ' selected' : '') + '>' +
				ff_escape(w.name) + '</option>'
			);
		});
		return html.join('\n');
	}

	this.render([
		this.header_html(wip ? 'Issue to WIP' : 'Item Transfer',
			wip ? 'Components onto the floor' : 'Warehouse to warehouse'),
		'<div class="ff-pair">',
		'  <label class="ff-label">From',
		'    <select class="ff-select" data-side="from">' + options(this.source) + '</select>',
		'  </label>',
		'  <label class="ff-label">To',
		'    <select class="ff-select" data-side="to">' + options(this.target) + '</select>',
		'  </label>',
		'</div>',
		'<div class="ff-scan">',
		ff_icon('scan'),
		'  <input class="ff-input" data-scan="1" placeholder="Scan or type an item" ',
		'         autocomplete="off" autocapitalize="off" spellcheck="false">',
		'</div>',
		'<div class="ff-results" data-results="1"></div>',
		'<div class="ff-basket" data-basket="1"></div>',
		'<div class="ff-actions">',
		'  <button class="ff-submit" data-submit="1" disabled>Record</button>',
		'</div>'
	].join('\n'));

	this.bind_back();

	this.$root.find('[data-side]').on('change', function () {
		var side = $(this).data('side');
		var value = $(this).val();
		if (side === 'from') self.source = value;
		else self.target = value;
		ff_remember(purpose, side, value);
	});

	this.$root.find('[data-scan]').on('keydown', function (e) {
		// Hardware scanners type the code and press Enter. So do people.
		if (e.which !== 13) return;
		e.preventDefault();
		self.search($(this).val());
	});

	this.paint_basket();
	this.focus_scan();
};

FuseFloor.prototype.focus_scan = function () {
	var $scan = this.$root.find('[data-scan]');
	if ($scan.length) $scan.val('').focus();
};

FuseFloor.prototype.search = function (term) {
	var self = this;
	term = (term || '').trim();
	if (!term) return;

	if (!this.source) {
		frappe.msgprint('Choose the warehouse the stock is coming from first.');
		return;
	}

	frappe.call({
		method: 'fuse_manufacturing.floor.find_item',
		args: { term: term, warehouse: this.source },
		freeze: true,
		freeze_message: 'Looking up ' + term,
		callback: function (r) {
			var matches = (r && r.message) || [];
			if (!matches.length) {
				self.$root.find('[data-results]').html(
					'<div class="ff-empty">Nothing matches “' + ff_escape(term) + '”.</div>'
				);
				self.focus_scan();
				return;
			}
			// One match is the scanner's normal case — go straight to the quantity
			// rather than making someone confirm what they just scanned.
			if (matches.length === 1) {
				self.ask_qty(matches[0]);
				return;
			}
			self.paint_matches(matches);
		}
	});
};

FuseFloor.prototype.paint_matches = function (matches) {
	var self = this;
	var html = ['<div class="ff-list">'];
	matches.forEach(function (m, index) {
		html.push(
			'<button class="ff-row" data-match="' + index + '">' +
			'  <span class="ff-row-main">' + ff_escape(m.item_code) + '</span>' +
			'  <span class="ff-row-sub">' + ff_escape(m.item_name || '') + '</span>' +
			'  <span class="ff-row-qty">' + ff_qty(m.actual_qty) + ' ' + ff_escape(m.stock_uom) + '</span>' +
			'</button>'
		);
	});
	html.push('</div>');

	this.$root.find('[data-results]').html(html.join('\n'));
	this.$root.find('[data-match]').on('click', function () {
		self.ask_qty(matches[$(this).data('match')]);
	});
};

FuseFloor.prototype.ask_qty = function (item) {
	var self = this;
	var dialog = new frappe.ui.Dialog({
		title: item.item_code,
		fields: [
			{
				fieldname: 'on_hand',
				fieldtype: 'HTML',
				options: [
					'<div class="ff-onhand">',
					ff_escape(item.item_name || ''),
					'<br><b>' + ff_qty(item.actual_qty) + ' ' + ff_escape(item.stock_uom) + '</b>',
					' in ' + ff_escape(self.source),
					'</div>'
				].join('')
			},
			{
				fieldname: 'qty',
				fieldtype: 'Float',
				label: 'Quantity (' + item.stock_uom + ')',
				reqd: 1
			}
		],
		primary_action_label: 'Add',
		primary_action: function (values) {
			if (flt(values.qty) <= 0) {
				frappe.msgprint('Enter how much is moving.');
				return;
			}
			dialog.hide();
			self.basket.push({
				item_code: item.item_code,
				item_name: item.item_name,
				stock_uom: item.stock_uom,
				qty: flt(values.qty)
			});
			self.$root.find('[data-results]').empty();
			self.paint_basket();
			self.focus_scan();
		}
	});
	dialog.show();
	// The keypad should be up and waiting — the operator already knows the number.
	setTimeout(function () {
		dialog.get_field('qty').$input.focus();
	}, 150);
};

FuseFloor.prototype.paint_basket = function () {
	var self = this;
	var $basket = this.$root.find('[data-basket]');
	var $submit = this.$root.find('[data-submit]');

	if (!this.basket.length) {
		$basket.html('<div class="ff-empty">Nothing added yet.</div>');
		$submit.prop('disabled', true).text('Record');
		return;
	}

	var html = ['<div class="ff-list ff-list-added">'];
	this.basket.forEach(function (row, index) {
		html.push(
			'<div class="ff-row ff-row-static">' +
			'  <span class="ff-row-main">' + ff_escape(row.item_code) + '</span>' +
			'  <span class="ff-row-sub">' + ff_escape(row.item_name || '') + '</span>' +
			'  <span class="ff-row-qty">' + ff_qty(row.qty) + ' ' + ff_escape(row.stock_uom) + '</span>' +
			'  <button class="ff-remove" data-remove="' + index + '" aria-label="Remove ' +
			ff_escape(row.item_code) + '">' + ff_icon('remove') + '</button>' +
			'</div>'
		);
	});
	html.push('</div>');
	$basket.html(html.join('\n'));

	$basket.find('[data-remove]').on('click', function () {
		self.basket.splice($(this).data('remove'), 1);
		self.paint_basket();
	});

	$submit
		.prop('disabled', false)
		.text('Record ' + this.basket.length + (this.basket.length === 1 ? ' line' : ' lines'))
		.off('click')
		.on('click', function () {
			self.submit_transfer();
		});
};

FuseFloor.prototype.submit_transfer = function () {
	var self = this;

	if (!this.source || !this.target) {
		frappe.msgprint('Choose both warehouses.');
		return;
	}
	if (this.source === this.target) {
		frappe.msgprint('From and to are the same warehouse.');
		return;
	}

	var rows = this.basket.map(function (row) {
		return {
			item_code: row.item_code,
			qty: row.qty,
			s_warehouse: self.source,
			t_warehouse: self.target
		};
	});

	frappe.call({
		method: 'fuse_manufacturing.floor.submit_transfer',
		args: { purpose: this.purpose, rows: JSON.stringify(rows) },
		freeze: true,
		freeze_message: 'Sending to Intacct…',
		callback: function (r) {
			if (!r || !r.message) return;
			self.done(r.message, 'Stock moved.');
		}
		// No error branch on purpose: a rejection raises server-side and Frappe shows
		// the reason — including Intacct's own words — in its own dialog. The screen
		// keeps the basket, so the operator fixes it and taps Record again.
	});
};

// ---------------------------------------------------------------------------
// Works Orders — recording production against one
// ---------------------------------------------------------------------------

FuseFloor.prototype.work_orders = function () {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.floor.open_work_orders',
		freeze: true,
		freeze_message: 'Loading works orders',
		callback: function (r) {
			var orders = (r && r.message) || [];

			self.render([
				self.header_html('Works Orders', 'Open orders'),
				ff_step(1, 3, 'Choose the order'),
				'<div class="ff-scan">',
				ff_icon('scan'),
				'  <input class="ff-input" data-scan="1" placeholder="Scan a works order, or filter" ',
				'         autocomplete="off" autocapitalize="off" spellcheck="false">',
				'</div>',
				'<div data-orders="1"></div>'
			].join('\n'));

			self.bind_back();
			self.paint_orders(orders, '');

			// A works order number is not a barcode in the Item Barcode sense — it is
			// the document's own name. Print it as Code-128 and the scanner simply
			// types it, so an exact match goes straight in and anything else filters
			// the list. No barcode table, no item lookup, nothing to configure.
			self.$root.find('[data-scan]').on('keydown', function (e) {
				if (e.which !== 13) return;
				e.preventDefault();

				var typed = ($(this).val() || '').trim();
				var hit = null;
				orders.forEach(function (wo) {
					if (wo.name.toLowerCase() === typed.toLowerCase()) hit = wo;
				});

				if (hit) {
					$(this).val('');
					self.ask_made(hit);
					return;
				}
				self.paint_orders(orders, typed);
			});

			self.$root.find('[data-scan]').on('input', function () {
				self.paint_orders(orders, ($(this).val() || '').trim());
			});
		}
	});
};

// The open orders, optionally narrowed. Matching is on the order number, the item
// code and the description, because an operator knows the compound by name far more
// often than by works order number.
FuseFloor.prototype.paint_orders = function (orders, filter) {
	var self = this;
	var needle = (filter || '').toLowerCase();

	var shown = orders.filter(function (wo) {
		if (!needle) return true;
		return [wo.name, wo.production_item, wo.item_name].some(function (field) {
			return (field || '').toLowerCase().indexOf(needle) !== -1;
		});
	});

	var html = [];
	if (!orders.length) {
		html.push('<div class="ff-empty">No works orders are open.</div>');
	} else if (!shown.length) {
		html.push('<div class="ff-empty">No open works order matches “' + ff_escape(filter) + '”.</div>');
	} else {
		html.push('<div class="ff-list">');
		shown.forEach(function (wo) {
			var left = flt(wo.qty) - flt(wo.produced_qty);
			html.push(
				'<button class="ff-row ff-row-wo" data-wo="' + ff_escape(wo.name) + '">' +
				'  <span class="ff-row-main">' + ff_escape(wo.production_item) + '</span>' +
				'  <span class="ff-row-sub">' + ff_escape(wo.item_name || '') + ' · ' + ff_escape(wo.name) + '</span>' +
				'  <span class="ff-row-qty">' + ff_qty(left) + ' ' + ff_escape(wo.stock_uom) + ' left</span>' +
				'</button>'
			);
		});
		html.push('</div>');
	}

	var $orders = this.$root.find('[data-orders]');
	$orders.html(html.join('\n'));
	$orders.find('[data-wo]').on('click', function () {
		var name = $(this).data('wo');
		orders.forEach(function (wo) {
			if (wo.name === name) self.ask_made(wo);
		});
	});
};

FuseFloor.prototype.ask_made = function (wo) {
	var self = this;
	var left = flt(wo.qty) - flt(wo.produced_qty);

	var dialog = new frappe.ui.Dialog({
		title: wo.production_item,
		fields: [
			{
				fieldname: 'ordered',
				fieldtype: 'HTML',
				options: [
					'<div class="ff-onhand">',
					ff_escape(wo.item_name || ''),
					'<br>Ordered <b>' + ff_qty(wo.qty) + '</b>, made <b>' + ff_qty(wo.produced_qty) + '</b>,',
					' <b>' + ff_qty(left) + ' ' + ff_escape(wo.stock_uom) + '</b> still to go.',
					'</div>'
				].join('')
			},
			{
				fieldname: 'qty',
				fieldtype: 'Float',
				label: 'How much did you actually make? (' + wo.stock_uom + ')',
				default: left,
				reqd: 1
			}
		],
		primary_action_label: 'Next',
		primary_action: function (values) {
			if (flt(values.qty) <= 0) {
				frappe.msgprint('Enter how much you made.');
				return;
			}
			dialog.hide();
			self.check_components(wo, flt(values.qty));
		}
	});
	dialog.show();
};

FuseFloor.prototype.check_components = function (wo, qty) {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.floor.work_order_lines',
		args: { work_order: wo.name, qty: qty },
		freeze: true,
		freeze_message: 'Working out the recipe',
		callback: function (r) {
			if (!r || !r.message) return;
			var consumed = r.message.consumed || [];
			var produced = r.message.produced;

			var html = [
				self.header_html('What went in?', wo.production_item + ' · ' + ff_qty(qty) + ' ' + wo.stock_uom),
				ff_step(3, 3, 'Confirm what went in'),
				'<div class="ff-note">',
				'  These are the recipe quantities. Change any that differed — the finished cost',
				'  is worked out from what actually went in.',
				'</div>',
				'<div class="ff-list ff-list-added">'
			];

			consumed.forEach(function (line, index) {
				html.push(
					'<div class="ff-row ff-row-static">' +
					'  <span class="ff-row-main">' + ff_escape(line.item_code) + '</span>' +
					'  <span class="ff-row-sub">' + ff_escape(line.item_name || '') + ' · from ' + ff_escape(line.s_warehouse || '') + '</span>' +
					'  <input class="ff-qty-input" type="number" inputmode="decimal" step="any" ' +
					'         data-line="' + index + '" value="' + ff_qty(line.qty) + '">' +
					'  <span class="ff-row-unit">' + ff_escape(line.uom) + '</span>' +
					'</div>'
				);
			});
			html.push('</div>');

			if (produced) {
				html.push(
					'<div class="ff-made">' + ff_icon('wip') + '<span>Making <b>' + ff_qty(produced.qty) + ' ' +
					ff_escape(produced.uom) + '</b> of ' + ff_escape(produced.item_code) +
					' into ' + ff_escape(produced.t_warehouse || '') + '</span></div>'
				);
			}

			html.push(
				'<div class="ff-actions">' +
				'  <button class="ff-submit" data-submit="1">Record the run</button>' +
				'</div>'
			);

			self.render(html.join('\n'));
			self.bind_back(function () {
				self.work_orders();
			});

			self.$root.find('[data-submit]').on('click', function () {
				var rows = [];
				self.$root.find('[data-line]').each(function () {
					var line = consumed[$(this).data('line')];
					var value = flt($(this).val());
					// A zero means it was not used. It is dropped, not sent — a zero
					// component cost is refused by Intacct on the reversal side too.
					if (value > 0) rows.push({ item_code: line.item_code, qty: value });
				});

				if (!rows.length) {
					frappe.msgprint('A run needs at least one component.');
					return;
				}

				frappe.call({
					method: 'fuse_manufacturing.floor.submit_manufacture',
					args: { work_order: wo.name, qty: qty, rows: JSON.stringify(rows) },
					freeze: true,
					freeze_message: 'Sending to Intacct…',
					callback: function (res) {
						if (!res || !res.message) return;
						self.done(res.message, 'Run recorded.');
					}
				});
			});
		}
	});
};

// ---------------------------------------------------------------------------

FuseFloor.prototype.done = function (result, message) {
	var self = this;

	this.render([
		'<div class="ff-done">',
		'  <div class="ff-tick">' + ff_icon('tick') + '</div>',
		'  <div class="ff-done-msg">' + ff_escape(message) + '</div>',
		'  <div class="ff-done-ref">' + ff_escape(result.stock_entry) + '</div>',
		result.intacct_key
			? '  <div class="ff-done-key">Intacct ' + ff_escape(result.intacct_key) + '</div>'
			: '',
		'</div>',
		'<div class="ff-actions">',
		'  <button class="ff-submit" data-again="1">Do another</button>',
		'  <button class="ff-secondary" data-open="1">Open the document</button>',
		'</div>'
	].join('\n'));

	this.$root.find('[data-again]').on('click', function () {
		self.home();
	});
	this.$root.find('[data-open]').on('click', function () {
		frappe.set_route('Form', 'Stock Entry', result.stock_entry);
	});
};


// ---------------------------------------------------------------------------
// Receiving — book a delivery in against a purchase order
//
// Orders are never created here; they are mirrored from Intacct. This records
// what turned up. Submitting posts a PO Receiver to Intacct first, so a rejection
// there means nothing is booked in here either.
// ---------------------------------------------------------------------------

FuseFloor.prototype.receiving = function (term) {
	var self = this;
	this.receipt = [];

	frappe.call({
		method: 'fuse_manufacturing.receiving.open_orders',
		args: { term: term || '' },
		freeze: true,
		freeze_message: 'Loading orders',
		callback: function (r) {
			var orders = (r && r.message) || [];

			var html = [
				self.header_html('Receiving', 'Deliveries against a purchase order'),
				ff_step(1, 3, 'Find the order'),
				'<div class="ff-scan">',
				ff_icon('scan'),
				'  <input class="ff-input" data-scan="1" placeholder="Scan or type an order number" ',
				'         autocomplete="off" autocapitalize="off" spellcheck="false" value="' + ff_escape(term || '') + '">',
				'</div>'
			];

			if (!orders.length) {
				html.push(
					'<div class="ff-empty">' +
					(term ? 'No open order matches “' + ff_escape(term) + '”.' : 'No orders are waiting for delivery.') +
					'</div>'
				);
			} else {
				html.push('<div class="ff-list">');
				orders.forEach(function (order) {
					html.push(
						'<button class="ff-row" data-order="' + ff_escape(order.name) + '">' +
						'  <span class="ff-row-main">' + ff_escape(order.intacct_po || order.custom_intacct_po_id || order.name) + '</span>' +
						'  <span class="ff-row-sub">' + ff_escape(order.supplier_name || order.supplier) + '</span>' +
						'  <span class="ff-row-qty">' + ff_qty(order.per_received) + '%<br>in</span>' +
						'</button>'
					);
				});
				html.push('</div>');
			}

			self.render(html.join('\n'));
			self.bind_back();

			// Searching the list and scanning the order number are the same action, so
			// they are the same box. Enter searches; an exact match opens straight away.
			self.$root.find('[data-scan]').on('keydown', function (e) {
				if (e.which !== 13) return;
				e.preventDefault();

				var typed = ($(this).val() || '').trim();
				var hit = null;
				orders.forEach(function (order) {
					var ours = (order.name || '').toLowerCase();
					var theirs = (order.custom_intacct_po_id || '').toLowerCase();
					if (ours === typed.toLowerCase() || theirs === typed.toLowerCase()) hit = order;
				});

				if (hit) {
					self.receive_order(hit.name);
					return;
				}
				self.receiving(typed);
			});

			self.$root.find('[data-order]').on('click', function () {
				self.receive_order($(this).data('order'));
			});
		}
	});
};

FuseFloor.prototype.receive_order = function (purchase_order) {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.receiving.order_lines',
		args: { purchase_order: purchase_order },
		freeze: true,
		freeze_message: 'Opening the order',
		callback: function (r) {
			if (!r || !r.message) return;
			self.order = r.message;
			self.receipt = [];
			self.paint_receiving();
		}
	});
};

FuseFloor.prototype.paint_receiving = function () {
	var self = this;
	var order = this.order;

	var html = [
		this.header_html('Receiving', (order.intacct_po || order.purchase_order) + ' · ' + (order.supplier_name || order.supplier)),
		ff_step(2, 3, 'Book the goods in'),
		'<div class="ff-scan">',
		ff_icon('scan'),
		'  <input class="ff-input" data-scan="1" placeholder="Scan an item on this order" ',
		'         autocomplete="off" autocapitalize="off" spellcheck="false">',
		'</div>',
		'<div class="ff-list">'
	];

	order.lines.forEach(function (line) {
		var booked = self.booked_for(line.purchase_order_item);
		var left = flt(line.outstanding_qty) - booked;
		html.push(
			'<button class="ff-row" data-line="' + ff_escape(line.purchase_order_item) + '">' +
			'  <span class="ff-row-main">' + ff_escape(line.item_code) + '</span>' +
			'  <span class="ff-row-sub">' + ff_escape(line.item_name || '') +
			(booked ? ' · <b>' + ff_qty(booked) + ' booked</b>' : '') + '</span>' +
			'  <span class="ff-row-qty">' + ff_qty(left) + '<br>' + ff_escape(line.uom) + '</span>' +
			'</button>'
		);
	});

	html.push('</div>');
	html.push(
		'<div class="ff-actions">',
		'  <button class="ff-submit" data-submit="1"' + (this.receipt.length ? '' : ' disabled') + '>' +
		(this.receipt.length
			? 'Finish ' + this.receipt.length + (this.receipt.length === 1 ? ' line' : ' lines')
			: 'Nothing booked yet') +
		'</button>',
		'</div>'
	);

	this.render(html.join('\n'));
	this.bind_back(function () {
		self.receiving();
	});

	this.$root.find('[data-line]').on('click', function () {
		self.ask_receive($(this).data('line'));
	});

	this.$root.find('[data-scan]').on('keydown', function (e) {
		if (e.which !== 13) return;
		e.preventDefault();
		self.scan_into_receipt($(this).val());
		$(this).val('');
	});

	this.$root.find('[data-submit]').on('click', function () {
		if (self.receipt.length) self.finish_receipt();
	});

	this.focus_scan();
};

// How much is already booked against an ordered line in this session.
FuseFloor.prototype.booked_for = function (po_item) {
	var total = 0;
	(this.receipt || []).forEach(function (row) {
		if (row.purchase_order_item === po_item) total += flt(row.qty) + flt(row.rejected_qty);
	});
	return total;
};

FuseFloor.prototype.line_by_id = function (po_item) {
	var found = null;
	this.order.lines.forEach(function (line) {
		if (line.purchase_order_item === po_item) found = line;
	});
	return found;
};

FuseFloor.prototype.scan_into_receipt = function (term) {
	var self = this;
	term = (term || '').trim();
	if (!term) return;

	frappe.call({
		method: 'fuse_manufacturing.receiving.scan',
		args: { purchase_order: this.order.purchase_order, term: term },
		freeze: true,
		freeze_message: 'Reading ' + term,
		callback: function (r) {
			var result = (r && r.message) || {};
			var scanned = result.scan || {};

			// Anything that is not an item is reported for what it was, rather than
			// as "not found" — scanning a pallet label at the wrong moment is a normal
			// mistake and the operator should be told what they actually scanned.
			if (scanned.type !== 'item') {
				frappe.msgprint(scanned.label || 'That is not an item on this order.');
				self.focus_scan();
				return;
			}

			if (!result.lines || !result.lines.length) {
				frappe.msgprint(result.message || 'That item is not on this order.');
				self.focus_scan();
				return;
			}

			// One ordered line is the normal case. Several means the same item was
			// ordered twice, and only the operator knows which delivery this is.
			if (result.lines.length === 1) {
				self.ask_receive(result.lines[0].name);
				return;
			}
			self.choose_line(result.lines);
		}
	});
};

FuseFloor.prototype.choose_line = function (lines) {
	var self = this;
	var dialog = new frappe.ui.Dialog({ title: 'Which line?' });
	var $body = $(dialog.body).empty();

	lines.forEach(function (line) {
		var $row = $(
			'<button type="button" class="ff-row ff-row-choice">' +
			'  <span class="ff-row-main"></span>' +
			'  <span class="ff-row-sub"></span>' +
			'</button>'
		);
		$row.find('.ff-row-main').text('Line ' + line.idx + ' · ' + line.item_code);
		$row.find('.ff-row-sub').text(
			ff_qty(line.outstanding_qty) + ' ' + (line.stock_uom || '') + ' outstanding · ' + (line.warehouse || '')
		);
		$row.on('click', function () {
			dialog.hide();
			self.ask_receive(line.name);
		});
		$body.append($row);
	});

	dialog.show();
};

FuseFloor.prototype.ask_receive = function (po_item) {
	var self = this;
	var line = this.line_by_id(po_item);
	if (!line) {
		frappe.msgprint('That line is not on this order.');
		return;
	}

	var booked = this.booked_for(po_item);
	var left = flt(line.outstanding_qty) - booked;

	var fields = [
		{
			fieldname: 'summary',
			fieldtype: 'HTML',
			options: [
				'<div class="ff-onhand">',
				ff_escape(line.item_name || ''),
				'<br>Ordered <b>' + ff_qty(line.ordered_qty) + '</b>,',
				' received <b>' + ff_qty(line.received_qty) + '</b>,',
				' <b>' + ff_qty(left) + ' ' + ff_escape(line.uom) + '</b> outstanding.',
				'</div>'
			].join('')
		},
		{
			fieldname: 'qty',
			fieldtype: 'Float',
			label: 'Accepted (' + line.uom + ')',
			default: left > 0 ? left : 0,
			reqd: 1
		},
		{
			fieldname: 'rejected_qty',
			fieldtype: 'Float',
			label: 'Rejected (' + line.uom + ')',
			default: 0,
			description: self.order.reject_warehouse
				? 'Goes to ' + self.order.reject_warehouse
				: 'No rejects warehouse is set, so a rejected quantity will be refused.'
		}
	];

	// Only where Intacct tracks lots on this item. Asking otherwise invites a number
	// that Intacct then rejects the whole receipt for.
	if (line.lot_tracked) {
		fields.push({
			fieldname: 'lot',
			fieldtype: 'Data',
			label: 'Lot number',
			reqd: 1
		});
	}

	var dialog = new frappe.ui.Dialog({
		title: line.item_code,
		fields: fields,
		primary_action_label: 'Book in',
		primary_action: function (values) {
			var accepted = flt(values.qty);
			var rejected = flt(values.rejected_qty);

			if (accepted <= 0 && rejected <= 0) {
				frappe.msgprint('Enter what arrived.');
				return;
			}
			if (rejected > 0 && !self.order.reject_warehouse) {
				frappe.msgprint('No receiving rejects warehouse is set, so rejected stock cannot be booked in.');
				return;
			}

			dialog.hide();
			self.receipt.push({
				purchase_order_item: po_item,
				item_code: line.item_code,
				qty: accepted,
				rejected_qty: rejected,
				warehouse: line.warehouse,
				lot: values.lot || null
			});
			self.paint_receiving();
		}
	});

	dialog.show();
	setTimeout(function () {
		dialog.get_field('qty').$input.focus().select();
	}, 150);
};

FuseFloor.prototype.finish_receipt = function (confirmed) {
	var self = this;

	var dialog = new frappe.ui.Dialog({
		title: 'Finish the delivery',
		fields: [
			{
				fieldname: 'supplier_delivery_note',
				fieldtype: 'Data',
				label: 'Supplier delivery note / invoice',
				description: 'The number on the paperwork. Carried to Intacct on the receiver.'
			},
			{
				fieldname: 'posting_date',
				fieldtype: 'Date',
				label: 'Received on',
				default: frappe.datetime.get_today(),
				reqd: 1
			}
		],
		primary_action_label: 'Record',
		primary_action: function (values) {
			dialog.hide();
			self.send_receipt(values, false);
		}
	});

	dialog.show();
};

FuseFloor.prototype.send_receipt = function (values, confirmed) {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.receiving.submit_receipt',
		args: {
			purchase_order: this.order.purchase_order,
			rows: JSON.stringify(this.receipt),
			supplier_delivery_note: values.supplier_delivery_note || '',
			posting_date: values.posting_date,
			confirm_over_receipt: confirmed ? 1 : 0
		},
		freeze: true,
		freeze_message: 'Sending to Intacct…',
		callback: function (r) {
			var result = (r && r.message) || {};

			// More arrived than was ordered. Nothing has been written — the operator
			// is told which line and by how much, and decides.
			if (result.confirm_required === 'over_receipt') {
				var lines = (result.over || []).map(function (row) {
					return row.item_code + ': ' + ff_qty(row.receiving_qty) +
						' against ' + ff_qty(row.outstanding_qty) + ' outstanding' +
						' (' + ff_qty(row.excess_qty) + ' over)';
				});
				frappe.confirm(
					'More is being booked in than this order expects:<br><br><b>' +
					lines.join('<br>') + '</b><br><br>Record it anyway?',
					function () {
						self.send_receipt(values, true);
					}
				);
				return;
			}

			if (!result.purchase_receipt) return;
			self.done(
				{ stock_entry: result.purchase_receipt, intacct_key: result.intacct_key },
				'Delivery booked in.'
			);
		}
	});
};
