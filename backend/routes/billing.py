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

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    Index,
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
from backend.database import get_db, get_engine, _retry_transient

# ── Cache schema (dialect-neutral, works on SQLite + Azure SQL) ─────────────
# We use SQLAlchemy Core Table objects instead of raw "CREATE TABLE IF NOT
# EXISTS" because that syntax is SQLite-only — MSSQL/Azure SQL doesn't
# support it. Table.create(checkfirst=True) generates the correct DDL for
# whatever engine we're connected to.
_billing_metadata = MetaData()

activities_cache = Table(
    "activities_cache",
    _billing_metadata,
    # IDs are BigInteger — Clio activity IDs already exceed the 2.1B INT
    # ceiling (≈7.8B as of mid-2026), and other ID columns will eventually
    # follow. cached_at is also BigInteger so unix epoch values can't
    # overflow once they cross 2.1B (year 2038).
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("type", String(32)),
    Column("date", String(16)),
    Column("quantity", Float),
    Column("note", Text),
    Column("price", Float),
    Column("total", Float),
    Column("flat_rate", Integer),
    Column("billed", Integer),
    Column("user_id", BigInteger),
    Column("user_name", String(200)),
    Column("matter_id", BigInteger),
    # matter_display_number can hold long custom formats like
    # "24089-Filing/Service". 200 is generous.
    Column("matter_display_number", String(200)),
    # matter_description is free-form prose from Clio — unbounded in
    # practice. Use Text (NVARCHAR(MAX) on MSSQL) since we never index it.
    Column("matter_description", Text),
    # activity_category / expense_category ARE indexed; SQL Server's
    # NVARCHAR index-key limit is 450 chars (900 bytes). 450 is safely
    # larger than anything Clio actually produces.
    Column("activity_category", String(450)),
    Column("expense_category", String(450)),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
    Column("cached_at", BigInteger, nullable=False),
    Index("idx_activities_cache_date", "date"),
    Index("idx_activities_cache_date_type", "date", "type"),
    Index("idx_activities_cache_user_date", "user_name", "date"),
    Index("idx_activities_cache_activity_category", "activity_category"),
    Index("idx_activities_cache_expense_category", "expense_category"),
)

billing_cache_meta = Table(
    "billing_cache_meta",
    _billing_metadata,
    Column("meta_key", String(40), primary_key=True),
    Column("meta_value", String(80), nullable=False),
)

router = APIRouter(tags=["Billing & Activities"])
log = logging.getLogger(__name__)

# Cache refresh tuning
_INSERT_BATCH_SIZE = 500
_META_LAST_REFRESH = "last_refresh_epoch"
_META_REFRESH_LOCK = "refresh_lock_epoch"
# Background-refresh status (so the UI can poll instead of holding the request
# open past Azure's ~230s gateway timeout). meta_value is String(80), so keep
# stored values short — the message is truncated before writing.
_META_REFRESH_STATUS = "refresh_status"      # running | ok | error
_META_REFRESH_MESSAGE = "refresh_message"    # short human-readable detail
_META_REFRESH_STARTED = "refresh_started_epoch"
_META_VALUE_MAX = 80
# If a worker dies mid-refresh, allow another worker to take over after this.
_LOCK_STALE_SECONDS = 600
# Overlap incremental syncs slightly so we don't miss edge updates.
_INCREMENTAL_OVERLAP_SECONDS = 300
# How many days back each routine refresh fully re-pulls *by activity date*.
# The dashboard groups by an activity's `date`, so to stay correct we must
# reconcile by date (Clio start_date/end_date) — NOT by created/updated time,
# which silently drops late-entered items (a court reporter or a lawyer logging
# time a few days after the fact). 35 days covers month-to-date plus a buffer
# for those late entries. A separate updated_since pass catches edits to
# entries older than this window.
_RECONCILE_DAYS_DEFAULT = 35

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


