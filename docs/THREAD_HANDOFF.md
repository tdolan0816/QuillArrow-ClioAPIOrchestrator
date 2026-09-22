# Thread handoff

Use this file to start a **new** Cursor chat. Do not continue the long bulk-ops thread.

## First message to paste

```
Read docs/THREAD_HANDOFF.md and docs/00_Home.md. Then do: <one outcome>.
Do not re-summarize the whole project.
```

Replace `<one outcome>` with a single task (example: diagnose Azure black-screen / restart loop; prove cancel on a 30-row custom-field execute; Entra ID SSO spike).

## Repo snapshot

- Branch: `main` = `origin/main`
- Last commit: **`9189af3` (2026-09-21)** — Bulk Update Tasks (CSV) for all updatable Clio task fields
- That commit also includes cooperative job cancel/rollback and custom-field preview caching (not fully proven on an 8k-row live run)

## What the app is

Firm-internal GUI over Clio API v4: bulk custom fields, matter properties, task reassignment, task field updates, audit/revert, Billings & Activities dashboard (Pods / Clio Groups). Stack: FastAPI + Vite React, Azure App Service, Azure SQL, Clio OAuth.

Auth today is **local JWT** (`backend/auth.py`), not Entra ID. Clio OAuth is separate (`/api/oauth/login`). Entra / IP allowlist are **future**, not current architecture.

## Docs map

Start at [[00_Home]]. Architecture: [[System_Context]], [[Container_Diagram]]. Risks: [[Reliability]].

## Open work (next coding threads)

1. **Verify the reliability fixes in prod** — code is in the working tree (not yet committed): SPA fallback (`backend/main.py`), Azure SQL `HYT00` + non-fatal `init_db` (`backend/database.py`), token-store retry (`backend/clio_token_store_db.py`), `gunicorn.conf.py` `post_fork` pool dispose wired via `startup.sh`, Clio-vs-app 401 split (`backend/dependencies.py` + `frontend/src/api/client.js`). Steps: `cd frontend; npm run build` → deploy prod from VS Code → wait for all four workers to log `Application startup complete` → load the app. Details in [[Reliability]] and [[2026-09-22]].
2. **Prove cancel + large CSV** — 8k custom-field preview/execute was not fully validated after cancel + cache changes. First test a ~30-row execute and click Cancel mid-run.
3. **Deploy kills jobs** — background work is in-process threads. Redeploy during an 8k job orphans `bulk_jobs` rows in `running`.
4. **Partner-ready** — security review (JWT secret in source, CORS, Entra), performance of billing refresh.

## Do not do in the next thread unless asked

- Migrate `Misc_Docs/` into this vault
- Rewrite C4 L1 for a small CSV change
- Re-implement Bulk Update Tasks (it is on `main`)