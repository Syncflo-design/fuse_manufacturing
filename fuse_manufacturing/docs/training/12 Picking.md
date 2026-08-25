# Picking

*Sending goods out against a customer order — Fuse Manufacturing user guide 12*

## Before you start

### What picking is

A customer has ordered goods. Picking is where you record what actually went out the door:
how much of each line, from which warehouse, and — where the item is tracked — which bin
and which lot.

Recording it does two things at once. The stock leaves Fuse, and a shipper is created in
Sage Intacct against the same order. Intacct goes first, so the two systems cannot
disagree about a despatch.

### Where the orders come from

**Sales orders are never created in Fuse.** They are raised in Intacct and mirrored here
read-only, so the warehouse can see what is due to go out. You can pick against one; you
cannot edit it, and you cannot invent one.

If an order you expect is not in the list, it is not open in Intacct. Check there rather
than looking for a way to add it here.

### What Fuse posts, and what it does not

Picking relieves **quantity only**. The invoice is still raised in Intacct, against the
shipper this creates. That split is deliberate: the warehouse says what went out, and
accounts decide what to charge for it.

### Before you pick anything

- Have the order number or the customer's name.
- Know what is actually going on the vehicle, not what was ordered.
- For lot-tracked items, know which lot you are shipping. It is what makes a recall
  possible later.

> **Screenshot 1 — Fuse Home with the Picking tile**
> *[to be inserted: Fuse Home, Quick Launch row, Picking tile]*

## Finding the order

1. On Fuse Home, click **Picking**.
2. A list opens showing every order still expecting a despatch: the Intacct order number,
   the customer, when it was ordered, when it is due, and how much has gone so far.
3. Use the search box. It matches the Intacct order number, the Fuse order number and the
   customer's name, so whatever is on the paperwork in your hand will find it.
4. Click the row.

A fully despatched order drops off the list. The list is what is still to go, not a
history.

> **Screenshot 2 — Orders awaiting despatch**
> *[to be inserted: Picking screen, order list]*

## Recording the despatch

### Step 1 — Read the lines

The order opens with one row per ordered line:

| Column | What it tells you |
|---|---|
| Item | The item code and its description |
| Ordered | How much the customer asked for |
| Already picked | How much has gone on earlier despatches |
| Still to go | The difference, and the figure to check against the vehicle |
| Picking | What you are sending now — the only column you fill in |

### Step 2 — Enter what is going

Type the quantity against each line. Leave a line at zero if none of it is going today;
the order stays open for the rest.

You can send more than was ordered only if the site allows over-delivery, and only up to
the tolerance an administrator has set. Beyond it the despatch is refused, which is the
right answer — a customer who ordered a hundred did not agree to two hundred.

> **Screenshot 3 — Entering picked quantities**
> *[to be inserted: Picking screen, order lines with quantities entered]*

### Step 3 — Bins and lots

Where an item is tracked in Intacct, two extra fields appear on the line:

- **Bin** — which bin the stock was picked from. If your warehouse has a default, it is
  filled in for you and you only change it when the pick came from somewhere else.
- **Lot** — which lot went out. Required on a lot-tracked item; the despatch is refused
  without it, because a lot nobody recorded is a recall nobody can trace.

### Step 4 — Scanning

Click **Scan Barcode** and scan the item, the bin label or the pallet. Fuse recognises
which of the three it is and fills the right field. Scanning the same item twice increases
the quantity rather than adding a row.

> **Screenshot 4 — Scanning a pick**
> *[to be inserted: Picking screen with the scan field active]*

### Step 5 — Quality, where it applies

If an item is set to be inspected before delivery, the line asks for an inspection before
it will go.

- No inspection at all — the despatch is refused and the line is named.
- An inspection that failed — also refused. Product that did not meet its own
  specification does not leave on this document. Releasing it anyway is a concession, and
  that is a decision someone makes deliberately, not something to nod past on a phone.

Record the inspection from the line itself. See guide 13 Quality Inspection.

### Step 6 — Submit

Click **Submit**.

Fuse creates a delivery note and posts a shipper to Intacct against the ordered lines. If
Intacct accepts it, the goods have gone in both systems. If it refuses, nothing stands
here either and the reason is shown.

> **Screenshot 5 — A submitted despatch**
> *[to be inserted: submitted delivery note with the Intacct key]*

## After it is submitted

The delivery note carries the Intacct document key. The order in Intacct now shows the
quantity despatched, and accounts can invoice against the shipper.

## Common questions

### The order is not in the list

It is either fully despatched, or not open in Intacct. The list only shows what is still
to go.

### The customer wants part of the order now and the rest later

Enter what is going today and submit. The order stays open for the balance and appears in
the list again tomorrow.

### I have picked the wrong thing

Cancel the delivery note. The shipper is reversed in Intacct as a new document and the
ordered line goes back to outstanding. Then pick it again correctly.
