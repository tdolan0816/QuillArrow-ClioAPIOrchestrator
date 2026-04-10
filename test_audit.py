"""Test the audit logging system — writes a test entry and queries it back."""
import requests

BASE = "http://localhost:8000/api"

# Login
login = requests.post(f"{BASE}/auth/login", data={"username": "admin", "password": "ClioAdmin2025!"})
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("=== Logged in ===\n")

# Write a test audit entry directly via the database
# (In production, write operations will do this automatically)
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from backend.database import get_connection
from backend.audit import write_audit_log

db = get_connection()
write_audit_log(
    db=db,
    username="admin",
    action="test_audit_entry",
    endpoint="/api/audit (test)",
    matter_id="1830300500",
    field_name="Vehicle Year",
    before_value="2020",
    after_value="2025",
    details={"note": "This is a test audit log entry"},
)
db.close()
print("=== Wrote test audit entry ===\n")

# Query the audit log via API
r = requests.get(f"{BASE}/audit", headers=headers)
print(f"=== GET /api/audit: {r.status_code} ===")
data = r.json()
print(f"  Total returned: {data['total_returned']}")
for entry in data["data"]:
    print(f"  [{entry['timestamp']}] {entry['username']} | {entry['action']} | "
          f"matter={entry['matter_id']} | {entry['field_name']}: "
          f"{entry['before_value']} -> {entry['after_value']} | {entry['status']}")

# Query with filter
print(f"\n=== GET /api/audit?matter_id=1830300500 ===")
r2 = requests.get(f"{BASE}/audit?matter_id=1830300500", headers=headers)
print(f"  Status: {r2.status_code}, entries: {r2.json()['total_returned']}")

# Query without auth (should 401)
print(f"\n=== GET /api/audit (no token) ===")
r3 = requests.get(f"{BASE}/audit")
print(f"  Status: {r3.status_code}")

print("\n=== All audit tests complete ===")
