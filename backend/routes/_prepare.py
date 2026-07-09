"""
Shared preparation logic for preview and execute routes.

These functions do all the work of resolving field names, finding value_ids,
validating picklist options, and building PATCH bodies — but they do NOT
send any requests to Clio. The caller (preview or execute) decides what
to do with the prepared data.

Each prepare_* function returns structured dicts describing the changes,
which can be:
    - Returned directly to the user as a preview
    - Fed into execute logic that sends the PATCH and logs the audit entry
"""

import csv
import io

from clio_client import ClioClient
from operations import (
    get_custom_field_lookup,
    VALID_MATTER_FIELDS,
    VALID_MATTER_REFERENCE_FIELDS,
    resolve_user_by_name_or_id,
)


def resolve_matter_id(client: ClioClient, matter_id: str | None, display_number: str | None) -> str:
    """
    Resolve a matter_id from either a direct ID or a display_number lookup.

    At least one must be provided. If display_number is given (without a
    matter_id), searches Clio for an exact match on display_number and
    returns the numeric ID. Uses the same search-then-verify approach as
    command #5N but skips the expensive enrichment step.
    """
    mid = (matter_id or "").strip()
    dn = (display_number or "").strip()

    if mid:
        return mid

    if dn:
        raw = client.get("matters", fields=["id", "display_number"], query=dn)

        # Clio normally returns {"data": [...]}, but handle edge cases
        if isinstance(raw, list):
            matters = raw
        elif isinstance(raw, dict):
            matters = raw.get("data", [])
        else:
            raise ValueError(
                f"Unexpected response type from Clio when searching for '{dn}': {type(raw).__name__}"
            )

        if isinstance(matters, dict):
            matters = [matters]

        for m in matters:
            if not isinstance(m, dict):
                continue
            if m.get("display_number", "").lower() == dn.lower():
                return str(m["id"])

        raise ValueError(
            f"No matter found with display_number '{dn}'. "
            f"Make sure you're using the full display number (e.g. '00015-Agueros')."
        )

    raise ValueError("Either matter_id or display_number must be provided.")


def prepare_custom_field_update(
    client: ClioClient,
    matter_id: str,
    field_name: str,
    value: str,
    display_number: str | None = None,
) -> dict:
    """
    Prepare a single custom field update (steps 1-5, no PATCH).

    Returns a dict describing the change:
        {
            "matter_id": "1830300500",
            "field_name": "Vehicle Year",
            "field_def_id": 21836420,
            "field_type": "numeric",
            "value_id": "numeric-182750525",
            "current_value": 2020,
            "new_value": "2025",
            "resolved_value": "2025",   (or option_id for picklists)
            "action": "UPDATE",         (or "CREATE" if field was empty)
            "patch_body": {...}          (the exact JSON that would be sent)
        }

    Raises ValueError if the field name is invalid, picklist option not found, etc.
    """
    # Step 0: Resolve matter_id from display_number if needed
    matter_id = resolve_matter_id(client, matter_id, display_number)

    # Step 1: Resolve field name -> field_def_id
    cf_lookup = get_custom_field_lookup(client)
    field_def_id = None
    for fid, fdef in cf_lookup.items():
        if fdef["name"] and fdef["name"].lower() == field_name.lower():
            field_def_id = fid
            break

    if field_def_id is None:
        raise ValueError(f"Custom field '{field_name}' not found in Clio field definitions.")

    field_type = cf_lookup[field_def_id].get("field_type", "unknown")

    # Step 2: GET this matter's current custom field values
    endpoint = f"matters/{matter_id}?fields=id,custom_field_values{{id,value,custom_field}}"
    current = client._request("GET", endpoint)

    if isinstance(current, list):
        current_data = current[0] if current else {}
    elif isinstance(current, dict):
        current_data = current.get("data", {})
    else:
        raise ValueError(f"Unexpected response from Clio for matter {matter_id}: {type(current).__name__}")

    if isinstance(current_data, list):
        current_data = current_data[0] if current_data else {}

    cfvs = current_data.get("custom_field_values", []) if isinstance(current_data, dict) else []

    # Step 3: Find existing value_id and current value
    existing_value_id = None
    current_value = None
    for cfv in cfvs:
        cf_ref = cfv.get("custom_field", {})
        if cf_ref.get("id") == field_def_id:
            existing_value_id = cfv.get("id")
            current_value = cfv.get("value")
            break

    # Step 4: Resolve picklist values
    resolved_value = value
    if field_type == "picklist":
        field_def = client.get(f"custom_fields/{field_def_id}", fields=["id", "picklist_options"])
        options = field_def.get("data", {}).get("picklist_options", [])

        matched_option = None
        for opt in options:
            if str(opt.get("option", "")).lower() == str(value).lower():
                matched_option = opt
                break

        if matched_option:
            resolved_value = matched_option["id"]
        else:
            available = [opt.get("option") for opt in options]
            raise ValueError(
                f"Picklist value '{value}' not found for field '{field_name}'. "
                f"Available options: {available}"
            )

    # Step 5: Build PATCH body
    cf_entry = {"custom_field": {"id": field_def_id}, "value": resolved_value}
    if existing_value_id:
        cf_entry["id"] = existing_value_id

    patch_body = {"data": {"custom_field_values": [cf_entry]}}

    return {
        "matter_id": str(matter_id),
        "field_name": field_name,
        "field_def_id": field_def_id,
        "field_type": field_type,
        "value_id": existing_value_id,
        "current_value": current_value,
        "new_value": value,
        "resolved_value": resolved_value,
        "action": "UPDATE" if existing_value_id else "CREATE",
        "patch_body": patch_body,
    }


