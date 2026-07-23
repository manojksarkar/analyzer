# ASPICE Platform — API Server

REST API for the Automotive ASPICE Documentation Platform.
Built with **FastAPI** + **Python 3.12**, backed by either an in-memory store
(default) or a JSON-file store.  The API drives the real **analyzer pipeline**
(`run.py`) for analysis jobs and reads its actual output for documents,
functions, render, download, and compare.

> **Docs in this folder:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (scoped context) · [PLAN.md](PLAN.md) (forward work + design record).

---

## Quick start

```bash
# Install dependencies (from repo root)
pip install -r api/requirements.txt

# Start the server (in-memory DB, simulated seed data)
uvicorn api.main:app --reload --port 8000

# Start with JSON DB (persists across restarts)
API_DB_BACKEND=json uvicorn api.main:app --reload --port 8000
```

| URL | Description |
|---|---|
| http://localhost:8000/docs | Swagger UI (interactive) |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/health | Health check |

### Sign in

```bash
curl -X POST http://localhost:8000/api/v1/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@aspice.dev", "password": "secret"}'
```

Seed users (all use password `secret`):

| Email | Role | Projects |
|---|---|---|
| alice@aspice.dev | Admin | VCU Engine Firmware, ADAS Sensor Fusion |
| bob@aspice.dev | Developer | VCU Engine Firmware |
| carol@aspice.dev | Developer | VCU Engine Firmware, Gateway ECU (admin) |
| dave@aspice.dev | Developer (pending) | VCU Engine Firmware |
| eve@aspice.dev | Developer | ADAS Sensor Fusion |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `API_DB_BACKEND` | `memory` | `memory` = in-memory seed data; `json` = persistent JSON files |
| `ANALYZER_REPO_ROOT` | auto-detected | Absolute path to the repo root (contains `engine/run.py`) |
| `ANALYZER_WORKSPACES_DIR` | `<repo_root>/workspaces/` | Where per-project checkouts and output dirs live |
| `JOB_MAX_CONCURRENCY` | `2` | Max pipeline subprocesses running simultaneously |
| `SUBPROCESS_TIMEOUT` | `0` | Seconds before a pipeline subprocess is killed (0 = no limit) |
| `LIBCLANG_PATH` | _(auto)_ | Path to libclang shared library, forwarded to `run.py` |

---

## Architecture

```
api/
├── main.py                  ← FastAPI app, router registration, CORS
├── requirements.txt         ← pip dependencies
│
├── models/
│   └── domain.py            ← Pure Python dataclasses (User, Project, Document, …)
│
├── repositories/
│   └── interfaces.py        ← 12 abstract ABCs — the DB contract every adapter fulfils
│
├── db/
│   ├── in_memory.py         ← In-memory adapter + seed data (default)
│   ├── json_db.py           ← JSON-file adapter (persistent, write-through)
│   └── session.py           ← ONE LINE to swap backend — reads API_DB_BACKEND
│
├── middleware/
│   └── auth.py              ← JWT (HS256), RBAC helpers, bcrypt shims
│
├── schemas.py               ← ~80 Pydantic response models (Swagger docs)
│
├── services/
│   ├── errors.py            ← Consistent HTTP error envelope helpers
│   ├── settings.py          ← Centralised env-var config (see table above)
│   ├── pipeline_runner.py   ← Real run.py subprocess driver (clone → config →
│   │                            run.py → SSE → version+docs)
│   ├── doc_render.py        ← Builds render payload from live output/ artifacts
│   ├── compare_engine.py    ← Section-level diff between version snapshots
│   ├── git_cli.py           ← Shell-safe git helpers (ls-remote, shallow-clone)
│   └── repo_git.py          ← Repository wizard (list refs, commits, upload)
│
└── routes/
    ├── auth.py              ← /auth/signin|refresh|signout, /auth/me
    ├── projects.py          ← CRUD projects, access requests
    ├── commits_versions.py  ← Commits list, version CRUD
    ├── jobs.py              ← Analysis jobs, SSE streaming, functions
    ├── documents.py         ← Documents, sections, approve, download, export
    ├── team.py              ← Member invite, role management
    ├── compare.py           ← Diff between commits/versions (real engine)
    ├── functions.py         ← Function visibility management
    ├── notifications.py     ← User notifications
    ├── repositories.py      ← Repository wizard (validate, list refs/commits)
    └── users.py             ← User search
```

