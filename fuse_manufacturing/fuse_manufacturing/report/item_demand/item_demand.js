// Item Demand — filters, and the way back to the order book.
//
// Warehouses is a multi-select so consignment stock at customers, quality hold and the
// like can be left out of "on hand" until the site has warehouse types to do it by rule.

const ORDER_FILTERS = ["company", "customer", "item_group", "item_code", "due_before"];

frappe.query_reports["Item Demand"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "stage",
			label: __("Stage"),
			fieldtype: "Select",
			options: ["All", "Finished", "Sub-assembly", "Raw material"],
			default: "All",
		},
		{
			fieldname: "shortages_only",
			label: __("Shortages only"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "warehouses",
			label: __("Count Stock In"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Warehouse", txt, {
					company: frappe.query_report.get_filter_value("company"),
					is_group: 0,
				});
			},
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "due_before",
			label: __("Orders Due On or Before"),
			fieldtype: "Date",
		},
	],

	onload: function (report) {
		report.page.add_inner_button(__("Outstanding Orders"), () => {
			const route_options = {};
			ORDER_FILTERS.forEach((name) => {
				const value = report.get_filter_value(name);
				if (value) route_options[name] = value;
			});
			frappe.set_route("query-report", "Outstanding Orders", route_options);
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "net" && data.net > 0) {
			value = `<b style="color: var(--red-600, #b02a37)">${value}</b>`;
		}
		return value;
	},
};