def _migrate_cache_schema_if_needed(engine) -> None:
    """One-shot migration: drop activities_cache if its schema is too narrow.

    Two known issues with the original DDL on Azure SQL:
      * ID columns were ``Integer`` (INT, max 2.1B); Clio activity IDs are
        already ~7.8B and overflow with error 8115 / SQLSTATE 22003.
      * Text columns (activity_category, expense_category,
        matter_description) were sized for Dev test data and truncated
        real Clio prose with error 2628 / SQLSTATE 42000.

    Since this cache is rebuilt from Clio on demand, the safest fix for
    both is to drop the table and let ``Table.create()`` recreate it with
    the wider schema. Only runs on MSSQL — SQLite ignores column lengths
    and INTEGER is variable-width.
    """
    if engine.dialect.name != "mssql":
        return
    try:
        with engine.connect() as conn:
            cols = conn.execute(
                text(
                    "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH "
                    "FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = 'activities_cache'"
                )
            ).mappings().all()
        if not cols:
            return
        col_map = {
            row["COLUMN_NAME"].lower(): (
                (row["DATA_TYPE"] or "").lower(),
                row["CHARACTER_MAXIMUM_LENGTH"],
            )
            for row in cols
        }
        reasons: list[str] = []
        # IDs must be BIGINT.
        for c in ("id", "user_id", "matter_id", "cached_at"):
            t = col_map.get(c, (None, None))[0]
            if t and t == "int":
                reasons.append(f"{c} is INT (needs BIGINT)")
        # Free-text columns need to be wide enough.
        def _check_width(col: str, min_chars: int) -> None:
            entry = col_map.get(col)
            if not entry:
                return
            _, length = entry
            # NVARCHAR(MAX) reports -1 — that's fine.
            if length is not None and 0 <= length < min_chars:
                reasons.append(f"{col} is {length} chars (needs ≥{min_chars})")

        _check_width("activity_category", 450)
        _check_width("expense_category", 450)
        _check_width("matter_description", 1000)  # any large value is fine
        _check_width("matter_display_number", 200)

        if not reasons:
            return

        log.warning(
            "activities_cache schema out of date (%s) — dropping and recreating",
            "; ".join(reasons),
        )
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE activities_cache"))
        # Clear last_refresh meta so the next refresh does a fresh seed.
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM billing_cache_meta WHERE meta_key = :k"
                    ),
                    {"k": _META_LAST_REFRESH},
                )
        except Exception:  # noqa: BLE001 -- meta table may not exist yet
            pass
    except Exception as exc:  # noqa: BLE001 -- never block startup on inspection
        log.warning("activities_cache schema check skipped: %s", exc)


def _ensure_cache_table():
    """Create the cache tables if they don't exist.

    Uses SQLAlchemy's Table.create(checkfirst=True) so the generated DDL
    is correct for whichever dialect we're connected to (SQLite locally,
    Azure SQL in production). Crucially this avoids the SQLite-only
    'CREATE TABLE IF NOT EXISTS' syntax that silently failed on MSSQL.
    """
    engine = get_engine()
    _migrate_cache_schema_if_needed(engine)
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


# Insert/upsert in chunks. Each batch commits separately so a long refresh
# survives worker timeouts and partial progress is preserved.
def _meta_get(key: str) -> str | None:
    _ensure_cache_table()
    with get_engine().connect() as conn:
        return conn.execute(
            text("SELECT meta_value FROM billing_cache_meta WHERE meta_key = :k"),
            {"k": key},
        ).scalar()


def _meta_set(key: str, value: str) -> None:
    _ensure_cache_table()
    with get_engine().begin() as conn:
        conn.execute(
            billing_cache_meta.delete().where(billing_cache_meta.c.meta_key == key)
        )
        conn.execute(
            billing_cache_meta.insert(),
            {"meta_key": key, "meta_value": value},
        )


def _meta_delete(key: str) -> None:
    _ensure_cache_table()
    with get_engine().begin() as conn:
        conn.execute(
            billing_cache_meta.delete().where(billing_cache_meta.c.meta_key == key)
        )


def _try_acquire_refresh_lock() -> bool:
    """Return True if this worker acquired the refresh lock."""
    now = int(time.time())
    existing = _meta_get(_META_REFRESH_LOCK)
    if existing:
        try:
            started = int(existing)
        except ValueError:
            started = 0
        if now - started < _LOCK_STALE_SECONDS:
            log.warning(
                "Refresh lock held since epoch %s (%ss ago); rejecting overlap",
                existing,
                now - started,
            )
            return False
        log.warning("Stale refresh lock detected; taking over")
    _meta_set(_META_REFRESH_LOCK, str(now))
    return True


