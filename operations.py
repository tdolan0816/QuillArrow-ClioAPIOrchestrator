"""
Pre-built operations for common Clio Manage API tasks.

Each function takes a ClioClient instance and any parameters it needs.
Add new operations here as your project grows.
"""

import csv
import json
from pathlib import Path

from clio_client import ClioClient


# ── Custom Field Definition Cache ────────────────────────────────────────────
# Clio only supports single-level nesting in the fields parameter, so we can't
# get custom_field{id,name,field_type} inside custom_field_values in one call.
# Instead we fetch the field definitions once and cache them as a lookup table.

# Cache the custom field definitions.
_custom_field_cache: dict[int, dict] | None = None

# Get the custom field lookup.
def get_custom_field_lookup(client: ClioClient) -> dict[int, dict]:
    """
    Fetch all Matter custom field definitions and return a dict keyed by ID.

    Cached after the first call so subsequent matter lookups don't repeat it.
    Result format: {field_id: {"name": "...", "field_type": "...", "parent_type": "..."}}
    """
    # Check if the custom field cache is not None.
    global _custom_field_cache
    if _custom_field_cache is not None:
        # Return the custom field cache.
        return _custom_field_cache
    # Print a message to the console.
    print("  Loading custom field definitions (one-time)...")

    # Get all the custom field definitions.
    all_fields = list(client.get_all("custom_fields", fields=["id", "name", "field_type", "parent_type"], parent_type="Matter"))
    # Print a message to the console.
    print(f"  Loaded {len(all_fields)} custom field definitions.")
    
    # Set the custom field cache.
    _custom_field_cache = {
        cf["id"]: {"name": cf.get("name"), "field_type": cf.get("field_type"), "parent_type": cf.get("parent_type")}
        for cf in all_fields
    }
    # Print a message to the console.
    print(f"  Cached {len(_custom_field_cache)} matter custom field definitions.")
    return _custom_field_cache

# Clear the custom field cache.
def clear_custom_field_cache():
    """Clear the custom field cache."""
    global _custom_field_cache
    _custom_field_cache = None
    # Print a message to the console.
    print("  Custom field cache cleared.")

# ── READ operations ──────────────────────────────────────────────────────────

# List matters.
def list_matters(client: ClioClient, fields=None, limit=10):
    """List matters with chosen fields."""
    fields = fields or ["id", "display_number", "description", "status"]
    return client.get("matters", fields=fields, limit=limit)

# Get a single matter by ID.
def get_matter(client: ClioClient, matter_id, fields=None):
    """
    Get a single matter by ID with fully resolved custom field values.

    Two-call strategy (Clio only supports single-level field nesting):
      Call 1: GET matters/{id} with custom_field_values{id,value,custom_field}
              Returns each value + its custom_field.id (the field definition ID)
      Call 2: GET custom_fields (cached) to get field name, type for each ID

    The results are joined in Python so each custom_field_value includes
    the field name and type inline.
    """
    if fields:
        return client.get_by_id("matters", matter_id, fields=fields)

    # Call 1: matter + custom field values with single-level nesting
    endpoint = (
        f"matters/{matter_id}"
        f"?fields=id,display_number,description,status,"
        f"custom_field_values{{id,value,custom_field}}"
    )
    matter_data = client._request("GET", endpoint)

    # Call 2: custom field definitions (cached after first call)
    cf_lookup = get_custom_field_lookup(client)

    # Join: enrich each custom_field_value with the field name and type,
    # and relabel the two different ID types for clarity:
    #   "value_id"      = the custom_field_values ID (unique per matter+field)
    #   "field_def_id"  = the custom_fields definition ID (shared across matters)
    for cfv in matter_data.get("data", {}).get("custom_field_values", []):
        cfv["value_id"] = cfv.pop("id", None)

        cf_ref = cfv.get("custom_field", {})
        cf_id = cf_ref.get("id")
        if cf_id is not None:
            cf_ref["field_def_id"] = cf_ref.pop("id")
            cf_ref.pop("etag", None)
            if cf_id in cf_lookup:
                cf_ref["name"] = cf_lookup[cf_id]["name"]
                cf_ref["field_type"] = cf_lookup[cf_id]["field_type"]

    return matter_data


# List contacts.
def list_contacts(client: ClioClient, fields=None, limit=10):
    """List contacts."""
    fields = fields or ["id", "name", "type", "primary_email_address"]
    return client.get("contacts", fields=fields, limit=limit)

