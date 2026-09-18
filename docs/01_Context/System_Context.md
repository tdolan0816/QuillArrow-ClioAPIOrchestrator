# System context

**Audience:** non-technical stakeholders.

The Orchestrator is a **Quill & Arrow internal** web application. Attorneys and operations staff log in, upload CSVs or use the billing dashboard, and the app talks to **Clio Manage** on their behalf. Every bulk write is audited so a batch can be reviewed or reverted.

It does **not** replace Clio. It is a controlled, logged way to change many records and to chart activity without hammering Clio on every dashboard click.

```mermaid
C4Context
  title Clio API Orchestrator — system context
  Person(staff, "Firm staff", "Attorneys, ops, admins")
  System(orch, "Clio API Orchestrator", "Bulk updates, audit/revert, billings dashboard")
  System_Ext(clio, "Clio Manage", "Matters, tasks, custom fields, activities, groups")
  System_Ext(azure, "Azure", "App Service host + SQL Database")
  Rel(staff, orch, "Uses in the browser")
  Rel(orch, clio, "OAuth + REST v4")
  Rel(orch, azure, "Runs on / stores cache and audit")
```

If Mermaid C4 is unavailable in a viewer, the same picture:

```mermaid
flowchart LR
  staff[Firm staff]
  orch[Clio API Orchestrator]
  clio[Clio Manage API]
  sql[Azure SQL]
  staff -->|HTTPS| orch
  orch -->|OAuth REST v4| clio
  orch -->|audit jobs activities tokens| sql
```

## People

- **Staff** — log in with the app’s own accounts today (not Microsoft Entra yet). Use Bulk Operations, Audit Log, Billings dashboard.
- **You (operator)** — deploy from VS Code, re-authorize Clio OAuth, watch jobs.

## External systems

| System | Role |
|---|---|
| Clio Manage | Source of truth for matters, tasks, custom fields, users/groups, time/expense activities |
| Azure App Service | Hosts the Python API and the built React SPA |
| Azure SQL | Audit log, Clio token row, activity cache, bulk job progress |

## Out of scope (today)

Microsoft Entra SSO and network IP allowlisting are planned, not implemented. See [[THREAD_HANDOFF]].
