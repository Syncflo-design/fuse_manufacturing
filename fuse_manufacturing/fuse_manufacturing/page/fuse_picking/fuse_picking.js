// Fuse — picking at a desk.
//
// The second front door onto fuse_manufacturing/picking.py. The Shop Floor page is the
// same flow shaped for a phone and a scanner; this one is shaped for the paperwork —
// the whole order visible at once, the date on screen rather than behind a dialog.
//
// Scanning still works here. A wedge scanner types into whatever has focus, and the scan
// box keeps focus between reads.
//
// It deliberately loads the RECEIVING stylesheet and uses its class names. The two
// screens are the same screen pointed in opposite directions, and they should not be able
// to drift apart visually because someone restyled one of them.
//
// Mounted inside page.body (jQuery in v16, per the page-api-drift gotcha).

frappe.pages['fuse-picking'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Picking',
		single_column: true
	});

	var BUILD_MARKER = 'v0.1.0-2026-08-24';
	console.log('Fuse Picking loaded:', BUILD_MARKER);

	if (!document.getElementById('fuse-receiving-stylesheet')) {
		var link = document.createElement('link');
		link.id = 'fuse-receiving-stylesheet';
		link.rel = 'stylesheet';
		link.href = '/assets/fuse_manufacturing/css/fuse_receiving.css?v=' + encodeURIComponent(BUILD_MARKER);
		document.head.appendChild(link);
	}

	wrapper.fusePicking = window.fusePicking = new FusePicking(page);
};

frappe.pages['fuse-picking'].on_page_show = function (wrapper) {
	if (wrapper.fusePicking) wrapper.fusePicking.find();
};

// ---------------------------------------------------------------------------

function fp_escape(value) {
	return frappe.utils.escape_html(value == null ? '' : String(value));
}

function fp_qty(value) {
	return String(parseFloat(flt(value).toFixed(4)));
}

function FusePicking(page) {
	this.page = page;
	this.$root = $('<div class="fr-root"></div>').appendTo(page.body);
	this.captured = {};
	this.find();
}

FusePicking.prototype.render = function (html) {
	this.$root.html(html);
};

// ---------------------------------------------------------------------------
// Find
// ---------------------------------------------------------------------------

FusePicking.prototype.find = function (term) {
	var self = this;
	this.order = null;
	this.captured = {};

	frappe.call({
		method: 'fuse_manufacturing.picking.open_orders',
		args: { term: term || null },
		callback: function (r) {
			var orders = (r && r.message) || [];

			var html = [
				'<div class="fr-head"><div><div class="fr-title">Orders to pick</div>',
				'<div class="fr-sub">Sales orders come from Intacct. Pick against one; the ' +
				'invoice is raised there.</div></div></div>',
				'<input class="fr-search" data-find="1" placeholder="Order number, Intacct number or customer"',
				'       autocomplete="off" autocapitalize="off" spellcheck="false"' +
				'       value="' + fp_escape(term || '') + '">'
			];

			if (!orders.length) {
				html.push('<div class="fr-empty">No orders are waiting to go out.</div>');
			} else {
				html.push('<table class="fr-table"><thead><tr>');
				html.push('<th>Intacct order</th><th>Customer</th><th>Due</th><th class="fr-right">Delivered</th>');
				html.push('</tr></thead><tbody>');
				orders.forEach(function (order) {
					// The whole row is the target, as on the receiving screen — a button in
					// the last column is a smaller thing to hit for no benefit.
					html.push(
						'<tr class="fr-pick" data-open="' + fp_escape(order.name) + '">' +
						'<td><b>' + fp_escape(order.custom_intacct_so_id) + '</b>' +
						'<div class="fr-muted">' + fp_escape(order.name) + '</div></td>' +
						'<td>' + fp_escape(order.customer_name || order.customer) + '</td>' +
						'<td>' + fp_escape(frappe.datetime.str_to_user(order.delivery_date) || '') + '</td>' +
						'<td class="fr-right">' + fp_qty(order.per_delivered) + '%</td>' +
						'</tr>'
					);
				});
				html.push('</tbody></table>');
			}

			self.render(html.join('\n'));

			// Debounced: a search box on a desk fires on every letter, and each one is a
			// round trip.
			var timer = null;
			self.$root.find('[data-find]').on('input', function () {
				var value = $(this).val();
				clearTimeout(timer);
				timer = setTimeout(function () { self.find(value); }, 300);
			}).focus();

			self.$root.find('[data-open]').on('click', function () {
				self.open($(this).data('open'));
			});
		}
	});
};

