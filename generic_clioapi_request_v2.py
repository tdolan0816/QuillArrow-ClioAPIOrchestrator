import json
import requests
from pathlib import Path

# =============================================================================
# AUTH — Load token from JSON file
# =============================================================================
token_path = Path(r"C:\Users\Tim\OneDrive - quillarrowlaw.com\Documents\ClioData_MassUpdate_Cleanup_MappingSchema\QuillArrow-ClioAPIOrchestrator\clio_tokens.json")

with token_path.open("r") as f:
    tokens = json.load(f)

headers = {
    "Authorization": f"Bearer {tokens['access_token']}",
    "Content-Type": "application/json",
}

BASE_URL = "https://app.clio.com/api/v4"

# =============================================================================
# REQUEST 1 — Search Custom Fields by NAME
# Uses ?query= for wildcard name search
# =============================================================================

search_name = "State Unicourt Identifier"   # <-- change this to any name you want

cf_fields = "id,name,field_type,parent_type,required,default,displayed,deleted,custom_field_set{id,name}"

url_cf = f"{BASE_URL}/custom_fields?fields={cf_fields}&query={requests.utils.quote(search_name)}"

print("=" * 60)
print(f"REQUEST 1 — Custom Field Name Search: '{search_name}'")
print("=" * 60)

cf_response = requests.get(url_cf, headers=headers)

if cf_response.status_code == 200:
    cf_data = cf_response.json().get("data", [])
    if not cf_data:
        print(f"  No custom fields found matching '{search_name}'")
    else:
        for cf in cf_data:
            print(f"\n  ID             : {cf.get('id')}")
            print(f"  Name           : {cf.get('name')}")
            print(f"  Field Type     : {cf.get('field_type')}")
            print(f"  Parent Type    : {cf.get('parent_type')}")
            print(f"  Required       : {cf.get('required')}")
            print(f"  Default        : {cf.get('default')}")
            print(f"  Displayed      : {cf.get('displayed')}")
            print(f"  Deleted        : {cf.get('deleted')}")
            cf_set = cf.get("custom_field_set") or {}
            print(f"  Field Set ID   : {cf_set.get('id', 'N/A')}")
            print(f"  Field Set Name : {cf_set.get('name', 'N/A')}")
else:
    print(f"  ✗ {cf_response.status_code} - {cf_response.text}")


# =============================================================================
# REQUEST 2 — GET Matter by Matter ID
# =============================================================================

matter_id = 1830300500    # <-- swap in any matter ID you want to look up

matter_fields = (
    "id,etag,display_number,description,status,"
    "open_date,close_date,pending_date,statute_of_limitations_at,"
    "client_reference,location,billable,billing_method,"
    "client{id,name},"
    "responsible_attorney{id,name},"
    "originating_attorney{id,name},"
    "responsible_staff{id,name},"
    "practice_area{id,name},"
    "billing_rate{id,type,rate},"
    "trust_balance,"
    "matter_stage{id,name},"
    "group{id,name},"
    "custom_field_values{id,value,custom_field}"
)

url_matter = f"{BASE_URL}/matters/{matter_id}?fields={matter_fields}"

print("\n")
print("=" * 60)
print(f"REQUEST 2 — Matter Lookup: ID {matter_id}")
print("=" * 60)

matter_response = requests.get(url_matter, headers=headers)

if matter_response.status_code == 200:
    m = matter_response.json().get("data", {})

    print(f"\n  ID                  : {m.get('id')}")
    print(f"  Display Number      : {m.get('display_number')}")
    print(f"  Description         : {m.get('description')}")
    print(f"  Status              : {m.get('status')}")
    print(f"  Open Date           : {m.get('open_date')}")
    print(f"  Close Date          : {m.get('close_date')}")
    print(f"  Pending Date        : {m.get('pending_date')}")
    print(f"  Statute of Lim.     : {m.get('statute_of_limitations_at')}")
    print(f"  Client Reference    : {m.get('client_reference')}")
    print(f"  Location            : {m.get('location')}")
    print(f"  Billable            : {m.get('billable')}")
    print(f"  Billing Method      : {m.get('billing_method')}")
    print(f"  Trust Balance       : {m.get('trust_balance')}")

    # --- Nested single objects ---
    for label, key in [
        ("Client",               "client"),
        ("Responsible Attorney", "responsible_attorney"),
        ("Originating Attorney", "originating_attorney"),
        ("Responsible Staff",    "responsible_staff"),
        ("Practice Area",        "practice_area"),
        ("Matter Stage",         "matter_stage"),
        ("Group",                "group"),
    ]:
        obj = m.get(key) or {}
        print(f"  {label:<22}: {obj.get('name', 'N/A')} (ID: {obj.get('id', 'N/A')})")

    # --- Billing rate ---
    br = m.get("billing_rate") or {}
    print(f"  {'Billing Rate':<22}: {br.get('type', 'N/A')} @ {br.get('rate', 'N/A')} (ID: {br.get('id', 'N/A')})")

    # --- Custom field values ---
    cfvs = m.get("custom_field_values", [])
    print(f"\n  Custom Field Values ({len(cfvs)} total):")
    if cfvs:
        for cfv in cfvs:
            cf_ref = cfv.get("custom_field") or {}
            print(f"    Value ID  : {cfv.get('id')}")
            print(f"    CF Def ID : {cf_ref.get('id')}")
            print(f"    Value     : {cfv.get('value')}")
            print()
    else:
        print("    None returned.")

# else:
#     print(f"  ✗ {matter_response.status_code} - {matter_response.text}")