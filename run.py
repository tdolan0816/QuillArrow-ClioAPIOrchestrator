"""
Clio API Orchestrator — Entry Point

Usage:
    python run.py                       # interactive menu
    python run.py list-matters          # direct command
    python run.py bulk-update-cf data_inputs/custom_field_updates.csv 12345
    python run.py auth                  # launch OAuth flow
"""

import subprocess
import sys
import json
import time
from pathlib import Path

from config import TOKEN_FILE, CLIO_APP_DOMAIN

# Pretty-print JSON data.
def pp(data):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=2))


# Check the authentication status.
def check_auth_status():
    """Show current token status without creating a client."""
    # Check if the token file exists.
    if not TOKEN_FILE.exists():
        # Print a message to the console.
        print("  Status: NOT AUTHORIZED")
        # Print a message to the console.
        print(f"  No token file found at {TOKEN_FILE}")
        # Print a message to the console.
        print("  Run 'python run.py auth' or use a launch script to authorize.")
        return False

    # Open the token file and load the tokens.
    with TOKEN_FILE.open("r", encoding="utf-8") as f:
        tokens = json.load(f)

    # Get the expiration time from the tokens.
    expires_at = tokens.get("expires_at", 0)
    # Get the current time.
    now = time.time()
    # Check if the token has expired.
    # Print a message to the console.
    if now >= expires_at:
        # Print a message to the console.
        print("  Status: TOKEN EXPIRED (will auto-refresh on next API call)")
    else:
        # Print a message to the console.
        remaining = int(expires_at - now)
        # Calculate the hours and remainder.
        hours, remainder = divmod(remaining, 3600)
        # Calculate the minutes and _ (unused).
        minutes, _ = divmod(remainder, 60)
        # Print a message to the console.
        print(f"  Status: AUTHORIZED (token expires in {hours}h {minutes}m)")

    # Check if the refresh token is present.
    if tokens.get("refresh_token"):
        # Print a message to the console.
        print("  Refresh token: present (auto-refresh enabled)")
    else:
        # Print a message to the console.
        print("  Refresh token: MISSING (will need to re-authorize)")
    # Return True.
    return True


COMMANDS = {
    "1":  ("List Matters",                          "list-matters"),
    "2":  ("List Contacts",                         "list-contacts"),
    "3":  ("List Custom Fields (All Types)",        "list-custom-fields"),
    "3M": ("List Custom Fields (Matters Only)",     "list-matter-custom-fields"),
    "4":  ("List Document Templates",               "list-doc-templates"),
    "5":  ("Get Single Matter by ID",               "get-matter"),
    "6":  ("Update a Custom Field on a Matter",     "update-cf"),
    "7":  ("Bulk Update Custom Fields from CSV",    "bulk-update-cf"),
    "8":  ("Bulk Update Matters from CSV",          "bulk-update-matters"),
    "9":  ("Export All Matters to JSON",            "export-matters"),
    "A":  ("Check Auth Status",                     "auth-status"),
    "R":  ("Re-Authorize (launch OAuth flow)",      "auth"),
}


def show_menu():
    """Show the menu for the CLI."""
    # Print a message to the console.
    print("\n╔══════════════════════════════════════════════════╗")
    # Print a message to the console.
    print("║        Clio API Orchestrator                     ║")
    # Print a message to the console.
    print("╠══════════════════════════════════════════════════╣")
    # Print a message to the console.
    print("║  Data Operations                                 ║")
    for key in ["1", "2", "3", "3M", "4", "5"]:
        label = COMMANDS[key][0]
        print(f"║  {key:<2} {label:<44}║")
    print("║  Write Operations                                ║")
    for key in ["6", "7", "8", "9"]:
        label = COMMANDS[key][0]
        print(f"║  {key:<2} {label:<44}║")
    print("║  Authentication                                  ║")
    for key in ["A", "R"]:
        label = COMMANDS[key][0]
        print(f"║  {key:<2} {label:<44}║")
    print("║  0  Exit                                         ║")
    print("╚══════════════════════════════════════════════════╝")