// ---------------------------------------------------------------------------
// Open one order
// ---------------------------------------------------------------------------

FusePicking.prototype.open = function (sales_order) {
	var self = this;
	frappe.call({
		method: 'fuse_manufacturing.picking.order_lines',
		args: { sales_order: sales_order },
		freeze: true,
		callback: function (r) {
			if (!r || !r.message) return;
			self.order = r.message;
			self.captured = {};
			self.paint();
		}
	});
};

FusePicking.prototype.paint = function () {
	var self = this;
	var order = this.order;

	var html = [
		'<div class="fr-head">',
		'  <button class="fr-back" data-back="1">&#8592; All orders</button>',
		'  <div>',
		'    <div class="fr-title">' + fp_escape(order.intacct_so || order.sales_order) + '</div>',
		'    <div class="fr-sub">' + fp_escape(order.customer) + ' · ' + fp_escape(order.sales_order) + '</div>',
		'  </div>',
		'</div>'
	];

	if (!order.posting_on) {
		html.push(
			'<div class="fr-warn">Posting to Intacct is switched off. A delivery recorded now ' +
			'takes stock out here and nowhere else.</div>'
		);
	}

	html.push(
		'<input class="fr-search" data-scan="1" placeholder="Scan an item on this order"',
		'       autocomplete="off" autocapitalize="off" spellcheck="false">'
	);

	html.push('<table class="fr-table fr-lines"><thead><tr>');
	html.push(
		'<th>Item</th><th class="fr-right">Ordered</th><th class="fr-right">Delivered</th>' +
		'<th class="fr-right">To pick</th><th class="fr-right">Available</th>' +
		'<th class="fr-right">Picking</th><th>Lot</th><th>Bin</th>'
	);
	html.push('</tr></thead><tbody>');

	order.lines.forEach(function (line) {
		var id = line.sales_order_item;
		var held = self.captured[id] || {};
		// Short is not an error — it is the picker's most common situation and the number
		// they act on, so it is called out rather than left to be worked out by eye.
		var short = flt(line.available) < flt(line.outstanding);

		html.push(
			'<tr data-row="' + fp_escape(id) + '">' +
			'<td><b>' + fp_escape(line.item_code) + '</b><div class="fr-muted">' +
			fp_escape(line.item_name || '') + ' · ' + fp_escape(line.warehouse || '') + '</div></td>' +
			'<td class="fr-right">' + fp_qty(line.ordered) + '</td>' +
			'<td class="fr-right">' + fp_qty(line.delivered) + '</td>' +
			'<td class="fr-right"><b>' + fp_qty(line.outstanding) + '</b> ' + fp_escape(line.uom) + '</td>' +
			'<td class="fr-right' + (short ? ' fr-shortfall' : '') + '">' + fp_qty(line.available) + '</td>' +
			'<td class="fr-right"><input class="fr-qty" type="number" inputmode="decimal" step="any" ' +
			'data-pick="' + fp_escape(id) + '" value="' + (held.qty != null ? fp_qty(held.qty) : '') + '"></td>' +
			'<td>' +
			(line.needs_lot
				? '<input class="fr-lot" data-lot="' + fp_escape(id) + '" value="' + fp_escape(held.lot || '') + '">'
				: '<span class="fr-muted">not tracked</span>') +
			'</td>' +
			'<td>' +
			(line.needs_bin
				? '<input class="fr-lot" data-bin="' + fp_escape(id) + '" value="' + fp_escape(held.bin || '') + '"' +
				  ' placeholder="default">'
				: '<span class="fr-muted">not tracked</span>') +
			'</td>' +
			'</tr>'
		);
	});

	html.push('</tbody></table>');

	html.push(
		'<div class="fr-finish">',
		'  <label class="fr-field">Delivered on',
		'    <input data-date="1" type="date" value="' + frappe.datetime.get_today() + '">',
		'  </label>',
		'  <button class="fr-record" data-record="1">Record the delivery</button>',
		'</div>'
	);

	this.render(html.join('\n'));

	this.$root.find('[data-back]').on('click', function () {
		self.find();
	});

	// Capture is read off the inputs at record time, but held per row as it is typed so a
	// scan re-paint does not throw away what is already entered.
	this.$root.find('[data-pick], [data-lot], [data-bin]').on('change', function () {
		self.hold();
	});

	this.$root.find('[data-scan]').on('keydown', function (e) {
		if (e.which !== 13) return;
		e.preventDefault();
		self.scan($(this).val());
		$(this).val('');
	});

	this.$root.find('[data-record]').on('click', function () {
		self.record(false);
	});

	this.$root.find('[data-scan]').focus();
};

