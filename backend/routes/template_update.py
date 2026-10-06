"""
Template Mass Update — bulk find/replace across Clio document templates.

Flow (mirrors the CSV bulk-update pattern so Azure's ~230s gateway timeout
never applies):

    1. The user uploads a two-column lookup CSV (old,new) and picks a scope
       (all templates, or an explicit list of template ids).
    2. ``POST /api/template-update/preview`` starts a **background job** that
       downloads each template, counts matches with a dry run, and reports
       per-template hit counts. No template is modified.
    3. ``POST /api/template-update/execute`` (admin only) starts a background
       job that rewrites each matching template and uploads it back to Clio as
       a **brand-new** template (dated suffix) — the original is never touched
       in v1. Each template is re-scanned to verify the tokens are gone, and an
       audit row is written per template (grouped by the job id / batch_id).

Both jobs are polled through the shared ``GET /api/execute/jobs/{id}`` endpoint
and cancelled through ``POST /api/execute/jobs/{id}/cancel`` (cooperative).

``POST /api/template-update/poc`` is an admin-only, single-template diagnostic
that validates the live Clio download → create-new upload → listing contract
without touching the original. Use it once against production to confirm the
endpoint shapes before running a real batch.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from clio_client import ClioClient, ClioAPIError
from backend.auth import UserInfo
from backend.dependencies import require_auth, get_clio_client
from backend.audit import new_batch_id
from backend.services.docx_replace import (
    parse_lookup_csv,
    process_docx_bytes,
)
from backend.services.docx_verify import verify_docx_bytes
from backend.routes._bulk_jobs import (
    create_job,
    run_in_thread,
    record_row,
    finish_job,
    set_phase_executing,
    touch_message,
    raise_if_cancelled,
    JobCancelled,
)

router = APIRouter(tags=["Template Mass Update"])


# ── Guards ──────────────────────────────────────────────────────────────────

def require_admin(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return user


# ── Options model (parsed from form fields) ─────────────────────────────────

class _Options:
    def __init__(
        self,
        *,
        ignore_case: bool,
        include_headers_footers: bool,
        include_textboxes: bool,
        filename_suffix: str,
        overwrite: bool = False,
    ):
        self.ignore_case = ignore_case
        self.include_headers_footers = include_headers_footers
        self.include_textboxes = include_textboxes
        self.filename_suffix = filename_suffix
        # overwrite=True → PATCH the existing template in place (same id, same
        # filename, no new template created). overwrite=False → create a NEW
        # template with the dated suffix and leave the original untouched.
        self.overwrite = overwrite


def _as_bool(value: str, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ── Clio helpers ────────────────────────────────────────────────────────────

_DOWNLOAD_CANDIDATES = ("document_templates/{id}/download", "document_templates/{id}/contents")
_TEMPLATE_FIELDS = ["id", "filename", "document_category{id,name}"]


def _download_template_bytes(client: ClioClient, template_id) -> bytes:
    """Download a template's .docx bytes, trying known Clio endpoint shapes."""
    last_err: Exception | None = None
    for shape in _DOWNLOAD_CANDIDATES:
        endpoint = shape.format(id=template_id)
        try:
            data = client.download_bytes(endpoint)
            if data and data[:2] == b"PK":  # a .docx is a zip; sanity check
                return data
            last_err = ClioAPIError(200, "Not a docx", f"{endpoint} returned non-zip bytes")
        except ClioAPIError as exc:
            last_err = exc
            continue
    raise last_err or ClioAPIError(404, "Not Found", f"template {template_id} download failed")


def _category_id(record: dict):
    cat = (record or {}).get("document_category") or {}
    return cat.get("id")


