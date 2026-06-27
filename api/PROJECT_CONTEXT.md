# API Server — Project Context

> Updated: 2026-06-27  
> Active branch: `feat/web-app-api`

---

## 1. What this is

A FastAPI REST server (70 endpoints) that exposes the Automotive ASPICE
Documentation Platform over HTTP.  Analysis jobs invoke the **real analyzer
pipeline** (`run.py`) as a subprocess; document render, download, and compare
all read **real pipeline output** from `output/` and `model/`.  The server
ships with an in-memory database seeded with realistic dummy data (default)
or a JSON-file store that persists across restarts.

---

## 2. Directory layout

```
api/
├── main.py                  ← FastAPI app, router registration, CORS
├── requirements.txt         ← pip dependencies (FastAPI, uvicorn, jose, passlib…)
├── README.md                ← Endpoint reference + quick-start
├── schemas.py               ← ~80 Pydantic response models for Swagger docs
│
├── models/
│   └── domain.py            ← 16 pure Python dataclasses — no ORM coupling
│
├── repositories/
│   └── interfaces.py        ← 12 abstract ABCs — the DB contract every adapter fulfils
│
├── db/
│   ├── in_memory.py         ← In-memory adapter + seed data
│   ├── json_db.py           ← JSON-file adapter (persistent, write-through)
│   └── session.py           ← ONE LINE to swap backend (reads API_DB_BACKEND)
│
├── middleware/
│   └── auth.py              ← JWT (HS256), RBAC helpers, bcrypt shims
│
├── services/
│   ├── errors.py            ← Consistent HTTP error envelope helpers
│   ├── settings.py          ← Centralised env-var config
│   ├── pipeline_runner.py   ← Real run.py subprocess driver
│   ├── doc_render.py        ← Render payload from live output/ artifacts
│   ├── compare_engine.py    ← Section-level diff between version snapshots
│   ├── git_cli.py           ← Shell-safe git helpers (ls-remote, shallow-clone)
│   └── repo_git.py          ← Repository wizard (list refs, commits, upload)
│
└── routes/
    ├── auth.py              ← /auth endpoints
    ├── projects.py          ← CRUD + access requests
    ├── commits_versions.py  ← Commits list, version CRUD
    ├── jobs.py              ← Analysis jobs, SSE streaming, functions
    ├── documents.py         ← Documents, sections, approve, download, export
    ├── team.py              ← Member invite, role management
    ├── compare.py           ← Diff between commits/versions
    ├── functions.py         ← Function visibility management
    ├── notifications.py     ← User notifications
    ├── repositories.py      ← Repository wizard (validate, list refs/commits)
    └── users.py             ← User search
```

---

## 3. Starting the server

```bash
pip install -r api/requirements.txt

# In-memory DB (default — resets on restart)
uvicorn api.main:app --reload --port 8000

# JSON-file DB (persists across restarts)
API_DB_BACKEND=json uvicorn api.main:app --reload --port 8000
```

| URL | Description |
|---|---|
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/health | Health check |

---

## 4. Environment variables

See `api/services/settings.py` for the canonical list.

| Variable | Default | Description |
|---|---|---|
| `API_DB_BACKEND` | `memory` | `memory` or `json` |
| `ANALYZER_REPO_ROOT` | auto-detected | Path to repo root (contains `run.py`) |
| `ANALYZER_WORKSPACES_DIR` | `<repo_root>/workspaces/` | Per-project checkout + output root |
| `JOB_MAX_CONCURRENCY` | `2` | Max simultaneous pipeline subprocesses |
| `SUBPROCESS_TIMEOUT` | `0` | Kill subprocess after N seconds (0 = unlimited) |
| `LIBCLANG_PATH` | _(auto)_ | Forwarded to `run.py` subprocesses |

---

## 5. Auth — passing tokens

```bash
# Sign in
curl -X POST http://localhost:8000/api/v1/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@aspice.dev", "password": "secret"}'

# Use the token
curl http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer eyJhbGci..."
```

