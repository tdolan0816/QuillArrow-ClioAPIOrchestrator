"""
CSV template endpoints.

These endpoints return downloadable CSV templates for the bulk-update workflows.
Templates are *generated* on request (not stored on disk or in the DB) so the
header row always matches what the preview/execute endpoints actually accept.
That way the authoritative schema lives in exactly one place (operations.py)
and can never drift from the template users are filling in.

Endpoints:
    GET /api/templates/bulk-update-fields.csv   — header + sample row for bulk CF updates
    GET /api/templates/bulk-update-matters.csv  — header + sample row for bulk matter updates
"""

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from backend.auth import UserInfo
from backend.dependencies import require_auth
from operations import VALID_MATTER_FIELDS, VALID_MATTER_REFERENCE_FIELDS

router = APIRouter(tags=["Templates"])


def _csv_response(filename: str, headers: list[str], sample_rows: list[dict]) -> Response:
    """Return a CSV file as a download, with a UTF-8 BOM so Excel opens it cleanly."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in sample_rows:
        # DictWriter will leave missing keys blank -- exactly what we want for a template.
        writer.writerow(row)
    body = "\ufeff" + buf.getvalue()  # UTF-8 BOM keeps Excel happy with non-ASCII names
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# ── GET /api/templates/bulk-update-fields.csv ────────────────────────────────
@router.get("/templates/bulk-update-fields.csv")
def download_bulk_update_fields_template(user: UserInfo = Depends(require_auth)):
    """
    Template for 'Bulk Update Fields (CSV)'.

    Columns:
      - matter_id          (either this or display_number is required)
      - display_number     (human-friendly matter id, e.g. '00015-Agueros')
      - field_name         (the Clio custom field name to update)
      - value              (the new value; for picklists, the option text)

    A sample row is included so users can see the expected shape. Delete the
    sample row before uploading, or leave it and fix it in place.
    """
    headers = ["matter_id", "display_number", "field_name", "value"]
    sample = [
        {
            "matter_id": "",
            "display_number": "00015-Agueros",
            "field_name": "Vehicle Make",
            "value": "Chevrolet",
        }
    ]
    return _csv_response("bulk_update_fields_template.csv", headers, sample)


# ── GET /api/templates/bulk-update-matters.csv ───────────────────────────────
@router.get("/templates/bulk-update-matters.csv")
def download_bulk_update_matters_template(user: UserInfo = Depends(require_auth)):
    """
    Template for 'Bulk Update Matters (CSV)'.

    Columns:
      - matter_id          (either this or display_number is required)
      - display_number
      - every scalar matter field in VALID_MATTER_FIELDS
      - every user-reference field in VALID_MATTER_REFERENCE_FIELDS
        (responsible_attorney, originating_attorney, responsible_staff)

    Reference fields accept full name, email, or the Clio user id; the backend
    resolves them to `{id: N}` before PATCHing.
    """
    # Scalars first, then references. display_number stays in the identifier slot.
    scalar_cols = sorted(f for f in VALID_MATTER_FIELDS if f != "display_number")
    reference_cols = sorted(VALID_MATTER_REFERENCE_FIELDS)
    headers = ["matter_id", "display_number", *scalar_cols, *reference_cols]

    sample = [
        {
            "matter_id": "",
            "display_number": "00015-Agueros",
            "description": "Updated description",
            "status": "Open",
            # References: full name, email, or Clio user id all work.
            "responsible_attorney": "Jane Doe",
            "originating_attorney": "jdoe@example.com",
            "responsible_staff": "12345678",
        }
    ]
    return _csv_response("bulk_update_matters_template.csv", headers, sample)
