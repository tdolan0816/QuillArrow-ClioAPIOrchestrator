"""
Matter endpoints.

All routes require authentication (JWT token in Authorization header).

Endpoints:
    GET /api/matters              — list matters (paginated)
    GET /api/matters/search       — find matter by display number
    GET /api/matters/{matter_id}  — get single matter with full custom field values
"""

from fastapi import APIRouter, Depends, Query, HTTPException

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from operations import (
    list_matters,
    get_matter,
    find_matter_by_display_number,
)

router = APIRouter(tags=["Matters"])


# ── GET /api/matters ─────────────────────────────────────────────────────────
@router.get("/matters")
def api_list_matters(
    limit: int = Query(default=10, ge=1, le=200, description="Number of matters to return (1-200)"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    List matters with basic fields: id, display_number, description, status.

    Query parameters:
        limit: how many to return (default 10, max 200)
    """
    return list_matters(client, limit=limit)


# ── GET /api/matters/search ──────────────────────────────────────────────────
# IMPORTANT: This route must be defined BEFORE /api/matters/{matter_id}
# otherwise FastAPI would interpret "search" as a matter_id.
@router.get("/matters/search")
def api_find_matter(
    display_number: str = Query(..., description="Full display number (e.g., '00015-Agueros')"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Find a matter by its display number.

    Returns the full matter detail with all custom field values resolved
    (same as GET /api/matters/{id}).
    """
    try:
        return find_matter_by_display_number(client, display_number)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── GET /api/matters/{matter_id} ─────────────────────────────────────────────
@router.get("/matters/{matter_id}")
def api_get_matter(
    matter_id: int,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Get a single matter by ID with fully resolved custom field values.

    Each custom field value includes:
        - value_id: the composite ID for this value instance
        - value: the actual data
        - custom_field.field_def_id: the field definition ID
        - custom_field.name: the human-readable field name
        - custom_field.field_type: text_line, numeric, picklist, etc.
    """
    try:
        return get_matter(client, matter_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
