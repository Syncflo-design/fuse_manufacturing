"""One counted worksheet, loaded back into its Intacct cycle count.

Saving reads the sheet and checks it against the count in Intacct: the count exists, it is
In Progress, every line on the sheet is a line on the count, and the units agree. Nothing is
sent until submit. Submitting writes the counted quantities onto the Intacct lines.

The lines table is rebuilt from the sheet on every save, never edited by hand. The sheet is
the record of what the counters wrote down, and a figure typed into Fuse afterwards would be
one nobody counted.

There is no cancel. Once a figure is in Intacct, cancelling this record would not take it
back out, and a cancelled record over a count Intacct still holds is worse than no record.
The correction is a new sheet: every value is absolute, so loading the right figure
overwrites the wrong one.

See counts.py for what the Intacct API allows and why.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from fuse_manufacturing import counts


class FuseCountImport(Document):
	def validate(self):
		self._check_module()
		self.company = self.company or frappe.defaults.get_user_default("Company")
		self._load()

	def on_submit(self):
		counted = [line for line in self.lines if line.counted]
		sent = counts.send(
			counted,
			company=self.company,
			reference=(self.doctype, self.name),
			stamp=now_datetime().strftime("%Y%m%d%H%M%S"),
		)
		self.db_set("lines_sent", sent)
		self.db_set("sent_on", now_datetime())

	def before_cancel(self):
		frappe.throw(
			"Counts already sent to Intacct cannot be taken back from here. To correct a line, "
			"load a sheet with the right figure on it: it overwrites the one in Intacct.",
			title="A count import cannot be cancelled",
		)

	def _check_module(self):
		from fuse_manufacturing import modules

		if modules.is_active("stock_count"):
			return

		label = modules.module_label("stock_count")
		frappe.throw(
			f"{label} is switched off for this site.\n\n"
			"An administrator can switch it on under Active Modules in Intacct Settings.",
			title=f"{label} is switched off",
		)

	def _load(self):
		header, sheet_lines, problems = counts.parse_sheet(counts.read_file(self.sheet))
		if problems:
			counts.raise_problems(problems, "The worksheet cannot be loaded")

		count = counts.read_count(header["count_id"], self.company)
		if not count:
			frappe.throw(
				f"Intacct has no count {header['count_id']}. Check the sheet is from this "
				"company's Intacct.",
				title="Count not found",
			)

		if header.get("warehouse") and header["warehouse"] != count["warehouse"]:
			frappe.throw(
				f"The sheet says warehouse {header['warehouse']}, but count {count['count_id']} "
				f"in Intacct is for {count['warehouse']}.",
				title="Wrong warehouse",
			)

		if count["state"] != "In Progress":
			frappe.throw(
				f"Count {count['count_id']} is {count['state']} in Intacct. Counts can only be "
				"loaded while the count is In Progress. "
				+ (
					"Start the count in Intacct first."
					if count["state"] == "Not Started"
					else "It is past the counting stage."
				),
				title="Count is not in progress",
			)

		count_lines = counts.read_count_lines(count["record_no"], self.company)
		matched, problems = counts.match(sheet_lines, count_lines)
		if problems:
			counts.raise_problems(problems, "The worksheet does not match the count")

		self.count_id = count["count_id"]
		self.count_description = count["description"]
		self.warehouse = count["warehouse"]
		self.count_state = count["state"]

		# A blind count hides quantity on hand from the counters. Showing it here would
		# hand it to whoever loads the first sheet before the recount.
		show = count["show_on_hand"]

		self.set("lines", [])
		for line in matched:
			intacct = line["intacct"]
			counted = line["qty_counted"] is not None
			self.append(
				"lines",
				{
					"sheet_row": line["sheet_row"],
					"item_id": intacct["item_id"],
					"item_name": intacct["item_name"],
					"bin": intacct["bin"],
					"unit": intacct["unit"],
					"qty_on_hand": intacct["on_hand"] if show else None,
					"qty_counted": line["qty_counted"] if counted else None,
					"counted": 1 if counted else 0,
					"variance": (line["qty_counted"] - intacct["on_hand"]) if (show and counted) else None,
					"qty_damaged": line["qty_damaged"],
					"damaged_entered": 1 if line["qty_damaged"] is not None else 0,
					"intacct_line": intacct["record_no"],
				},
			)

		self.lines_in_count = len(count_lines)
		self.lines_counted = sum(1 for line in self.lines if line.counted)
		self.lines_blank = len(self.lines) - self.lines_counted

		if not self.lines_counted:
			frappe.throw(
				"No quantities are filled in on this sheet, so there is nothing to send.",
				title="Nothing counted",
			)