// Read every row's inputs into `captured`, so a repaint keeps them.
FusePicking.prototype.hold = function () {
	var self = this;
	this.captured = {};

	this.$root.find('[data-pick]').each(function () {
		var id = $(this).data('pick');
		self.captured[id] = self.captured[id] || {};
		self.captured[id].qty = flt($(this).val());
	});
	this.$root.find('[data-lot]').each(function () {
		var id = $(this).data('lot');
		self.captured[id] = self.captured[id] || {};
		self.captured[id].lot = ($(this).val() || '').trim();
	});
	this.$root.find('[data-bin]').each(function () {
		var id = $(this).data('bin');
		self.captured[id] = self.captured[id] || {};
		self.captured[id].bin = ($(this).val() || '').trim();
	});
};

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

FusePicking.prototype.scan = function (term) {
	var self = this;
	if (!term) return;

	frappe.call({
		method: 'fuse_manufacturing.picking.scan',
		args: { sales_order: this.order.sales_order, term: term },
		callback: function (r) {
			var result = (r && r.message) || {};
			var lines = result.lines || [];

			if (!lines.length) {
				frappe.show_alert({
					message: result.message || (result.scan && result.scan.label) || 'Not recognised.',
					indicator: 'orange'
				});
				return;
			}

			// One line: fill the outstanding quantity in, which is the answer nine times
			// out of ten and leaves the picker to change it only when short.
			self.hold();
			var line = lines[0];
			self.captured[line.sales_order_item] = self.captured[line.sales_order_item] || {};
			var held = self.captured[line.sales_order_item];
			if (held.qty == null || !flt(held.qty)) held.qty = line.outstanding;

			self.paint();

			// Flash the row so a scanner user sees which line moved without reading it.
			var $row = self.$root.find('[data-row="' + line.sales_order_item + '"]');
			$row.addClass('fr-hit');
			setTimeout(function () { $row.removeClass('fr-hit'); }, 900);

			if (lines.length > 1) {
				frappe.show_alert({
					message: line.item_code + ' is on more than one line — check which.',
					indicator: 'orange'
				});
			}
		}
	});
};

// ---------------------------------------------------------------------------
// Record
// ---------------------------------------------------------------------------

FusePicking.prototype.record = function (confirmed) {
	var self = this;
	this.hold();

	var rows = [];
	Object.keys(this.captured).forEach(function (id) {
		var held = self.captured[id];
		if (!flt(held.qty)) return;
		var line = (self.order.lines || []).filter(function (l) {
			return l.sales_order_item === id;
		})[0] || {};
		rows.push({
			sales_order_item: id,
			item_code: line.item_code,
			qty: flt(held.qty),
			lot: held.lot || null,
			bin: held.bin || null
		});
	});

	if (!rows.length) {
		frappe.show_alert({ message: 'Nothing picked yet.', indicator: 'orange' });
		return;
	}

	frappe.call({
		method: 'fuse_manufacturing.picking.submit_delivery',
		args: {
			sales_order: this.order.sales_order,
			rows: JSON.stringify(rows),
			posting_date: this.$root.find('[data-date]').val() || null,
			confirm_over_delivery: confirmed ? 1 : 0
		},
		freeze: true,
		freeze_message: 'Recording the delivery…',
		callback: function (r) {
			var result = (r && r.message) || {};

			// Over-delivery comes back as a question, not an error: the server wrote
			// nothing and is waiting to be told whether the picker meant it.
			if (result.confirm_required === 'over_delivery') {
				var detail = (result.over || []).map(function (o) {
					return o.item_code + ': picking ' + fp_qty(o.picked) +
						', outstanding ' + fp_qty(o.outstanding) +
						' (' + fp_qty(o.excess) + ' over)';
				}).join('<br>');

				frappe.confirm(
					'More is being picked than the order is waiting for:<br><br>' + detail +
					'<br><br>Record it anyway?',
					function () { self.record(true); }
				);
				return;
			}

			self.done(result);
		}
	});
};

FusePicking.prototype.done = function (result) {
	var self = this;
	frappe.show_alert({
		message: 'Delivery ' + result.delivery_note + ' recorded' +
			(result.intacct_key ? ' · Intacct ' + result.intacct_key : ''),
		indicator: 'green'
	}, 7);

	// Straight back to the order, so a part-picked order can be finished without
	// hunting for it again.
	this.open(this.order.sales_order);
	setTimeout(function () { self.$root.find('[data-scan]').focus(); }, 300);
};
