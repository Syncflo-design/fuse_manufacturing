# Material Request

*Asking for material to buy, move or make — Fuse Manufacturing user guide 15*

## Before you start

### What a material request is

Somebody needs something they have not got. A material request is the record of the ask:
what, how much, where it is wanted, and by when.

It does not move any stock and it does not buy anything. It states a need, so that
whoever fulfils it is working from a written request rather than a message.

### The three kinds

You choose one when you raise it, and it changes who acts on it:

| Type | What it means | Who picks it up |
|---|---|---|
| Purchase | Buy this | Whoever raises purchase orders — in Intacct |
| Material Transfer | Move this from another warehouse | Stores |
| Manufacture | Make this | Planning, usually through a production plan |

### Where it stops

On a site integrated with Intacct, **purchase orders are raised in Intacct**, not here.
A purchase request is the requisition step: it records what was asked for and by whom, and
somebody acts on it there. It does not become a purchase order by itself.

That is deliberate. Buying commits money, and money is Intacct's job.

> **Screenshot 1 — Fuse Home with the Material Request tile**
> *[to be inserted: Fuse Home, reference row, Material Request tile]*

## Raising a request

1. On Fuse Home, click **Material Request**, then **Add Material Request**.
2. Choose the **Purpose** — Purchase, Material Transfer, or Manufacture.
3. Set **Required By**. Be honest about it; a date everyone knows is invented gets ignored,
   and then the real ones do too.
4. Add a row per item:

| Column | What goes in it |
|---|---|
| Item | What is needed |
| Quantity | How much |
| Warehouse | Where it is wanted, not where it might come from |
| Required By | Per line, if some are more urgent than others |

5. Save, then **Submit**.

> **Screenshot 2 — A material request for three items**
> *[to be inserted: Material Request with three rows and a required-by date]*

## After it is submitted

The request sits open until it is fulfilled. What "fulfilled" means depends on the type:

- **Purchase** — someone raises the order in Intacct. Once received, the receipt in Fuse
  is what puts the stock on the shelf. See guide 07 Receiving.
- **Material Transfer** — stores records a warehouse transfer. See guide 02.
- **Manufacture** — planning explodes it into works orders, usually through a production
  plan. See guide 17.

## Common questions

### Can I turn the request into a purchase order here?

No, and that is by design. Orders are raised in Intacct and mirrored back into Fuse
read-only so the warehouse can receive against them. What Fuse holds is the request and
the receipt; Intacct holds the commitment.

### Nobody is acting on my request

It is a document, not a message. Check who is meant to be watching the list on your site —
that is usually a planner or a buyer with a saved filter — and tell them it is there.

### How do I see what is still outstanding?

Open the Material Request list and filter by status. Anything not Stopped or fully
fulfilled is still a live ask.
