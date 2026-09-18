# Auth (app JWT) and Clio OAuth

## Purpose

Two independent identity flows. The app JWT gates **our** UI/API. Clio OAuth gates **Clio** as the connected firm.

## Entry points

- `POST /api/auth/login` — username/password, returns JWT
- `get_current_user` / `require_auth` on almost all `/api/*` routes
- `GET /api/oauth/login`, `/api/oauth/callback`, `/api/oauth/status`

## Important functions

- JWT HS256, ~8 hour expiry, `USERS` dict with bcrypt hashes in [`auth.py`](../../backend/auth.py)
- Clio authorization code flow; tokens persisted per env (`dev`/`prod`)

## Data flow

Browser stores app JWT → `Authorization: Bearer`. Server uses Clio access token from SQL/file, never from the browser.

## Dependencies

[`backend/auth.py`](../../backend/auth.py), [`backend/routes/oauth.py`](../../backend/routes/oauth.py), [`backend/dependencies.py`](../../backend/dependencies.py).

## Known risks

- `SECRET_KEY` and demo users live in source — **must** move to Key Vault / env before partner or production hardening.
- Entra ID is explicitly **not** wired; comments in `auth.py` describe a future swap of the user store only.
- Clio refresh failure is a 401, not a process crash.

## Source

[`backend/auth.py`](../../backend/auth.py), [`backend/routes/oauth.py`](../../backend/routes/oauth.py)
