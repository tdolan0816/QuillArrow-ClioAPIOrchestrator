"""
Pre-built operations for common Clio Manage API tasks.

Each function takes a ClioClient instance and any parameters it needs.
Add new operations here as your project grows.
"""

import csv
import json
from pathlib import Path

from clio_client import ClioClient


# ── READ operations ──────────────────────────────────────────────────────────

def list_matters(client: ClioClient, fields=None, limit=10):
    """List matters with chosen fields."""
    fields = fields or ["id", "display_number", "description", "status"]
    return client.get("matters", fields=fields, limit=limit)


def get_matter(client: ClioClient, matter_id, fields=None):
    """Get a single matter by ID."""
    fields = fields or ["id", "display_number", "description", "status", "custom_field_values"]
    return client.get_by_id("matters", matter_id, fields=fields)


def list_contacts(client: ClioClient, fields=None, limit=10):
    fields = fields or ["id", "name", "type", "primary_email_address"]
    return client.get("contacts", fields=fields, limit=limit)


def list_custom_fields(client: ClioClient, fields=None, limit=10):
    fields = fields or ["id", "name", "field_type", "parent_type"]
    return client.get("custom_fields", fields=fields, limit=limit)


def list_document_templates(client: ClioClient, fields=None, limit=10):
    fields = fields or ["id", "filename"]
    return client.get("document_templates", fields=fields, limit=limit)


def get_all_matters(client: ClioClient, fields=None):
    """Paginate through ALL matters (can be thousands)."""
    fields = fields or ["id", "display_number", "description", "status"]
    return list(client.get_all("matters", fields=fields))


# ── UPDATE operations ────────────────────────────────────────────────────────

def update_matter(client: ClioClient, matter_id, updates: dict):
    """
    Update a single matter.

    Example updates dict:
        {"data": {"description": "New description here"}}
    """
    return client.update_by_id("matters", matter_id, body=updates)


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

def export_to_json(data, output_path):
    """Write any data structure to a JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Exported {output_path}")


def export_to_csv(records, output_path, fieldnames=None):
    """Write a list of flat dicts to a CSV file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        print("No records to export.")
        return
    fieldnames = fieldnames or list(records[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"Exported {len(records)} records to {output_path}")
