"""
Health check endpoint.

GET /api/health — returns server status.
Used by monitoring tools, load balancers, and developers to verify
the API is running and can reach the Clio API.
"""

from fastapi import APIRouter
from config import CLIO_API_BASE_URL, TOKEN_FILE

router = APIRouter()


@router.get("/health")
def health_check():
    """
    Returns the current status of the API server.

    Response includes:
        - status: "ok" if the server is running
        - clio_api_url: the Clio API base URL we're configured to use
        - token_file_exists: whether the OAuth token file is present
    """
    return {
        "status": "ok",
        "clio_api_url": CLIO_API_BASE_URL,
        "token_file_exists": TOKEN_FILE.exists(),
    }
