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
from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    text,
)

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import get_clio_client, require_auth
from backend.database import get_db, get_engine

# ── Cache schema (dialect-neutral, works on SQLite + Azure SQL) ─────────────
# We use SQLAlchemy Core Table objects instead of raw "CREATE TABLE IF NOT
# EXISTS" because that syntax is SQLite-only — MSSQL/Azure SQL doesn't
# support it. Table.create(checkfirst=True) generates the correct DDL for
# whatever engine we're connected to.
_billing_metadata = MetaData()

activities_cache = Table(
    "activities_cache",
    _billing_metadata,
    Column("id", Integer, primary_key=True),
    Column("type", String(32)),
    Column("date", String(16)),
    Column("quantity", Float),
    Column("note", Text),
    Column("price", Float),
    Column("total", Float),
    Column("flat_rate", Integer),
    Column("billed", Integer),
    Column("user_id", Integer),
    Column("user_name", String(200)),
    Column("matter_id", Integer),
    Column("matter_display_number", String(60)),
    Column("matter_description", String(400)),
    Column("activity_category", String(200)),
    Column("expense_category", String(200)),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
    Column("cached_at", Integer, nullable=False),
)

billing_cache_meta = Table(
    "billing_cache_meta",
    _billing_metadata,
    Column("meta_key", String(40), primary_key=True),
    Column("meta_value", String(80), nullable=False),
)

router = APIRouter(tags=["Billing & Activities"])

