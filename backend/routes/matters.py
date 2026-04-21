"""
Matter endpoints.

Endpoints:
    GET /api/matters                       — list matters (basic fields, paginated)
    GET /api/matters/search                — advanced search with filtering
    GET /api/matters/custom-field-names    — names of Matter custom fields (for UI dropdowns)
    GET /api/matters/{matter_id}           — full detail with all fields + custom values
"""

import re

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


# ── Custom-field filter helpers ──────────────────────────────────────────────

def _normalize_cf_key(s: str) -> str:
    """Lowercase + strip + collapse whitespace; used to compare Clio field names."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip().lower())


def _build_cf_name_index(cf_lookup: dict[int, dict]) -> dict[str, int]:
    """
    Build a case-insensitive, whitespace-tolerant lookup: normalized name -> field id.
    Also indexes common aliases (slashes removed, parentheticals stripped) so users can
    type "O/C" when the real field is "Opposing Counsel" — the UI still returns a clear
    `warnings` entry when nothing matches.
    """
    index: dict[str, int] = {}
    for fid, fdef in cf_lookup.items():
        name = fdef.get("name")
        if not name:
            continue
        base = _normalize_cf_key(name)
        if not base:
            continue
        index.setdefault(base, fid)

        # Alias: no slashes (e.g., "O/C" -> "oc")
        no_slash = base.replace("/", "")
        if no_slash and no_slash != base:
            index.setdefault(no_slash, fid)

        # Alias: drop any "(parenthetical)" suffix/prefix -- "Opposing Counsel (O/C)" -> "opposing counsel"
        no_paren = re.sub(r"\s*\([^)]*\)\s*", " ", base).strip()
        no_paren = re.sub(r"\s+", " ", no_paren)
        if no_paren and no_paren != base:
            index.setdefault(no_paren, fid)
    return index


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

    - Clio `query` handles the main text search.
    - Attorney / staff / date range filters are applied locally.
    - `cf_filters` is a JSON array of {name, value}. Filters use normalized name matching
      (case, whitespace, "/" tolerant). If a filter name doesn't match a Clio Matter custom
      field, it is returned in `warnings` so the UI can tell the user.
    - When CF filters are present, we scan a wider pool than `limit` so filtering isn't
      limited to the first page of Clio results.
    """
    import json

    warnings: list[str] = []

    # When we need to apply CF filters we scan a larger pool first, then trim to `limit` at the end.
    cf_active = bool(cf_filters.strip())
    search_limit = max(limit, 500) if cf_active else limit

    raw = search_matters(client, query=q.strip() or None, limit=search_limit)

    if isinstance(raw, list):
        matters = raw
    elif isinstance(raw, dict):
        matters = raw.get("data", [])
    else:
        matters = []

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

    # Custom field filtering (fetches CF values per candidate matter; can be slower)
    if cf_active:
        try:
            cf_filter_list = json.loads(cf_filters)
        except json.JSONDecodeError:
            cf_filter_list = []
            warnings.append("cf_filters parameter was not valid JSON; it was ignored.")

        if cf_filter_list:
            cf_lookup = get_custom_field_lookup(client)
            cf_name_index = _build_cf_name_index(cf_lookup)

            target_filters: list[tuple[int, str, str, str]] = []  # (field_id, field_type, raw_value, lower_value)
            for f in cf_filter_list:
                raw_name = (f.get("name") or "").strip()
                raw_value = (f.get("value") or "").strip()
                if not raw_name or not raw_value:
                    continue
                key = _normalize_cf_key(raw_name)
                key_no_slash = key.replace("/", "")
                fid = cf_name_index.get(key) or cf_name_index.get(key_no_slash)
                if fid is None:
                    warnings.append(
                        f"Custom field '{raw_name}' was not found among Matter custom fields; filter ignored."
                    )
                    continue
                ftype = (cf_lookup.get(fid) or {}).get("field_type") or ""
                target_filters.append((fid, ftype, raw_value, raw_value.lower()))

            if target_filters:
                print(
                    f"  [Matters Search] CF filters active -> "
                    f"{[(fid, ftype, rv) for (fid, ftype, rv, _) in target_filters]} "
                    f"across {len(filtered)} candidate matters"
                )
                cf_matched: list[dict] = []
                for matter in filtered:
                    mid = matter.get("id")
                    try:
                        endpoint = f"matters/{mid}?fields=id,custom_field_values{{id,value,custom_field}}"
                        detail = client._request("GET", endpoint)
                        detail_data = detail.get("data", {}) if isinstance(detail, dict) else {}
                        if isinstance(detail_data, list):
                            detail_data = detail_data[0] if detail_data else {}
                        cfvs = detail_data.get("custom_field_values", [])

                        # Map: field_id -> raw value (string)
                        cf_values_raw: dict[int, str] = {}
                        for cfv in cfvs:
                            cf_ref = cfv.get("custom_field", {}) or {}
                            fid = cf_ref.get("id")
                            if fid is None:
                                continue
                            val = cfv.get("value")
                            if val is None:
                                continue
                            cf_values_raw[fid] = str(val)

                        def cf_value_matches(fid: int, ftype: str, needle_raw: str, needle_lower: str) -> bool:
                            stored = cf_values_raw.get(fid)
                            if stored is None:
                                return False
                            stored_lower = stored.lower()
                            if ftype.lower() == "date":
                                # Exact-match YYYY-MM-DD if the user supplied a date-like string, else substring
                                needle_clean = needle_raw.strip()
                                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", needle_clean):
                                    return stored.startswith(needle_clean)
                                return needle_lower in stored_lower
                            # default: substring match, case-insensitive
                            return needle_lower in stored_lower

                        all_match = all(
                            cf_value_matches(fid, ftype, rv, lv)
                            for (fid, ftype, rv, lv) in target_filters
                        )
                        if all_match:
                            cf_matched.append(matter)
                    except Exception as cf_err:
                        print(f"  [Matters Search] CF lookup failed for matter {mid}: {cf_err}")
                        continue
                filtered = cf_matched

    # Trim to the requested limit now that server-side filtering is done.
    trimmed = filtered[:limit]

    return {
        "data": trimmed,
        "total": len(trimmed),
        "matched_total": len(filtered),
        "warnings": warnings,
    }


# ── GET /api/matters/custom-field-names ──────────────────────────────────────
@router.get("/matters/custom-field-names")
def api_list_matter_custom_field_names(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Return the canonical names of Matter custom fields, so the UI can power filter dropdowns
    and show users the exact names to use in `cf_filters`.
    """
    cf_lookup = get_custom_field_lookup(client)
    result = [
        {"id": fid, "name": fdef.get("name"), "field_type": fdef.get("field_type")}
        for fid, fdef in cf_lookup.items()
        if fdef.get("name")
    ]
    result.sort(key=lambda r: (r["name"] or "").lower())
    return {"data": result, "total": len(result)}


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
