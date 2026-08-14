// Filters for Stock on Order.
//
// No Project filter: purchase orders are mirrored from Intacct and carry no project here,
// so it would be a box that never changes the answer. Supplier is the one people actually
// reach for, so it is near the top.
frappe.query_reports["Stock on Order"] = {
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
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "due_before",
			label: __("Due On or Before"),
			fieldtype: "Date",
		},
		{
			fieldname: "overdue_only",
			label: __("Overdue only"),
			fieldtype: "Check",
		},
	],

	// Anything past its due date is worth seeing without reading the dates.
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.overdue_by) {
			value = `<span style="color: var(--red-600, #b02a37)">${value}</span>`;
		}
		return value;
	},
};
