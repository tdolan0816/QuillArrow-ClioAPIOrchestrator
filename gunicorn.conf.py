"""
Gunicorn config for the Azure App Service container.

We start gunicorn with ``--preload`` so backend.main (and therefore init_db())
is imported once in the master process before workers fork. This avoids each
of the four uvicorn workers racing to create Azure SQL tables on cold start.

The catch: SQLAlchemy's connection pool is created in the master too. When
the master forks, every worker inherits the same open TCP sockets to Azure
SQL. The first per-worker query then trips ``08S01 TCP Provider: Error code
0x20 (32)`` (broken pipe) because two processes cannot share one pyodbc
connection. Prod logs on 2026-09-22 at 18:31:14 showed exactly this pattern
inside ``clio_tokens.load``.

SQLAlchemy's documented fix is to dispose the inherited pool in each worker
right after fork, so the worker opens fresh connections on demand. Passing
``close=False`` leaves the master's still-open sockets alone (the master is
not going to use them anyway) instead of double-closing them from the child.

Reference: https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork
"""


def post_fork(server, worker):
    from backend.database import get_engine

    get_engine().dispose(close=False)
