"""
task_reassign.py  —  Reassign tasks within Clio Matters to a new user.

Inputs (via CSV):
    matter_display_number, task_name, new_assignee_name

Run from repo root:
    .venv\Scripts\python.exe task_reassign.py --env prod --csv data_inputs/task_reassignments.csv
    .venv\Scripts\python.exe task_reassign.py --env prod --interactive

CSV format:
    matter_display_number,task_name,new_assignee_name
    00180-Gubik,Send Demand Letter,Jane Doe
    00215-Smith,File Motion,John Smith
"""

import argparse
import csv
import json
import os
from pathlib import Path


# ── Parse args before importing app modules ───────────────────────────────────

parser = argparse.ArgumentParser(description="Reassign Clio tasks to a new user.")
parser.add_argument(
    "--env",
    choices=["dev", "prod"],
    default="dev",
    help="Which Clio environment to connect to (default: dev)",
)

mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument(
    "--csv",
    metavar="PATH",
    help="Path to CSV file with columns: matter_display_number, task_name, new_assignee_name",
)
mode.add_argument(
    "--interactive",
    action="store_true",
    help="Prompt for a single matter/task/assignee interactively",
)

parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Preview what would change without actually PATCHing Clio",
)
args = parser.parse_args()


# ── Inject credentials before config.py loads ────────────────────────────────

CREDENTIALS = {
    "dev": {
        "CLIO_CLIENT_ID":     "w9ciZKnsTZw8Hx1Y1gjT3J149jtamwaGY429NlQ6",
        "CLIO_CLIENT_SECRET": "yuwhJD1qyqjwKIwO1i17xZyozePCcfr8in6E1UwM",
        "CLIO_REDIRECT_URI":  "quillarrow-clioapiorchestrator-dccuhyf6epetf5ek.westus2-01.azurewebsites.net/api/oauth/callback",
        # "CLIO_REDIRECT_URI":  "https://localhost:8787/oauth/callback",
    },
    # "prod": {
    #     "CLIO_CLIENT_ID":     "hUN65hCoCcJVMcCdpjVShJBPqWhwAjGpRCA75vzi",
    #     "CLIO_CLIENT_SECRET": "payho6jN1Ed4VDhKFXRh3RB2kNmqTSQL4zK6QvIi",
    #     "CLIO_REDIRECT_URI":  "https://quillarrow-clioapiorchestrator-prod-dcayasf7gcbhcre5.westus2-01.azurewebsites.net/api/oauth/callback",
    # },
}

for key, value in CREDENTIALS[args.env].items():
    os.environ[key] = value

os.environ["CLIO_TOKEN_FILE"] = f"clio_tokens_{args.env}.json"


# ── Now safe to import app modules ────────────────────────────────────────────

from clio_client import ClioClient
from operations import get_user_lookup


# ── Step helpers ──────────────────────────────────────────────────────────────

def resolve_matter_id(client: ClioClient, display_number: str) -> tuple[str, str]:
    """
    Resolve a matter display number to its numeric Clio ID.
    Returns (matter_id, display_number) or raises ValueError.
    """
    # Strip whitespace and search Clio
    dn = display_number.strip()
    resp = client._request(
        "GET",
        "matters",
        params={"query": dn, "fields": "id,display_number", "limit": 10},
    )
    matters = resp.get("data", []) if isinstance(resp, dict) else []

    # Verify exact match — Clio may return partial matches
    for m in matters:
        if (m.get("display_number") or "").lower() == dn.lower():
            return str(m["id"]), m["display_number"]

    raise ValueError(
        f"No matter found with display_number '{dn}'. "
        f"Check the display number and try again."
    )


