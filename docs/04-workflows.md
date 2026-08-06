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

## STATUS: NOT STARTED — blocked on enumeration

Nothing is written below yet, deliberately. Filling these rows requires reading the two live
systems rather than assuming:

- **ERPNext** — enumerate Module Def, DocType, Report on the actual instance. No instance
  exists yet (as of 2026-08-06); none of the configured Frappe MCP connectors
  (`ardmore`, `blomo`, `comstruct`, `demo`, `nesterp`) is this project's site.
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