# List custom fields.
def list_custom_fields(client: ClioClient, fields=None, limit=10, parent_type=None):
    """
    List custom fields.

    parent_type filters by entity: "Matter", "Contact", "Activity", etc.
    Without it, returns ALL custom fields across all entity types --
    which is why you may see more than what's visible on matters alone.
    """
    # Set the fields for the custom fields.
    fields = fields or ["id", "name", "field_type", "parent_type"]
    # Set the extra parameters for the custom fields.
    extra = {}
    if parent_type:
        # Set the parent type for the custom fields.
        extra["parent_type"] = parent_type
    # Return the custom fields.
    return client.get("custom_fields", fields=fields, limit=limit, **extra)


# List document templates.
def list_document_templates(client: ClioClient, fields=None, limit=10):
    """List document templates."""
    # Set the fields for the document templates.
    fields = fields or ["id", "filename"]
    # Return the document templates.
    return client.get("document_templates", fields=fields, limit=limit)


# Paginate through ALL matters (can be thousands).
def get_all_matters(client: ClioClient, fields=None):
    """Paginate through ALL matters (can be thousands)."""
    # Set the fields for the matters.
    fields = fields or ["id", "display_number", "description", "status"]
    # Return the matters.
    return list(client.get_all("matters", fields=fields))


# ── UPDATE operations ────────────────────────────────────────────────────────

# Update a single matter.
def update_matter(client: ClioClient, matter_id, updates: dict):
    """
    Update a single matter.

    Example updates dict:
        {"data": {"description": "New description here"}}
    """
    # Update the matter by ID.
    return client.update_by_id("matters", matter_id, body=updates)


