"""
OAuth helper for Clio — handles initial authorization and token storage.

Deployed to Azure Web App:
    https://quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net

Endpoints:
    GET  /              — Health check / landing page
    GET  /login         — Starts OAuth flow (redirects to Clio)
    GET  /oauth/callback— Clio redirects back here with auth code; exchanges for tokens
    POST /clio/deauth   — Deauthorization webhook (optional)

After initial auth, the ClioClient handles token refresh automatically — you
should rarely need to re-authorize unless you revoke the app in Clio.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from flask import Flask, redirect, request

from config import (
    CLIO_CLIENT_ID,
    CLIO_CLIENT_SECRET,
    CLIO_REDIRECT_URI,
    CLIO_AUTH_BASE,
    CLIO_APP_DOMAIN,
    TOKEN_FILE,
)

app = Flask(__name__)

# Save the tokens to the token file.
def save_tokens(payload: dict) -> Path:
    """Persist token payload with computed expiration timestamp."""
    # Get the current time in seconds since the epoch.
    now = int(time.time())
    # Set the created_at timestamp in the payload.
    payload["created_at"] = now
    # Check if the expires_in is provided.
    if "expires_in" in payload:
        # Set the expires_at timestamp in the payload.
        payload["expires_at"] = now + int(payload["expires_in"])

    # Create the parent directory if it doesn't exist.
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Open the token file and save the payload.
    with TOKEN_FILE.open("w", encoding="utf-8") as f:
        # Save the payload to the token file.
        json.dump(payload, f, indent=2)
    # Return the token file.
    return TOKEN_FILE


# Get the index page.
@app.get("/")
def index():
    # Print a message to the console.
    print("Getting the index page...")
    # Return the index page.
    return (
        "<h2>Clio API Orchestrator — OAuth</h2>"
        "<p>Visit <a href='/login'>/login</a> to authorize with Clio.</p>"
    )


# Get the login page.
@app.get("/login")
def login():
    # Generate a random state.
    state = secrets.token_urlsafe(16)
    # Set the state in the app configuration.
    app.config["OAUTH_STATE"] = state

    # Set the parameters for the request.
    params = {
        "response_type": "code",
        "client_id": CLIO_CLIENT_ID,
        "redirect_uri": CLIO_REDIRECT_URI,
        "state": state,
    }

    # Set the authorization URL.
    auth_url = f"{CLIO_AUTH_BASE}/oauth/authorize?{urlencode(params)}"
    # Redirect to the authorization URL.
    return redirect(auth_url)


# Get the OAuth callback page.
@app.get("/oauth/callback")
def oauth_callback():
    # Check if the error is provided.
    if error := request.args.get("error"):
        # Return a message if the error is provided.
        return f"OAuth error: {error}", 400
    # Get the code from the request.

    code = request.args.get("code")
    if not code:
        # Return a message if the code is missing.
        return "Missing authorization code.", 400

    # Get the expected state from the app configuration.
    expected_state = app.config.get("OAUTH_STATE")
    # Check if the state is provided.
    if expected_state and request.args.get("state") != expected_state:
        return "Invalid OAuth state.", 400

    # Send a request to the Clio API.
    response = requests.post(
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

    # Check if the response status code is not 200.
    if response.status_code != 200:
        # Return a message if the response status code is not 200.
        return f"Token request failed ({response.status_code}): {response.text}", 400

    # Save the tokens to the token file.
    token_path = save_tokens(response.json())
    # Print a message to the console.
    print(f"Tokens saved to {token_path}.")
    # Return a message if the tokens are saved.
    return (
        "<h2>Authorization Complete</h2>"
        f"<p>Tokens saved to <code>{token_path}</code>.</p>"
        "<p>The orchestrator will now auto-refresh tokens as needed.</p>"
        "<p>You can close this window and use <code>python run.py</code> "
        "or your launch scripts.</p>"
    )


@app.post("/clio/deauth")
def deauthorize():
    # Print a message to the console.
    print("Deauthorizing the Clio API...")
    # Return a message if the Clio API is deauthorized.
    return "", 204


if __name__ == "__main__":
    # Get the port from the environment variables.
    port = int(os.environ.get("PORT", "8787"))
    # Print a message to the console.
    print(f"Starting Clio OAuth server on port {port}...")
    # Print a message to the console.
    print(f"  Redirect URI: {CLIO_REDIRECT_URI}")
    # Print a message to the console.
    print(f"  Visit https://{CLIO_APP_DOMAIN}/login to authorize.")
    # Run the app.
    app.run(
        # Set the host to 0.0.0.0.
        host="0.0.0.0",
        # Set the port to the port from the environment variables.
        port=port,
    )
