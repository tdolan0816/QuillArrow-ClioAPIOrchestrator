# Data dictionary

Schema as defined in SQLAlchemy (source of truth for what the app creates/migrates). Production is Azure SQL. Some environments historically used SQLite for audit.

`bulk_jobs` and billing tables are created on first use as well as at startup depending on path.

## `audit_log`

**Why:** one row per attempted change (and revert). Enables batch UI, failure tables, and reverse PATCH.

Defined in [`backend/database.py`](../../backend/database.py).

| Column | Type | Notes |
|---|---|---|
| id | Integer PK identity | |
| timestamp | String(40) | ISO-8601 UTC |
| username | String(120) | App user |
| action | String(80) | e.g. `bulk_update_custom_field`, `revert_bulk_update_task` |
| endpoint | String(200) | |
| matter_id | String(40) | Nullable |
| field_name | String(200) | |
| details | Text | JSON extras (task_id, etc.) |
| before_value | Text | |
| after_value | Text | |
| status | String(16) | `success` / `error` |
| error_message | Text | |
| batch_id | String(36) | Execute job id |
| reverted | Boolean | Default false |
| reverted_by_batch_id | String(36) | |

Indexes: timestamp, username, action, matter_id, batch_id.

## `clio_tokens`

**Why:** persist Clio OAuth so workers share one firm connection.

| Column | Type | Notes |
|---|---|---|
| env | String(16) PK | `dev` / `prod` |
| access_token | Text | Secret |
| refresh_token | Text | Secret |
| token_type | String(32) | |
| expires_at | Integer | Unix |
| created_at | Integer | Unix |
| updated_at | String(40) | |

## `bulk_jobs`

**Why:** progress visible across gunicorn workers; survives closing the browser. See [[ADR-003-db-backed-job-registry]].

Defined in [`backend/routes/_bulk_jobs.py`](../../backend/routes/_bulk_jobs.py). Column `cancel_requested` is ALTERed in if the table already existed.

| Column | Type | Notes |
|---|---|---|
| id | String(64) PK | Job / batch id |
| job_type | String(32) | `fields`, `matters`, `tasks`, `task-update`, `*-preview`, `revert` |
| state | String(16) | `running` `ok` `error` `cancelled` |
| phase | String(16) | `preparing` `executing` `reverting` `done` |
| username | String(128) | |
| total, completed, failed, skipped | Integer | |
| message | String(500) | Truncated on purpose |
| prep_errors | Text | JSON list |
| results | Text | JSON list |
| started_at, updated_at, finished_at | Integer | Unix; finished nullable |
| cancel_requested | Integer | 0/1 |

## `activities_cache`

**Why:** dashboard KPIs without live Clio. Clio activity ids are BigInteger. [[ADR-001-azure-sql-activity-cache]]

[`backend/routes/billing.py`](../../backend/routes/billing.py)

| Column | Type | Notes |
|---|---|---|
| id | BigInteger PK | Clio activity id |
| type | String(32) | TimeEntry / ExpenseEntry |
| date | String(16) | |
| quantity | Float | |
| note | Text | |
| price | Float | Rate; **not** the dashboard dollar total |
| total | Float | Billable amount |
| non_billable_total | Float | |
| flat_rate | Integer | |
| billed | Integer | |
| user_id | BigInteger | |
| user_name | String(200) | |
| matter_id | BigInteger | |
| matter_display_number | String(200) | |
| matter_description | Text | |
| activity_category | String(450) | Indexed; length cap for SQL Server |
| expense_category | String(450) | Indexed |
| created_at, updated_at | String(40) | From Clio |
| cached_at | BigInteger | Unix |

Indexes: date; date+type; user_name+date; activity_category; expense_category.

## `billing_cache_meta`

**Why:** last refresh watermark / status strings.

| Column | Type | Notes |
|---|---|---|
| meta_key | String(40) PK | |
| meta_value | String(80) | |

When you add a column, migrate in code (ALTER on first run) and update this page in the same commit.