def _release_refresh_lock() -> None:
    _meta_delete(_META_REFRESH_LOCK)


def _upsert_batch(batch: list[dict]) -> None:
    """Upsert a batch of activity rows by primary key (id).

    Cross-database pattern: delete the ids in this batch, then bulk insert.
    Each batch runs in its own transaction so a long refresh commits progress
    incrementally instead of one giant SQLEndTran at the end.
    """
    if not batch:
        return
    engine = get_engine()
    ids = [r["id"] for r in batch if r.get("id") is not None]
    with engine.begin() as conn:
        if ids:
            conn.execute(
                activities_cache.delete().where(activities_cache.c.id.in_(ids))
            )
        conn.execute(activities_cache.insert(), batch)


def _ensure_cache_indexes() -> None:
    """Create indexes on an existing cache table (safe to re-run).

    Table.create(checkfirst=True) only runs at table creation time, so indexes
    added after the table already exists need an explicit pass.
    """
    engine = get_engine()
    for idx in activities_cache.indexes:
        try:
            idx.create(engine, checkfirst=True)
        except Exception as exc:
            if _is_object_exists_error(exc):
                continue
            raise


def _stream_upsert(client: ClioClient, *, now_epoch: int, **clio_params) -> int:
    """Stream activities matching ``clio_params`` from Clio and upsert them.

    Records stream page-by-page; each batch upserts in its own transaction so a
    long pull commits progress incrementally instead of one giant transaction.
    Upsert is keyed by id, so overlapping pulls (date-window + updated_since)
    are naturally de-duplicated.
    """
    count = 0
    batch: list[dict] = []
    for record in client.get_all("/activities", fields=_ACTIVITY_FIELDS, **clio_params):
        batch.append(_parse_activity(record, now_epoch))
        if len(batch) >= _INSERT_BATCH_SIZE:
            _upsert_batch(batch)
            count += len(batch)
            batch.clear()
    if batch:
        _upsert_batch(batch)
        count += len(batch)
    return count


