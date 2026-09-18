---
status: accepted
date: 2026-06-15
---

# ADR-001: Cache Clio activities in Azure SQL

## Status

Accepted

## Context

Clio contains on the order of thousands of new Activities per day. Querying Clio for every dashboard filter change is too slow and burns API quota.

## Decision

Persist TimeEntry/ExpenseEntry rows in Azure SQL (`activities_cache`). Dashboard aggregations query the cache. A explicit “Refresh from Clio” job reconciles a ~6-month window.

## Alternatives considered

1. Query Clio on every request — too expensive
2. In-memory cache — lost on recycle, not shared across workers
3. Azure SQL persistent cache — chosen

## Consequences

- Fast dashboard reads
- Less Clio traffic
- Must run sync logic (month chunks, orphan delete)
- Cache freshness is an operator action
- Column widths matter (SQL Server index key limits)
