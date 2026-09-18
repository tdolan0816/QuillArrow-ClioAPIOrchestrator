# Module / component catalog

**Audience:** engineers. Update this table when a module is added or its job changes. Deep pages exist only for high-risk pieces.

Wiki links go to pages in this folder. Code links are the git repo (one level up from `docs/`, then into the tree).

## Root / shared

| File | Responsibility | Major dependencies | Notes |
|---|---|---|---|
| [`clio_client.py`](../../clio_client.py) | Clio HTTP, pagination, token refresh | Clio API, token store | Deep: [[Clio_Client]] |
| [`operations.py`](../../operations.py) | Matter field maps, user resolve, CF lookup | Clio client | Used by prepare + some routes |
| [`config.py`](../../config.py) | Env / Clio app settings | process env | Secrets must not be committed |
| [`clio_tokens.py`](../../clio_tokens.py) | File vs DB token store interface | Azure SQL or JSON file | |

## Backend core

| File | Responsibility | Major dependencies | Notes |
|---|---|---|---|
| [`backend/main.py`](../../backend/main.py) | FastAPI app, CORS, routers, static SPA | all routers | [[Backend_FastAPI]] |
| [`backend/database.py`](../../backend/database.py) | Engine, retry, `audit_log`, `clio_tokens` | Azure SQL, SQLAlchemy | Deep: [[Database]] |
| [`backend/auth.py`](../../backend/auth.py) | JWT login, `USERS` dict | jose, passlib | [[Auth_OAuth]] — not Entra yet |
| [`backend/dependencies.py`](../../backend/dependencies.py) | `require_auth`, `get_clio_client` | auth, clio_client | Maps `ClioAuthError` to 401 |
| [`backend/audit.py`](../../backend/audit.py) | Write/query audit, batch summaries, revert helpers | `audit_log` | |
| [`backend/clio_token_store_db.py`](../../backend/clio_token_store_db.py) | Persist Clio tokens in SQL | `clio_tokens` | Production path |

## Backend routes

| File | Responsibility | Major dependencies | Notes |
|---|---|---|---|
| [`health.py`](../../backend/routes/health.py) | Liveness | none | |
| [`oauth.py`](../../backend/routes/oauth.py) | Clio OAuth login/callback/status | clio_client | [[Auth_OAuth]] |
| [`matters.py`](../../backend/routes/matters.py) | Matter search / get / CF names | Clio | |
| [`custom_fields.py`](../../backend/routes/custom_fields.py) | Custom field definitions | Clio | |
| [`document_templates.py`](../../backend/routes/document_templates.py) | List Clio document templates | Clio | |
| [`_prepare.py`](../../backend/routes/_prepare.py) | CSV validation, PATCH bodies, no writes | Clio, operations | Shared by preview + execute |
| [`preview.py`](../../backend/routes/preview.py) | Dry-run background jobs | `_prepare`, `_bulk_jobs` | [[Bulk_Jobs]] |
| [`execute.py`](../../backend/routes/execute.py) | PATCH Clio, jobs, cancel, revert | `_prepare`, audit | [[Bulk_Jobs]] |
| [`_bulk_jobs.py`](../../backend/routes/_bulk_jobs.py) | `bulk_jobs` table, threads, cancel flag | Azure SQL | Deep: [[Bulk_Jobs]] |
| [`templates.py`](../../backend/routes/templates.py) | Download CSV templates | operations field lists | |
| [`audit.py`](../../backend/routes/audit.py) | HTTP audit + batch CSV download | `backend/audit.py` | |
| [`billing.py`](../../backend/routes/billing.py) | Activity cache, refresh, pods, summary | Clio Groups, Azure SQL | Deep: [[Billing_Cache]] |

## Frontend

| File | Responsibility | Major dependencies | Notes |
|---|---|---|---|
| [`main.jsx`](../../frontend/src/main.jsx) / [`App.jsx`](../../frontend/src/App.jsx) | Router, pages | react-router | [[Frontend_React]] |
| [`client.js`](../../frontend/src/api/client.js) | `get` / `post` / `postForm` / download | JWT | |
| [`AuthContext.jsx`](../../frontend/src/context/AuthContext.jsx) | Login state | `/api/auth` | |
| [`Layout.jsx`](../../frontend/src/components/Layout.jsx) | Shell / nav | | |
| [`LoginPage.jsx`](../../frontend/src/pages/LoginPage.jsx) | App login | | |
| [`DashboardPage.jsx`](../../frontend/src/pages/DashboardPage.jsx) | Home | | |
| [`BulkOperationsPage.jsx`](../../frontend/src/pages/BulkOperationsPage.jsx) | All bulk CSV + single field | job polling, cancel | Deep page |
| [`BillingDashboardPage.jsx`](../../frontend/src/pages/BillingDashboardPage.jsx) | KPIs, pods, refresh | `/api/billing` | |
| [`AuditLogPage.jsx`](../../frontend/src/pages/AuditLogPage.jsx) | Batch audit + CSV | `/api/audit/batches` | |
| [`MattersPage.jsx`](../../frontend/src/pages/MattersPage.jsx) | Matter explorer | | |
| [`CustomFieldsPage.jsx`](../../frontend/src/pages/CustomFieldsPage.jsx) | Field explorer | | |

## Deep pages

- [[Clio_Client]]
- [[Database]]
- [[Bulk_Jobs]]
- [[Billing_Cache]]
- [[Auth_OAuth]]
- [[Backend_FastAPI]]
- [[Frontend_React]]
- [[BulkOperationsPage]]
