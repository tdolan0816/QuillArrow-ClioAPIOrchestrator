import time
from pathlib import Path

import requests

from config import (
    CLIO_CLIENT_ID,
    CLIO_CLIENT_SECRET,
    CLIO_API_BASE_URL,
    CLIO_AUTH_BASE,
    TOKEN_FILE,
)
from clio_tokens import (
    FileTokenStore,
    TokenStore,
    TokenStoreMissing,
)


class ClioAuthError(Exception):
    """Raised when tokens are missing or cannot be refreshed."""


class ClioAPIError(Exception):
    """Raised when the Clio API returns a non-success status."""

    # ClioAPIError class is used to raise an exception when the Clio API returns a non-success status.
    # It takes the status code, reason, and body of the response and raises an exception with the appropriate message.
    def __init__(self, status_code, reason, body):
        # Initialize the ClioAPIError instance with the status code, reason, and body.
        # The super().__init__() method is used to call the parent class (Exception) constructor and pass the message.
        self.status_code = status_code
        # Set the reason for the error.
        self.reason = reason
        # Set the body of the response.
        self.body = body
        # Call the parent class (Exception) constructor and pass the message.
        # The message is formatted as "Clio API {status_code} {reason}: {body}".
        super().__init__(f"Clio API {status_code} {reason}: {body}")


