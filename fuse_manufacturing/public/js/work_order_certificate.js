// Fuse — the Certificate of Analysis, one click from the works order.
//
// A run's inspection is recorded against its Manufacture stock entry, so without this the
// certificate is three documents away from the works order. The button appears only once a
// run has an inspection; with more than one run, it asks which batch.

(function () {
	function open_certificate(inspection) {
		var url = '/printview?doctype=' + encodeURIComponent('Quality Inspection')
			+ '&name=' + encodeURIComponent(inspection)
			+ '&format=' + encodeURIComponent('Certificate of Analysis')
			+ '&no_letterhead=0';
		window.open(frappe.urllib.get_full_url(url));
	}

	frappe.ui.form.on('Work Order', {
		refresh: function (frm) {
			if (frm.doc.docstatus !== 1) {
				return;
			}

			frappe.call({
				method: 'fuse_manufacturing.quality.work_order_certificates',
				args: { work_order: frm.doc.name },
				callback: function (r) {
					var certificates = (r && r.message) || [];
					if (!certificates.length) {
						return;
					}
					frm.add_custom_button(__('Certificate of Analysis'), function () {
						if (certificates.length === 1) {
							open_certificate(certificates[0].name);
							return;
						}
						frappe.prompt(
							{
								fieldname: 'inspection',
								fieldtype: 'Select',
								label: __('Batch'),
								reqd: 1,
								options: certificates.map(function (c) {
									return {
										value: c.name,
										label: (c.batch_no || c.name) + ' · ' + __(c.status) + ' · ' + frappe.datetime.str_to_user(c.report_date)
									};
								}),
								default: certificates[0].name
							},
							function (values) {
								open_certificate(values.inspection);
							},
							__('Certificate of Analysis'),
							__('Open')
						);
					});
				}
			});
		}
	});
})();
