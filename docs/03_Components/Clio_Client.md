# Clio HTTP client

## Purpose

Single outbound client for Clio Manage API v4: attach OAuth tokens, refresh, paginate, GET/PATCH, raise typed errors.

## Entry points

- `ClioClient()` constructed in `get_clio_client` and in background workers (workers often construct a **new** client; they do not share the request-scoped one).
- `get`, `patch`, `_request`, token load/save.

## Important functions

- Token refresh on expired access token
- `_save_tokens` — must require `refresh_token` in Clio’s response or raise `ClioAuthError` (do not `payload["refresh_token"]` on an error body)
- Pagination helpers used by billing and lookups

## Data flow

Route → `ClioClient` → Clio HTTPS. Tokens from `clio_tokens` table (Azure) or `clio_tokens.json` (local file store).

## Dependencies

[`clio_client.py`](../../clio_client.py), [`config.py`](../../config.py), [`clio_tokens.py`](../../clio_tokens.py), [`backend/clio_token_store_db.py`](../../backend/clio_token_store_db.py), [`backend/dependencies.py`](../../backend/dependencies.py).

## Known risks

- Dead refresh token used to 500 the whole app; now 401. User must hit `/api/oauth/login`.
- Each row of a bulk job can be one or more Clio round trips — why jobs exist ([[ADR-002-background-jobs-for-azure-gateway]]).
- Rate limits / 429 — client should back off; bulk jobs amplify traffic.

## Source

[`clio_client.py`](../../clio_client.py)
