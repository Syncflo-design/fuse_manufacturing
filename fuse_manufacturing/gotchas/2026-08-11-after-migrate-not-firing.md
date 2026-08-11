# after_migrate does not reliably fire on a Frappe Cloud deploy

**Seen:** 2026-08-11, leadertread-imp.

A deploy shipped new code AND two new Custom Field definitions. The code arrived —
`reverse_stock_entry_manufacture` was callable — but the fields did not exist, so the
posting wrote to a field that was not there.

`hooks.py` had it wired correctly the whole time:

```python
after_install = "fuse_manufacturing.install.after_install"
after_migrate = "fuse_manufacturing.install.after_install"
```

## How to tell, without bench access

Change the `description` of an EXISTING custom field in the same commit, then read it back
after the deploy. `create_custom_fields` updates existing fields, so if the description is
still the old text, `after_migrate` did not run. Ours still said the old text with a
`modified` date four days earlier.

Do not test by checking whether the NEW field exists — you cannot tell a hook that did not
run from a hook that ran and failed.

## Fix

`masters.run_now("setup")` re-applies every custom field and role. Idempotent, whitelisted,
runnable from the desk. Run it after any deploy that adds or changes a field.

The Error Log showed nothing, so there is no failure to find — the hook simply did not
fire. Do not go looking for an exception.

**Wider point:** the fresh-install promise depends on this hook. Until we know why it
skipped, treat "installing the app configures the site" as unproven on Frappe Cloud, and
run `setup` explicitly.
