#!/bin/bash
# Post-build script for Azure App Service (Oryx).
#
# Oryx runs this AFTER the Python environment is set up (requirements.txt
# installed) but BEFORE the app starts. It builds the React frontend so
# that frontend/dist/ exists when gunicorn boots and FastAPI mounts it.
#
# Triggered by the App Setting:
#   POST_BUILD_COMMAND=scripts/post_build.sh
#
# Why this exists: frontend/dist/ is gitignored (build artifact), so it
# doesn't travel with the source code. This script rebuilds it on every
# deploy, ensuring the UI is always present without manual npm run build.

set -e

echo "[post_build] Installing Node.js dependencies for frontend..."
cd frontend
npm install --production=false

echo "[post_build] Building React frontend (vite build)..."
npm run build

echo "[post_build] Frontend built successfully → frontend/dist/"
