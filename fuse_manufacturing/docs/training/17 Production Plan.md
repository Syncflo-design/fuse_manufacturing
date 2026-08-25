# Production Plan

*Working out what to make and what to buy — Fuse Manufacturing user guide 17*

## Before you start

### What a production plan is

You have demand — sales orders, a forecast, or a figure somebody has decided on. A
production plan takes that demand, reads it through the BOMs, and tells you two things:

1. **What to make**, and in what order, once sub-assemblies are taken into account.
2. **What to buy**, once what is already on the shelf and already on order is taken off.

Then it raises the works orders and material requests to match, in one go.

### Why not just raise the works orders

Because the arithmetic is where the mistakes are. Demand for a hundred finished units is
not demand for a hundred of each component — some are already in stock, some are on order,
some go into a sub-assembly that itself needs making first. Doing that by hand is where a
shortage gets missed.

> **Screenshot 1 — Fuse Home with the Production Plan tile**
> *[to be inserted: Fuse Home, Quick Launch row, Production Plan tile]*

## Building a plan

### Step 1 — Say where the demand comes from

1. On Fuse Home, click **Production Plan**, then **Add Production Plan**.
2. Set **Get Items From**:
   - **Sales Order** — plan against real customer orders.
   - **Material Request** — plan against internal asks (see guide 15).
   - Leave it unset and add the items by hand, which is what you do for a forecast or a
     make-to-stock run.
3. If you are pulling from orders, filter by customer or date and click **Get Sales
   Orders**, then **Get Items for Work Order**.

### Step 2 — Check what is to be made

The **Items to Manufacture** table now lists each finished item, how many, and the BOM it
will use.

Check the BOM on each line. Where an item has more than one, the default is used and it is
not always the one you meant.

> **Screenshot 2 — Items to manufacture**
> *[to be inserted: Production Plan, Items to Manufacture table]*

### Step 3 — Work out the materials

1. Tick **Include Non Stock Items** and **Include Sub-assembly Items** as your process
   requires. Sub-assemblies matter: leave it off and the plan assumes they already exist.
2. Set the **warehouse** the material is to come from.
3. Click **Get Raw Materials for Production**.

The **Material Request Plan** table fills in with what is needed, and — this is the useful
part — what is actually short:

| Column | What it tells you |
|---|---|
| Required Qty | What the BOMs call for |
| Available Qty | What is on the shelf now |
| Ordered Qty | What is already on its way |
| Quantity | What still has to be requested |

A line with a Quantity of zero needs nothing doing. The lines with a number are your
shortage list.

> **Screenshot 3 — The material request plan, showing shortages**
> *[to be inserted: Production Plan, Material Request Plan table with shortfalls]*

### Step 4 — Submit, then raise the documents

1. **Submit** the plan.
2. **Create Work Orders** — one per line in Items to Manufacture, in dependency order so a
   sub-assembly is made before the thing it goes into.
3. **Create Material Requests** — one per shortage. On an integrated site these are
   requisitions; the purchase order itself is raised in Intacct.

> **Screenshot 4 — Work orders raised from a plan**
> *[to be inserted: submitted Production Plan with the work order links]*

## After the plan

Each works order runs its own course — issue to WIP, record production, inspect, put away.
See guides 03, 04, 05 and 13.

The plan stays as the record of why those works orders exist and what demand they were
raised against. When somebody asks in three weeks why four hundred were made, this is the
answer.

## Common questions

### The available quantity looks wrong

It is read from the warehouse you set in step 3. Material sitting in a different warehouse
is not counted, which is usually the explanation.

### It wants to buy something we already have plenty of

Check the warehouse again, and check whether the stock is in a WIP warehouse rather than
stores. A plan can only see where you point it.

### Can I plan without sales orders?

Yes — leave Get Items From unset and add the finished items and quantities by hand. That
is the normal way to plan a make-to-stock run or a forecast.

### I raised the works orders and then the demand changed

Cancel the works orders that are not needed. The plan itself is a record and stays; it is
not a live document that keeps re-planning.
