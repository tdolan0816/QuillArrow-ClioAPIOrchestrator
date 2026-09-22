# Reliability and operations

Known failure modes. Update this page when a cause is confirmed or a fix ships.

## Login loop / dashboard 500 / JSON 404 on refresh

**Symptoms observed Sep 18–22 2026:**

- `GET /login` returned `{"detail":"Not Found"}` after a browser refresh or after the frontend redirected on 401.
- Dashboard flashed and bounced back to the login page.
- `pyodbc.OperationalError` in logs: `40613` (`quillarrow-database-prod` not currently available), `HYT00` login timeout, or `08S01 TCP Provider: Error code 0x20 (32)` (broken pipe) — often inside `clio_token_store_db.load`.

**Confirmed causes and fixes:**

- **Client routes are not files.** `GET /` serves `frontend/dist/index.html`, but `/login`, `/billing`, `/matters`, etc. are React Router routes. A full navigation (refresh, or `frontend/src/api/client.js` sending the browser to `/login` on HTTP 401) asked the server for a file named `login`. `StaticFiles(html=True)` does not fall back to `index.html` for those paths, so FastAPI answered JSON 404. Fixed by `_SPAStaticFiles` in `backend/main.py` — real missing assets (paths with a `.` in the last segment) still 404.
- **Every 401 was treated as an app-session expiry.** `client.js` cleared the JWT and redirected to `/login` on any 401, including the Clio-authorization 401 raised by `get_clio_client`. Any Clio blip therefore looked like a login loop. Fixed by returning `{"error":"clio_auth","message":"..."}` (plus `WWW-Authenticate: Clio`) from `backend/dependencies.py` and having `client.js` surface that as a re-authorize message instead of logging the user out.
- **Azure SQL auto-pause.** After ~an hour idle, the first request needs 30–60 s to resume the database. Only `40613` was retried; `HYT00` (login timeout expired) and the token store's SELECT were not. `init_db()` under `gunicorn --preload` also killed the container if SQL was still paused when the master imported `backend.main`. Fixed by adding `HYT00` / `login timeout expired` to `_TRANSIENT_SQL_SIGNATURES`, setting pyodbc `timeout=30`, wrapping `DbTokenStore.load/save/exists` in `_retry_transient`, and letting `init_db()` defer instead of crash on a paused DB.
- **Worker fork inherited the master's DB sockets.** With `--preload`, the pool is created in the master and every uvicorn worker forks a copy of the same TCP connections to Azure SQL. Two processes cannot share one pyodbc connection, so the first per-worker query trips `08S01` broken pipe. Fixed by `gunicorn.conf.py` `post_fork` calling `get_engine().dispose(close=False)` — each worker opens fresh connections lazily.
- **Two deploy pipelines can 404 the first request.** VS Code "Deploy to Web App" sometimes records **OneDeploy** (Author N/A) and sometimes **ZipDeploy** (`ms-azuretools-vscode`). Oryx only pip-installs on the ZipDeploy path. The first boot can arrive before Oryx has produced `startup.sh` (`bash: startup.sh: No such file or directory`); a later restart succeeds. Wait until the log shows `Application startup complete` for all four workers before judging the deploy. Do not redeploy just because the first request 404'd during the Oryx build.
- **React is not built on the server.** Oryx's Node is too old for Vite 8, and there is no root `package.json` on purpose (a root one makes Oryx treat the app as Node). Build locally before every UI deploy: `cd frontend; npm run build`. `frontend/dist/` is gitignored and is included in the VS Code zip.

**Still true:**

- Gunicorn worker crash. A Clio refresh-token failure used to `KeyError: 'refresh_token'` and 500 every request. Mitigated: `ClioAuthError` → HTTP 401 and re-authorize at `/api/oauth/login`.
- Azure App Service recycle / multiple workers vs in-process threads.

**Do not** assume closing the browser cancelled a job. Check `GET /api/execute/jobs?active_only=true`. Rows stuck `running` after a deploy are **orphans**; `completed` tells you how much hit Clio. Revert that `batch_id` if needed.

## Gateway timeout (~230s)

Fixed for bulk preview/execute/revert and billing refresh by returning a `job_id` immediately and polling. Any new long Clio loop must use the same pattern.

## Cancel vs leave vs deploy

| User action | Server |
|---|---|
| Close tab / X progress | Job **keeps running** |
| Cancel button | Flag `cancel_requested`; worker stops; execute rolls back audit rows |
| Redeploy / process restart | Threads **die**; job row may stay `running` |

Rollback on cancel uses `audit_log` for that job id, not an in-memory counter.

## Local `.venv`

Native wheels (`pydantic_core`, `_cffi_backend`) have failed under OneDrive. Recreate the venv on a non-synced path before treating local import errors as application bugs.

## OAuth

App JWT expiry is 8 hours. Clio refresh tokens expire independently. Re-authorize Clio without redeploying if APIs return 401 with a Clio auth message.

## Deploy comment

Paste [[Unreleased]] bullets into the VS Code Azure deploy prompt. After success, move them to a dated file under `09_Changelog/`. Git commits can use the repo `.gitmessage` template (`git.commitTemplate`).
