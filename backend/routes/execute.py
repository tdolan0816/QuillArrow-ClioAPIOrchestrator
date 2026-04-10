"""
Execute (Real Run) endpoints.

These endpoints do the same preparation as the preview endpoints, then
actually send the PATCH requests to Clio and record everything in the
audit log.

Every successful update captures before/after values for rollback capability.

Endpoints:
    POST /api/execute/update-field         — execute a single custom field update
    POST /api/execute/bulk-update-fields   — execute CSV bulk custom field updates
    POST /api/execute/bulk-update-matters  — execute CSV bulk matter property updates
"""

import sqlite3

from fastapi import APIRouter, Depends, UploadFile, File, Form
from pydantic import BaseModel

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from backend.database import get_db
from backend.audit import write_audit_log
from backend.routes._prepare import (
    prepare_custom_field_update,
    prepare_bulk_custom_field_updates,
    prepare_bulk_matter_updates,
)

router = APIRouter(tags=["Execute (Real Run)"])


class UpdateFieldRequest(BaseModel):
    matter_id: str
    field_name: str
    value: str


# ── POST /api/execute/update-field ───────────────────────────────────────────

@router.post("/execute/update-field")
def execute_update_field(
    req: UpdateFieldRequest,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Execute a single custom field update on a matter.

    Runs all preparation steps, sends the PATCH to Clio, and records
    the change in the audit log with before/after values.
    """
    # Step 1: Prepare (same as preview)
    try:
        change = prepare_custom_field_update(client, req.matter_id, req.field_name, req.value)
    except Exception as e:
        write_audit_log(db, username=user.username, action="update_custom_field",
                        matter_id=req.matter_id, field_name=req.field_name,
                        after_value=req.value, status="error", error_message=str(e))
        return {"success": False, "error": str(e)}

    # Step 2: Send the PATCH to Clio
    try:
        result = client.patch(f"matters/{req.matter_id}.json", body=change["patch_body"])
    except Exception as e:
        write_audit_log(db, username=user.username, action="update_custom_field",
                        matter_id=req.matter_id, field_name=req.field_name,
                        before_value=str(change["current_value"]), after_value=req.value,
                        status="error", error_message=str(e))
        return {"success": False, "error": str(e), "change": change}

    # Step 3: Audit log
    write_audit_log(
        db,
        username=user.username,
        action="update_custom_field",
        endpoint="/api/execute/update-field",
        matter_id=req.matter_id,
        field_name=req.field_name,
        before_value=str(change["current_value"]),
        after_value=req.value,
        details={
            "field_def_id": change["field_def_id"],
            "field_type": change["field_type"],
            "value_id": change["value_id"],
            "resolved_value": change["resolved_value"],
        },
    )

    return {"success": True, "change": change}


# ── POST /api/execute/bulk-update-fields ─────────────────────────────────────

@router.post("/execute/bulk-update-fields")
def execute_bulk_update_fields(
    file: UploadFile = File(...),
    field_name: str = Form(default=""),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Execute CSV bulk custom field updates.

    Prepares all rows, then sends PATCHes one at a time. Each row is
    independently logged to the audit trail. If one row fails, the
    rest continue.
    """
    content = file.file.read().decode("utf-8")
    fname = field_name.strip() if field_name.strip() else None

    # Prepare all rows
    changes, prep_errors = prepare_bulk_custom_field_updates(client, content, field_name=fname)

    if not changes and prep_errors:
        return {"success": False, "completed": 0, "failed": 0, "errors": prep_errors}

    # Execute each prepared change
    completed = 0
    failed = 0
    results = []

    for change in changes:
        mid = change["matter_id"]
        try:
            client.patch(f"matters/{mid}.json", body=change["patch_body"])
            write_audit_log(
                db, username=user.username, action="bulk_update_custom_field",
                endpoint="/api/execute/bulk-update-fields",
                matter_id=mid, field_name=change["field_name"],
                before_value=str(change["current_value"]),
                after_value=change["new_value"],
                details={"field_def_id": change["field_def_id"], "field_type": change["field_type"]},
            )
            results.append({"matter_id": mid, "field": change["field_name"], "status": "success"})
            completed += 1
        except Exception as e:
            write_audit_log(
                db, username=user.username, action="bulk_update_custom_field",
                matter_id=mid, field_name=change["field_name"],
                status="error", error_message=str(e),
            )
            results.append({"matter_id": mid, "field": change["field_name"], "status": "error", "error": str(e)})
            failed += 1

    return {
        "success": failed == 0,
        "completed": completed,
        "failed": failed,
        "total_rows": len(changes),
        "prep_errors": prep_errors,
        "results": results,
    }


# ── POST /api/execute/bulk-update-matters ────────────────────────────────────

@router.post("/execute/bulk-update-matters")
def execute_bulk_update_matters(
    file: UploadFile = File(...),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Execute CSV bulk matter property updates.

    Prepares all rows, validates column names, then sends PATCHes one at
    a time. Each row is independently logged to the audit trail.
    """
    content = file.file.read().decode("utf-8")

    changes, prep_errors = prepare_bulk_matter_updates(client, content)

    if not changes and prep_errors:
        return {"success": False, "completed": 0, "failed": 0, "errors": prep_errors}

    completed = 0
    failed = 0
    results = []

    for change in changes:
        mid = change["matter_id"]
        fields_updated = list(change["fields_to_update"].keys())
        try:
            client.patch(f"matters/{mid}.json", body=change["patch_body"])
            write_audit_log(
                db, username=user.username, action="bulk_update_matter",
                endpoint="/api/execute/bulk-update-matters",
                matter_id=mid,
                details={"fields_updated": fields_updated, "values": change["fields_to_update"]},
            )
            results.append({"matter_id": mid, "fields": fields_updated, "status": "success"})
            completed += 1
        except Exception as e:
            write_audit_log(
                db, username=user.username, action="bulk_update_matter",
                matter_id=mid, status="error", error_message=str(e),
            )
            results.append({"matter_id": mid, "fields": fields_updated, "status": "error", "error": str(e)})
            failed += 1

    return {
        "success": failed == 0,
        "completed": completed,
        "failed": failed,
        "total_rows": len(changes),
        "prep_errors": prep_errors,
        "results": results,
    }
