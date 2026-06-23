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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import (
    auth_router, projects_router, commits_versions_router,
    jobs_router, documents_router, team_router,
    compare_router, functions_router, notifications_router,
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
    docs_url="/docs",
    redoc_url="/redoc",
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
