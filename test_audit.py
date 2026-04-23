"""Test the audit logging system -- writes a test entry via SQLAlchemy and queries it back through the API."""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

from backend.database import get_engine, init_db  # noqa: E402
from backend.audit import write_audit_log, new_batch_id  # noqa: E402

BASE = "http://localhost:8000/api"

# Login (the API must be running locally on :8000).
login = requests.post(f"{BASE}/auth/login", data={"username": "admin", "password": "ClioAdmin2025!"})
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("=== Logged in ===\n")

# Make sure the schema exists locally (safe to call repeatedly).
init_db()

# Write a test audit entry directly through SQLAlchemy so we don't depend on Clio for the write.
engine = get_engine()
batch_id = new_batch_id()
with engine.begin() as conn:
    write_audit_log(
        conn,
        username="admin",
        action="test_audit_entry",
        endpoint="/api/audit (test)",
        matter_id="1830300500",
        field_name="Vehicle Year",
        before_value="2020",
        after_value="2025",
        details={"note": "This is a test audit log entry", "source": "test_audit.py"},
        batch_id=batch_id,
    )
print(f"=== Wrote test audit entry (batch_id={batch_id}) ===\n")

# Query the audit log via API.
r = requests.get(f"{BASE}/audit", headers=headers)
print(f"=== GET /api/audit: {r.status_code} ===")
data = r.json()
print(f"  Total returned: {data['total_returned']}")
for entry in data["data"][:10]:
    print(
        f"  [{entry['timestamp']}] {entry['username']} | {entry['action']} | "
        f"matter={entry['matter_id']} | {entry['field_name']}: "
        f"{entry['before_value']} -> {entry['after_value']} | "
        f"batch={entry.get('batch_id', '-')} | reverted={entry.get('reverted', False)} | "
        f"{entry['status']}"
    )

# Query by batch_id (new filter exposed by the revert-capable endpoint).
print(f"\n=== GET /api/audit?batch_id={batch_id} ===")
r2 = requests.get(f"{BASE}/audit", headers=headers, params={"batch_id": batch_id})
print(f"  Status: {r2.status_code}, entries: {r2.json()['total_returned']}")

# Query with matter filter (existing behavior).
print(f"\n=== GET /api/audit?matter_id=1830300500 ===")
r3 = requests.get(f"{BASE}/audit?matter_id=1830300500", headers=headers)
print(f"  Status: {r3.status_code}, entries: {r3.json()['total_returned']}")

# Query without auth (should 401).
print(f"\n=== GET /api/audit (no token) ===")
r4 = requests.get(f"{BASE}/audit")
print(f"  Status: {r4.status_code}")

print("\n=== All audit tests complete ===")
