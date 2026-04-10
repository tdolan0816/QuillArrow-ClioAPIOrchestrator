"""
Preview (Dry Run) endpoints.

These endpoints run all the preparation steps (resolve field names, find
value_ids, validate picklist options) WITHOUT actually sending any PATCH
requests to Clio. They return exactly what WOULD change.

Endpoints:
    POST /api/preview/update-field         — preview a single custom field update
    POST /api/preview/bulk-update-fields   — preview CSV bulk custom field updates
    POST /api/preview/bulk-update-matters  — preview CSV bulk matter property updates
"""

import csv
import io
import sqlite3

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from backend.routes._prepare import (
    prepare_custom_field_update,
    prepare_bulk_custom_field_updates,
    prepare_bulk_matter_updates,
)

router = APIRouter(tags=["Preview (Dry Run)"])


# ── Request models ───────────────────────────────────────────────────────────

class UpdateFieldRequest(BaseModel):
    """Request body for previewing/executing a single custom field update.

    Users can identify a matter by either matter_id or display_number (or both).
    display_number is the human-friendly identifier shown in the Clio UI.
    """
    matter_id: str = ""
    display_number: str = ""
    field_name: str
    value: str


# ── POST /api/preview/update-field ───────────────────────────────────────────

@router.post("/preview/update-field")
def preview_update_field(
    req: UpdateFieldRequest,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Dry run: preview what a single custom field update would do.

    Runs all preparation steps (resolve name, find value_id, validate
    picklist options) but does NOT send any PATCH to Clio.

    Returns the change that would be made, including current and new values.
    """
    try:
        change = prepare_custom_field_update(
            client, req.matter_id or None, req.field_name, req.value,
            display_number=req.display_number or None,
        )
        return {"preview": [change], "total_changes": 1, "errors": []}
    except Exception as e:
        return {"preview": [], "total_changes": 0, "errors": [str(e)]}


# ── POST /api/preview/bulk-update-fields ─────────────────────────────────────

@router.post("/preview/bulk-update-fields")
def preview_bulk_update_fields(
    file: UploadFile = File(..., description="CSV file with columns: matter_id, field_name, value"),
    field_name: str = Form(default="", description="Optional: apply this field name to all rows"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Dry run: preview what a CSV bulk custom field update would do.

    Upload a CSV file. Each row is validated and prepared but NOT sent to Clio.
    Returns the full list of changes that would be made, plus any errors.
    """
    content = file.file.read().decode("utf-8")
    fname = field_name.strip() if field_name.strip() else None
    changes, errors = prepare_bulk_custom_field_updates(client, content, field_name=fname)
    return {"preview": changes, "total_changes": len(changes), "errors": errors}


# ── POST /api/preview/bulk-update-matters ────────────────────────────────────

@router.post("/preview/bulk-update-matters")
def preview_bulk_update_matters(
    file: UploadFile = File(..., description="CSV file with columns: matter_id, plus matter field columns"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Dry run: preview what a CSV bulk matter property update would do.

    Upload a CSV file. Validates all column names against Clio's allowed
    matter fields. Returns the list of changes per matter.
    """
    content = file.file.read().decode("utf-8")
    changes, errors = prepare_bulk_matter_updates(client, content)
    return {"preview": changes, "total_changes": len(changes), "errors": errors}
