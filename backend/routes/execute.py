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
    POST /api/execute/bulk-reassign-tasks   -- execute CSV bulk task reassignments
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
    prepare_bulk_task_reassignments,
)
from backend.routes._bulk_jobs import (
    create_job,
    set_phase_executing,
    record_row,
    touch_message,
    finish_job,
    run_in_thread,
    get_job,
)
from operations import VALID_MATTER_REFERENCE_FIELDS

# How often (in rows) to refresh the human-readable progress message. The
# per-row counters update every row regardless; this only throttles the
# cosmetic "Processing X of N…" string to keep DB writes light.
_PROGRESS_EVERY = 10

router = APIRouter(tags=["Execute (Real Run)"])


# ── Request bodies ──────────────────────────────────────────────────────────

class UpdateFieldRequest(BaseModel):
    matter_id: str = ""
    display_number: str = ""
    field_name: str
    value: str


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

def _run_bulk_update_fields(
    job_id: str, client: ClioClient, content: str, field_name: str | None, username: str
) -> None:
    """Background worker: validate + PATCH every custom-field row."""
    changes, prep_errors = prepare_bulk_custom_field_updates(
        client, content, field_name=field_name
    )
    if not changes:
        finish_job(
            job_id,
            state="error" if prep_errors else "ok",
            message="No valid rows to update." if prep_errors else "Nothing to update.",
            results=[],
            prep_errors=prep_errors,
        )
        return

    total = len(changes)
    set_phase_executing(job_id, total, prep_errors)
    completed = failed = 0
    results: list[dict] = []

    for i, change in enumerate(changes, 1):
        mid = change["matter_id"]
        try:
            client.patch(f"matters/{mid}.json", body=change["patch_body"])
            record_row(
                job_id,
                audit={
                    "username": username,
                    "action": "bulk_update_custom_field",
                    "endpoint": "/api/execute/bulk-update-fields",
                    "matter_id": mid,
                    "field_name": change["field_name"],
                    "before_value": (
                        str(change["current_value"]) if change["current_value"] is not None else None
                    ),
                    "after_value": change["new_value"],
                    "details": {
                        "field_def_id": change["field_def_id"],
                        "field_type": change["field_type"],
                        "value_id": change["value_id"],
                        "resolved_value": change["resolved_value"],
                    },
                    "batch_id": job_id,
                },
                completed=1,
            )
            results.append({"matter_id": mid, "field": change["field_name"], "status": "success"})
            completed += 1
        except Exception as e:  # noqa: BLE001 -- per-row failure, keep going
            record_row(
                job_id,
                audit={
                    "username": username,
                    "action": "bulk_update_custom_field",
                    "matter_id": mid,
                    "field_name": change["field_name"],
                    "status": "error",
                    "error_message": str(e),
                    "batch_id": job_id,
                },
                failed=1,
            )
            results.append({
                "matter_id": mid,
                "field": change["field_name"],
                "status": "error",
                "error": str(e),
            })
            failed += 1

        if i % _PROGRESS_EVERY == 0:
            touch_message(job_id, f"Processing {i} of {total}…")

    finish_job(
        job_id,
        state="ok" if failed == 0 else "error",
        message=f"Completed {completed} of {total}" + (f", {failed} failed" if failed else ""),
        results=results,
        prep_errors=prep_errors,
    )


