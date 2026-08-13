"""
Background job registry for long-running bulk operations.

Why this exists
---------------
Azure App Service puts a hard ~230-second timeout on its front-end gateway
that cannot be raised by any app setting or by the gunicorn timeout. A bulk
CSV execute (Matters / Tasks / Custom Fields) makes one Clio API round trip
per row, so anything past ~50 rows blows through that ceiling and the browser
gets a gateway error even though the backend is often still working.

The fix mirrors the billing "Refresh from Clio" pattern: the HTTP request only
starts the work, then returns immediately. The actual PATCH loop runs in a
background thread and records its progress in this DB-backed registry. The
browser polls ``GET /api/execute/jobs/{id}`` for live progress and the final
per-row results.

Why the state lives in the DB (not an in-process dict)
------------------------------------------------------
Gunicorn runs multiple workers. The worker that starts the job and the worker
that later serves a status poll are usually different processes, so an
in-memory dict would be invisible across them. A tiny ``bulk_jobs`` table is
visible to every worker and also survives the user closing their tab.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any, Callable

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    text,
)

from backend.database import get_engine, _retry_transient
from backend.audit import write_audit_log

_bulk_metadata = MetaData()

# Short-value cap so a stray long Clio error can never trip the "string would
# be truncated" error we hit on the activities cache.
_MESSAGE_MAX = 500

bulk_jobs = Table(
    "bulk_jobs",
    _bulk_metadata,
    Column("id", String(64), primary_key=True),          # == audit batch_id
    Column("job_type", String(32), nullable=False),      # matters | tasks | fields
    # running | ok | error | cancelled
    Column("state", String(16), nullable=False),
    # preparing | executing | reverting | done
    Column("phase", String(16), nullable=False),
    Column("username", String(128)),
    Column("total", Integer, nullable=False, default=0),
    Column("completed", Integer, nullable=False, default=0),
    Column("failed", Integer, nullable=False, default=0),
    Column("skipped", Integer, nullable=False, default=0),
    Column("message", String(_MESSAGE_MAX)),
    Column("prep_errors", Text),                          # JSON list[str]
    Column("results", Text),                              # JSON list[dict], set at finish
    Column("started_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    Column("finished_at", Integer),
    # Cooperative cancellation: the HTTP request sets this to 1 and the worker
    # thread notices on its next checkpoint and stops. A thread can't be killed
    # from outside safely, so the worker has to opt out on its own.
    Column("cancel_requested", Integer, nullable=False, default=0),
)

_table_ready = False
_table_lock = threading.Lock()

# Columns added after the table first shipped. Existing deployments already
# have a bulk_jobs table, so create(checkfirst=True) is a no-op for them and
# these have to be ALTERed in.
_ADDED_COLUMNS = {
    "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
}


def _is_object_exists_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "(2714)" in msg or "42s01" in msg or "already exists" in msg


def _is_duplicate_column_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "duplicate column" in msg          # SQLite
        or "(2705)" in msg                 # MSSQL: column name already exists
        or "already exists" in msg
    )


def _migrate_added_columns(engine) -> None:
    """ALTER IN any columns added after the table's first release."""
    from sqlalchemy import inspect

    try:
        existing = {c["name"] for c in inspect(engine).get_columns("bulk_jobs")}
    except Exception:  # noqa: BLE001 -- if we can't inspect, let the ALTERs try
        existing = set()

    for col, ddl in _ADDED_COLUMNS.items():
        if col in existing:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE bulk_jobs ADD {col} {ddl}"))
        except Exception as exc:  # noqa: BLE001 -- parallel workers race here
            if not _is_duplicate_column_error(exc):
                raise


def ensure_bulk_jobs_table() -> None:
    """Create the bulk_jobs table on first use (idempotent, worker-race safe)."""
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        engine = get_engine()
        try:
            bulk_jobs.create(engine, checkfirst=True)
        except Exception as exc:  # noqa: BLE001 -- tolerate parallel worker create
            if not _is_object_exists_error(exc):
                raise
        _migrate_added_columns(engine)
        _table_ready = True


def _now() -> int:
    return int(time.time())


def create_job(job_id: str, job_type: str, username: str, *, total: int = 0) -> None:
    """Insert a fresh job row in the ``running`` / ``preparing`` state."""
    ensure_bulk_jobs_table()
    now = _now()

    def _op():
        with get_engine().begin() as conn:
            conn.execute(
                bulk_jobs.insert().values(
                    id=job_id,
                    job_type=job_type,
                    state="running",
                    phase="preparing",
                    username=username,
                    total=total,
                    completed=0,
                    failed=0,
                    skipped=0,
                    message="Validating CSV…",
                    prep_errors=None,
                    results=None,
                    started_at=now,
                    updated_at=now,
                    finished_at=None,
                    cancel_requested=0,
                )
            )

    _retry_transient("bulk_job.create", _op)


