# Backend FastAPI container

## Purpose

HTTP API, startup DB init, static hosting of `frontend/dist`.

## Entry points

- `uvicorn backend.main:app` (dev)
- Azure startup / `startup.sh` + gunicorn (prod)
- Interactive schema: `{origin}/docs` (Swagger)

## Important functions

- `init_db()` on import/startup
- Router includes under `/api`
- `StaticFiles(..., html=True)` last so SPA fallback works

## Data flow

See [[Container_Diagram]]. Long work must not stay on the request thread ([[Bulk_Jobs]], billing refresh).

## Dependencies

All `backend/routes/*`. CORS currently allows localhost Vite ports; production should restrict origins.

## Known risks

Multiple workers + in-process threads ([[ADR-003-db-backed-job-registry]]). First request after idle may wait on SQL resume.

## Source

[`backend/main.py`](../../backend/main.py), [`backend/database.py`](../../backend/database.py)
