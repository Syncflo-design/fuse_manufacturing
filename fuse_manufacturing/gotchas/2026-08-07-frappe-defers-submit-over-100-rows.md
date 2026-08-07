# Frappe silently defers submit() on documents with more than 100 child rows

**Symptom:** A background job reports success. The documents exist. There is no stock —
no Stock Ledger Entries, no Bin records, and every document sits at `docstatus 0`.

**Cause:** Frappe queues `submit()` as a background job once a document has **more than
100 child rows**. `submit()` returns immediately having changed nothing visible, so code
that calls `doc.insert()` then `doc.submit()` looks like it worked. Hit on the first
opening-stock run: 1,960 lines batched at 200 rows produced 10 Stock Reconciliations, all
left at draft.

**Fix:** keep batches **at or below 100 rows**, and never trust `submit()` to have worked:

```python
doc.submit()
doc.reload()
if doc.docstatus != 1:
    frappe.throw(f"{doc.name} did not submit (docstatus {doc.docstatus})")
```

**Why it matters more than it looks:** this failure is indistinguishable from success
unless something checks. A sync that reports `"posted": 1960` while the site holds no
stock is worse than one that crashes — nobody goes looking.

**Applies to:** Frappe v16, any submittable doctype with a large child table —
Stock Reconciliation, Stock Entry, Purchase Receipt, Sales Invoice.
