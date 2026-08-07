# Fuse_Manufacturing — Sage Intacct integration reference

Facts below were learned the hard way against a real Intacct company. **Do not rediscover
them, and do not "improve" on them without evidence from the gateway.**

## Transport

- Endpoint: `https://api.intacct.com/ia/xml/xmlgw.phtml` (XML gateway).
- **Not REST.** REST forces every customer through app registration in the Sage developer
  portal; the XML gateway needs only a sender ID plus company credentials.
- Issued from Python/`requests` inside Frappe. No .NET SDK, no middleware, no proxy.
- Credentials: gateway `senderid`/`senderpassword` + company `userid`/`companyid`/`userpassword`.
  Frappe site config or a credentials DocType — never the repo.

## Session / login

**Every login must carry `<locationid>`.** Manufacturing transaction definitions are set to
"Entity only"; a top-level session is rejected with **BL01001973**.

## Entities

Read entities from **`LOCATIONENTITY`**, *not* `LOCATION`. `LOCATION` also returns ordinary
locations nested under entities and will over-report. Filter on `STATUS = active`.

Store the Intacct entity ID against each ERPNext Company.

## The four manufacturing entries — exact names

| Name | Meaning |
|---|---|
| `Manufacturing Run Increase` | finished goods in — **carries unit cost** |
| `Manufacturing Backflush Decr` | components consumed |
| `Manufacturing Run Decrease` | |
| `Manufacturing Backflush Incr` | |

- **Line cost is a UNIT cost, not extended.** Proven live.
- **Quantities go POSITIVE on every leg.** Each definition applies its own sign.

Worked example — build 10 units that consume 30 kg of a component costing R4/kg,
finished cost R15 each:

- `Manufacturing Backflush Decr`: quantity **30** (positive), unit cost **4**. Stock falls
  30 kg, R120 leaves the component account.
- `Manufacturing Run Increase`: quantity **10** (positive), unit cost **15**. Stock rises
  10 units, R150 lands in the finished-goods account.

Send 30 and 10 — never −30. Send 4 and 15 — never 120 and 150.

## Units of measure

UOM strings must match the item's UOM **character for character** or the line is rejected
with **BL03000018 "Missing unit"**. They are SA English:

`Cubic metres`, `Litres`, `Metres`, `Millimetres`, `Kilograms`, `Each`

## Paging — the one that bit us live

**Paging MUST order by `RECORDNO`.** Without an explicit order Intacct returns rows in any
order, so offset pages overlap AND leave gaps. An item sync reported **2362 rows from a
master of 2000**.

## Throughput limits

- The gateway limits **concurrent connections per company** (~5 in process, the rest queue
  FIFO ~5s). It **queues rather than rejecting**.
- Request timeout: 15 minutes.
- Keep **queries under ~1000 records** and **manipulations under ~100**.

## What Intacct does NOT have

- **No manufacturing process objects at all.**
- Its only recipe structure is `ITEMCOMPONENT` — 17 fields, flat, **single-level**.
- `WORKORDER` exists but is a **field-service repair job**, not a production order.

## Per-tenant configuration — read before scoping

Every tenant is configured differently. Read the client's own `SODOCUMENTPARAMS` /
`PODOCUMENTPARAMS` / `INVDOCUMENTPARAMS` before scoping. Which definitions are active, and
whether delivery relieves stock quantity separately from the invoice, **changes where the
handover boundary sits**.

## Carried forward from the WebForms Fuse (intent only, not code)

- Stores = Intacct `WAREHOUSE`. Lot-tracked items → `ENABLE_LOT_CATEGORY` + `<itemdetail><lotno>`.
- Stock counts bypass `ICCYCLECOUNT` (its header is not API-updatable) — post the variance
  batch as atomic stock adjustments referencing the count number.
- Item identity bridge: every ERPNext Item needs the Intacct `ITEMID` stored against it.
- **Idempotency:** deterministic `controlid` from the local PK + `<uniqueid>true</uniqueid>`;
  multi-record posts use `<operation transaction="true">`.

Note: Fuse posted *all* works-order movement as `create_ictransaction` Stock Adjustment
In/Out with the WO number in `<referenceno>`. That was an SBMS workaround — the four named
manufacturing definitions above are the correct route here. Verify on leadertread-DEV.

## Read from the donor code 2026-08-06 (`SBMS/Classes/Intacct/`)

Verified by reading the source, not assumed.

### Auth
- The SDK path does **login-per-request** — no session handling. The raw-gateway path caches a
  session for 20 min (sessions idle out ~1 hr). Re-logging in per call turned one kit import
  into 16 logins.
