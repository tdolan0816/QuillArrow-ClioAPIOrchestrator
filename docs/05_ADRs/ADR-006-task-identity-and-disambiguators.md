---
status: accepted
date: 2026-07-29
---

# ADR-006: Task identity and optional disambiguators

## Status

Accepted

## Context

Reassign-by-name matched every same-named task in a matter, which is wrong when a matter has duplicates. Operators also needed a stable id.

## Decision

- `task_id` present → GET that task; ignore name disambiguators
- Else matter + `task_name`
  - Optional `task_description`, `due_at`, `current_assignee` must narrow to **exactly one** task or the row errors (lists candidate ids)
  - If no disambiguators, legacy behavior: all same-named tasks (each preview row)

Bulk **Update** Tasks uses `task_id` or matter + name (all matches) plus field columns.

## Alternatives considered

1. Name only — too ambiguous
2. task_id only — painful for spreadsheet ops
3. id or name+optional disambiguators — chosen

## Consequences

- CSV templates include extra columns
- Status Review / override remain reassign-specific
