# Tagging a barcode's type makes ERPNext validate it — and a bad tag fails the whole item

**Date:** 2026-08-18
**Applies to:** `masters.sync_items`, `rules.barcode_type`, any Item Barcode write

## Symptom

An item with a perfectly good internal code in Intacct's `UPC` or `EAN13` field
fails to sync. Not "the barcode is missing" — the **item** errors, every hour,
until someone changes the value in Intacct.

## Cause

ERPNext validates the length and the GTIN check digit of any Item Barcode row whose
`barcode_type` is set to `UPC-A` or `EAN`. It validates **nothing** when the type is
blank.

`sync_items` used to tag every value it found: `UPC` → `UPC-A`, `EAN13` → `EAN`. So
the moment a client put their own numbering in those fields — a works order number,
an internal stock code, anything that is not a real GTIN — the Item save threw and
took the rest of that item's sync with it.

The trap is that **we** caused the validation. Intacct accepted the value happily.
Nothing was wrong with the data; the tag we attached to it was the lie.

## Fix

`rules.barcode_type(value)` returns `"EAN"` or `"UPC-A"` only when the value really
is one — right length, all digits, and the check digit reconciles — and `None`
otherwise. `sync_items` writes `barcode_type` as that or blank:

```python
barcodes.append({"barcode": value, "barcode_type": rules.barcode_type(value) or ""})
```

Blank is a valid option on the Item Barcode Select and the field is not required
(verified against the live doctype, not assumed).

An untyped barcode is not a lesser barcode. ERPNext stores it, the scanner reads it,
and `floor.find_item` matches it exactly the same way.

## Why this is non-obvious

The natural instinct is that a barcode field holds barcodes and a barcode has a
type, so you fill both in. The cost only appears at a client who numbers their own
stock — which is every client — and it appears as an item sync failure a long way
from the field that caused it.

It is also the golden-source rule in miniature: Intacct holds a string, and our job
was to record it, not to assert a standard about it that we had not checked.

## See also

- `docs/03-decisions.md` — 2026-08-18, the shop-floor screens these barcodes feed
- Works order numbers are NOT item barcodes. Print the order's own name as Code-128;
  the batch screen matches the scanned text against the open orders directly.
