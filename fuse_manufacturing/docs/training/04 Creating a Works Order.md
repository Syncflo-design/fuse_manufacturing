# Creating a Works Order

*Raising an instruction to make something — Fuse Manufacturing user guide 04*

> This guide covers **raising** a works order. Recording what you actually made against
> one is a separate job, covered in **Works Orders — recording production**.

## Before you start

### What a works order is

An instruction to make something: which item, how much of it, and from what recipe. It
is raised before production starts and stays open until the full quantity has been made.

Raising one does not move any stock. Nothing happens in Fuse or in Sage Intacct until
somebody records production against it.

### Who raises them

Whoever plans production — a supervisor or planner. The person who *fulfils* the order is
usually not the person who raised it, which is why these are two different guides.

### Where the recipe comes from

Every works order points at a **BOM** — the recipe. On this site, BOMs are Sage Intacct
kits, brought across by the kit sync. You cannot create or edit a BOM in Fuse; the New
button is not there and an attempt is refused.

If a recipe is wrong or missing, it is fixed in Intacct as a kit, and the next sync
brings it across.

### Before you raise one

- Know **what** you are making and **how much**.
- Know **when** it is needed.
- Check the recipe exists — if the item has no BOM, the works order cannot be raised.

## Raising the works order

1. On Fuse Home, click **Works Orders**.
2. Click **+ Add Work Order** at the top right.
3. Fill in:

| Field | What to put |
|---|---|
| Item To Manufacture | The finished item. The BOM fills in by itself if the item has a default one. |
| BOM No | The recipe. Leave it alone unless the item has more than one and you mean to use another. |
| Qty To Manufacture | How much you are instructing them to make. |
| Company | Already set. Leave it. |
| Target Warehouse | Where the finished goods will be put. |
| Source Warehouse | Where the components will be taken from. |
| Planned Start Date | When production is expected to begin. |
| Expected Delivery Date | When it is needed by. |

> **Screenshot 1 — A new works order**
> *[to be inserted: the Work Order form with item, BOM and quantity filled in]*

4. Click **Save**. The order is a draft — it changes nothing and can be edited or
   deleted freely.
5. Read the **Required Items** table. Fuse has worked the components out from the recipe
   for the quantity you entered.
6. Click **Submit**.

> **Screenshot 2 — Required items worked out from the recipe**
> *[to be inserted: the Required Items table on a saved works order]*

## What happens after you submit

The order moves to **Not Started** and appears on the shop floor's list of open orders.
Still nothing has moved — it is an instruction, not a movement.

| Status | What it means |
|---|---|
| Draft | Saved but not submitted. Nobody can produce against it. |
| Not Started | Submitted and waiting. Ready to be produced against. |
| In Process | Some production has been recorded, but not the full quantity. |
| Completed | The full quantity has been made. It drops off the default list. |
| Stopped | Deliberately halted. Nothing more can be recorded against it. |

## Two things that are fixed once you submit

**The required items list.** On this site the components on a submitted works order
cannot be edited. That is deliberate, and it is not a limitation: substitutions belong to
the *run*, not the instruction. When the floor is short of something they change it on
the Manufacture entry when recording production, which affects that run only and leaves
the recipe and the works order alone.

**The recipe.** Changing the BOM afterwards does not change a works order already raised.
It carries the components it was raised with.

If the quantity or the item is genuinely wrong, **stop the order and raise a new one**
rather than trying to bend it.

## What the floor can change, and what it cannot

You are raising an instruction. The people making it record what actually happened, and
those are not always the same thing — so it is worth knowing exactly how far they can
depart from what you wrote.

**On the works order itself: nothing.** Once you submit, the required items are fixed.
Nobody on the floor can edit the order you raised.

**On the production run: quite a lot, and deliberately so.** When they record production,
Fuse opens a Manufacture entry pre-filled from the recipe, and on that entry they may:

- change a **quantity**, where more or less went in than the recipe says
- **substitute** an item, by changing the item code on a row — they ran short and used
  something else
- **add a row**, for something that went in which the recipe does not have at all
- **remove a row**, or set it to zero, for something that was not used

All four apply to **that run only**. None of them touches the BOM, the Intacct kit, or
this works order. The next order for the same item starts from the original recipe.

**Why it works this way.** The cost of the finished goods is worked out from what was
actually consumed. If the floor could not record a substitution, they would have to record
the recipe instead — and the cost would be wrong from that point on, with nothing to show
it. A works order that cannot be departed from produces accurate paperwork and inaccurate
costs.

**What this means for you.** If you find substitutions happening on the same item run
after run, the recipe is wrong — fix the kit in Intacct rather than leaving the floor to
correct it every time. The Manufacture entries are the record of what really happened, and
they are worth reading for exactly this.

## Producing in stages

One works order can be produced against many times. An order for 100 kg can be recorded
as 40 today and 60 tomorrow; it stays In Process until the full quantity is made.

You do not raise a separate works order per shift.

## Stopping or closing an order

If an order is abandoned, open it and use **Stop**. It can no longer be produced against,
and it comes off the shop floor's list.

Do not delete a submitted works order. Stopping keeps the record of what was intended and
what was made against it; deleting throws that away.

## If something goes wrong

| What you see | What it means and what to do |
|---|---|
| No BOM found for the item | The item has no recipe. It is created in Intacct as a kit, then the kit sync brings it across. |
| BOM is not active / not submitted | The recipe exists but is not usable. Check the kit in Intacct and re-run the sync. |
| Item To Manufacture is not a stock item | You have chosen something Intacct does not hold stock for. Check the item. |
| The Required Items table is empty | The BOM has no components. Fix the kit in Intacct. |
| Recipes come from Intacct on this site | You have tried to create or edit a BOM. Recipes are kits, changed in Intacct. |
| Cannot edit the required items | Correct on this site. Substitute on the Manufacture entry when recording production instead. |

## Quick reference

Fuse Home → Works Orders → Add Work Order → item, quantity, warehouses, dates → Save →
check Required Items → Submit.

| Question | Answer |
|---|---|
| Does raising one move stock? | No. Nothing moves until production is recorded. |
| Can I change the recipe here? | No. BOMs are Intacct kits. |
| Can I change the components on the order? | Not once submitted. Substitute per run instead. |
| Can one order be produced in parts? | Yes. It stays open until the full quantity is made. |
| How do I cancel one? | Stop it. Do not delete it. |
| Who records what was made? | The shop floor — see the recording production guide. |
