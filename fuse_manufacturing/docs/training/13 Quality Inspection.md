# Quality Inspection

*Checking a batch against its specification — Fuse Manufacturing user guide 13*

## Before you start

### What an inspection is

An item has a specification: what it should look like, what it should measure, what it
should do. An inspection is the record that somebody checked, what they found, and what
they decided.

Fuse asks for one at three points, and each is set per item:

| Point | When it is asked for | Set by |
|---|---|---|
| Incoming | A supplier delivery is booked in | **Inspect before purchase** on the item |
| In process | A batch is produced against a works order | **Inspect before delivery** on the item |
| Outgoing | Goods are picked for a customer | **Inspect before delivery** on the item |

An item with neither flag set is never asked for one.

### What happens if the check fails

A rejected inspection stops the movement. The goods cannot be received, produced onward,
or despatched on that document, and the line is named so nobody has to guess which one.

That is the point of the whole system. Releasing product that failed its own
specification is a **concession** — a decision somebody makes deliberately and records,
not something to click past on a phone.

> **Screenshot 1 — Fuse Home with the Quality Inspection tile**
> *[to be inserted: Fuse Home, Quick Launch row, Quality Inspection tile]*

## Recording an inspection

You can start one from two places, and both produce the same record.

### From the movement

This is the usual way, because the inspection belongs to a delivery, a production run or a
despatch.

1. Open the receipt, the works order or the pick.
2. On the line that needs checking, choose **Inspect**.
3. The specification for that item opens with one row per parameter.

The document, the item, the batch and the quantity are all filled in from where you came
from, so there is nothing to retype and nothing to get wrong.

### From the Quality Inspection tile

Use this to look back at what has been inspected, or to record one that was taken away
from a document.

1. On Fuse Home, click **Quality Inspection**.
2. Click **Add Quality Inspection**.
3. Choose the inspection type, the document it relates to, and the item.

## Filling it in

### Step 1 — The readings

Each row is one thing to check, and comes from the item's inspection template:

| Column | What goes in it |
|---|---|
| Parameter | What is being checked. Filled in from the template. |
| Acceptance criteria | What it has to be. Either a value in words or a minimum and maximum. |
| Reading | What you actually found |
| Status | Accepted or Rejected for that one line |

For a numeric parameter, type the measurement. It is compared against the minimum and
maximum and the line marks itself.

For a parameter checked in words, the reading has to match the acceptance criteria to
pass. If it does not — "two cartons crushed" against "sealed and undamaged" — the line
fails, which is exactly what you want it to do.

> **Screenshot 2 — The readings, with one line failing**
> *[to be inserted: Quality Inspection readings table, one row rejected]*

### Step 2 — The instrument

Where a reading came off a meter, a gauge or a balance, name it in **Instrument**.

A reading is only evidence if the instrument was in calibration when it was taken. Fuse
refuses an inspection recorded against an instrument whose calibration has lapsed or that
is out of service — see guide 14 Quality Setup for the register.

### Step 3 — Sample size and remarks

- **Sample size** — how many units you actually checked out of the quantity delivered or
  made.
- **Remarks** — what a person would need to know later. On a rejection this is the most
  useful field on the document, so write what was wrong, not that something was.

### Step 4 — The overall result

The inspection as a whole is **Rejected** if any single line was rejected. That is not
something to override on this screen; if the failing reading was a mistake, correct the
reading.

### Step 5 — Submit

Submit the inspection. It attaches to the line it came from, and the movement can now go
ahead — or is now formally blocked, if it failed.

> **Screenshot 3 — A submitted inspection**
> *[to be inserted: submitted Quality Inspection showing Accepted status and the instrument]*

## When something fails

1. The movement stops. Quarantine the goods.
2. Raise a **Quality Action** against the rejection, from the Quality page. That is where
   the cause is investigated, a resolution agreed, and somebody made responsible for it.
3. If the product is to be released anyway, that decision and its reason belong on the
   record. It is a concession, and it is auditable.

See guide 14 Quality Setup for procedures, goals and corrective actions.

## Common questions

### The inspection did not appear when I expected it

The item is not flagged for it. Check **Inspect before purchase** and **Inspect before
delivery** on the item, and that it has an inspection template.

### I cannot select my instrument

Its calibration has lapsed, or it is marked Out of Service. Use another instrument, or ask
whoever owns the register to recalibrate it. Do not record the reading without one.

### Can I inspect part of a delivery?

Yes — that is what sample size is for. You record how many you checked; the inspection
covers the line.

### Where do I find old inspections?

The Quality Inspection tile lists them all. The Quality page has a **Rejected** shortcut,
which is what people usually go looking for, and a Quality Inspection Summary report.