Access token expires after 15 min; refresh token lifetime is 7 days.

---

## 6. Seed data

All seed users use password `secret`.

| Email | Role | Projects |
|---|---|---|
| alice@aspice.dev | Admin | VCU Engine Firmware (p1), ADAS Sensor Fusion (p2) |
| bob@aspice.dev | Developer | VCU Engine Firmware (p1) |
| carol@aspice.dev | Developer | VCU Engine Firmware (p1), Gateway ECU (p3, admin) |
| dave@aspice.dev | Developer (pending invite) | VCU Engine Firmware (p1) |
| eve@aspice.dev | Developer | ADAS Sensor Fusion (p2) |

Seed projects:

| ID | Name | Standard | Status |
|---|---|---|---|
| p1 | VCU Engine Firmware | ISO_26262 | in_review |
| p2 | ADAS Sensor Fusion | ASPICE_L2 | complete |
| p3 | Gateway ECU | ASPICE_L3 | not_run |

Other seeded data: 4 versions, 6 commits, 2 analysis jobs (one running, one
complete), 8 documents with sections and review state, 8 functions (job1/ver3),
notifications for bob and carol, one compare result with diffs.

---

## 7. Architecture — key decisions

### Domain models are pure dataclasses

`api/models/domain.py` contains 16 `@dataclass` classes.  No SQLAlchemy,
no Pydantic ORM mode.  Routes and services import only from here.

### Repository pattern — the DB contract

`api/repositories/interfaces.py` defines 12 ABCs:

```
IUserRepository            IProjectRepository         IProjectMemberRepository
IAccessRequestRepository   IVersionRepository         ICommitRepository
IAnalysisJobRepository     IDocumentRepository        IDocumentAssignmentRepository
IFunctionRepository        ICompareRepository         INotificationRepository
```

Both `InMemoryDatabase` and `JsonDatabase` implement all 12.

### Swapping the database — one line

`api/db/session.py` reads `API_DB_BACKEND` and instantiates either adapter.
To add a new backend, implement all 12 interfaces and change one line there.

### Real pipeline (not a simulation)

`POST /projects/:id/jobs` spawns a **daemon thread** via `pipeline_runner.start()`.
The thread:
1. Clones / checks out the commit into `workspaces/<project_id>/<sha16>/` via
   `git_cli.shallow_clone`.
2. Writes a per-project `config.json` (from `build_config` + `architecture_layers`)
   and passes it via `--config` to `run.py`.
3. Runs `run.py` as a subprocess (`shell=False`, `cwd=repo_root`), merging
   `stdout`+`stderr` and tailing the output for SSE events.
4. Detects phase transitions from log markers (`=== Phase N: ===`), updates
   the job record for the SSE stream.
5. On completion: registers a `Version` + `Document`s by scanning `output/` dirs;
   captures a version snapshot to `workspaces/<project_id>/versions/<id>/` for
   future compare calls.
6. On cancel: terminates the subprocess immediately.

`JOB_MAX_CONCURRENCY` is enforced by a `threading.BoundedSemaphore` — threads
that exceed the limit block until a slot frees.

### Per-project workspace isolation

Each project gets its own directory under `workspaces/<project_id>/`:
- `<sha16>/` — git checkout used as the `<project_path>` argument to `run.py`
- `config.json` — per-project config merged from defaults + `build_config`
- `versions/<version_id>/model/` + `versions/<version_id>/output/` — version
  snapshots captured after each successful run for the compare engine

Currently, pipeline output (`model/`, `output/`) lands in the repo root shared
dirs.  Full per-project isolation of these dirs requires a future `run.py` flag.

### RBAC is server-side

`require_project_admin` / `require_project_member` in `middleware/auth.py`
are called at the top of every protected route handler.

---

## 8. Known issues / previous fixes

### Compare page rendered raw JSON instead of document content

