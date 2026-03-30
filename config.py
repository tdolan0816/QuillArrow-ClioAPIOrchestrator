import os
import sys
from dotenv import load_dotenv

load_dotenv()

CLIO_ACCESS_TOKEN = os.getenv("CLIO_ACCESS_TOKEN")
CLIO_API_BASE_URL = os.getenv("CLIO_API_BASE_URL", "https://app.clio.com/api/v4")

if not CLIO_ACCESS_TOKEN:
    print("ERROR: CLIO_ACCESS_TOKEN not set. Copy .env.example to .env and add your token.")
    sys.exit(1)
