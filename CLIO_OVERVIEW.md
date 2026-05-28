# QuillArrow — Clio API Orchestrator: Project Overview
<!-- READ THIS FIRST at the start of any new chat session. ~2 min read. -->
<!-- Last updated: 2026-05-28 -->

## What This App Does
Internal web tool for Quill & Arrow Law (Lemon Law division) that wraps the
Clio Manage API with a React + FastAPI layer, enabling:
- Bulk updates on Matters and Custom Fields (with Preview → Execute → Revert)
- Audit log of every write operation (who, what, when, before/after values)
- Scheduled batch jobs (planned — Azure Function Timer, not yet built)
- Billing Dashboard + Reporting (planned)
- Attorney Workload Management (planned)

## Architecture
```
Browser (React / Vite)
    │  /api/* calls
    ▼
Azure Web App (Python 3.12 / gunicorn + uvicorn workers)
    backend/main.py  ← FastAPI app, mounts static React build at "/"
    backend/routes/  ← one file per feature area
    backend/auth.py  ← JWT login (hardcoded users — Entra ID coming)
    backend/database.py ← SQLAlchemy Core, dialect-neutral (SQLite local / Azure SQL prod)
    clio_client.py   ← all Clio API calls, token refresh, pagination, rate limits
    operations.py    ← bulk-update business logic (called by routes)
    config.py        ← env-var driven config (CLIO_ENV, DATABASE_URL, etc.)
    │
    ├── Azure SQL DB (quillarrow-database / quillarrow-database-prod)
    │   Tables: audit_log, clio_tokens
    │   Auth: Managed Identity (passwordless) via azure-identity token injection
    │
    └── Clio Manage API (https://app.clio.com/api/v4)
        Auth: OAuth2 — tokens stored in clio_tokens table (DbTokenStore)
              Local dev uses clio_tokens.json (FileTokenStore)
```

## Azure Resources
| Resource | Name | Notes |
|---|---|---|
| Resource Group | QuillArrowLawResourceGroup | |
| App Service Plan | ASP-QuillArrowLawResourceGroup-a2ac | B1 (shared by dev + prod) |
| Dev Web App | QuillArrow-ClioAPIOrchestrator | Always On: ON |
| Prod Web App | QuillArrow-ClioAPIOrchestrator-Prod | Always On: ON |
| Dev URL | quillarrow-clioapiorchestrator-dccuhyf6epetf5ek.westus2-01.azurewebsites.net | |
| Prod URL (current) | quillarrow-clioapiorchestrator-prod-dcayasf7gcbhcre5.westus2-01.azurewebsites.net | |
| Prod URL (custom — pending DNS) | app.quillarrowlaw.com | Serge (IT) adding DNS records |
| SQL Server | quillarrow-sql-sever.database.windows.net | Note: typo "sever" not "server" — don't rename, firewall rules tied to it |
| Dev DB | quillarrow-database | Serverless, auto-pause 1hr |
| Prod DB | quillarrow-database-prod | Serverless, auto-pause 1hr |
| Dev App Insights | QuillArrow-ClioAPIOrchestrator | |
| Prod App Insights | QuillArrow-ClioAPIOrchestrator-Prod | Availability test: prod-health-keepwarm (5 min) |
| Function App | quillarrow-schedbatchapp | Reserved for scheduled batch jobs (not yet deployed) |

## Environments
| | Dev | Prod |
|---|---|---|
| CLIO_ENV | dev | prod |
| Clio App | "Clio API Orchestrator - Dev" | "Clio API Orchestrator - Prod" |
| Clio Client ID | Eth67c5v4... | hUN65hCo... |
| Token store | clio_tokens table, env='dev' | clio_tokens table, env='prod' |
| SQL DB | quillarrow-database | quillarrow-database-prod |

## Key Decisions (Architecture)
- **SQLAlchemy Core (not ORM)** — stays close to SQL, dialect-neutral, auditable
- **Managed Identity for SQL** — passwordless auth; token injected via SQLAlchemy `do_connect` event (not ODBC connection string) because ODBC string + MSI conflicts with pyodbc
- **FileTokenStore (local) / DbTokenStore (Azure)** — auto-selected by `get_default_token_store()` based on DATABASE_URL; easily swappable for Key Vault later
- **gunicorn -w 4 + uvicorn workers** — startup script `bash startup.sh` (relative path, not absolute — Oryx extracts to /tmp/<hash>/, not /home/site/wwwroot)
- **`_create_tables_idempotent()`** — wraps `metadata.create_all` per-table to handle gunicorn multi-worker cold-start race (MSSQL 42S01 / error 2714)
- **Transient retry (`_retry_transient`)** — handles Azure SQL auto-pause error 40613 with exponential backoff
- **Frontend served by FastAPI** — `StaticFiles` mount at "/" on the `frontend/dist` directory; only active if `dist/` exists (must run `npm run build` before deploying)
- **CORS** — currently allows localhost only; prod served same-origin so no prod CORS needed