# ── Cooperative cancellation ────────────────────────────────────────────────


class JobCancelled(Exception):
    """Raised inside a worker when the user has requested cancellation.

    Workers let this propagate out of their row loop; the caller catches it,
    finalizes the job as ``cancelled``, and (for execute jobs) reverts whatever
    was already applied.
    """


def request_cancel(job_id: str) -> bool:
    """Flag a running job for cancellation. Returns False if it isn't running."""
    ensure_bulk_jobs_table()

    def _op():
        with get_engine().begin() as conn:
            result = conn.execute(
                bulk_jobs.update()
                .where(bulk_jobs.c.id == job_id)
                .where(bulk_jobs.c.state == "running")
                .values(
                    cancel_requested=1,
                    message="Cancellation requested…",
                    updated_at=_now(),
                )
            )
            return result.rowcount > 0

    return bool(_retry_transient("bulk_job.request_cancel", _op))


def is_cancel_requested(job_id: str) -> bool:
    """Has cancellation been requested for this job?

    Called from worker checkpoints, so a transient DB hiccup must NOT abort the
    job -- on error we report False and the next checkpoint tries again.
    """
    try:
        def _op():
            with get_engine().connect() as conn:
                return conn.execute(
                    bulk_jobs.select()
                    .with_only_columns(bulk_jobs.c.cancel_requested)
                    .where(bulk_jobs.c.id == job_id)
                ).scalar()

        return bool(_retry_transient("bulk_job.is_cancelled", _op))
    except Exception:  # noqa: BLE001 -- never let a status read kill the job
        return False


def raise_if_cancelled(job_id: str) -> None:
    """Worker checkpoint: abort the row loop if the user asked to cancel."""
    if is_cancel_requested(job_id):
        raise JobCancelled()


def set_phase(job_id: str, phase: str, message: str | None = None) -> None:
    """Move a job to a new phase (e.g. 'reverting') without touching counters."""
    try:
        def _op():
            values: dict = {"phase": phase, "updated_at": _now()}
            if message is not None:
                values["message"] = message[:_MESSAGE_MAX]
            with get_engine().begin() as conn:
                conn.execute(
                    bulk_jobs.update().where(bulk_jobs.c.id == job_id).values(**values)
                )

        _retry_transient("bulk_job.set_phase", _op)
    except Exception:  # noqa: BLE001 -- phase label is cosmetic
        pass


def list_jobs(*, active_only: bool = False, limit: int = 25) -> list[dict]:
    """Recent jobs, newest first -- lets the UI find jobs it lost track of.

    A browser that closes mid-run has no record of its job id, but the job
    keeps going server-side; this is how it gets picked back up.
    """
    ensure_bulk_jobs_table()

    def _op():
        stmt = bulk_jobs.select()
        if active_only:
            stmt = stmt.where(bulk_jobs.c.state == "running")
        stmt = stmt.order_by(bulk_jobs.c.started_at.desc()).limit(limit)
        with get_engine().connect() as conn:
            return [dict(r) for r in conn.execute(stmt).mappings().all()]

    jobs = _retry_transient("bulk_job.list", _op)
    for job in jobs:
        job.pop("results", None)  # keep the listing light
        raw = job.get("prep_errors")
        if raw:
            try:
                job["prep_errors"] = json.loads(raw)
            except (ValueError, TypeError):
                job["prep_errors"] = []
        else:
            job["prep_errors"] = []
    return jobs


def set_phase_executing(job_id: str, total: int, prep_errors: list[str]) -> None:
    """Flip a job from preparing → executing once the CSV is validated."""
    def _op():
        with get_engine().begin() as conn:
            conn.execute(
                bulk_jobs.update()
                .where(bulk_jobs.c.id == job_id)
                .values(
                    phase="executing",
                    total=total,
                    prep_errors=json.dumps(prep_errors or []),
                    message=f"Processing 0 of {total}…",
                    updated_at=_now(),
                )
            )

    _retry_transient("bulk_job.set_executing", _op)


