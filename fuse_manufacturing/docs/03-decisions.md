# Architecture decision log — Fuse_Manufacturing

Newest at the bottom. One entry per decision.

Template:

```
## YYYY-MM-DD — <decision in one line>

**Context:** what forced the choice
**Decision:** what we're doing
**Why:** the reasoning that would otherwise be lost
**Alternatives rejected:** and why
**Consequences:** what this locks in or makes harder
```

---

## 2026-08-06 — Repo created as `C:\ClaudeCode\Fuse_Manufacturing`

**Context:** "Fuse" already names the ASP.NET WebForms app at
`\\Syncflo-desktop\f\Manifold\Intacct_Fusion Manufacturing`.
**Decision:** The ERPNext build lives in `Fuse_Manufacturing` (Russell's choice, "for now" —
treat as provisional).
**Consequences:** The Frappe app name cannot carry capitals — it will be `fuse_manufacturing`
at `bench new-app` time, so folder and app name won't match exactly. Decide before scaffolding
whether to rename the folder to match.

## 2026-08-06 — ERPNext replaces the WebForms Fuse; this is NOT a cutover

**Context:** Fuse works and is proven against a live Intacct company, but everything it
hand-builds (works orders, BOM explosion, backflush, WIP) ERPNext ships as standard.
**Decision:** Retire Fuse. Rebuild on ERPNext. Fuse is the **requirements document, not the
template** — port intent, never screens.
**Why:** Fuse has only ever run in a dev environment. **Nothing is live: no data to migrate,
nobody to retrain.** That is exactly why the switch happens now rather than later.
**Consequences:** No migration workstream, no parallel run, no rollback plan needed. Where
ERPNext does something natively, use ERPNext — Fuse's version is an SBMS workaround.
Its .NET SDK transport does not port; the gateway approach does.

## 2026-08-06 — XML gateway, not REST

**Decision:** Post XML to `https://api.intacct.com/ia/xml/xmlgw.phtml`.
**Why:** REST forces every customer through app registration in the Sage developer portal.
The XML gateway needs only a sender ID plus company credentials — which is what makes this
a product rather than a per-customer install.
**Consequences:** We own the envelope. All gateway constraints in `02-intacct-integration.md`
apply — entity-only login, `RECORDNO` paging, concurrency limits, exact UOM strings.

## 2026-08-06 — Python inside Frappe, no middleware

**Decision:** Python/`requests` inside the Frappe app. No .NET middleware, no proxy service.
**Why:** Errors surface in the request that caused them; retries and scheduling come free
from Frappe's queue; per-client config lives in DocTypes.
**Alternatives rejected:** A .NET service — it would add a deployment, a log to check, and a
place for failures to hide.

## 2026-08-06 — Intacct posts first, always

**Decision:** If Intacct rejects the post, the ERPNext transaction does not stand. ERPNext
never invents a value; it records the cost Intacct accepted. Live, never batched.
**Why:** Any local-only outcome creates a divergence someone has to reconcile by hand, which
is precisely the failure mode the product exists to remove.
**Consequences:** Every ERPNext submit that has a financial consequence is gated on a
synchronous gateway call. The **"On failure"** column of the workflow document is therefore
the column that decides the build.

## 2026-08-06 — Theme lives in its own Frappe app

**Decision:** Intacct visual language ships as a separate app from the integration app.
**Why:** Not every client wants the Intacct look, and cosmetic changes must not force an
integration release.
**Consequences:** Style only — colour, typography, density, nav, buttons. **Do not restructure
form layouts** to mimic Intacct screens; that fights the framework every release.
Precedent app: `nest_theme`.

## 2026-08-06 — Exactly two custom apps

**Decision:** Two Frappe apps, no more.

1. **`fuse_theme`** — Intacct visual language only. Colour, typography, density, nav, button
   treatment. Precedent: `nest_theme`.
2. **`fuse_manufacturing`** — everything else: the Intacct XML gateway client, masters mirror,
   postings, custom DocTypes, per-client config, roles and permissions, mobile scanner flows,
   and all code that would otherwise be hand-entered on a site.

**Why:** the theme releases on a cosmetic cadence and not every client wants the Intacct look;
the integration app releases on a correctness cadence. Keeping them apart means a colour tweak
never triggers an integration release, and vice versa.

**Consequences — the thing to hold the line on:** anything typed into a *site* rather than
committed to the app (Server Scripts, Client Scripts, Property Setters, Custom Fields, Role
Permission Manager changes) is invisible to git, does not deploy, and is lost on a rebuild.
Rule: **if it is behaviour, it ships in `fuse_manufacturing` as code or as a fixture.**
Site-side scripting is for spikes only, and gets migrated into the app before it counts as done.

## 2026-08-06 — Perpetual inventory OFF: ERPNext tracks quantity, Intacct holds value

