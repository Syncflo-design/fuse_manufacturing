# Production planning — what must be configured first

*Leader Rubber Company. Drafted 2026-09-07 against the live site (erpnext 16.34.1,
fuse_manufacturing 0.9.1).*

Two things have been asked for:

1. **Reorder requirements report** — for every finished good, what to make; for every
   compound, what to mix; for every raw material, what to buy. Demand from open sales
   orders plus a target stock level, netted against what is on hand, in progress and on
   order, exploded through the BOMs.
2. **Machine / production line plan** — which work runs on which machine, when, and how
   loaded each machine is.

Both are standard ERPNext once the data below exists. Neither can be produced from what
is on the site today. This document lists exactly what is missing, who supplies it, and
the decisions the client has to make before any of it is built.

---

## What the site already has

| Input | State on the site | Source |
|---|---|---|
| Items | 2 447 stock items | Intacct ITEM sync |
| BOMs | 900 active, multi-level (tread/patch → final compound → raw materials) | Intacct sync |
| Open sales orders | Mirrored from Intacct, with due date and remaining qty per line | Intacct SODOCUMENT sync |
| Open purchase orders | Mirrored from Intacct, with due date | Intacct PODOCUMENT sync |
| Stock on hand | Per item per warehouse in ERPNext Bins | Opened from Intacct, moved in ERPNext |
| Warehouses | 50+, flat under All Warehouses, no warehouse types set | Intacct sync |
| Work Orders | 4, all manual test orders on compounds; no operations | Estelle, Sep 2026 |
| Workstations / Operations / Routings | None (one unused Operation, "Assembly") | — |
| Production Plans / Job Cards | None | — |
| Manufacturing Settings | Defaults: capacity planning on, 30 days, backflush from BOM | — |

---

## Goal 1 — Reorder requirements report

The calculation the client runs today, per finished item, in the workbook
"Outstanding Orders by Inv Item":

    NEED = outstanding sales-order qty + target stock (Max) − stock on hand

with rolls already allocated to orders netted off the outstanding figure. The report
reproduces that, then carries NEED down through the BOM levels.

### Level 0 — finished goods (what to make)

| # | Required | Status | Who / where |
|---|---|---|---|
| 1.1 | Every finished good has a default BOM | Done (851 items) | Intacct |
| 1.2 | All open customer orders exist in Intacct and are mirrored | Sync exists; **only 20 open orders on the site vs 139 in the workbook** | Client must capture all orders in Intacct, not Evolution |
| 1.3 | **Target stock level ("Max") per item** | **Missing entirely** | Decision A |
| 1.4 | Which warehouses count as available finished-goods stock | Not defined | Decision B |
| 1.5 | Roll ↔ kilogram conversion per item (42 kg and 17.5 kg rolls) | Item UOM conversions synced from Intacct; must be verified item by item | Intacct SOUOMDETAIL |
| 1.6 | Rolls already allocated to orders | Not modelled | Decision C |
| 1.7 | Inter-branch demand (IBTs to KZN / Cape Town) | Not modelled | Decision D |
| 1.8 | Planning horizon — which orders count | Not defined | Decision E |

### Level 1 — compounds / sub-assemblies (what to mix)

| # | Required | Status | Who / where |
|---|---|---|---|
| 2.1 | Compound BOM linked on the parent BOM line | Done (`bom_no` set on BOM items) | Intacct |
| 2.2 | Compound stock held in an identifiable warehouse | Exists ("JHB Industria - Mixing Kelvin Compound") but not typed | Decision B |
| 2.3 | Open Work Orders counted as supply | Standard once WOs are raised in ERPNext | Process |
| 2.4 | Mix batch size per compound (rounding rule for NEED) | Not held anywhere; BOMs are per 1 unit | Decision F |
| 2.5 | Process loss / scrap % on compound BOMs | All 0 | Optional, client |

### Level 2 — raw materials (what to buy)

| # | Required | Status | Who / where |
|---|---|---|---|
| 3.1 | Raw-material stock in the stores warehouse(s) | Exists ("Stores", "Raw materials", "Mixing Kelvin Raw Materi", "Mixing Telford Raw Mater") | Decision B |
| 3.2 | Open purchase orders counted as supply | Sync exists | Intacct |
| 3.3 | Supplier lead time per item | Not held | Later phase; Intacct item-vendor lead time or ERPNext Item.lead_time_days |
| 3.4 | Minimum order / pack quantity per raw material | Not held | Later phase |

