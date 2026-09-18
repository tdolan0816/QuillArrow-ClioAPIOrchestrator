---
status: accepted
date: 2026-07-21
---

# ADR-002: Background jobs for Azure gateway timeout

## Status

Accepted

## Context

Azure App Service’s front-end gateway times out around 230 seconds. Bulk CSV preview/execute and billing refresh do per-row Clio I/O and exceed that limit. The timeout cannot be raised by app settings.

## Decision

HTTP handlers only **start** work and return a `job_id`. A background thread does Clio I/O. The UI polls a status endpoint.

## Alternatives considered

1. Raise gunicorn timeout — does not affect the gateway
2. Smaller CSVs only — not acceptable for 1000+ row firm cleanup
3. Azure Functions / queue workers — future hardening; threads shipped first

## Consequences

- Large batches can complete
- Jobs die if the process recycles ([[Reliability]])
- Preview and execute both use this pattern
