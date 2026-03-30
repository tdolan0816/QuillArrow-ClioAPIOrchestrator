import requests
import json

# ── Configuration ─────────────────────────────────────────────────────────────
ACCESS_TOKEN = "26651-T52LkwQVy6Ms4ghFAkPf4IDhNvIGCRlgQN"

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

api_base_url = "https://app.clio.com/api/v4"

params_doc_temp = {
    "clio_section": "document_templates",
    "field1": "id",
    "field2": "filename",
    "limit": 10
}

params_matter = {
    "clio_section": "matters",
    "field1": "description",
    "field2": "id",
    "limit": 10
}

params_contacts = {
    "clio_section": "contacts",
    "field1": "id",
    "field2": "name",
    "limit": 10
}

params_custom_fields = {
    "clio_section": "custom_fields",
    "field1": "id", 
    "field2": "name",
    "limit": 10
}


ep_url_doc_temp = f"{api_base_url}/{params_doc_temp['clio_section']}?fields={params_doc_temp['field1']},{params_doc_temp['field2']}&limit={params_doc_temp['limit']}"
ep_url_matter = f"{api_base_url}/{params_matter['clio_section']}?fields={params_matter['field1']},{params_matter['field2']}&limit={params_matter['limit']}"
ep_url_contacts = f"{api_base_url}/{params_contacts['clio_section']}?fields={params_contacts['field1']},{params_contacts['field2']}&limit={params_contacts['limit']}"
ep_url_custom_fields = f"{api_base_url}/{params_custom_fields['clio_section']}?fields={params_custom_fields['1830300500']},{params_custom_fields['field2']}&limit={params_custom_fields['limit']}"


# ── Endpoints to test — swap/add as needed ────────────────────────────────────
# Format: (label, full_url)

ENDPOINTS = [
    ("Document Templates", ep_url_doc_temp),
    ("Matters",           ep_url_matter),
    ("Contacts",          ep_url_contacts),
    ("Custom Fields",     ep_url_custom_fields),
]

try:
    response = requests.get(ep_url_custom_fields, headers=HEADERS, timeout=15)
    print(f"  Status   : {response.status_code} {response.reason}")

    data = response.json()
    print("  Response :")
    print(json.dumps(data, indent=2))

except requests.exceptions.ConnectionError:
    print("  ERROR: Could not connect. Check the URL or your network.")