### Decisions the client has to make — goal 1

- **A. Where does the target stock level live?** The site's rule is that Intacct is the
  golden source. Intacct holds reorder settings per item per warehouse (reorder point,
  reorder qty, min/max order qty on ITEMWAREHOUSEINFO — to be verified on the gateway
  before relying on it). If the client will maintain Max there, it syncs into ERPNext's
  Item Reorder table. If not, it is a field captured in ERPNext and Intacct never sees it.
  **Recommendation: Intacct.**
- **B. Warehouse classes.** Which warehouses are *available finished goods* (Dispatch,
  Factory, Slab Stock?), which are *compound*, which are *raw material*, and which are
  excluded (Quality hold, consignment stock at customers — A1 Retreaders, Brelko,
  Frontier, Kaltyre, Pride in Tyres, Nuvo, Bandag). Today nothing distinguishes them.
  Set with ERPNext Warehouse Type; the report filters on it.
- **C. Allocated rolls.** Either use ERPNext stock reservation against the sales order
  (exact equivalent of the workbook's allocated column) or drop the concept and treat all
  on-hand stock as available. Reservation is more work for dispatch on every order.
  **Recommendation: drop it for phase 1.**
- **D. Inter-branch demand.** The workbook counts IBTs to KZN and Cape Town as demand on
  JHB. In ERPNext these are Material Requests of type Material Transfer raised by the
  branch. Either the branches raise them, or branch demand is ignored.
- **E. Horizon.** All open orders regardless of due date, or only orders due within N
  days. **Recommendation: all open, with due date shown so overdue is visible.**
- **F. Batch sizes.** Compounds are mixed in fixed batches. The report should round the
  compound NEED up to whole batches. The batch size per compound has to be supplied
  (BOM quantity or a field on the item).

---

## Goal 2 — Machine / production line plan

Nothing for this exists yet. It is all client-supplied master data.

| # | Required | What it is | Who |
|---|---|---|---|
| 4.1 | **Workstations** | One per machine or line: mixers, calenders, extruders, presses, cutters. Working hours per day, days per week, holiday list. Interchangeable machines share a Workstation Type. | Client (production manager) |
| 4.2 | **Operations** | The steps: Mix, Mill, Extrude, Cure, Cut, Inspect, Pack. Each with a default workstation. | Client |
| 4.3 | **Routings** | The ordered list of operations per product family (precure tread, patch, compound), with time per unit or per batch and setup time. | Client |
| 4.4 | **BOMs with operations** | Each BOM (or product family) linked to its routing. 900 BOMs, so this is done by family rule, not by hand. | Fuse, from client's family → routing map |
| 4.5 | **Manufacturing Settings** | Overtime allowed? Production on holidays? Minutes between operations? Capacity horizon (30 days now). | Client decides, Fuse sets |
| 4.6 | **Job Card discipline** | Someone on the floor starts and completes each Job Card, or times are never real and the plan drifts. | Client process |
| 4.7 | Shift pattern | Single, double or continuous shift per machine. | Client |

### Decisions the client has to make — goal 2

- **G. Level of detail.** Plan per machine, or per line/department? Per machine gives a
  true load picture but needs every machine's hours and every routing's time. Per
  department is faster to set up and usually enough for a first plan.
- **H. Time basis.** Time per unit (per roll / per kg) or per batch. Compounds are per
  batch; tread is per roll. Both are supported but must be stated per operation.
- **I. Who owns the data.** Routings and machine times live in ERPNext only — Intacct has
  no equivalent. The client must accept maintaining them there.

---

## Sequence

1. Client answers decisions A–F. Client captures all open orders in Intacct.
2. Fuse: warehouse types set, Max synced or captured, batch sizes loaded.
3. Fuse: reorder requirements report built and checked against the workbook for one week.
4. Client supplies workstations, operations, routings (decisions G–I).
5. Fuse: routings attached to BOMs by family; capacity planning switched on for real.
6. Machine plan: Work Orders → Job Cards → workstation load / Gantt.

Lead times, minimum order quantities and scrap percentages come after step 3 is proven.
