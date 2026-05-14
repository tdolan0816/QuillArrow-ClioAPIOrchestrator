import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Azure Web App Domain ─────────────────────────────────────────────────────
# This is the public hostname of the deployed app. Each environment overrides
# it via App Settings; the default here points at the current dev Web App so
# local + first-time deploys behave sensibly. Set explicitly in production.
CLIO_APP_DOMAIN = os.getenv(
    "CLIO_APP_DOMAIN",
    "quillarrow-clioapiorchestrator-dccuhyf6epetf5ek.westus2-01.azurewebsites.net",
)

# ── OAuth App Credentials ────────────────────────────────────────────────────
CLIO_CLIENT_ID = os.getenv("CLIO_CLIENT_ID")
CLIO_CLIENT_SECRET = os.getenv("CLIO_CLIENT_SECRET")
# The new FastAPI OAuth route is mounted at /api/oauth/callback (consistent
# with /api/health, /api/auth/login, etc.). Whatever you set here also needs
# to be registered as an allowed redirect URI on the Clio Developer app.
CLIO_REDIRECT_URI = os.getenv(
    "CLIO_REDIRECT_URI",
    f"https://{CLIO_APP_DOMAIN}/api/oauth/callback",
)

CLIO_AUTH_BASE = os.getenv("CLIO_AUTH_BASE", "https://app.clio.com")
CLIO_API_BASE_URL = os.getenv("CLIO_API_BASE_URL", "https://app.clio.com/api/v4")

# Where OAuth tokens (access + refresh) are persisted between runs *locally*.
# In Azure the DbTokenStore is used automatically (see clio_tokens.py).
TOKEN_FILE = Path(os.getenv("CLIO_TOKEN_FILE", "clio_tokens.json")).resolve()

if not CLIO_CLIENT_ID or not CLIO_CLIENT_SECRET:
    print("ERROR: CLIO_CLIENT_ID and CLIO_CLIENT_SECRET must be set.")
    print("       Copy .env.example to .env and fill in your app credentials,")
    print("       or use one of the launch scripts (start_dev.ps1 / start_prod.ps1).")
    sys.exit(1)
