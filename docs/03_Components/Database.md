# Database engine and core schema

## Purpose

Process-wide SQLAlchemy engine, transient retry for Azure SQL auto-pause, `audit_log` + `clio_tokens`, `init_db` at startup.

Billing tables and `bulk_jobs` are defined next to those features but use the same `get_engine()`.

## Entry points

`get_engine()`, `get_db()` (FastAPI dependency), `init_db()`, `_retry_transient`.

## Important functions

- `_ensure_new_audit_columns` — ALTER for `batch_id` / revert flags
- Worker-safe `create(checkfirst=True)` so gunicorn races do not crash startup

## Data flow

All workers share Azure SQL. There is no shared Python dict for jobs.

## Dependencies

[`backend/database.py`](../../backend/database.py). Identity: connection string and/or Managed Identity (see file header).

## Known risks

Cold start vs paused SQL. String truncation if we store unbounded Clio text in `VARCHAR` columns.

## Source

[`backend/database.py`](../../backend/database.py) — columns in [[Data_Dictionary]]
