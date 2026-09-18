# Frontend React SPA

## Purpose

Operator UI: login, bulk CSV workflows, billing dashboard, audit batches.

## Entry points

[`App.jsx`](../../frontend/src/App.jsx) routes. Production: files in `frontend/dist` served by FastAPI.

## Important modules

- [`client.js`](../../frontend/src/api/client.js) — fetch wrapper
- Pages listed in [[Catalog]]

## Data flow

JWT in memory/storage → `/api/*`. Bulk tabs poll jobs every ~2s. Billing refresh polls `/api/billing/refresh/status`.

## Dependencies

Vite 8, React, Chart.js on the billing page, Tailwind-style utility classes.

## Known risks

- Must `npm run build` before deploy or Azure serves an old SPA.
- Poll loops swallow transient errors (DB wake) — a permanent 404 looks like a hang.
- Cancel requires `activeJobId`; after refresh, use jobs list to reattach (list API exists; UI reattach is limited).

## Source

[`frontend/src/`](../../frontend/src/)
