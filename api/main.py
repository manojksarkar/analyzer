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
    repositories_router, users_router, text_overrides_router,
    version_components_router,
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


def _ensure_default_admin(db) -> None:
    """Guarantee a login exists: create ``admin@aspice.dev`` / ``admin`` when that user is absent,
    so a brand-new database (e.g. a freshly created remote Postgres) is never left with no way to
    sign in. Idempotent — a no-op once the user exists. Change the password after first login.

    An ORDINARY user: it reaches the projects it is a member of -- every project it creates -- and
    no others. Not a superuser: its password is published here, it comes back when deleted, and
    the JWT secret's default makes a token for it forgeable, so making it reach every project
    would make every project reachable by anyone. A superuser is made on purpose, with
    `tools/grant_access.py --set-superuser --email <address>`."""
    import datetime
    import sys
    try:
        if db.users.get_by_email("admin@aspice.dev"):
            return
        from .models.domain import User
        from .middleware.auth import hash_password
        db.users.create(User(
            id="admin", email="admin@aspice.dev", name="Administrator", initials="AD",
            avatar_url=None, hashed_password=hash_password("admin"),
            created_at=datetime.datetime.now(datetime.timezone.utc)))
        print("[api] created default admin — sign in: admin@aspice.dev / admin", file=sys.stderr)
    except Exception as exc:                                  # noqa: BLE001
        print(f"[api] could not ensure default admin: {type(exc).__name__}: {exc}", file=sys.stderr)


#: Seconds between two tries of the start-up check below while the database does not answer.
JOB_SWEEP_RETRY_SECONDS = 30.0


def _fail_interrupted_jobs(db) -> bool:
    """Jobs a stopped server left queued or running: failed with what happened, or -- a run in
    the background -- followed again (`pipeline_runner.fail_interrupted_jobs`). Only jobs that
    started before this process did: one started since is this process's own. Never stops the
    start-up. False when the check could not run (the database did not answer)."""
    import sys
    try:
        from .services import pipeline_runner
        engine = getattr(db, "_engine", None)
        if engine is not None and not pipeline_runner.claim_job_runner(engine):
            print("[api] another API server runs jobs on this database: none of its jobs is "
                  "touched, and none left by a stopped server is cleared", file=sys.stderr)
            return True
        n = pipeline_runner.fail_interrupted_jobs(db, before=pipeline_runner.PROCESS_STARTED)
        if n:
            print(f"[api] {n} job(s) left running by a stopped server: marked failed "
                  f"(interrupted)", file=sys.stderr)
        return True
    except Exception as exc:                                  # noqa: BLE001
        print(f"[api] could not check for interrupted jobs: {type(exc).__name__}: {exc} -- "
              f"trying again in {JOB_SWEEP_RETRY_SECONDS:.0f} s", file=sys.stderr)
        return False


#: Seconds between two looks for active jobs that nothing follows any more.
JOB_WATCH_SECONDS = 300.0


def _watch_jobs(db, stop=None) -> None:
    """After start-up, every five minutes: a job left active with nothing following it -- its
    thread died on an error it could not record (the database down at the end of a run) -- is
    followed again (a background run) or failed, as at start-up. Only by the server that runs
    jobs on this database, and never a job started in the last two minutes: it may be between
    its row and its thread."""
    import datetime as _dt
    import sys
    import threading

    stop = stop or threading.Event()          # set by a test to end the thread

    def loop() -> None:
        from .services import pipeline_runner
        while not stop.wait(JOB_WATCH_SECONDS):
            try:
                engine = getattr(db, "_engine", None)
                if engine is not None and not pipeline_runner.runner_still_held(engine):
                    continue
                pipeline_runner.fail_interrupted_jobs(
                    db, before=pipeline_runner._now() - _dt.timedelta(seconds=120),
                    reattach_only=True)
            except Exception as exc:                          # noqa: BLE001 - next round
                print(f"[api] job watch: {type(exc).__name__}: {exc}", file=sys.stderr)
    threading.Thread(target=loop, daemon=True, name="job-watch").start()


