# Role permissions cannot switch off a feature that shares its DocType with another

**Date:** 2026-08-18
**Applies to:** `modules.py`, `install._apply_role_permissions`, `postings.block_inactive_module`

## Symptom

You build an on/off switch per module and wire it to role permissions. Receiving
switches off cleanly. Item Transfer does not — switching it off also kills Issue to WIP
and Works Orders, or nothing at all, depending on which way you wire it.

## Cause

Frappe permissions are granted **per DocType**. Three of Fuse's modules raise the same
one:

| Module | Document | What separates it |
|---|---|---|
| Issue to WIP | Stock Entry | `purpose = Material Transfer for Manufacture` |
| Item Transfer | Stock Entry | `purpose = Material Transfer` |
| Works Orders | Stock Entry | `purpose = Manufacture` |

A role either may create Stock Entries or it may not. There is no permission that says
"may create transfers but not production runs", because the thing that distinguishes
them is a field value on the document, and that is only knowable once the document
exists.

Receiving and Works Orders have documents of their own — Purchase Receipt, Work Order —
so those two CAN be withdrawn by permission.

## Fix

Two mechanisms, chosen by whether the module owns its document:

1. **Owns a document → withdraw the permission.** `MODULE_DOCTYPES` maps a module to
   the doctypes it owns, and `_apply_role_permissions` removes the role's row rather
   than zeroing it — a row with every flag at 0 still reads as "this role has an
   opinion here", which the next person cannot tell apart from a mistake.

2. **Shares a document → guard on validate.** `postings.block_inactive_module` reads
   `doc.purpose`, maps it to a module, and refuses with a message naming the module.
   A refusal, not a silent no-op: someone arriving from a bookmark or a report link has
   done nothing wrong and needs to know who to ask.

## The deploy trap this avoids

Editing role permissions at runtime normally loses to
`CoWork_Helper/gotchas/2026-05-20-frappe-deploy-overwrites-doctype-permissions.md` —
migrate re-asserts what the app declares.

Here it works the other way, because permissions are **derived** from the switches
rather than typed in: `_apply_role_permissions` reads the settings table every time it
runs, so a deploy reinstates the client's choice instead of trampling it. The same
function is called from `Intacct Settings.on_update`, so a toggle takes effect at once
rather than at the next migrate.

Do not "fix" this by writing permission rows into the DocType JSON. The JSON cannot
know what a given client switched off.

## Found while wiring it

`Purchase Receipt` had never been in `ROLE_PERMISSIONS` — the list was written while
receiving was refused outright. Receiving shipped the day before and would have failed
on permissions for exactly the users meant to do it. Whenever a refusal becomes a
feature, check what the role was never given.

## See also

- `CoWork_Helper/gotchas/2026-05-20-frappe-deploy-overwrites-doctype-permissions.md`
- `docs/03-decisions.md` — 2026-08-18, receiving and the module switches
