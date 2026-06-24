# mock-api — local mock backend for `web-app`

This is the **mock** FastAPI backend that drives the `web-app/` frontend during
development. It is a self-contained snapshot of the API contract (in-memory /
JSON DB, seeded data, render fixtures, simulated job runner) so the frontend can
be built and demoed without the real backend.

The **real API** is developed separately and lives in [`../api/`](../api/). When
it is ready, switch to it with **zero frontend code change** — `web-app` selects
its backend purely via the `VITE_API_URL` env var (default
`http://localhost:8000/api/v1`). Just run the real `api/` on that URL instead of
this mock, or point `VITE_API_URL` at wherever the real API is hosted.

## Run

**Easiest — the launcher works from any directory (autoreload on):**

```bash
python mock-api/run.py            # or: cd mock-api && python run.py
```

Override with env vars if needed: `PORT=8001`, `HOST=0.0.0.0`, `RELOAD=0`.

**Or call uvicorn directly** (must be from the `mock-api/` folder):

```bash
cd mock-api
uvicorn api.main:app --port 8000

# For dev with autoreload, also pass --app-dir . :
uvicorn api.main:app --reload --app-dir . --port 8000
```

> **Why the `--app-dir .` / launcher fuss:** the package lives at `mock-api/api`,
> so it is only importable when **`mock-api/`** (not `mock-api/api/`) is on
> `sys.path`. Without `--reload` your shell's cwd covers that. With `--reload`,
> uvicorn spawns a child process that does **not** inherit the cwd on Windows, so
> `import api` fails with `ModuleNotFoundError: No module named 'api'`. `run.py`
> (and `--app-dir .`) add the correct directory in the child process too. A common
> trip-up is running from inside `mock-api/api/` — `run.py` avoids that entirely.

- Swagger UI: http://localhost:8000/docs
- Health:     http://localhost:8000/health

Every endpoint declares an **exact response-body schema** in Swagger (expand a
route → "Responses" → 200/201/202 → Schema). These come from `api/schemas.py` and
are attached for documentation only (via `responses={...}`, not `response_model=`),
so they never alter the actual JSON returned.

The launch target (`api.main:app`) and all imports are identical to the real
`api/` — only the working directory differs.

## Seed login

All seed users use password `secret` (e.g. `alice@aspice.dev` — admin on the
`VCU Engine Firmware` / p1 project, which has the fixture-backed render docs).

## Optional: persistent JSON DB

```bash
API_DB_BACKEND=json uvicorn api.main:app --port 8000   # default: memory (resets on restart)
```

See [`api/PROJECT_CONTEXT.md`](api/PROJECT_CONTEXT.md) for the full mock context
(routes, seed data, fixtures, job runner).
