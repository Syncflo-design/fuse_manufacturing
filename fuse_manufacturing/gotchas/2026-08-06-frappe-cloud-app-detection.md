# Frappe Cloud rejects a repo with more than one directory at the root

**Symptom:** "Add app from GitHub" fails with
`Not a valid Frappe App! Files hooks.py or patches.txt does not exist inside gotchas/gotchas directory.`
— naming a directory that has nothing to do with the app.

**Cause:** Frappe Cloud picks a directory at the repo root and expects the app's
`hooks.py` (or `patches.txt`) inside it. It does not search for the one that actually
is the app. `fuse_manufacturing/` was there and correct, but `docs/` and `gotchas/`
were too, and it landed on `gotchas`.

**Fix:** keep exactly one visible directory at the repo root — the app package. Docs
and anything else move inside it. Files at the root (`README.md`, `pyproject.toml`,
`CLAUDE.md`) are fine; hidden directories (`.claude/`, `.git/`) are ignored.

**Related, hit in the same session:**
- `Not a valid Frappe App! ... does not exist inside <app>/<app> directory` with only
  one root directory means what it says — add `patches.txt` or check `hooks.py` is committed.
- `Could not find compatible Frappe version in pyproject.toml file` — declare it:
  ```toml
  [tool.bench.frappe-dependencies]
  frappe = ">=16.0.0,<17.0.0"
  erpnext = ">=16.0.0,<17.0.0"
  ```
- `Could not fetch branch (main) info` — the repo is empty, nothing pushed yet.
- Private repo + `repository not found` on push — the authenticated GitHub account has
  no access; GitHub returns 404 rather than 403.

**Applies to:** Frappe Cloud, August 2026. Bench installs from a local path are not
affected — this is Frappe Cloud's repo validation only.