def record_row(
    job_id: str,
    *,
    audit: dict | None = None,
    completed: int = 0,
    failed: int = 0,
    skipped: int = 0,
) -> None:
    """Atomically record one processed row: its audit entry + counter bumps.

    The audit insert and the counter increment share a single transaction so
    progress can never drift from what's actually in the audit log. The whole
    thing is wrapped in transient-error retry, and opens a short-lived
    connection per row so a long job never holds a connection across Azure's
    idle-drop window.
    """
    def _op():
        with get_engine().begin() as conn:
            if audit is not None:
                write_audit_log(conn, **audit)
            conn.execute(
                bulk_jobs.update()
                .where(bulk_jobs.c.id == job_id)
                .values(
                    completed=bulk_jobs.c.completed + completed,
                    failed=bulk_jobs.c.failed + failed,
                    skipped=bulk_jobs.c.skipped + skipped,
                    updated_at=_now(),
                )
            )

    _retry_transient("bulk_job.record_row", _op)


def update_progress(
    job_id: str,
    *,
    processed: int,
    total: int | None = None,
    phase: str | None = None,
    message: str | None = None,
) -> None:
    """Set ABSOLUTE progress on a job (used by preview jobs).

    Unlike ``record_row`` (which increments counters as rows are PATCHed), the
    preview path knows exactly how many rows it has validated, so it sets the
    ``completed`` counter to an absolute value. Best-effort: a failed progress
    write is cosmetic and must never abort the preview.
    """
    try:
        def _op():
            values: dict = {"completed": processed, "updated_at": _now()}
            if total is not None:
                values["total"] = total
            if phase:
                values["phase"] = phase
            if message is not None:
                values["message"] = message[:_MESSAGE_MAX]
            with get_engine().begin() as conn:
                conn.execute(
                    bulk_jobs.update().where(bulk_jobs.c.id == job_id).values(**values)
                )

        _retry_transient("bulk_job.update_progress", _op)
    except Exception:  # noqa: BLE001 -- progress is cosmetic
        pass


def touch_message(job_id: str, message: str) -> None:
    """Update the human-readable progress message (best-effort, non-fatal)."""
    try:
        def _op():
            with get_engine().begin() as conn:
                conn.execute(
                    bulk_jobs.update()
                    .where(bulk_jobs.c.id == job_id)
                    .values(message=(message or "")[:_MESSAGE_MAX], updated_at=_now())
                )

        _retry_transient("bulk_job.touch", _op)
    except Exception:  # noqa: BLE001 -- progress text is cosmetic
        pass


def finish_job(
    job_id: str,
    *,
    state: str,
    message: str,
    results: list[dict] | None = None,
    prep_errors: list[str] | None = None,
) -> None:
    """Mark the job done (ok/error) and store its final results payload."""
    def _op():
        with get_engine().begin() as conn:
            values = {
                "state": state,
                "phase": "done",
                "message": (message or "")[:_MESSAGE_MAX],
                "results": json.dumps(results or [], default=str),
                "finished_at": _now(),
                "updated_at": _now(),
            }
            if prep_errors is not None:
                values["prep_errors"] = json.dumps(prep_errors)
            conn.execute(
                bulk_jobs.update().where(bulk_jobs.c.id == job_id).values(**values)
            )

    _retry_transient("bulk_job.finish", _op)


def get_job(job_id: str) -> dict | None:
    """Return the job row as a plain dict, with JSON columns decoded."""
    ensure_bulk_jobs_table()

    def _op():
        with get_engine().connect() as conn:
            row = conn.execute(
                bulk_jobs.select().where(bulk_jobs.c.id == job_id)
            ).mappings().first()
            return dict(row) if row else None

    job = _retry_transient("bulk_job.get", _op)
    if not job:
        return None
    for col in ("prep_errors", "results"):
        raw = job.get(col)
        if raw:
            try:
                job[col] = json.loads(raw)
            except (ValueError, TypeError):
                job[col] = []
        else:
            job[col] = []
    return job


def run_in_thread(job_id: str, worker: Callable[[], None], name: str = "bulk-job") -> None:
    """Spawn a daemon thread that runs ``worker`` and never lets it crash silently.

    ``worker`` owns its own success path (it should call ``finish_job``). This
    wrapper only guarantees that an unexpected crash still marks the job as
    errored instead of leaving it stuck on "running" forever.
    """
    def _runner():
        try:
            worker()
        except JobCancelled:
            # Safety net only -- workers normally handle their own cancellation
            # so they can revert first. Reaching here means one didn't.
            try:
                finish_job(job_id, state="cancelled", message="Job cancelled.")
            except Exception:  # noqa: BLE001 -- last-resort
                traceback.print_exc()
        except Exception as exc:  # noqa: BLE001 -- surface to UI via job state
            traceback.print_exc()
            try:
                finish_job(
                    job_id,
                    state="error",
                    message=f"Job crashed: {exc}",
                )
            except Exception:  # noqa: BLE001 -- last-resort; nothing else we can do
                traceback.print_exc()

    threading.Thread(target=_runner, name=name, daemon=True).start()
