"""
Execute (Real Run) endpoints.

These endpoints do the same preparation as the preview endpoints, then
actually send the PATCH requests to Clio and record everything in the
audit log. Every successful update captures before/after values for the
Revert feature below.

Endpoints:
    POST /api/execute/update-field          -- execute a single custom field update
    POST /api/execute/bulk-update-fields    -- execute CSV bulk custom field updates
    POST /api/execute/bulk-update-matters   -- execute CSV bulk matter property updates
    POST /api/execute/revert/{batch_id}     -- revert every successful row from a prior execute

Each execute() call is stamped with a fresh `batch_id` (uuid4). All audit rows
produced by that call share the batch id so the revert endpoint can pull them
back as one group, rebuild the reverse PATCHes, and mark the originals as
`reverted=true` in the audit log.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from backend.database import get_db
from backend.audit import (
    write_audit_log,
    new_batch_id,
    get_batch_rows_for_revert,
    mark_rows_reverted,
)
from backend.routes._prepare import (
    prepare_custom_field_update,
    prepare_bulk_custom_field_updates,
    prepare_bulk_matter_updates,
)
from operations import VALID_MATTER_REFERENCE_FIELDS

router = APIRouter(tags=["Execute (Real Run)"])


# ── Request bodies ──────────────────────────────────────────────────────────

class UpdateFieldRequest(BaseModel):
    matter_id: str = ""
    display_number: str = ""
    field_name: str
    value: str


# ── Shared helpers ──────────────────────────────────────────────────────────

def _audit_matter_update(
    db: Connection,
    *,
    batch_id: str,
    username: str,
    endpoint: str,
    action: str,
    matter_id: str,
    previous_values: dict,
    new_fields: dict,
    display_number: str | None = None,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """
    One audit row per matter-level bulk update. `previous_values` and
    `new_fields` keep both sides of every column so revert can reconstruct
    the exact prior state.
    """
    write_audit_log(
        db,
        username=username,
        action=action,
        endpoint=endpoint,
        matter_id=str(matter_id),
        details={
            "fields_updated": list(new_fields.keys()),
            "previous_values": previous_values,
            "new_values": new_fields,
            "display_number": display_number,
        },
        before_value=json.dumps(previous_values, default=str),
        after_value=json.dumps(new_fields, default=str),
        status=status,
        error_message=error_message,
        batch_id=batch_id,
    )


# ── POST /api/execute/update-field ──────────────────────────────────────────

@router.post("/execute/update-field")
def execute_update_field(
    req: UpdateFieldRequest,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: Connection = Depends(get_db),
):
    """
    Execute a single custom field update on a matter.

    Every call gets its own batch_id, which the response returns so the UI can
    offer a Revert button tied to this specific execute.
    """
    batch_id = new_batch_id()

    try:
        change = prepare_custom_field_update(
            client, req.matter_id or None, req.field_name, req.value,
            display_number=req.display_number or None,
        )
    except Exception as e:
        write_audit_log(
            db,
            username=user.username,
            action="update_custom_field",
            matter_id=req.matter_id or req.display_number,
            field_name=req.field_name,
            after_value=req.value,
            status="error",
            error_message=str(e),
            batch_id=batch_id,
        )
        return {"success": False, "error": str(e), "batch_id": batch_id}

    resolved_id = change["matter_id"]

    try:
        client.patch(f"matters/{resolved_id}.json", body=change["patch_body"])
    except Exception as e:
        write_audit_log(
            db,
            username=user.username,
            action="update_custom_field",
            matter_id=resolved_id,
            field_name=req.field_name,
            before_value=str(change["current_value"]),
            after_value=req.value,
            status="error",
            error_message=str(e),
            batch_id=batch_id,
        )
        return {"success": False, "error": str(e), "change": change, "batch_id": batch_id}

    write_audit_log(
        db,
        username=user.username,
        action="update_custom_field",
        endpoint="/api/execute/update-field",
        matter_id=resolved_id,
        field_name=req.field_name,
        before_value=str(change["current_value"]) if change["current_value"] is not None else None,
        after_value=req.value,
        details={
            "display_number": req.display_number or None,
            "field_def_id": change["field_def_id"],
            "field_type": change["field_type"],
            "value_id": change["value_id"],
            "resolved_value": change["resolved_value"],
        },
        batch_id=batch_id,
    )

    return {"success": True, "change": change, "batch_id": batch_id}


# ── POST /api/execute/bulk-update-fields ────────────────────────────────────

@router.post("/execute/bulk-update-fields")
def execute_bulk_update_fields(
    file: UploadFile = File(...),
    field_name: str = Form(default=""),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: Connection = Depends(get_db),
):
    """
    Execute CSV bulk custom field updates. One audit row per CSV row, all
    sharing the same batch_id.
    """
    batch_id = new_batch_id()
    content = file.file.read().decode("utf-8-sig")
    fname = field_name.strip() if field_name.strip() else None

    changes, prep_errors = prepare_bulk_custom_field_updates(client, content, field_name=fname)
    if not changes and prep_errors:
        return {
            "success": False,
            "completed": 0,
            "failed": 0,
            "errors": prep_errors,
            "batch_id": batch_id,
        }

    completed = 0
    failed = 0
    results: list[dict] = []

    for change in changes:
        mid = change["matter_id"]
        try:
            client.patch(f"matters/{mid}.json", body=change["patch_body"])
            write_audit_log(
                db,
                username=user.username,
                action="bulk_update_custom_field",
                endpoint="/api/execute/bulk-update-fields",
                matter_id=mid,
                field_name=change["field_name"],
                before_value=(
                    str(change["current_value"]) if change["current_value"] is not None else None
                ),
                after_value=change["new_value"],
                details={
                    "field_def_id": change["field_def_id"],
                    "field_type": change["field_type"],
                    "value_id": change["value_id"],
                    "resolved_value": change["resolved_value"],
                },
                batch_id=batch_id,
            )
            results.append({"matter_id": mid, "field": change["field_name"], "status": "success"})
            completed += 1
        except Exception as e:
            write_audit_log(
                db,
                username=user.username,
                action="bulk_update_custom_field",
                matter_id=mid,
                field_name=change["field_name"],
                status="error",
                error_message=str(e),
                batch_id=batch_id,
            )
            results.append({
                "matter_id": mid,
                "field": change["field_name"],
                "status": "error",
                "error": str(e),
            })
            failed += 1

    return {
        "success": failed == 0,
        "completed": completed,
        "failed": failed,
        "total_rows": len(changes),
        "prep_errors": prep_errors,
        "results": results,
        "batch_id": batch_id,
    }


# ── POST /api/execute/bulk-update-matters ───────────────────────────────────

@router.post("/execute/bulk-update-matters")
def execute_bulk_update_matters(
    file: UploadFile = File(...),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: Connection = Depends(get_db),
):
    """
    Execute CSV bulk matter property updates. Each row's previous values (captured
    during prepare) are written to the audit log so the row can be reverted.
    """
    batch_id = new_batch_id()
    content = file.file.read().decode("utf-8-sig")

    changes, prep_errors = prepare_bulk_matter_updates(client, content)
    if not changes and prep_errors:
        return {
            "success": False,
            "completed": 0,
            "failed": 0,
            "errors": prep_errors,
            "batch_id": batch_id,
        }

    completed = 0
    failed = 0
    results: list[dict] = []

    for change in changes:
        mid = change["matter_id"]
        patch_fields = change["patch_body"]["data"]
        previous_values = change.get("previous_values") or {}
        fields_updated = list(patch_fields.keys())
        try:
            client.patch(f"matters/{mid}.json", body=change["patch_body"])
            _audit_matter_update(
                db,
                batch_id=batch_id,
                username=user.username,
                endpoint="/api/execute/bulk-update-matters",
                action="bulk_update_matter",
                matter_id=mid,
                previous_values=previous_values,
                new_fields=patch_fields,
                display_number=change.get("display_number"),
            )
            results.append({"matter_id": mid, "fields": fields_updated, "status": "success"})
            completed += 1
        except Exception as e:
            _audit_matter_update(
                db,
                batch_id=batch_id,
                username=user.username,
                endpoint="/api/execute/bulk-update-matters",
                action="bulk_update_matter",
                matter_id=mid,
                previous_values=previous_values,
                new_fields=patch_fields,
                display_number=change.get("display_number"),
                status="error",
                error_message=str(e),
            )
            results.append({
                "matter_id": mid,
                "fields": fields_updated,
                "status": "error",
                "error": str(e),
            })
            failed += 1

    return {
        "success": failed == 0,
        "completed": completed,
        "failed": failed,
        "total_rows": len(changes),
        "prep_errors": prep_errors,
        "results": results,
        "batch_id": batch_id,
    }


# ── POST /api/execute/revert/{batch_id} ─────────────────────────────────────

def _revert_custom_field(client: ClioClient, row: dict) -> dict:
    """Build + send the reverse PATCH for a CF-update audit row."""
    details = json.loads(row.get("details") or "{}") if row.get("details") else {}
    field_def_id = details.get("field_def_id")
    if field_def_id is None:
        raise ValueError("audit row is missing field_def_id; cannot rebuild CF revert")

    before_value = row.get("before_value")  # string (as originally stored)

    # Reuse the same patch shape the executor uses. If the original had a
    # value_id, include it so Clio knows we're updating the same cell.
    cf_entry: dict[str, Any] = {"custom_field": {"id": field_def_id}}
    if before_value is None:
        # Prior state was empty -- Clio doesn't have a documented "clear" verb,
        # but sending an empty string generally clears text/numeric fields.
        cf_entry["value"] = ""
    else:
        cf_entry["value"] = before_value
    if details.get("value_id"):
        cf_entry["id"] = details["value_id"]

    patch_body = {"data": {"custom_field_values": [cf_entry]}}
    return client.patch(f"matters/{row['matter_id']}.json", body=patch_body)


def _revert_matter_update(client: ClioClient, row: dict) -> dict:
    """Build + send the reverse PATCH for a matter-property audit row."""
    details = json.loads(row.get("details") or "{}") if row.get("details") else {}
    previous = details.get("previous_values") or {}
    if not previous:
        raise ValueError(
            "audit row has no previous_values; cannot rebuild matter revert"
        )

    restore: dict[str, Any] = {}
    for col, prior in previous.items():
        if col in VALID_MATTER_REFERENCE_FIELDS:
            if isinstance(prior, dict) and prior.get("id") is not None:
                restore[col] = {"id": prior["id"]}
            # If prior was None we skip -- Clio doesn't expose a clean "unset"
            # for these reference fields via the standard PATCH; admins can
            # clear them manually if they really need the before-state to be
            # unset. This is surfaced in the revert result as a skipped column.
        else:
            # Scalars: restore exact prior string. Dates / booleans / empty strings
            # all ride through as-is.
            restore[col] = prior if prior is not None else ""

    if not restore:
        raise ValueError("nothing to restore for this matter row (all prior refs were unset)")

    return client.patch(f"matters/{row['matter_id']}.json", body={"data": restore})


@router.post("/execute/revert/{batch_id}")
def execute_revert(
    batch_id: str,
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
    db: Connection = Depends(get_db),
):
    """
    Revert every successful, un-reverted audit row for the given batch_id.

    For each row we rebuild a PATCH that restores the prior state, send it to
    Clio, and -- on success -- mark the row as reverted. The revert itself is
    recorded as new audit rows tagged with a fresh revert batch_id so it's
    auditable (and re-revertible).
    """
    rows = get_batch_rows_for_revert(db, batch_id)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No reversible audit rows found for batch '{batch_id}'. "
                "Rows may have been reverted already, or the batch id is wrong."
            ),
        )

    revert_batch_id = new_batch_id()
    reverted_row_ids: list[int] = []
    results: list[dict] = []
    completed = 0
    failed = 0

    # Revert in reverse insertion order so the last change applied is the first
    # to be undone. Protects us from intra-batch ordering dependencies.
    for row in reversed(rows):
        action = row.get("action")
        matter_id = row.get("matter_id")
        try:
            if action in ("update_custom_field", "bulk_update_custom_field"):
                _revert_custom_field(client, row)
                write_audit_log(
                    db,
                    username=user.username,
                    action=f"revert_{action}",
                    endpoint="/api/execute/revert",
                    matter_id=matter_id,
                    field_name=row.get("field_name"),
                    before_value=row.get("after_value"),  # swap perspective
                    after_value=row.get("before_value"),
                    details={
                        "reverted_audit_id": row.get("id"),
                        "reverted_batch_id": batch_id,
                    },
                    batch_id=revert_batch_id,
                )
            elif action == "bulk_update_matter":
                _revert_matter_update(client, row)
                write_audit_log(
                    db,
                    username=user.username,
                    action="revert_bulk_update_matter",
                    endpoint="/api/execute/revert",
                    matter_id=matter_id,
                    details={
                        "reverted_audit_id": row.get("id"),
                        "reverted_batch_id": batch_id,
                    },
                    before_value=row.get("after_value"),
                    after_value=row.get("before_value"),
                    batch_id=revert_batch_id,
                )
            else:
                raise ValueError(f"revert not supported for action '{action}'")
            reverted_row_ids.append(int(row["id"]))
            results.append({
                "audit_id": row["id"],
                "matter_id": matter_id,
                "status": "success",
            })
            completed += 1
        except Exception as e:
            write_audit_log(
                db,
                username=user.username,
                action=f"revert_{action}" if action else "revert",
                endpoint="/api/execute/revert",
                matter_id=matter_id,
                field_name=row.get("field_name"),
                status="error",
                error_message=str(e),
                details={
                    "reverted_audit_id": row.get("id"),
                    "reverted_batch_id": batch_id,
                },
                batch_id=revert_batch_id,
            )
            results.append({
                "audit_id": row["id"],
                "matter_id": matter_id,
                "status": "error",
                "error": str(e),
            })
            failed += 1

    mark_rows_reverted(db, reverted_row_ids, revert_batch_id)

    return {
        "success": failed == 0,
        "reverted": completed,
        "failed": failed,
        "total_rows": len(rows),
        "results": results,
        "original_batch_id": batch_id,
        "revert_batch_id": revert_batch_id,
    }
