# Reliability and operations

Known failure modes as of `f0570a7`. Update this page when a cause is confirmed or a fix ships.

## Black screen / must redeploy

**Symptom:** Browser shows a blank page; sometimes 502/500. Workaround has been redeploying from VS Code, occasionally twice.

**Likely contributors (not all proven):**

- Gunicorn worker crash. A Clio refresh-token failure used to `KeyError: 'refresh_token'` and 500 every request. Mitigated: `ClioAuthError` → HTTP 401 and re-authorize at `/api/oauth/login`. If the UI does not handle 401, it can still look “dead.”
- Azure App Service recycle / multiple workers vs in-process threads.
- Azure SQL auto-pause: connections retry via `_retry_transient`; a long pause can still fail the first request.
- Serving `frontend/dist`: if a deploy uploads backend without a fresh `npm run build`, the SPA can be stale or missing.

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
