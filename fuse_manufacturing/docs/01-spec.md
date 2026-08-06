# Fuse_Manufacturing — scope

## What it is

An ERPNext operational layer alongside Sage Intacct, per client. Intacct keeps the books.
ERPNext runs manufacturing, stock, quality, maintenance, CRM, support and HR, and posts every
financial consequence into Intacct live.

The live financial sync is the product. Everything else is ERPNext configuration.

## Deliverables

1. **Frappe integration app** — XML gateway client, masters mirror (in), postings (out),
   per-client config DocTypes.
2. **Frappe theme app** — Intacct visual language. Separate release cycle. Precedent: `nest_theme`.
3. **Mobile scanner flows** — item convert, handoff, put-away, receiving. The only place
   custom screens are justified; ERPNext's stock screens are not scanner-shaped and these
   flows are already proven with the client's people.
4. **Client configuration** — mostly setup, not development.

## Build order

1. Masters in, read-only mirror. **First.**
2. Postings out. Proven on leadertread-DEV: production run, goods receipt, warehouse
   transfer, stock adjustment — all correctly costed.
3. Client process configuration.
4. Then dates.

## Requirements source

The retired WebForms Fuse: `\\Syncflo-desktop\f\Manifold\Intacct_Fusion Manufacturing`
(root `CLAUDE.md` first, then `SBMS/Classes/Intacct/`).

Read it for **intent and Intacct behaviour**. Never for screens or code. Anything it
hand-builds that ERPNext ships as standard — works orders, BOM explosion, backflush, WIP —
is an SBMS workaround, not a requirement.

## Explicitly out of scope

- Migrating Fuse data. Nothing is live; Fuse only ever ran in dev.
- Retraining. Nobody is on it.
- Moving the books. Intacct stays the accounting system of record.
- Batch or overnight sync of any kind.
- .NET middleware or a proxy service.

## Open per-client questions

1. Which Intacct transaction definitions are active? (`SODOCUMENTPARAMS` /
   `PODOCUMENTPARAMS` / `INVDOCUMENTPARAMS`)
2. Does delivery relieve stock quantity separately from the invoice? This moves the
   handover boundary.
3. Which manufacturing-invented items (WIP intermediates, sub-assemblies) does Intacct need?
   Rule: if it holds value in a warehouse, Intacct creates it.
4. Does this client want the Intacct look, or stock ERPNext?