def prepare_bulk_custom_field_updates(
    client: ClioClient, csv_content: str, field_name: str | None = None
) -> tuple[list[dict], list[str]]:
    """
    Prepare bulk custom field updates from CSV content (steps 1-5 per row, no PATCH).

    Returns:
        (changes, errors) where:
            changes = list of prepared change dicts (same format as prepare_custom_field_update)
            errors  = list of error message strings for rows that failed preparation
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    headers = reader.fieldnames or []

    has_matter_id = "matter_id" in headers
    has_display_number = "display_number" in headers
    if not has_matter_id and not has_display_number:
        return [], [f"CSV must have a 'matter_id' or 'display_number' column. Found: {headers}"]
    if "value" not in headers:
        return [], [f"CSV missing required 'value' column. Found: {headers}"]
    if not field_name and "field_name" not in headers:
        return [], [
            f"CSV missing 'field_name' column and no field name provided. Found: {headers}"
        ]

    changes = []
    errors = []

    for row_num, row in enumerate(reader, start=2):
        mid = (row.get("matter_id") or "").strip() if has_matter_id else ""
        dn = (row.get("display_number") or "").strip() if has_display_number else ""
        fname = field_name or (row.get("field_name") or "").strip()
        val = (row.get("value") or "").strip()

        if (not mid and not dn) or not fname or not val:
            errors.append(f"Row {row_num}: missing identifier (matter_id or display_number), field_name, or value — skipped")
            continue

        try:
            change = prepare_custom_field_update(client, mid or None, fname, val, display_number=dn or None)
            changes.append(change)
        except Exception as e:
            identifier = mid or dn
            errors.append(f"Row {row_num} (matter {identifier}, field '{fname}'): {e}")

    return changes, errors


def _find_tasks_for_matter(client: ClioClient, matter_id: str, task_name: str) -> list[dict]:
    """Return every task in a matter whose name matches (case-insensitive).

    Multiple tasks can share a name within one matter; the caller reassigns
    all of them and reports each separately. Paginates automatically.
    """
    needle = task_name.strip().lower()
    matches = []
    for task in client.get_all(
        "tasks",
        fields=["id", "name", "status", "assignee{id,name,type}"],
        matter_id=matter_id,
    ):
        if (task.get("name") or "").strip().lower() == needle:
            matches.append(task)
    return matches


def prepare_bulk_task_reassignments(
    client: ClioClient, csv_content: str, status_override: bool = False
) -> tuple[list[dict], list[str]]:
    """
    Prepare bulk task reassignments from CSV content (lookups only, no PATCH).

    CSV columns:
        matter_display_number  — e.g. '00015-Agueros' (or a 'matter_id' column)
        task_name              — exact task name, case-insensitive
        new_assignee_name      — Clio user full name, email, or user id

    One CSV row can expand to MULTIPLE change dicts when several tasks in the
    matter share the same name — each task is reassigned and audited separately.

    Task status rules (a Clio task can be pending / in_progress / in_review /
    complete / draft):
      - Default (status_override=False):
          * complete -> blocked ("NO CHANGE (Task is Completed)")
          * every other status  -> reassigned normally
      - status_override=True: every status rule is disregarded and all tasks
        are reassigned per the CSV (including complete). The only remaining
        no-op is a task already assigned to the target user.

    Returns (changes, errors); each change dict:
        {
            "matter_id": "1830300500",
            "display_number": "00015-Agueros",
            "task_id": 987654,
            "task_name": "Send Demand Letter",
            "task_status": "pending",
            "current_assignee": "Jane Doe" | "unassigned",
            "new_assignee": "John Smith (id: 123)",
            "action": "REASSIGN" | "REASSIGN (Status Override)" | "NO CHANGE (...)",
            "previous_assignee": {"id": 99, "name": "Jane Doe", "type": "User"} | None,
            "new_assignee_id": 123,
            "patch_body": {"data": {"assignee": {"id": 123, "type": "User"}}},
        }
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    headers = [h.strip() for h in (reader.fieldnames or [])]

    has_dn = "matter_display_number" in headers or "display_number" in headers
    has_mid = "matter_id" in headers
    if not has_dn and not has_mid:
        return [], [
            "CSV must have a 'matter_display_number' (or 'matter_id') column. "
            f"Found: {headers}"
        ]
    if "task_name" not in headers:
        return [], [f"CSV missing required 'task_name' column. Found: {headers}"]
    if "new_assignee_name" not in headers:
        return [], [f"CSV missing required 'new_assignee_name' column. Found: {headers}"]

    changes: list[dict] = []
    errors: list[str] = []
    # Cache lookups within one upload: the same matter or assignee often
    # repeats across many rows (e.g. reassigning 50 tasks to one paralegal).
    matter_cache: dict[str, str] = {}
    user_cache: dict[str, tuple[int, str]] = {}

    for row_num, row in enumerate(reader, start=2):
        dn = (
            (row.get("matter_display_number") or row.get("display_number") or "").strip()
        )
        mid = (row.get("matter_id") or "").strip() if has_mid else ""
        task_name = (row.get("task_name") or "").strip()
        assignee_raw = (row.get("new_assignee_name") or "").strip()

        if (not dn and not mid) or not task_name or not assignee_raw:
            errors.append(
                f"Row {row_num}: missing matter identifier, task_name, or "
                "new_assignee_name — skipped"
            )
            continue

        # 1. Matter → id
        try:
            cache_key = mid or dn.lower()
            if cache_key in matter_cache:
                resolved_id = matter_cache[cache_key]
            else:
                resolved_id = resolve_matter_id(client, mid or None, dn or None)
                matter_cache[cache_key] = resolved_id
        except Exception as e:
            errors.append(f"Row {row_num} (matter {mid or dn}): {e}")
            continue

        # 2. New assignee → user id
        try:
            ukey = assignee_raw.lower()
            if ukey in user_cache:
                user_id, user_name = user_cache[ukey]
            else:
                user_id, user_name, candidates = resolve_user_by_name_or_id(
                    client, assignee_raw
                )
                if user_id is None:
                    if candidates:
                        cand_desc = [
                            f"{c.get('name')} ({c.get('email') or 'no email'})"
                            for c in candidates
                        ]
                        errors.append(
                            f"Row {row_num} (matter {dn or resolved_id}): "
                            f"'{assignee_raw}' matched multiple users: {cand_desc}. "
                            "Use the Clio user ID or a more specific value."
                        )
                    else:
                        errors.append(
                            f"Row {row_num} (matter {dn or resolved_id}): no Clio "
                            f"user matches '{assignee_raw}' — row skipped."
                        )
                    continue
                user_cache[ukey] = (user_id, user_name)
        except Exception as e:
            errors.append(f"Row {row_num} (assignee '{assignee_raw}'): {e}")
            continue

        # 3. Task name → task(s) within the matter
        try:
            tasks = _find_tasks_for_matter(client, resolved_id, task_name)
        except Exception as e:
            errors.append(f"Row {row_num} (matter {dn or resolved_id}): {e}")
            continue
        if not tasks:
            errors.append(
                f"Row {row_num}: no task named '{task_name}' found in matter "
                f"{dn or resolved_id} — skipped."
            )
            continue

        # 4. One change per matching task
        for task in tasks:
            prior = task.get("assignee") or None
            # Clio task status is one of pending / in_progress / in_review /
            # complete / draft. Completed tasks are locked from reassignment as
            # a firm-side safety rule -- UNLESS the caller passes status_override,
            # in which case every status rule is disregarded per the CSV.
            status_raw = (task.get("status") or "").strip().lower()
            is_completed = status_raw in ("complete", "completed", "done")
            already = (
                isinstance(prior, dict)
                and prior.get("id") == user_id
                and (prior.get("type") or "User") == "User"
            )
            is_pending = status_raw == "pending"
            needs_review = False
            if already:
                # An identical assignment is always a no-op, override or not.
                action = "NO CHANGE (Already Assigned)"
            elif status_override:
                # Override disregards every status rule and reassigns per the CSV.
                action = "REASSIGN (Status Override)" if is_completed else "REASSIGN"
            elif is_completed:
                action = "NO CHANGE (Task is Completed)"
            elif is_pending:
                action = "REASSIGN"
            else:
                # Any status that isn't pending or complete (in_progress,
                # in_review, draft, or anything unexpected) is held for explicit
                # user review rather than reassigned automatically.
                action = f"REVIEW ({status_raw or 'unknown status'})"
                needs_review = True
            changes.append({
                "matter_id": resolved_id,
                "display_number": dn or None,
                "task_id": task["id"],
                "task_name": task.get("name"),
                "task_status": task.get("status"),
                "current_assignee": (prior or {}).get("name") or "unassigned",
                "new_assignee": f"{user_name} (id: {user_id})",
                "action": action,
                "needs_review": needs_review,
                "previous_assignee": (
                    {
                        "id": prior.get("id"),
                        "name": prior.get("name"),
                        "type": prior.get("type") or "User",
                    }
                    if isinstance(prior, dict) and prior.get("id") is not None
                    else None
                ),
                "new_assignee_id": user_id,
                "patch_body": {"data": {"assignee": {"id": user_id, "type": "User"}}},
            })
    
    return changes, errors


