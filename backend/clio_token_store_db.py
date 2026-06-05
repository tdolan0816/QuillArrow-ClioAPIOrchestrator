"""
SQL-backed Clio token store + factory.

Used in Azure (or any non-SQLite DATABASE_URL) where the App Service filesystem
is ephemeral. Picks which row of the ``clio_tokens`` table to read/write by
the ``CLIO_ENV`` env var (``'dev'`` / ``'prod'``); defaults to ``'dev'`` so a
mistake on the prod side never silently overwrites prod tokens.
"""

from __future__ import annotations

import datetime as _dt
import os

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

from clio_tokens import (
    FileTokenStore,
    TokenStore,
    TokenStoreMissing,
    stamp_timestamps,
)

from backend.database import (
    DATABASE_URL,
    clio_tokens as _clio_tokens_table,
    get_engine,
)


class DbTokenStore(TokenStore):
    """SQLAlchemy-backed Clio token store. One row per environment."""

    def __init__(self, engine: Engine | None = None, env: str | None = None):
        self._engine = engine or get_engine()
        self._env = (env or os.getenv("CLIO_ENV", "dev")).lower()

    @property
    def env(self) -> str:
        return self._env

    def load(self) -> dict:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    select(_clio_tokens_table).where(
                        _clio_tokens_table.c.env == self._env
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise TokenStoreMissing(
                f"No Clio token row in clio_tokens for env='{self._env}'. "
                "Visit /api/oauth/login on the deployed app to authorize."
            )
        return {
            "access_token": row["access_token"],
            "refresh_token": row["refresh_token"],
            "token_type": row["token_type"] or "Bearer",
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
        }

    def save(self, payload: dict) -> dict:
        payload = stamp_timestamps(payload)
        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()

        # Dialect-neutral upsert: delete-then-insert inside a single transaction.
        # The clio_tokens table is single-row-per-env with no foreign keys, so
        # this is safe across SQLite and MSSQL without dialect-specific MERGE.
        with self._engine.begin() as conn:
            conn.execute(
                delete(_clio_tokens_table).where(
                    _clio_tokens_table.c.env == self._env
                )
            )
            conn.execute(
                _clio_tokens_table.insert().values(
                    env=self._env,
                    access_token=payload["access_token"],
                    refresh_token=payload["refresh_token"],
                    token_type=payload.get("token_type", "Bearer"),
                    expires_at=int(payload["expires_at"]),
                    created_at=int(payload["created_at"]),
                    updated_at=now_iso,
                )
            )
        return payload

    def exists(self) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(_clio_tokens_table.c.env).where(
                    _clio_tokens_table.c.env == self._env
                )
            ).first()
        return row is not None

    def describe(self) -> str:
        return f"db:clio_tokens[env={self._env}]"


def get_default_token_store() -> TokenStore:
    """Auto-select implementation based on deployment context.

    - mssql+pyodbc (Azure SQL) -> DbTokenStore
    - Azure App Service without Azure SQL (SQLite under /home) -> DbTokenStore
    - local machine (no WEBSITE_SITE_NAME) -> FileTokenStore at TOKEN_FILE

    DbTokenStore on Azure avoids writing clio_tokens.json under /tmp/..., which
    is ephemeral and disappears on every container restart.
    """
    if DATABASE_URL.startswith("mssql+") or os.getenv("WEBSITE_SITE_NAME"):
        return DbTokenStore()

    # Local dev only. Imported lazily so `config.py` is only required when
    # the file store is actually needed (it sys.exit()s if CLIO_CLIENT_ID is
    # missing, which we don't want to trigger in pure-DB contexts).
    from config import TOKEN_FILE
    return FileTokenStore(TOKEN_FILE)
