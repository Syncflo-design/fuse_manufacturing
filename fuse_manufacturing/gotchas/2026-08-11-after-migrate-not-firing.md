# A Frappe Cloud deploy can succeed without the site running your latest commit

**Seen:** 2026-08-11, leadertread-imp.

Twice in one session, code appeared not to have deployed. The first diagnosis was that
`after_migrate` was not firing. **That was wrong.** The site was simply running an earlier
commit, which had nothing new to create.

## What actually happened

The bench's **Apps** tab showed `fuse_theme` at the newest commit with status "Latest
Version". The site was still serving the previous one. The Apps tab shows the commit the
bench is pinned to — a deploy has to be started *after* that pinning for the site to run it.
A deploy that completed earlier the same afternoon did not contain the commits pushed after
it started.

## How to tell what the site is ACTUALLY running

Do not trust the bench's Apps tab, and do not trust `frappe.utils.change_log.get_versions`
— it returns the version from `pyproject.toml` (`0.1.0` for both our apps regardless of
commit), not the commit.

Call something that only exists in the new code, and check for a value only the new code
returns:

```
fuse_manufacturing.masters.run_now  job=definitions
```

`required_by_postings` listing four definitions instead of six proved the site predated the
commit that added the adjustment definitions. A missing whitelisted method — `gateway.read`
raising "module has no attribute" — proved the same thing in one call.

Pick a marker per deploy and check it. It takes one call and replaces an afternoon of
theorising about framework internals.

## Do not conclude "the hook did not fire"

There is no evidence `after_install` / `after_migrate` are unreliable on Frappe Cloud. Both
apps wire them, and both also expose the same function as a whitelisted call
(`masters.run_now("setup")`, `fuse_theme.api.setup`). Those remain useful — re-applying
fields and workspaces on demand without bench access is worth having — but they are a
convenience, not a workaround for a framework bug.
