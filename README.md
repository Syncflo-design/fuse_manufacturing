# fuse_manufacturing

Sage Intacct integration for ERPNext. Intacct keeps the books; ERPNext runs the
operation and posts every financial consequence into Intacct live.

Companion app: `fuse_theme` (look and feel, released separately).

## Layout

Flat on purpose — three modules and one settings DocType.

| File | Does |
|---|---|
| `gateway.py` | Everything that talks to Intacct: session, query with paging, post |
| `masters.py` | Masters in — warehouses, UOMs, items, bins |
| `install.py` | Custom fields holding Intacct identity on Item / Warehouse / Company |
| `Intacct Settings` | Credentials, entity, tuning. One Intacct company per site. |

## Masters in

Run in dependency order — items need the UOMs, bins need the warehouses:

```
bench --site <site> execute fuse_manufacturing.masters.sync_all
```

Or individually: `sync_warehouses`, `sync_uoms`, `sync_items`, `sync_bins`.
Every one is idempotent.

### Why UOMs are synced before items

Intacct rejects any transaction line whose unit does not match the item's UOM character
for character — error `BL03000018`, "Missing unit". Its strings are SA English
("Cubic metres", "Litres", "Kilograms") and ERPNext ships none of them.

So `sync_uoms` creates them with Intacct's exact spelling, and `sync_items` **skips**
any item whose unit is still missing rather than substituting a near-match. A silently
mapped UOM would post fine today and fail much later, much less obviously.

### What is deliberately not read

Item cost. Intacct does not carry it on the `ITEM` object at all — the only place the
API exposes it is `ITEMWAREHOUSEINFO.AVERAGE_COST`, per warehouse. It arrives with the
stock pull, not the item.

## Install

The GitHub repo must be named `fuse_manufacturing`, lowercase. `bench get-app` clones
into a folder named after the repo and then looks for a Python module of that name.

```bash
bench get-app fuse_manufacturing <repo-url>
bench --site <site> install-app fuse_manufacturing
```

## Status

v0.1.0. Compiles clean, ruff clean. **No call has been made against Intacct yet** —
no gateway credentials on the build machine. The XML envelope shapes follow the donor
app's proven raw-gateway calls, but the query/filter path is unproven until it runs
against `leadertread-DEV`.

See `fuse_manufacturing/docs/02-intacct-integration.md` for the gateway constraints, and
`fuse_manufacturing/docs/03-decisions.md` for why the architecture is what it is.
