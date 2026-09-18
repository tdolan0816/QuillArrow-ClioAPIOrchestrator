---
status: accepted
date: 2026-07-30
---

# ADR-004: Cooperative cancel and execute rollback

## Status

Accepted

## Context

Operators need to stop a long preview or execute. Python threads cannot be safely killed. Leaving the page did not stop work, which looked like a hang and left partial Clio writes.

## Decision

`POST /api/execute/jobs/{id}/cancel` sets `cancel_requested`. Workers check every few rows and raise `JobCancelled`.

- **Preview / validation:** stop; nothing to undo
- **Execute:** stop, then revert every successful `audit_log` row for that job id (same machinery as manual Revert). Rollback ignores further cancel flags

## Alternatives considered

1. Kill the thread — unsafe
2. Cancel without rollback — leaves partial jobs, which stakeholders rejected
3. Cooperative cancel + audit-based rollback — chosen

## Consequences

- Cancel is delayed by a few Clio calls
- Rollback completeness depends on audit rows being written after each successful PATCH
- Deploy still cannot cancel; it aborts the process
