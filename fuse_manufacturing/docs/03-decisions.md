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

## 2026-08-07 — Request log, deterministic control IDs, atomic multi-leg posts

Three things done together because they share one code path, and all three must exist
**before anything posts to a real company**.

**1. `Intacct Request Log`.** Every write is recorded: function, control ID, ERPNext
document, entity, duration, HTTP status, Intacct key, and the full request/response XML.
Reads are logged **only when they fail** — logging every successful page would make this
the largest table on the site during a masters sync, for no diagnostic value.
- **Credentials are redacted before storage** (`<password>`, `<sessionid>`). The login
  envelope carries both the sender and user password in clear; an unredacted log is a
  credential store. Verified by test, not assumed.
- No role has create or write. An audit trail someone can edit is not an audit trail.
- Logging never raises — a logging failure must not fail the posting it describes.

**2. Deterministic control IDs + `<uniqueid>true</uniqueid>`.** Derived from the ERPNext
document via `control_id_for(doctype, name, purpose)`, so it is reproducible from the
document rather than stored and hoped for.

**Why this is non-negotiable:** `_post` retries on timeout. A request that times out
*after* Intacct committed it would be retried and post the movement twice. With a
deterministic control ID and uniqueid set, Intacct rejects the replay. Without it, the
retry logic is a stock-duplication machine. It is harmless today only because nothing
posts yet.

**3. `execute_many(..., atomic=True)`** wraps multiple functions in
`<operation transaction="true">` so Intacct commits all or none. This closes the donor's
put-away hole *by construction*: it posted the Out leg, and if the In leg failed the
stock had left the bay and arrived nowhere, with only a message telling someone to go and
fix it by hand in Intacct. Every leg of one movement goes in a single call.

**Still outstanding:** no automated tests, and the reversal/cancellation design.

## 2026-08-07 — Build for lot, serial and bin tracking even though Leadertread has them off

**Context:** Leadertread runs with lot tracking, serial tracking and bin tracking all
switched off. Other clients will use them, and Leadertread may switch them on later.

**Decision:** Every posting, screen and sync is written to handle tracked items from the
start. Not "add it later" — the code paths exist and are exercised, even if Leadertread's
own data never hits them.

**Why:** tracked stock is not a variation on untracked stock, it is a different shape —
a movement carries lot or serial identity per line, and ERPNext refuses to change an
item's tracking flags once movements exist against it. Retrofitting means unpicking
history, not adding a branch.

**Consequences:**
- Never assume a movement can be posted from a warehouse total alone.
- `post_opening_stock` already skips tracked items and reports them, rather than inventing
  lot numbers. That stays the pattern: refuse and report, never guess.
- DEV's own test data DOES have lot, serial and bin tracked items (CSS1001, CSS1003–1005).
  That is a useful accident — it exercises the paths Leadertread's data will not.

## 2026-08-06 — Substitution via Item Alternative, approved per pairing

**Context:** Leadertread substitutes a raw material when one is unavailable, and a
substitution must be approved by someone rather than chosen freely on the floor.

**Decision:** Use ERPNext's **Item Alternative**, not alternative BOMs. Approval is at
the **pairing** level — "Y may stand in for X" is approved once and then reused — not per
individual swap.

**Why not alternative BOMs:** they are combinatorial. A component with two substitutes
appearing in ten kits means a matrix of near-identical BOMs, every one needing to stay in
step each time Intacct changes a recipe. Item Alternative is one statement, maintained
once, reused by every BOM containing that item. Reserve alternative BOMs for a genuinely
different recipe — different quantities or process — not "we ran out".

**Consequences:**
- Synced BOM lines carry `allow_alternative_item = 1`. The **approved pairing list is the
  control**, not the line flag: with no Item Alternative for a component, the flag does
  nothing. One list to maintain instead of a flag per line.
- Item Alternative permissions were tightened on 2026-08-06: **Stock User and Stock
  Controller are read-only**; Stock Manager and Item Manager may create. ERPNext ships
  Stock User with full create rights, which would have let the storeman approve their own
  substitutions.
- Adding one Custom DocPerm replaces the standard permission set for that doctype
  entirely, so all four roles had to be restated. Do not add a single row and assume the
  rest survive.
- The pairing list lives in **ERPNext only**. Intacct's `ITEM.SUBSTITUTEID` exists but
  holds a **single** substitute per item, where Item Alternative is many-to-many and can
  be two-way. Syncing it was considered and rejected: anything beyond one substitute
  would have to live in ERPNext anyway, so it would mean maintaining the list twice.
  Treat `SUBSTITUTEID` as information, not as the source. `ITEMCOMPONENT` has no
  alternatives flag at all.
