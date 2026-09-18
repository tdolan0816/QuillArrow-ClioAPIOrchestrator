# Unreleased

Work on `main` at **`f0570a7` (2026-08-12)** that should be confirmed in the next successful Azure deploy, then moved to a dated changelog file.

## Added

- Bulk Update Tasks (CSV): status and other Clio task fields; template `/api/templates/bulk-update-tasks.csv`
- Job cancel: `POST /api/execute/jobs/{id}/cancel` plus Cancel on preview/execute progress cards; execute rolls back applied rows
- `GET /api/execute/jobs` to list recent/active jobs
- Audit log batch view and per-batch CSV download (shipped earlier on `main`: `0a2c0eb`)

## Changed

- Bulk preview/execute/revert run as background jobs (Azure ~230s gateway)
- Custom-field preview caches picklist options and combines matter resolve + current values
- Blank custom-field `value` clears the field
- Task reassign: `task_id` and optional disambiguators
- Clio token refresh: missing `refresh_token` → 401, not 500

## Fixed

- Revert worker call signatures (`get_engine`, `record_row`, `finish_job`) so background revert can finish
- Bulk Operations success banner using real job counts; failed-row table from audit `status=error`
