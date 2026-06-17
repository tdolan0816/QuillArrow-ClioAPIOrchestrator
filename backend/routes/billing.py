"""
Billing / Activities endpoints for the dashboard.

Clio's "Activities" are the firm's billing records (TimeEntry + ExpenseEntry).
Since Quill & Arrow doesn't bill clients directly (opposing counsel pays),
everything lives in Activities rather than Clio's Billing module.

Endpoints:
    GET /api/billing/activities  — paginated list with filters
    GET /api/billing/summary     — aggregated KPI data for the dashboard
    POST /api/billing/refresh    — force re-fetch from Clio into cache
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import get_clio_client, require_auth
from backend.database import get_db, get_engine

router = APIRouter(tags=["Billing & Activities"])

# Fields we request from Clio's /activities endpoint
_ACTIVITY_FIELDS = (
    "id,type,date,quantity,note,price,total,flat_rate,billed,"
    "created_at,updated_at,"
    "user{id,name},"
    "matter{id,display_number,description},"
    "activity_description{id,name},"
    "expense_category{id,name}"
)


def _ensure_cache_table():
    """Create the activities_cache table if it doesn't exist (SQLite + MSSQL safe)."""
    engine = get_engine()
    create_sql = text("""
        CREATE TABLE IF NOT EXISTS activities_cache (
            id INTEGER PRIMARY KEY,
            type VARCHAR(32),
            date VARCHAR(16),
            quantity REAL,
            note TEXT,
            price REAL,
            total REAL,
            flat_rate INTEGER,
            billed INTEGER,
            user_id INTEGER,
            user_name VARCHAR(200),
            matter_id INTEGER,
            matter_display_number VARCHAR(60),
            matter_description VARCHAR(400),
            activity_category VARCHAR(200),
            expense_category VARCHAR(200),
            created_at VARCHAR(40),
            updated_at VARCHAR(40),
            cached_at INTEGER NOT NULL
        )
    """)
    # Refresh bookkeeping lives outside the data rows so an empty cache
    # (e.g. all activities deleted in Clio) still remembers when it was
    # last synced and doesn't re-hit Clio on every page load.
    create_meta_sql = text("""
        CREATE TABLE IF NOT EXISTS billing_cache_meta (
            meta_key VARCHAR(40) PRIMARY KEY,
            meta_value VARCHAR(80) NOT NULL
        )
    """)
    try:
        with engine.begin() as conn:
            conn.execute(create_sql)
            conn.execute(create_meta_sql)
    except Exception:
        pass


