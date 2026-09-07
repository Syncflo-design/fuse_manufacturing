// Outstanding Orders — the order book by item, with the include/exclude toggle.
//
// The toggle writes a flag on the Sales Order through a whitelisted method rather than
// through the form: the order is submitted and mirrored from Intacct, and this is the one
// thing about it a planner may change.

const PLANNING_FILTERS = ["company", "customer", "item_group", "item_code", "due_before"];

frappe.query_reports["Outstanding Orders"] = {
	tree: true,
	name_field: "name",
	parent_field: "parent_name",
	initial_depth: 0,

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
			label: __("Due On or Before"),
			fieldtype: "Date",
		},
	],

	onload: function (report) {
		report.page.add_inner_button(__("Item Demand"), () => {
			const route_options = {};
			PLANNING_FILTERS.forEach((name) => {
				const value = report.get_filter_value(name);
				if (value) route_options[name] = value;
			});
			frappe.set_route("query-report", "Item Demand", route_options);
		});

		// One handler on the page for every toggle the formatter draws, so rows redrawn
		// on refresh keep working without being wired up again.
		$(report.page.wrapper).on("click", ".fuse-plan-toggle", function (event) {
			event.preventDefault();
			const so = $(this).data("so");
			const excluded = $(this).data("excluded") ? 0 : 1;
			frappe.call({
				method: "fuse_manufacturing.demand.set_planning_exclusion",
				args: { sales_order: so, excluded },
				callback: () => report.refresh(),
			});
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === "planning" && data.sales_order) {
			const label = data.excluded ? __("Include") : __("Exclude");
			const colour = data.excluded ? "var(--green-600, #2e7d32)" : "var(--red-600, #b02a37)";
			return `<a href="#" class="fuse-plan-toggle" data-so="${data.sales_order}" data-excluded="${data.excluded}" style="color: ${colour}">${label}</a>`;
		}
		if (data.is_item) {
			value = `<b>${value}</b>`;
		} else if (data.excluded) {
			value = `<span style="color: var(--gray-500, #888); text-decoration: line-through">${value}</span>`;
		}
		return value;
	},
};
