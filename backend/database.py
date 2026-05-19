"""
Database setup for the Clio API Orchestrator.

Now backed by SQLAlchemy Core. The connection URL comes from the DATABASE_URL
environment variable so the same code runs against:

    Local dev:        sqlite:///./orchestrator.db   (default)
    Azure SQL (prod): mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+18+for+SQL+Server

Tables that live here:

    audit_log       -- every write operation that the API performs
                       (batch_id + reverted flags power the Revert feature)
    clio_tokens     -- Clio OAuth tokens for each environment (dev / prod);
                       used by DbTokenStore when DATABASE_URL points at Azure SQL

Routes get a short-lived Connection via the `get_db` FastAPI dependency. We keep
using SQLAlchemy Core (not the ORM) to stay close to SQL, dialect-neutral, and
simple to reason about during audits.
"""

from __future__ import annotations

import os
import random
import struct
import time
from pathlib import Path
from typing import Callable, TypeVar

from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    Index,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine

from azure.identity import ManagedIdentityCredential, DefaultAzureCredential

_SQL_COPT_SS_ACCESS_TOKEN = 1256

# ── Azure SQL transient-error retry ─────────────────────────────────────────
# The Free Offer auto-pauses the database after idle time, so the first
# request after a pause commonly fails with 40613 ("database is currently
# unavailable") while Azure resumes it. The other codes here are the
# documented transient errors worth retrying.
# Reference: docs.microsoft.com/azure/azure-sql/database/troubleshoot-common-errors-issues
_TRANSIENT_SQL_CODES: frozenset[int] = frozenset(
    {
        4060,   # Cannot open database (often surfaces during auto-resume)
        10928,  # Resource ID limit reached
        10929,  # Resource governor: not enough resources
        40197,  # Service encountered an error processing the request
        40501,  # Service is currently busy
        40613,  # Database currently unavailable (auto-pause / resume)
        49918,  # Cannot process request, not enough resources
        49919,  # Cannot process create/update request, too many operations
        49920,  # Cannot process request, too many operations
    }
)

T = TypeVar("T")


def _is_transient_sql_error(exc: BaseException) -> bool:
    """Return True if the exception looks like a transient Azure SQL error."""
    msg = str(exc)
    for code in _TRANSIENT_SQL_CODES:
        # pyodbc surfaces the code as "(40613)" and SQLAlchemy wraps it the
        # same way in DBAPIError.__str__.
        if f"({code})" in msg:
            return True
    return False


def _is_object_exists_error(exc: BaseException) -> bool:
    """
    Return True for the benign "object already exists" race during init_db.

    Background: gunicorn boots N workers in parallel and each one calls
    ``init_db()`` during import. SQLAlchemy's ``checkfirst=True`` is *not*
    atomic across connections -- two workers can both SELECT-then-CREATE and
    the second one trips MSSQL error 2714 (SQLSTATE 42S01). Treat it as a
    success: whichever worker won the race created the table, the loser's
    work is just redundant.
    """
    msg = str(exc)
    return "(2714)" in msg or "42S01" in msg


