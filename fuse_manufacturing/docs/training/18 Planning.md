# Planning

*From the customer order book to what to make and what to buy — Fuse Manufacturing user guide 18*

## Before you start

### What this does

You have orders from customers. Some of what they want is on the shelf, some has to be
made, and making it uses compound that may itself have to be mixed, from raw materials
that may have to be bought. Working that out by hand is where shortages get missed.

Two reports do it for you, in the order you would do it yourself:

1. **Outstanding Orders** — everything customers are still owed, grouped by item, with
   the orders under each. This is where you decide which orders count.
2. **Item Demand** — the same orders netted against stock and carried down the bill of
   materials: finished goods first, then the sub-assemblies they need, then the raw
   materials the sub-assemblies need.

The arithmetic at every level is the one you already know:

    Net requirement = customer demand + target stock − on hand − already on order

"Already on order" means open works orders for something you make and open purchase
orders for something you buy.

### Where the numbers come from

- **Orders** are mirrored from Intacct every hour. An order shipped in Intacct closes
  here on the next sync and drops out of demand.
- **Stock on hand** is what is in the ERPNext warehouses. Which warehouses count is a
  filter on the report — consignment stock sitting at a customer is not on your shelf.
- **Target stock** is the level you keep for an item on top of what is ordered. It is
  read from the item's reorder levels; an item with none has a target of nought.
- **Bills of materials** are the default BOM on each item, as synced from Intacct.

> **Screenshot 1 — Fuse Home with the Planning tile**
> *[to be inserted: Fuse Home, the Planning tile]*

## Step 1 — The order book

1. On Fuse Home, click **Planning**. Outstanding Orders opens, grouped by item.
2. Each item row shows the total still outstanding and how many orders it is spread over.
   Click the arrow on a row to see the orders underneath.
3. Narrow it if you need to: by customer, item group, item, or orders due on or before a
   date. The same filters carry through to Item Demand.

> **Screenshot 2 — Outstanding Orders, one item expanded**
> *[to be inserted: Outstanding Orders with an item row opened to show its orders]*

## Step 2 — Decide which orders count

Every order line has **Exclude** at the far right. Click it and the order is taken out of
the plan: the line greys out, the item total drops, and Item Demand ignores it. Click
**Include** to put it back.

The choice is saved on the order, not on the report. It holds when you come back
tomorrow, it holds for whoever else opens the report, and a note is left on the order
saying it was taken out. The order itself is not changed — it is still owed, it is just
not being planned for right now.

The line under the report says how many orders are open and how many are excluded, so an
exclusion is never silent.

> **Screenshot 3 — An excluded order, greyed, with the Include link**
> *[to be inserted: Outstanding Orders with one order line struck through]*

## Step 3 — What to make

1. Click **Item Demand** at the top of the report. It opens with the same filters.
2. Leave **Stage** at *Finished* and **Shortages only** ticked. You now have the finished
   items that need making, one row each.
3. Set **Count Stock In** to the warehouses that hold sellable stock. Leave it empty and
   every warehouse except transit is counted, consignment included.

| Column | What it tells you |
|---|---|
| Customer Demand | What is on the order book, in stock units |
| Target Stock | The level you keep on top of that |
| On Hand | Stock in the warehouses you chose |
| On Works Orders | Already being made |
| Net Requirement | What still has to be made — the figure in red |

A row with Make/Buy of *Buy* on this page is a bought-in resale line, not something you
make; it goes on the purchasing list in step 5 the same way a raw material does.

> **Screenshot 4 — Item Demand, Finished stage, shortages only**
> *[to be inserted: Item Demand filtered to Finished, red net figures visible]*

## Step 4 — What to mix

Change **Stage** to *Sub-assembly*. These are the compounds the shortfall in step 3 calls
for, after compound already mixed and compound already on a works order are taken off.

**Needed by Parents** is what the finished goods ask for; the net is what is left to mix
once stock and open works orders are counted. Compound on the shelf stops the demand
there — it does not go on to ask for the rubber that is already in it.

> **Screenshot 5 — Item Demand, Sub-assembly stage**
> *[to be inserted: Item Demand filtered to Sub-assembly]*

## Step 5 — What to buy

Change **Stage** to *Raw material*. This is the purchasing list: what the compounds in
step 4 need, less what is in stores and less what is already on an open purchase order.

**On Purchase Orders** is read from the orders mirrored from Intacct, so a delivery that
is on its way is not bought twice.

Raise the purchase requisitions from here — a Material Request of type Purchase per
shortage (guide 15). On an integrated site the purchase order itself is placed in
Intacct against that request, and it shows in this column on the next sync.

> **Screenshot 6 — Item Demand, Raw material stage**
> *[to be inserted: Item Demand filtered to Raw material]*

## Step 6 — Raise the works orders

The figures from steps 3 and 4 are what the works orders are for. Raise them through a
Production Plan (guide 17), which creates one works order per item in the right order —
compound before the tread that needs it — or directly (guide 04) for a one-off.

Once a works order exists it appears in **On Works Orders** and the net requirement
falls. Run Item Demand again and the row goes to zero: that is how you know the plan is
covered.

## Common questions

### An order is on the report that has already been delivered

Deliveries made in Intacct close the order here on the next hourly sync. If it is still
showing an hour later, the order is still open in Intacct — check there.

### The on-hand figure is too high

Look at **Count Stock In**. Empty means every warehouse except transit, which includes
consignment stock at customers and anything in quality hold. Choose the warehouses that
hold stock you can actually ship or use.

### Target stock is zero on everything

No reorder levels have been set. Until they are, the report plans to cover orders only,
with nothing kept on the shelf. Reorder levels are set per item per warehouse.

### The quantities are in kilograms, we order in rolls

The report works in the item's stock unit, which is what the orders and the BOMs are in.
A roll count needs a roll unit with a conversion on the item; without one, kilograms are
the only unit the figures agree in.

### I excluded an order by mistake

Open Outstanding Orders and click **Include** on it. Nothing else has to be undone.