@router.post("/execute/bulk-update-fields")
def execute_bulk_update_fields(
    file: UploadFile = File(...),
    field_name: str = Form(default=""),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Start a background CSV bulk custom-field update.

    Returns **202-style "started" immediately** and runs the PATCH loop in a
    background thread so Azure's ~230s gateway timeout never applies. The UI
    polls ``GET /api/execute/jobs/{job_id}`` for live progress and results.
    One audit row per CSV row, all sharing the job id as their batch_id.
    """
    batch_id = new_batch_id()
    content = file.file.read().decode("utf-8-sig")
    fname = field_name.strip() if field_name.strip() else None

    create_job(batch_id, "fields", user.username)
    run_in_thread(
        batch_id,
        lambda: _run_bulk_update_fields(batch_id, client, content, fname, user.username),
        name="bulk-fields",
    )
    return {"status": "started", "job_id": batch_id, "batch_id": batch_id}


# ── POST /api/execute/bulk-update-matters ───────────────────────────────────

def _matter_audit_kwargs(
    *, batch_id, username, matter_id, previous_values, new_fields,
    display_number=None, status="success", error_message=None,
) -> dict:
    """Build the write_audit_log kwargs for one matter-update row.

    Mirrors the old _audit_matter_update helper but returns kwargs (so the
    background worker can hand them to record_row) instead of writing directly.
    """
    return {
        "username": username,
        "action": "bulk_update_matter",
        "endpoint": "/api/execute/bulk-update-matters",
        "matter_id": str(matter_id),
        "details": {
            "fields_updated": list(new_fields.keys()),
            "previous_values": previous_values,
            "new_values": new_fields,
            "display_number": display_number,
        },
        "before_value": json.dumps(previous_values, default=str),
        "after_value": json.dumps(new_fields, default=str),
        "status": status,
        "error_message": error_message,
        "batch_id": batch_id,
    }


def _run_bulk_update_matters(
    job_id: str, client: ClioClient, content: str, username: str
) -> None:
    """Background worker: validate + PATCH every matter row.

    Preparation (which resolves display_number → matter_id via a Clio search
    per row) happens HERE, inside the background thread, so even a CSV that
    uses display_numbers for thousands of matters can't blow the gateway
    timeout during validation.
    """
    changes, prep_errors = prepare_bulk_matter_updates(client, content)
    if not changes:
        finish_job(
            job_id,
            state="error" if prep_errors else "ok",
            message="No valid rows to update." if prep_errors else "Nothing to update.",
            results=[],
            prep_errors=prep_errors,
        )
        return

    total = len(changes)
    set_phase_executing(job_id, total, prep_errors)
    completed = failed = 0
    results: list[dict] = []

    for i, change in enumerate(changes, 1):
        mid = change["matter_id"]
        patch_fields = change["patch_body"]["data"]
        previous_values = change.get("previous_values") or {}
        fields_updated = list(patch_fields.keys())
        try:
            client.patch(f"matters/{mid}.json", body=change["patch_body"])
            record_row(
                job_id,
                audit=_matter_audit_kwargs(
                    batch_id=job_id,
                    username=username,
                    matter_id=mid,
                    previous_values=previous_values,
                    new_fields=patch_fields,
                    display_number=change.get("display_number"),
                ),
                completed=1,
            )
            results.append({"matter_id": mid, "fields": fields_updated, "status": "success"})
            completed += 1
        except Exception as e:  # noqa: BLE001 -- per-row failure, keep going
            record_row(
                job_id,
                audit=_matter_audit_kwargs(
                    batch_id=job_id,
                    username=username,
                    matter_id=mid,
                    previous_values=previous_values,
                    new_fields=patch_fields,
                    display_number=change.get("display_number"),
                    status="error",
                    error_message=str(e),
                ),
                failed=1,
            )
            results.append({
                "matter_id": mid,
                "fields": fields_updated,
                "status": "error",
                "error": str(e),
            })
            failed += 1

        if i % _PROGRESS_EVERY == 0:
            touch_message(job_id, f"Processing {i} of {total}…")

    finish_job(
        job_id,
        state="ok" if failed == 0 else "error",
        message=f"Completed {completed} of {total}" + (f", {failed} failed" if failed else ""),
        results=results,
        prep_errors=prep_errors,
    )


@router.post("/execute/bulk-update-matters")
def execute_bulk_update_matters(
    file: UploadFile = File(...),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Start a background CSV bulk matter-property update.

    Returns immediately and runs the PATCH loop in a background thread (see
    _run_bulk_update_matters) so large batches — think 1,000+ matters when an
    attorney leaves the firm — are no longer capped by Azure's ~230s gateway
    timeout. Each row's previous values are captured for Revert. The UI polls
    ``GET /api/execute/jobs/{job_id}`` for progress.
    """
    batch_id = new_batch_id()
    content = file.file.read().decode("utf-8-sig")

    create_job(batch_id, "matters", user.username)
    run_in_thread(
        batch_id,
        lambda: _run_bulk_update_matters(batch_id, client, content, user.username),
        name="bulk-matters",
    )
    return {"status": "started", "job_id": batch_id, "batch_id": batch_id}


# ── POST /api/execute/bulk-reassign-tasks ───────────────────────────────────

def _run_bulk_reassign_tasks(
    job_id: str,
    client: ClioClient,
    content: str,
    username: str,
    *,
    status_override: bool,
    approved: set[str],
) -> None:
    """Background worker: validate + PATCH every approved task reassignment."""
    changes, prep_errors = prepare_bulk_task_reassignments(
        client, content, status_override=status_override
    )
    if not changes:
        finish_job(
            job_id,
            state="error" if prep_errors else "ok",
            message="No valid rows to update." if prep_errors else "Nothing to update.",
            results=[],
            prep_errors=prep_errors,
        )
        return

    total = len(changes)
    set_phase_executing(job_id, total, prep_errors)
    completed = failed = skipped = 0
    results: list[dict] = []

    for i, change in enumerate(changes, 1):
        task_id = change["task_id"]
        mid = change["matter_id"]

        action_label = change.get("action", "")
        if action_label.startswith("NO CHANGE"):
            if "Completed" in action_label:
                skip_reason = "skipped (task is completed)"
            else:
                skip_reason = "skipped (already assigned)"
            results.append({
                "matter_id": mid,
                "task_id": task_id,
                "task_name": change["task_name"],
                "status": skip_reason,
            })
            record_row(job_id, skipped=1)
            skipped += 1
            continue

        # Review-flagged tasks require explicit approval from the Status Review
        # section. If the user didn't check the box, we leave the task untouched.
        if change.get("needs_review") and str(task_id) not in approved:
            results.append({
                "matter_id": mid,
                "task_id": task_id,
                "task_name": change["task_name"],
                "status": f"skipped (status '{change.get('task_status')}' not approved for review)",
            })
            record_row(job_id, skipped=1)
            skipped += 1
            continue

        prior = change.get("previous_assignee")
        try:
            client.patch(f"tasks/{task_id}.json", body=change["patch_body"])
            record_row(
                job_id,
                audit={
                    "username": username,
                    "action": "bulk_reassign_task",
                    "endpoint": "/api/execute/bulk-reassign-tasks",
                    "matter_id": mid,
                    "field_name": "assignee",
                    "before_value": json.dumps(prior, default=str) if prior else None,
                    "after_value": json.dumps(
                        {"id": change["new_assignee_id"], "type": "User"}
                    ),
                    "details": {
                        "task_id": task_id,
                        "task_name": change["task_name"],
                        "display_number": change.get("display_number"),
                        "previous_assignee": prior,
                        "new_assignee": change["new_assignee"],
                    },
                    "batch_id": job_id,
                },
                completed=1,
            )
            results.append({
                "matter_id": mid,
                "task_id": task_id,
                "task_name": change["task_name"],
                "new_assignee": change["new_assignee"],
                "status": "success",
            })
            completed += 1
        except Exception as e:  # noqa: BLE001 -- per-row failure, keep going
            record_row(
                job_id,
                audit={
                    "username": username,
                    "action": "bulk_reassign_task",
                    "endpoint": "/api/execute/bulk-reassign-tasks",
                    "matter_id": mid,
                    "field_name": "assignee",
                    "status": "error",
                    "error_message": str(e),
                    "details": {
                        "task_id": task_id,
                        "task_name": change["task_name"],
                        "display_number": change.get("display_number"),
                    },
                    "batch_id": job_id,
                },
                failed=1,
            )
            results.append({
                "matter_id": mid,
                "task_id": task_id,
                "task_name": change["task_name"],
                "status": "error",
                "error": str(e),
            })
            failed += 1

        if i % _PROGRESS_EVERY == 0:
            touch_message(job_id, f"Processing {i} of {total}…")

    parts = [f"Completed {completed} of {total}"]
    if failed:
        parts.append(f"{failed} failed")
    if skipped:
        parts.append(f"{skipped} skipped")
    finish_job(
        job_id,
        state="ok" if failed == 0 else "error",
        message=", ".join(parts),
        results=results,
        prep_errors=prep_errors,
    )


@router.post("/execute/bulk-reassign-tasks")
def execute_bulk_reassign_tasks(
    file: UploadFile = File(...),
    status_override: bool = Form(default=False),
    approved_task_ids: str = Form(default=""),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Start a background CSV bulk task reassignment.

    Returns immediately and runs the PATCH loop in a background thread so large
    batches aren't capped by Azure's ~230s gateway timeout. One audit row per
    task PATCHed, all sharing the job id as their batch_id. Rows whose task is
    already assigned to the target user, or already complete (without override),
    are skipped. The UI polls ``GET /api/execute/jobs/{job_id}`` for progress.

    When `status_override` is true, completed tasks are reassigned too. The
    override must match the value used at preview time for counts to line up.

    `approved_task_ids` is a comma-separated list of task ids the user explicitly
    approved from the Status Review section; review-flagged tasks are reassigned
    ONLY if their id appears here.
    """
    batch_id = new_batch_id()
    content = file.file.read().decode("utf-8-sig")
    approved: set[str] = {t.strip() for t in approved_task_ids.split(",") if t.strip()}

    create_job(batch_id, "tasks", user.username)
    run_in_thread(
        batch_id,
        lambda: _run_bulk_reassign_tasks(
            batch_id, client, content, user.username,
            status_override=status_override, approved=approved,
        ),
        name="bulk-tasks",
    )
    return {"status": "started", "job_id": batch_id, "batch_id": batch_id}


# ── GET /api/execute/jobs/{job_id} ──────────────────────────────────────────

@router.get("/execute/jobs/{job_id}")
def get_bulk_job_status(job_id: str, user: UserInfo = Depends(require_auth)):
    """Report progress + final results for a background bulk job.

    ``state`` is one of ``running`` | ``ok`` | ``error``. While running, the
    UI reads total/completed/failed/skipped for a live progress bar; once the
    state leaves ``running`` it reads ``results`` for the per-row breakdown.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such job")

    total = job.get("total") or 0
    completed = job.get("completed") or 0
    failed = job.get("failed") or 0
    skipped = job.get("skipped") or 0
    done = completed + failed + skipped
    return {
        "job_id": job["id"],
        "batch_id": job["id"],
        "job_type": job.get("job_type"),
        "state": job.get("state"),
        "phase": job.get("phase"),
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "processed": done,
        "percent": round(done / total * 100) if total else 0,
        "message": job.get("message"),
        "prep_errors": job.get("prep_errors") or [],
        # Only meaningful once finished; empty list while running.
        "results": job.get("results") or [],
        "success": job.get("state") == "ok",
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


def _revert_task_reassignment(client: ClioClient, row: dict) -> dict:
    """Build + send the reverse PATCH for a task-reassignment audit row."""
    details = json.loads(row.get("details") or "{}") if row.get("details") else {}
    task_id = details.get("task_id")
    if task_id is None:
        raise ValueError("audit row is missing task_id; cannot rebuild task revert")

    prior = details.get("previous_assignee")
    if not isinstance(prior, dict) or prior.get("id") is None:
        raise ValueError(
            "task had no prior assignee recorded (it was unassigned); "
            "Clio requires an assignee, so this row must be fixed manually"
        )

    patch_body = {
        "data": {
            "assignee": {"id": prior["id"], "type": prior.get("type") or "User"}
        }
    }
    return client.patch(f"tasks/{task_id}.json", body=patch_body)


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
            elif action == "bulk_reassign_task":
                _revert_task_reassignment(client, row)
                write_audit_log(
                    db,
                    username=user.username,
                    action="revert_bulk_reassign_task",
                    endpoint="/api/execute/revert",
                    matter_id=matter_id,
                    field_name="assignee",
                    before_value=row.get("after_value"),
                    after_value=row.get("before_value"),
                    details={
                        "reverted_audit_id": row.get("id"),
                        "reverted_batch_id": batch_id,
                    },
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
