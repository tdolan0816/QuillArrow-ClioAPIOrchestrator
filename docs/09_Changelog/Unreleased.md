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
- SPA client routes (`/login`, `/billing`, `/matters`, …) serve `index.html` on refresh instead of a JSON 404 (`backend/main.py` `_SPAStaticFiles`)
- Azure SQL auto-pause: `HYT00` login timeout is retried, pyodbc login timeout raised to 30 s, `DbTokenStore.load/save/exists` retry on transient errors, and a paused DB during boot no longer kills gunicorn
- Gunicorn `--preload` fork race with the SQLAlchemy pool: `gunicorn.conf.py` `post_fork` disposes the inherited pool so workers do not share pyodbc sockets (was surfacing as `08S01 TCP Provider: Error code 0x20 (32)`)
- Clio-authorization 401 no longer logs the user out of the app; frontend renders the re-authorize message and keeps the app session (`backend/dependencies.py` + `frontend/src/api/client.js`)