def find_tasks_for_matter(client: ClioClient, matter_id: str, task_name: str) -> list[dict]:
    """
    Fetch all tasks for a matter and return those whose name matches task_name
    (case-insensitive). Paginates automatically in case the matter has many tasks.
    """
    matches = []
    needle = task_name.strip().lower()

    for task in client.get_all(
        "tasks",
        fields=["id", "name", "status", "assignee{id,name,type}"],
        matter_id=matter_id,
    ):
        if (task.get("name") or "").lower() == needle:
            matches.append(task)

    return matches


def resolve_user_id(client: ClioClient, name: str) -> tuple[int, str]:
    """
    Resolve a user name (or partial name) to a Clio user ID.
    Uses the cached user lookup from operations.py.
    Returns (user_id, canonical_name) or raises ValueError.
    """
    users = get_user_lookup(client)
    needle = name.strip().lower()

    # Try exact full-name match first
    exact = [u for u in users.values() if (u.get("name") or "").lower() == needle]
    if len(exact) == 1:
        u = exact[0]
        return u["id"], u.get("name", f"User {u['id']}")
    if len(exact) > 1:
        names = [u.get("name") for u in exact]
        raise ValueError(
            f"'{name}' matched multiple users: {names}. "
            f"Use a more specific name or their Clio user ID."
        )

    # Fall back to partial match
    partial = [u for u in users.values() if needle in (u.get("name") or "").lower()]
    if len(partial) == 1:
        u = partial[0]
        return u["id"], u.get("name", f"User {u['id']}")
    if len(partial) > 1:
        names = [u.get("name") for u in partial]
        raise ValueError(
            f"'{name}' matched multiple users: {names}. "
            f"Be more specific."
        )

    raise ValueError(
        f"No Clio user found matching '{name}'. "
        f"Check the spelling or use their full name as it appears in Clio."
    )


def reassign_task(
    client: ClioClient,
    task: dict,
    user_id: int,
    user_name: str,
    dry_run: bool = False,
) -> dict:
    """
    PATCH the task's assignee to the given user.
    Returns a result dict describing what happened.
    """
    task_id = task["id"]
    task_name = task.get("name")
    current_assignee = (task.get("assignee") or {}).get("name", "unassigned")

    if dry_run:
        return {
            "task_id":          task_id,
            "task_name":        task_name,
            "current_assignee": current_assignee,
            "new_assignee":     user_name,
            "status":           "DRY RUN — no changes made",
        }

    patch_body = {
        "data": {
            "assignee": {
                "id":   user_id,
                "type": "User",
            }
        }
    }

    client.patch(f"tasks/{task_id}.json", body=patch_body)

    return {
        "task_id":          task_id,
        "task_name":        task_name,
        "current_assignee": current_assignee,
        "new_assignee":     user_name,
        "status":           "success",
    }


# ── Core processing ───────────────────────────────────────────────────────────

