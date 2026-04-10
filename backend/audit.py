"""
Audit logging utilities.

Provides a simple write_audit_log() function that any route or operation
can call to record who did what, when, and what changed.

The audit log captures:
    - username:      who performed the action
    - action:        what they did (e.g., "update_custom_field", "bulk_update_matters")
    - endpoint:      the API endpoint that was called
    - matter_id:     which matter was affected (if applicable)
    - field_name:    which field was changed (if applicable)
    - details:       free-form JSON with additional context
    - before_value:  the value before the change
    - after_value:   the value after the change
    - status:        "success" or "error"
    - error_message: error details if status is "error"

Usage:
    from backend.audit import write_audit_log

    write_audit_log(
        db=db,
        username="admin",
        action="update_custom_field",
        matter_id="1830300500",
        field_name="Vehicle Year",
        before_value="2020",
        after_value="2025",
    )
"""

import json
import sqlite3
from datetime import datetime, timezone


def write_audit_log(
    db: sqlite3.Connection,
    username: str,
    action: str,
    endpoint: str = None,
    matter_id: str = None,
    field_name: str = None,
    details: dict = None,
    before_value: str = None,
    after_value: str = None,
    status: str = "success",
    error_message: str = None,
):
    """
    Write a single entry to the audit_log table.

    All parameters except username and action are optional.
    The details dict is serialized to JSON for storage.
    """
    db.execute(
        """
        INSERT INTO audit_log
            (timestamp, username, action, endpoint, matter_id, field_name,
             details, before_value, after_value, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            username,
            action,
            endpoint,
            str(matter_id) if matter_id else None,
            field_name,
            json.dumps(details, default=str) if details else None,
            str(before_value) if before_value is not None else None,
            str(after_value) if after_value is not None else None,
            status,
            error_message,
        ),
    )
    db.commit()


def get_audit_logs(
    db: sqlite3.Connection,
    username: str = None,
    action: str = None,
    matter_id: str = None,
    since: str = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Query audit log entries with optional filters.

    Parameters:
        username:  filter by who performed the action
        action:    filter by action type (e.g., "update_custom_field")
        matter_id: filter by matter
        since:     only entries after this ISO timestamp (e.g., "2026-04-01")
        limit:     max entries to return (default 50)
        offset:    skip this many entries (for pagination)

    Returns a list of dicts, newest first.
    """
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []

    if username:
        query += " AND username = ?"
        params.append(username)
    if action:
        query += " AND action = ?"
        params.append(action)
    if matter_id:
        query += " AND matter_id = ?"
        params.append(str(matter_id))
    if since:
        query += " AND timestamp >= ?"
        params.append(since)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]
