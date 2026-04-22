import json
import requests
from pathlib import Path

# --- Load tokens from your JSON file ---
token_path = Path(r"C:\Users\Tim\OneDrive - quillarrowlaw.com\Documents\ClioData_MassUpdate_Cleanup_MappingSchema\QuillArrow-ClioAPIOrchestrator\clio_tokens.json")

with token_path.open("r") as f:
    tokens = json.load(f)

access_token = tokens["access_token"]

# --- Build the headers (this is all Clio needs for auth) ---
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
}

# --- Define the fields you want back ---
fields = "id,name,field_type,required,displayed,deleted"

# --- Loop through your specific field IDs ---
field_ids = [
    
]
results = []

for field_id in field_ids:
    # url = f"https://app.clio.com/api/v4/custom_fields/?fields=id,name,created_at,updated_at,field_type"
    url = f"https://app.clio.com/api/v4/custom_fields/?fields={fields}"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        # results.append(response.json()["data"])
        results.append(response.json())
        print(f"✓ Field {field_id}: {response.json()}")
    else:
        print(f"✗ Field {field_id}: {response.status_code} - {response.text}")

# --- results now holds all 5 field definitions ---
print(f"\nFetched {len(results)} fields successfully.")