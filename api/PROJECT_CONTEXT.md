# API Server — Project Context

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
│   └── errors.py           ← Consistent HTTP error envelope helpers
└── routes/
    ├── auth.py             ← POST /auth/signin|refresh|signout, GET/PATCH /auth/me
    ├── projects.py         ← CRUD projects, access requests
    ├── commits_versions.py ← Commits list, version CRUD
    ├── jobs.py             ← Analysis jobs + SSE streaming + function list
    ├── documents.py        ← Documents, section review, approve, export
    ├── team.py             ← Member invite, role management
    ├── compare.py          ← Diff between commits / versions
    ├── functions.py        ← Function visibility management
    └── notifications.py    ← User notifications
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

## 10. Route summary (51 endpoints)

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
| Meta | `/health`, `/` | 2 |
