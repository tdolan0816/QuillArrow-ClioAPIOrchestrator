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
    find_matter_by_display_number,
    VALID_MATTER_FIELDS,
)


def resolve_matter_id(client: ClioClient, matter_id: str | None, display_number: str | None) -> str:
    """
    Resolve a matter_id from either a direct ID or a display_number lookup.

    Exactly one must be provided. If display_number is given, calls
    find_matter_by_display_number (command #5N) to get the real numeric ID.
    """
    mid = (matter_id or "").strip()
    dn = (display_number or "").strip()

    if mid and dn:
        return mid  # matter_id takes priority when both provided

    if dn:
        result = find_matter_by_display_number(client, dn)
        resolved = result.get("data", {}).get("id")
        if not resolved:
            raise ValueError(f"Could not resolve display_number '{dn}' to a matter ID.")
        return str(resolved)

    if mid:
        return mid

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
    cfvs = current.get("data", {}).get("custom_field_values", [])

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


def prepare_bulk_matter_updates(
    client: ClioClient, csv_content: str
) -> tuple[list[dict], list[str]]:
    """
    Prepare bulk matter property updates from CSV content (validation only, no PATCH).

    Returns:
        (changes, errors) where each change dict contains:
            {
                "matter_id": "1830300500",
                "fields_to_update": {"description": "New desc", "status": "Open"},
                "patch_body": {"data": {"description": "New desc", "status": "Open"}}
            }
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    headers = [h.strip() for h in (reader.fieldnames or [])]

    has_matter_id = "matter_id" in headers
    has_display_number = "display_number" in headers
    if not has_matter_id and not has_display_number:
        return [], [f"CSV must have a 'matter_id' or 'display_number' column. Found: {headers}"]

    id_columns = {"matter_id", "display_number"}
    data_headers = [h for h in headers if h not in id_columns]
    invalid = [h for h in data_headers if h not in VALID_MATTER_FIELDS]
    if invalid:
        return [], [f"Invalid matter field names: {invalid}. Valid: {sorted(VALID_MATTER_FIELDS)}"]

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

        data_fields = {}
        for col in data_headers:
            val = (row.get(col) or "").strip()
            if val:
                data_fields[col] = val

        if not data_fields:
            errors.append(f"Row {row_num} (matter {resolved_id}): no fields to update — skipped")
            continue

        changes.append({
            "matter_id": resolved_id,
            "display_number": dn or None,
            "fields_to_update": data_fields,
            "patch_body": {"data": data_fields},
        })

    return changes, errors