def _fetch_matter_for_previous_values(client: ClioClient, matter_id: str, columns: list[str]) -> dict:
    """
    Fetch a matter's current top-level values so the executor can audit both sides
    of the change. This lets the Revert feature restore prior values exactly, even
    for reference fields where we need the *old user id*, not just the old name.
    """
    if not columns:
        return {}
    # Always request id + each requested column. Reference fields need {id,name}.
    parts = ["id"]
    for col in columns:
        if col in VALID_MATTER_REFERENCE_FIELDS:
            parts.append(f"{col}{{id,name}}")
        else:
            parts.append(col)
    endpoint = f"matters/{matter_id}?fields={','.join(parts)}"
    resp = client._request("GET", endpoint)
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


def prepare_bulk_matter_updates(
    client: ClioClient, csv_content: str
) -> tuple[list[dict], list[str]]:
    """
    Prepare bulk matter property updates from CSV content (validation only, no PATCH).

    Scalar fields (see VALID_MATTER_FIELDS) are passed through as-is. Reference fields
    (see VALID_MATTER_REFERENCE_FIELDS -- responsible_attorney, etc.) are resolved
    from text to a Clio user id; ambiguous or missing matches are reported as per-row
    errors and the row is skipped rather than PATCHed with a wrong value.

    Returns:
        (changes, errors) where each change dict contains:
            {
                "matter_id": "1830300500",
                "display_number": "00015-Agueros" | None,
                "fields_to_update":     # human-readable, for the preview UI
                    {"description": "New desc", "responsible_attorney": "Jane Doe (id: 123)"},
                "patch_body":           # what is actually sent to Clio
                    {"data": {"description": "New desc", "responsible_attorney": {"id": 123}}},
                "previous_values":      # for audit + revert (scalars are strings; refs are {id,name}/None)
                    {"description": "Old desc", "responsible_attorney": {"id": 99, "name": "Old Attorney"}}
            }
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    headers = [h.strip() for h in (reader.fieldnames or [])]

    has_matter_id = "matter_id" in headers
    has_display_number = "display_number" in headers
    if not has_matter_id and not has_display_number:
        return [], [f"CSV must have a 'matter_id' or 'display_number' column. Found: {headers}"]

    id_columns = {"matter_id", "display_number"}
    all_valid_fields = VALID_MATTER_FIELDS | VALID_MATTER_REFERENCE_FIELDS
    data_headers = [h for h in headers if h not in id_columns]
    invalid = [h for h in data_headers if h not in all_valid_fields]
    if invalid:
        return [], [
            f"Invalid matter field names: {invalid}. "
            f"Valid: {sorted(all_valid_fields)}"
        ]

    changes = []
    errors = []

    for row_num, row in enumerate(reader, start=2):
        mid = (row.get("matter_id") or "").strip() if has_matter_id else ""
        dn = (row.get("display_number") or "").strip() if has_display_number else ""

        if not mid and not dn:
            errors.append(f"Row {row_num}: missing matter_id or display_number — skipped")
            continue

        # Resolve display_number to matter_id if needed
        try:
            resolved_id = resolve_matter_id(client, mid or None, dn or None)
        except Exception as e:
            identifier = mid or dn
            errors.append(f"Row {row_num} (matter {identifier}): {e}")
            continue

        # Split display_fields (for preview) from patch_fields (for Clio).
        display_fields: dict = {}
        patch_fields: dict = {}
        row_errors: list[str] = []

        for col in data_headers:
            val = (row.get(col) or "").strip()
            if not val:
                continue

            if col in VALID_MATTER_REFERENCE_FIELDS:
                user_id, user_name, candidates = resolve_user_by_name_or_id(client, val)
                if user_id is None:
                    if candidates:
                        cand_desc = [
                            f"{c.get('name')} ({c.get('email') or 'no email'})" for c in candidates
                        ]
                        row_errors.append(
                            f"Row {row_num} (matter {resolved_id}): '{val}' for '{col}' "
                            f"matched multiple users: {cand_desc}. Use the Clio user ID or a more specific value."
                        )
                    else:
                        row_errors.append(
                            f"Row {row_num} (matter {resolved_id}): no Clio user matches '{val}' "
                            f"for '{col}' -- row skipped."
                        )
                    continue
                display_fields[col] = f"{user_name} (id: {user_id})"
                patch_fields[col] = {"id": user_id}
            else:
                display_fields[col] = val
                patch_fields[col] = val

        if row_errors:
            errors.extend(row_errors)
            continue
        if not patch_fields:
            errors.append(f"Row {row_num} (matter {resolved_id}): no fields to update — skipped")
            continue

        # Capture prior state for audit/revert. Never fatal -- if Clio doesn't
        # return this matter we still proceed, but the row won't be revertible.
        previous_values: dict = {}
        try:
            matter_before = _fetch_matter_for_previous_values(
                client, resolved_id, list(patch_fields.keys())
            )
            for col in patch_fields.keys():
                if col in VALID_MATTER_REFERENCE_FIELDS:
                    prior = matter_before.get(col) or None
                    if isinstance(prior, dict) and prior.get("id") is not None:
                        previous_values[col] = {
                            "id": prior.get("id"),
                            "name": prior.get("name"),
                        }
                    else:
                        previous_values[col] = None
                else:
                    previous_values[col] = matter_before.get(col)
        except Exception as e:
            errors.append(
                f"Row {row_num} (matter {resolved_id}): could not capture prior values "
                f"(revert won't be available for this row): {e}"
            )

        changes.append({
            "matter_id": resolved_id,
            "display_number": dn or None,
            "fields_to_update": display_fields,
            "patch_body": {"data": patch_fields},
            "previous_values": previous_values,
        })

    return changes, errors