def process_row(
    client: ClioClient,
    matter_display_number: str,
    task_name: str,
    new_assignee_name: str,
    dry_run: bool = False,
) -> list[dict]:
    """
    Full workflow for one CSV row / interactive entry:
        1. Resolve matter display number → matter ID
        2. Find matching tasks within that matter by name
        3. Resolve new assignee name → user ID
        4. PATCH each matching task

    Returns a list of result dicts (there may be multiple tasks with the same
    name in a matter, so we update all of them).
    """
    results = []

    # Step 1: Matter lookup
    try:
        matter_id, display_number = resolve_matter_id(client, matter_display_number)
        print(f"  ✓ Matter   : {display_number} (ID: {matter_id})")
    except ValueError as e:
        print(f"  ✗ Matter   : {e}")
        return [{"matter": matter_display_number, "task": task_name, "status": f"ERROR: {e}"}]

    # Step 2: Task lookup
    try:
        tasks = find_tasks_for_matter(client, matter_id, task_name)
        if not tasks:
            msg = f"No task named '{task_name}' found in matter {display_number}."
            print(f"  ✗ Task     : {msg}")
            return [{
                "matter":  display_number,
                "task":    task_name,
                "status":  f"ERROR: {msg}",
            }]
        print(f"  ✓ Tasks    : found {len(tasks)} matching task(s) named '{task_name}'")
    except Exception as e:
        print(f"  ✗ Task     : {e}")
        return [{"matter": display_number, "task": task_name, "status": f"ERROR: {e}"}]

    # Step 3: User lookup
    try:
        user_id, user_name = resolve_user_id(client, new_assignee_name)
        print(f"  ✓ Assignee : {user_name} (ID: {user_id})")
    except ValueError as e:
        print(f"  ✗ Assignee : {e}")
        return [{
            "matter":  display_number,
            "task":    task_name,
            "status":  f"ERROR: {e}",
        }]

    # Step 4: PATCH each matching task
    for task in tasks:
        current = (task.get("assignee") or {}).get("name", "unassigned")
        print(f"  → Reassigning task ID {task['id']} "
              f"from '{current}' to '{user_name}'"
              + (" [DRY RUN]" if dry_run else "") + "...")
        try:
            result = reassign_task(client, task, user_id, user_name, dry_run=dry_run)
            result["matter"] = display_number
            results.append(result)
            print(f"    ✓ {result['status']}")
        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            results.append({
                "matter":          display_number,
                "task_id":         task["id"],
                "task_name":       task_name,
                "current_assignee": current,
                "new_assignee":    user_name,
                "status":          f"ERROR: {e}",
            })

    return results


# ── Main entry point ──────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"  Clio Task Reassignment Tool")
    print(f"  Environment : {args.env.upper()}")
    print(f"  Mode        : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    client = ClioClient()
    all_results = []

    if args.interactive:
        # ── Single interactive entry ──────────────────────────────────────
        print("Enter the details for the task reassignment:\n")
        matter_dn    = input("  Matter Display Number : ").strip()
        task_name    = input("  Task Name             : ").strip()
        assignee     = input("  New Assignee Name     : ").strip()

        print()
        results = process_row(client, matter_dn, task_name, assignee, dry_run=args.dry_run)
        all_results.extend(results)

    else:
        # ── CSV batch mode ────────────────────────────────────────────────
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"ERROR: CSV file not found: {csv_path}")
            return

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        print(f"  Loaded {len(rows)} row(s) from {csv_path.name}\n")

        for i, row in enumerate(rows, start=1):
            matter_dn = (row.get("matter_display_number") or "").strip()
            task_name = (row.get("task_name") or "").strip()
            assignee  = (row.get("new_assignee_name") or "").strip()

            if not matter_dn or not task_name or not assignee:
                print(f"[Row {i}] Skipping — missing required fields.")
                all_results.append({
                    "matter": matter_dn, "task": task_name,
                    "status": "SKIPPED: missing fields",
                })
                continue

            print(f"[Row {i}/{len(rows)}] {matter_dn} | '{task_name}' → '{assignee}'")
            results = process_row(client, matter_dn, task_name, assignee, dry_run=args.dry_run)
            all_results.extend(results)
            print()

    # ── Summary ───────────────────────────────────────────────────────────────
    succeeded = [r for r in all_results if "ERROR" not in r.get("status", "") and "SKIPPED" not in r.get("status", "")]
    failed    = [r for r in all_results if "ERROR" in r.get("status", "") or "SKIPPED" in r.get("status", "")]

    print(f"\n{'='*60}")
    print(f"  Complete: {len(succeeded)} succeeded, {len(failed)} failed/skipped")
    print(f"{'='*60}\n")

    # ── Write results CSV ─────────────────────────────────────────────────────
    os.makedirs("data_outputs", exist_ok=True)
    out_path = f"data_outputs/task_reassign_results_{args.env}.csv"

    fieldnames = [
        "matter", "task_id", "task_name",
        "current_assignee", "new_assignee", "status",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_results)

    print(f"  Results written to {out_path}\n")


if __name__ == "__main__":
    main()