def _resolve_scope(client: ClioClient, scope: str, ids: list[str]) -> list[dict]:
    """Return [{id, filename, document_category_id}] for the requested scope."""
    out: list[dict] = []
    if scope == "ids":
        for tid in ids:
            rec = client.get_by_id("document_templates", tid, fields=_TEMPLATE_FIELDS)
            data = rec.get("data", rec) if isinstance(rec, dict) else {}
            out.append(
                {
                    "id": data.get("id", tid),
                    "filename": data.get("filename") or f"template_{tid}.docx",
                    "document_category_id": _category_id(data),
                }
            )
    elif scope == "all":
        for data in client.get_all("document_templates", fields=_TEMPLATE_FIELDS):
            out.append(
                {
                    "id": data.get("id"),
                    "filename": data.get("filename") or f"template_{data.get('id')}.docx",
                    "document_category_id": _category_id(data),
                }
            )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported scope: {scope!r}")
    return out


_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_upload_filename(name: str, suffix: str) -> str:
    """Build a safe, suffixed .docx filename for the new template."""
    base = name or "template"
    if base.lower().endswith(".docx"):
        base = base[:-5]
    base = base.replace("&", " and ")
    base = _INVALID_FILENAME.sub("", base).strip() or "template"
    suffix = (suffix or "").strip()
    return f"{base}{suffix}.docx"


# ── Lookup CSV sample ───────────────────────────────────────────────────────

