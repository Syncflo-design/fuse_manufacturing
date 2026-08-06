# Fuse_Manufacturing — ERPNext operational layer over Sage Intacct

Auto-loaded for every session in this folder. Read this first, then
`fuse_manufacturing/docs/03-decisions.md`.
Root `C:\ClaudeCode\CLAUDE.md` and `CoWork_Helper/CLAUDE.md` still apply on top.

## What we are building

An ERPNext operational layer alongside Sage Intacct, **per client**. Intacct stays the
accounting system of record — the books never move. ERPNext runs manufacturing, stock,
quality, maintenance, CRM, support and HR, and posts every financial consequence into
Intacct **live**.

That live financial sync is the product. Everything else is configuration.

## Status

Preliminary. **No ERPNext instance exists yet.** No Frappe app scaffolded.
`leadertread-DEV` is the Intacct sandbox company, not an ERPNext site.

## The predecessor: Fuse (WebForms)

`\\Syncflo-desktop\f\Manifold\Intacct_Fusion Manufacturing` — ASP.NET WebForms over
Intacct, SBMS as donor. Proven against a live Intacct company but **being retired**:
everything it hand-builds (works orders, BOM explosion, backflush, WIP) ERPNext ships
as standard.

**Nothing is live. Fuse only ever ran in dev — no data to migrate, nobody to retrain.**
That is why the switch is happening now, and why this is not a cutover project.

> **Fuse is the requirements document, not the template.** Port intent, never screens.
> Where ERPNext does it natively, use ERPNext — Fuse's version is a workaround for SBMS's
> limitations, not a specification. Its .NET SDK transport does not port; the *gateway
> approach* does (same endpoint, same envelope, same function names, issued from Python).

## Architecture — decided, do not re-litigate

- A Frappe app posting **XML** to `https://api.intacct.com/ia/xml/xmlgw.phtml`.
- **Not** Intacct's REST API — REST forces every customer through app registration in the
  Sage developer portal. The XML gateway needs only a sender ID plus company credentials.
- **No .NET middleware, no proxy service.** Python/`requests` inside Frappe is enough.
  Errors surface in the request that caused them; retries and scheduling come free from
  Frappe's queue; per-client config lives in DocTypes.
- **Two apps, separately releasable:** the integration app, and a *theme* app.
  Cosmetic changes must never force an integration release.

## Tenancy

1 client = 1 ERPNext instance = 1 Intacct **company** (one `companyid`, one credential set).
A company contains N **entities** (`locationid`). Hierarchy: **company → entity → location**.

Store the Intacct entity ID against each ERPNext Company; send it as `<locationid>` on
**every** login.

## The integration contract

- **Intacct posts first, always.** If Intacct rejects the post, the ERPNext transaction
  does not stand. There is no local-only outcome.
- **ERPNext never invents a value.** It records the cost Intacct accepted.
- **Live, never batched.** No overnight file, no summary journal, no suspense account.
- **Masters flow one way, Intacct → ERPNext:** chart of accounts, customers, suppliers,
  items, warehouses, bins, UOMs, entities, tax schedules.
- Per-client exception to settle: manufacturing invents items accounting does not need
  (WIP intermediates, sub-assemblies). Rule — **if it holds value in a warehouse, Intacct
  creates it.**

## Handover points (default; confirm per client)

- **Buying** — requisition, approval and PO in ERPNext. PO copies to Intacct with no ledger
  impact. Goods receipt posts to Intacct (quantity **and** value, updates cost). Supplier
  invoice is processed in Intacct.
- **Making** — production job and shop floor in ERPNext. Materials consumed and finished
  goods produced post to Intacct as they happen.
- **Selling** — pipeline, order, pick and delivery in ERPNext. Sales invoice raised in Intacct.

## UI

ERPNext must resemble Sage Intacct for visual consistency. **Own Frappe app**, separate from
the integration app — not every client wants the Intacct look. Precedent: `nest_theme`
(already on several of our instances, see `C:\ClaudeCode\nest_theme`).

**Style it, do not restructure it.** Colour, typography, density, nav and button treatment
survive upgrades. Rearranging form layouts to mimic Intacct screens will fight the framework
every release.

The one exception where custom Frappe screens earn their keep: **mobile scanner flows**
(item convert, handoff, put-away, receiving). ERPNext's stock screens are not scanner-shaped,
and those flows are already proven with the client's people.

## Environment

- **leadertread-DEV** is the Intacct sandbox. Prove the posting layer there — production run,
  goods receipt, warehouse transfer, stock adjustment, all correctly costed — without
  touching the live company.
- **A dev company's configuration DRIFTS from live.** Re-read the live company's transaction
  definitions before committing to any go-live.
- Rollout runs at least six months. There is runway.
- Credentials live in `IntacctConfig.cs` on the C# workstation. Bring them across securely,
  into site config / Frappe secrets. **Never into the repo, never into a chat.**

## Plan

1. Build the Frappe Intacct app. **Masters in (read-only mirror) FIRST**, postings out second.
2. Prove the postings against leadertread-DEV before any date is committed.
3. Configure ERPNext to the client's actual process — mostly setup, not development.
4. Then talk dates.

## Working rules (this repo)

- **Never guess how something behaves.** Read the code or query the system. Enumerate the
  ERPNext instance (Module Def, DocType, Report) and read Intacct from the gateway rather
  than assuming. If unsure, go and check.
- Answer on line one. Terse. Plain English for logic/accounting/process, with a worked
  numbers example, no jargon.
- Smallest change that works. No extra abstraction, helpers or config unless asked.
- Python 3.13 on this machine — `py_compile` + `ruff` every changed file before reporting
  done. Server Scripts obey `safe_exec` limits (no imports, no commit, `json.loads` not
  `parse_json`, no tuple unpacking).
- Capture anything non-obvious in `gotchas/` before closing a session.

## Layout

**The repo root must contain exactly one visible directory: `fuse_manufacturing/`.**
Frappe Cloud's "Add app from GitHub" picks a directory at the root and expects
`hooks.py` inside it — a second one at the root (`docs/`, `gotchas/`) makes it reject
the repo as "Not a valid Frappe App". That is why the docs live inside the app.

- `fuse_manufacturing/` — the Frappe app (`hooks.py`, `gateway.py`, `masters.py`, `install.py`).
- `fuse_manufacturing/docs/` — spec, Intacct integration reference, decision log, workflow document.
- `fuse_manufacturing/gotchas/` — `YYYY-MM-DD-short-title.md`.
- The GitHub repo is `fuse_manufacturing`, lowercase — `bench get-app` clones into a
  folder named after the repo and then looks for a Python module of that same name.
  The local folder is title-cased; that is fine, only the repo name matters.

## Git

Russell runs all git himself in Git Bash: `cd /c/ClaudeCode/Fuse_Manufacturing`.
Never push, commit, or call `gh` on his behalf — hand over the commands.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
