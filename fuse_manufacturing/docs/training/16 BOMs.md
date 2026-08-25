# BOMs

*What each product is made of — Fuse Manufacturing user guide 16*

## Before you start

### What a BOM is

A bill of materials is the recipe for one product: which components go into it, and how
much of each. Everything downstream reads it — a works order knows what to consume, a
production plan knows what to buy, and costing knows what the finished item is worth.

### Where recipes come from

On most sites, **from Intacct**. A kit in Intacct is mirrored here as a BOM on every kit
sync, and Intacct's recipe is restored as the default each time. The New button is hidden
and creating one by hand is refused.

That is not an obstacle. A hand-built BOM would be a second recipe Intacct has never heard
of, and the next sync would quietly make Intacct's the default again — so the hand-built
one would look right and be ignored.

Two switches in Intacct Settings decide this, and they answer different questions:

| Switch | Question it answers |
|---|---|
| Use Intacct Kits as BOMs | Does Intacct hold the recipes at all? |
| Lock BOM Creation in Fuse | May anyone keep one here as well? |

A client whose recipes are not in Intacct switches the first off, and then BOMs are built
here as in stock ERPNext.

> **Screenshot 1 — Fuse Home with the BOMs tile**
> *[to be inserted: Fuse Home, reference row, BOMs tile]*

## Reading a BOM

1. On Fuse Home, click **BOMs**.
2. Open one.

| Section | What it tells you |
|---|---|
| Item | What is being made, and the quantity the recipe is written for |
| Items | One row per component: the item, how much, and its rate |
| Costing | What the components come to, and therefore what the finished item costs to make |

The quantity at the top matters. A recipe written for 100 litres and one written for 1
litre both work, but every component quantity is read against it — so check which you are
looking at before doing arithmetic in your head.

> **Screenshot 2 — A BOM with its component list**
> *[to be inserted: BOM showing items and the costing section]*

## Sub-assemblies

A component can itself have a BOM. Fuse follows the chain when it needs to — a production
plan exploding demand will work down through every level, and a works order can be told to
use the multi-level recipe or to treat the sub-assembly as a component to be issued.

Where a sub-assembly holds stock in a warehouse, **Intacct creates it**, the same as any
other item. If it holds value, accounting knows about it.

## Costing

The rates on a BOM come from Intacct, because that is where cost lives. Fuse does not
invent a number:

- Where Intacct has a cost, that is what is used.
- Where it has none, the item opens at a sentinel of 0.01 so the gap is visible rather
  than plausible. A BOM total that looks obviously wrong is a gap someone will fix; a
  total that looks reasonable and is wrong is one nobody will.

The cost of what a production run actually consumed is what gets posted back to Intacct
with the finished goods. See guide 05.

## Common questions

### The New button is missing

The site is set up with Intacct as the source for recipes. Add the kit in Intacct and it
appears here on the next sync.

### The BOM does not match what the floor actually does

Then either the recipe is wrong or the practice is. Both are worth resolving, and neither
is fixed by editing the copy here — the next sync would overwrite it. Change it in
Intacct.

### A component is missing from a BOM

Same answer. Check the kit in Intacct, then re-run the kit sync from Intacct Settings.

### How do I know which BOM a works order used?

It is named on the works order. A BOM can be superseded, so the one used at the time is
recorded rather than looked up again later.