def _parse_activity(record: dict, now_epoch: int) -> dict:
    """Flatten a Clio activity record into a cache-friendly dict."""
    user = record.get("user") or {}
    matter = record.get("matter") or {}
    act_desc = record.get("activity_description") or {}
    exp_cat = record.get("expense_category") or {}

    # Clio returns quantity in seconds for TimeEntry; convert to hours.
    raw_qty = record.get("quantity")
    if raw_qty and record.get("type") == "TimeEntry":
        raw_qty = raw_qty / 3600.0

    return {
        "id": record.get("id"),
        "type": record.get("type"),
        "date": record.get("date"),
        "quantity": raw_qty,
        "note": record.get("note"),
        "price": record.get("price"),
        "total": record.get("total"),
        "flat_rate": 1 if record.get("flat_rate") else 0,
        "billed": 1 if record.get("billed") else 0,
        "user_id": user.get("id"),
        "user_name": user.get("name"),
        "matter_id": matter.get("id"),
        "matter_display_number": matter.get("display_number"),
        "matter_description": matter.get("description"),
        "activity_category": act_desc.get("name"),
        "expense_category": exp_cat.get("name"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "cached_at": now_epoch,
    }


def _refresh_cache(client: ClioClient, *, date_from: str | None = None):
    """Pull activities from Clio and rebuild the cache table to mirror them.

    The cache is a full mirror of the fetched window: rows deleted in Clio
    disappear here too (including the everything-deleted case, where the
    fetch returns 0 records and the cache is emptied). The fetch completes
    BEFORE the transaction starts, so a mid-fetch failure (timeout, 4xx)
    leaves the existing cache untouched.
    """
    _ensure_cache_table()
    engine = get_engine()
    now_epoch = int(time.time())

    params: dict = {}
    if date_from:
        # Clio's created_since requires a full ISO-8601 datetime ("xmlschema
        # format"); a bare YYYY-MM-DD date is rejected with a 422.
        params["created_since"] = f"{date_from}T00:00:00Z"

    records = []
    for record in client.get_all("/activities", fields=_ACTIVITY_FIELDS, **params):
        records.append(_parse_activity(record, now_epoch))

    with engine.begin() as conn:
        # Mirror semantics: wipe and rebuild so Clio-side deletions propagate.
        conn.execute(text("DELETE FROM activities_cache"))

        for r in records:
            conn.execute(
                text("""
                    INSERT INTO activities_cache
                        (id, type, date, quantity, note, price, total, flat_rate, billed,
                         user_id, user_name, matter_id, matter_display_number,
                         matter_description, activity_category, expense_category,
                         created_at, updated_at, cached_at)
                    VALUES
                        (:id, :type, :date, :quantity, :note, :price, :total, :flat_rate, :billed,
                         :user_id, :user_name, :matter_id, :matter_display_number,
                         :matter_description, :activity_category, :expense_category,
                         :created_at, :updated_at, :cached_at)
                """),
                r,
            )

        # Record the sync time even when 0 records came back.
        conn.execute(text("DELETE FROM billing_cache_meta WHERE meta_key = 'last_refresh_epoch'"))
        conn.execute(
            text("INSERT INTO billing_cache_meta (meta_key, meta_value) VALUES ('last_refresh_epoch', :v)"),
            {"v": str(now_epoch)},
        )

    return len(records)


def _cache_age_seconds() -> int | None:
    """Return seconds since the last successful refresh, or None if never synced."""
    engine = get_engine()
    _ensure_cache_table()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT meta_value FROM billing_cache_meta WHERE meta_key = 'last_refresh_epoch'")
        ).scalar()
        if row is None:
            # Fall back to data rows for caches written before the meta table existed.
            row = conn.execute(text("SELECT MAX(cached_at) FROM activities_cache")).scalar()
    if row is None:
        return None
    return int(time.time()) - int(row)


def _auto_refresh_if_stale(client: ClioClient) -> str | None:
    """Refresh the cache if empty/older than 1 hour.

    Returns an error string instead of raising, so GET endpoints can still
    serve whatever cached data exists when Clio is unreachable or rejects
    the request.
    """
    age = _cache_age_seconds()
    if age is not None and age <= 3600:
        return None
    date_cutoff = (date.today() - timedelta(days=90)).isoformat()
    try:
        _refresh_cache(client, date_from=date_cutoff)
        return None
    except Exception as exc:  # noqa: BLE001 -- degrade to cached data
        return str(exc)


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/billing/refresh")
def refresh_activities(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    days_back: int = Query(default=90, description="How many days of history to pull"),
):
    """Force a refresh of the activities cache from Clio."""
    date_from = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        count = _refresh_cache(client, date_from=date_from)
    except Exception as exc:
        # Surface the Clio error as a structured JSON 502 instead of a bare
        # 500 so the UI can show something meaningful.
        raise HTTPException(
            status_code=502,
            detail=f"Clio refresh failed: {exc}",
        ) from exc
    return {"refreshed": count, "days_back": days_back}


