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
    try:
        with engine.begin() as conn:
            conn.execute(create_sql)
    except Exception:
        pass


def _parse_activity(record: dict, now_epoch: int) -> dict:
    """Flatten a Clio activity record into a cache-friendly dict."""
    user = record.get("user") or {}
    matter = record.get("matter") or {}
    act_desc = record.get("activity_description") or {}
    exp_cat = record.get("expense_category") or {}

    return {
        "id": record.get("id"),
        "type": record.get("type"),
        "date": record.get("date"),
        "quantity": record.get("quantity"),
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
    """Pull activities from Clio and upsert into the cache table."""
    _ensure_cache_table()
    engine = get_engine()
    now_epoch = int(time.time())

    params: dict = {}
    if date_from:
        params["created_since"] = date_from

    records = []
    for record in client.get_all("/activities", fields=_ACTIVITY_FIELDS, **params):
        records.append(_parse_activity(record, now_epoch))

    if not records:
        return 0

    with engine.begin() as conn:
        # Clear old cache rows for the IDs we're about to insert
        ids = [r["id"] for r in records]
        # SQLite/MSSQL both support IN with parameter lists up to ~1000
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start:chunk_start + 500]
            placeholders = ",".join(str(i) for i in chunk)
            conn.execute(text(f"DELETE FROM activities_cache WHERE id IN ({placeholders})"))

        # Insert fresh rows
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

    return len(records)


def _cache_age_seconds() -> int | None:
    """Return how many seconds since the most recent cache write, or None if empty."""
    engine = get_engine()
    _ensure_cache_table()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT MAX(cached_at) FROM activities_cache")).scalar()
    if row is None:
        return None
    return int(time.time()) - int(row)


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/billing/refresh")
def refresh_activities(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    days_back: int = Query(default=90, description="How many days of history to pull"),
):
    """Force a refresh of the activities cache from Clio."""
    date_from = (date.today() - timedelta(days=days_back)).isoformat()
    count = _refresh_cache(client, date_from=date_from)
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

    # Auto-refresh if stale
    age = _cache_age_seconds()
    if auto_refresh and (age is None or age > 3600):
        date_cutoff = (date.today() - timedelta(days=90)).isoformat()
        _refresh_cache(client, date_from=date_cutoff)

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
        },
    }


@router.get("/billing/summary")
def billing_summary(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD start"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD end"),
    auto_refresh: bool = Query(default=True),
):
    """Aggregated billing stats for the dashboard KPI cards and charts."""
    _ensure_cache_table()

    # Auto-refresh if stale
    age = _cache_age_seconds()
    if auto_refresh and (age is None or age > 3600):
        date_cutoff = (date.today() - timedelta(days=90)).isoformat()
        _refresh_cache(client, date_from=date_cutoff)

    # Date filter
    conditions = []
    params: dict = {}
    if date_from:
        conditions.append("date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("date <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions) if conditions else "1=1"

    engine = get_engine()
    with engine.connect() as conn:
        # Overall totals
        totals = conn.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_entries,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN 1 ELSE 0 END), 0) as time_entries,
                    COALESCE(SUM(CASE WHEN type='ExpenseEntry' THEN 1 ELSE 0 END), 0) as expense_entries,
                    COALESCE(SUM(total), 0) as total_billed,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN total ELSE 0 END), 0) as time_total,
                    COALESCE(SUM(CASE WHEN type='ExpenseEntry' THEN total ELSE 0 END), 0) as expense_total,
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
                    COALESCE(SUM(total), 0) as total,
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
                    COALESCE(SUM(total), 0) as total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN total ELSE 0 END), 0) as time_total,
                    COALESCE(SUM(CASE WHEN type='ExpenseEntry' THEN total ELSE 0 END), 0) as expense_total,
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
                    COALESCE(SUM(total), 0) as total
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
    }
