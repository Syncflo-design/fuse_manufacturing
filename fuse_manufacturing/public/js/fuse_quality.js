// Fuse — recording an inspection, wherever stock changes hands.
//
// One dialog, four callers: receiving at a desk and on a phone, picking at a desk and on
// a phone, and a production run on the floor. Written once because the thing being asked
// is identical at every point — what did it measure, on what, does it pass — and four
// versions of that question would drift into four different records.
//
// What it hands back is exactly what fuse_manufacturing/quality.py expects as `captured`.
// Nothing is written here: the screen holds it and sends it with the movement, so the
// inspection and the stock move stand or fall together.
//
// Loaded desk-wide from hooks (app_include_js), so any screen can call it.

window.fuseQuality = window.fuseQuality || {};

(function (fq) {
	// Parameters and instruments are asked for once per item, not once per line — a
	// twelve-line delivery of the same product should not be twelve round trips.
	var requirements = {};
	var instruments = null;

	fq.requirement = function (item_code, reference_type, then) {
		var key = item_code + '::' + reference_type;
		if (requirements[key]) {
			then(requirements[key]);
			return;
		}
		frappe.call({
			method: 'fuse_manufacturing.quality.line_requirement',
			args: { item_code: item_code, reference_type: reference_type },
			callback: function (r) {
				requirements[key] = (r && r.message) || { required: false };
				then(requirements[key]);
			}
		});
	};

	fq.instruments = function (then) {
		if (instruments) {
			then(instruments);
			return;
		}
		frappe.call({
			method: 'fuse_manufacturing.quality.instruments',
			callback: function (r) {
				instruments = (r && r.message) || [];
				then(instruments);
			}
		});
	};

	// A line of the specification, as a dialog field. Numeric parameters get a Float with
	// the limits in the description, so the person taking the reading sees what they are
	// aiming at without opening the spec sheet.
	function field_for(parameter) {
		var limits = [];
		if (parameter.numeric) {
			if (parameter.min_value !== null && parameter.min_value !== undefined) {
				limits.push('min ' + parameter.min_value);
			}
			if (parameter.max_value !== null && parameter.max_value !== undefined) {
				limits.push('max ' + parameter.max_value);
			}
		} else if (parameter.value) {
			limits.push(parameter.value);
		}

		return {
			fieldname: 'p_' + frappe.utils.escape_html(parameter.specification).replace(/[^A-Za-z0-9]/g, '_'),
			fieldtype: parameter.numeric ? 'Float' : 'Data',
			label: parameter.specification,
			description: limits.join(' · ') || null,
			// Kept so the reading can be posted back under the parameter's real name,
			// which is what the Quality Inspection stores.
			_specification: parameter.specification
		};
	}

	/**
	 * Ask for an inspection and hand the result back.
	 *
	 * opts: { item_code, item_name, reference_type, batch_no, requirement }
	 * then(captured) is called only when the dialog is completed. Cancelling calls nothing,
	 * which leaves the line uninspected — and the submit then refuses it, which is the
	 * honest outcome rather than a half-filled record.
	 */
	fq.capture = function (opts, then) {
		var requirement = opts.requirement || {};
		var outgoing = requirement.inspection_type === 'Outgoing';

		fq.instruments(function (list) {
			var parameter_fields = (requirement.parameters || []).map(field_for);

			var fields = [
				{
					fieldname: 'about',
					fieldtype: 'HTML',
					options:
						'<div class="text-muted">' +
						frappe.utils.escape_html(opts.item_name || opts.item_code) +
						(opts.batch_no ? ' · batch ' + frappe.utils.escape_html(opts.batch_no) : '') +
						'</div>'
				}
			];

			if (parameter_fields.length) {
				fields.push({ fieldtype: 'Section Break', label: 'Readings' });
				fields = fields.concat(parameter_fields);
			} else {
				fields.push({
					fieldname: 'no_template',
					fieldtype: 'HTML',
					options:
						'<div class="text-muted">This item has no inspection template, so there ' +
						'are no parameters to record. Pass or fail is still yours to set.</div>'
				});
			}

			fields.push({ fieldtype: 'Section Break', label: 'Evidence' });

			// An instrument is offered, not demanded. Some checks are visual — appearance,
			// clarity, labelling — and there is no meter behind them. Where one IS named, it
			// must be in calibration, and the list only ever holds instruments that are.
			fields.push({
				fieldname: 'instrument',
				fieldtype: 'Select',
				label: 'Measured on',
				options: [''].concat(
					list.map(function (i) {
						return i.name;
					})
				).join('\n'),
				description: list.length
					? 'Only instruments in calibration are listed.'
					: 'No instrument is in calibration. Record a calibration first if a reading needs one.'
			});

			fields.push({
				fieldname: 'status',
				fieldtype: 'Select',
				label: 'Result',
				options: 'Accepted\nRejected',
				default: 'Accepted',
				reqd: 1
			});

			if (outgoing) {
				// 8.6: product does not reach a customer without a named person releasing it.
				fields.push({
					fieldname: 'verified_by',
					fieldtype: 'Data',
					label: 'Released by',
					default: frappe.session.user_fullname,
					reqd: 1,
					description: 'Who authorised this batch to go to the customer.'
				});
			}

			fields.push({
				fieldname: 'remarks',
				fieldtype: 'Small Text',
				label: 'Remarks'
			});

			var dialog = new frappe.ui.Dialog({
				title: 'Inspection · ' + opts.item_code,
				fields: fields,
				primary_action_label: 'Record',
				primary_action: function (values) {
					var readings = {};
					parameter_fields.forEach(function (f) {
						var taken = values[f.fieldname];
						// Left blank stays blank. A blank tells an auditor nobody measured it;
						// a zero tells them somebody did and got zero.
						if (taken !== undefined && taken !== null && taken !== '') {
							readings[f._specification] = taken;
						}
					});

					if (values.status === 'Rejected' && !(values.remarks || '').trim()) {
						frappe.msgprint('Say why it failed — that is the record.');
						return;
					}

					dialog.hide();
					then({
						readings: readings,
						instrument: values.instrument || null,
						status: values.status,
						verified_by: values.verified_by || null,
						remarks: values.remarks || null,
						batch_no: opts.batch_no || null,
						report_date: frappe.datetime.get_today(),
						sample_size: 1
					});
				}
			});

			dialog.show();
		});
	};

	// A short line for a screen to show against a line it has already captured.
	fq.summary = function (captured) {
		if (!captured) return '';
		var bits = [captured.status];
		var count = Object.keys(captured.readings || {}).length;
		if (count) bits.push(count + (count === 1 ? ' reading' : ' readings'));
		if (captured.instrument) bits.push(captured.instrument);
		return bits.join(' · ');
	};
})(window.fuseQuality);
