# A rejected Intacct posting left the document Submitted

**Found:** 2026-09-22, first live test of Stock Count. Intacct rejected FUSE-CNT-2026-00001
(a schema error in our XML), the user saw the error, and on reopening the import it was
Submitted with nothing sent.

**Cause:** `fuse_core.gateway._log_request` called `frappe.db.commit()` after writing a
FAILED request, so the log row would survive the rollback. A commit commits the whole
transaction, and inside a submit that includes the document's own docstatus = 1, which Frappe
writes before `on_submit` runs. The exception then rolled back nothing. This applied to
every movement that posts on submit, not just counts. It broke "Intacct posts first".

**Fix:** a failed request's log row is written but not committed, and
`frappe.db.after_rollback` writes it again (same fixed name, so no duplicate) once the
rollback has happened. A caller that swallows the failure (Fuse Projects saves a task locally
when Intacct refuses it) never rolls back, and the row commits with its own work. Success
still commits at once: once Intacct has taken a posting the local document must stand.

**Checked:** the only earlier failed writes on Leader (MAT-STE-2026-00002/00003, 2026-08-11)
are both cancelled with Intacct keys, so nothing was left orphaned.

**Rule:** never `frappe.db.commit()` inside anything that can run during a submit unless the
thing being committed is meant to stand whether or not the submit does.
