#!/bin/bash
set -e

# Activate the virtual environment so gunicorn can find uvicorn and all
# pip-installed packages. Oryx creates 'antenv' during the build phase;
# the runtime startup wrapper sometimes fails to locate it when using
# compressed deploys, so we activate it explicitly here.
if [ -d "/home/site/wwwroot/antenv" ]; then
    echo "[startup] Activating virtual environment: antenv"
    source /home/site/wwwroot/antenv/bin/activate
elif [ -d "/tmp/8*/antenv" ]; then
    echo "[startup] Activating virtual environment from build cache"
    source /tmp/8*/antenv/bin/activate
fi

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