- Approval sits with operations, not accounting, which is the other reason the list
  belongs on this side.
- Per-swap approval was considered and deferred. It needs a Workflow on the Stock Entry
  and a queue someone watches on the floor; revisit only if pairing-level proves too loose.

## 2026-08-06 — Alternative BOMs are allowed; postings follow actual consumption

**Context:** Leadertread substitutes raw materials when one is unavailable, so they need
more than one BOM per finished good. Intacct cannot express that — `ITEMCOMPONENT` holds
exactly one flat recipe per kit.

**Decision:** ERPNext may hold as many BOMs per item as the plant needs. The sync
maintains **only** the Intacct-sourced one and never touches the others.

**Why this is safe:** postings send a Manufacturing Increase / Decrease **per item, from
what was actually consumed**, not from the planned recipe. Intacct therefore never needs
to know which BOM was used — it only ever sees real movements. The recipe is an ERPNext
planning concern; the movements are the shared truth.

**Consequences:**
- A sync-managed BOM is identified by its `custom_intacct_signature`. Matching on "the
  active BOM for this item" would find a hand-built substitution BOM and cancel it,
  destroying someone's work silently. Never match that way.
- **The Intacct BOM is always the default.** Substitution BOMs are for when a material
  is unavailable and are chosen deliberately on the Work Order — the exception, not the
  standing recipe. Every sync restores Intacct's as default, even if a substitution was
  made default in the meantime.
- **Do not lock down BOM permissions** for the Stock Controller. An earlier reading —
  "Intacct is the golden source for recipes, so make BOM read-only" — is wrong for this
  client. Substitution is a real operational need.
- Because consumption drives the posting, a substitution reaches Intacct correctly with
  no extra work: the component that was actually used is the one that decrements.

## 2026-08-06 — Opening stock once, then a drift report — never a continuous mirror

**Context:** ERPNext starts with no stock. Intacct holds the on-hand
(`ITEMWAREHOUSEINFO.WONHAND`, with `AVERAGE_COST` — the only place the API exposes item
cost at all).

**Decision:** Read Intacct's on-hand **once** at go-live and post it as an opening Stock
Reconciliation. After that ERPNext maintains its own quantities from the movements it
posts. A read-only `stock_drift_report` compares the two on demand.

**Alternatives rejected:** re-reading Intacct on a schedule and correcting ERPNext to
match. It hides the bugs that cause drift instead of surfacing them, and it can
overwrite a movement that has not posted yet.

**Why it holds:** quantities stay in step precisely *because* every movement posts both
ways. If they stop agreeing, that is a fault to find, not a number to overwrite.

**Consequences:**
- `post_opening_stock` is once-only **per item/warehouse combination**, and resumable.
  It first refused outright if any stock movement existed. That read as safe and was
  not: the first real run posted one batch of 100, stopped, and the retry was refused —
  leaving the opening 5% done with no way to continue. It now skips combinations that
  already hold stock and opens the rest, so a run that dies can simply be run again.
- Zero-cost items open at **0.01**, not skipped. ERPNext refuses a stock line with no
  valuation rate, so skipping would silently lose the quantity — the thing the factory
  actually needs. 0.01 is never a plausible cost, is glaring in any report, and the
  exact figure is the worklist: filter Bin valuation rate = 0.01.
- Valuation on the opening entry comes from Intacct's `AVERAGE_COST`. ERPNext never
  invents a value.
- **Batch and serial tracked items are skipped and reported.** Intacct holds those per
  lot, not as a warehouse total, so opening them blind would invent tracking data.
  They need a deliberate decision before go-live.

## 2026-08-07 — REVERSED: reach the Fuse page from a workspace tile, not a home-page hook

**Supersedes the decision below.** `home_page` and `role_home_page` govern the **website**
home page. The desk always lands on a **workspace**, so those hooks looked correct, passed
review, deployed — and the desk kept reverting. Both removed.

**Decision:** the Fuse page is reached from a tile on the Fuse workspace. One workspace per
role, restricted by role, each with the tiles that role needs.

**Why:** it is how Frappe expects it to work, so it survives upgrades and needs no
redirect shim. Russell's call — do not fight the framework.

## 2026-08-06 — "Home" always means the user's Fuse landing page, never the desk (SUPERSEDED)

**Decision:** The breadcrumb house, `/app`, and post-login all land on the user's Fuse
home page. Set via `home_page = "fuse-home"` in `fuse_theme`, with `role_home_page` kept
for per-role overrides. Applies project-wide, not just to Stock Controller.

