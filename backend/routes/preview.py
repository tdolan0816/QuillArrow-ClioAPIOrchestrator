"""
Preview (Dry Run) endpoints.

These endpoints run all the preparation steps (resolve field names, find
value_ids, validate picklist options) WITHOUT actually sending any PATCH
requests to Clio. They return exactly what WOULD change.

Endpoints:
    POST /api/preview/update-field          — preview a single custom field update
    POST /api/preview/bulk-update-fields    — preview CSV bulk custom field updates
    POST /api/preview/bulk-update-matters   — preview CSV bulk matter property updates
    POST /api/preview/bulk-reassign-tasks   — preview CSV bulk task reassignments
"""

import csv
import io
import sqlite3

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from clio_client import ClioClient
from backend.auth import UserInfo
from backend.audit import new_batch_id
from backend.dependencies import require_auth, get_clio_client
from backend.routes._prepare import (
    prepare_custom_field_update,
    prepare_bulk_custom_field_updates,
    prepare_bulk_matter_updates,
    prepare_bulk_task_reassignments,
)
from backend.routes._bulk_jobs import (
    create_job,
    update_progress,
    finish_job,
    run_in_thread,
)

router = APIRouter(tags=["Preview (Dry Run)"])

# Throttle preview progress DB writes: update the job row at most once every
# this many CSV rows (plus a final update at the end). Keeps a 1,000-row
# preview from generating 1,000 extra DB writes just for the progress bar.
_PREVIEW_PROGRESS_EVERY = 10


def _make_preview_progress_cb(job_id: str):
    """Return a progress callback that throttles updates to the job row."""
    def _cb(processed: int, total: int) -> None:
        if processed == 0:
            update_progress(
                job_id, processed=0, total=total, phase="executing",
                message=f"Validating 0 of {total}…",
            )
        elif processed >= total or processed % _PREVIEW_PROGRESS_EVERY == 0:
            update_progress(
                job_id, processed=processed, total=total, phase="executing",
                message=f"Validating {processed} of {total}…",
            )
    return _cb


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

# ── Background preview workers ───────────────────────────────────────────────
# Preparation makes one (or more) Clio API call per CSV row, so at 100+ rows a
# synchronous preview blows past Azure's ~230s gateway timeout — the same wall
# the execute step hit. Previews therefore run as background jobs too: the POST
# returns a job_id immediately and the UI polls GET /api/execute/jobs/{id}.
# When the job finishes, its ``results`` hold the prepared changes and its
# ``prep_errors`` hold any per-row issues.

def _run_preview_fields(job_id: str, client: ClioClient, content: str, field_name):
    changes, errors = prepare_bulk_custom_field_updates(
        client, content, field_name=field_name, progress_cb=_make_preview_progress_cb(job_id)
    )
    finish_job(
        job_id, state="ok",
        message=f"Preview ready — {len(changes)} change(s)",
        results=changes, prep_errors=errors,
    )


def _run_preview_matters(job_id: str, client: ClioClient, content: str):
    changes, errors = prepare_bulk_matter_updates(
        client, content, progress_cb=_make_preview_progress_cb(job_id)
    )
    finish_job(
        job_id, state="ok",
        message=f"Preview ready — {len(changes)} change(s)",
        results=changes, prep_errors=errors,
    )


def _run_preview_tasks(job_id: str, client: ClioClient, content: str, status_override: bool):
    changes, errors = prepare_bulk_task_reassignments(
        client, content, status_override=status_override,
        progress_cb=_make_preview_progress_cb(job_id),
    )
    finish_job(
        job_id, state="ok",
        message=f"Preview ready — {len(changes)} change(s)",
        results=changes, prep_errors=errors,
    )


@router.post("/preview/bulk-update-fields")
def preview_bulk_update_fields(
    file: UploadFile = File(..., description="CSV file with columns: matter_id, field_name, value"),
    field_name: str = Form(default="", description="Optional: apply this field name to all rows"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Start a background dry run of a CSV bulk custom-field update.

    Returns a ``job_id`` immediately; the UI polls GET /api/execute/jobs/{id}
    and renders the preview from the finished job's ``results``. No PATCH is
    ever sent — this only validates and resolves the rows.
    """
    content = file.file.read().decode("utf-8-sig")
    fname = field_name.strip() if field_name.strip() else None
    job_id = new_batch_id()
    create_job(job_id, "fields-preview", user.username)
    run_in_thread(
        job_id,
        lambda: _run_preview_fields(job_id, client, content, fname),
        name="preview-fields",
    )
    return {"status": "started", "job_id": job_id}


# ── POST /api/preview/bulk-update-matters ────────────────────────────────────

@router.post("/preview/bulk-update-matters")
def preview_bulk_update_matters(
    file: UploadFile = File(..., description="CSV file with columns: matter_id, plus matter field columns"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Start a background dry run of a CSV bulk matter-property update.

    Returns a ``job_id`` immediately; the UI polls GET /api/execute/jobs/{id}.
    This is the slowest preview (a Clio matter lookup + prior-value fetch per
    row) which is exactly why it can no longer run inline. No PATCH is sent.
    """
    content = file.file.read().decode("utf-8-sig")
    job_id = new_batch_id()
    create_job(job_id, "matters-preview", user.username)
    run_in_thread(
        job_id,
        lambda: _run_preview_matters(job_id, client, content),
        name="preview-matters",
    )
    return {"status": "started", "job_id": job_id}


# ── POST /api/preview/bulk-reassign-tasks ────────────────────────────────────

@router.post("/preview/bulk-reassign-tasks")
def preview_bulk_reassign_tasks(
    file: UploadFile = File(..., description="CSV with columns: matter_display_number, task_name, new_assignee_name"),
    status_override: bool = Form(default=False, description="If true, disregard task status rules (incl. completed) and reassign every task per the CSV"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """
    Start a background dry run of a CSV bulk task reassignment.

    Returns a ``job_id`` immediately; the UI polls GET /api/execute/jobs/{id}.
    A CSV row can expand into multiple preview rows when several tasks in the
    matter share the same name. No PATCH is sent.

    When `status_override` is true, completed tasks are reassigned too; the
    only remaining no-op is a task already assigned to the target user.
    """
    content = file.file.read().decode("utf-8-sig")
    job_id = new_batch_id()
    create_job(job_id, "tasks-preview", user.username)
    run_in_thread(
        job_id,
        lambda: _run_preview_tasks(job_id, client, content, status_override),
        name="preview-tasks",
    )
    return {"status": "started", "job_id": job_id}
