#!/bin/bash
# Post-build script placeholder.
#
# The Oryx build container for Python apps ships with Node.js 14, which
# is too old for our frontend toolchain (Vite 8 / Tailwind 4 require
# Node 20+). Installing Node via apt is blocked in the build container.
#
# Current approach: build frontend locally (cd frontend && npm run build)
# before deploying. The zipIgnorePattern in .vscode/settings.json already
# includes frontend/dist/ in the deploy zip.
#
# Future improvement: switch to GitHub Actions CI/CD pipeline where we
# control the full build environment and can install any Node version.

echo "[post_build] No server-side frontend build (Node 14 too old). Using pre-built dist/."
