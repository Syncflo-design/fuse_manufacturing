# Intacct Settings moved to fuse_core — what that does and does not preserve

**Date:** 2026-08-21
**Applies to:** `fuse_core`, `fuse_manufacturing`, `fuse_projects`

## What changed

`gateway.py`, `Intacct Settings`, `Intacct Request Log`, `Fuse Active Module`,
`Intacct Transaction Definition` and `Intacct Transaction Mapping` now belong to
`fuse_core`, along with the definitions mirror that used to be
`masters.sync_transaction_definitions`. `fuse_manufacturing` declares `required_apps = ["fuse_core"]` and imports
the gateway from there. Four pure functions the transport depends on — `control_id_for`,
`result_keys`, `rejection_errors`, `intacct_date` — moved to `fuse_core.rules` and are
re-exported from `fuse_manufacturing.rules`, so nothing else in this app changed.

Driver: `fuse_projects` is sold separately and needs the same Intacct connection. Two apps
cannot both ship a doctype called `Intacct Settings`, and a second copy of the credentials
was never acceptable.

## The bit that is easy to get wrong

Core kept the connection and both registries — the module switches and the process
mapping. The stock-specific settings — `use_intacct_kits_as_boms`, `boms_from_intacct`,
`default_item_group`, `reject_warehouse`, `last_item_sync` — come back as **custom fields**
added by `fuse_manufacturing.install`.

That preserves the data **only because the fieldnames are identical**. `Intacct Settings`
is a Single: its values live in `tabSingles` keyed by field name, not by which app declared
the field. A standard field becoming a custom field of the same name keeps its value.

**Rename one of those fieldnames and the client's setting is silently lost.**

`transaction_mappings` is NOT one of them — it stayed a standard field and simply changed
app. Its rows are untouched: still `parent = "Intacct Settings"`,
`parentfield = "transaction_mappings"`.

## Deploy order

Core must migrate first. `required_apps` handles that on a normal bench install; on Frappe
Cloud, add `fuse_core` to the bench before the other two. All three deploy together — there
is no release in which one app has the doctype and another expects it.

If `after_migrate` does not fire (see `2026-08-11-after-migrate-not-firing.md`), the custom
fields will not exist and both tables will look empty. Both are repairable without bench
access: call `fuse_core.api.setup` for the switch and process tables, and
`fuse_manufacturing.masters.run_now` with `job="setup"` for this app's custom fields and
role permissions.

## Two registries, one pattern

Core owns both tables on Intacct Settings and declares nothing for either:

| Table | Hook | Core's part | This app's part |
|---|---|---|---|
| Active Modules | `fuse_modules` | the table and its rules | the seven features it implements |
| Transactions | `fuse_processes` | the table, and the definition picker read from Intacct | the five processes it posts |

Core announces a switch toggle back through `fuse_modules_changed` — which is how this app
still withdraws Purchase Receipt and Work Order permissions the moment a module is switched
off. Core cannot import this app, and must not know it is installed.

That is what makes the Transactions table grow on its own: when Projects starts posting, it
declares its processes through the same hook and core does not change.

## Tests

`fuse_manufacturing/tests/` import `fuse_manufacturing.rules`, which now imports
`fuse_core.rules`. Running the suite needs `fuse_core` importable — it is on a bench, but
not in a bare checkout of this repo on its own.
