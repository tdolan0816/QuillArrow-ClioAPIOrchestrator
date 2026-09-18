---
status: accepted
date: 2026-07-21
---

# ADR-003: Database-backed job registry

## Status

Accepted

## Context

Gunicorn runs multiple workers. The worker that starts a job is often not the worker that serves the next poll. An in-process dict is invisible across processes and is lost when the user closes a tab (the thread may still be running on another worker).

## Decision

Store job state in Azure SQL table `bulk_jobs`. Every worker reads/writes the same rows.

## Alternatives considered

1. In-memory dict — wrong with multiple workers
2. Redis — extra service; SQL already required
3. Azure SQL table — chosen

## Consequences

- Polling works; tab close does not lose the job id **if** the UI stored it or the user lists jobs
- Need schema migrations for new columns (`cancel_requested`)
- `results` JSON can grow large
