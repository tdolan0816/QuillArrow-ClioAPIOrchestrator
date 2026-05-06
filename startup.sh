#!/bin/bash
set -e

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
exec gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 backend.main:app