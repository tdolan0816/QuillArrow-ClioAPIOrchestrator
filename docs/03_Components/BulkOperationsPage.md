# Bulk Operations page

## Purpose

All CSV bulk modules and the single custom-field form. Shared `CsvBulkTab`: preview job → table / Status Review (tasks reassign only) → execute job → failures table → revert job.

## Entry points

Route in the SPA (Bulk Operations). Tabs: single field, bulk fields, bulk matters, bulk reassign tasks, **bulk update tasks**.

## Important functions (behavioral)

- `handlePreview` / `handleExecute` / `handleCancel` / `handleRevert`
- `finishFromResult` — banners from job counts, not “0 errors means success”
- Status Override + Status Review only on **reassign** tab
- Templates downloaded from `/api/templates/*.csv`

## Data flow

Upload CSV → preview job (Clio reads) → execute job (Clio PATCH + audit) → optional cancel rollback or later revert.

## Dependencies

[[Bulk_Jobs]], [[Endpoints]], [`BulkOperationsPage.jsx`](../../frontend/src/pages/BulkOperationsPage.jsx).

## Known risks

- Closing the progress UI does not cancel ([[Reliability]]).
- Preview of thousands of custom-field rows is still Clio-bound (one lookup per matter after caching picklists).
- Task reassign vs task update are different endpoints; do not mix CSVs.

## Source

[`frontend/src/pages/BulkOperationsPage.jsx`](../../frontend/src/pages/BulkOperationsPage.jsx)
