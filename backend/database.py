"""
Database setup for the Clio API Orchestrator.

Now backed by SQLAlchemy Core. The connection URL comes from the DATABASE_URL
environment variable so the same code runs against:

    Local dev:        sqlite:///./orchestrator.db   (default)
    Azure SQL (prod): mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+18+for+SQL+Server

Only two tables live here right now:

    audit_log       -- every write operation that the API performs
                       (batch_id + reverted flags power the Revert feature)

Routes get a short-lived Connection via the `get_db` FastAPI dependency. We keep
using SQLAlchemy Core (not the ORM) to stay close to SQL, dialect-neutral, and
simple to reason about during audits.
"""

from __future__ import annotations

import os
from pathlib import Path

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
    inspect,
    text,
)
from sqlalchemy.engine import Engine


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
# dependency functions that may run on different threads. WAL mode gives us
# concurrent readers during long-running bulk operations.
_connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

_engine: Engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    future=True,
    pool_pre_ping=True,
)

if DATABASE_URL.startswith("sqlite"):
    # Enable WAL once per process -- safe to re-run.
    with _engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))


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


# ── Public API used by routes / tests ───────────────────────────────────────

def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy Engine."""
    return _engine


def get_db():
    """
    FastAPI dependency: yields a Core Connection with an open transaction.

    Usage:
        def my_route(db: Connection = Depends(get_db)):
            db.execute(audit_log.insert().values(...))

    The transaction commits automatically when the request ends successfully,
    or rolls back on an uncaught exception -- whichever happens first.
    """
    with _engine.begin() as conn:
        yield conn


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


def init_db() -> None:
    """Create tables + apply any lightweight column migrations."""
    metadata.create_all(_engine)
    _ensure_new_audit_columns()
    print(f"  [DB] Audit database ready at {DATABASE_URL}")
