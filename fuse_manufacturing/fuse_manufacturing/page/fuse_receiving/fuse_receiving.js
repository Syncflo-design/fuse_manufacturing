// Fuse — receiving at a desk.
//
// The second front door onto fuse_manufacturing/receiving.py. The Shop Floor page
// is the same flow shaped for a phone and a scanner; this one is shaped for the
// paperwork — the whole order visible at once, the supplier's delivery note and
// the date on screen rather than behind a dialog.
//
// Scanning still works here. A wedge scanner types into whatever has focus, and
// the scan box keeps focus between reads.
//
// Mounted inside page.body (jQuery in v16, per the page-api-drift gotcha).

frappe.pages['fuse-receiving'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Receiving',
		single_column: true
	});

	var BUILD_MARKER = 'v0.5.0-2026-08-18';
	console.log('Fuse Receiving loaded:', BUILD_MARKER);

	if (!document.getElementById('fuse-receiving-stylesheet')) {
		var link = document.createElement('link');
		link.id = 'fuse-receiving-stylesheet';
		link.rel = 'stylesheet';
		link.href = '/assets/fuse_manufacturing/css/fuse_receiving.css?v=' + encodeURIComponent(BUILD_MARKER);
		document.head.appendChild(link);
	}

	wrapper.fuseReceiving = window.fuseReceiving = new FuseReceiving(page);
};

frappe.pages['fuse-receiving'].on_page_show = function (wrapper) {
	if (wrapper.fuseReceiving) wrapper.fuseReceiving.find();
};

// ---------------------------------------------------------------------------

function fr_escape(value) {
	return frappe.utils.escape_html(value == null ? '' : String(value));
}

function fr_qty(value) {
	return String(parseFloat(flt(value).toFixed(4)));
}

function FuseReceiving(page) {
	this.page = page;
	this.$root = $('<div class="fr-root"></div>').appendTo(page.body);
	this.captured = {};
	this.find();
}

FuseReceiving.prototype.render = function (html) {
	this.$root.html(html);
};

// ---------------------------------------------------------------------------
// Find
// ---------------------------------------------------------------------------

FuseReceiving.prototype.find = function (term) {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.receiving.open_orders',
		args: { term: term || '' },
		freeze: true,
		freeze_message: 'Loading orders',
		callback: function (r) {
			var orders = (r && r.message) || [];

			var html = [
				'<div class="fr-head">',
				'  <div>',
				'    <div class="fr-title">Receiving</div>',
				'    <div class="fr-sub">Deliveries against a purchase order. Orders come from Intacct and are never created here.</div>',
				'  </div>',
				'</div>',
				'<input class="fr-search" data-search="1" placeholder="Order number, Intacct number or supplier"',
				'       autocomplete="off" value="' + fr_escape(term || '') + '">'
			];

			if (!orders.length) {
				html.push(
					'<div class="fr-empty">' +
					(term ? 'No open order matches “' + fr_escape(term) + '”.' : 'No orders are waiting for delivery.') +
					'</div>'
				);
			} else {
				html.push('<table class="fr-table"><thead><tr>');
				html.push('<th>Intacct order</th><th>Supplier</th><th>Ordered</th><th>Due</th><th class="fr-right">Received</th>');
				html.push('</tr></thead><tbody>');
				orders.forEach(function (order) {
					html.push(
						'<tr class="fr-pick" data-order="' + fr_escape(order.name) + '">' +
						'<td><b>' + fr_escape(order.custom_intacct_po_id || order.name) + '</b>' +
						'<div class="fr-muted">' + fr_escape(order.name) + '</div></td>' +
						'<td>' + fr_escape(order.supplier_name || order.supplier) + '</td>' +
						'<td>' + fr_escape(frappe.datetime.str_to_user(order.transaction_date)) + '</td>' +
						'<td>' + fr_escape(frappe.datetime.str_to_user(order.schedule_date)) + '</td>' +
						'<td class="fr-right">' + fr_qty(order.per_received) + '%</td>' +
						'</tr>'
					);
				});
				html.push('</tbody></table>');
			}

			self.render(html.join('\n'));

			self.$root.find('[data-search]').on('keydown', function (e) {
				if (e.which !== 13) return;
				e.preventDefault();
				self.find(($(this).val() || '').trim());
			});

			self.$root.find('[data-order]').on('click', function () {
				self.open($(this).data('order'));
			});
		}
	});
};

// ---------------------------------------------------------------------------
// Open
// ---------------------------------------------------------------------------