# ── Static employee list for filter dropdowns ───────────────────────────────
# Source: QuillArrow_EmployeeList_061926.txt
# Will be replaced by BambooHR API pull in a future sprint.
_EMPLOYEES = [
    "Aaron Grewal", "Aaron Zarrabi", "Aerik Fincher", "Alan Montes",
    "Albert Velazquez", "Alejandro Perfino", "Alessandra Ferriso", "Alex Ottmar",
    "Alfredo Campos", "Alicia Bejar", "Alina Susu", "Amari Garrissey",
    "Ana Mendoza Flores", "Andrew Jung", "Andrew Noseworthy", "Ani Zakaryan",
    "Anthony Reyes Hernandez", "Antonio Rojas", "Aram Danakian", "Arlene Rodriguez",
    "Armando Curan", "Ashley Dillard", "Ashley Sanchez Montoya", "Astha Shah",
    "Aurora Mercado", "Azaya Duncan", "Bethany Mao", "Bethany Villa",
    "Bianca Andrade", "Bianca Peralta", "Brandon Edgar", "Brenda Contreras",
    "Brian Henriquez", "Brianna Johnson", "Briseida Henriquez", "Brittany Farfan",
    "Brittany Gibson", "Brittany Meyerhardt", "Brittany Smallwood", "Bryan Altman",
    "Camilo Fernandez", "Carlos Arredondo", "Carrie Herlihy", "Catherine Sandoval",
    "Cecilia Hidalgo", "Charles Donnelly", "Charlie Solis", "Chase Duffin",
    "Christian Quinonez", "Cody Spencer", "Cole Barron", "Courtney Lugo",
    "Cynthia Tellez", "Daniel Gopstein", "Daniel Louis", "Danilo Guerrero",
    "Danny Mendoza", "David Peterson", "Debbie Cook", "Deborah Correa",
    "Delano Bannister", "Denilson Tecun de Leon", "Dennise Gonzalez", "Derek Chipman",
    "Desiree Lopez", "Diana Fonseca", "Diana Santos", "Diana Shirshova",
    "Ding Wang", "Djeh-ran Aytekin", "Donald Mahnke", "Elena Vicente",
    "Elian Salazar", "Elias Valladares", "Elizabeth McLaughlin", "Elizabeth Votra",
    "Ellen Zakharian", "Emily Marin", "Endrew Omana", "Erick Castillo",
    "Erik Schmitt", "Ester Mehrabanian", "Evelyn Pickens", "Fabian Ramirez",
    "Farah Garcia", "Fatima Tall", "Fernando Rivas", "Gabriel McIntire",
    "Gabriela Refugio", "Genesis Lopez", "Genesis Martinez", "Genesis Perez",
    "Gerardino Lacap", "Gloria Chavez", "Grace Papa", "Grayson Sobel",
    "Greg Loera", "Gregory Sogoyan", "Guadalupe Jimenez", "Gustavo Ocampo",
    "Harberth Godinez", "Harison Sulejmanagic", "Heather Howard", "Henrry Sandoval",
    "Huriel Diego", "Inessa Oganezova", "Irene Reznik", "Irina Monkiewicz",
    "Isabela Lacsina", "Ismael Flores", "Ismenia Benavides", "Jack Chudacoff",
    "Jafarri Nocentelli", "Jaguar Busuego", "Jaiden Cox", "James Carroll",
    "Janette Juarez", "Jasmine Perez", "Jason Muturi", "Jazmin Arambula",
    "Jeanette Velazquez", "Jeleene Punzal", "Jennifer Buenrostro", "Jennifer Guardado",
    "Jenny Lopez", "Jessica Brown", "Jessica Fuentes", "Jessica Mijares",
    "Jessie Zhang", "Jiny Mun", "Jo Encarnacion", "John Honeycutt",
    "Johnson Vo", "Jonathan Shirian", "Joon Kim", "Joonhyoung Suhl",
    "Jorge Martinez", "Jose Salazar", "Joseph Poole", "Josue Dominguez",
    "Josue Linares Barahona", "Jovanny Guevarra-Guerrero", "Julia Maroquin", "Julia Park",
    "Julian Salcedo", "Kaliq Uduman", "Karamjit Singh", "Karen Alfaro",
    "Karina Sanchez Lopez", "Karla Ferrer", "Kassey Spears", "Kassy Amoi",
    "Katarina Fernandez", "Katehrin Welling", "Katherin Tellez", "Katherine Hernandez",
    "Katherine Ly", "Kathia Martinez", "Kayla Corrick", "Kelly Cervantes",
    "Kelly Torres", "Kenneth Pagan Sanchez", "Kevin Jacobson", "Kiara Andrade",
    "Kimberly Barreto", "Kirsten Stillman", "Kristel Santos", "Kristina Grodz",
    "Latrel Powell", "Lee Bowles", "Liana Giniatullina", "Lilian Azat",
    "Lizbeth Rosas", "Lizeth Perez Andres", "Long Cao", "Luz Mejia",
    "Lynn Frasco", "Maddie Dixon", "Mahly Villa", "Maria Melendez",
    "Maria Orozco", "Mariam Ally", "Marie Dugan", "Marina Zherebchevsky",
    "Marisol Cruz", "Mark Morales", "Marvin Salinas", "Mary Efren",
    "Matt Dean", "Matthew Hartman", "Matthew Noel", "Max Reyes",
    "Maya Harbour", "Megan Prough", "Melissa Anaya", "Melody Fermin",
    "Meredith Akins", "Merri Capossela", "Michael Jahangani", "Michelle Lee",
    "Mike Chakhoyan", "Mikhail Alcantara", "Naedy Rodriguez", "Nancy Meily",
    "Nancy Sanchez", "Natalie Valladares", "Nicholas Yowarski", "Nicki Casillas",
    "Nima Elie", "Nima Sadeghi", "Nyomie Argueta", "Olga Ponce",
    "Olivia Andonian", "Oscar Almeralla- Mora", "Paola Rodriguez", "Patricia Torres",
    "Patricio Benavides", "Patrick Dickinson", "Pearl Corbett", "Perla Hernandez",
    "Plus Chuensukanant", "Priscilla Loiola", "Randy Esparza", "Raquel McDonald",
    "Raul Rincon", "Rebecca Jacobson", "Robert Gallander", "Ronald Salguero",
    "Rosa Sandoval", "Rosio Rocha", "Roxana Akseralyan", "Ryan Ardi",
    "Ryan Baggs", "Salma Martinez Aragon", "Samantha Gonzales", "Samantha West",
    "Scott Garcia", "Sebastian Garriga", "Semaias Gonzalez", "Sergio Cardenas",
    "Shammari Khan", "Socorro Hernandez", "Solange Tadros", "Sonia Arefadib",
    "Stephanie Hovhannisyan", "Stephanie Taft", "Stephen Basinger", "Steve Candelario",
    "Steven Chang", "Steven Lobato", "Suzanne Benner", "Tessa Bannister",
    "Timothy Dolan", "Troy Sanders", "Ulises Gonzalez Garcia", "Vanessa Ortega",
    "Veronica Cunningham", "Veronica Rosales", "Vin Andreano", "Wendy Caceres",
    "Wendy Melgar", "Wendy Perla", "Xavier Hozven", "Xitong Lu",
    "Yevgeniya Skovinskaya", "Yugan Siriwardhanage", "Yuvisela Sandoval Sandoval", "Zach Klein",
]


