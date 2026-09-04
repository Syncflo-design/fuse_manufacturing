# A works-order material issue is not a warehouse transfer

**Date:** 2026-09-04
**Site:** Leadertread (Leader Rubber Company)

## What happened

Submitting `MAT-STE-2026-00019` — a Material Transfer for Manufacture raised from
`MFG-WO-2026-00002` — died on submit with a Server Error traceback:

```
ValueError: RMSULPHUR: source and destination are the same warehouse
  postings.py -> post_stock_entry_transfer -> rules.transfer_legs
```

Every one of the 14 component rows had `s_warehouse == t_warehouse ==
JHB Industria - Mixing Kelvin Compound`.

## Why

Leadertread mixes compound in the warehouse the raw materials are stored in. There is no
separate WIP warehouse and there never will be — works orders here have Source, WIP and
Target all set to the same place, deliberately.

ERPNext still raises a Material Transfer for Manufacture, because that is how it records
the issue against the works order. Fuse was routing that document down the **warehouse
transfer** path, which builds an out leg and an in leg for Intacct. Two legs against the
same warehouse is not a transfer — `rules.transfer_legs` refused it, correctly, and the
whole submit rolled back.

The error was right. The routing was wrong: this is manufacturing, not a transfer.

## The fix

`postings.py` — `_moves_nothing(doc)`. A transfer where **every** row leaves and arrives
in the same warehouse posts nothing to Intacct and returns cleanly. The ERPNext document
stands (the works order needs it to count Material Transferred for Manufacturing); Intacct
sees nothing, because nothing moved.

All rows or none. One stay-put row among rows that move is a mistake on that row, and
`rules.transfer_legs` still refuses it.

`on_stock_entry_submit` no longer stamps `custom_intacct_key` / `custom_intacct_posted_on`
when no key came back — otherwise a cancel would later try to reverse a posting that never
happened.

## Also

`Issue to WIP` is switched ON in Intacct Settings on this site. It should be off for a
client whose works orders never stage to a WIP warehouse — it puts a tile on Fuse Home for
a step they do not do.

## Lesson

Do not infer the process from ERPNext's document type. A Material Transfer for Manufacture
is a works-order issue, and on a site without a WIP warehouse it is a bookkeeping row with
no movement behind it. Ask what the client actually does before treating a document as a
stock movement Intacct has to hear about.
