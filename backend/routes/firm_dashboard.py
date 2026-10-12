"""
Firm Wide Dashboard endpoints (landing page).

Matter-level KPIs for stakeholders: how many matters the firm has filed over
time, how many are Open / Pending / Closed, and the same split by Jurisdiction
(State vs Federal vs Arbitration).

Two Clio Matter custom fields drive everything:
    * "Matter Filed Date"  (custom field id 19020488, type date)  — the date
      every chart buckets on and every date filter applies to.
    * "Jurisdiction"       (custom field id 8835211, type picklist) — options:
          Federal      -> picklist option id 4702486
          State        -> picklist option id 4702471
          Arbitration  -> picklist option id 10733393
          blank / null -> counted as STATE (every case starts in State court;
                          brand-new matters simply haven't been tagged yet).

Like the Billing dashboard, this page never calls Clio on page load. Matters
are pulled into a local cache table (``matters_cache``) by a background
refresh job (``POST /api/firm/refresh``) and every GET aggregates from the
cache with plain SQL. The refresh runs in a thread because a full matter pull
at firm volume takes longer than Azure's ~230s gateway timeout; the UI polls
``GET /api/firm/refresh/status``.

Endpoints:
    POST /api/firm/refresh          — start a background pull of matters from Clio
    GET  /api/firm/refresh/status   — poll refresh state
    GET  /api/firm/summary          — KPI totals (all / state / federal / arbitration)
    GET  /api/firm/trend            — matters filed per period × jurisdiction × status
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import BigInteger, Column, Index, MetaData, String, Table, Text, text

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import get_clio_client, require_auth
from backend.database import get_engine

router = APIRouter(tags=["Firm Wide Dashboard"])
log = logging.getLogger(__name__)

# ── Clio custom-field configuration — EDIT HERE if the fields change ────────
FILED_DATE_FIELD_ID = 19020488
JURISDICTION_FIELD_ID = 8835211
JURISDICTION_OPTIONS = {
    4702486: "Federal",
    4702471: "State",
    10733393: "Arbitration",
}
# Matters with no Jurisdiction value are bucketed here (see module docstring).
JURISDICTION_DEFAULT = "State"
JURISDICTIONS = ("State", "Federal", "Arbitration")
STATUSES = ("Open", "Pending", "Closed")

# ── Cache schema (dialect-neutral; same approach as billing.py) ─────────────
_metadata = MetaData()

matters_cache = Table(
    "matters_cache",
    _metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("display_number", String(200)),
    Column("description", Text),
    Column("status", String(32)),
    Column("open_date", String(16)),
    Column("close_date", String(16)),
    Column("pending_date", String(16)),
    # "Matter Filed Date" custom field — the dashboard's time axis.
    Column("filed_date", String(16)),
    # Raw picklist option id (for troubleshooting) + the resolved bucket.
    Column("jurisdiction_option_id", BigInteger),
    Column("jurisdiction", String(32)),
    Column("created_at", String(40)),
    Column("updated_at", String(40)),
    Column("cached_at", BigInteger, nullable=False),
    Index("idx_matters_cache_filed", "filed_date"),
    Index("idx_matters_cache_filed_jur_status", "filed_date", "jurisdiction", "status"),
)

matters_cache_meta = Table(
    "matters_cache_meta",
    _metadata,
    Column("meta_key", String(40), primary_key=True),
    Column("meta_value", String(80), nullable=False),
)

_META_LAST_REFRESH = "last_refresh_epoch"
_META_REFRESH_LOCK = "refresh_lock_epoch"
_META_REFRESH_STATUS = "refresh_status"      # running | ok | error
_META_REFRESH_MESSAGE = "refresh_message"
_META_REFRESH_STARTED = "refresh_started_epoch"
_META_VALUE_MAX = 80
_LOCK_STALE_SECONDS = 900
_INSERT_BATCH_SIZE = 500
# Incremental refreshes re-pull anything Clio says changed since the last
# run, overlapped a little so clock skew can't drop an edit.
_INCREMENTAL_OVERLAP_SECONDS = 600

# Only what the dashboard needs. custom_field_values is requested with
# single-level nesting (the only nesting Clio's index endpoint supports).
_MATTER_FIELDS = (
    "id,display_number,description,status,open_date,close_date,pending_date,"
    "created_at,updated_at,custom_field_values{id,value,custom_field}"
)


def _is_object_exists_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "already exists" in msg or "already an object" in msg


def _ensure_tables() -> None:
    engine = get_engine()
    for table in (matters_cache, matters_cache_meta):
        try:
            table.create(engine, checkfirst=True)
        except Exception as exc:  # noqa: BLE001
            if _is_object_exists_error(exc):
                continue
            raise


# ── Meta helpers ────────────────────────────────────────────────────────────

def _meta_get(key: str) -> str | None:
    _ensure_tables()
    with get_engine().connect() as conn:
        return conn.execute(
            text("SELECT meta_value FROM matters_cache_meta WHERE meta_key = :k"),
            {"k": key},
        ).scalar()


def _meta_set(key: str, value: str) -> None:
    _ensure_tables()
    with get_engine().begin() as conn:
        conn.execute(matters_cache_meta.delete().where(matters_cache_meta.c.meta_key == key))
        conn.execute(matters_cache_meta.insert(), {"meta_key": key, "meta_value": value[:_META_VALUE_MAX]})


def _meta_delete(key: str) -> None:
    _ensure_tables()
    with get_engine().begin() as conn:
        conn.execute(matters_cache_meta.delete().where(matters_cache_meta.c.meta_key == key))


def _try_acquire_lock() -> bool:
    now = int(time.time())
    existing = _meta_get(_META_REFRESH_LOCK)
    if existing:
        try:
            started = int(existing)
        except ValueError:
            started = 0
        if now - started < _LOCK_STALE_SECONDS:
            return False
        log.warning("Stale matters refresh lock detected; taking over")
    _meta_set(_META_REFRESH_LOCK, str(now))
    return True


def _release_lock() -> None:
    _meta_delete(_META_REFRESH_LOCK)


def _set_status(status: str, message: str = "") -> None:
    _meta_set(_META_REFRESH_STATUS, status)
    _meta_set(_META_REFRESH_MESSAGE, message or "")


def _cache_age_seconds() -> int | None:
    row = _meta_get(_META_LAST_REFRESH)
    if row is None:
        return None
    return int(time.time()) - int(row)


def _cache_count() -> int:
    _ensure_tables()
    with get_engine().connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM matters_cache")).scalar() or 0)


# ── Clio → cache row ────────────────────────────────────────────────────────

def _parse_matter(record: dict, now_epoch: int) -> dict:
    """Flatten a Clio matter record (with custom_field_values) into a cache row."""
    filed_date = None
    jur_option_id = None
    for cfv in record.get("custom_field_values") or []:
        cf = cfv.get("custom_field") or {}
        fid = cf.get("id")
        val = cfv.get("value")
        if fid == FILED_DATE_FIELD_ID and val:
            # Date custom fields come back as "YYYY-MM-DD"; keep the first 10
            # chars defensively in case a timestamp ever sneaks in.
            filed_date = str(val)[:10]
        elif fid == JURISDICTION_FIELD_ID and val not in (None, ""):
            # Picklist values are the option id (int or numeric string).
            try:
                jur_option_id = int(val)
            except (TypeError, ValueError):
                jur_option_id = None

    jurisdiction = JURISDICTION_OPTIONS.get(jur_option_id, JURISDICTION_DEFAULT)

    return {
        "id": record.get("id"),
        "display_number": record.get("display_number"),
        "description": record.get("description"),
        "status": record.get("status"),
        "open_date": record.get("open_date"),
        "close_date": record.get("close_date"),
        "pending_date": record.get("pending_date"),
        "filed_date": filed_date,
        "jurisdiction_option_id": jur_option_id,
        "jurisdiction": jurisdiction,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "cached_at": now_epoch,
    }


def _upsert_batch(batch: list[dict]) -> None:
    if not batch:
        return
    ids = [r["id"] for r in batch if r.get("id") is not None]
    with get_engine().begin() as conn:
        if ids:
            conn.execute(matters_cache.delete().where(matters_cache.c.id.in_(ids)))
        conn.execute(matters_cache.insert(), batch)


def _refresh_cache(client: ClioClient, *, full: bool) -> int:
    """Pull matters from Clio into the cache. Returns rows written.

    ``full=True`` re-pulls every matter and purges cache rows Clio no longer
    returns (deleted matters). Otherwise only matters updated since the last
    refresh are pulled — fast enough to run routinely.
    """
    _ensure_tables()
    now_epoch = int(time.time())
    last = _meta_get(_META_LAST_REFRESH)
    incremental = bool(last) and not full and _cache_count() > 0

    params: dict = {}
    if incremental:
        since = int(last) - _INCREMENTAL_OVERLAP_SECONDS
        params["updated_since"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))

    live_ids: set[int] = set()
    batch: list[dict] = []
    written = 0
    for record in client.get_all("matters", fields=_MATTER_FIELDS, limit=200, **params):
        row = _parse_matter(record, now_epoch)
        if row["id"] is None:
            continue
        live_ids.add(row["id"])
        batch.append(row)
        if len(batch) >= _INSERT_BATCH_SIZE:
            _upsert_batch(batch)
            written += len(batch)
            batch = []
            _set_status("running", f"{'incremental' if incremental else 'full'} sync: {written} matters…")
    _upsert_batch(batch)
    written += len(batch)

    if not incremental and live_ids:
        # Full pull: anything not returned by Clio no longer exists there.
        with get_engine().begin() as conn:
            conn.execute(matters_cache.delete().where(matters_cache.c.cached_at < now_epoch))

    _meta_set(_META_LAST_REFRESH, str(now_epoch))
    return written


def _run_refresh_job(client: ClioClient, *, full: bool) -> None:
    try:
        count = _refresh_cache(client, full=full)
        _set_status("ok", f"Synced {count} matters")
        log.info("matters refresh complete: %s rows", count)
    except Exception as exc:  # noqa: BLE001
        log.exception("matters refresh failed")
        _set_status("error", str(exc))
    finally:
        _release_lock()


# ── Routes: refresh ─────────────────────────────────────────────────────────

@router.post("/firm/refresh")
def refresh_matters(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    full: bool = Query(default=False, description="Re-pull every matter (also purges deleted ones)."),
):
    """Start a background refresh of the matters cache. Returns immediately."""
    if not _try_acquire_lock():
        raise HTTPException(status_code=409, detail="A refresh is already in progress. Please wait for it to finish.")

    # First-ever refresh is always a full pull.
    do_full = full or _cache_count() == 0
    _set_status("running", f"{'full' if do_full else 'incremental'} sync started")
    _meta_set(_META_REFRESH_STARTED, str(int(time.time())))

    threading.Thread(
        target=_run_refresh_job,
        kwargs={"client": client, "full": do_full},
        name="matters-refresh",
        daemon=True,
    ).start()
    return {"status": "started", "mode": "full" if do_full else "incremental"}


@router.get("/firm/refresh/status")
def refresh_status(user: UserInfo = Depends(require_auth)):
    state = _meta_get(_META_REFRESH_STATUS) or "idle"
    message = _meta_get(_META_REFRESH_MESSAGE) or ""
    started = _meta_get(_META_REFRESH_STARTED)
    running_for = None
    if started:
        try:
            running_for = int(time.time()) - int(started)
        except ValueError:
            running_for = None
    if state == "running" and _meta_get(_META_REFRESH_LOCK) is None:
        state = "error"
        message = message or "Refresh stopped unexpectedly"
    return {
        "state": state,
        "message": message,
        "running_for_seconds": running_for,
        "cache_age_seconds": _cache_age_seconds(),
        "cached_matters": _cache_count(),
    }


# ── Aggregation helpers ─────────────────────────────────────────────────────

def _dialect_name() -> str:
    return get_engine().dialect.name


def _period_expr(granularity: str) -> str:
    """SQL expression bucketing ``filed_date`` for the requested granularity."""
    mssql = _dialect_name() == "mssql"
    if granularity == "day":
        return "filed_date"
    if granularity == "week":
        if mssql:
            return (
                "CONCAT(SUBSTRING(filed_date, 1, 4), '-', "
                "RIGHT('0' + CAST(DATEPART(week, CAST(filed_date AS DATE)) AS VARCHAR), 2))"
            )
        return "strftime('%Y-%W', filed_date)"
    return "SUBSTRING(filed_date, 1, 7)" if mssql else "SUBSTR(filed_date, 1, 7)"


def _build_where(*, date_from: str | None, date_to: str | None, jurisdiction: str | None) -> tuple[str, dict]:
    """WHERE clause shared by the cards and the charts.

    Date filters apply to the Matter Filed Date; matters without a filed date
    never match a date filter (they're reported separately as ``unfiled``).
    """
    clauses = ["filed_date IS NOT NULL"]
    params: dict = {}
    if date_from:
        clauses.append("filed_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        clauses.append("filed_date <= :date_to")
        params["date_to"] = date_to
    if jurisdiction:
        clauses.append("jurisdiction = :jurisdiction")
        params["jurisdiction"] = jurisdiction
    return " WHERE " + " AND ".join(clauses), params


def _empty_bucket() -> dict:
    return {"total": 0, "open": 0, "pending": 0, "closed": 0}


def _default_window(today: date) -> tuple[str, str]:
    """Default to the trailing 12 months (first of month, 11 months back → today)."""
    year, month = today.year, today.month - 11
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1).isoformat(), today.isoformat()


# ── Routes: data ────────────────────────────────────────────────────────────

@router.get("/firm/summary")
def firm_summary(
    user: UserInfo = Depends(require_auth),
    date_from: Optional[str] = Query(default=None, description="Matter Filed Date >= (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(default=None, description="Matter Filed Date <= (YYYY-MM-DD)"),
    jurisdiction: Optional[str] = Query(default=None, description="State | Federal | Arbitration"),
):
    """KPI totals for the Firm Wide Dashboard cards.

    ``totals`` is the firm-wide bucket honouring every filter (incl. the
    Jurisdiction filter). ``by_jurisdiction`` always splits the date window
    into State / Federal / Arbitration regardless of the jurisdiction filter,
    so the State and Federal card rows are always populated.
    """
    _ensure_tables()
    today = date.today()
    if not date_from and not date_to:
        date_from, date_to = _default_window(today)
    if jurisdiction and jurisdiction not in JURISDICTIONS:
        raise HTTPException(status_code=400, detail=f"jurisdiction must be one of {JURISDICTIONS}")

    where_all, params_all = _build_where(date_from=date_from, date_to=date_to, jurisdiction=jurisdiction)
    where_jur, params_jur = _build_where(date_from=date_from, date_to=date_to, jurisdiction=None)

    totals = _empty_bucket()
    by_jur = {j: _empty_bucket() for j in JURISDICTIONS}
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(f"SELECT status, COUNT(*) AS n FROM matters_cache{where_all} GROUP BY status"),
            params_all,
        ).mappings().all()
        for r in rows:
            n = int(r["n"] or 0)
            totals["total"] += n
            key = (r["status"] or "").lower()
            if key in totals:
                totals[key] += n

        rows = conn.execute(
            text(
                f"SELECT jurisdiction, status, COUNT(*) AS n FROM matters_cache{where_jur} "
                "GROUP BY jurisdiction, status"
            ),
            params_jur,
        ).mappings().all()
        for r in rows:
            bucket = by_jur.get(r["jurisdiction"])
            if bucket is None:
                continue
            n = int(r["n"] or 0)
            bucket["total"] += n
            key = (r["status"] or "").lower()
            if key in bucket:
                bucket[key] += n

        unfiled = int(conn.execute(
            text("SELECT COUNT(*) FROM matters_cache WHERE filed_date IS NULL")
        ).scalar() or 0)
        cached = int(conn.execute(text("SELECT COUNT(*) FROM matters_cache")).scalar() or 0)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "jurisdiction": jurisdiction,
        "totals": totals,
        "by_jurisdiction": by_jur,
        "unfiled_matters": unfiled,
        "cached_matters": cached,
        "cache_age_seconds": _cache_age_seconds(),
    }


@router.get("/firm/trend")
def firm_trend(
    user: UserInfo = Depends(require_auth),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    granularity: str = Query(default="month", pattern="^(day|week|month)$"),
):
    """Matters filed per period, split by jurisdiction and status.

    Returns one flat row per (period, jurisdiction, status) so the UI can
    drive both charts' dropdowns (Jurisdiction / Matter Status) client-side
    without another round trip. Only the time interval needs a re-query.
    """
    _ensure_tables()
    today = date.today()
    if not date_from and not date_to:
        date_from, date_to = _default_window(today)
    where, params = _build_where(date_from=date_from, date_to=date_to, jurisdiction=None)
    period = _period_expr(granularity)

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT {period} AS period, jurisdiction, status, COUNT(*) AS n "
                f"FROM matters_cache{where} "
                f"GROUP BY {period}, jurisdiction, status ORDER BY period"
            ),
            params,
        ).mappings().all()

    return {
        "date_from": date_from,
        "date_to": date_to,
        "granularity": granularity,
        "rows": [
            {
                "period": r["period"],
                "jurisdiction": r["jurisdiction"],
                "status": r["status"],
                "count": int(r["n"] or 0),
            }
            for r in rows
        ],
    }
