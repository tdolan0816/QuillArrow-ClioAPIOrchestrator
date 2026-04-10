"""Quick test script for all Phase 2 API endpoints."""
import requests
import json

BASE = "http://localhost:8000/api"

# Step 1: Login
print("=== Login ===")
login = requests.post(f"{BASE}/auth/login", data={"username": "admin", "password": "ClioAdmin2025!"})
print(f"  Status: {login.status_code}")
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Step 2: List Matters
print("\n=== GET /api/matters (limit=3) ===")
r = requests.get(f"{BASE}/matters?limit=3", headers=headers)
print(f"  Status: {r.status_code}")
for m in r.json().get("data", []):
    print(f"  {m['id']} | {m.get('display_number')} | {m.get('status')}")

# Step 3: Get Single Matter (use first result)
data = r.json().get("data", [])
if data:
    mid = data[0]["id"]
    print(f"\n=== GET /api/matters/{mid} ===")
    r2 = requests.get(f"{BASE}/matters/{mid}", headers=headers)
    print(f"  Status: {r2.status_code}")
    matter = r2.json().get("data", {})
    cf_count = len(matter.get("custom_field_values", []))
    print(f"  display_number: {matter.get('display_number')}")
    print(f"  custom_field_values: {cf_count} fields")

# Step 4: Search by display number
print("\n=== GET /api/matters/search?display_number=00015-Agueros ===")
r3 = requests.get(f"{BASE}/matters/search?display_number=00015-Agueros", headers=headers)
print(f"  Status: {r3.status_code}")
if r3.status_code == 200:
    print(f"  Found: {r3.json().get('data', {}).get('display_number')}")
else:
    print(f"  Response: {r3.json()}")

# Step 5: Custom Fields (Matter only)
print("\n=== GET /api/custom-fields (parent_type=Matter, limit=3) ===")
r4 = requests.get(f"{BASE}/custom-fields?limit=3&parent_type=Matter", headers=headers)
print(f"  Status: {r4.status_code}")
for cf in r4.json().get("data", []):
    print(f"  {cf['id']} | {cf.get('name')} | {cf.get('field_type')}")

# Step 6: Document Templates
print("\n=== GET /api/document-templates (limit=3) ===")
r5 = requests.get(f"{BASE}/document-templates?limit=3", headers=headers)
print(f"  Status: {r5.status_code}")
for dt in r5.json().get("data", []):
    print(f"  {dt['id']} | {dt.get('filename')}")

# Step 7: No token (should 401)
print("\n=== GET /api/matters (no token - should 401) ===")
r6 = requests.get(f"{BASE}/matters")
print(f"  Status: {r6.status_code}")
print(f"  Response: {r6.json()}")

print("\n=== All tests complete ===")
