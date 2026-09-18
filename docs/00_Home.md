# Home

QuillArrow **Clio API Orchestrator** — a firm-internal web app for auditable bulk updates in Clio Manage and a Billings & Activities dashboard.

## C4 zoom

1. **Context** (stakeholders) — [[System_Context]]
2. **Containers** (new engineers) — [[Container_Diagram]]
3. **Components** (engineers) — [[Catalog]], plus deep pages for jobs, billing cache, Clio client, auth
4. **Code / workflows** (engineers) — sequence diagrams in `04_Workflows/`, not class catalogs

## Artifacts

| Artifact | Location |
|---|---|
| Architecture | Context + containers |
| Module catalog | [[Catalog]] |
| ADRs | `05_ADRs/` |
| API | [[Endpoints]] (live schema: FastAPI `/docs`) |
| Data | [[Data_Dictionary]] |
| Operations | [[Reliability]], [[How_We_Document]] |
| Releases | [[Unreleased]] |
| Next Cursor chat | [[THREAD_HANDOFF]] |

## How this maps to SDLC

C4 is how we **zoom**. ADRs, API, data dictionary, and changelog are how we **record change**. We do not keep a diary `DEVELOPMENT_LOG.md`; current state is these pages, history is ADRs + changelog.

## Start here if you are new

1. [[System_Context]]
2. [[Container_Diagram]]
3. [[Catalog]]
4. [[Reliability]] — known production issues before you deploy
