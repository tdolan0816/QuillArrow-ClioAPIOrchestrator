# How we document

This vault (`docs/` in git) is the system of record. Open **this folder** in Obsidian as the vault, not the whole repo.

The old notes under `Misc_Docs/` are an archive. Do not copy them in wholesale.

## Cadence

| Event | What to update |
|---|---|
| Architecture change (new container, new external system) | [[System_Context]], [[Container_Diagram]] |
| New or changed module | [[Catalog]] — deep page only if it is high-risk (jobs, tokens, billing cache, bulk UI) |
| Major design choice | New ADR in `05_ADRs/` from `_templates/adr.md` |
| Endpoint / payload / job contract | [[Endpoints]] |
| Table, column, index | [[Data_Dictionary]] |
| Ship to Azure | Fill VS Code deploy comment from [[Unreleased]], then date a changelog file |
| New production failure mode | [[Reliability]] and [[THREAD_HANDOFF]] |

## What not to write

- Chat transcripts
- Per-function dumps of large files
- A second copy of FastAPI Swagger (`/docs` on the running app)
- A "code review" folder until we use GitHub pull requests

## Diagrams

Use Mermaid in markdown. Lucid/Visio is optional for a slide deck and will go stale; it is not official.

## Cursor

Rules in `.cursor/rules/` tell the agent the same conventions. New coding threads start from [[THREAD_HANDOFF]], not a long prior chat.
