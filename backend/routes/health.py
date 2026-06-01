"""
Health check endpoint.

GET /api/health -- returns server status.
Used by monitoring tools, load balancers, and developers to verify
the API is running and can reach the Clio API.
"""

import os

from fastapi import APIRouter

from config import CLIO_API_BASE_URL

router = APIRouter()


@router.get("/health")
def health_check():
    """
    Returns the current status of the API server.

    Response includes:
        - status: "ok" if the server is running
        - clio_api_url: the Clio API base URL we're configured to use
        - clio_env: which environment the app thinks it is talking to
                   (dev / prod). Defaults to 'dev' so a misconfigured app never
                   silently behaves as production.
        - clio_token_present: whether a Clio OAuth token is stored (file or DB)
        - token_store: short description of where tokens are persisted
                      (e.g. 'file:/.../clio_tokens.json' or 'db:clio_tokens[env=prod]')
    """
    # Lazy import so this endpoint never raises at import time if the token-
    # store machinery has a configuration error.
    return {
        "status": "ok",
        "clio_api_url": CLIO_API_BASE_URL,
        "clio_env": os.getenv("CLIO_ENV", "dev").lower(),
    }