@router.get("/billing/employees")
def list_employees(user: UserInfo = Depends(require_auth)):
    """Return the firm employee list for filter dropdowns."""
    return {"data": _EMPLOYEES}


# Fields we request from Clio's /activities endpoint
_ACTIVITY_FIELDS = (
    "id,type,date,quantity,note,price,total,flat_rate,billed,"
    "created_at,updated_at,"
    "user{id,name},"
    "matter{id,display_number,description},"
    "activity_description{id,name},"
    "expense_category{id,name}"
)


def _is_object_exists_error(exc: BaseException) -> bool:
    """Match the 'table already exists' race across SQLite and MSSQL.

    Mirrors the helper in backend/database.py so parallel gunicorn workers
    creating the cache tables at the same time don't crash each other.
    """
    msg = str(exc).lower()
    return "(2714)" in msg or "42s01" in msg or "already exists" in msg


def _ensure_cache_table():
    """Create the cache tables if they don't exist.

    Uses SQLAlchemy's Table.create(checkfirst=True) so the generated DDL
    is correct for whichever dialect we're connected to (SQLite locally,
    Azure SQL in production). Crucially this avoids the SQLite-only
    'CREATE TABLE IF NOT EXISTS' syntax that silently failed on MSSQL.
    """
    engine = get_engine()
    # Refresh bookkeeping lives outside the data rows so an empty cache
    # (e.g. all activities deleted in Clio) still remembers when it was
    # last synced and doesn't re-hit Clio on every page load.
    for table in (activities_cache, billing_cache_meta):
        try:
            table.create(engine, checkfirst=True)
        except Exception as exc:
            if _is_object_exists_error(exc):
                # Another gunicorn worker won the race — fine.
                continue
            raise


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


