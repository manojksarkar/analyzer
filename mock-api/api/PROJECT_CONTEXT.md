# API Server — Project Context

> NOTE (mock-api): this tree is the **mock backend** copied to `mock-api/` for `web-app` dev; the real API is developed separately under the repo-root `api/`. See the repo-root PROJECT_CONTEXT.md relocation entry.
> Updated: 2026-06-24 (feat/web-app — **every endpoint now declares an exact response-body schema in Swagger/OpenAPI** (`/docs`). New **`api/schemas.py`** with ~80 Pydantic response models (`ProjectView`, `JobView`, `DocumentDetail`, the recursive `RenderSection` for the `{cover,toc,sections,meta}` render payload, etc.; sub-models reused — `Pagination`, `DocCounts`, `AssigneeView`, …). Wired into **all 56 JSON routes** (+ `/health`, `/`) via the decorator's **`responses={<status>: {"model": X}}`** argument — deliberately **NOT** `response_model=`, so the schema is documented WITHOUT runtime filtering: handlers still return their plain dicts unchanged (proved byte-identical against a pre-change baseline; the synthesized render path keeps omitting `image_url`/`mermaid` while the pipeline path includes them). Status codes matched (201/202 where set). Date fields typed `str` (helpers already emit `.isoformat()`); free-form blobs (`build_config`, `architecture_layers`, repo `entries`) typed loosely on purpose. Binary/stream routes (`…/assets/{path}`, `…/download`, `…/export`, SSE `…/events`) and 204 deletes intentionally carry no JSON model. Verified: app imports (70 routes), 101 component schemas, `/openapi.json`+`/docs` 200, all 56 JSON endpoints expose a 2xx `$ref`, responses unchanged.)
> Updated: 2026-06-24 (feat/frontend-app — **`…/documents/{id}/render` now serves REAL output from a committed fixture, + a diagram asset route**. New **`api/services/doc_render.py`** + **`api/fixtures/documents/<group>/`** (curated snapshot of `output/<group>/` for `Full`/`Access`/`Diag`: real `interface_tables.json` + diagram `.png`/`.mmd`). `render_document` builds `{cover,toc,sections,meta}` from the fixture when `doc.group` has one (`source:"pipeline"`, real interface tables + per-component/unit `diagram` sections with `image_url`+`mermaid`), else falls back to the prior synthesized `_render_doc_dict` (`source:"model"`). New **unauthenticated** `GET /projects/{id}/documents/{doc_id}/assets/{asset_path:path}` → `FileResponse` from the group fixture, path-traversal-guarded (`doc_render.resolve_asset`); unauthenticated by design like the SSE route so `<img>` can load diagrams. **Re-seeded** the p1 SWE.3 docs to the fixture groups (`Full`/`Access`/`Diag`, layer `Layer1`). Live `output/` is gitignored/unreliable, hence the committed fixture. Smoke-tested via `TestClient`.)
> Updated: 2026-06-24 (feat/frontend-app — **new read endpoint `GET /projects/{id}/documents/{doc_id}/render`** (`routes/documents.py`) for the web Document Inspector: returns the rich **`{cover, toc, sections, meta}`** shape (cover = project/version/layer/group/standard; `sections` are typed/nested — `richtext`|`table`|`diagram` with `children`; `meta` = `pipeline_data_available`/`model_data_available`/`source`/`layers`/`components`/`units_total`/`functions_total`/`globals_total`). **Representative schema-faithful payload, NOT parsed from the real `model/`+`output/` artifacts** (deliberate): `cover`/`meta` derived from the project (`architecture_layers`) + document, `sections` from the seeded `DocumentSection` bodies (markdown tables parsed; design sections get representative diagram children). Pure addition — no existing endpoint/model changed; smoke-tested via `TestClient`. Helpers `_render_doc_dict`/`_render_section`/`_parse_md_table`/`_arch_summary`/`_flatten_toc` in `routes/documents.py`.)
> Updated: 2026-06-23 (feat/frontend-app — (1) **API is now self-contained for git**: the wizard's git work moved off `backend/git_service.py` into a new `api/services/git_cli.py` (ls_remote/shallow_clone/list_tree/list_commits); `backend/` reverted + no longer imported anywhere under `api/`. (2) **Simulated analysis worker** `api/services/job_runner.py`: `POST /jobs` spawns a background thread that animates the four phases over SSE and, on completion, synthesises a `Version` + architecture-derived `Document`s and flips the project to `in_review`. See §12 "Source of truth: git_cli.py" + "Simulated job runner".)
> Updated: 2026-06-23 (feat/frontend-app — `_project_view` (routes/projects.py) now also returns `default_branch` and a **token-stripped** `build_config` (drops `repo_access_token`) so the frontend overview can show a project's captured config before any analysis run. No new endpoints. See §12 "Surfacing config pre-analysis".)
> Updated: 2026-06-23 (feat/frontend-app — added the new-project wizard's server endpoints: `repositories/*` (test-connection, browse, uploads) **backed by real git** via `backend/git_service.py`, `users/search` (org directory) backed by a new `IUserRepository.search` in both DB adapters, and an optional `access_token` on `POST /projects` (stored in `build_config`, never echoed). New files: `services/repo_git.py`, `routes/repositories.py`, `routes/users.py`. First change under `api/`. See §12.)
> Updated: 2026-06-22 (feat/api-server branch — initial implementation)
> Active branch: `feat/api-server`

---

## 1. What this is

A FastAPI REST server that exposes the ASPICE Documentation Platform over HTTP.
It ships with an in-memory database seeded with realistic dummy data so every
endpoint is immediately usable without a real DB.

---

## 2. Directory layout

```
api/
├── main.py                 ← FastAPI app, router registration, CORS
├── requirements.txt        ← pip dependencies (FastAPI, uvicorn, jose, passlib…)
├── README.md               ← Endpoint reference + quick-start
├── models/
│   └── domain.py           ← 16 pure Python dataclasses — no ORM coupling
├── repositories/
│   └── interfaces.py       ← 12 abstract ABCs — the DB contract every adapter must fulfill
├── db/
│   ├── in_memory.py        ← Concrete in-memory adapter + seed data
│   └── session.py          ← ONE LINE to swap backend: replace `InMemoryDatabase()`
├── middleware/
│   └── auth.py             ← JWT (HS256), RBAC helpers, bcrypt compatibility shims
├── services/
│   ├── errors.py           ← Consistent HTTP error envelope helpers
│   ├── git_cli.py          ← Self-contained git CLI wrapper (no backend import) — §12
│   ├── repo_git.py         ← Git-backed repo introspection (ls-remote / browse / commits) — §12
│   └── job_runner.py       ← Simulated analysis worker (phase progression + doc gen) — §12
└── routes/
    ├── auth.py             ← POST /auth/signin|refresh|signout, GET/PATCH /auth/me
    ├── projects.py         ← CRUD projects (+ optional access_token), access requests
    ├── commits_versions.py ← Commits list, version CRUD
    ├── jobs.py             ← Analysis jobs + SSE streaming + function list
    ├── documents.py        ← Documents, section review, approve, export
    ├── team.py             ← Member invite, role management
    ├── compare.py          ← Diff between commits / versions
    ├── functions.py        ← Function visibility management
    ├── notifications.py    ← User notifications
    ├── repositories.py     ← Wizard: test-connection, browse, uploads (real git) — §12
    └── users.py            ← Org member search (GET /users/search) — §12
```

---

## 3. Starting the server

```bash
pip install -r api/requirements.txt
uvicorn api.main:app --reload --port 8000
```

| URL | Description |
|---|---|
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/health | Health check |

---

## 4. Auth — passing tokens

All endpoints except `/api/v1/auth/signin` and `/api/v1/auth/refresh` require:

```
Authorization: Bearer <access_token>
```

**Sign in:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@aspice.dev", "password": "secret"}'
```

**Use the token:**
```bash
curl http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer eyJhbGci..."
```

**Refresh (access token expires after 15 min):**
```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJhbGci..."}'
```

Refresh token lifetime: 7 days.

---

## 5. Seed data

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

## 6. Architecture — key decisions

### Domain models are pure dataclasses

`api/models/domain.py` contains 16 `@dataclass` classes. No SQLAlchemy,
no Pydantic ORM mode, no Django models. Routes and services import only
from here. The DB adapter converts to/from these.

### Repository pattern — the DB contract

`api/repositories/interfaces.py` defines 12 ABCs:

```
IUserRepository            IProjectRepository         IProjectMemberRepository
IAccessRequestRepository   IVersionRepository         ICommitRepository
IAnalysisJobRepository     IDocumentRepository        IDocumentAssignmentRepository
IFunctionRepository        ICompareRepository         INotificationRepository
```

Every concrete storage adapter must implement all of them.

### Swapping the database — one line

`api/db/session.py`:
```python
_db = InMemoryDatabase()   # ← replace this line only
```

Steps to add a real DB:
1. Implement all 12 ABCs.
2. Replace `InMemoryDatabase()` with your adapter in `session.py`.
3. Nothing else changes — routes and services only see the interfaces.

### RBAC is server-side

`require_project_admin` / `require_project_member` in `middleware/auth.py`
are called at the top of every protected route handler. The client's claimed
role is never trusted.

---

## 7. Known issues fixed on this branch

### bcrypt 4.x `__about__` AttributeError

`passlib 1.7.4` reads `bcrypt.__about__.__version__` which was removed in
bcrypt 4.x. Fixed in `middleware/auth.py` with a shim injected before passlib
imports:

```python
import bcrypt as _bcrypt
if not hasattr(_bcrypt, "__about__"):
    class _About:
        __version__ = getattr(_bcrypt, "__version__", "4.0.0")
    _bcrypt.__about__ = _About()
```

`api/requirements.txt` also pins `bcrypt>=3.2.0,<4.0.0` for clean installs.

### bcrypt 72-byte password limit

`bcrypt 4.x` strictly enforces the 72-byte limit (previously silently truncated).
Fixed by pre-hashing with SHA-256 + base64 before bcrypt, so bcrypt always
sees exactly 44 ASCII chars regardless of password length:

```python
def _prepare(plain: str) -> str:
    digest = hashlib.sha256(plain.encode()).digest()
    return base64.b64encode(digest).decode()
```

Both `hash_password` and `verify_password` call `_prepare` — consistent on
both sides so existing hashes verify correctly.

### Corrupt seed hash from `sed` dollar-sign escaping

An earlier `sed` substitution escaped `$` in the bcrypt hash, producing a
structurally plausible but internally corrupt 60-char string. bcrypt accepted
the length but failed verification, surfacing as a confusing error. Fixed by
regenerating the hash directly in Python and writing it with a Python script.

### `api/models/` blocked by `.gitignore`

The root `.gitignore` contains `model*` (intended for ML model files), which
matched `api/models/`. Fixed with `git add -f api/models/`.

---

## 8. Error envelope

All errors return:
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Document doc_999 does not exist.",
    "status": 404
  }
}
```

Error helpers live in `api/services/errors.py`:
`not_found`, `forbidden`, `conflict`, `bad_request`.

---

## 9. SSE — live job progress

```bash
curl -N -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/projects/p1/jobs/job1/events
```

Event types: `phase_update`, `activity_update`, `log_line`,
`job_complete`, `job_failed`. Emits every 3 seconds while the job is active.

---

## 10. Route summary (55 endpoints)

All under `/api/v1`. Full reference: `api/README.md`.

| Group | Prefix | Count |
|---|---|---|
| Auth | `/auth` | 5 |
| Projects | `/projects` | 9 |
| Commits & Versions | `/projects/:id/commits`, `/projects/:id/versions` | 8 |
| Jobs + Functions | `/projects/:id/jobs` | 8 |
| Documents | `/projects/:id/documents` | 16 |
| Team | `/projects/:id/members` | 6 |
| Compare | `/projects/:id/compare` | 3 |
| Functions | `/projects/:id/functions` | 2 |
| Notifications | `/notifications` | 3 |
| Repositories (wizard) | `/repositories` | 3 |
| Users | `/users` | 1 |
| Meta | `/health`, `/` | 2 |

---

## 11. JSON Database adapter (`api/db/json_db.py`)

Added on branch `feat/api-server`. A second concrete storage adapter that
uses JSON files instead of in-memory dicts, making the API state **persistent
across restarts** and **integrated with the document-generation pipeline**.

### Motivation

The `InMemoryDatabase` resets on every server restart.  The `JsonDatabase`:

1. **Persists all mutations** to `api/db/data/*.json` (write-through on every
   create/update/delete — one file per aggregate).
2. **Loads pipeline output automatically** — if `model/functions.json` exists
   (written by Phase 2 of the document-generation pipeline), its contents
   replace the seeded function data so the API always reflects the latest
   analysis run without any manual migration step.

### Directory layout

```
api/db/data/                ← created automatically on first startup
  users.json
  projects.json
  members.json
  access_requests.json
  versions.json
  commits.json
  jobs.json
  documents.json
  sections.json
  assignments.json
  functions.json            ← overwritten by pipeline output if model/ exists
  notifications.json
  compare_results.json
  compare_diffs.json

model/                      ← pipeline output (read-only from API perspective)
  functions.json            ← loaded on JsonDatabase init if present
  metadata.json             ← used to derive project name
```

### How to switch backends

**Environment variable (recommended):**
```bash
API_DB_BACKEND=json  uvicorn api.main:app --reload --port 8000
API_DB_BACKEND=memory uvicorn api.main:app --reload --port 8000  # default
```

**Code change (one line in `api/db/session.py`):**
```python
from .json_db import JsonDatabase
_db = JsonDatabase()          # was: InMemoryDatabase()
```

### First-run behaviour

1. If `api/db/data/` files are **absent** → seed from same dummy data as
   `InMemoryDatabase` and write files to disk.
2. If files **exist** → load as-is (mutations from previous runs are preserved).
3. If `model/functions.json` **exists** → replace the functions store with
   pipeline output (regardless of whether it was seeded or loaded from disk).

### Pipeline integration detail

`_load_pipeline_functions(model_dir)` in `json_db.py` reads
`model/functions.json` (written by Phase 1 + 2) and maps each entry to the
`Function` domain model.  The mapping handles the analyzer's key format
(`Layer::Component::FunctionName`) and field names (`componentName`, `layer`,
`isVisible`, `description`, etc.).  The result is keyed under `job1` (the
default seeded job ID) so the existing `/jobs/{job_id}/functions` endpoint
returns the real pipeline data with no route changes.

### Serialisation

All `datetime` and `date` objects are serialised to ISO 8601 strings via a
custom `_default` encoder passed to `json.dump`.  `_parse_dt` / `_parse_date`
handle both string inputs (from disk) and native Python objects (from the seed
path), so the adapter works correctly on both first-run seeding and subsequent
disk reloads.

### Write-through safety

Every mutating repository method calls `_save()` before returning.  `_save()`
uses an atomic rename (`path.with_suffix('.json.tmp') → path.replace(tmp)`) so
a crash mid-write never leaves a corrupt file — the old data survives until the
new write completes.

---

## 12. New-project wizard endpoints (real git)

Added on `feat/frontend-app` for the wizard's repository & team steps — the
**first change ever made under `api/`** (the frontend previously treated the API
as fixed and stubbed these client-side). The four endpoints below replace those
mocks, and the git-backed ones use **real `git`**, not simulation.

### Source of truth: `api/services/git_cli.py`

`api/services/repo_git.py` shells out via the API's **own** self-contained git
CLI wrapper [`api/services/git_cli.py`](./services/git_cli.py) — the API does
**not** import from `backend/`. Same conventions as the rest of the platform
(`shell=False`, credential scrubbing, `GIT_TERMINAL_PROMPT=0`):

| Primitive | git command | Purpose |
|---|---|---|
| `ls_remote(url, user, token)` | `git ls-remote --symref <url> HEAD "refs/heads/*"` | Connection test — branches + default branch, **no clone** |
| `shallow_clone(url, user, token, dest, ref, depth)` | `git clone --depth <n> [--branch <ref>]` | Read-only checkout (depth 1 to browse, larger to list commits); resets `origin` to a credential-free URL |
| `list_tree(repo_dir, ref)` | `git ls-tree -r --name-only` | Nested `{type,name,path,children?}` tree (folders-first sort) |
| `list_commits(repo_dir, branch, …)` | `git log origin/<branch>` | Recent commits `{sha, shortSha, author, authorEmail, date, message}` |

### Endpoints

| Method | Path | Backed by | Notes |
|---|---|---|---|
| POST | `/repositories/test-connection` | `git ls-remote` | Body `{repo_url, repo_provider?, access_token?}` → `{connected, default_branch, branches, message}`. Bad URL / auth / network → `connected:false` + friendly message (never raises). |
| GET | `/repositories/browse` | depth-1 clone + `git ls-tree` | Query `repo_url, ref?, path?, access_token?` → `{entries:[…]}`. Clone cached under `workspaces/_wizard/<sha16>` (gitignored), keyed by url+ref. `GitError` → 400. |
| POST | `/repositories/uploads` | process-local store | Multipart `file` + `kind` (`preprocessor_definitions`\|`data_dictionary`) → `{id, file_name, size, …}`. 5 MB cap; bytes reset on restart. |
| GET | `/users/search` | `IUserRepository.search` | Query `q`, `limit` → `{users:[{id,name,email,initials}]}`. Excludes the caller. |

### Credentials

Access tokens are passed to git as HTTPS credentials (PAT in the username
position, `https://<token>@host`) and are **never persisted** — `git_cli`
strips them from the clone's `origin` and from any error text. The wizard also
sends the token to `POST /projects`, where `CreateProjectRequest.access_token`
is stashed into `build_config` (`repo_access_token`) and never echoed
(`_project_view` omits `build_config`).

### New repository method

`IUserRepository.search(query, limit=10)` was added to the interface
(`repositories/interfaces.py`) and implemented in **both** adapters
(`_InMemUserRepo`, `_JsonUserRepo`): case-insensitive name/email substring match,
name-sorted, capped at `limit`.

### Tested

Smoke-tested e2e via `TestClient` against a throwaway **local** git repo (no
network): `ls-remote` branches + default branch, `ls-tree` files (incl. a
subpath), missing-repo → `connected:false`, upload + bad-kind rejection, user
search excludes the caller, and the project access token persisted in
`build_config` but absent from the project view.

Frontend wiring (how the wizard consumes these) is documented separately in
[`web-app/INTEGRATION_NOTES.md`](../web-app/INTEGRATION_NOTES.md)
→ "Repository wizard endpoints".

### Surfacing config pre-analysis

`_project_view` (`routes/projects.py`) returns, in addition to the existing
fields, `default_branch` and a **token-stripped** `build_config` (every key
except `repo_access_token`). This lets the frontend overview render a project's
captured configuration — repository, branch, compliance standard, architecture
layers, build config, and team — **before any analysis has run** (a freshly
created project is `status: not_run` with no documents/versions/commits). The
access token is still never exposed in any response.

### Backfilling commits

`GET /projects/:id/commits` (`routes/commits_versions.py`) lazily **backfills
real commits** the first time a project with no stored commits is viewed:
`_backfill_commits_from_repo` calls `repo_git.list_commits` (depth-limited clone
+ `git log` via `git_cli.list_commits`), maps each to a `Commit`, and `upsert`s
it. Best-effort — a git/network failure leaves the list empty. This is what lets
a wizard-created project show its real latest commit and lets **Run Analysis
start** (`POST /jobs` only needs a `commit_sha`). Private repos use the token
from `build_config`. The job is then driven to completion by the simulated
runner (next section).

### Simulated job runner

The server has no real analyzer worker, so [`api/services/job_runner.py`](./services/job_runner.py)
provides a **simulation**. `POST /jobs` spawns a daemon thread (`job_runner.start`)
that walks the job through the four phases — updating `phase`/`phase_pct`/activity
and phase durations as it goes, which the SSE stream (`/jobs/:id/events`) re-reads
every 3 s so the overview's progress banner animates — honouring cancel and
`pause_after_phase1`. On completion it marks the job `complete`, synthesises a
`Version` — named from the run's **`version_tag`** (the name typed in the Run
Analysis modal; auto `v0.x.0` if blank, made unique) — and a set of `Document`s
derived from the project's architecture (one SWE.2 per group, one SWE.3 per
component, plus global SYS.2/SWE.1), and flips the project to `in_review` so the
overview shows generated content. No C++ is parsed — replacing `_run` with a real
worker is the only change needed. Step timing is read from `JOB_SIM_STEP_SECONDS`
(env) at call time (tests set it near-zero).

`AnalysisJob` carries `version_tag` (the chosen version name, surfaced in
`_job_dict` for the overview's running banner) and resolves `branch` from the
selected commit at `POST /jobs`. The banner shows the **version** by default and
falls back to **branch @ commit** only when a non-latest commit was selected
(computed frontend-side by comparing `job.commitSha` to the latest commit).