def update_custom_field_value(client: ClioClient, matter_id, field_name, value):
    """
    Update a custom field on a matter by field NAME.

    User-facing inputs:
      - matter_id:  which matter (e.g. 1830300500)
      - field_name: the custom field name (e.g. "Vehicle Year")
      - value:      the new value to set

    Behind the scenes this resolves the field_name to the correct value_id
    by fetching the matter's custom field values + the cached field definitions.

    Per Clio API docs (Matters > CustomFieldValues > Update):
      UPDATE existing: PATCH matters/{id}.json with {"id": value_id, "value": new_val}
      CREATE new:      PATCH matters/{id}.json with {"custom_field": {"id": field_def_id}, "value": val}
    """
    log_path = Path("debug_cf_update.log")
    print(f"  [DEBUG] update_custom_field_value called:")
    print(f"          matter_id={matter_id}, field_name='{field_name}', new_value={value}")

    # Step 1: Get the custom field definitions to resolve name -> field_def_id
    cf_lookup = get_custom_field_lookup(client)
    field_def_id = None
    for fid, fdef in cf_lookup.items():
        if fdef["name"] and fdef["name"].lower() == field_name.lower():
            field_def_id = fid
            break

    if field_def_id is None:
        _write_log(log_path, {
            "stage": "NAME_NOT_FOUND",
            "field_name": field_name,
        })
        raise ValueError(
            f"Custom field '{field_name}' not found in Clio field definitions. "
            f"Check the exact spelling (use option 3M to list all matter fields)."
        )

    print(f"  [DEBUG] Step 1 - Resolved '{field_name}' -> field_def_id={field_def_id}")

    # Step 2: GET this matter's custom_field_values to find the value_id
    endpoint = f"matters/{matter_id}?fields=id,custom_field_values{{id,value,custom_field}}"
    print(f"  [DEBUG] Step 2 - GET {endpoint}")

    try:
        current = client._request("GET", endpoint)
    except Exception as get_err:
        _write_log(log_path, {
            "stage": "GET_FAILED", "matter_id": matter_id, "error": str(get_err),
        })
        raise RuntimeError(
            f"GET custom_field_values failed for matter {matter_id}: {get_err}"
        ) from get_err

    cfvs = current.get("data", {}).get("custom_field_values", [])
    print(f"  [DEBUG] Step 2 - Got {len(cfvs)} custom_field_values on this matter")

    _write_log(log_path, {
        "stage": "GET_OK",
        "matter_id": matter_id,
        "field_name": field_name,
        "field_def_id": field_def_id,
        "total_cfv_returned": len(cfvs),
    })

    # Step 3: Find the existing value_id for this field_def_id
    existing_value_id = None
    for cfv in cfvs:
        cf_ref = cfv.get("custom_field", {})
        if cf_ref.get("id") == field_def_id:
            existing_value_id = cfv.get("id")
            break

    field_type = cf_lookup.get(field_def_id, {}).get("field_type", "unknown")
    print(f"  [DEBUG] Step 3 - value_id: {existing_value_id or 'NONE (will create new)'}")
    print(f"  [DEBUG] Step 3 - field_type: {field_type}")

    # Step 4: Resolve the value for picklist fields.
    # Picklist/dropdown fields require the numeric OPTION ID, not the text.
    # e.g., "ALAMEDA" must be sent as 12315410. We fetch the picklist options
    # from the field definition and match the user's text to an option.
    resolved_value = value
    if field_type == "picklist":
        print(f"  [DEBUG] Step 4 - Picklist detected, fetching options for field {field_def_id}...")
        field_def = client.get(f"custom_fields/{field_def_id}", fields=["id", "picklist_options"])
        options = field_def.get("data", {}).get("picklist_options", [])

        _write_log(log_path, {
            "stage": "PICKLIST_OPTIONS",
            "field_def_id": field_def_id,
            "options": options,
            "user_value": value,
        })

        matched_option = None
        for opt in options:
            if str(opt.get("option", "")).lower() == str(value).lower():
                matched_option = opt
                break

        if matched_option:
            resolved_value = matched_option["id"]
            print(f"  [DEBUG] Step 4 - Matched '{value}' -> option_id={resolved_value}")
        else:
            available = [opt.get("option") for opt in options]
            raise ValueError(
                f"Picklist value '{value}' not found for field '{field_name}'.\n"
                f"  Available options: {available}"
            )
    else:
        print(f"  [DEBUG] Step 4 - Non-picklist field, using value as-is")

    # Step 5: Build the PATCH body.
    # Always include custom_field.id (required for picklists, harmless for others).
    # The value_id tells Clio it's an UPDATE vs CREATE.
    cf_entry = {"custom_field": {"id": field_def_id}, "value": resolved_value}
    if existing_value_id:
        cf_entry["id"] = existing_value_id

    body = {"data": {"custom_field_values": [cf_entry]}}

    _write_log(log_path, {
        "stage": "PATCH_BODY",
        "operation": "UPDATE" if existing_value_id else "CREATE",
        "value_id": existing_value_id,
        "field_def_id": field_def_id,
        "field_type": field_type,
        "original_value": value,
        "resolved_value": resolved_value,
        "body": body,
    })
    print(f"  [DEBUG] Step 5 - PATCH body: {json.dumps(body)}")

    # Step 6: Send the PATCH
    try:
        result = client.patch(f"matters/{matter_id}.json", body=body)
        _write_log(log_path, {"stage": "PATCH_OK", "field_name": field_name})
        print(f"  [DEBUG] Step 6 - Success!")
        return result
    except Exception as patch_err:
        _write_log(log_path, {
            "stage": "PATCH_FAILED", "error": str(patch_err), "body_sent": body,
        })
        raise
 
 
def _write_log(log_path: Path, entry: dict):
    """Append a JSON entry to the debug log file."""
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
 
