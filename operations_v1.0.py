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


# Update a custom field value on a matter.
def update_custom_field_value(client: ClioClient, matter_id, custom_field_id, value):
    """
    Set or update a custom field value on a matter.

    Clio has two different IDs for custom fields:
      - field_def_id (e.g. 21836420) = the field definition, shared across matters
      - value_id (e.g. "numeric-182750525") = the specific value instance on a matter
    """

    # Set the custom field ID.
    custom_field_id = int(custom_field_id)

    # Fetch the matter's current custom field values to find existing value_id
    # Set the endpoint for the custom field values.
    endpoint = (
        f"matters/{matter_id}"
        f"?fields=custom_field_values{{id,custom_field{{id}}}}"
    )
    # Get the current custom field values.
    current = client._request("GET", endpoint)

    print("  Raw custom_field_values:", current.get("data", {}).get("custom_field_values", []))

    # Look for an existing value_id for this field_def_id - field_def_id = field definition ID
    # Set the existing value ID.
    existing_value_id = None
    # Look for an existing value ID for the custom field ID - cfv = custom field value
    for cfv in current.get("data", {}).get("custom_field_values", []):
        # Set the custom field reference.
        cf_ref = cfv.get("custom_field", {}) # cf_ref = custom field reference
        # Check if the custom field ID is the same as the custom field ID.
        if cf_ref.get("id") == custom_field_id: # cf_ref.get("id") = custom field ID
            # Set the existing value ID.
            existing_value_id = cfv.get("id") # cfv.get("id") = value ID
            break

    # Set the custom field entry.
    cf_entry = {
        # Set the custom field ID.
        "custom_field": {"id": custom_field_id},
        # Set the value.
        "value": value,
    }
    # Check if the existing value ID is not None.
    if existing_value_id:
        # Set the existing value ID.
        cf_entry["id"] = existing_value_id
    # Set the body for the custom field values.

    # Set the body for the custom field values.
    body = {"data": {"custom_field_values": [cf_entry]}}
    # Return the custom field values.
    return client.update_by_id("matters", matter_id, body=body)


# Bulk update custom field from CSV.
def bulk_update_custom_field_from_csv(client: ClioClient, csv_path, custom_field_id=None):
    """
    Read a CSV file and apply custom field updates to matters in bulk.

    Uses the same value_id lookup as update_custom_field_value -- for each
    row, fetches the matter's existing value_id so Clio accepts the update.

    Expected CSV columns:
        matter_id, custom_field_id (optional if passed as arg), value

    If custom_field_id is provided as an argument, the CSV only needs:
        matter_id, value
    """
    # Set the CSV file path.
    csv_path = Path(csv_path)
    # Check if the CSV file exists.
    if not csv_path.exists():
        # Raise a FileNotFoundError if the CSV file does not exist.
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    # Set the rows for the custom field values.
    rows = []
    # Open the CSV file and read the rows.
    with open(csv_path, newline="", encoding="utf-8") as f:
        # Create a CSV reader.
        reader = csv.DictReader(f)
        # Iterate over the rows.
        for row in reader:
            # Set the matter ID.
            rows.append({
                # Set the matter ID.
                "matter_id": row["matter_id"].strip(),
                # Set the custom field ID.
                "custom_field_id": int(custom_field_id or row["custom_field_id"].strip()),
                # Set the value.
                "value": row["value"].strip(),
            })
    # Print a message to the console.
    print(f"Loaded {len(rows)} rows from {csv_path.name}")
    # Print a message to the console.
    print("  Resolving value_ids for existing fields...")
    # Set the results for the custom field values.
    results = []
    # Set the total number of rows.
    total = len(rows)
    # Iterate over the rows.
    for i, row in enumerate(rows, 1):
        # Set the matter ID.
        mid = row["matter_id"]
        # Set the custom field ID.
        cfid = row["custom_field_id"]
        # Set the value.
        val = row["value"]
        # Print a message to the console.
        print(f"  [{i}/{total}] Updating matter {mid}, field {cfid}...")
        # Try to update the custom field value.
        try:
            # Update the custom field value.
            resp = update_custom_field_value(client, mid, cfid, val)
            # Set the results for the custom field values.
            results.append((mid, True, resp))
        # Catch any exceptions.
        except Exception as e:
            # Print a message to the console.
            print(f"  FAILED matter {mid}: {e}")
            # Set the results for the custom field values.
            results.append((mid, False, str(e)))

    # Return the results for the custom field values.
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
