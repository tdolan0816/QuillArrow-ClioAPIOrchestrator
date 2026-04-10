"""
Custom field endpoints.

Endpoints:
    GET /api/custom-fields  — list custom field definitions (filterable by parent type)
"""

from fastapi import APIRouter, Depends, Query

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from operations import list_custom_fields

router = APIRouter(tags=["Custom Fields"])


@router.get("/custom-fields")
def api_list_custom_fields(
    limit: int = Query(default=10, ge=1, le=200, description="Number of fields to return"),
    parent_type: str | None = Query(default=None, description="Filter by entity type: 'Matter', 'Contact', 'Activity', etc."),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    List custom field definitions.

    Without parent_type: returns ALL custom fields across all entity types.
    With parent_type=Matter: returns only matter-level custom fields.

    Each field includes: id, name, field_type, parent_type.
    """
    return list_custom_fields(client, limit=limit, parent_type=parent_type)
