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

# The default Node.js in the Oryx Python build image is v14, which is
# too old for Vite 8, Tailwind 4, and React Router 7 (all require 20+).
# Install Node.js 20 LTS from the official distribution.
echo "[post_build] Installing Node.js 20 LTS..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
apt-get install -y nodejs > /dev/null 2>&1
echo "[post_build] Node.js version: $(node --version)"

echo "[post_build] Installing frontend dependencies..."
cd frontend
npm install --production=false

echo "[post_build] Building React frontend (vite build)..."
npm run build

echo "[post_build] Frontend built successfully."
ls -la dist/
