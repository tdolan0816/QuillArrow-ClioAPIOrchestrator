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

    Exact (normalized) names always win so that when your firm has near-duplicate fields
    such as:
        "OC Firm Name"        (new)
        "O/C Firm Name"       (old / to be retired)
        "Vehicle Make"        (new)
        "Vehicle Make (Old)"  (old)
    typing the exact modern name resolves to the modern field. Aliases (slashes removed,
    parentheticals stripped) are only added for names that don't already have an exact
    entry, so an old field can never displace a new one with the same base text.
    """
    exact: dict[str, int] = {}
    alias: dict[str, int] = {}

    # Pass 1: exact normalized names only -- these are authoritative.
    for fid, fdef in cf_lookup.items():
        name = fdef.get("name")
        if not name:
            continue
        base = _normalize_cf_key(name)
        if not base:
            continue
        exact.setdefault(base, fid)

    # Pass 2: aliases, but never overwrite an exact match.
    for fid, fdef in cf_lookup.items():
        name = fdef.get("name")
        if not name:
            continue
        base = _normalize_cf_key(name)
        if not base:
            continue

        # Alias: no slashes (e.g., "O/C" -> "oc")
        no_slash = base.replace("/", "")
        if no_slash and no_slash != base and no_slash not in exact:
            alias.setdefault(no_slash, fid)

        # Alias: drop "(parenthetical)" -- "Vehicle Make (Old)" -> "vehicle make"
        no_paren = re.sub(r"\s*\([^)]*\)\s*", " ", base).strip()
        no_paren = re.sub(r"\s+", " ", no_paren)
        if no_paren and no_paren != base and no_paren not in exact:
            alias.setdefault(no_paren, fid)

    return {**alias, **exact}  # exact keys overwrite alias keys with the same string


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
    cf_filters: str = Query(default="", description="Custom field filters as JSON: [{\"name\":\"OC Firm Name\",\"value\":\"...\"}]"),
    limit: int = Query(default=50, ge=1, le=200),
    debug: int = Query(default=0, description="Set to 1 to include per-filter diagnostics in the response"),
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

            # Each target filter is (field_id, field_type, raw_value, lower_value, picklist_option_ids).
            # For picklist fields, picklist_option_ids is the set of option ids whose option text
            # matches the user's input (substring, case-insensitive). For non-picklist fields the
            # set is empty and we fall back to string substring matching as before.
            target_filters: list[tuple[int, str, str, str, set[str]]] = []

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
                fdef = cf_lookup.get(fid) or {}
                ftype = fdef.get("field_type") or ""

                # Picklist: resolve the user's text to matching picklist option ids. Clio stores
                # cfv.value as the option id (e.g. 12305135), so we compare id->id.
                option_id_set: set[str] = set()
                if ftype.lower() == "picklist":
                    try:
                        # Clio rejects `picklist_options{deleted}` as an InvalidFields request,
                        # so we only request id/option. Deleted options simply won't appear in
                        # active matters' custom_field_values, so no special filtering needed.
                        detail = client._request(
                            "GET",
                            f"custom_fields/{fid}?fields=id,picklist_options{{id,option}}",
                        )
                        opts = (detail.get("data", {}) or {}).get("picklist_options", []) if isinstance(detail, dict) else []
                        needle = raw_value.lower()
                        matches: list[tuple[int, str]] = []
                        for opt in opts:
                            option_text = str(opt.get("option") or "")
                            if needle in option_text.lower():
                                matches.append((opt.get("id"), option_text))
                        if not matches:
                            warnings.append(
                                f"No picklist option in '{fdef.get('name')}' matches '{raw_value}'; "
                                f"filter ignored."
                            )
                            continue
                        option_id_set = {str(m[0]) for m in matches}
                        print(
                            f"  [Matters Search]   resolved picklist {raw_value!r} -> "
                            f"{[f'{oid}:{otxt}' for (oid, otxt) in matches]}"
                        )
                    except Exception as lookup_err:
                        warnings.append(
                            f"Failed to load picklist options for '{fdef.get('name')}': {lookup_err}."
                        )
                        continue

                print(
                    f"  [Matters Search]   resolved filter {raw_name!r} -> "
                    f"field_id={fid} name={fdef.get('name')!r} type={ftype}"
                )
                target_filters.append((fid, ftype, raw_value, raw_value.lower(), option_id_set))

            if target_filters:
                print(
                    f"  [Matters Search] CF filters active -> "
                    f"{[(fid, ftype, rv) for (fid, ftype, rv, _, _) in target_filters]} "
                    f"across {len(filtered)} candidate matters"
                )
                # Per-filter diagnostics for the UI / debug mode
                filter_stats = {
                    fid: {
                        "field_id": fid,
                        "field_type": ftype,
                        "value_sent": rv,
                        "matters_with_a_value": 0,
                        "matters_matched": 0,
                        "sample_stored_values": [],  # small sample of real values we saw
                        "picklist_option_ids": sorted(opt_ids) if opt_ids else [],
                    }
                    for (fid, ftype, rv, _, opt_ids) in target_filters
                }

                cf_matched: list[dict] = []
                for matter in filtered:
                    mid = matter.get("id")
                    try:
                        # Keep the field selector minimal: some Clio tenants reject extra
                        # nested selectors like picklist_option{...} on mixed-type cfv lists.
                        endpoint = f"matters/{mid}?fields=id,custom_field_values{{id,value,custom_field}}"
                        detail = client._request("GET", endpoint)
                        detail_data = detail.get("data", {}) if isinstance(detail, dict) else {}
                        if isinstance(detail_data, list):
                            detail_data = detail_data[0] if detail_data else {}
                        cfvs = detail_data.get("custom_field_values", [])

                        # Map: field_id -> list of comparable string forms (raw value + picklist text, etc.)
                        cf_values_raw: dict[int, list[str]] = {}
                        for cfv in cfvs:
                            cf_ref = cfv.get("custom_field", {}) or {}
                            cf_id = cf_ref.get("id")
                            if cf_id is None:
                                continue
                            forms: list[str] = []
                            val = cfv.get("value")
                            if val is not None:
                                if isinstance(val, (str, int, float, bool)):
                                    forms.append(str(val))
                                elif isinstance(val, dict):
                                    # e.g. {"id":..., "option":"Ford"} or {"name":"..."}
                                    for key in ("option", "name", "display", "value"):
                                        if key in val and val[key] is not None:
                                            forms.append(str(val[key]))
                                    forms.append(str(val))
                                elif isinstance(val, list):
                                    for item in val:
                                        forms.append(str(item))
                                else:
                                    forms.append(str(val))
                            if forms:
                                cf_values_raw[cf_id] = forms

                        def cf_value_matches(
                            fid: int,
                            ftype: str,
                            needle_raw: str,
                            needle_lower: str,
                            opt_ids: set[str],
                        ) -> bool:
                            forms = cf_values_raw.get(fid)
                            if not forms:
                                return False
                            if ftype.lower() == "picklist":
                                # cfv.value is the picklist option id; compare against resolved ids.
                                return any(str(f) in opt_ids for f in forms)
                            if ftype.lower() == "date":
                                needle_clean = needle_raw.strip()
                                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", needle_clean):
                                    return any(str(f).startswith(needle_clean) for f in forms)
                                return any(needle_lower in str(f).lower() for f in forms)
                            return any(needle_lower in str(f).lower() for f in forms)

                        all_match = True
                        for (fid, ftype, rv, lv, opt_ids) in target_filters:
                            stat = filter_stats[fid]
                            forms = cf_values_raw.get(fid)
                            if forms:
                                stat["matters_with_a_value"] += 1
                                if len(stat["sample_stored_values"]) < 5:
                                    sample = {
                                        "matter_id": mid,
                                        "display_number": matter.get("display_number"),
                                        "stored_forms": forms[:5],
                                    }
                                    stat["sample_stored_values"].append(sample)
                            passed = cf_value_matches(fid, ftype, rv, lv, opt_ids)
                            if passed:
                                stat["matters_matched"] += 1
                            else:
                                all_match = False
                        if all_match:
                            cf_matched.append(matter)
                    except Exception as cf_err:
                        print(f"  [Matters Search] CF lookup failed for matter {mid}: {cf_err}")
                        continue

                # Summarize diagnostics in the server log so you can see it in Terminal A.
                for stat in filter_stats.values():
                    print(
                        f"  [Matters Search]   field_id={stat['field_id']} "
                        f"type={stat['field_type']} value_sent={stat['value_sent']!r} "
                        f"matters_with_value={stat['matters_with_a_value']} "
                        f"matters_matched={stat['matters_matched']}"
                    )
                    for s in stat["sample_stored_values"][:3]:
                        print(
                            f"      e.g. matter {s['matter_id']} ({s['display_number']}): "
                            f"stored={s['stored_forms']}"
                        )

                filtered = cf_matched

    # Trim to the requested limit now that server-side filtering is done.
    trimmed = filtered[:limit]

    response: dict = {
        "data": trimmed,
        "total": len(trimmed),
        "matched_total": len(filtered),
        "warnings": warnings,
    }
    if debug and cf_active and "filter_stats" in locals():
        response["cf_diagnostics"] = list(filter_stats.values())  # type: ignore[name-defined]
    return response


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
