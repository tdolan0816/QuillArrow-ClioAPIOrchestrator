"""
Clio OAuth flow inside the FastAPI app.

Endpoints:
    GET /api/oauth/login     -- start the OAuth dance (admin only, JWT in
                                ?session=<jwt> because a browser can't send
                                Authorization: Bearer on a plain navigation).
    GET /api/oauth/callback  -- Clio redirects here with ?code= and ?state=;
                                we validate the state cookie, exchange the
                                code for tokens, and persist via the active
                                TokenStore (DbTokenStore in Azure, file locally).
    GET /api/oauth/status    -- non-sensitive flag for the UI: token present? env?

This replaces the standalone clio_oauth_app.py for the deployed path. The
local helper still works in a CLI context, but the deployed app must use this
flow because the App Service filesystem is ephemeral.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Cookie, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt

from clio_client import _default_token_store
from config import (
    CLIO_API_BASE_URL,
    CLIO_AUTH_BASE,
    CLIO_CLIENT_ID,
    CLIO_CLIENT_SECRET,
    CLIO_REDIRECT_URI,
)

from backend.auth import ALGORITHM, SECRET_KEY, USERS

router = APIRouter(tags=["Clio OAuth"])

# Cookie scoped under /api/oauth so it's only sent on this flow's URLs.
# httponly + samesite=lax keeps it inaccessible to JS and intact across the
# Clio -> our-domain redirect.
_STATE_COOKIE = "clio_oauth_state"
_STATE_COOKIE_PATH = "/api/oauth"
_STATE_MAX_AGE_SECS = 300  # 5 minutes is plenty for a redirect dance


def _require_admin_session(token: str) -> str:
    """Validate a JWT from /api/auth/login. Returns the admin username.

    Raises 401 if the token is bad / expired / not admin. We can't use the
    normal OAuth2PasswordBearer dependency here because the JWT comes in as
    a query parameter, not an Authorization header.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        username = None

    if not username or username not in USERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid or expired session token. Get a fresh JWT from "
                "POST /api/auth/login and retry with ?session=<jwt>."
            ),
        )
    if USERS[username].get("role") != "admin":
        # Only admins can rewire the firm-wide Clio connection; non-admins
        # using the app still hit their JWT against /api/auth/login as usual.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can connect Clio for the whole tenant.",
        )
    return username


def _use_secure_cookie() -> bool:
    """Mark the state cookie Secure only when our redirect URI is HTTPS.

    Locally over plain HTTP the Secure flag would suppress the cookie entirely
    and break the callback.
    """
    return CLIO_REDIRECT_URI.lower().startswith("https://")


def _html_page(title: str, body_html: str, status_code: int = 200) -> HTMLResponse:
    """Tiny helper: render a small, dependency-free HTML response."""
    html = (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head>"
        "<body style='font-family: system-ui, -apple-system, sans-serif; "
        "padding: 2rem; max-width: 720px;'>"
        f"<h2>{title}</h2>"
        f"{body_html}"
        "</body></html>"
    )
    return HTMLResponse(content=html, status_code=status_code)


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/oauth/status")
def oauth_status():
    """Non-sensitive status for the UI: is a token stored? which env?"""
    try:
        store = _default_token_store()
        return {
            "clio_env": os.getenv("CLIO_ENV", "dev").lower(),
            "token_present": store.exists(),
            "token_store": store.describe(),
        }
    except Exception as exc:  # noqa: BLE001 -- never crash the UI on this
        return {
            "clio_env": os.getenv("CLIO_ENV", "dev").lower(),
            "token_present": False,
            "token_store": f"unavailable: {exc}",
        }


@router.get("/oauth/login")
def oauth_login(
    session: str = Query(
        ...,
        description="JWT obtained from POST /api/auth/login. Admin role required.",
    )
):
    """Kick off the Clio OAuth flow.

    The flow:
      1. Validate the admin session JWT.
      2. Mint a random CSRF state, set it as an httponly Secure cookie.
      3. 302-redirect the browser to Clio's authorize URL.
    """
    _require_admin_session(session)

    state = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": CLIO_CLIENT_ID,
        "redirect_uri": CLIO_REDIRECT_URI,
        "state": state,
    }
    auth_url = f"{CLIO_AUTH_BASE}/oauth/authorize?{urlencode(params)}"

    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        max_age=_STATE_MAX_AGE_SECS,
        httponly=True,
        secure=_use_secure_cookie(),
        samesite="lax",
        path=_STATE_COOKIE_PATH,
    )
    return response


@router.get("/oauth/callback")
def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    clio_oauth_state: str | None = Cookie(default=None),
):
    """Receive Clio's redirect, exchange the code for tokens, persist them."""
    if error:
        return _html_page(
            "Clio returned an error",
            f"<p>{error_description or error}</p>"
            "<p>Try again from <code>/api/oauth/login</code>.</p>",
            status_code=400,
        )
    if not code:
        return _html_page(
            "Missing authorization code",
            "<p>Clio's redirect did not include an authorization code. "
            "Start the flow again from <code>/api/oauth/login</code>.</p>",
            status_code=400,
        )
    if not state or not clio_oauth_state or state != clio_oauth_state:
        return _html_page(
            "OAuth state mismatch",
            "<p>The state cookie did not match the value Clio returned. This "
            "usually means the flow timed out or a different browser is "
            "completing it. Start the flow again from "
            "<code>/api/oauth/login</code>.</p>",
            status_code=400,
        )

    # Exchange the auth code for real tokens.
    token_resp = requests.post(
        f"{CLIO_AUTH_BASE}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIO_CLIENT_ID,
            "client_secret": CLIO_CLIENT_SECRET,
            "redirect_uri": CLIO_REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )
    if token_resp.status_code != 200:
        return _html_page(
            "Clio token exchange failed",
            f"<p>Clio responded with HTTP {token_resp.status_code}.</p>"
            f"<pre>{token_resp.text}</pre>",
            status_code=502,
        )

    # Persist via the active TokenStore (Db in Azure, file locally).
    store = _default_token_store()
    store.save(token_resp.json())

    env_label = os.getenv("CLIO_ENV", "dev").lower()
    response = _html_page(
        "Clio Authorization Complete",
        f"<p>Environment: <code>{env_label}</code></p>"
        f"<p>Tokens stored at: <code>{store.describe()}</code></p>"
        f"<p>API base: <code>{CLIO_API_BASE_URL}</code></p>"
        "<p>You can close this window. The app will refresh tokens "
        "automatically from now on.</p>",
    )
    # The state cookie has done its job.
    response.delete_cookie(_STATE_COOKIE, path=_STATE_COOKIE_PATH)
    return response
