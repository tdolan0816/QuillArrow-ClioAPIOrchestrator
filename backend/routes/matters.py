"""
Matter endpoints.

Endpoints:
    GET /api/matters              — list matters (basic fields, paginated)
    GET /api/matters/search       — advanced search with filtering
    GET /api/matters/{matter_id}  — full detail with all fields + custom values
"""

from fastapi import APIRouter, Depends, Query, HTTPException

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from operations import (
    list_matters,
    get_matter_detail,
    search_matters,
    get_custom_field_lookup,
)

router = APIRouter(tags=["Matters"])


# ── GET /api/matters ─────────────────────────────────────────────────────────
@router.get("/matters")
def api_list_matters(
    limit: int = Query(default=10, ge=1, le=200),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """List matters with basic fields: id, display_number, description, status."""
    return list_matters(client, limit=limit)


# ── GET /api/matters/search ──────────────────────────────────────────────────
@router.get("/matters/search")
def api_search_matters(
    q: str = Query(default="", description="Full-text search (display number, description, etc.)"),
    responsible_attorney: str = Query(default="", description="Filter by responsible attorney name"),
    originating_attorney: str = Query(default="", description="Filter by originating attorney name"),
    responsible_staff: str = Query(default="", description="Filter by responsible staff name"),
    open_date_from: str = Query(default="", description="Open date range start (YYYY-MM-DD)"),
    open_date_to: str = Query(default="", description="Open date range end (YYYY-MM-DD)"),
    status: str = Query(default="", description="Filter by status (Open, Closed, Pending)"),
    cf_filters: str = Query(default="", description="Custom field filters as JSON: [{\"name\":\"O/C\",\"value\":\"...\"}]"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Advanced matter search with server-side filtering.

    Clio's API supports `query` for full-text search. Additional filters
    (attorney names, date ranges, custom field values) are applied server-side
    after fetching results from Clio.
    """
    import json

    raw = search_matters(client, query=q.strip() or None, limit=limit)

    if isinstance(raw, list):
        matters = raw
    elif isinstance(raw, dict):
        matters = raw.get("data", [])
    else:
        matters = []

    # Server-side filters for fields Clio can't filter natively
    def matches(matter):
        if status and matter.get("status", "").lower() != status.lower():
            return False

        if responsible_attorney:
            ra = matter.get("responsible_attorney") or {}
            if responsible_attorney.lower() not in (ra.get("name") or "").lower():
                return False

        if originating_attorney:
            oa = matter.get("originating_attorney") or {}
            if originating_attorney.lower() not in (oa.get("name") or "").lower():
                return False

        if responsible_staff:
            rs = matter.get("responsible_staff") or {}
            if responsible_staff.lower() not in (rs.get("name") or "").lower():
                return False

        od = matter.get("open_date") or ""
        if open_date_from and od < open_date_from:
            return False
        if open_date_to and od > open_date_to:
            return False

        return True

    filtered = [m for m in matters if matches(m)]

    # Custom field filtering (requires fetching detail per matter — only if filters provided)
    if cf_filters.strip():
        try:
            cf_filter_list = json.loads(cf_filters)
        except json.JSONDecodeError:
            cf_filter_list = []

        if cf_filter_list:
            cf_lookup = get_custom_field_lookup(client)
            cf_name_to_id = {}
            for fid, fdef in cf_lookup.items():
                if fdef.get("name"):
                    cf_name_to_id[fdef["name"].lower()] = fid

            target_filters = []
            for f in cf_filter_list:
                name = (f.get("name") or "").strip().lower()
                value = (f.get("value") or "").strip().lower()
                if name and value and name in cf_name_to_id:
                    target_filters.append((cf_name_to_id[name], value))

            if target_filters:
                cf_matched = []
                for matter in filtered:
                    mid = matter.get("id")
                    try:
                        endpoint = f"matters/{mid}?fields=id,custom_field_values{{id,value,custom_field}}"
                        detail = client._request("GET", endpoint)
                        detail_data = detail.get("data", {}) if isinstance(detail, dict) else {}
                        if isinstance(detail_data, list):
                            detail_data = detail_data[0] if detail_data else {}
                        cfvs = detail_data.get("custom_field_values", [])

                        cf_values = {}
                        for cfv in cfvs:
                            cf_ref = cfv.get("custom_field", {})
                            cf_values[cf_ref.get("id")] = str(cfv.get("value") or "").lower()

                        all_match = all(
                            filter_val in cf_values.get(filter_id, "")
                            for filter_id, filter_val in target_filters
                        )
                        if all_match:
                            cf_matched.append(matter)
                    except Exception:
                        continue
                filtered = cf_matched

    return {"data": filtered, "total": len(filtered)}


# ── GET /api/matters/{matter_id} ─────────────────────────────────────────────
@router.get("/matters/{matter_id}")
def api_get_matter(
    matter_id: int,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Get full matter detail with all fields: people, financials, practice area,
    stage, group, relationships, and enriched custom field values.
    """
    try:
        return get_matter_detail(client, matter_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