# Insert in chunks rather than one-at-a-time. With ~2-3K activities per day
# in Prod, a 30-day refresh is ~75K rows; doing those as individual round-trips
# to Azure SQL takes 10+ minutes (each INSERT is a network hop). Batches of 500
# get the same job done in under a minute.
_INSERT_BATCH_SIZE = 500


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
        conn.execute(activities_cache.delete())

        # Bulk insert in batches. SQLAlchemy turns this into a parameterised
        # multi-row INSERT (or executemany for pyodbc), which is orders of
        # magnitude faster than calling execute() once per row.
        for i in range(0, len(records), _INSERT_BATCH_SIZE):
            batch = records[i : i + _INSERT_BATCH_SIZE]
            conn.execute(activities_cache.insert(), batch)

        # Record the sync time even when 0 records came back.
        conn.execute(
            billing_cache_meta.delete().where(
                billing_cache_meta.c.meta_key == "last_refresh_epoch"
            )
        )
        conn.execute(
            billing_cache_meta.insert(),
            {"meta_key": "last_refresh_epoch", "meta_value": str(now_epoch)},
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

    Uses a 30-day window to keep the automatic pull fast in Production
    (2,000-3,000 entries/day × 30 days ≈ 75,000 records). Users who need
    older data can adjust filters or request a manual refresh.
    """
    age = _cache_age_seconds()
    if age is not None and age <= 3600:
        return None
    date_cutoff = (date.today() - timedelta(days=1)).isoformat()
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
    days_back: int = Query(default=1, description="How many days of history to pull"),
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
        if type == "TimeEntry":
            conditions.append("type = 'TimeEntry'")
        else:
            # "Expense" means anything that isn't a TimeEntry (covers
            # ExpenseEntry, HardCostEntry, SoftCostEntry, etc.)
            conditions.append("type <> 'TimeEntry'")
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
    # MSSQL uses OFFSET/FETCH instead of LIMIT/OFFSET. Both require ORDER BY.
    if engine.dialect.name == "mssql":
        page_clause = "OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"
    else:
        page_clause = "LIMIT :limit OFFSET :offset"

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT * FROM activities_cache
                WHERE {where}
                ORDER BY date DESC
                {page_clause}
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


def _months_back_first(today: date, months: int) -> date:
    """Return the first day of the month that is `months` months before `today`.

    e.g., _months_back_first(date(2026, 6, 23), 5) -> date(2026, 1, 1)
    Used to anchor the 6-month chart window so it starts on a clean month boundary.
    """
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _dialect_name() -> str:
    """Return the SQL dialect name (e.g. 'sqlite', 'mssql')."""
    return get_engine().dialect.name


def _month_expr() -> str:
    """SQL expression that yields 'YYYY-MM' from the `date` column."""
    if _dialect_name() == "mssql":
        # MSSQL doesn't have SUBSTR; SUBSTRING is the equivalent.
        return "SUBSTRING(date, 1, 7)"
    return "SUBSTR(date, 1, 7)"


def _week_expr() -> str:
    """SQL expression that yields a sortable year-week string from `date`."""
    if _dialect_name() == "mssql":
        # Compose year + zero-padded ISO week so values sort correctly when
        # crossing year boundaries (e.g. '2026-01' < '2026-52').
        return (
            "CONCAT(SUBSTRING(date, 1, 4), '-', "
            "RIGHT('0' + CAST(DATEPART(week, CAST(date AS DATE)) AS VARCHAR), 2))"
        )
    return "strftime('%Y-%W', date)"


def _resolve_chart_window(today: date, granularity: str) -> tuple[str, str, str]:
    """Return (date_from, date_to, period_sql_expr) for the trend chart.

    The chart auto-sizes its window so the bar count stays readable regardless
    of granularity (month=6 bars, week=~12 bars, day=~30 bars).
    """
    if granularity == "day":
        return (
            (today - timedelta(days=29)).isoformat(),  # 30 days inclusive
            today.isoformat(),
            "date",
        )
    if granularity == "week":
        return (
            (today - timedelta(weeks=11)).isoformat(),  # 12 weeks inclusive
            today.isoformat(),
            _week_expr(),
        )
    # month (default) — anchor to first-of-month so the leftmost bar is whole
    return (
        _months_back_first(today, 5).isoformat(),
        today.isoformat(),
        _month_expr(),
    )


def _build_summary_where(*, date_from, date_to, type, user_name):
    """Build a WHERE clause + params dict for the activities_cache table.

    Centralised so the cards and the chart can re-use the same filter logic
    against different date windows.
    """
    conds = ["date >= :date_from", "date <= :date_to"]
    params: dict = {"date_from": date_from, "date_to": date_to}
    if type:
        if type == "TimeEntry":
            conds.append("type = 'TimeEntry'")
        else:
            # "Expense" = anything non-Time (covers ExpenseEntry, HardCostEntry,
            # SoftCostEntry, etc. across Clio Prod vs Dev environments).
            conds.append("type <> 'TimeEntry'")
    if user_name:
        conds.append("user_name LIKE :user_name")
        params["user_name"] = f"%{user_name}%"
    return " AND ".join(conds), params


@router.get("/billing/summary")
def billing_summary(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD start (default: first of current month)"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD end (default: today)"),
    type: Optional[str] = Query(default=None, description="TimeEntry or filter for expense (non-TimeEntry)"),
    user_name: Optional[str] = Query(default=None, description="Filter by user name (contains)"),
    granularity: str = Query(default="month", description="Chart aggregation: day, week, or month"),
    auto_refresh: bool = Query(default=True),
):
    """Aggregated billing stats for the dashboard KPI cards and charts.

    Two independent date windows:
      * Cards/attorney/category: user's date_from/date_to filter, defaulting
        to month-to-date when the user hasn't picked one.
      * Trend chart: auto-sized window based on `granularity` (6 months for
        month, 12 weeks for week, 30 days for day) — independent of the
        user's filter so executives always see historical trends.
    Type/user filters apply to BOTH windows.
    """
    _ensure_cache_table()

    refresh_error = _auto_refresh_if_stale(client) if auto_refresh else None

    today = date.today()

    # Cards: respect user filter, fall back to MTD for the default landing view.
    card_date_from = date_from or today.replace(day=1).isoformat()
    card_date_to = date_to or today.isoformat()

    # Chart: auto-sized historical window based on granularity.
    granularity = (granularity or "month").lower()
    if granularity not in ("day", "week", "month"):
        granularity = "month"
    chart_date_from, chart_date_to, period_expr = _resolve_chart_window(today, granularity)

    card_where, card_params = _build_summary_where(
        date_from=card_date_from, date_to=card_date_to, type=type, user_name=user_name,
    )
    chart_where, chart_params = _build_summary_where(
        date_from=chart_date_from, date_to=chart_date_to, type=type, user_name=user_name,
    )

    engine = get_engine()
    with engine.connect() as conn:
        # Overall totals (cards) — MTD by default.
        # ── Dollar amounts use SUM(total), NOT SUM(price). Clio's `total`
        # is the billable dollar amount (rate * quantity, or just the flat
        # rate when flat_rate=true). `price` is just the per-unit rate
        # and gives wrong totals whenever quantity ≠ 1 (e.g. hourly time
        # entries in our Dev environment).
        totals = conn.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_entries,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN 1 ELSE 0 END), 0) as time_entries,
                    COALESCE(SUM(CASE WHEN type <> 'TimeEntry' THEN 1 ELSE 0 END), 0) as expense_entries,
                    COALESCE(SUM(total), 0) as total_billed,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN total ELSE 0 END), 0) as time_total,
                    COALESCE(SUM(CASE WHEN type <> 'TimeEntry' THEN total ELSE 0 END), 0) as expense_total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN quantity ELSE 0 END), 0) as total_hours
                FROM activities_cache
                WHERE {card_where}
            """),
            card_params,
        ).mappings().first()

        # By user (attorney breakdown) — same window as cards
        by_user = conn.execute(
            text(f"""
                SELECT
                    user_name,
                    COUNT(*) as entries,
                    COALESCE(SUM(total), 0) as total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN quantity ELSE 0 END), 0) as hours
                FROM activities_cache
                WHERE {card_where}
                GROUP BY user_name
                ORDER BY total DESC
            """),
            card_params,
        ).mappings().all()

        # Trend chart — auto-sized window with granularity-based grouping
        by_period = conn.execute(
            text(f"""
                SELECT
                    {period_expr} as period,
                    COALESCE(SUM(total), 0) as total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN total ELSE 0 END), 0) as time_total,
                    COALESCE(SUM(CASE WHEN type <> 'TimeEntry' THEN total ELSE 0 END), 0) as expense_total,
                    COALESCE(SUM(CASE WHEN type='TimeEntry' THEN quantity ELSE 0 END), 0) as hours
                FROM activities_cache
                WHERE {chart_where}
                GROUP BY {period_expr}
                ORDER BY period ASC
            """),
            chart_params,
        ).mappings().all()

        # Top categories split by type — Time uses `activity_category` (the
        # "Activity Description" picklist in Clio), Expense uses `expense_category`
        # (a separate picklist). They live in different columns because Clio
        # treats them as different concepts.
        # MSSQL uses TOP N at SELECT, SQLite uses LIMIT N at the end.
        is_mssql = engine.dialect.name == "mssql"
        top_clause_select = "TOP 10 " if is_mssql else ""
        top_clause_end = "" if is_mssql else "LIMIT 10"

        by_category_time = conn.execute(
            text(f"""
                SELECT {top_clause_select}
                    COALESCE(activity_category, 'Uncategorized') as category,
                    COUNT(*) as entries,
                    COALESCE(SUM(total), 0) as total
                FROM activities_cache
                WHERE {card_where} AND type = 'TimeEntry'
                GROUP BY activity_category
                ORDER BY total DESC
                {top_clause_end}
            """),
            card_params,
        ).mappings().all()

        by_category_expense = conn.execute(
            text(f"""
                SELECT {top_clause_select}
                    COALESCE(expense_category, 'Uncategorized') as category,
                    COUNT(*) as entries,
                    COALESCE(SUM(total), 0) as total
                FROM activities_cache
                WHERE {card_where} AND type <> 'TimeEntry'
                GROUP BY expense_category
                ORDER BY total DESC
                {top_clause_end}
            """),
            card_params,
        ).mappings().all()

    by_period_list = [dict(r) for r in by_period]
    by_category_time_list = [dict(r) for r in by_category_time]
    by_category_expense_list = [dict(r) for r in by_category_expense]

    return {
        "totals": dict(totals) if totals else {},
        "by_user": [dict(r) for r in by_user],
        "by_period": by_period_list,
        # Keep `by_month` for any legacy callers — same shape as by_period.
        "by_month": by_period_list,
        "by_category_time": by_category_time_list,
        "by_category_expense": by_category_expense_list,
        # Legacy field — combined list, kept for any pre-split callers.
        "by_category": by_category_time_list + by_category_expense_list,
        "granularity": granularity,
        "card_date_from": card_date_from,
        "card_date_to": card_date_to,
        "chart_date_from": chart_date_from,
        "chart_date_to": chart_date_to,
        "cache_age_seconds": _cache_age_seconds(),
        "refresh_error": refresh_error,
    }
