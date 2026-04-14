"""
Custom field endpoints.

Endpoints:
    GET /api/custom-fields              — list custom field definitions
    GET /api/custom-fields/search       — search by name, type, parent
    GET /api/custom-fields/{field_id}   — full detail with picklist options
"""

from fastapi import APIRouter, Depends, Query, HTTPException

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from operations import list_custom_fields, get_custom_field_detail, search_custom_fields

router = APIRouter(tags=["Custom Fields"])


# ── GET /api/custom-fields ───────────────────────────────────────────────────
@router.get("/custom-fields")
def api_list_custom_fields(
    limit: int = Query(default=10, ge=1, le=200),
    parent_type: str | None = Query(default=None, description="Filter: 'Matter', 'Contact', etc."),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """List custom field definitions with basic fields."""
    return list_custom_fields(client, limit=limit, parent_type=parent_type)


# ── GET /api/custom-fields/search ────────────────────────────────────────────
@router.get("/custom-fields/search")
def api_search_custom_fields(
    q: str = Query(default="", description="Search by name"),
    field_type: str = Query(default="", description="Filter by field_type (text_line, picklist, etc.)"),
    parent_type: str = Query(default="", description="Filter by parent_type (Matter, Contact)"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Search custom fields with optional type and parent filters.
    Server-side filtering applied after Clio API response.
    """
    raw = search_custom_fields(
        client,
        query=q.strip() or None,
        parent_type=parent_type.strip() or None,
        limit=limit,
    )

    if isinstance(raw, list):
        fields = raw
    elif isinstance(raw, dict):
        fields = raw.get("data", [])
    else:
        fields = []

    if field_type.strip():
        ft = field_type.strip().lower()
        fields = [f for f in fields if (f.get("field_type") or "").lower() == ft]

    return {"data": fields, "total": len(fields)}


# ── GET /api/custom-fields/{field_id} ────────────────────────────────────────
@router.get("/custom-fields/{field_id}")
def api_get_custom_field(
    field_id: int,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Get full custom field detail: metadata, configuration, picklist options,
    and field set membership.
    """
    try:
        return get_custom_field_detail(client, field_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