**Total routes: 70** across all routers.

### Design principles

- **Domain models are pure dataclasses** (`api/models/domain.py`).  Routes and
  services work only with these — zero ORM import anywhere except the DB adapter.

- **Repository pattern** (`api/repositories/interfaces.py`).  Every concrete
  storage adapter must implement the abstract classes here.  Switching databases
  means writing one new adapter; no route or service changes.

- **One injection point** (`api/db/session.py`).  `get_db()` is a FastAPI
  dependency.  Replace the instantiation inside it to swap backends.

- **Real pipeline, not a simulation**.  `POST /jobs` spawns a daemon thread that
  shells out to `run.py` via `pipeline_runner.py`.  The thread:
  1. Clones/checks out the commit into `workspaces/<project_id>/<sha16>/`.
  2. Writes a per-project `config.json` from `build_config` + `architecture_layers`.
  3. Runs `run.py` as a subprocess and tails its output for SSE events.
  4. On completion, registers a real `Version` and `Documents` from `output/` dirs.
  5. Captures a version snapshot to `workspaces/<project_id>/versions/<id>/` for
     future compare/diff calls.

- **Role enforcement is server-side**.  `require_project_admin` /
  `require_project_member` are called at the start of every protected handler.

---

## Storage backends

### In-memory (`API_DB_BACKEND=memory`)

Default.  Seeded with five users, three projects, versions, commits, jobs,
documents, and sample sections.  Resets on restart.  Ideal for development
and demos.

### JSON files (`API_DB_BACKEND=json`)

Persists every aggregate to `api/db/data/*.json`.  Write-through: every
`create`/`update`/`delete` flushes to disk atomically.  On startup, if
`model/functions.json` exists (written by the pipeline) it is overlaid on the
functions store so the API reflects the latest run.

---

## API reference

Base path: `/api/v1`
All endpoints except `/auth/signin` and `/auth/refresh` require
`Authorization: Bearer <token>`.

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/auth/signin` | Email + password → access + refresh token |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/signout` | Invalidate tokens |
| GET | `/auth/me` | Current user profile |
| PATCH | `/auth/me` | Update name / avatar |

### Projects

| Method | Path | Description |
|---|---|---|
| GET | `/projects` | List projects for current user |
| POST | `/projects` | Create project |
| GET | `/projects/search` | Search discoverable projects |
| GET | `/projects/:id` | Project detail + KPIs |
| PATCH | `/projects/:id` | Update project (admin) |
| DELETE | `/projects/:id` | Delete project (admin) |
| POST | `/projects/:id/access-requests` | Request access |
| GET | `/projects/:id/access-requests` | List pending requests (admin) |
| PATCH | `/projects/:id/access-requests/:reqId` | Approve / deny request (admin) |

### Repositories (wizard)

| Method | Path | Description |
|---|---|---|
| POST | `/repositories/validate` | Validate repo URL + credentials |
| GET | `/repositories/refs` | List branches and tags |
| GET | `/repositories/commits` | List commits on a branch |
| POST | `/repositories/upload` | Upload data dictionary / macros CSV |

### Commits & Versions

| Method | Path | Description |
|---|---|---|
| GET | `/projects/:id/commits` | Paginated commit list |
| GET | `/projects/:id/versions` | All tagged versions |
| POST | `/projects/:id/versions` | Tag a commit as a version (admin) |
| GET | `/projects/:id/versions/:versionId` | Version detail |
| PATCH | `/projects/:id/versions/:versionId` | Approve / update version (admin) |
| DELETE | `/projects/:id/versions/:versionId` | Delete version (admin) |

### Analysis Jobs

| Method | Path | Description |
|---|---|---|
| POST | `/projects/:id/jobs` | Start analysis job (202 Accepted) |
| GET | `/projects/:id/jobs/current` | Active / latest job with progress |
| GET | `/projects/:id/jobs/:jobId` | Job detail |
| GET | `/projects/:id/jobs/:jobId/events` | **SSE** live progress stream |
| POST | `/projects/:id/jobs/:jobId/cancel` | Cancel running job (admin) |
| POST | `/projects/:id/jobs/:jobId/resume` | Resume paused job (admin) |
| GET | `/projects/:id/jobs/:jobId/functions` | Discovered functions after Phase 1 |
| POST | `/projects/:id/jobs/:jobId/reexport` | Re-export DOCX (admin) |

