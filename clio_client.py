import time
import requests
from config import CLIO_ACCESS_TOKEN, CLIO_API_BASE_URL


class ClioAPIError(Exception):
    """Raised when the Clio API returns a non-success status."""

    def __init__(self, status_code, reason, body):
        self.status_code = status_code
        self.reason = reason
        self.body = body
        super().__init__(f"Clio API {status_code} {reason}: {body}")


class ClioClient:
    """
    Reusable client for the Clio Manage v4 API.

    Handles authentication, request building, automatic pagination,
    rate-limit back-off, and structured error handling.
    """

    RATE_LIMIT_STATUS = 429
    MAX_RETRIES = 3
    DEFAULT_LIMIT = 200  # Clio's max per page

    def __init__(self, access_token=None, base_url=None):
        self.base_url = (base_url or CLIO_API_BASE_URL).rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {access_token or CLIO_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        })

    # ── Core HTTP verbs ──────────────────────────────────────────────────

    def _request(self, method, endpoint, params=None, json_body=None):
        """
        Send a single request with retry on 429 (rate limit).
        Returns the parsed JSON response.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        for attempt in range(1, self.MAX_RETRIES + 1):
            resp = self._session.request(
                method, url, params=params, json=json_body, timeout=30
            )

            if resp.status_code == self.RATE_LIMIT_STATUS:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"  Rate limited. Waiting {wait}s (attempt {attempt}/{self.MAX_RETRIES})...")
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                raise ClioAPIError(resp.status_code, resp.reason, resp.text)

            return resp.json()

        raise ClioAPIError(429, "Rate Limited", "Max retries exceeded")

    def get(self, endpoint, fields=None, limit=None, **extra_params):
        """GET a single page from an endpoint."""
        params = {**extra_params}
        if fields:
            params["fields"] = ",".join(fields) if isinstance(fields, list) else fields
        if limit:
            params["limit"] = limit
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint, body):
        """POST (create) a resource."""
        return self._request("POST", endpoint, json_body=body)

    def patch(self, endpoint, body):
        """PATCH (update) a resource."""
        return self._request("PATCH", endpoint, json_body=body)

    def delete(self, endpoint):
        """DELETE a resource."""
        return self._request("DELETE", endpoint)

    # ── Pagination ───────────────────────────────────────────────────────

    def get_all(self, endpoint, fields=None, limit=None, **extra_params):
        """
        Auto-paginate through all results for a GET endpoint.
        Yields individual records so you can process them as a stream.
        """
        page_limit = limit or self.DEFAULT_LIMIT
        params = {**extra_params, "limit": page_limit}
        if fields:
            params["fields"] = ",".join(fields) if isinstance(fields, list) else fields

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        while url:
            data = self._request("GET", url.replace(self.base_url + "/", ""), params=params)

            section_key = endpoint.lstrip("/").split("?")[0]
            records = data.get("data", data.get(section_key, []))
            for record in records:
                yield record

            paging = data.get("meta", {}).get("paging", {})
            url = paging.get("next")
            params = None  # subsequent pages use the full URL from `next`

    # ── Convenience helpers ──────────────────────────────────────────────

    def get_by_id(self, endpoint, resource_id, fields=None):
        """GET a single resource by ID."""
        return self.get(f"{endpoint}/{resource_id}", fields=fields)

    def update_by_id(self, endpoint, resource_id, body):
        """PATCH a single resource by ID."""
        return self.patch(f"{endpoint}/{resource_id}", body=body)

    def bulk_update(self, endpoint, updates, progress=True):
        """
        Apply a list of updates sequentially.

        Each entry in `updates` should be a dict with:
            - "id": the resource ID
            - "body": the JSON body to PATCH

        Returns a list of (id, success, response_or_error) tuples.
        """
        results = []
        total = len(updates)
        for i, update in enumerate(updates, 1):
            rid = update["id"]
            body = update["body"]
            if progress:
                print(f"  [{i}/{total}] Updating {endpoint}/{rid} ...")
            try:
                resp = self.update_by_id(endpoint, rid, body)
                results.append((rid, True, resp))
            except ClioAPIError as e:
                print(f"  FAILED {endpoint}/{rid}: {e}")
                results.append((rid, False, str(e)))
        return results
