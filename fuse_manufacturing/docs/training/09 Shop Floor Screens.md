# Shop Floor Screens

*Fuse on a phone or tablet — Fuse Manufacturing user guide 09*

## Before you start

### What these screens are

The same jobs as the desk forms, shaped for someone standing at a machine with gloves
on: big buttons, one thing per screen, and a box that takes a scan.

Nothing here is a different system. A batch confirmed on a phone creates exactly the
same document as one confirmed at a desk, and it reaches Sage Intacct the same way.

### Getting to them

On a phone, open Fuse and go to **Shop Floor**. There are four things you can do:

| | What it is for |
|---|---|
| **Works Orders** | Record what you made against a works order |
| **Issue to WIP** | Move components from a store onto the floor |
| **Item Transfer** | Move stock between warehouses |
| **Receiving** | Book a delivery in against a purchase order |

> **Screenshot 1 — The Shop Floor menu**
> *[to be inserted: /app/fuse-floor on a phone-width screen, four tiles]*

### Installing it as an app

You do not have to find it in a browser every time.

- **Android:** open the Shop Floor screen in Chrome, then Chrome's menu → **Install app**
  (or *Add to Home screen*). You get a Fuse icon that opens straight to these screens.
- **iPhone / iPad:** Safari's share button → **Add to Home Screen**.

Once installed it opens in its own window with no address bar, which is a lot more usable
at arm's length.

> **Screenshot 2 — The installed icon on a phone home screen**
> *[to be inserted: home screen showing the Fuse icon]*

### The red banner

If a red banner says posting to Intacct is switched off, stop and tell your supervisor.
Anything recorded while it is showing moves stock in Fuse and nowhere else.

## Works Orders — recording production

1. Tap **Works Orders**. The open orders are listed with how much is still to make.
2. Tap the order, or scan its number if it is printed on the job card.
3. Enter **how much you actually made**. It can be less than the order.
4. Fuse works out the components from the recipe and shows them.
5. **Correct anything that differed.** What is shown is what the recipe says; what you
   record should be what really went in. Setting a component to zero drops it.
6. Tap **Record the run**.

> **Screenshot 3 — Confirming what went in**
> *[to be inserted: the component list with editable quantities]*

The finished cost is worked out from what was actually consumed. Accept the recipe when
it was not followed and the cost is wrong from that point on, with nobody downstream able
to tell.

You do not have to record a whole order at once. Record 40 of 100 and the order stays
open with 60 to go.

## Issue to WIP and Item Transfer

Both move stock, and both work the same way.

1. Choose the **From** and **To** warehouses. Your last choice is remembered, so the
   second move of a shift is far quicker.
2. **Scan or type an item.** One match goes straight to the quantity; several show a list.
3. Enter the quantity and tap **Add**. The line joins the list at the bottom.
4. Add as many items as you need, then tap **Record**.

> **Screenshot 4 — Items added to a transfer**
> *[to be inserted: the basket with two or three lines and the Record button]*

Tap the × on a line to take it off before recording.

## Receiving

Covered in full in guide 06. On a phone it is the same three steps: find the order,
scan the items in, then finish with the delivery note number.

## If something goes wrong

| What you see | What it means and what to do |
|---|---|
| Nothing matches what you scanned | The code is not an item, or not one this screen can use. Check you scanned the right label. |
| That item is not on this order | You are receiving, and the scanned item was not ordered on the order you opened. |
| From and to are the same warehouse | Choose a different destination. |
| Not enough stock | The item is not in the source warehouse in that quantity. If components were issued to the floor, they are in a WIP warehouse, not the store. |
| The green button is greyed out | Nothing has been added yet. |
| Posting to Intacct is switched off | Stop and tell your supervisor. |

## Two rules that apply to everything in Fuse

### It is not recorded until you tap the green button

Everything you add is held on the screen until then. Nothing has moved.

### Cancel, never delete

If you record something wrongly, tell your supervisor. Movements are reversed in Intacct
first so both systems return to where they were — entering an opposite movement instead
leaves two wrong movements in the history rather than none.

## Quick reference

| Question | Answer |
|---|---|
| Do I need a scanner? | No. Every screen takes a typed code as well. |
| Why does it remember my warehouses? | So the second job of a shift is three taps. |
| Can I record part of a works order? | Yes. The rest stays open. |
| Can I change a component to a different item? | Not on the phone yet — use the desk form. |
| Does it work offline? | No. Every screen sends the movement to Intacct as you record it. |
