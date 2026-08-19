# Fuse_Manufacturing — workflow document

One entry per process. **Four columns:**

| Trigger | Steps in ERPNext | What posts to Intacct, and when | On failure |
|---|---|---|---|

The last column is the one everyone skips and the one that decides the build. Because
Intacct posts first and there is no local-only outcome, "on failure" is not an edge case —
it is the normal path whenever the gateway rejects, times out (15 min), or queues behind the
~5 concurrent connections per company.

## Processes to cover (minimum)

1. Goods receipt
2. Put-away
3. Manufacture
4. Handoff between stages
5. Warehouse transfer
6. Stock adjustment
7. Pick and delivery

---

## STATUS

Row 1 (goods receipt) is written, from a study of the donor on 2026-08-18. The rest
are still blocked on enumeration — see the note at the foot of this file.

---

### Goods receipt (receiving)

**Source:** the donor's `Receiving.aspx` / `Receiving.aspx.cs` and
`Classes/Intacct/IntacctReceiverStore.cs`, read 2026-08-18. Intent only — the screen
does not port.

**The thing to understand first:** the donor does **not** receive locally and tell
Intacct afterwards. It builds an Intacct **PO Receiver** and posts it as a
*conversion of the purchase order*, then commits its own stock. That is the same
contract Fuse already runs on — Intacct posts first — so receiving is not an
exception to the model, and the current blanket refusal is a bigger decision than it
looked.

**Trigger:** goods arrive against a purchase order. A storeman opens the PO on the
receiving screen. One receipt covers one PO.

**Steps in ERPNext:**

1. Open the mirrored Purchase Order. Lines are refreshed from the source first, and
   anything that changed since last time is surfaced as a banner rather than applied
   silently.
2. Per line: quantity received, destination warehouse, and — where the item is
   tracked — a lot number with its piece count, note and expiry. A reject quantity is
   captured on the same line.
3. A scan jumps straight to the first PO line matching that item code and opens it
   for capture. This is the whole reason the flow is scanner-shaped.
4. "Receive all" fills every outstanding line at its full remaining quantity.
5. Nothing has moved yet. Every line above is staged; the receipt is a draft until
   the storeman finishes it.
6. Finish: capture the supplier invoice / delivery-note number and the receipt date,
   then submit.

**What posts to Intacct, and when:** on finish, one `create_potransaction` with
definition **`PO Receiver-Inventory`**, carrying
`createdfrom = "Purchase Order-Inventory-<PO number>"`. That linkage is what moves the
PO to Partially Converted / Converted, which is what the PO sync filters on.

Per line: `SourceLineRecordNo` = the PO line's `PODOCUMENTENTRY.RECORDNO` (this is the
join, not the item code), `ITEMID`, quantity, unit, `WAREHOUSEID`, and `LOCATIONID` on
**every** line. Header carries the vendor, the transaction date, and the supplier
invoice number as both vendor document number and reference.

Three details that are not optional:

- **Rejects are their own receiver line**, same source PO line, quantity into the
  reject warehouse. The donor notes it has not confirmed Intacct accepts the split
  when one line is both accepted and rejected — verify before relying on it.
- **Bin-tracked items must carry a bin**, resolved as the lowest `BINID` on the
  receiving warehouse, cached per warehouse. No bin on the warehouse is a hard failure,
  not a silent omission.
- **Lot detail only for items Intacct actually lot-tracks.** Sending a lot for an
  untracked item is rejected with BL03001974.

**On failure:** the receipt does not stand. Nothing local is committed, because the
Intacct post happens before the stock does. Specific cases the donor learned to name:

| What happened | What the storeman sees |
|---|---|
| PO already received in Intacct ("already converted") | Told plainly that this PO was already received, and no second receiver is created |
| A second click during the post | Refused — the header is marked submitted before the stock commits |
| Supplier invoice number already used | Refused before anything posts |
| No line has a receive quantity | Refused — Intacct rejects an empty receiver with "potransitems: Missing child element" |
| A received line has no warehouse | Refused, naming the line |
| Rejects captured but no reject warehouse configured | Refused, naming the setting |
| Marking the PO complete with quantities outstanding | Confirm first, and say plainly that the rest of the PO will be closed |

---

## What this means for Fuse

Receipting is currently **refused outright** (`postings.block_goods_receipt`, decision
2026-08-06). That decision reads "goods are received in Intacct" — which is true of
where the *receiver document* lands, but not of where the *work* happens. In the donor
the work happens on the receiving floor, and Intacct receives a PO Receiver as a
result.

Replicating this therefore means deliberately removing the block, together with the
posting that replaces it — exactly the condition the original decision set for its own
removal. Not yet done, and not to be done by half: a Purchase Receipt that submits
without posting a PO Receiver would add stock Intacct never saw.

**Unverified against `leadertread`:** whether `PO Receiver-Inventory` exists and is
active on this company, and whether its numbering scheme is attached. The donor ran
against a different company and the decision log already warns that definitions drift.
Read `PODOCUMENTPARAMS` before building.

**Related, not built:** the donor also has `IntacctPutAwayStore` and
`IntacctWarehouseTransferStore`. Put-away is the natural follow-on to receiving and is
listed as row 2 below.

---

## STATUS: the remaining rows — blocked on enumeration

Nothing is written below yet, deliberately. Filling these rows requires reading the two live
systems rather than assuming:

- **ERPNext** — enumerate Module Def, DocType, Report on the actual instance. The site
  now exists (Leader Rubber Company, `frappe-leader`); the note here that no instance
  existed was true on 2026-08-06 and is not any more.
- **Intacct** — read `leadertread-DEV` from the gateway: active transaction definitions
  (`SODOCUMENTPARAMS` / `PODOCUMENTPARAMS` / `INVDOCUMENTPARAMS`), the four manufacturing
  entry definitions, `LOCATIONENTITY` list, UOM strings. Credentials are in `IntacctConfig.cs`
  on the C# workstation and have not been brought across.

Whether delivery relieves stock quantity separately from the invoice changes where the
selling boundary sits — so row 7 in particular cannot be written from assumption.

---

## Template for each row

```
### <Process name>

**Trigger:** what starts it, and who does it

**Steps in ERPNext:** the doctypes and states, in order

**What posts to Intacct, and when:** the exact function and definition name, the moment it
fires (on submit / on save / on completion), and what carries the cost

**On failure:** what the user sees, what state the ERPNext document is left in, whether it
retries, and who finds out
```
