# Billing activity cache

## Purpose

Clio emits thousands of TimeEntry / ExpenseEntry activities. The dashboard cannot query Clio on every filter change. Activities are stored in Azure SQL; “Refresh from Clio” reconciles a ~190-day window in month chunks.

## Entry points

- `POST /api/billing/refresh` — start background reconcile
- `GET /api/billing/refresh/status`
- `GET /api/billing/summary`, `GET /api/billing/activities`
- `GET /api/billing/pods`, `GET /api/billing/employees` — Clio Groups (pods) + members

## Important functions

- Month-window iteration; each month upserts then **deletes orphans** (ids in cache for that date range but not in the live Clio pull)
- Independent month commits so a failed month does not unwind others
- Aggregations use `total` (billable dollars), not `price` (rate)

## Data flow

Refresh thread → Clio activities by date → `activities_cache` upsert → orphan delete → `billing_cache_meta` timestamps. Dashboard reads SQL only.

## Dependencies

[`billing.py`](../../backend/routes/billing.py), Clio, Azure SQL. Frontend: [`BillingDashboardPage.jsx`](../../frontend/src/pages/BillingDashboardPage.jsx).

## Known risks

- Refresh is a long background job; same “leave the tab” rules as bulk ops.
- Truncation / overflow happened on long category strings — columns are capped; keep an eye on Clio field length.
- Pod filter depends on Clio Groups API remaining available to the connected token.

## Source

[`backend/routes/billing.py`](../../backend/routes/billing.py)

Related: [[Billing_Refresh]], [[ADR-001-azure-sql-activity-cache]], [[Data_Dictionary]]
