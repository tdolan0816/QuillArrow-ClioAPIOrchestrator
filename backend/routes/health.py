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

    This endpoint intentionally avoids any database calls so that Azure's
    Health Check probe (every 10 min) does not prevent the serverless SQL
    databases from auto-pausing.
    """
    return {
        "status": "ok",
        "clio_api_url": CLIO_API_BASE_URL,
        "clio_env": os.getenv("CLIO_ENV", "dev").lower(),
    }
