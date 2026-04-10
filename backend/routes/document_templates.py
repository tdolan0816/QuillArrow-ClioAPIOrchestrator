"""
Document template endpoints.

Endpoints:
    GET /api/document-templates  — list document templates
"""

from fastapi import APIRouter, Depends, Query

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from operations import list_document_templates

router = APIRouter(tags=["Document Templates"])


@router.get("/document-templates")
def api_list_document_templates(
    limit: int = Query(default=10, ge=1, le=200, description="Number of templates to return"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    List document templates.

    Each template includes: id, filename.
    """
    return list_document_templates(client, limit=limit)
