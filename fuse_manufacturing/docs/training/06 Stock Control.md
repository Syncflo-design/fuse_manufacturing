# Stock Control

*Where the stock reports live — Fuse Manufacturing user guide 06*

## Before you start

### What Stock Control is

The tiles on Fuse Home are the things you *do*. Stock Control is where you go to *look* —
what is where, what moved, what is coming, and what it is all worth.

It is a curated page rather than the whole of ERPNext's Stock module. What is on it is
what a stock controller actually opens; the rest is still there for an administrator who
needs it.

> **Screenshot 1 — Fuse Home with the Stock Control tile**
> *[to be inserted: Fuse Home, Quick Launch row, Stock Control tile]*

## What is on the page

### Shortcuts

Two counts across the top, each opening a filtered list:

| Shortcut | What it shows |
|---|---|
| Transfers | Every warehouse transfer and issue to WIP |
| Production | Every production run recorded |

### Movements

The documents themselves — **Stock Entry** and **Work Order**. Use these when you want a
particular movement rather than a total.

### Reports — the daily four

| Report | The question it answers |
|---|---|
| Stock Balance | What is on hand, in and out, over a period |
| Stock Ledger | Every movement of an item, in order, with the running balance |
| Projected Stock | What will be left once what is on order and committed is taken into account |
| Warehouse Wise Stock Balance | The same balance, split by warehouse |
| Stock on Order | What is still coming from suppliers, where it is going and when it was due |

**Projected Stock** is the one to reach for before promising anything. Stock Balance says
what you have; Projected Stock says what you will still have once existing commitments are
met.

**Stock on Order** is ours rather than ERPNext's. ERPNext's Purchase Order Analysis is
built for a business that receipts and bills in ERPNext — here it does neither, so its
Received and Billed columns sit permanently at zero. This one shows what is still coming,
where it is going and when it was due.

> **Screenshot 2 — The Stock Control page**
> *[to be inserted: Fuse Stock Control workspace, shortcuts and cards]*

### Analysis

The questions asked at month end, or when something looks wrong:

| Report | The question it answers |
|---|---|
| Stock Summary | A live view of stock by item and warehouse |
| Stock Ageing | How long stock has been sitting, in bands |
| Stock Analytics | Movement over time, charted |
| Item Price Stock | What is on hand set against what it is priced at |

### Master Data

**Item**, **Warehouse** and **BOM**. All read-only for most roles, because Intacct owns
them — an edit here would be overwritten by the next sync.

## Using the reports

Every report works the same way:

1. Open it.
2. Set the filters across the top — company, warehouse, item group, date range. Most
   default to something sensible; the date range rarely does.
3. Read it, or use the menu to export to Excel.

Two habits worth having:

- **Check the warehouse filter before you believe a shortage.** More reported stock
  problems turn out to be a filter than turn out to be stock.
- **Use the date range on Stock Balance.** It shows movement over a period, not a snapshot,
  so a range that is too wide reads as far more activity than there was.

## Common questions

### The numbers here and in Intacct disagree

They should not, and a difference is worth chasing rather than explaining away. Every
movement Fuse records is posted to Intacct as it happens, and a movement Intacct refused
does not stand in Fuse either.

Start with the Stock Ledger for the item, find the movement that is in one system and not
the other, and open it — the Intacct document key is on the movement itself.

### Something moved but I cannot see who did it

Open the Stock Entry. Every document carries who created it and when, and the full history
is under the menu.

### Can I correct a stock figure here?

No, and deliberately not. Fuse posts movements, not adjustments. On-hand corrections go
through Intacct's cycle count, which is how the correction ends up in the accounts as well
as on the shelf. A local adjustment would move stock Intacct never saw.