### Documents

| Method | Path | Description |
|---|---|---|
| GET | `/projects/:id/documents` | Filterable document list |
| GET | `/projects/:id/documents/stats` | KPI summary counts |
| POST | `/projects/:id/documents/export-all` | ZIP export of all docs |
| POST | `/projects/:id/documents/assignments/batch` | Batch assign reviewers |
| POST | `/projects/:id/documents/approve-all` | Bulk approve (admin) |
| GET | `/projects/:id/documents/:docId` | Full doc with sections |
| PATCH | `/projects/:id/documents/:docId` | Update status (admin) |
| GET | `/projects/:id/documents/:docId/render` | Rich render payload (cover + sections) |
| GET | `/projects/:id/documents/:docId/download` | Download DOCX |
| GET | `/projects/:id/documents/:docId/export` | Export single doc |
| GET | `/projects/:id/documents/:docId/assets/:path` | Serve diagram / asset file |
| POST | `/projects/:id/documents/:docId/assignments` | Assign reviewer(s) |
| DELETE | `/projects/:id/documents/:docId/assignments/:userId` | Remove assignee |
| POST | `/projects/:id/documents/:docId/assignments/self` | Self-assign |
| PATCH | `/projects/:id/documents/:docId/sections/:key` | Accept / decline / edit section |
| POST | `/projects/:id/documents/:docId/submit-review` | Submit full review |
| POST | `/projects/:id/documents/:docId/approve` | Approve document (admin) |
| POST | `/projects/:id/documents/:docId/request-changes` | Request changes (admin) |

### Functions

| Method | Path | Description |
|---|---|---|
| PATCH | `/projects/:id/functions/:fnId` | Set visibility (admin) |
| PATCH | `/projects/:id/functions` | Bulk update visibility (admin) |

### Compare

| Method | Path | Description |
|---|---|---|
| GET | `/projects/:id/compare` | Diff summary between two refs |
| GET | `/projects/:id/compare/documents` | Changed documents between refs |
| GET | `/projects/:id/compare/documents/:docId` | Section-level diff |

### Team

| Method | Path | Description |
|---|---|---|
| GET | `/projects/:id/members` | Active members |
| GET | `/projects/:id/members/pending` | Pending invites (admin) |
| POST | `/projects/:id/members/invite` | Invite by email (admin) |
| PATCH | `/projects/:id/members/:userId/role` | Change role (admin) |
| DELETE | `/projects/:id/members/:userId` | Remove member (admin) |
| DELETE | `/projects/:id/members/pending/:inviteId` | Cancel invite (admin) |

### Notifications

| Method | Path | Description |
|---|---|---|
| GET | `/notifications` | Unread notifications |
| PATCH | `/notifications/:id/read` | Mark one read |
| POST | `/notifications/read-all` | Mark all read |

### Users

| Method | Path | Description |
|---|---|---|
| GET | `/users/search` | Search users by name/email |

---

## Error envelope

All errors return a consistent JSON body:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document doc_999 does not exist in this project.",
    "status": 404
  }
}
```

---

## Real-time (SSE)

Connect to `GET /api/v1/projects/:id/jobs/:jobId/events`:

```bash
curl -N -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/projects/p1/jobs/job1/events
```

Event types: `phase_update`, `activity_update`, `log_line`,
`job_complete`, `job_failed`.

---

## Swapping the database

1. Implement every ABC in `api/repositories/interfaces.py`
   (12 classes: `IUserRepository`, `IProjectRepository`, etc.)

2. Create your adapter class (e.g. `PostgresDatabase`) with the same
   attribute names as `InMemoryDatabase`.

3. In **`api/db/session.py`** replace the one line:

   ```python
   # Before
   _db = InMemoryDatabase()

   # After
   _db = PostgresDatabase(dsn=os.environ["DATABASE_URL"])
   ```

4. Done — no route or service file needs to change.