def _retry_transient(
    operation: str,
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> T:
    """
    Run ``fn()`` and retry on transient Azure SQL errors.

    Uses exponential backoff with full jitter, capped at ``max_delay`` seconds.
    Non-transient exceptions propagate immediately.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not _is_transient_sql_error(exc) or attempt >= max_attempts:
                raise
            cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = random.uniform(0.0, cap)
            print(
                f"  [DB] Transient SQL error on {operation} "
                f"(attempt {attempt}/{max_attempts}): {exc}; "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)
    # Loop body either returns or raises; this is just to satisfy type checkers.
    raise RuntimeError(f"_retry_transient: exhausted retries for {operation}")

# ── Connection URL ──────────────────────────────────────────────────────────
# SQLite local file (default) keeps zero infra for dev. Azure Web App override
# by setting DATABASE_URL in App Settings.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE_PATH = _PROJECT_ROOT / "orchestrator.db"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{_DEFAULT_SQLITE_PATH.as_posix()}",
)


# ── Engine (connection pool) ────────────────────────────────────────────────
# SQLite needs check_same_thread=False because FastAPI hands connections to
# dependency functions that may run on different threads.
_connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False


def _make_engine(url: str) -> Engine:
    engine = create_engine(
        url,
        connect_args=_connect_args,
        future=True,
        pool_pre_ping=True,
    )

    if url.startswith("sqlite"):
        # Enable WAL once per process -- safe to re-run.
        with engine.begin() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))

    elif url.startswith("mssql+"):
        # On Azure SQL with Managed Identity, fetch the token in Python and
        # hand it to pyodbc directly. More reliable than relying on the ODBC
        # driver's Authentication=ActiveDirectoryMsi connection-string flow.
        # The credential is reused across connections so azure-identity can
        # cache tokens internally.
        credential = (
            ManagedIdentityCredential()
            if os.getenv("IDENTITY_ENDPOINT")
            else DefaultAzureCredential()
        )

        @event.listens_for(engine, "do_connect")
        def _inject_token(dialect, conn_rec, cargs, cparams):
            token = credential.get_token("https://database.windows.net/.default").token
            token_bytes = token.encode("utf-16-le")
            packed = struct.pack(
                f"<I{len(token_bytes)}s", len(token_bytes), token_bytes
            )
            cparams["attrs_before"] = {_SQL_COPT_SS_ACCESS_TOKEN: packed}

    return engine


_engine: Engine = _make_engine(DATABASE_URL)


# ── Schema (dialect-neutral types only) ─────────────────────────────────────
metadata = MetaData()

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Use String(32) for timestamp text so Azure SQL stays happy. ISO-8601
    # UTC strings keep sort-by-time working the same on both backends.
    Column("timestamp", String(40), nullable=False),
    Column("username", String(120), nullable=False),
    Column("action", String(80), nullable=False),
    Column("endpoint", String(200), nullable=True),
    Column("matter_id", String(40), nullable=True),
    Column("field_name", String(200), nullable=True),
    Column("details", Text, nullable=True),
    Column("before_value", Text, nullable=True),
    Column("after_value", Text, nullable=True),
    Column("status", String(16), nullable=False, default="success"),
    Column("error_message", Text, nullable=True),
    # Revert-feature columns (added in 2026-04). Nullable so rows that pre-date
    # the feature keep working, and backfill isn't required.
    Column("batch_id", String(36), nullable=True),
    Column("reverted", Boolean, nullable=False, default=False),
    Column("reverted_by_batch_id", String(36), nullable=True),
    Index("idx_audit_timestamp", "timestamp"),
    Index("idx_audit_username", "username"),
    Index("idx_audit_action", "action"),
    Index("idx_audit_matter_id", "matter_id"),
    Index("idx_audit_batch_id", "batch_id"),
)


# Single row per environment ('dev' / 'prod'). Used by DbTokenStore in Azure;
# local dev keeps using the JSON file via FileTokenStore. Token values are
# fairly small (~1 KB each) so Text is plenty.
clio_tokens = Table(
    "clio_tokens",
    metadata,
    Column("env", String(16), primary_key=True),
    Column("access_token", Text, nullable=False),
    Column("refresh_token", Text, nullable=False),
    Column("token_type", String(32), nullable=True),
    Column("expires_at", Integer, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", String(40), nullable=False),
)


# ── Public API used by routes / tests ───────────────────────────────────────

def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy Engine."""
    return _engine


def _open_connection_with_transaction():
    """Open a Connection + start a transaction, retrying on transient SQL errors."""
    def _open():
        conn = _engine.connect()
        trans = conn.begin()
        return conn, trans

    return _retry_transient("get_db.open", _open)


def get_db():
    """
    FastAPI dependency: yields a Core Connection with an open transaction.

    Usage:
        def my_route(db: Connection = Depends(get_db)):
            db.execute(audit_log.insert().values(...))

    The transaction commits automatically when the request ends successfully,
    or rolls back on an uncaught exception -- whichever happens first.

    Connection open is wrapped in transient-error retry so the Azure SQL
    auto-pause/resume window (40613, etc.) is invisible to callers when the
    database is available within the retry budget.
    """
    conn, trans = _open_connection_with_transaction()
    try:
        yield conn
    except Exception:
        trans.rollback()
        raise
    else:
        trans.commit()
    finally:
        conn.close()


def _ensure_new_audit_columns() -> None:
    """
    Light-weight migration for the SQLite dev file.

    When we added batch_id / reverted / reverted_by_batch_id, databases that
    already existed on disk needed the columns appended. SQLAlchemy's
    `metadata.create_all` only creates missing *tables*, not missing columns,
    so we do one ALTER TABLE per column when we detect them missing.

    Azure SQL / Azure DB for MSSQL will have the same columns ensured the
    first time the new code ships to that environment. The same ALTER TABLE
    pattern is valid T-SQL.
    """
    inspector = inspect(_engine)
    if "audit_log" not in inspector.get_table_names():
        return  # table not created yet; metadata.create_all handles it

    existing_cols = {col["name"] for col in inspector.get_columns("audit_log")}
    additions: list[str] = []
    if "batch_id" not in existing_cols:
        additions.append("ALTER TABLE audit_log ADD COLUMN batch_id VARCHAR(36)")
    if "reverted" not in existing_cols:
        # SQLite/MSSQL both accept a numeric default for BOOLEAN/BIT.
        additions.append("ALTER TABLE audit_log ADD COLUMN reverted INTEGER NOT NULL DEFAULT 0")
    if "reverted_by_batch_id" not in existing_cols:
        additions.append("ALTER TABLE audit_log ADD COLUMN reverted_by_batch_id VARCHAR(36)")

    if not additions:
        return

    with _engine.begin() as conn:
        for stmt in additions:
            conn.execute(text(stmt))
    print(f"  [DB] Applied {len(additions)} audit_log column migration(s).")


def _create_tables_idempotent() -> None:
    """
    Create each table individually, swallowing per-table 'already exists'
    races between parallel gunicorn workers. Unlike ``metadata.create_all``,
    a race on table A here does not abort the creation of tables B/C.
    """
    for table in metadata.sorted_tables:
        try:
            table.create(_engine, checkfirst=True)
        except Exception as exc:
            if _is_object_exists_error(exc):
                # Another worker created this one first -- that's fine.
                continue
            raise


def init_db() -> None:
    """Create tables + apply any lightweight column migrations.

    Both steps are wrapped in transient-error retry because app startup is
    the most likely time Azure SQL is in the middle of resuming from auto-pause.
    Table creation is also race-tolerant so cold starts with multiple gunicorn
    workers don't crash on the first deploy of a new database.
    """
    _retry_transient("init_db.create_all", _create_tables_idempotent)
    _retry_transient("init_db.migrate_columns", _ensure_new_audit_columns)
    print(f"  [DB] Audit database ready at {DATABASE_URL}")
