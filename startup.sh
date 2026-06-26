#!/bin/bash
set -e

# Disable Azure's auto-injected OpenTelemetry agent. It has a bug where
# _get_route_details crashes on FastAPI's _IncludedRouter objects.
# Removing /agents/python from PYTHONPATH prevents it from loading entirely.
export PYTHONPATH="${PYTHONPATH/\/agents\/python:/}"
export PYTHONPATH="${PYTHONPATH/\/agents\/python/}"
export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="fastapi,starlette,asgi"

# Install Microsoft ODBC Driver 18 if it isn't already present.
# This runs once per container instance start; it's idempotent.
if ! command -v odbcinst &> /dev/null || ! odbcinst -q -d | grep -q "ODBC Driver 18"; then
    echo "[startup] Installing Microsoft ODBC Driver 18 for SQL Server..."
    curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
    curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        | tee /etc/apt/sources.list.d/mssql-release.list > /dev/null
    apt-get update -y
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
    echo "[startup] ODBC Driver 18 installed."
fi

# Hand off to gunicorn.
# --timeout 300: billing cache refresh can paginate Clio for minutes on the
#   first full-window seed; 120s was killing workers mid-upsert (08S01).
# --preload: import the app once in the master process BEFORE forking workers,
#   so init_db() runs exactly once (no SQLite table-creation race).
exec gunicorn --preload -w 4 -t 300 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 backend.main:app
