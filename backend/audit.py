"""
Audit logging utilities (SQLAlchemy Core).

Every write operation the API performs lands here. In addition to the
historical who/what/when/before/after columns, each row now carries a
`batch_id` so the Revert feature can re-group every row that belonged to
one execute() call (single update or a whole CSV bulk run).

Usage:
    from backend.audit import write_audit_log, new_batch_id

    batch_id = new_batch_id()
    write_audit_log(
        db=db,
        batch_id=batch_id,
        username="admin",
        action="update_custom_field",
        matter_id="1830300500",
        field_name="Vehicle Year",
        before_value="2020",
        after_value="2025",
    )
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from backend.database import audit_log


# ── Helpers ─────────────────────────────────────────────────────────────────

def new_batch_id() -> str:
    """Generate a fresh uuid4 string for grouping an execute call's audit rows."""
    return str(uuid.uuid4())


def _as_text(value: Any) -> str | None:
    """Normalize any stringifiable value to its DB representation (or None)."""
    if value is None:
        return None
    return str(value)


# ── Writes ──────────────────────────────────────────────────────────────────

def write_audit_log(
    db: Connection,
    *,
    username: str,
    action: str,
    endpoint: str | None = None,
    matter_id: str | None = None,
    field_name: str | None = None,
    details: dict | None = None,
    before_value: Any = None,
    after_value: Any = None,
    status: str = "success",
    error_message: str | None = None,
    batch_id: str | None = None,
) -> int:
    """
    Write a single audit_log row and return its id.

    All parameters except username + action are optional. `details` is serialized
    to JSON. `batch_id` should be reused across every row that belongs to one
    execute() call so Revert can pull them back together.
    """
    stmt = audit_log.insert().values(
        timestamp=datetime.now(timezone.utc).isoformat(),
        username=username,
        action=action,
        endpoint=endpoint,
        matter_id=_as_text(matter_id),
        field_name=field_name,
        details=json.dumps(details, default=str) if details else None,
        before_value=_as_text(before_value),
        after_value=_as_text(after_value),
        status=status,
        error_message=error_message,
        batch_id=batch_id,
        reverted=False,
    )
    result = db.execute(stmt)
    return int(result.inserted_primary_key[0]) if result.inserted_primary_key else 0


def mark_rows_reverted(db: Connection, row_ids: list[int], reverted_by_batch_id: str) -> None:
    """
    Flip `reverted=True` and stamp `reverted_by_batch_id` on the given rows.
    Used by the revert endpoint after it succeeds on Clio.
    """
    if not row_ids:
        return
    stmt = (
        update(audit_log)
        .where(audit_log.c.id.in_(row_ids))
        .values(reverted=True, reverted_by_batch_id=reverted_by_batch_id)
    )
    db.execute(stmt)


# ── Reads ───────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Turn a SQLAlchemy Row into a plain dict (adds back-compat details)."""
    d = dict(row._mapping)
    # reverted is stored as 0/1 on SQLite -- normalize to Python bool so the
    # frontend and revert logic can use truthy checks.
    d["reverted"] = bool(d.get("reverted"))
    return d


def get_audit_logs(
    db: Connection,
    *,
    username: str | None = None,
    action: str | None = None,
    matter_id: str | None = None,
    since: str | None = None,
    batch_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Query audit_log with optional filters; newest first.

    New: `batch_id` filter (used by the revert endpoint and, optionally, by the
    Audit Log UI to show "all rows from this execute").
    """
    stmt = select(audit_log)
    conditions = []
    if username:
        conditions.append(audit_log.c.username == username)
    if action:
        conditions.append(audit_log.c.action == action)
    if matter_id:
        conditions.append(audit_log.c.matter_id == str(matter_id))
    if since:
        conditions.append(audit_log.c.timestamp >= since)
    if batch_id:
        conditions.append(audit_log.c.batch_id == batch_id)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(audit_log.c.timestamp.desc()).limit(limit).offset(offset)
    return [_row_to_dict(r) for r in db.execute(stmt).fetchall()]


def get_batch_rows_for_revert(db: Connection, batch_id: str) -> list[dict]:
    """
    Return every successful, un-reverted audit row for `batch_id`.

    Rows are returned in insertion order (by id ASC) so the revert preserves
    the same per-row ordering the original execute used.
    """
    stmt = (
        select(audit_log)
        .where(
            and_(
                audit_log.c.batch_id == batch_id,
                audit_log.c.status == "success",
                audit_log.c.reverted == False,  # noqa: E712 -- SQL bool compare
            )
        )
        .order_by(audit_log.c.id.asc())
    )
    return [_row_to_dict(r) for r in db.execute(stmt).fetchall()]