def _sweep_until_done(db) -> None:
    """Try the start-up check again, in the background, until it runs. A run in the background
    is followed again only by that check: one missed try -- a database slow to answer while the
    machine is busy -- left its job saying "running" for ever, with nothing following the run."""
    import threading
    import time

    def loop() -> None:
        while True:
            time.sleep(JOB_SWEEP_RETRY_SECONDS)
            if _fail_interrupted_jobs(db):
                return
    threading.Thread(target=loop, daemon=True, name="job-sweep").start()


@app.on_event("startup")
async def _db_startup_check() -> None:
    """When the SQL backend is active, log which database the API is bound to (password
    redacted) and whether it's reachable — so a missing/wrong DATABASE_URL surfaces HERE, not
    as a cryptic 500 on the first request. Does not abort startup (the DB may come up shortly)."""
    import os
    import sys
    from .db.session import _db
    from .middleware.auth import ACCESS_TOKEN_EXPIRE_MINUTES
    # Said at start-up, because the only other way to find out is to wait for a 401.
    print(f"[api] sign-ins last {ACCESS_TOKEN_EXPIRE_MINUTES} minutes "
          f"(auth.accessTokenMinutes in engine/config/config.local.json)", file=sys.stderr)
    engine = getattr(_db, "_engine", None)
    if engine is None:
        # D-16: Postgres is the only real backend. In-memory is a test/dev seam that persists
        # NOTHING — say so loudly rather than letting a misconfigured server look healthy.
        print("[api] *** NO DATABASE CONFIGURED — running the in-memory TEST backend. ***\n"
              "      Seed data only; every project, version and document is lost on restart.\n"
              "      Set DATABASE_URL, or add a `db` section to engine/config/config.local.json,\n"
              "      then run `python analyzer.py setup`.", file=sys.stderr)
        return
    sys.path.insert(0, str(Path(__file__).parent.parent / "engine"))
    from core.db import _redact
    from sqlalchemy import text
    dsn = str(engine.url)
    src = "DATABASE_URL env" if os.environ.get("DATABASE_URL", "").strip() else "config db section / default"
    print(f"[api] SQL backend — database: {_redact(dsn)}  (source: {src})", file=sys.stderr)
    try:
        with engine.connect() as cx:
            cx.execute(text("SELECT 1"))
        print("[api] database reachable ✓", file=sys.stderr)
        _ensure_default_admin(_db)          # never leave a fresh DB with no way to sign in
    except Exception as exc:                                  # noqa: BLE001
        print(f"[api] *** DATABASE UNREACHABLE *** {type(exc).__name__}: {exc}\n"
              f"      The API is bound to {_redact(dsn)} (source: {src}). If that is 'localhost'\n"
              f"      but you meant a remote server, set DATABASE_URL before starting uvicorn, or\n"
              f"      add a `db` section to engine/config/config.local.json.", file=sys.stderr)
    # No job says "running" with nothing running or following it -- tried again until it runs,
    # then looked for again every few minutes.
    if not _fail_interrupted_jobs(_db):
        _sweep_until_done(_db)
    _watch_jobs(_db)

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
    # Starlette answers an unhandled exception from ServerErrorMiddleware, which sits OUTSIDE
    # CORSMiddleware, so this response never gets its CORS headers. The browser then blocks it
    # and the web app reports "Failed to fetch" instead of the message below. Echo the origin
    # the way CORSMiddleware does for every other response (allow_origins=["*"] with credentials).
    headers = {}
    origin = request.headers.get("origin")
    if origin:
        headers = {"Access-Control-Allow-Origin": origin,
                   "Access-Control-Allow-Credentials": "true",
                   "Vary": "Origin"}
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc), "status": 500}},
        headers=headers,
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
# Review & Update -- correcting LLM text in a generated document (spec 05 section 10)
app.include_router(text_overrides_router,    prefix=PREFIX)
# Staged generation -- a version's components and the documents still to make
app.include_router(version_components_router, prefix=PREFIX)

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
