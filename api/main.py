"""
Automotive ASPICE Documentation Platform — API Server
======================================================

Start:
    uvicorn api.main:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs         (Swagger UI)
    http://localhost:8000/redoc        (ReDoc)

Quick test (after server is running):
    curl -X POST http://localhost:8000/api/v1/auth/signin \
         -H "Content-Type: application/json" \
         -d '{"email": "alice@aspice.dev", "password": "secret"}'
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html

from .routes import (
    auth_router, projects_router, commits_versions_router,
    jobs_router, documents_router, team_router,
    compare_router, functions_router, notifications_router,
    repositories_router, users_router,
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ASPICE Documentation Platform API",
    description=(
        "Multi-tenant, role-based SaaS API for automating automotive ASPICE / "
        "ISO 26262 documentation from C++ source code repositories."
    ),
    version="0.1.0",
    docs_url=None,      # custom self-hosted routes below (CDN-free, offline-friendly)
    redoc_url=None,
)


@app.on_event("startup")
async def _db_startup_check() -> None:
    """When the SQL backend is active, log which database the API is bound to (password
    redacted) and whether it's reachable — so a missing/wrong DATABASE_URL surfaces HERE, not
    as a cryptic 500 on the first request. Does not abort startup (the DB may come up shortly)."""
    import os
    import sys
    from .db.session import _db
    engine = getattr(_db, "_engine", None)
    if engine is None:
        print("[api] backend: in-memory/json (no external database).", file=sys.stderr)
        return
    sys.path.insert(0, str(Path(__file__).parent.parent / "engine"))
    from core.db import _redact
    from sqlalchemy import text
    dsn = str(engine.url)
    env_set = "set" if os.environ.get("DATABASE_URL", "").strip() else "NOT SET"
    print(f"[api] SQL backend — database: {_redact(dsn)}  (DATABASE_URL is {env_set})",
          file=sys.stderr)
    try:
        with engine.connect() as cx:
            cx.execute(text("SELECT 1"))
        print("[api] database reachable ✓", file=sys.stderr)
    except Exception as exc:                                  # noqa: BLE001
        print(f"[api] *** DATABASE UNREACHABLE *** {type(exc).__name__}: {exc}\n"
              f"      The API is bound to {_redact(dsn)}. If that is 'localhost' but you meant a\n"
              f"      remote server, set DATABASE_URL *before* starting uvicorn (it is {env_set}).",
              file=sys.stderr)

# ---------------------------------------------------------------------------
# Self-hosted API docs — Swagger UI / ReDoc assets are served from api/static/
# instead of a public CDN, so /docs and /redoc work on networks (e.g. office
# firewalls) that block cdn.jsdelivr.net. Assets are vendored in the repo.
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


@app.get("/redoc", include_in_schema=False)
async def custom_redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url="/static/redoc.standalone.js",
    )

# ---------------------------------------------------------------------------
# CORS (permissive for local dev — tighten for production)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global error handler — ensures consistent error envelope
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc), "status": 500}},
    )

# ---------------------------------------------------------------------------
# Register routers under /api/v1
# ---------------------------------------------------------------------------

PREFIX = "/api/v1"

app.include_router(auth_router,              prefix=PREFIX)
app.include_router(projects_router,          prefix=PREFIX)
app.include_router(commits_versions_router,  prefix=PREFIX)
app.include_router(jobs_router,              prefix=PREFIX)
app.include_router(documents_router,         prefix=PREFIX)
app.include_router(team_router,              prefix=PREFIX)
app.include_router(compare_router,           prefix=PREFIX)
app.include_router(functions_router,         prefix=PREFIX)
app.include_router(notifications_router,     prefix=PREFIX)
app.include_router(repositories_router,      prefix=PREFIX)
app.include_router(users_router,             prefix=PREFIX)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": app.version}


@app.get("/", tags=["meta"])
def root():
    return {
        "name": app.title,
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
    }
