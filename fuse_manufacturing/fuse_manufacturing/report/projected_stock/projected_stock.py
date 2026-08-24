"""Projected Stock — ERPNext's Stock Projected Qty, without the columns Fuse cannot fill.

Not a rewrite. It calls ERPNext's own report and returns what that returns, minus a
column or two. Every number, filter and piece of logic is theirs and stays theirs
through upgrades.

Why it exists: the Description column sits beside Item Name and is empty on every row.
Intacct DOES have a field for it — ITEM.EXTENDED_DESCRIPTION, which the item sync now
maps — but companies that never fill it in get a blank column, and an always-empty
column reads as missing data rather than as a field nobody uses.

It cannot be removed from a Script Report by Customise: the columns are built in Python,
not stored on the Report record. Hence this.

If a client does populate extended descriptions, drop "description" from DROP below and
they get ERPNext's report back, column and all.

Add to DROP rather than editing ERPNext if another column turns out to be dead weight.
"""

from erpnext.stock.report.stock_projected_qty.stock_projected_qty import (
	execute as erpnext_execute,
)

# Fieldnames to leave out. Description only, for now.
DROP = {"description"}


def execute(filters=None):
	columns, data = erpnext_execute(filters)

	# Which positions survive, worked out before anything is dropped — the row data is
	# positional when ERPNext returns lists, so the columns and the values have to be cut
	# in the same places.
	keep = [index for index, column in enumerate(columns) if _fieldname(column) not in DROP]
	if len(keep) == len(columns):
		# Nothing to drop. An ERPNext release that renames or removes the column lands
		# here, and the report goes on working rather than failing on a missing index.
		return columns, data

	trimmed_columns = [columns[index] for index in keep]
	trimmed_data = []
	for row in data or []:
		if isinstance(row, dict):
			# Keyed rows need no positional surgery — a column that is gone is simply
			# never read.
			trimmed_data.append(row)
		else:
			trimmed_data.append([row[index] for index in keep if index < len(row)])

	return trimmed_columns, trimmed_data


def _fieldname(column):
	"""The fieldname of a column, whichever shape ERPNext used.

	Columns come back as dicts on most reports and as "Label:Type/Options:Width" strings
	on older ones. Both appear across ERPNext, so neither is assumed.
	"""
	if isinstance(column, dict):
		return column.get("fieldname")
	return (str(column).split(":")[0] or "").strip().lower().replace(" ", "_")