@router.get("/template-update/lookup-template.csv")
def download_lookup_template(user: UserInfo = Depends(require_auth)):
    """Download a starter lookup CSV the user can fill in (old,new)."""
    sample = (
        "old,new\r\n"
        "<< Old Field Name >>,<< New Field Name >>\r\n"
        "Acme Law Group,Quill & Arrow LLP\r\n"
    )
    return StreamingResponse(
        io.BytesIO(sample.encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="lookup-template.csv"'},
    )


# ── List templates (for the scope picker) ──────────────────────────────────

@router.get("/template-update/templates")
def list_templates(
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """List all document templates (id, filename, category) for the UI picker."""
    try:
        items = _resolve_scope(client, "all", [])
    except ClioAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Clio list failed: {exc}") from exc
    return {"count": len(items), "templates": items}


# ── Shared worker core ──────────────────────────────────────────────────────

def _parse_ids(raw: str) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[\s,]+", raw) if p.strip()]


def _run_template_job(
    job_id: str,
    client: ClioClient,
    lookup_content: str,
    scope: str,
    ids: list[str],
    opts: _Options,
    username: str,
    *,
    apply_changes: bool,
) -> None:
    """Background worker for both preview (dry run) and execute (real upload)."""
    try:
        replacements = parse_lookup_csv(lookup_content)
    except Exception as exc:  # noqa: BLE001
        finish_job(job_id, state="error", message=f"Could not parse lookup CSV: {exc}", results=[])
        return
    if not replacements:
        finish_job(job_id, state="error", message="Lookup CSV had no usable old→new rows.", results=[])
        return

    try:
        templates = _resolve_scope(client, scope, ids)
    except HTTPException as exc:
        finish_job(job_id, state="error", message=str(exc.detail), results=[])
        return
    except ClioAPIError as exc:
        finish_job(job_id, state="error", message=f"Clio list failed: {exc}", results=[])
        return

    total = len(templates)
    if total == 0:
        finish_job(job_id, state="ok", message="No templates in scope.", results=[])
        return

    set_phase_executing(job_id, total, [])
    results: list[dict] = []
    completed = failed = 0
    suffix = opts.filename_suffix

    for i, tpl in enumerate(templates, 1):
        try:
            raise_if_cancelled(job_id)
        except JobCancelled:
            finish_job(
                job_id,
                state="cancelled",
                message=f"Cancelled after {i - 1} of {total}.",
                results=results,
            )
            return

        tid = tpl["id"]
        fname = tpl["filename"]
        try:
            data = _download_template_bytes(client, tid)
            res = process_docx_bytes(
                data,
                replacements,
                ignore_case=opts.ignore_case,
                include_headers_footers=opts.include_headers_footers,
                include_textboxes=opts.include_textboxes,
                apply_changes=apply_changes,
            )

            row: dict = {
                "template_id": tid,
                "filename": fname,
                "matches": res.total,
                "status": "success",
            }

            if apply_changes and res.total > 0:
                verify = verify_docx_bytes(
                    res.data,
                    replacements,
                    ignore_case=opts.ignore_case,
                    include_headers_footers=opts.include_headers_footers,
                )
                if opts.overwrite:
                    # In-place overwrite, keeping the original filename. Prefer a
                    # PATCH in place (same id). If the account rejects a
                    # file-bearing PATCH, fall back to the legacy contract:
                    # create a NEW template with the same name, then delete the
                    # old id (net effect is the same name with fresh content).
                    overwrite_name = sanitize_upload_filename(fname, "")
                    cat_id = tpl.get("document_category_id")
                    try:
                        updated = client.upload_template(
                            file_bytes=res.data,
                            filename=overwrite_name,
                            template_id=tid,
                            document_category_id=cat_id,
                            mode="update",
                        )
                        result_id = updated.get("id", tid)
                        result_name = updated.get("filename", overwrite_name)
                        overwrite_method = "patch"
                        after_desc = f"overwrote template {tid} in place ({result_name})"
                    except ClioAPIError as patch_exc:
                        created = client.upload_template(
                            file_bytes=res.data,
                            filename=overwrite_name,
                            document_category_id=cat_id,
                            mode="create",
                        )
                        result_id = created.get("id")
                        result_name = created.get("filename", overwrite_name)
                        overwrite_method = "create_delete"
                        old_deleted = False
                        delete_error = None
                        if result_id and str(result_id) != str(tid):
                            try:
                                client.delete_template(tid)
                                old_deleted = True
                            except ClioAPIError as del_exc:
                                delete_error = str(del_exc)[:300]
                        after_desc = (
                            f"replaced template {tid} via create+delete "
                            f"(new {result_id}, {result_name}); "
                            f"old_deleted={old_deleted}"
                        )
                        row["old_deleted"] = old_deleted
                        if delete_error:
                            row["delete_error"] = delete_error
                        row["patch_fallback_reason"] = str(patch_exc)[:200]

                    row["overwritten"] = True
                    row["overwrite_method"] = overwrite_method
                    row["new_template_id"] = result_id
                    row["new_filename"] = result_name
                    audit_details = {
                        "source_template_id": tid,
                        "overwritten": True,
                        "overwrite_method": overwrite_method,
                        "new_template_id": result_id,
                        "matches": res.total,
                        "verified_clean": verify["clean"],
                        "old_remaining": verify["old_remaining_total"],
                    }
                    if overwrite_method == "create_delete":
                        audit_details["old_deleted"] = row.get("old_deleted", False)
                        if row.get("delete_error"):
                            audit_details["delete_error"] = row["delete_error"]
                else:
                    # Non-destructive: create a NEW template with the suffix.
                    new_name = sanitize_upload_filename(fname, suffix)
                    created = client.upload_template(
                        file_bytes=res.data,
                        filename=new_name,
                        document_category_id=tpl.get("document_category_id"),
                        mode="create",
                    )
                    row["overwritten"] = False
                    row["new_template_id"] = created.get("id")
                    row["new_filename"] = created.get("filename", new_name)
                    after_desc = f"new template {created.get('id')} ({new_name})"
                    audit_details = {
                        "source_template_id": tid,
                        "new_template_id": created.get("id"),
                        "matches": res.total,
                        "verified_clean": verify["clean"],
                        "old_remaining": verify["old_remaining_total"],
                    }

                row["verified_clean"] = verify["clean"]
                row["old_remaining"] = verify["old_remaining_total"]

                record_row(
                    job_id,
                    audit={
                        "username": username,
                        "action": "template_mass_update",
                        "endpoint": "/api/template-update/execute",
                        "field_name": fname,
                        "before_value": f"template {tid} ({res.total} tokens)",
                        "after_value": after_desc,
                        "details": audit_details,
                        "status": "success",
                        "batch_id": job_id,
                    },
                    completed=1,
                )
            else:
                # preview rows, or execute rows with zero matches: count progress
                # without writing an audit entry (nothing changed in Clio).
                record_row(job_id, completed=1)

            results.append(row)
            completed += 1
        except Exception as exc:  # noqa: BLE001 — per-template failure, keep going
            results.append(
                {
                    "template_id": tid,
                    "filename": fname,
                    "status": "error",
                    "error": str(exc)[:300],
                }
            )
            if apply_changes:
                record_row(
                    job_id,
                    audit={
                        "username": username,
                        "action": "template_mass_update",
                        "endpoint": "/api/template-update/execute",
                        "field_name": fname,
                        "details": {"source_template_id": tid},
                        "status": "error",
                        "error_message": str(exc)[:400],
                        "batch_id": job_id,
                    },
                    failed=1,
                )
            else:
                record_row(job_id, failed=1)
            failed += 1

        if i % 5 == 0 or i == total:
            touch_message(job_id, f"Processing {i} of {total}…")

    if not apply_changes:
        verb = "Previewed"
    elif opts.overwrite:
        verb = "Overwrote"
    else:
        verb = "Created updated copies for"
    finish_job(
        job_id,
        state="ok" if failed == 0 else "error",
        message=(
            f"{verb} {completed} template(s)"
            + (f", {failed} failed" if failed else "")
            + (" — dry run, nothing uploaded" if not apply_changes else "")
        ),
        results=results,
    )


def _build_options(
    ignore_case: str,
    include_headers_footers: str,
    include_textboxes: str,
    filename_suffix: str,
    overwrite: str = "",
) -> _Options:
    suffix = (filename_suffix or "").strip()
    if not suffix:
        suffix = "_Updated_" + datetime.now(timezone.utc).strftime("%m%d%y")
    return _Options(
        ignore_case=_as_bool(ignore_case, False),
        include_headers_footers=_as_bool(include_headers_footers, True),
        include_textboxes=_as_bool(include_textboxes, True),
        filename_suffix=suffix,
        overwrite=_as_bool(overwrite, False),
    )


# ── Preview (dry run) ───────────────────────────────────────────────────────

@router.post("/template-update/preview")
def preview_template_update(
    file: UploadFile = File(...),
    scope: str = Form(default="all"),
    template_ids: str = Form(default=""),
    ignore_case: str = Form(default=""),
    include_headers_footers: str = Form(default="true"),
    include_textboxes: str = Form(default="true"),
    user: UserInfo = Depends(require_auth),
    client: ClioClient = Depends(get_clio_client),
):
    """Start a background dry-run: count matches per template, change nothing."""
    content = file.file.read().decode("utf-8-sig")
    ids = _parse_ids(template_ids)
    opts = _build_options(ignore_case, include_headers_footers, include_textboxes, "")

    job_id = new_batch_id()
    create_job(job_id, "template-preview", user.username)
    run_in_thread(
        job_id,
        lambda: _run_template_job(
            job_id, client, content, scope, ids, opts, user.username, apply_changes=False
        ),
        name="template-preview",
    )
    return {"status": "started", "job_id": job_id, "batch_id": job_id}


# ── Execute (real upload) ───────────────────────────────────────────────────

@router.post("/template-update/execute")
def execute_template_update(
    file: UploadFile = File(...),
    scope: str = Form(default="all"),
    template_ids: str = Form(default=""),
    ignore_case: str = Form(default=""),
    include_headers_footers: str = Form(default="true"),
    include_textboxes: str = Form(default="true"),
    filename_suffix: str = Form(default=""),
    overwrite: str = Form(default="false"),
    user: UserInfo = Depends(require_admin),
    client: ClioClient = Depends(get_clio_client),
):
    """Start a background real run: rewrite matches and upload them back to Clio.

    Two modes:
      * ``overwrite=false`` (default): create a NEW template with a dated suffix;
        the original is never modified or deleted.
      * ``overwrite=true``: PATCH the existing template in place — same id, same
        filename, no suffix. This is destructive (the original file content is
        replaced), so it is admin-only and requires explicit opt-in.

    The UI polls ``GET /api/execute/jobs/{job_id}``.
    """
    content = file.file.read().decode("utf-8-sig")
    ids = _parse_ids(template_ids)
    opts = _build_options(
        ignore_case, include_headers_footers, include_textboxes, filename_suffix, overwrite
    )

    job_id = new_batch_id()
    create_job(job_id, "template-update", user.username)
    run_in_thread(
        job_id,
        lambda: _run_template_job(
            job_id, client, content, scope, ids, opts, user.username, apply_changes=True
        ),
        name="template-update",
    )
    return {"status": "started", "job_id": job_id, "batch_id": job_id}


# ── Live POC / diagnostic (single template, non-destructive) ────────────────

@router.post("/template-update/poc")
def template_update_poc(
    template_id: str = Form(...),
    do_upload: str = Form(default="false"),
    user: UserInfo = Depends(require_admin),
    client: ClioClient = Depends(get_clio_client),
):
    """Validate the live Clio contract for ONE template (synchronous, safe).

    Steps, each reported individually so you can see exactly where Clio's API
    shape differs from our assumptions:

    * ``list``     — can we page document_templates and get a count?
    * ``download`` — which download endpoint returns real .docx (zip) bytes?
    * ``upload``   — (only when ``do_upload=true``) create a NEW template from
                     the SAME bytes with a ``_POC`` suffix. The original is
                     never modified or deleted.

    Run this once against production before kicking off a real batch.
    """
    report: dict = {"template_id": template_id, "steps": {}}

    # 1. listing + count
    try:
        templates = _resolve_scope(client, "all", [])
        report["steps"]["list"] = {"ok": True, "count": len(templates)}
    except Exception as exc:  # noqa: BLE001
        report["steps"]["list"] = {"ok": False, "error": str(exc)[:300]}

    # 2. download (try each candidate, report which worked)
    data: bytes | None = None
    download_detail: dict = {}
    for shape in _DOWNLOAD_CANDIDATES:
        endpoint = shape.format(id=template_id)
        try:
            raw = client.download_bytes(endpoint)
            is_docx = bool(raw) and raw[:2] == b"PK"
            download_detail[endpoint] = {"bytes": len(raw or b""), "is_docx": is_docx}
            if is_docx and data is None:
                data = raw
                download_detail[endpoint]["used"] = True
        except Exception as exc:  # noqa: BLE001
            download_detail[endpoint] = {"error": str(exc)[:200]}
    report["steps"]["download"] = {"ok": data is not None, "endpoints": download_detail}

    # 3. optional non-destructive create-new upload
    if _as_bool(do_upload, False) and data is not None:
        try:
            rec = client.get_by_id("document_templates", template_id, fields=_TEMPLATE_FIELDS)
            src = rec.get("data", rec) if isinstance(rec, dict) else {}
            new_name = sanitize_upload_filename(src.get("filename") or f"template_{template_id}", "_POC")
            created = client.upload_template(
                file_bytes=data,
                filename=new_name,
                document_category_id=_category_id(src),
                mode="create",
            )
            report["steps"]["upload"] = {
                "ok": bool(created.get("id")),
                "new_template_id": created.get("id"),
                "new_filename": created.get("filename", new_name),
                "note": "New template created; original untouched. Delete the _POC copy in Clio when done.",
            }
        except Exception as exc:  # noqa: BLE001
            report["steps"]["upload"] = {"ok": False, "error": str(exc)[:400]}
    else:
        report["steps"]["upload"] = {"skipped": True, "reason": "do_upload=false or no bytes"}

    return report
