"""
Token storage abstraction for Clio OAuth credentials.

Two implementations live in the project today:

    FileTokenStore  -- local dev (writes JSON to CLIO_TOKEN_FILE)
    DbTokenStore    -- Azure / production (single row in clio_tokens table)
                       Lives in backend/clio_token_store_db.py so it can import
                       SQLAlchemy + the engine without forcing that dependency
                       on CLI-only callers (run.py).

Designed so a future KeyVaultTokenStore is a drop-in replacement -- the only
contract ClioClient depends on is `TokenStore` below.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path


class TokenStoreError(Exception):
    """Base class for token-store problems."""


class TokenStoreMissing(TokenStoreError):
    """Raised when no token has been persisted yet."""


class TokenStore(ABC):
    """Abstract Clio token persistence."""

    @abstractmethod
    def load(self) -> dict:
        """Return the stored token payload.

        Raises:
            TokenStoreMissing: if no token has been persisted yet.
        """

    @abstractmethod
    def save(self, payload: dict) -> dict:
        """Persist payload (with computed created_at / expires_at). Returns the stored payload."""

    @abstractmethod
    def exists(self) -> bool:
        """Return True if a token is currently stored."""

    @abstractmethod
    def describe(self) -> str:
        """Short human-readable description for logs / health endpoint."""


def stamp_timestamps(payload: dict) -> dict:
    """Return a copy of payload with created_at + expires_at filled in.

    `expires_at` is derived from `expires_in` when present. Both timestamps are
    unix epoch seconds (int) so they sort cleanly in SQL.
    """
    now = int(time.time())
    payload = dict(payload)  # shallow copy
    payload["created_at"] = now
    if "expires_in" in payload:
        payload["expires_at"] = now + int(payload["expires_in"])
    return payload


class FileTokenStore(TokenStore):
    """JSON-file token store -- used for local dev."""

    def __init__(self, path: Path | str):
        self._path = Path(path).resolve()

    def load(self) -> dict:
        if not self._path.exists():
            raise TokenStoreMissing(
                f"No token file found at {self._path}. "
                "Run 'python clio_oauth_app.py' (or visit /api/oauth/login on the "
                "deployed app) to authorize first."
            )
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, payload: dict) -> dict:
        payload = stamp_timestamps(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to a temp file then rename so a crash mid-write
        # never leaves a half-written tokens.json on disk.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(self._path)
        return payload

    def exists(self) -> bool:
        return self._path.exists()

    def describe(self) -> str:
        return f"file:{self._path}"
