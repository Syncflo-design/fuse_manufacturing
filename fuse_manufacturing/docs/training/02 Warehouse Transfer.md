# Warehouse Transfer

*Moving stock from one warehouse to another — Fuse Manufacturing user guide 02*

## Before you start

### What a warehouse transfer is

Stock is in one warehouse and needs to be in another. Nothing is bought, sold, made or
consumed — the same goods simply change place.

Recording it does two things at once. The stock moves in Fuse, and the same movement is
posted to Sage Intacct. Intacct goes first, so the two systems cannot end up disagreeing
about where the stock is.

### Two screens, one job

Your site is set up with one of two screens, and an administrator chooses which under
**Use Simple Warehouse Transfer** in Intacct Settings:

| Screen | What it looks like |
|---|---|
| Fuse's transfer screen | A from, a to, and a list of items. The item picker only offers what the source warehouse actually holds. |
| ERPNext's Stock Entry form | The full form, with every field a stock movement can carry. |

Both record exactly the same movement and post the same thing to Intacct. The difference
is how much the person moving the stock has to look at. This guide covers Fuse's screen;
if yours looks different, see guide 06 Stock Control.

### Before you record anything

- Know which warehouse the stock is leaving and which it is going to.
- Know what is actually moving, and how much. Not what was asked for — what is on the
  trolley.
- If your items are bin or lot tracked in Intacct, know which bin it came out of, which
  bin it is going into, and which lot.

> **Screenshot 1 — Fuse Home with the Warehouse Transfer tile**
> *[to be inserted: Fuse Home, Quick Launch row, Warehouse Transfer tile]*

## Recording the transfer

### Step 1 — Set the route

1. On Fuse Home, click **Warehouse Transfer**.
2. In **From**, choose the warehouse the stock is leaving.
3. In **To**, choose the warehouse it is going to.

Set the From warehouse before you add any items. The item list is drawn from what that
warehouse holds, so choosing it first is what makes the picker useful.

If you pick the same warehouse on both sides the transfer is refused. Nothing would move,
so there is nothing to record.

> **Screenshot 2 — The transfer route, From and To**
> *[to be inserted: Fuse Stock Transfer, route section with the arrow between the two warehouses]*

### Step 2 — Add what is moving

1. In **Items to move**, click **Add Row**.
2. Start typing in the **Item** column. Only items the From warehouse actually holds are
   offered, and you can search on the item code or on its description.
3. Pick the item. A message tells you how much of it is on hand in that warehouse.
4. Type the **Quantity**.
5. Repeat for everything on the trolley.

The unit is filled in for you from the item and cannot be changed here. It has to match
Intacct's unit for that item exactly, so it is not something to type.

> **Screenshot 3 — The item list, with the on-hand message**
> *[to be inserted: items grid with two rows added and the on-hand alert visible]*

### Step 3 — Bins and lots, where the item has them

Two extra columns appear on the grid, but only when something on the document needs them:

- **From bin** and **To bin** appear as soon as you add an item that Intacct tracks in
  bins. Each side is filled separately, because the stock leaves a bin in one warehouse
  and lands in a bin in the other. The picker only offers bins that belong to the
  warehouse on that side.
- **Lot** appears for items Intacct tracks by lot. Say which lot moved.

Leave a bin blank and the warehouse's default bin is used. Leave a lot blank on a
lot-tracked item and the transfer is refused — Intacct will not accept the movement
without one, and it is better to be told here than after the goods have gone.

If neither column has appeared, nothing on this document is tracked and there is nothing
to fill in.

> **Screenshot 4 — The bin and lot columns on a tracked item**
> *[to be inserted: items grid showing From bin, To bin and Lot columns]*

### Step 4 — Scanning instead of typing

If you have a scanner:

1. Click **Scan Barcode** at the top of the screen.
2. Scan an item. It is added to the list with a quantity of one.
3. Scan the same item again and the quantity goes up by one rather than adding a second
   row.
4. Click **Done Scanning** when you have finished, then correct any quantities by hand.

### Step 5 — Submit

Click **Submit**.

At that moment Fuse asks Intacct to record the movement. If Intacct accepts it, the
transfer stands and the stock has moved in both systems. If Intacct refuses it — a closed
period, a warehouse it does not recognise, a bin that does not exist — the transfer does
not stand here either, and the reason is shown on screen.

> **Screenshot 5 — A submitted transfer**
> *[to be inserted: submitted Fuse Stock Transfer showing the linked Stock Entry]*

## After it is submitted

**Recorded as** shows the Stock Entry the transfer created. That is the movement itself,
and the Intacct document key is on it. Click through if anyone needs to reconcile the two
systems.

## Common questions

### The item I need is not in the list

It is not in the From warehouse. Either it is somewhere else — check the warehouse — or
it has never been received into that warehouse at all.

### It says the warehouse does not hold enough

The quantity you are moving is more than the warehouse shows. Check whether the same item
is on the document twice: two rows of forty are eighty, and each row looked fine on its
own.

If the figure on screen genuinely disagrees with what is on the shelf, that is a stock
accuracy problem, not a transfer problem. Raise it rather than working around it.

### I have chosen the wrong warehouse after adding items

Change it. Any bins you had picked are cleared, because they belonged to the old
warehouse, and you are told how many were cleared. The items themselves stay — check they
are all still held in the new From warehouse.

### I need to undo a transfer

Cancel it. Cancelling posts the reverse movement to Intacct as a new document, so both
systems agree again. Intacct keeps the original and the undo; nothing is deleted, which
is what an audit trail is for.
