# Bin Transfer

*Moving stock between bins inside one warehouse — Fuse Manufacturing user guide 11*

## Before you start

### What a bin transfer is

Stock stays in the same warehouse but moves to a different bin. A pallet comes down from
a high rack into a pick face; a part moves from goods-in to its home location; a bin is
emptied so it can be re-racked.

### Why it works differently from a warehouse transfer

This one is worth understanding, because it explains what the screen can and cannot tell
you.

Fuse holds stock **per warehouse**. Intacct holds it **per bin**. So when stock moves
between two bins in the same warehouse, the Fuse quantity does not change at all —
nothing has left the warehouse. There is no stock movement for Fuse to record.

That means:

- **The Bin Transfer document is the record.** There is no stock entry behind it.
- **It must reach Intacct.** If posting to Intacct is switched off, the transfer is
  refused rather than saved, because nothing else would record it.
- **Nothing can tell you what is in a bin.** Fuse does not track stock at bin level, and
  Intacct reports on-hand per warehouse rather than per bin. The quantities on screen are
  warehouse-wide. Check the shelf.

> **Screenshot 1 — Fuse Home with the Bin Transfer tile**
> *[to be inserted: Fuse Home, reference row, Bin Transfer tile]*

### Before you record anything

- Know the warehouse, the bin it is coming out of and the bin it is going into.
- Know what is actually moving and how much.
- For lot-tracked items, know which lot.

If the Bin Transfer tile is not on your home page, either your items are not bin-enabled
in Intacct or an administrator has the module switched off. Bin Transfer is off by default
for exactly that reason: a site without bins has nowhere for this to move stock to.

## Recording the move

### Step 1 — Choose the warehouse

1. On Fuse Home, click **Bin Transfer**.
2. In **Warehouse**, choose where the stock is. Both bins live in this warehouse — stock
   does not leave it.

> **Screenshot 2 — The warehouse and the two bins**
> *[to be inserted: Fuse Bin Transfer, warehouse field above the bin-to-bin section]*

### Step 2 — Choose the bins

1. In **From bin**, choose the bin the stock is coming out of.
2. In **To bin**, choose where it is going.

Both pickers only offer bins that belong to the warehouse above, and only bins that are
active in Intacct. Change the warehouse afterwards and both bins are cleared, because they
belonged to the old one.

The same bin on both sides is refused. Nothing would move.

### Step 3 — Add what is moving

1. In **Items to move**, click **Add Row** and choose the item. Only items the warehouse
   actually holds are offered.
2. Type the **Quantity**.
3. A **Lot** column appears if anything on the document is lot tracked. Fill it in — a
   lot-tracked move is refused without it.

The message that appears as you pick each item shows what the whole warehouse holds,
across every bin. It is there to give you a sense of scale, not to tell you what is in the
bin you are emptying.

> **Screenshot 3 — The item list**
> *[to be inserted: Fuse Bin Transfer items grid with two rows]*

### Step 4 — Scanning

Click **Scan Barcode**, scan each item, and click **Done Scanning** when you are finished.
Scanning the same item twice increases its quantity rather than adding a second row.

### Step 5 — Submit

Click **Submit**. Fuse posts the move to Intacct as a pair of documents — the stock out of
one bin and into the other — in a single operation. Either both go or neither does.

If Intacct refuses it, the transfer does not stand here either and the reason is shown.
The most common refusal is a quantity larger than the bin actually holds, which is the
check this screen cannot make for you.

> **Screenshot 4 — A submitted bin transfer with its Intacct keys**
> *[to be inserted: submitted Fuse Bin Transfer, Recorded in Intacct section]*

## After it is submitted

**Recorded in Intacct** carries the keys of the two documents the move created. Anyone
reconciling can find either one from here.

## Common questions

### Why can I not see what is in each bin?

Because neither system holds it in a way this screen can read. Intacct is where stock sits
in bins, and it reports on-hand by warehouse. Until Fuse mirrors bins as warehouses in
their own right, the honest answer is that the shelf is the source of truth for what is in
a bin.

### It will not let me submit — posting is switched off

That is deliberate. A bin transfer has no effect in Fuse at all; Intacct is the only place
the movement lands. Saving one while posting is off would file a record of something that
never happened. Ask an administrator to turn **Post Stock Movements** back on.

### I need to undo one

Cancel it. The stock is moved back to the bin it came from, as a new pair of documents in
Intacct. The original stays on the record.
