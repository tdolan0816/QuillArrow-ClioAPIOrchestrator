"""
Audit log endpoints.

Endpoints:
    GET /api/audit                             -- query raw audit rows with optional filters
    GET /api/audit/batches                     -- one consolidated row per execute() batch
    GET /api/audit/batch/{batch_id}/download   -- CSV of every row in one batch
    GET /api/audit/download                    -- CSV of the entire audit log

CSV downloads are generated on demand straight from the database — nothing is
written to disk, so there are no stored files to rotate or expire.
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import Connection

from backend.auth import UserInfo
from backend.dependencies import require_auth
from backend.database import get_db
from backend.audit import get_audit_logs, get_batch_summaries

router = APIRouter(tags=["Audit Log"])

# Columns exported to CSV, in order. Mirrors the audit_log table minus the
# internal numeric PK-adjacent noise nobody needs in a spreadsheet.
_CSV_COLUMNS = [
    "timestamp", "username", "action", "endpoint", "matter_id", "field_name",
    "before_value", "after_value", "status", "error_message", "batch_id",
    "reverted", "reverted_by_batch_id", "details",
]


@router.get("/audit")
def api_get_audit_log(
    username: str | None = Query(default=None, description="Filter by username"),
    action: str | None = Query(default=None, description="Filter by action type (e.g., 'update_custom_field')"),
    matter_id: str | None = Query(default=None, description="Filter by matter ID"),
    since: str | None = Query(default=None, description="Only entries after this date (YYYY-MM-DD or ISO timestamp)"),
    batch_id: str | None = Query(default=None, description="Filter to one execute() batch (useful for revert / history)"),
    status: str | None = Query(default=None, description="Filter by row status: 'success' or 'error'"),
    limit: int = Query(default=50, ge=1, le=500, description="Max entries to return"),
    offset: int = Query(default=0, ge=0, description="Skip this many entries (for pagination)"),
    user: UserInfo = Depends(require_auth),
    db: Connection = Depends(get_db),
):
    """
    Query the audit log. Entries are returned newest-first. All filters combine with AND.

    Example queries:
        /api/audit                                   -- last 50 entries
        /api/audit?username=admin                    -- only admin's actions
        /api/audit?action=update_custom_field        -- only custom field updates
        /api/audit?matter_id=1830300500              -- everything that happened to this matter
        /api/audit?batch_id=<uuid>                   -- everything in one execute() / revert batch
        /api/audit?batch_id=<uuid>&status=error      -- only the FAILED rows of a batch
        /api/audit?since=2026-04-01&limit=100        -- last 100 entries since April 1st
    """
    entries = get_audit_logs(
        db,
        username=username,
        action=action,
        matter_id=matter_id,
        since=since,
        batch_id=batch_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"total_returned": len(entries), "data": entries}


@router.get("/audit/batches")
def api_get_audit_batches(
    limit: int = Query(default=50, ge=1, le=500, description="Max batches to return"),
    offset: int = Query(default=0, ge=0, description="Skip this many batches (for pagination)"),
    user: UserInfo = Depends(require_auth),
    db: Connection = Depends(get_db),
):
    """
    Consolidated audit view: one row per execute() batch, newest first.

    Each row: batch_id, timestamp (batch start), username, action, total_rows,
    success_rows, error_rows, status ('success' | 'partial' | 'failed'), and
    whether the batch has been reverted. Concurrent executes never mix — each
    keeps its own batch_id no matter how their raw rows interleave in time.
    """
    return {"data": get_batch_summaries(db, limit=limit, offset=offset)}


def _rows_to_csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    """Serialize audit rows to a CSV attachment (built in memory, on demand)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col) for col in _CSV_COLUMNS})
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit/batch/{batch_id}/download")
def api_download_batch_csv(
    batch_id: str,
    user: UserInfo = Depends(require_auth),
    db: Connection = Depends(get_db),
):
    """Download every audit row (successes AND failures) for one batch as CSV."""
    # High limit: a batch is one CSV upload, comfortably within a few thousand.
    rows = get_audit_logs(db, batch_id=batch_id, limit=100000)
    if not rows:
        raise HTTPException(status_code=404, detail="No audit rows for that batch id")
    # Oldest-first reads naturally in a spreadsheet (rows in execution order).
    rows.reverse()
    return _rows_to_csv_response(rows, f"audit_batch_{batch_id}.csv")


@router.get("/audit/download")
def api_download_full_audit_csv(
    since: str | None = Query(default=None, description="Optional YYYY-MM-DD lower bound"),
    user: UserInfo = Depends(require_auth),
    db: Connection = Depends(get_db),
):
    """Download the entire audit log (optionally since a date) as CSV."""
    rows = get_audit_logs(db, since=since, limit=1000000)
    rows.reverse()  # oldest first
    suffix = f"_since_{since}" if since else ""
    return _rows_to_csv_response(rows, f"audit_log_full{suffix}.csv")