## Gotchas / Things to Be Aware Of
- **SQL server name typo**: `quillarrow-sql-sever` (missing an 'r') — already in all firewall rules and connection strings, do not rename
- **`npm run build` before every deploy** — if you forget, the root URL serves 404. Frontend dist is not committed to git.
- **Startup command must be relative**: `bash startup.sh` not `bash /home/site/wwwroot/startup.sh` — Oryx extracts to /tmp/
- **Free DB offer**: 100k vCore-seconds/month shared across subscription. Dev DB paused = normal. First request wakes it (40613 → retry handles it).
- **Clio Prod redirect URI**: registered at `https://quillarrow-clioapiorchestrator-prod-dcayasf7gcbhcre5.westus2-01.azurewebsites.net/api/oauth/callback` — update to `https://app.quillarrowlaw.com/api/oauth/callback` once custom domain is live
- **`start_prod.ps1` requires `-Force` flag** — safety gate so muscle memory can't accidentally connect laptop to Clio Prod
- **Legacy `clio_oauth_app.py`** — Flask-based, only used for local-laptop Clio auth fallback. Deprecated for Azure; FastAPI `/api/oauth/*` routes handle prod OAuth

## Local Development
```powershell
.\start_dev.ps1 api    # FastAPI on http://localhost:8000 (hot reload)
.\start_dev.ps1 ui     # Vite React on http://localhost:3000 (proxies /api to :8000)
# First-time Clio auth: visit http://localhost:8000/api/oauth/login?session=<jwt>
# after logging in via POST /api/auth/login
```
Uses: SQLite (`orchestrator.db`), `clio_tokens.json` (FileTokenStore), Clio Dev app

## Current Users (temporary — Entra ID planned)
| Username | Password | Role |
|---|---|---|
| admin | ClioAdmin2025! | admin (all access + OAuth management) |
| clio_user | ClioUser2025! | user |

## Project Roadmap (priority order)
1. ✅ **Phase 0** — SQLAlchemy migration, Managed Identity, Azure SQL
2. ✅ **Phase A** — Production-grade Clio OAuth (DB token store, FastAPI OAuth routes)
3. ✅ **Phase B** — Prod Web App stood up (side-by-side with dev, Clio Prod authorized)
4. 🔄 **Shape A/B infra polish** — Custom domain `app.quillarrowlaw.com` (DNS pending Serge/IT), IP allowlist, Always-On ✅, Availability test ✅
5. **Phase C** — Microsoft Entra ID SSO (partners' show-stopper; replaces hardcoded users)
6. **Billing Dashboard** — Boss requested after demo; needs business requirements meeting first (metrics TBD). Architecture decided: cached-hourly snapshots to SQL, merged Dashboard+Reports page.
7. **Phase D** — Attorney Workload Management (reassign matters between attorneys)
8. **Phase E** — Scheduled Batch Jobs (Azure Function Timer, `scheduled_jobs` table)
9. **Phase F** — Hardening (alerts, SQL backup retention, move off free DB tier)

## Key Files Map
| File | Purpose |
|---|---|
| `backend/main.py` | FastAPI app, router registration, static file mount, `init_db()` call |
| `backend/database.py` | Engine, schema (audit_log + clio_tokens), init, retry logic |
| `backend/auth.py` | JWT login, user store, `get_current_user` dependency |
| `backend/routes/oauth.py` | Clio OAuth flow endpoints (`/api/oauth/login`, `/api/oauth/callback`) |
| `backend/routes/matters.py` | Matter search, bulk preview/execute/revert |
| `backend/routes/audit.py` | Audit log query endpoint |
| `clio_client.py` | Clio API client (token refresh, pagination, rate limits) |
| `clio_tokens.py` | TokenStore ABC + FileTokenStore (local dev) |
| `backend/clio_token_store_db.py` | DbTokenStore (Azure SQL) + `get_default_token_store()` |
| `operations.py` | Bulk update business logic |
| `config.py` | All env-var config (CLIO_*, DATABASE_URL, TOKEN_FILE) |
| `startup.sh` | Container startup: installs ODBC Driver 18, launches gunicorn |
| `start_dev.ps1` | Local dev launcher (Clio Dev creds, SQLite, localhost) |
| `start_prod.ps1` | Local prod launcher (requires -Force flag; discouraged) |
| `frontend/src/` | React app source (Vite) |
| `frontend/dist/` | Built React app (gitignored; run `npm run build` before deploy) |
| `.vscode/settings.json` | zipIgnorePattern — excludes node_modules, .venv, etc. from deploy zip |
| `CLIO_OVERVIEW.md` | This file — read at start of every new chat session |

## New Session Grounding Message (copy-paste to start a chat)
```
Read CLIO_OVERVIEW.md for project context, then we'll work on: [TASK]
```
```