def bulk_update_custom_field_from_csv(client: ClioClient, csv_path, field_name=None):
    """
    Bulk update custom field values on matters from a CSV file.

    Uses the same name-based resolution as option 6 (update_custom_field_value).
    Each row calls the full 5-step process: resolve name, GET matter, find
    value_id, build body, PATCH.

    Expected CSV columns:
        matter_id, field_name, value

    If field_name is provided at the prompt, it applies to ALL rows
    and the CSV only needs:
        matter_id, value

    Example CSV (multiple fields):
        matter_id,field_name,value
        1830300500,Vehicle Year,2025
        1830302510,Plaintiff's Demand,Test bulk value

    Example CSV (single field, name passed at prompt):
        matter_id,value
        1830300500,2025
        1830302510,2026
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Validate CSV columns up front so the user gets a clear message
        if "matter_id" not in headers:
            raise ValueError(
                f"CSV is missing required column 'matter_id'.\n"
                f"  Found columns: {headers}\n"
                f"  Expected: matter_id, field_name, value"
            )
        if "value" not in headers:
            raise ValueError(
                f"CSV is missing required column 'value'.\n"
                f"  Found columns: {headers}\n"
                f"  Expected: matter_id, field_name, value"
            )
        if not field_name and "field_name" not in headers:
            raise ValueError(
                f"CSV is missing 'field_name' column and no field name was entered at the prompt.\n"
                f"  Found columns: {headers}\n"
                f"  Either add a 'field_name' column to the CSV, or enter a field name at the prompt.\n"
                f"  The prompt applies a single field name to every row."
            )

        for row in reader:
            rows.append({
                "matter_id": row["matter_id"].strip(),
                "field_name": field_name or row["field_name"].strip(),
                "value": row["value"].strip(),
            })

    print(f"  Loaded {len(rows)} rows from {csv_path.name}")
    print(f"  CSV columns: {headers}")

    results = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        mid = row["matter_id"]
        fname = row["field_name"]
        val = row["value"]
        print(f"\n  [{i}/{total}] Matter {mid} | Field: '{fname}' | Value: {val}")
        try:
            resp = update_custom_field_value(client, mid, fname, val)
            results.append((mid, True, resp))
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append((mid, False, str(e)))

    return results


# Generic bulk matter update from CSV.
def bulk_update_matters_from_csv(client: ClioClient, csv_path):
    """
    Generic bulk matter update from CSV.

    CSV must have a 'matter_id' column.  All other columns are treated as
    fields to update under {"data": {col: value}}.

    Example CSV:
        matter_id,description,status
        12345,Updated description,Open
    """
    # Set the CSV file path.
    csv_path = Path(csv_path)
    # Check if the CSV file exists.
    if not csv_path.exists():
        # Raise a FileNotFoundError if the CSV file does not exist.
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    
    # Set the updates for the matters.
    updates = []
    # Open the CSV file and read the rows.
    with open(csv_path, newline="", encoding="utf-8") as f:
        # Create a CSV reader.
        reader = csv.DictReader(f)
        # Iterate over the rows.
        for row in reader:
            # Set the matter ID.
            mid = row.pop("matter_id").strip()
            # Set the data fields.
            data_fields = {k.strip(): v.strip() for k, v in row.items()}
            # Set the updates for the matters.
            updates.append({
                # Set the matter ID.
                "id": mid,
                # Set the body for the matters.
                "body": {"data": data_fields},
            })
    # Print a message to the console.
    print(f"Loaded {len(updates)} updates from {csv_path.name}")
    # Return the bulk update matters.
    return client.bulk_update("matters", updates)


# ── CREATE operations ────────────────────────────────────────────────────────

# Create a new contact.
def create_contact(client: ClioClient, name, contact_type="Person", **extra_fields):
    """
    Create a new contact.
    contact_type: "Person" or "Company"
    """
    # Set the body for the contacts.
    body = {
        # Set the data for the contacts.
        "data": {
            # Set the name for the contacts.
            "name": name,
            # Set the type for the contacts.
            "type": contact_type,
            # Set the extra fields for the contacts.
            **extra_fields,
        }
    }
    # Return the new contact.
    return client.post("contacts", body=body)


# ── EXPORT helpers ───────────────────────────────────────────────────────────

# Write any data structure to a JSON file.
def export_to_json(data, output_path):
    """Write any data structure to a JSON file."""
    # Set the output path as a Path object 
    output_path = Path(output_path)
    # Create the parent directory if it doesn't exist using the output path.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Open the output file and write the data to it.
    with open(output_path, "w", encoding="utf-8") as file:
        # Write the data to the file.
        json.dump(data, file, indent=2)
    # Print a message to the console.
    print(f"Exported {output_path}")


# Write a list of flat dicts to a CSV file.
def export_to_csv(records, output_path, fieldnames=None):
    """Write a list of flat dicts to a CSV file."""
    # Set the output path as a Path object.
    output_path = Path(output_path)
    # Create the parent directory if it doesn't exist using the output path.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Check if there are no records.
    if not records:
        # Print a message to the console.
        print("No records to export.")
        return
    # Set the fieldnames for the CSV file.
    fieldnames = fieldnames or list(records[0].keys())
    # Open the output file and write the data to it.
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        # Create a CSV writer.
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        # Write the header to the CSV file.
        writer.writeheader()
        # Write the records to the CSV file.
        writer.writerows(records)
    # Print a message to the console.
    print(f"Exported {len(records)} records to {output_path}")