**Why:** this is a single-product site. Dropping someone on the generic desk workspace
list makes them navigate out of somewhere they never asked to be.

**Consequences:**
- `role_home_page` cannot carry the general case — Frappe matches **one** role, so a
  user holding several gets whichever resolves first. That is why the app-wide
  `home_page` does the work and `role_home_page` is only for genuine exceptions.
- Any new landing page for another role is a `role_home_page` entry, not a new mechanism.
- The Page's own `roles` list must include any role expected to land there, or they
  land on a page they cannot open.

## 2026-08-06 — Kits become BOMs; the multi-level cascade is ERPNext's, not Intacct's

**Context:** Intacct has no BOM and no recipe-style production recording. Its only
recipe structure is `ITEMCOMPONENT` — flat, single-level, 17 fields. A kit IS the
finished good.

**Decision:** Mirror kits into ERPNext BOMs, built in **dependency order** so a
sub-assembly's BOM exists before any BOM that consumes it. ERPNext then explodes the
sub-assembly rather than treating it as a raw part, and the cascade emerges from a set
of flat Intacct kits.

**Why:** cascading BOMs and true sub-assemblies are a real gain for Leadertread and are
a large part of what makes ERPNext worth the switch. Verified on this site
(2026-08-06) that a BOM with zero valuation both saves and submits, which is what makes
this workable with perpetual inventory off.

**Consequences:**
- **Every level of the cascade posts its own movements to Intacct.** A sub-assembly is
  really produced and really consumed, so it becomes stock at its level.
- Therefore each intermediate that holds value in a warehouse **must exist as an Intacct
  item** — the rule from the handoff, now with teeth. How deep the cascade goes is a
  decision about how much intermediate stock Leadertread wants to hold and count.
- BOMs are rebuilt only when the recipe signature changes. Cancel-and-replace is the
  only way to change a submitted BOM, so an unconditional rebuild would churn the entire
  BOM history on every run.
- Circular recipes are reported and skipped. Intacct permits saving one; ERPNext cannot
  explode it.

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

**Decision:** The Leadertread ERPNext site's Intacct Settings target the **DEV** company
first. `leadertread-imp` is the **final testing** instance — not production — and the
connection moves there for transaction tests once DEV is proven.
**Why:** the posting layer has to be proven — production run, goods receipt, warehouse
transfer, stock adjustment, all correctly costed — without touching the live company.
**Consequences:**
- Configuration drifts between companies, so each one's transaction definitions must be
  re-read on arrival — DEV's are not evidence for imp's, and imp's are not evidence for
  production's.
- **The entity ID differs per company:** DEV is `100`, imp is `E100`. Confirmed on
  2026-08-06 — the donor's `E100` did not exist in DEV, and the resulting failure was
  `XL03000006`, which reads as a credentials error rather than an entity one. Switching
  companies means changing the entity too.
- DEV's units are `Each` and `Ounce`, not the SA English set (`Cubic metres`, `Kilograms`)
  seen on the donor's company. Do not treat DEV data as representative.

## 2026-08-06 — 1 client = 1 ERPNext instance = 1 Intacct company

**Decision:** One credential set per instance. Company → entity (`locationid`) → location.
Entity ID stored against each ERPNext Company, sent as `<locationid>` on every login.
**Why:** Manufacturing transaction definitions are "Entity only"; a top-level session is
rejected with BL01001973.

## 2026-08-11 — A cancel reverses in Intacct; it does not refuse

**Decision:** Cancelling a posted Stock Entry posts a reversing pair to Intacct first,
then allows the cancel. It no longer throws. The reversal is a NEW pair of documents —
Intacct keeps the original and the undo.

**Why:** the previous refusal was based on the donor's claim that the reversal definitions
are convert-only. `INVDOCUMENTPARAMS` on `leadertread-imp` says otherwise: both
`Manufacturing Run Decrease` and `Manufacturing Backflush Incr` are active with
CREATETYPE "New document or Convert". Refusing was the honest answer while that was
unknown; it is not any more.

**The trap — a reversal is NOT the forward pair negated.** The cost always rides the
increase leg, so flipping direction moves it to the other side:

| | Components | Finished goods |
|---|---|---|
| Forward | Backflush **Decr** — no cost | Run **Increase** — cost sent |
| Reverse | Backflush **Incr** — **cost required** | Run **Decrease** — no cost |

Building the reversal by mirroring the forward legs returns the quantities and loses the
money. `rules.manufacture_reversal_legs` returns components at the exact rate they were
consumed at, read from the same rows the forward post used.

