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

_custom_field_cache: dict[int, dict] | None = None


def get_custom_field_lookup(client: ClioClient) -> dict[int, dict]:
    """
    Fetch all Matter custom field definitions and return a dict keyed by ID.

    Cached after the first call so subsequent matter lookups don't repeat it.
    Result format: {field_id: {"name": "...", "field_type": "...", "parent_type": "..."}}
    """
    global _custom_field_cache
    if _custom_field_cache is not None:
        return _custom_field_cache

    print("  Loading custom field definitions (one-time)...")
    all_fields = list(client.get_all(
        "custom_fields",
        fields=["id", "name", "field_type", "parent_type"],
        parent_type="Matter",
    ))
    _custom_field_cache = {
        cf["id"]: {"name": cf.get("name"), "field_type": cf.get("field_type"), "parent_type": cf.get("parent_type")}
        for cf in all_fields
    }
    print(f"  Cached {len(_custom_field_cache)} matter custom field definitions.")
    return _custom_field_cache


def clear_custom_field_cache():
    """Force a refresh of the custom field lookup on the next call."""
    global _custom_field_cache
    _custom_field_cache = None


# ── READ operations ──────────────────────────────────────────────────────────

def list_matters(client: ClioClient, fields=None, limit=10):
    """List matters with chosen fields."""
    fields = fields or ["id", "display_number", "description", "status"]
    return client.get("matters", fields=fields, limit=limit)


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

    # Join: enrich each custom_field_value with the field name and type
    for cfv in matter_data.get("data", {}).get("custom_field_values", []):
        cf_ref = cfv.get("custom_field", {})
        cf_id = cf_ref.get("id")
        if cf_id and cf_id in cf_lookup:
            cf_ref["name"] = cf_lookup[cf_id]["name"]
            cf_ref["field_type"] = cf_lookup[cf_id]["field_type"]

    return matter_data


# List contacts.
def list_contacts(client: ClioClient, fields=None, limit=10):
    fields = fields or ["id", "name", "type", "primary_email_address"]
    return client.get("contacts", fields=fields, limit=limit)


def list_custom_fields(client: ClioClient, fields=None, limit=10, parent_type=None):
    """
    List custom fields.

    parent_type filters by entity: "Matter", "Contact", "Activity", etc.
    Without it, returns ALL custom fields across all entity types --
    which is why you may see more than what's visible on matters alone.
    """
    fields = fields or ["id", "name", "field_type", "parent_type"]
    extra = {}
    if parent_type:
        extra["parent_type"] = parent_type
    return client.get("custom_fields", fields=fields, limit=limit, **extra)


# List document templates.
def list_document_templates(client: ClioClient, fields=None, limit=10):
    fields = fields or ["id", "filename"]
    return client.get("document_templates", fields=fields, limit=limit)


# Paginate through ALL matters (can be thousands).
def get_all_matters(client: ClioClient, fields=None):
    """Paginate through ALL matters (can be thousands)."""
    fields = fields or ["id", "display_number", "description", "status"]
    return list(client.get_all("matters", fields=fields))


# ── UPDATE operations ────────────────────────────────────────────────────────

# Update a single matter.
def update_matter(client: ClioClient, matter_id, updates: dict):
    """
    Update a single matter.

    Example updates dict:
        {"data": {"description": "New description here"}}
    """
    return client.update_by_id("matters", matter_id, body=updates)


# Set a custom field value on a matter.
def update_custom_field_value(client: ClioClient, matter_id, custom_field_id, value):
    """
    Set a custom field value on a matter.

    Clio expects custom_field_values nested under the matter update.
    """
    body = {
        "data": {
            "custom_field_values": [
                {
                    "custom_field": {"id": custom_field_id},
                    "value": value,
                }
            ]
        }
    }
    return client.update_by_id("matters", matter_id, body=body)


# Read a CSV file and apply custom field updates to matters in bulk.
def bulk_update_custom_field_from_csv(client: ClioClient, csv_path, custom_field_id=None):
    """
    Read a CSV file and apply custom field updates to matters in bulk.

    Expected CSV columns:
        matter_id, custom_field_id (optional if passed as arg), value

    If custom_field_id is provided as an argument, the CSV only needs:
        matter_id, value
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    updates = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mid = row["matter_id"].strip()
            cfid = custom_field_id or int(row["custom_field_id"].strip())
            val = row["value"].strip()
            updates.append({
                "id": mid,
                "body": {
                    "data": {
                        "custom_field_values": [
                            {
                                "custom_field": {"id": int(cfid)},
                                "value": val,
                            }
                        ]
                    }
                },
            })

    print(f"Loaded {len(updates)} updates from {csv_path.name}")
    return client.bulk_update("matters", updates)


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
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    updates = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mid = row.pop("matter_id").strip()
            data_fields = {k.strip(): v.strip() for k, v in row.items()}
            updates.append({
                "id": mid,
                "body": {"data": data_fields},
            })

    print(f"Loaded {len(updates)} updates from {csv_path.name}")
    return client.bulk_update("matters", updates)


# ── CREATE operations ────────────────────────────────────────────────────────

# Create a new contact.
def create_contact(client: ClioClient, name, contact_type="Person", **extra_fields):
    """
    Create a new contact.
    contact_type: "Person" or "Company"
    """
    body = {
        "data": {
            "name": name,
            "type": contact_type,
            **extra_fields,
        }
    }
    return client.post("contacts", body=body)


# ── EXPORT helpers ───────────────────────────────────────────────────────────

# Write any data structure to a JSON file.
def export_to_json(data, output_path):
    """Write any data structure to a JSON file."""
    # Create the parent directory if it doesn't exist.
    output_path = Path(output_path)
    # Create the parent directory if it doesn't exist.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Open the output file and write the data to it.
    with open(output_path, "w", encoding="utf-8") as f:
        # Write the data to the file.
        json.dump(data, f, indent=2)
    # Print a message to the console.
    print(f"Exported {output_path}")


# Write a list of flat dicts to a CSV file.
def export_to_csv(records, output_path, fieldnames=None):
    """Write a list of flat dicts to a CSV file."""
    # Create the parent directory if it doesn't exist.
    output_path = Path(output_path)
    # Create the parent directory if it doesn't exist.
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