`compute_document_sections_diff` in `api/services/compare_engine.py` was
calling `json.dumps(unit_data, indent=2)` on raw `interface_tables.json` unit
values and passing the resulting JSON string as `current_content` /
`baseline_content`.  The frontend's `SectionBody` component in `ComparePage.tsx`
only understands plain text and GitHub-style pipe tables (parsed by
`parseSectionBody` in `web-app/src/lib/markdown.ts`), so it displayed the raw
JSON as unreadable text.

Fixed by adding `_itf_unit_to_markdown(data)` which converts the `entries` list
of a unit dict into a proper markdown pipe table (8 columns: Interface ID, Name,
Information, Data Type, Data Range, Direction, Source/Dest, Type — matching the
same column order used by `doc_render.py`).  Pipe characters inside cell values
are escaped to `/`; newlines are collapsed to a space.  Commit `d8bd70b`.

### bcrypt 4.x `__about__` AttributeError

`passlib 1.7.4` reads `bcrypt.__about__.__version__` removed in bcrypt 4.x.
Fixed in `middleware/auth.py` with a shim injected before passlib imports.
`requirements.txt` pins `bcrypt>=3.2.0,<4.0.0` for clean installs.

### bcrypt 72-byte password limit

Fixed by pre-hashing with SHA-256 + base64 before bcrypt so bcrypt always
sees exactly 44 ASCII chars.

### `api/models/` blocked by `.gitignore`

The root `.gitignore` contains `model*` (intended for ML model files), which
matched `api/models/`.  Fixed with `git add -f api/models/`.

---

## 9. Error envelope

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Document doc_999 does not exist.",
    "status": 404
  }
}
```

Error helpers: `not_found`, `forbidden`, `conflict`, `bad_request`
in `api/services/errors.py`.

---

## 10. SSE — live job progress

```bash
curl -N -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/projects/p1/jobs/job1/events
```

Event types: `phase_update`, `activity_update`, `log_line`,
`job_complete`, `job_failed`.  Emits every 3 seconds while the job is active.

---

## 11. Route summary (70 endpoints)

All under `/api/v1`.  Full reference: `api/README.md`.

| Group | Prefix | Count |
|---|---|---|
| Auth | `/auth` | 5 |
| Projects | `/projects` | 9 |
| Repositories (wizard) | `/repositories` | 4 |
| Commits & Versions | `/projects/:id/commits` + `/versions` | 8 |
| Jobs + SSE | `/projects/:id/jobs` | 8 |
| Documents | `/projects/:id/documents` | 18 |
| Team | `/projects/:id/members` | 6 |
| Compare | `/projects/:id/compare` | 3 |
| Functions | `/projects/:id/functions` | 2 |
| Notifications | `/notifications` | 3 |
| Users | `/users` | 1 |
| Meta | `/health`, `/` | 2 |
| **Total** | | **69+** |

---

## 12. JSON Database adapter

`api/db/json_db.py` — write-through persistence to `api/db/data/*.json`.

- On first run: seeds from same dummy data as `InMemoryDatabase`, writes files.
- On subsequent runs: loads from disk.
- On init: if `model/functions.json` exists, its contents replace the seeded
  function store so the API reflects the latest pipeline run.

Write-through uses an atomic rename (`path.tmp` → `path`) so a crash mid-write
never leaves a corrupt file.

---

## 13. Implementation milestones

| Milestone | Status | Description |
|---|---|---|
| M0 | ✅ | Static surface sync — schemas, users, repositories, domain fields, token-stripped config, commit backfill |
| M1 | ✅ | Real analysis worker — pipeline_runner.py (clone → config → run.py → SSE → version+docs) |
| M2 | ✅ | Real functions diff, doc_render on live output, assets, download/export, export-all ZIP |
| M3 | ✅ | Real compare — section-level diff via compare_engine over version snapshots |
| M4 | ✅ | Persistence, central config (settings.py), gitignore, docs, API smoke tests |
