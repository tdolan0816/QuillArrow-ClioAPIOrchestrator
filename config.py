import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Azure Web App Domain ─────────────────────────────────────────────────────
CLIO_APP_DOMAIN = os.getenv(
    "CLIO_APP_DOMAIN",
    "quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net",
)

# ── OAuth App Credentials ────────────────────────────────────────────────────
CLIO_CLIENT_ID = os.getenv("CLIO_CLIENT_ID")
CLIO_CLIENT_SECRET = os.getenv("CLIO_CLIENT_SECRET")
CLIO_REDIRECT_URI = os.getenv(
    "CLIO_REDIRECT_URI",
    f"https://{CLIO_APP_DOMAIN}/oauth/callback",
)

CLIO_AUTH_BASE = os.getenv("CLIO_AUTH_BASE", "https://app.clio.com")
CLIO_API_BASE_URL = os.getenv("CLIO_API_BASE_URL", "https://app.clio.com/api/v4")

# Where OAuth tokens (access + refresh) are persisted between runs
TOKEN_FILE = Path(os.getenv("CLIO_TOKEN_FILE", "clio_tokens.json")).resolve()

if not CLIO_CLIENT_ID or not CLIO_CLIENT_SECRET:
    print("ERROR: CLIO_CLIENT_ID and CLIO_CLIENT_SECRET must be set.")
    print("       Copy .env.example to .env and fill in your app credentials,")
    print("       or use one of the launch scripts (start_dev.ps1 / start_prod.ps1).")
    sys.exit(1)