@router.get("/billing/activities")
def list_activities(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    type: Optional[str] = Query(default=None, description="TimeEntry or ExpenseEntry"),
    user_name: Optional[str] = Query(default=None, description="Filter by user name (contains)"),
    matter_query: Optional[str] = Query(default=None, description="Filter by matter number or description"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD start"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD end"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    auto_refresh: bool = Query(default=True, description="Auto-refresh if cache is stale (>1 hr)"),
):
    """Return cached activities with optional filters.

    If the cache is empty or older than 1 hour and auto_refresh=True,
    triggers a background refresh from Clio first.
    """
    _ensure_cache_table()

    refresh_error = _auto_refresh_if_stale(client) if auto_refresh else None

    # Build query
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if type:
        conditions.append("type = :type")
        params["type"] = type
    if user_name:
        conditions.append("user_name LIKE :user_name")
        params["user_name"] = f"%{user_name}%"
    if matter_query:
        conditions.append("(matter_display_number LIKE :mq OR matter_description LIKE :mq)")
        params["mq"] = f"%{matter_query}%"
    if date_from:
        conditions.append("date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("date <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions) if conditions else "1=1"

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT * FROM activities_cache
                WHERE {where}
                ORDER BY date DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).mappings().all()

        count_row = conn.execute(
            text(f"SELECT COUNT(*) FROM activities_cache WHERE {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        ).scalar()

    return {
        "data": [dict(r) for r in rows],
        "meta": {
            "total": count_row,
            "limit": limit,
            "offset": offset,
            "cache_age_seconds": _cache_age_seconds(),
            "refresh_error": refresh_error,
        },
    }


@router.get("/billing/summary")
def billing_summary(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD start"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD end"),
    type: Optional[str] = Query(default=None, description="TimeEntry or filter for expense (non-TimeEntry)"),
    user_name: Optional[str] = Query(default=None, description="Filter by user name (contains)"),
    auto_refresh: bool = Query(default=True),
):
    """Aggregated billing stats for the dashboard KPI cards and charts."""
    _ensure_cache_table()

    refresh_error = _auto_refresh_if_stale(client) if auto_refresh else None

    # Filters
    conditions = []
    params: dict = {}
    if date_from:
        conditions.append("date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("date <= :date_to")
        params["date_to"] = date_to
    if type:
        conditions.append("type = :type")
        params["type"] = type
    if user_name:
        conditions.append("user_name LIKE :user_name")
        params["user_name"] = f"%{user_name}%"

    where = " AND ".join(conditions) if conditions else "1=1"

    engine = get_engine()
    with engine.connect() as conn:
        # Overall totals
        totals = conn.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_entries,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN 1 ELSE 0 END), 0) as time_entries,
                    COALESCE(SUM(CASE WHEN type <> 'TimeEntry' THEN 1 ELSE 0 END), 0) as expense_entries,
                    COALESCE(SUM(price), 0) as total_billed,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN price ELSE 0 END), 0) as time_total,
                    COALESCE(SUM(CASE WHEN type <> 'TimeEntry' THEN price ELSE 0 END), 0) as expense_total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN quantity ELSE 0 END), 0) as total_hours
                FROM activities_cache
                WHERE {where}
            """),
            params,
        ).mappings().first()

        # By user
        by_user = conn.execute(
            text(f"""
                SELECT
                    user_name,
                    COUNT(*) as entries,
                    COALESCE(SUM(price), 0) as total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN quantity ELSE 0 END), 0) as hours
                FROM activities_cache
                WHERE {where}
                GROUP BY user_name
                ORDER BY total DESC
            """),
            params,
        ).mappings().all()

        # By month (for line/bar chart)
        by_month = conn.execute(
            text(f"""
                SELECT
                    SUBSTR(date, 1, 7) as month,
                    COALESCE(SUM(price), 0) as total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN price ELSE 0 END), 0) as time_total,
                    COALESCE(SUM(CASE WHEN type <> 'TimeEntry' THEN price ELSE 0 END), 0) as expense_total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN quantity ELSE 0 END), 0) as hours
                FROM activities_cache
                WHERE {where}
                GROUP BY SUBSTR(date, 1, 7)
                ORDER BY month ASC
            """),
            params,
        ).mappings().all()

        # By activity category (top 10)
        by_category = conn.execute(
            text(f"""
                SELECT
                    COALESCE(activity_category, 'Uncategorized') as category,
                    COUNT(*) as entries,
                    COALESCE(SUM(price), 0) as total
                FROM activities_cache
                WHERE {where}
                GROUP BY activity_category
                ORDER BY total DESC
                LIMIT 10
            """),
            params,
        ).mappings().all()

    return {
        "totals": dict(totals) if totals else {},
        "by_user": [dict(r) for r in by_user],
        "by_month": [dict(r) for r in by_month],
        "by_category": [dict(r) for r in by_category],
        "cache_age_seconds": _cache_age_seconds(),
        "refresh_error": refresh_error,
    }
