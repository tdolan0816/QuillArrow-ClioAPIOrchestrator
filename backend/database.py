"""
Database setup for the Clio API Orchestrator.

Current implementation: SQLite (zero infrastructure, single file).
Future: swap connection string for Azure SQL — same schema, same queries.

The database stores:
    - audit_log: every write operation with who, when, what, and before/after values

Usage:
    from backend.database import get_db, init_db

    # At app startup:
    init_db()

    # In a route:
    def my_route(db: sqlite3.Connection = Depends(get_db)):
        db.execute("INSERT INTO ...")
"""

import sqlite3
from pathlib import Path

# ── Database file location ───────────────────────────────────────────────────
# Stored in the project root next to clio_tokens.json.
# SQLite creates the file automatically if it doesn't exist.
DB_PATH = Path(__file__).resolve().parent.parent / "orchestrator.db"


def get_connection() -> sqlite3.Connection:
    """
    Open a connection to the SQLite database.
    row_factory=sqlite3.Row makes rows accessible by column name (like a dict).
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    return conn


def get_db():
    """
    FastAPI dependency that provides a database connection.
    Automatically closes the connection after the request completes.

    Usage in routes:
        def my_route(db: sqlite3.Connection = Depends(get_db)):
            ...
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """
    Create database tables if they don't already exist.
    Called once at app startup.
    """
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
                username    TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                endpoint    TEXT,
                matter_id   TEXT,
                field_name  TEXT,
                details     TEXT,
                before_value TEXT,
                after_value  TEXT,
                status      TEXT    NOT NULL DEFAULT 'success',
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_username  ON audit_log(username);
            CREATE INDEX IF NOT EXISTS idx_audit_action    ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_matter_id ON audit_log(matter_id);
        """)
        conn.commit()
        print(f"  [DB] Audit database ready at {DB_PATH}")
    finally:
        conn.close()