**Consequences:**
- **A zero component cost is refused, not sent.** `Backflush Incr` has UPDATES_COST=true,
  so a zero would overwrite Intacct's valuation of that item — destructive, not merely
  wrong.
- **The finished-goods leg carries no cost**, so Intacct removes it at its own current
  valuation. If that item has been produced again since at a different cost, the reversal
  will not net to zero in value. That is Intacct's own behaviour and correct: we do not
  know what it has cost since, and inventing a number to force a clean net would be
  exactly the guessing the golden-source principle forbids.
- **The reversal is dated the ORIGINAL posting date**, so the pair nets to zero in the
  period it happened in. A closed period rejects it — the right answer, not something to
  route around by quietly dating the reversal today.
- Control ID carries purpose `-reverse`, so it is deterministic (a retried reversal cannot
  post twice) but distinct from the forward post (Intacct will not mistake it for a replay).
- `custom_intacct_reversal_key` blocks a second reversal; posting switched off blocks the
  cancel entirely rather than stranding a posting with nothing to undo it.

## 2026-08-11 — Intacct documents say "Fuse", not "ERPNext"

**Decision:** the DESCRIPTION on posted documents reads `Fuse <name>`. Internal messages
that describe ERPNext's own behaviour keep saying ERPNext, because that is what they mean.
**Why:** the client bought Fuse. The platform it runs on is not their concern.

## 2026-08-11 — Fuse supplies the document number on reversals

**Decision:** the reversal legs carry a Fuse-generated `documentno` (`FR-<hash>-<leg>`).
**Why:** neither reversal definition has a numbering scheme attached in `leadertread-imp`,
so Intacct rejects them with `PL01000127 "Document Number is missing"`. Attaching one is a
template setting needing admin rights on the company. Russell's call, 2026-08-11: supply
the number, deal with the Intacct config later — the system has to work now.
**Consequences:**
- The `FR-` prefix and non-numeric body mean it can never collide with a number Intacct
  issues, including if a scheme is attached to these templates afterwards.
- Deterministic from the Stock Entry name, so a retried reversal reuses the number instead
  of creating a second document.
- **This is the one place Fuse invents a value.** It is an identifier, not a quantity or a
  cost, so nothing about Intacct's books depends on it — but it is a deviation from the
  golden-source principle and should be undone once the templates are configured. The
  `definitions` job now reports `not_numbered`, so the day it can be undone is visible.

## 2026-08-11 — Co-products and scrap are refused, not guessed

**Decision:** a Manufacture entry with more than one finished item, or with output that is
not the finished item (scrap, by-product), is refused with a message naming the rows.
**Why:** both were silently dropped. Classification worked by elimination — finished item,
else anything with a source warehouse, else skip — so a second finished item overwrote the
first and any row with a destination and no source vanished. Intacct received less than
happened, with nothing logged.
**Why refuse rather than support:** handling them means splitting one production cost
across several outputs, and there is no non-arbitrary rule. Quantity-weighted is wrong the
moment two outputs are worth different amounts. Inventing the split is exactly what the
golden-source principle forbids, so it waits for someone to decide the allocation rule.
**Consequences:**
- Leadertread's compounds are single-output, so nothing they do today is blocked.
- Substitution is unaffected and needs no special handling: a swapped raw material is just
  a different consumed row, which is why the postings go leg-by-leg rather than by BOM.

## 2026-08-11 — Stock adjustments use Intacct's cycle-count definitions

**Decision:** Material Receipt posts `SYS-CC Adjustment Increase`, Material Issue posts
`SYS-CC Adjustment Decrease`. One document, one definition — an adjustment only moves one
way, so there is nothing to pair it with.
**Why:** both are already active and postable in `leadertread-imp`, so adjustments need no
new Intacct configuration. Neither carries a numbering scheme, so Fuse supplies the
document number as it does for reversals.
**Consequences:**
- The increase values the movement (UPDATES_COST=true) and carries a cost; the decrease
  does not, so Intacct removes stock at its own valuation. A zero cost on the increase is
  refused, not sent — it would overwrite the item's valuation with nothing.
- **Stock Reconciliation is deliberately NOT wired.** It is the doctype the opening stock
  sync uses, and opening stock came FROM Intacct. Posting it back would double every
  balance on the day a site went live. Adjustments are Material Receipt and Material Issue
  only.
- Adjustments carry bins, because they go through `create_ictransaction` — so unlike
  transfers, they already work for the 32 bin-tracked items.