def _refresh_cache(
    client: ClioClient,
    *,
    reconcile_days: int = _RECONCILE_DAYS_DEFAULT,
    full_backfill_days: int | None = None,
    catch_edits: bool = True,
) -> int:
    """Pull activities from Clio and upsert them into the cache.

    Correctness model — the dashboard aggregates by each activity's ``date``,
    so we sync **by activity date**, not by created/updated time. Filtering on
    ``created_since``/``updated_since`` alone silently misses late-entered items
    (e.g. a court reporter's expense or time logged a few days after the fact)
    for dates the dashboard is showing.

    Two passes (both upsert by id, so overlap is harmless):

    1. **Date-window reconcile** — re-pull every activity whose ``date`` falls
       in the rolling window via Clio ``start_date``/``end_date`` and upsert.
       This makes the recent window an exact mirror of Clio on every refresh,
       including anything entered or corrected since the last run. The window
       is ``reconcile_days`` (default 35) for routine refreshes, or
       ``full_backfill_days`` for a one-time/scheduled deep backfill (used to
       populate the 6-month chart history).

    2. **Edit catch-up** — for entries OLDER than the reconcile window, pull
       anything ``updated_since`` the last refresh so edits to historical
       entries are still picked up cheaply. Skipped during a full backfill
       (the wide window already covers everything).

    Never wipes the cache table.
    """
    _ensure_cache_table()
    _ensure_cache_indexes()
    now_epoch = int(time.time())
    t0 = time.time()
    today = date.today()
    last_refresh = _meta_get(_META_LAST_REFRESH)

    if full_backfill_days:
        window_days = full_backfill_days
        catch_edits = False  # the wide date window already covers everything
    else:
        window_days = reconcile_days

    start_date = (today - timedelta(days=window_days)).isoformat()
    end_date = today.isoformat()

    # Pass 1: reconcile by activity date.
    log.info(
        "billing refresh: date-window reconcile %s..%s (%s days)",
        start_date, end_date, window_days,
    )
    total = _stream_upsert(
        client,
        now_epoch=now_epoch,
        start_date=start_date,
        end_date=end_date,
    )
    log.info("billing refresh: date-window pass upserted %s rows", total)

    # Pass 2: catch edits to entries older than the reconcile window.
    if catch_edits and last_refresh is not None:
        since_epoch = max(0, int(last_refresh) - _INCREMENTAL_OVERLAP_SECONDS)
        updated_since = datetime.fromtimestamp(
            since_epoch, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        log.info("billing refresh: edit catch-up updated_since=%s", updated_since)
        edits = _stream_upsert(client, now_epoch=now_epoch, updated_since=updated_since)
        log.info("billing refresh: edit-catch pass upserted %s rows", edits)
        total += edits

    _meta_set(_META_LAST_REFRESH, str(now_epoch))
    log.info(
        "billing refresh: done — %s rows processed in %.1fs",
        total, time.time() - t0,
    )
    return total


def _cache_age_seconds() -> int | None:
    """Return seconds since the last successful refresh, or None if never synced."""
    _ensure_cache_table()
    row = _meta_get(_META_LAST_REFRESH)
    if row is None:
        with get_engine().connect() as conn:
            row = conn.execute(text("SELECT MAX(cached_at) FROM activities_cache")).scalar()
            if row is not None:
                row = str(row)
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
    if not _try_acquire_refresh_lock():
        return "A refresh is already in progress"
    try:
        _refresh_cache(client, reconcile_days=_RECONCILE_DAYS_DEFAULT)
        return None
    except Exception as exc:  # noqa: BLE001 -- degrade to cached data
        return str(exc)
    finally:
        _release_refresh_lock()


def _set_refresh_status(status: str, message: str = "") -> None:
    """Record background-refresh state for the UI to poll.

    meta_value is a short column, so the message is truncated defensively to
    avoid the very "string would be truncated" error we hit on the cache rows.
    """
    _meta_set(_META_REFRESH_STATUS, status[:_META_VALUE_MAX])
    _meta_set(_META_REFRESH_MESSAGE, (message or "")[:_META_VALUE_MAX])


def _run_refresh_job(
    client: ClioClient,
    *,
    reconcile_days: int,
    full_backfill_days: int | None,
) -> None:
    """Body of the background refresh thread.

    Runs the (potentially multi-minute) Clio sync after the HTTP request has
    already returned 202, so Azure's ~230s gateway timeout never applies. The
    DB lock guarantees only one of these runs across all gunicorn workers; we
    release it (and record final status) in a finally block.
    """
    try:
        count = _refresh_cache(
            client,
            reconcile_days=reconcile_days,
            full_backfill_days=full_backfill_days,
        )
        _set_refresh_status("ok", f"Synced {count} activities")
        log.info("background refresh complete: %s rows", count)
    except Exception as exc:  # noqa: BLE001 -- surface to UI via status meta
        log.exception("background refresh failed")
        _set_refresh_status("error", str(exc))
    finally:
        _release_refresh_lock()


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/billing/refresh")
def refresh_activities(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    reconcile_days: int = Query(
        default=_RECONCILE_DAYS_DEFAULT,
        ge=1,
        le=200,
        description="Days back to fully re-pull by activity date (the rolling reconcile window)",
    ),
    full_backfill_days: int = Query(
        default=0,
        ge=0,
        le=400,
        description=(
            "When > 0, do a one-time deep backfill of this many days by "
            "activity date (used to seed the 6-month chart history). 0 = "
            "routine reconcile."
        ),
    ),
):
    """Start a background refresh of the activities cache from Clio.

    Returns **202 Accepted immediately** and runs the sync in a background
    thread. At production volume a refresh takes minutes — far longer than
    Azure App Service's ~230s gateway timeout — so we must NOT hold the HTTP
    request open. The UI polls ``GET /billing/refresh/status`` for progress.

    Syncs **by activity date** (Clio start_date/end_date) so late-entered items
    are never missed, plus an ``updated_since`` pass for edits to older entries.
    Pass ``full_backfill_days`` to seed a wide history window once.

    Only one refresh runs at a time across all gunicorn workers (DB lock).
    """
    if not _try_acquire_refresh_lock():
        raise HTTPException(
            status_code=409,
            detail="A refresh is already in progress. Please wait for it to finish.",
        )

    backfill = full_backfill_days or None
    mode = f"backfill {full_backfill_days}d" if backfill else f"reconcile {reconcile_days}d"

    # Mark running BEFORE spawning so an immediate status poll sees "running".
    _set_refresh_status("running", f"{mode} started")
    _meta_set(_META_REFRESH_STARTED, str(int(time.time())))

    thread = threading.Thread(
        target=_run_refresh_job,
        kwargs={
            "client": client,
            "reconcile_days": reconcile_days,
            "full_backfill_days": backfill,
        },
        name="billing-refresh",
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "mode": mode,
        "reconcile_days": reconcile_days,
        "full_backfill_days": full_backfill_days,
    }


@router.get("/billing/refresh/status")
def refresh_status(user: UserInfo = Depends(require_auth)):
    """Report the state of the most recent background refresh.

    ``state`` is one of: ``idle`` (never run), ``running``, ``ok``, ``error``.
    The UI polls this after kicking off a refresh and reloads the dashboard
    when the state leaves ``running``.
    """
    state = _meta_get(_META_REFRESH_STATUS) or "idle"
    message = _meta_get(_META_REFRESH_MESSAGE) or ""
    started = _meta_get(_META_REFRESH_STARTED)
    running_for = None
    if started:
        try:
            running_for = int(time.time()) - int(started)
        except ValueError:
            running_for = None

    # Self-heal a stuck status: if the lock is gone but status still says
    # running (e.g. the worker died), report it as no longer running.
    lock_held = _meta_get(_META_REFRESH_LOCK) is not None
    if state == "running" and not lock_held:
        state = "error"
        message = message or "Refresh stopped unexpectedly"

    return {
        "state": state,
        "message": message,
        "running_for_seconds": running_for,
        "cache_age_seconds": _cache_age_seconds(),
    }


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
    auto_refresh: bool = Query(
        default=False,
        description=(
            "Deprecated for reads. Cache-only by default — see /billing/summary. "
            "Use POST /billing/refresh to populate the cache."
        ),
    ),
):
    """Return cached activities with optional filters.

    READ-ONLY against the cache; does NOT call Clio. Cache population is the
    job of POST /billing/refresh.
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

    def _run_activities_reads():
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
        return rows, count_row

    rows, count_row = _retry_transient("billing.activities.read", _run_activities_reads)

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
    auto_refresh: bool = Query(
        default=False,
        description=(
            "Deprecated for reads. Cache-only by default — the dashboard must "
            "never trigger a synchronous Clio sync (it can take minutes at "
            "production volume and kills the gunicorn worker). Use POST "
            "/billing/refresh to populate the cache."
        ),
    ),
):
    """Aggregated billing stats for the dashboard KPI cards and charts.

    READ-ONLY against the cache. This endpoint does NOT call Clio: at
    production volume (75K+ rows) a synchronous refresh exceeds the worker
    timeout and returns 502s. Cache population is the job of POST
    /billing/refresh (and, later, a background scheduler).

    Two independent date windows:
      * Cards/attorney/category: user's date_from/date_to filter, defaulting
        to month-to-date when the user hasn't picked one.
      * Trend chart: auto-sized window based on `granularity` (6 months for
        month, 12 weeks for week, 30 days for day) — independent of the
        user's filter so executives always see historical trends.
    Type/user filters apply to BOTH windows.
    """
    _ensure_cache_table()

    # auto_refresh defaults to False; only honoured if a caller explicitly
    # opts in (e.g. an admin tool). Normal dashboard loads read cache only.
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

    # The whole read runs inside a retry so a cold Azure SQL connection
    # (serverless auto-resume / dropped idle link = 08S01) re-runs on a
    # fresh connection instead of 500-ing the dashboard load.
    def _run_summary_reads():
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
        return totals, by_user, by_period, by_category_time, by_category_expense

    totals, by_user, by_period, by_category_time, by_category_expense = _retry_transient(
        "billing.summary.read", _run_summary_reads
    )

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
