# Fuse_Manufacturing — documentation index

One file per topic. Anything not listed here is a scratch note, not a decision.

| File | Purpose | Status |
|---|---|---|
| `01-spec.md` | Scope, deliverables, build order, what's out of scope | current |
| `02-intacct-integration.md` | Gateway reference — hard-won Intacct facts, entity mapping | current, mapping unverified |
| `03-decisions.md` | Architecture decision log | current |
| `04-workflows.md` | **The workflow document** — trigger / ERPNext steps / Intacct post / on failure | not started, blocked on enumeration |

## Rules

- Record the **why**, not just the what — future sessions read these instead of re-deriving.
- Date every decision. Convert relative dates to absolute.
- When a decision is reversed, keep the original entry and append the reversal. Don't delete.
- **Never write behaviour you have not read from the system.** Mark anything unverified.
