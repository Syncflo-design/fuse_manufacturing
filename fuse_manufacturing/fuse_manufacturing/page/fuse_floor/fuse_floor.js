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

	var BUILD_MARKER = 'v0.0.1-2026-08-18';
	console.log('Fuse Shop Floor loaded:', BUILD_MARKER);

	if (!document.getElementById('fuse-floor-stylesheet')) {
		var link = document.createElement('link');
		link.id = 'fuse-floor-stylesheet';
		link.rel = 'stylesheet';
		link.href = '/assets/fuse_manufacturing/css/fuse_floor.css';
		document.head.appendChild(link);
	}

	wrapper.fuseFloor = window.fuseFloor = new FuseFloor(page);
};

frappe.pages['fuse-floor'].on_page_show = function (wrapper) {
	if (wrapper.fuseFloor) wrapper.fuseFloor.reload_context();
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

// ---------------------------------------------------------------------------

function FuseFloor(page) {
	this.page = page;
	this.context = null;
	this.$root = $('<div class="ff-root"></div>').appendTo(page.body);
	this.reload_context();
}

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
		'<div class="ff-warn">',
		'  Posting to Intacct is switched off. Nothing recorded here will reach the books.',
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

FuseFloor.prototype.home = function () {
	var self = this;
	this.basket = [];

	this.render([
		'<div class="ff-menu">',
		'  <button class="ff-tile" data-go="run">',
		'    <span class="ff-tile-title">Confirm a batch</span>',
		'    <span class="ff-tile-sub">Record what you made against a works order</span>',
		'  </button>',
		'  <button class="ff-tile" data-go="wip">',
		'    <span class="ff-tile-title">Issue to WIP</span>',
		'    <span class="ff-tile-sub">Move components from a store onto the floor</span>',
		'  </button>',
		'  <button class="ff-tile" data-go="move">',
		'    <span class="ff-tile-title">Move stock</span>',
		'    <span class="ff-tile-sub">Warehouse to warehouse</span>',
		'  </button>',
		'</div>'
	].join('\n'));

	this.$root.find('[data-go]').on('click', function () {
		var go = $(this).data('go');
		if (go === 'run') self.work_orders();
		else if (go === 'wip') self.transfer(FF_WIP);
		else self.transfer(FF_MOVE);
	});
};

FuseFloor.prototype.header_html = function (title, subtitle) {
	return [
		'<div class="ff-head">',
		'  <button class="ff-back" data-back="1">&#8592;</button>',
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
		this.header_html(wip ? 'Issue to WIP' : 'Move stock',
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
		'  <input class="ff-input" data-scan="1" placeholder="Scan or type an item" ',
		'         autocomplete="off" autocapitalize="off" spellcheck="false">',
		'</div>',
		'<div class="ff-results" data-results="1"></div>',
		'<div class="ff-basket" data-basket="1"></div>',
		'<button class="ff-submit" data-submit="1" disabled>Record</button>'
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
			'  <button class="ff-remove" data-remove="' + index + '">&#215;</button>' +
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
// Confirm a batch
// ---------------------------------------------------------------------------

FuseFloor.prototype.work_orders = function () {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.floor.open_work_orders',
		freeze: true,
		freeze_message: 'Loading works orders',
		callback: function (r) {
			var orders = (r && r.message) || [];
			var html = [self.header_html('Confirm a batch', 'Open works orders')];

			if (!orders.length) {
				html.push('<div class="ff-empty">No works orders are open.</div>');
			} else {
				html.push('<div class="ff-list">');
				orders.forEach(function (wo, index) {
					var left = flt(wo.qty) - flt(wo.produced_qty);
					html.push(
						'<button class="ff-row ff-row-wo" data-wo="' + index + '">' +
						'  <span class="ff-row-main">' + ff_escape(wo.production_item) + '</span>' +
						'  <span class="ff-row-sub">' + ff_escape(wo.item_name || '') + ' · ' + ff_escape(wo.name) + '</span>' +
						'  <span class="ff-row-qty">' + ff_qty(left) + ' ' + ff_escape(wo.stock_uom) + ' left</span>' +
						'</button>'
					);
				});
				html.push('</div>');
			}

			self.render(html.join('\n'));
			self.bind_back();
			self.$root.find('[data-wo]').on('click', function () {
				self.ask_made(orders[$(this).data('wo')]);
			});
		}
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
					'<div class="ff-made">Making <b>' + ff_qty(produced.qty) + ' ' +
					ff_escape(produced.uom) + '</b> of ' + ff_escape(produced.item_code) +
					' into ' + ff_escape(produced.t_warehouse || '') + '</div>'
				);
			}

			html.push('<button class="ff-submit" data-submit="1">Record the run</button>');

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
		'  <div class="ff-tick">&#10003;</div>',
		'  <div class="ff-done-msg">' + ff_escape(message) + '</div>',
		'  <div class="ff-done-ref">' + ff_escape(result.stock_entry) + '</div>',
		result.intacct_key
			? '  <div class="ff-done-key">Intacct ' + ff_escape(result.intacct_key) + '</div>'
			: '',
		'</div>',
		'<button class="ff-submit" data-again="1">Do another</button>',
		'<button class="ff-secondary" data-open="1">Open the document</button>'
	].join('\n'));

	this.$root.find('[data-again]').on('click', function () {
		self.home();
	});
	this.$root.find('[data-open]').on('click', function () {
		frappe.set_route('Form', 'Stock Entry', result.stock_entry);
	});
};
