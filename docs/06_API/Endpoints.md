# API endpoints

Live request/response schemas: FastAPI Swagger at `/docs` on the running app (e.g. `https://<app>/docs`). This page is the **catalog** (auth, jobs, Clio side effects).

Unless noted, routes require `Authorization: Bearer <app JWT>`. `GET /api/health` does not.

Long-running POSTs return **immediately** with `{ "status": "started"|"accepted", "job_id": ... }` (HTTP 200). Poll `GET /api/execute/jobs/{job_id}` until `state` is `ok`, `error`, or `cancelled`. Billing refresh has its own status URL.

## Health and app auth

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | No DB. Status + Clio env label |
| POST | `/api/auth/login` | Form username/password → JWT |
| GET | `/api/auth/me` | Current app user |

## Clio OAuth

| Method | Path | Notes |
|---|---|---|
| GET | `/api/oauth/status` | Whether Clio tokens exist / look valid |
| GET | `/api/oauth/login` | Redirect to Clio |
| GET | `/api/oauth/callback` | Stores tokens |

## Matters, custom fields, templates (read)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/matters` | List/page matters |
| GET | `/api/matters/search` | Search |
| GET | `/api/matters/custom-field-names` | Names for UI |
| GET | `/api/matters/{matter_id}` | One matter |
| GET | `/api/custom-fields` | Definitions |
| GET | `/api/custom-fields/search` | Search |
| GET | `/api/custom-fields/{field_id}` | One definition |
| GET | `/api/document-templates` | Clio document templates |
| GET | `/api/templates/bulk-update-fields.csv` | CSV template |
| GET | `/api/templates/bulk-update-matters.csv` | |
| GET | `/api/templates/bulk-reassign-tasks.csv` | |
| GET | `/api/templates/bulk-update-tasks.csv` | |

## Preview (no Clio PATCH)

| Method | Path | Job? |
|---|---|---|
| POST | `/api/preview/update-field` | Sync JSON |
| POST | `/api/preview/bulk-update-fields` | Job `fields-preview` |
| POST | `/api/preview/bulk-update-matters` | Job `matters-preview` |
| POST | `/api/preview/bulk-reassign-tasks` | Job `tasks-preview`; form `status_override` |
| POST | `/api/preview/bulk-update-tasks` | Job `task-update-preview` |

## Execute (writes Clio + audit)

| Method | Path | Job? |
|---|---|---|
| POST | `/api/execute/update-field` | Sync single PATCH |
| POST | `/api/execute/bulk-update-fields` | Job `fields` |
| POST | `/api/execute/bulk-update-matters` | Job `matters` |
| POST | `/api/execute/bulk-reassign-tasks` | Job `tasks`; `status_override`, `approved_task_ids` |
| POST | `/api/execute/bulk-update-tasks` | Job `task-update` |
| GET | `/api/execute/jobs` | List recent; `active_only`, `limit` |
| GET | `/api/execute/jobs/{job_id}` | Progress + results |
| POST | `/api/execute/jobs/{job_id}/cancel` | Sets flag; 409 if not running |
| POST | `/api/execute/revert/{batch_id}` | Job `revert`; undoes successful un-reverted rows |

## Billing

| Method | Path | Notes |
|---|---|---|
| GET | `/api/billing/pods` | Clio Groups |
| GET | `/api/billing/employees` | Optional `group_id` → pod members |
| POST | `/api/billing/refresh` | Background month reconcile |
| GET | `/api/billing/refresh/status` | Poll |
| GET | `/api/billing/activities` | Cached, filtered list |
| GET | `/api/billing/summary` | KPIs / charts |

## Audit

| Method | Path | Notes |
|---|---|---|
| GET | `/api/audit` | Filters: username, action, batch_id, **status**, limit |
| GET | `/api/audit/batches` | One row per batch |
| GET | `/api/audit/batch/{batch_id}/download` | CSV |
| GET | `/api/audit/download` | Full CSV |

Routers: [`backend/main.py`](../../backend/main.py). Job payload shape: [[Bulk_Jobs]].