class ClioClient:
    """
    Reusable client for the Clio Manage v4 API.

    Handles OAuth token management (load, refresh, persist),
    request building, automatic pagination, rate-limit back-off,
    and structured error handling.
    """

    RATE_LIMIT_STATUS = 429
    MAX_RETRIES = 3
    DEFAULT_LIMIT = 200
    TOKEN_EXPIRY_BUFFER_SECS = 60  # refresh this many seconds before actual expiry

    def __init__(
        self,
        token_store: TokenStore | None = None,
        base_url: str | None = None,
        *,
        token_file: Path | None = None,
    ):
        """
        Args:
            token_store: where to read/write Clio OAuth tokens. If omitted,
                falls back to the default store (DB-backed when DATABASE_URL is
                Azure SQL, file-backed otherwise).
            base_url: override the Clio API base URL.
            token_file: legacy compatibility shim -- if given, wraps the path
                in a FileTokenStore. Prefer ``token_store=`` in new code.
        """
        self.base_url = (base_url or CLIO_API_BASE_URL).rstrip("/")

        if token_store is not None:
            self._token_store: TokenStore = token_store
        elif token_file is not None:
            self._token_store = FileTokenStore(token_file)
        else:
            self._token_store = _default_token_store()

        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

        # Load and set the token for the Clio API.
        self._load_and_set_token()

    # ── Token management ─────────────────────────────────────────────────

    @property
    def token_store(self) -> TokenStore:
        """Expose the underlying TokenStore (used by the OAuth callback route)."""
        return self._token_store

    def _load_tokens(self) -> dict:
        try:
            return self._token_store.load()
        except TokenStoreMissing as exc:
            # Translate to the existing ClioAuthError so callers keep working.
            raise ClioAuthError(str(exc)) from exc

    def _save_tokens(self, payload: dict) -> dict:
        return self._token_store.save(payload)

    def _is_token_expired(self, tokens: dict) -> bool:
        # Get the expires_at timestamp from the payload.
        expires_at = tokens.get("expires_at")
        # Check if the token is expired.
        if not expires_at:
            return True
        # Check if the token is expired.
        return time.time() >= (expires_at - self.TOKEN_EXPIRY_BUFFER_SECS)

    def _refresh_access_token(self, tokens: dict) -> dict:
        # Get the refresh_token from the payload.
        refresh_token = tokens.get("refresh_token")
        # Check if the refresh_token is missing.
        if not refresh_token:
            # Raise an exception if the refresh_token is missing.
            raise ClioAuthError(
                # The message is formatted as "No refresh_token in token file. Re-run the OAuth flow:\n"
                # "  python clio_oauth_app.py"
                "No refresh_token in token file. Re-run the OAuth flow:\n"
                "  python clio_oauth_app.py"
            )

        # Print a message to the console.
        print("  Access token expired — refreshing automatically...")
        # Send a POST request to the Clio API to refresh the access token.
        resp = requests.post(
            # The URL for the Clio API to refresh the access token.
            f"{CLIO_AUTH_BASE}/oauth/token",
            # The data to send in the POST request.
            data={
                "grant_type": "refresh_token",
                # The client ID for the Clio API.
                "client_id": CLIO_CLIENT_ID,
                # The client secret for the Clio API.
                "client_secret": CLIO_CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        # Check if the token refresh failed.
        if resp.status_code != 200:
            # Raise an exception if the token refresh failed.
            raise ClioAuthError(
                # The message is formatted as "Token refresh failed ({resp.status_code}): {resp.text}\n"
                # "You may need to re-authorize: python clio_oauth_app.py"
                f"Token refresh failed ({resp.status_code}): {resp.text}\n"
                "You may need to re-authorize: python clio_oauth_app.py"
            )

        # Save the new tokens (timestamps stamped by the store) and return
        # the post-save dict so the caller sees expires_at populated.
        new_tokens = self._save_tokens(resp.json())
        print("  Token refreshed and saved.")
        return new_tokens

    def _load_and_set_token(self):
        """Load tokens from file, refresh if expired, set on session."""
        tokens = self._load_tokens()
        # Check if the token is expired.
        if self._is_token_expired(tokens):
            tokens = self._refresh_access_token(tokens)
        # Set the authorization header on the session.
        self._session.headers["Authorization"] = f"Bearer {tokens['access_token']}"

    def _ensure_valid_token(self):
        """Called before each request to check token freshness."""
        tokens = self._load_tokens()
        # Check if the token is expired.
        if self._is_token_expired(tokens):
            tokens = self._refresh_access_token(tokens)
            # Set the authorization header on the session.
            self._session.headers["Authorization"] = f"Bearer {tokens['access_token']}"

    # ── Core HTTP verbs ──────────────────────────────────────────────────

    def _request(self, method, endpoint, params=None, json_body=None):
        """
        Send a single request with automatic token refresh and retry on 429.
        """
        self._ensure_valid_token()
        # Build the URL for the request.
        url = self._build_url(endpoint)

        # Send a request to the Clio API.
        for attempt in range(1, self.MAX_RETRIES + 1):
            # Send a request to the Clio API.
            resp = self._session.request(
                method, url, params=params, json=json_body, timeout=30
            )
            # Check if the request failed.
            if resp.status_code == 401:
                # Print a message to the console.
                print("  Got 401 — forcing token refresh...")
                # Load the tokens from the token file.
                tokens = self._load_tokens()
                # Refresh the access token.
                tokens = self._refresh_access_token(tokens)
                # Set the authorization header on the session.
                self._session.headers["Authorization"] = f"Bearer {tokens['access_token']}"
                continue

            # Check if the request is rate limited.
            if resp.status_code == self.RATE_LIMIT_STATUS:
                # Get the retry after time from the response headers.
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                # Print a message to the console.
                print(f"  Rate limited. Waiting {wait}s (attempt {attempt}/{self.MAX_RETRIES})...")
                # Wait for the retry after time.
                time.sleep(wait)
                continue

            # Check if the request failed.
            if resp.status_code >= 400:
                # Raise an exception if the request failed.
                raise ClioAPIError(resp.status_code, resp.reason, resp.text)

            # Return the response.
            return resp.json()

        raise ClioAPIError(429, "Rate Limited", "Max retries exceeded")

    def _build_url(self, endpoint):
        # Strip the leading slash from the endpoint.
        endpoint = endpoint.lstrip("/")
        # Check if the endpoint starts with http.
        if endpoint.startswith("http"):
            # Return the endpoint.
            return endpoint
        # Return the base URL and the endpoint.
        return f"{self.base_url}/{endpoint}"

    def get(self, endpoint, fields=None, limit=None, **extra_params):
        """GET a single page from an endpoint."""
        # Set the parameters for the request.
        params = {**extra_params}
        # Check if the fields are provided.
        if fields:
            # Set the fields for the request.
            params["fields"] = ",".join(fields) if isinstance(fields, list) else fields
        # Check if the limit is provided.
        if limit:
            # Set the limit for the request.
            params["limit"] = limit
        # Send a request to the Clio API.
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint, body):
        """POST (create) a resource."""
        # Send a request to the Clio API.
        return self._request("POST", endpoint, json_body=body)

    def patch(self, endpoint, body):
        """PATCH (update) a resource."""
        # Send a request to the Clio API.
        return self._request("PATCH", endpoint, json_body=body)

    def delete(self, endpoint):
        """DELETE a resource."""
        # Send a request to the Clio API.
        return self._request("DELETE", endpoint)

    # ── Pagination ───────────────────────────────────────────────────────

    def get_all(self, endpoint, fields=None, limit=None, **extra_params):
        """
        Auto-paginate through all results for a GET endpoint.
        Yields individual records so you can process them as a stream.
        """
        # Set the page limit for the request.
        page_limit = limit or self.DEFAULT_LIMIT
        # Set the parameters for the request.
        params = {**extra_params, "limit": page_limit}
        # Check if the fields are provided.
        if fields:
            # Set the fields for the request.
            params["fields"] = ",".join(fields) if isinstance(fields, list) else fields
        # Set the current endpoint for the request.
        current_endpoint = endpoint
        # Send a request to the Clio API.
        while current_endpoint:
            # Send a request to the Clio API.
            data = self._request("GET", current_endpoint, params=params)

            records = data.get("data", [])
            # Yield the records.
            for record in records:
                yield record

            # Get the next URL from the response.
            next_url = data.get("meta", {}).get("paging", {}).get("next")
            # Check if the next URL is provided.
            if next_url:
                # Set the current endpoint for the request.
                current_endpoint = next_url
                # Set the parameters for the request.
                params = None
            else:
                # Set the current endpoint for the request.
                current_endpoint = None

    # ── Convenience helpers ──────────────────────────────────────────────

    def get_by_id(self, endpoint, resource_id, fields=None):
        """GET a single resource by ID."""
        # Send a request to the Clio API.
        return self.get(f"{endpoint}/{resource_id}", fields=fields)

    def update_by_id(self, endpoint, resource_id, body):
        """PATCH a single resource by ID."""
        # Send a PATCH request to the Clio API.
        return self.patch(f"{endpoint}/{resource_id}", body=body)
        # Return the updated resource.

    def bulk_update(self, endpoint, updates, progress=True):
        """
        Apply a list of updates sequentially.

        Each entry in `updates` should be a dict with:
            - "id": the resource ID
            - "body": the JSON body to PATCH

        Returns a list of (id, success, response_or_error) tuples.
        """
        # Set the results for the request.
        results = []
        # Set the total for the request.
        total = len(updates)
        for i, update in enumerate(updates, 1):
            # Set the resource ID for the request.
            rid = update["id"]
            # Set the body for the request.
            body = update["body"]
            # Check if the progress is provided.
            if progress:
                # Print a message to the console.
                print(f"  [{i}/{total}] Updating {endpoint}/{rid} ...")
            try:
                # Send a request to the Clio API.
                resp = self.update_by_id(endpoint, rid, body)
                results.append((rid, True, resp))
            except ClioAPIError as e:
                # Print a message to the console.
                print(f"  FAILED {endpoint}/{rid}: {e}")
                results.append((rid, False, str(e)))
        return results


# ── Default TokenStore factory ─────────────────────────────────────────────
# Lives at module-bottom (not at import-time) so importing ClioClient never
# requires SQLAlchemy if the caller is a pure CLI script. The DB-backed store
# is only loaded when we actually need it.
def _default_token_store() -> TokenStore:
    """Return the auto-selected TokenStore.

    Prefers ``DbTokenStore`` when the backend layer is importable AND
    ``DATABASE_URL`` points at Azure SQL. Falls back to ``FileTokenStore`` at
    ``TOKEN_FILE`` otherwise -- which keeps ``run.py`` and local dev unchanged.
    """
    try:
        from backend.clio_token_store_db import get_default_token_store
    except Exception:  # noqa: BLE001 -- backend may not be on sys.path (CLI use)
        return FileTokenStore(TOKEN_FILE)
    return get_default_token_store()
