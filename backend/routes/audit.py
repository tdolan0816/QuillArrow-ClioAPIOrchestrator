"""
Audit log endpoints.

Endpoints:
    GET /api/audit  — query the audit log with optional filters
"""

import sqlite3
from fastapi import APIRouter, Depends, Query

from backend.auth import UserInfo
from backend.dependencies import require_auth
from backend.database import get_db
from backend.audit import get_audit_logs

router = APIRouter(tags=["Audit Log"])


@router.get("/audit")
def api_get_audit_log(
    username: str | None = Query(default=None, description="Filter by username"),
    action: str | None = Query(default=None, description="Filter by action type (e.g., 'update_custom_field')"),
    matter_id: str | None = Query(default=None, description="Filter by matter ID"),
    since: str | None = Query(default=None, description="Only entries after this date (YYYY-MM-DD or ISO timestamp)"),
    limit: int = Query(default=50, ge=1, le=500, description="Max entries to return"),
    offset: int = Query(default=0, ge=0, description="Skip this many entries (for pagination)"),
    user: UserInfo = Depends(require_auth),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Query the audit log.

    Returns entries newest-first. All filters are optional and combine with AND logic.

    Example queries:
        /api/audit                              — last 50 entries
        /api/audit?username=admin               — only admin's actions
        /api/audit?action=update_custom_field   — only custom field updates
        /api/audit?matter_id=1830300500         — everything that happened to this matter
        /api/audit?since=2026-04-01&limit=100   — last 100 entries since April 1st
    """
    entries = get_audit_logs(
        db,
        username=username,
        action=action,
        matter_id=matter_id,
        since=since,
        limit=limit,
        offset=offset,
    )
    return {"total_returned": len(entries), "data": entries}