FuseReceiving.prototype.open = function (purchase_order) {
	var self = this;

	frappe.call({
		method: 'fuse_manufacturing.receiving.order_lines',
		args: { purchase_order: purchase_order },
		freeze: true,
		freeze_message: 'Opening the order',
		callback: function (r) {
			if (!r || !r.message) return;
			self.order = r.message;
			self.captured = {};
			self.paint();
		}
	});
};

FuseReceiving.prototype.paint = function () {
	var self = this;
	var order = this.order;

	var html = [
		'<div class="fr-head">',
		'  <button class="fr-back" data-back="1">&#8592; All orders</button>',
		'  <div>',
		'    <div class="fr-title">' + fr_escape(order.intacct_po || order.purchase_order) + '</div>',
		'    <div class="fr-sub">' + fr_escape(order.supplier_name || order.supplier) + ' · ' + fr_escape(order.purchase_order) + '</div>',
		'  </div>',
		'</div>'
	];

	if (!order.posting_on) {
		html.push(
			'<div class="fr-warn">Posting to Intacct is switched off. A receipt recorded now ' +
			'books stock in here and nowhere else.</div>'
		);
	}

	html.push(
		'<input class="fr-search" data-scan="1" placeholder="Scan an item on this order"',
		'       autocomplete="off" autocapitalize="off" spellcheck="false">'
	);

	html.push('<table class="fr-table fr-lines"><thead><tr>');
	html.push(
		'<th>#</th><th>Item</th><th class="fr-right">Ordered</th><th class="fr-right">Received</th>' +
		'<th class="fr-right">Outstanding</th><th class="fr-right">Accept</th><th class="fr-right">Reject</th><th>Lot</th>'
	);
	html.push('</tr></thead><tbody>');

	order.lines.forEach(function (line) {
		var id = line.purchase_order_item;
		var held = self.captured[id] || {};
		html.push(
			'<tr data-row="' + fr_escape(id) + '">' +
			'<td>' + line.idx + '</td>' +
			'<td><b>' + fr_escape(line.item_code) + '</b><div class="fr-muted">' +
			fr_escape(line.item_name || '') + ' · ' + fr_escape(line.warehouse || '') + '</div></td>' +
			'<td class="fr-right">' + fr_qty(line.ordered_qty) + '</td>' +
			'<td class="fr-right">' + fr_qty(line.received_qty) + '</td>' +
			'<td class="fr-right"><b>' + fr_qty(line.outstanding_qty) + '</b> ' + fr_escape(line.uom) + '</td>' +
			'<td class="fr-right"><input class="fr-qty" type="number" inputmode="decimal" step="any" ' +
			'data-accept="' + fr_escape(id) + '" value="' + (held.qty != null ? fr_qty(held.qty) : '') + '"></td>' +
			'<td class="fr-right"><input class="fr-qty" type="number" inputmode="decimal" step="any" ' +
			'data-reject="' + fr_escape(id) + '" value="' + (held.rejected_qty ? fr_qty(held.rejected_qty) : '') + '"' +
			(order.reject_warehouse ? '' : ' disabled title="No receiving rejects warehouse is set"') + '></td>' +
			'<td>' +
			(line.lot_tracked
				? '<input class="fr-lot" data-lot="' + fr_escape(id) + '" value="' + fr_escape(held.lot || '') + '">'
				: '<span class="fr-muted">not tracked</span>') +
			'</td>' +
			'</tr>'
		);
	});

	html.push('</tbody></table>');

	html.push(
		'<div class="fr-finish">',
		'  <label class="fr-field">Supplier delivery note / invoice',
		'    <input data-dn="1" autocomplete="off">',
		'  </label>',
		'  <label class="fr-field">Received on',
		'    <input data-date="1" type="date" value="' + frappe.datetime.get_today() + '">',
		'  </label>',
		'  <button class="fr-record" data-record="1">Record the delivery</button>',
		'</div>'
	);

	this.render(html.join('\n'));

	this.$root.find('[data-back]').on('click', function () {
		self.find();
	});

	// Capture is read off the inputs at record time, but held per row as it is typed
	// so a scan re-paint does not throw away what is already entered.
	this.$root.find('[data-accept], [data-reject], [data-lot]').on('change', function () {
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
FuseReceiving.prototype.hold = function () {
	var self = this;
	this.captured = {};

	this.$root.find('[data-accept]').each(function () {
		var id = $(this).data('accept');
		self.captured[id] = self.captured[id] || {};
		self.captured[id].qty = flt($(this).val());
	});
	this.$root.find('[data-reject]').each(function () {
		var id = $(this).data('reject');
		self.captured[id] = self.captured[id] || {};
		self.captured[id].rejected_qty = flt($(this).val());
	});
	this.$root.find('[data-lot]').each(function () {
		var id = $(this).data('lot');
		self.captured[id] = self.captured[id] || {};
		self.captured[id].lot = ($(this).val() || '').trim();
	});
};

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

FuseReceiving.prototype.scan = function (term) {
	var self = this;
	term = (term || '').trim();
	if (!term) return;

	this.hold();

	frappe.call({
		method: 'fuse_manufacturing.receiving.scan',
		args: { purchase_order: this.order.purchase_order, term: term },
		callback: function (r) {
			var result = (r && r.message) || {};
			var scanned = result.scan || {};

			if (scanned.type !== 'item') {
				frappe.show_alert({ message: scanned.label || 'Not an item.', indicator: 'orange' });
				return;
			}
			if (!result.lines || !result.lines.length) {
				frappe.show_alert({
					message: result.message || 'Not on this order.',
					indicator: 'orange'
				});
				return;
			}

			// A scan means "one more of this arrived". The row is highlighted and its
			// accepted quantity stepped up by one, which is what a storeman counting
			// cartons off a pallet is actually doing.
			var id = result.lines[0].name;
			var $input = self.$root.find('[data-accept="' + id + '"]');
			if (!$input.length) return;

			$input.val(fr_qty(flt($input.val()) + 1));
			self.hold();

			var $row = self.$root.find('[data-row="' + id + '"]');
			$row.addClass('fr-hit');
			setTimeout(function () {
				$row.removeClass('fr-hit');
			}, 600);
		}
	});
};

// ---------------------------------------------------------------------------
// Process
// ---------------------------------------------------------------------------

FuseReceiving.prototype.record = function (confirmed) {
	var self = this;
	this.hold();

	var rows = [];
	Object.keys(this.captured).forEach(function (id) {
		var held = self.captured[id];
		var accepted = flt(held.qty);
		var rejected = flt(held.rejected_qty);
		if (accepted <= 0 && rejected <= 0) return;

		var line = null;
		self.order.lines.forEach(function (candidate) {
			if (candidate.purchase_order_item === id) line = candidate;
		});

		rows.push({
			purchase_order_item: id,
			item_code: line ? line.item_code : null,
			qty: accepted,
			rejected_qty: rejected,
			warehouse: line ? line.warehouse : null,
			lot: held.lot || null
		});
	});

	if (!rows.length) {
		frappe.msgprint('Nothing has been captured against this order.');
		return;
	}

	frappe.call({
		method: 'fuse_manufacturing.receiving.submit_receipt',
		args: {
			purchase_order: this.order.purchase_order,
			rows: JSON.stringify(rows),
			supplier_delivery_note: (this.$root.find('[data-dn]').val() || '').trim(),
			posting_date: this.$root.find('[data-date]').val(),
			confirm_over_receipt: confirmed ? 1 : 0
		},
		freeze: true,
		freeze_message: 'Sending to Intacct…',
		callback: function (r) {
			var result = (r && r.message) || {};

			if (result.confirm_required === 'over_receipt') {
				var lines = (result.over || []).map(function (row) {
					return row.item_code + ': ' + fr_qty(row.receiving_qty) + ' against ' +
						fr_qty(row.outstanding_qty) + ' outstanding (' + fr_qty(row.excess_qty) + ' over)';
				});
				frappe.confirm(
					'More is being received than this order expects:<br><br><b>' +
					lines.join('<br>') + '</b><br><br>Record it anyway?',
					function () {
						self.record(true);
					}
				);
				return;
			}

			if (!result.purchase_receipt) return;
			self.done(result);
		}
	});
};

FuseReceiving.prototype.done = function (result) {
	var self = this;

	this.render([
		'<div class="fr-done">',
		'  <div class="fr-done-title">Delivery recorded</div>',
		'  <div class="fr-done-ref">' + fr_escape(result.purchase_receipt) + '</div>',
		result.intacct_key
			? '  <div class="fr-muted">Intacct ' + fr_escape(result.intacct_key) + '</div>'
			: '  <div class="fr-muted">Not posted — posting is switched off.</div>',
		'</div>',
		'<div class="fr-finish">',
		'  <button class="fr-record" data-again="1">Receive another order</button>',
		'  <button class="fr-secondary" data-open="1">Open the receipt</button>',
		'</div>'
	].join('\n'));

	this.$root.find('[data-again]').on('click', function () {
		self.find();
	});
	this.$root.find('[data-open]').on('click', function () {
		frappe.set_route('Form', 'Purchase Receipt', result.purchase_receipt);
	});
};