def run_command(cmd: str, args: list[str] | None = None):
    """Run the command for the CLI."""
    # Set the arguments for the command.
    args = args or []
    if cmd in {"auth-status", "A"}:
        check_auth_status()
        return

    if cmd in {"auth", "R"}:
        # Print a message to the console.
        print("  Launching OAuth server...")
        # Print a message to the console.
        print(f"  Visit https://{CLIO_APP_DOMAIN}/login in your browser.")
        # Run the OAuth server.
        subprocess.run([sys.executable, "clio_oauth_app.py"])
        return

    # Everything below needs a live client — import lazily so auth check
    # only happens when you actually make API calls.
    from clio_client import ClioClient
    from operations import (
        list_matters,
        get_matter,
        list_contacts,
        list_custom_fields,
        list_document_templates,
        get_all_matters,
        update_custom_field_value,
        bulk_update_custom_field_from_csv,
        bulk_update_matters_from_csv,
        export_to_json,
    )

    # Create a new Clio client.
    client = ClioClient()

    # Check if the command is "list-matters" or "1".
    if cmd in {"list-matters", "1"}:
        # Set the limit for the command.
        limit = int(args[0]) if args else 10
        # Pretty-print the list of matters.
        pp(list_matters(client, limit=limit))
        # Return.

    # Check if the command is "list-contacts" or "2".
    elif cmd in {"list-contacts", "2"}:
        # Set the limit for the command.
        limit = int(args[0]) if args else 10
        # Pretty-print the list of contacts.
        pp(list_contacts(client, limit=limit))
        # Return.
        
    elif cmd in {"list-custom-fields", "3"}:
        limit = int(args[0]) if args else 10
        pp(list_custom_fields(client, limit=limit))

    elif cmd in {"list-matter-custom-fields", "3M"}:
        limit = int(args[0]) if args else 200
        pp(list_custom_fields(client, limit=limit, parent_type="Matter"))

    elif cmd in {"list-doc-templates", "4"}:
        # Set the limit for the command.
        limit = int(args[0]) if args else 10
        # Pretty-print the list of document templates.
        pp(list_document_templates(client, limit=limit))
        # Return.
        
    # Check if the command is "get-matter" or "5".
    elif cmd in {"get-matter", "5"}:
        # Set the matter ID for the command.
        matter_id = args[0] if args else input("  Enter Matter ID: ").strip()
        # Pretty-print the matter.
        pp(get_matter(client, matter_id))
        # Return.
        
    # Check if the command is "update-cf" or "6".
    elif cmd in {"update-cf", "6"}:
        # Set the matter ID for the command.
        matter_id = args[0] if len(args) > 0 else input("  Matter ID: ").strip()
        # Set the custom field ID for the command.
        cf_id = int(args[1] if len(args) > 1 else input("  Custom Field ID: ").strip())
        # Set the value for the command.
        value = args[2] if len(args) > 2 else input("  New Value: ").strip()
        # Pretty-print the updated custom field value.
        pp(update_custom_field_value(client, matter_id, cf_id, value))
        print("  Updated successfully.")
        # Return.
        
    # Check if the command is "bulk-update-cf" or "7".
    elif cmd in {"bulk-update-cf", "7"}:
        # Set the CSV file path for the command.
        csv_path = args[0] if len(args) > 0 else input("  CSV file path: ").strip()
        # Set the custom field ID for the command.
        cf_id_str = args[1] if len(args) > 1 else input("  Custom Field ID (or leave blank if in CSV): ").strip()
        # Set the custom field ID for the command.
        cf_id = int(cf_id_str) if cf_id_str else None
        # Pretty-print the results of the bulk update custom field from CSV.
        results = bulk_update_custom_field_from_csv(client, csv_path, custom_field_id=cf_id)
        # Set the succeeded results for the command.
        succeeded = [r for r in results if r[1]]
        # Print a message to the console.
        print(f"\n  Done: {len(succeeded)}/{len(results)} succeeded.")
        # Return.
        
    # Check if the command is "bulk-update-matters" or "8".
    elif cmd in {"bulk-update-matters", "8"}:
        # Set the CSV file path for the command.
        csv_path = args[0] if args else input("  CSV file path: ").strip()
        # Set the results for the command.
        results = bulk_update_matters_from_csv(client, csv_path)
        # Set the succeeded results for the command.
        succeeded = [r for r in results if r[1]]
        # Print a message to the console.
        print(f"\n  Done: {len(succeeded)}/{len(results)} succeeded.")
        # Return.
        
    # Check if the command is "export-matters" or "9".
    elif cmd in {"export-matters", "9"}:
        # Set the output file path for the command.
        out = args[0] if args else "data_outputs/all_matters.json"
        # Print a message to the console.
        print("  Fetching all matters (this may take a moment)...")
        # Get all the matters.
        all_m = get_all_matters(client)
        # Export the all matters to a JSON file.
        export_to_json(all_m, out)
        # Return.
        
    # Check if the command is "unknown" or "U".
    else:
        # Print a message to the console.
        print(f"  Unknown command: {cmd}")
        # Return.


def main():
    """Main function for the CLI."""
    # Check if the command is provided.
    if len(sys.argv) > 1:
        # Set the command for the CLI.
        cmd = sys.argv[1]
        # Run the command for the CLI.
        run_command(cmd, sys.argv[2:])
        # Return.
        return

    while True:
        # Show the menu for the CLI.
        show_menu()
        # Get the choice from the user.
        choice = input("\nSelect option: ").strip().upper()
        # Check if the choice is "0".
        if choice == "0":
            # Print a message to the console.
            print("Goodbye.")
            break
        # Check if the choice is in the COMMANDS dictionary.
        if choice in COMMANDS:
            # Set the command for the CLI.
            _, cmd = COMMANDS[choice]
            # Try to run the command for the CLI.
            try:
                # Run the command for the CLI.
                run_command(cmd)
            # Catch any exceptions and print the error.
            except Exception as e:
                # Print a message to the console.
                print(f"  ERROR: {e}")
        # Check if the choice is not in the COMMANDS dictionary.
        else:
            # Print a message to the console.
            print("  Invalid choice.")


if __name__ == "__main__":
    # Run the main function for the CLI.
    main()
