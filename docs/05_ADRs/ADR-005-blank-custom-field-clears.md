---
status: accepted
date: 2026-07-29
---

# ADR-005: Blank custom-field CSV value clears the field

## Status

Accepted

## Context

Bulk custom-field CSVs used empty `value` to mean “wipe this field.” Validation treated empty as missing and skipped the row.

## Decision

Empty/whitespace `value` is a **CLEAR**: PATCH `_destroy: true` on the existing custom field value id. If already empty, action is `NO CHANGE (Already Empty)` and `patch_body` is null (executor skips). Picklist option lookup is skipped on clear.

Revert of a CLEAR must recreate the prior value (or handle missing value id via live GET).

## Alternatives considered

1. Reject blank values — blocked the cleanup
2. Separate `action` CSV column — extra operator burden
3. Blank means clear — chosen

## Consequences

- Template text must say blank = clear
- Execute must not PATCH null bodies
