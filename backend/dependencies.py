"""
Shared FastAPI dependencies.

Dependencies are functions that FastAPI calls automatically before your route
handler runs. They handle common setup like "get the Clio client" or
"verify the user is logged in" so each route doesn't repeat that logic.

Usage in any route:
    from backend.dependencies import require_auth, get_clio_client

    @router.get("/example")
    def my_route(
        user: UserInfo = Depends(require_auth),
        client: ClioClient = Depends(get_clio_client),
    ):
        # user is the authenticated user
        # client is a ready-to-use ClioClient instance
        ...
"""

from fastapi import Depends

from clio_client import ClioClient
from backend.auth import get_current_user, UserInfo

# ── Clio Client ──────────────────────────────────────────────────────────────
# Singleton instance — created once and reused across all requests.
# The ClioClient handles its own token refresh, so one instance is safe.
_clio_client: ClioClient | None = None


def get_clio_client() -> ClioClient:
    """
    Returns a shared ClioClient instance.
    Created on first call, reused after that.
    """
    global _clio_client
    if _clio_client is None:
        _clio_client = ClioClient()
    return _clio_client


# ── Auth shortcut ────────────────────────────────────────────────────────────
# Just an alias so route files can import from one place.
def require_auth(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """Require a valid JWT token. Returns the authenticated user."""
    return user
