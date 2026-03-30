"""
Clio API Orchestrator — Entry Point

Usage:
    python run.py                       # interactive menu
    python run.py list-matters          # direct command
    python run.py bulk-update-cf data_inputs/custom_field_updates.csv 12345
"""

import sys
import json

from clio_client import ClioClient
from operations import (
    list_matters,
    get_matter,
    list_contacts,
    list_custom_fields,
    list_document_templates,
    get_all_matters,
    update_matter,
    update_custom_field_value,
    bulk_update_custom_field_from_csv,
    bulk_update_matters_from_csv,
    export_to_json,
    export_to_csv,
)


def pp(data):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=2))


COMMANDS = {
    "1": ("List Matters",             "list-matters"),
    "2": ("List Contacts",            "list-contacts"),
    "3": ("List Custom Fields",       "list-custom-fields"),
    "4": ("List Document Templates",  "list-doc-templates"),
    "5": ("Get Single Matter by ID",  "get-matter"),
    "6": ("Update a Custom Field on a Matter", "update-cf"),
    "7": ("Bulk Update Custom Fields from CSV", "bulk-update-cf"),
    "8": ("Bulk Update Matters from CSV",       "bulk-update-matters"),
    "9": ("Export All Matters to JSON", "export-matters"),
}


def show_menu():
    print("\n╔══════════════════════════════════════════════╗")
    print("║     Clio API Orchestrator                    ║")
    print("╠══════════════════════════════════════════════╣")
    for key, (label, _) in COMMANDS.items():
        print(f"║  {key}. {label:<40} ║")
    print("║  0. Exit                                     ║")
    print("╚══════════════════════════════════════════════╝")


def run_command(client: ClioClient, cmd: str, args: list[str] | None = None):
    args = args or []

    if cmd in {"list-matters", "1"}:
        limit = int(args[0]) if args else 10
        pp(list_matters(client, limit=limit))

    elif cmd in {"list-contacts", "2"}:
        limit = int(args[0]) if args else 10
        pp(list_contacts(client, limit=limit))

    elif cmd in {"list-custom-fields", "3"}:
        limit = int(args[0]) if args else 10
        pp(list_custom_fields(client, limit=limit))

    elif cmd in {"list-doc-templates", "4"}:
        limit = int(args[0]) if args else 10
        pp(list_document_templates(client, limit=limit))

    elif cmd in {"get-matter", "5"}:
        matter_id = args[0] if args else input("  Enter Matter ID: ").strip()
        pp(get_matter(client, matter_id))

    elif cmd in {"update-cf", "6"}:
        matter_id = args[0] if len(args) > 0 else input("  Matter ID: ").strip()
        cf_id = int(args[1] if len(args) > 1 else input("  Custom Field ID: ").strip())
        value = args[2] if len(args) > 2 else input("  New Value: ").strip()
        pp(update_custom_field_value(client, matter_id, cf_id, value))
        print("  Updated successfully.")

    elif cmd in {"bulk-update-cf", "7"}:
        csv_path = args[0] if len(args) > 0 else input("  CSV file path: ").strip()
        cf_id_str = args[1] if len(args) > 1 else input("  Custom Field ID (or leave blank if in CSV): ").strip()
        cf_id = int(cf_id_str) if cf_id_str else None
        results = bulk_update_custom_field_from_csv(client, csv_path, custom_field_id=cf_id)
        succeeded = [r for r in results if r[1]]
        print(f"\n  Done: {len(succeeded)}/{len(results)} succeeded.")

    elif cmd in {"bulk-update-matters", "8"}:
        csv_path = args[0] if args else input("  CSV file path: ").strip()
        results = bulk_update_matters_from_csv(client, csv_path)
        succeeded = [r for r in results if r[1]]
        print(f"\n  Done: {len(succeeded)}/{len(results)} succeeded.")

    elif cmd in {"export-matters", "9"}:
        out = args[0] if args else "data_outputs/all_matters.json"
        print("  Fetching all matters (this may take a moment)...")
        all_m = get_all_matters(client)
        export_to_json(all_m, out)

    else:
        print(f"  Unknown command: {cmd}")


def main():
    client = ClioClient()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        run_command(client, cmd, sys.argv[2:])
        return

    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        if choice == "0":
            print("Goodbye.")
            break
        if choice in COMMANDS:
            _, cmd = COMMANDS[choice]
            try:
                run_command(client, cmd)
            except Exception as e:
                print(f"  ERROR: {e}")
        else:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()
