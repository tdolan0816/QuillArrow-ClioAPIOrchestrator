# Bulk jobs (preview, execute, cancel, revert)

## Purpose

Run long Clio-bound loops off the HTTP request so Azure’s ~230s gateway does not kill them. Persist progress so any gunicorn worker can answer polls.

## Entry points

- `POST /api/preview/bulk-*` and `POST /api/execute/bulk-*` → `create_job` + `run_in_thread`
- `GET /api/execute/jobs`, `GET /api/execute/jobs/{id}`
- `POST /api/execute/jobs/{id}/cancel`
- `POST /api/execute/revert/{batch_id}` (also a job)

## Important functions

| Symbol | Role |
|---|---|
| `create_job` | Insert `running` / `preparing` |
| `set_phase_executing` | After CSV validate |
| `record_row` | Counters + optional audit write |
| `raise_if_cancelled` / `JobCancelled` | Cooperative stop |
| `finish_job` | `ok` / `error` / `cancelled` + JSON results |
| `_finish_cancelled` | Query audit rows for this job id and reverse PATCH |

Prepare lives in [`_prepare.py`](../../backend/routes/_prepare.py) (read-only). Execute PATCHes then audits.

## Data flow

```
HTTP start → bulk_jobs row → thread
  → prepare (Clio GET) → PATCH (execute only) → audit_log
UI polls bulk_jobs
Cancel sets cancel_requested → worker notices → reverting phase if rows applied
```

Job `id` **is** the audit `batch_id` for execute jobs.

## Dependencies

[`_bulk_jobs.py`](../../backend/routes/_bulk_jobs.py), [`execute.py`](../../backend/routes/execute.py), [`preview.py`](../../backend/routes/preview.py), Azure SQL, Clio.

## Known risks

- Threads die on deploy; rows can stay `running` ([[Reliability]]).
- Cancel is not instant (checked every few rows).
- Revert of cancel must not itself honor cancel (half rollback is worse).
- `results` JSON on huge jobs can be large; UI also loads failures from audit.

## Source

[`backend/routes/_bulk_jobs.py`](../../backend/routes/_bulk_jobs.py)

Related: [[Bulk_Preview_Execute_Cancel]], [[ADR-003-db-backed-job-registry]], [[ADR-004-cooperative-cancel-and-rollback]]
