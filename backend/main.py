"""
Clio API Orchestrator — FastAPI Backend Entry Point

This is the web API server that wraps our existing CLI core engine
(config.py, clio_client.py, operations.py) with HTTP endpoints.

Usage (development):
    uvicorn backend.main:app --reload --port 8000

The app will be available at:
    http://localhost:8000
    http://localhost:8000/docs  (auto-generated Swagger UI)
"""

import sys
from pathlib import Path

# ── Make the core engine importable ──────────────────────────────────────────
# The core modules (config.py, clio_client.py, operations.py) live in the
# project root (one level up from backend/). Add the root to Python's import
# path so we can do `from clio_client import ClioClient` etc.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import (
    health,
    matters,
    custom_fields,
    document_templates,
    audit,
    preview,
    execute,
    templates,
    oauth,
    billing,
)
from backend.auth import auth_router
from backend.database import init_db

# ── Create the FastAPI application ───────────────────────────────────────────
app = FastAPI(
    title="Clio API Orchestrator",
    description="Web API for managing Clio Manage data — matters, custom fields, bulk updates, and more.",
    version="1.0.0",
)

# ── CORS (Cross-Origin Resource Sharing) ─────────────────────────────────────
# Allows the React frontend (running on a different port during development)
# to make requests to this API. In production, restrict origins to your domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # React dev server (default Vite port)
        "http://localhost:3001",   # React dev server (common alternate)
        "http://localhost:5173",   # Vite alternate port
        "http://localhost:8000",   # Same-origin requests
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register route modules ───────────────────────────────────────────────────
# Each module in backend/routes/ handles a group of related endpoints.
# The prefix determines the URL path (e.g., /api/health, /api/auth).
# ── Initialize database on startup ────────────────────────────────────────────
init_db()

# ── Register route modules ───────────────────────────────────────────────────
app.include_router(health.router, prefix="/api")
app.include_router(auth_router, prefix="/api/auth")
app.include_router(oauth.router, prefix="/api")
app.include_router(matters.router, prefix="/api")
app.include_router(custom_fields.router, prefix="/api")
app.include_router(document_templates.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(execute.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(billing.router, prefix="/api")

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# Serve the built React frontend in production. API routes registered above
# win for /api/*. Client routes (/login, /billing, /matters, ...) are not files
# on disk. Starlette's html=True only serves index.html for a directory-style
# request, so a full navigation to a client route (browser refresh, or
# frontend/src/api/client.js sending the browser to /login on HTTP 401) fell
# through to FastAPI's JSON 404. _SPAStaticFiles catches those 404s and returns
# index.html so React Router can render the client route. Requests for files
# that legitimately don't exist (any path with a "." in the last segment, e.g.
# /assets/missing.js) still return 404.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class _SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)


if _FRONTEND_DIST.exists():
    app.mount("/", _SPAStaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")