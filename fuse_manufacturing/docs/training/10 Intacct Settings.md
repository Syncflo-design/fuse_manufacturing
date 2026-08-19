# Intacct Settings

*The connection to Sage Intacct, and what each part of it controls — Fuse Manufacturing
administrator guide 10*

> This guide is for administrators. **Do not share screenshots of this page without
> blanking the credential fields first.**

## Before you start

### What this page is

One page holding everything Fuse needs to talk to Sage Intacct, plus the few choices
that cannot be read from Intacct.

The governing rule is worth knowing before you change anything: **Intacct is the golden
source.** Almost everything here is either a credential or a mapping onto something
Intacct already holds. Where Fuse can read a value from Intacct, it does — it does not
ask you to type it.

Find it by typing **Intacct Settings** in the search bar.

## Enabled, and Post Stock Movements

Two switches at the top, and they do different jobs.

**Enabled** is the master switch. With it off, every call to Intacct raises an error
instead of going out. Use it when the connection must be stopped entirely.

**Post Stock Movements to Intacct** controls whether movements are sent. With it off,
Fuse records stock locally and Intacct hears nothing. That is the right setting while a
new site is syncing its masters and nobody should be posting yet — and the wrong setting
for a live site, because the two systems then drift apart silently.

The shop floor screens show a red banner whenever it is off, so an operator is never
recording into a system that is not posting without being told.

> **Screenshot 1 — The two switches**
> *[to be inserted: top of Intacct Settings]*

## Credentials

Five values, in two groups: the **sender** pair identifies Fuse to the Intacct gateway,
and the **company** trio identifies which Intacct company to sign into.

| Field | What it is |
|---|---|
| Sender ID / Sender Password | Issued by Sage for the gateway itself |
| Company ID | The Intacct company, e.g. a live company or an `-imp` test one |
| User ID / User Password | The Intacct web services user Fuse signs in as |

These come from whoever administers your Intacct company. **They are never written down
in a document, an email or a chat message** — including this guide.

> **Screenshot 2 — Credentials, values blanked**
> *[to be inserted: the Credentials section with every value obscured before sharing]*

## Entity

**Entity ID (locationid)** is the Intacct entity Fuse signs into, and it is sent on
every request.

It matters more than it looks. Intacct's manufacturing definitions are set to "Entity
only", so signing in at the top level is rejected — with an error that reads like a
credentials problem rather than an entity one. The entity also differs between
companies: a test company and a live one will not share the same value.

## Defaults

**Default Item Group** — Intacct has no concept that maps onto ERPNext item groups, so
synced items land here.

**Receiving Rejects Warehouse** — where damaged goods go when a delivery is received.
This is the one field on the page not read from Intacct: Intacct does not record which
of its warehouses is the reject one, so it is a Fuse routing choice. The warehouse itself
still comes from Intacct like every other.

Leave it empty and receiving refuses a rejected quantity, rather than quietly putting
damaged stock back into good stock.

## Transactions

Which Intacct definition each Fuse process posts to.

Every Intacct company names these differently. Leadertread's goods receipt is called
*Goods received voucher*; another company calls the same thing something else entirely.
A name that is right for one client is simply wrong for the next, and the rejection it
causes names no field — so nothing here is defaulted from another client.

| Column | What it is |
|---|---|
| Process | The Fuse job — receiving, the production legs, and so on |
| Intacct Definition | Which of this company's definitions it posts |
| What it posts | Plain English description of the document created |

The picker lists what **this** company actually has. If it is empty, the definitions have
not been read yet — run the definitions sync (below) and they appear.

**A process with nothing mapped refuses to post.** That is deliberate: the alternative is
sending a definition name borrowed from somebody else's company.

> **Screenshot 3 — The Transactions table**
> *[to be inserted: process rows with the definition picker open]*

## Active Modules

Which parts of Fuse this client uses. Untick one and its tile disappears from Fuse Home,
the role loses access to the documents behind it, and the action itself refuses with a
message naming the module.

Switching a module off is safe and reversible — nothing is deleted, and ticking it again
restores access immediately.

> **Screenshot 4 — Active Modules**
> *[to be inserted: the module list with the tick column]*

## Tuning and Status

**Query Page Size** — how many records are read per request. Intacct's own guidance is
to stay under about 1000; larger pages tend to time out rather than fail cleanly.

**Max Attempts** — how many times a transient failure is retried. A genuine rejection is
never retried.

**Request Timeout** — seconds before a call is abandoned.

The **Status** section is read-only and shows when the last sync ran and what it
returned. It is the first place to look when data seems stale.

## Keeping it in step

| Job | What it does |
|---|---|
| `masters.sync_transaction_definitions` | Reads this company's definitions so the Transactions picker is populated |
| `masters.sync_purchase_orders` | Refreshes mirrored orders and their line keys |
| `masters.sync_items` | Items, barcodes and tracking flags — runs hourly |
| `install.after_install` | Re-applies fields, roles and the settings tables. Safe to run at any time |

## If something goes wrong

| What you see | What it means and what to do |
|---|---|
| No Intacct definition is mapped for a process | Set it under Transactions. If the picker is empty, run the definitions sync first. |
| Login rejected, BL01001973 | The entity is missing or wrong. Manufacturing definitions are entity-only. |
| A movement recorded but nothing in Intacct | Post Stock Movements is off. |
| The Transactions picker is empty | The definitions have never been read for this company. |
| Everything worked yesterday, nothing today | Check Status for the last sync result before changing any setting. |

## Quick reference

| Task | Where |
|---|---|
| Stop all Intacct traffic | Untick Enabled |
| Stop posting but keep syncing | Untick Post Stock Movements |
| Point receiving at the right document | Transactions → Receiving goods |
| Turn a feature off for this client | Active Modules |
| Send damaged goods somewhere | Defaults → Receiving Rejects Warehouse |