**Context:** the Leadertread company was created with `enable_perpetual_inventory = 1`
and valuation FIFO. That makes ERPNext write its own GL entries — Stock In Hand, Stock
Adjustment, COGS — at its own FIFO valuation, while Intacct values the same stock on
average cost and holds the real books.

**Decision:** turn perpetual inventory **off**, per company. ERPNext tracks quantities;
Intacct holds value. Set on Leader Rubber Company 2026-08-06, and the default for every
new client instance.

**Why:** two systems both valuing the same stock will diverge — not might, will, because
FIFO and average cost are different methods answering the same question. Someone opens a
stock value report, sees a number that disagrees with the accounts, and now nobody trusts
either. Reconciling that is precisely the manual work this product exists to remove.

**Alternatives rejected:** mirror the chart of accounts and treat ERPNext's ledger as an
unofficial shadow — the shadow still gets read, and still gets believed. Reconciling the
two — that is the failure mode, not the fix.

**Consequences:**
- ERPNext stock **value** reports go blank. Quantity reports are unaffected.
- Do this **before any stock movement exists.** ERPNext will not let the flag be toggled
  once stock ledger entries are on the books.
- The chart of accounts (Intacct → ERPNext) becomes a later question, needed only if
  ERPNext ever has to report on value rather than quantity. Reversible by design.

## 2026-08-06 — Intacct is the golden source for locations; ERPNext mirrors its grain

**Context:** ERPNext's Warehouse is a nested tree, so Location → Warehouse → Zone → Aisle
→ Bin could all be Warehouse nodes with stock tracked at the leaf — finer than Intacct,
which holds stock per warehouse with bin as line detail.

**Decision:** Do **not** do that. Mirror Intacct's grain exactly:
- One ERPNext Warehouse per Intacct WAREHOUSE.
- Bins mirrored into an `Intacct Bin` DocType, read-only, one row per Intacct bin.
- No warehouse, bin or location is created or edited in ERPNext. They are managed in
  Intacct and synced down.

**Why:** a finer-grained ERPNext picture would disagree with Intacct the moment anything
moved, and reconciling two different grains is exactly the manual work this product
exists to remove. Less granular and identical beats more granular and divergent.

**Consequences:**
- The bin mirror deletes rows that no longer exist in Intacct. It is a mirror, not an archive.
- Preventing manual creation is a **permissions** job, not code: the Stock Controller
  role gets read-only on Warehouse. Do not write a guard hook for it — ERPNext itself
  creates warehouses during company setup and a blanket block would fight that.
- If bin-level stock visibility is ever genuinely needed, it is a new conversation, not
  a quiet change of grain.

## 2026-08-06 — Generic Intacct methods first; custom definitions are a last resort

**Decision:** Use Intacct's own transaction definitions and standard functions wherever
they do the job. Create a custom definition only when a generic one genuinely cannot,
and **write down why** — here, plus a note in `02-intacct-integration.md`.

**Why:** every custom definition is a per-client configuration step, a thing that can
drift between DEV and live, and a thing the next person has to discover. The donor
already showed the cost of the opposite habit: it posted all works-order movement as
generic stock adjustments because SBMS couldn't do better, and that is precisely the
workaround being retired.

**Consequences:** before building a posting, check what Intacct already ships —
`create_whtransfer` for transfers, the four manufacturing definitions, conversions via
`createdfrom`. Reach for a new definition only after that check fails.

## 2026-08-06 — Mobile / barcode scanner flows are a first-class target

**Decision:** The scanner flows carry over from the donor. Build the posting layer so
they are reachable from a lightweight mobile page, not only from a desk form.

**Why:** the donor has a working mobile/barcode version and the client's people already
use it. Retrofitting mobile onto logic buried in desk form hooks means writing it twice.
See [[barcodes-mobile-only]] — barcodes are a mobile-only feature, not a desktop one.

**Consequences:** posting logic lives in plain whitelisted functions taking explicit
arguments, not in `on_submit` handlers that assume a fully-populated desk document. The
desk form and the scanner page both call the same function.

## 2026-08-06 — Point at `leadertread-DEV`

**Decision:** The Leadertread ERPNext site's Intacct Settings target the **DEV** company,
not `leadertread-imp`.
**Why:** the posting layer has to be proven — production run, goods receipt, warehouse
transfer, stock adjustment, all correctly costed — without touching the live company.
**Consequences:** a dev company's configuration drifts from live, so the live company's
transaction definitions must be re-read before any go-live date is committed. The entity
ID must also be confirmed against DEV: the donor's `E100` was set alongside the live
company block and is not verified to exist in DEV.

## 2026-08-06 — 1 client = 1 ERPNext instance = 1 Intacct company

**Decision:** One credential set per instance. Company → entity (`locationid`) → location.
Entity ID stored against each ERPNext Company, sent as `<locationid>` on every login.
**Why:** Manufacturing transaction definitions are "Entity only"; a top-level session is
rejected with BL01001973.