- Two Intacct companies are in play, **neither of them live**:
  - **`leadertread-DEV`** — the sandbox. Masters and postings are proven here first.
    Its entity is **`100`** (confirmed by `LOCATIONENTITY` on 2026-08-06).
  - **`leadertread-imp`** — the **final testing** instance. Transaction tests move here
    once DEV is proven. The donor app's config points at it, with entity `E100`.
- **The entity ID differs between the two companies** — `100` on DEV, `E100` on imp.
  Switching the connection is a Settings change, no code, but the entity must change with
  it. Get it wrong and the login fails outright; DEV's own entity was wrong at first setup
  and produced `XL03000006`, which reads like a credentials problem rather than an entity one.
- Connection cap: ASP.NET pinned the host to 2 connections and the kit import (~32 calls) died
  with "A task was canceled". Raised to 24. **Python won't have this bug** — but the underlying
  Intacct-side concurrency limit still applies.
- Retry: 3 attempts, 2s then 4s backoff, on timeout / empty response / 5xx / 429 only.
  A genuine 4xx is not retried.

### Transactions — one engine, definition selects behaviour
`create_ictransaction` is the engine for adjustments, put-away and manufacturing. The
`TransactionDefinition` decides what it does.

| Flow | Intacct call | Definition(s) |
|---|---|---|
| Stock adjustment | `create_ictransaction` | `Inventory Adjustment` (signed qty) |
| Manufacture — produce | `create_ictransaction` | `Manufacturing Run Increase` (UPDATES_COST=true) |
| Manufacture — consume | `create_ictransaction` | `Manufacturing Backflush Decr` (UPDATES_COST=false) |
| Put-away | `create_ictransaction` ×2 | `Stock Transfer Decrease` then `Stock Transfer Increase` |
| Warehouse transfer | **`create_whtransfer`** | Intacct drives SYS-Warehouse Transfer Out/In itself |
| Goods receipt | `create_potransaction` | `PO Receiver-Inventory`, as a **conversion** of the PO |

### Details that cost real debugging
- **`Manufacturing Run Decrease` and `Manufacturing Backflush Incr` are CONVERT-ONLY.** They
  cannot be posted through `create_ictransaction` at all — they exist only by converting the
  source document.
- **Cost is sent only when the definition has `UPDATES_COST=true`.** On a consume leg, leave it
  null or you override Intacct's own valuation.
- **Warehouse transfer is one document with both legs**, not two adjustments. `InOut` is
  `"O"`/`"I"` — **not** `"Out"`/`"In"`; a wrong value is rejected as "The required field
  'From Location' is missing".
- **Transfer `Action` must be `Post`, not `Submit`** (BL03002129). Valid actions depend on
  `TRANSFERTYPE`: Immediate → Draft|Post; In transit → Draft|Transfer out|Transfer in.
- **Goods receipt is a conversion:** `createdfrom = "<source def>-<source docno>"`
  (e.g. `Purchase Order-Inventory-PO0051`), and each line needs
  `SourceLineRecordNo = PODOCUMENTENTRY.RECORDNO`. That linkage is what drives the PO into
  Partially Converted / Converted.
- **Bin-tracked items must carry a bin** on every movement. Donor resolves the warehouse's
  **lowest BINID** for determinism and fails loudly if the warehouse has none.
- `LocationId` is required on **every line**.

### The failure hole to fix, not port
Put-away posts the Out leg, then the In leg. **If the In leg fails, the Out has already
committed** — stock has left the bay and sits nowhere. The donor can only raise a message
telling someone to fix it by hand in Intacct.

This is exactly the case the "On failure" column exists for. Either post both legs in one
`<operation transaction="true">` so Intacct rolls them back together, or use `create_whtransfer`
(single document, both legs) as the transfer path already does.

## Entity mapping (fill in as confirmed on leadertread-DEV)

| ERPNext | Intacct | Direction | Key field | Status |
|---|---|---|---|---|
| Company | LOCATIONENTITY | in | entity id → `<locationid>` | to verify |
| Item | ITEM | in | `ITEMID` | to verify |
| Warehouse | WAREHOUSE | in | | to verify |
| UOM | | in | exact string | to verify |
| Customer | CUSTOMER | in | | to verify |
| Supplier | VENDOR | in | | to verify |
| Account | GLACCOUNT | in | | to verify |
| Stock Entry (manufacture) | Manufacturing Run Increase / Backflush Decr | **out** | | to verify |
| Purchase Receipt | ICTRANSACTION | **out** | qty + value | to verify |
| Stock Reconciliation | Stock Adjustment | **out** | | to verify |
| Stock Entry (transfer) | | **out** | | to verify |
| Purchase Order | PODOCUMENT | out, no ledger impact | | to verify |
