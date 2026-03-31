import json
import time
import requests
from pathlib import Path

from config import (
    CLIO_CLIENT_ID,
    CLIO_CLIENT_SECRET,
    CLIO_API_BASE_URL,
    CLIO_AUTH_BASE,
    TOKEN_FILE,
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

    def __init__(self, token_file: Path | None = None, base_url: str | None = None):
        # Set the base URL for the Clio API.
        self.base_url = (base_url or CLIO_API_BASE_URL).rstrip("/")
        # Set the token file for the Clio API.
        self._token_file = token_file or TOKEN_FILE
        # Create a session for the Clio API.
        self._session = requests.Session()
        # Set the content type for the Clio API.
        self._session.headers["Content-Type"] = "application/json"

        # Load and set the token for the Clio API.
        self._load_and_set_token()

    # ── Token management ─────────────────────────────────────────────────

    def _load_tokens(self) -> dict:
        # Check if the token file exists.
        if not self._token_file.exists():
            # Raise an exception if the token file does not exist.
            raise ClioAuthError(
                # The message is formatted as "No token file found at {self._token_file}.\n"
                # "Run 'python clio_oauth_app.py' and visit https://localhost:8787/login "
                # "to authorize first."
                f"No token file found at {self._token_file}.\n"
                "Run 'python clio_oauth_app.py' and visit https://localhost:8787/login "
                "to authorize first."
            )
        # Open the token file and load the tokens.
        with self._token_file.open("r", encoding="utf-8") as f:
            # Load the tokens from the token file.
            return json.load(f)

    def _save_tokens(self, payload: dict):
        # Get the current time in seconds since the epoch.
        now = int(time.time())
        # Set the created_at timestamp in the payload.
        payload["created_at"] = now
        # Set the expires_at timestamp in the payload.
        if "expires_in" in payload:
            # Set the expires_at timestamp in the payload.
            payload["expires_at"] = now + int(payload["expires_in"])
        # Open the token file and save the payload.
        with self._token_file.open("w", encoding="utf-8") as f:
            # Save the payload to the token file.
            json.dump(payload, f, indent=2)

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

        # Get the new tokens from the response.
        new_tokens = resp.json()
        # Save the new tokens to the token file.
        self._save_tokens(new_tokens)
        # Print a message to the console.
        print("  Token refreshed and saved.")
        # Return the new tokens.
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
        # Send a request to the Clio API.
        return self.patch(f"{endpoint}/{resource_id}", body=body)

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
