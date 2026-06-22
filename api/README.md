# ASPICE Platform — API Server

REST API for the Automotive ASPICE Documentation Platform.
Built with **FastAPI** + **Python 3.12**, backed by an in-memory store seeded
with realistic dummy data.  The storage layer is fully swappable — see
[Swapping the database](#swapping-the-database).

---

## Quick start

```bash
# Install dependencies
pip install -r api/requirements.txt

# Start the server (from repo root)
uvicorn api.main:app --reload --port 8000
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

## Architecture

```
api/
├── main.py                 ← FastAPI app, router registration, CORS
├── requirements.txt        ← pip dependencies
│
├── models/
│   └── domain.py           ← Pure Python dataclasses — no DB coupling
│                             (User, Project, Document, AnalysisJob, …)
│
├── repositories/
│   └── interfaces.py       ← Abstract repository ABCs — the DB contract
│                             (IUserRepository, IProjectRepository, …)
│
├── db/
│   ├── in_memory.py        ← Concrete in-memory adapter + seed data
│   └── session.py          ← DB instantiation ← SWAP HERE to change backend
│
├── middleware/
│   └── auth.py             ← JWT creation/verification, FastAPI dependency,
│                             role-checking helpers
│
├── services/
│   └── errors.py           ← Standardised HTTP error helpers
│
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

### Design principles

- **Domain models are pure dataclasses** (`api/models/domain.py`).
  Routes and services work only with these — zero ORM import anywhere except
  the DB adapter.

- **Repository pattern** (`api/repositories/interfaces.py`).
  Every concrete storage adapter must implement the abstract classes defined
  here.  Switching databases means writing a new adapter; no route or service
  file changes.

- **One injection point** (`api/db/session.py`).
  `get_db()` is a FastAPI dependency that returns the active DB adapter.
  Replace the single `InMemoryDatabase()` instantiation here to swap backends.

- **Role enforcement is server-side**.
  `require_project_admin` / `require_project_member` helpers are called at the
  start of every protected handler.  The UI state is never trusted.

---

## API reference

Base path: `/api/v1`  
All endpoints except `/auth/signin` and `/auth/refresh` require
`Authorization: Bearer <token>`.

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/auth/signin` | Email + password → access token + refresh token |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/signout` | Invalidate tokens |
| GET | `/auth/me` | Current user profile |
| PATCH | `/auth/me` | Update name / avatar |

### Projects

| Method | Path | Description |
|---|---|---|
| GET | `/projects` | List projects for current user |
| POST | `/projects` | Create project (wizard) |
| GET | `/projects/:id` | Project detail + KPIs |
| PATCH | `/projects/:id` | Update project (admin) |
| DELETE | `/projects/:id` | Delete project (admin) |
| GET | `/projects/search` | Search discoverable projects |
| POST | `/projects/:id/access-requests` | Request access |
| GET | `/projects/:id/access-requests` | List pending requests (admin) |
| PATCH | `/projects/:id/access-requests/:reqId` | Approve / deny request (admin) |

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
| POST | `/projects/:id/jobs` | Start analysis job (admin, 202 Accepted) |
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
| GET | `/projects/:id/documents/:docId` | Full doc with sections |
| PATCH | `/projects/:id/documents/:docId` | Update status (admin) |
| GET | `/projects/:id/documents/:docId/download` | Download DOCX |
| GET | `/projects/:id/documents/:docId/export` | Export single doc |
| POST | `/projects/:id/documents/export-all` | Zip export |
| POST | `/projects/:id/documents/:docId/assignments` | Assign reviewer(s) (admin) |
| DELETE | `/projects/:id/documents/:docId/assignments/:userId` | Remove assignee |
| POST | `/projects/:id/documents/assignments/batch` | Batch assign |
| POST | `/projects/:id/documents/:docId/assignments/self` | Self-assign (developer) |
| PATCH | `/projects/:id/documents/:docId/sections/:key` | Accept / decline / edit section |
| POST | `/projects/:id/documents/:docId/submit-review` | Submit full review |
| POST | `/projects/:id/documents/:docId/approve` | Approve document (admin) |
| POST | `/projects/:id/documents/:docId/request-changes` | Request changes (admin) |
| POST | `/projects/:id/documents/approve-all` | Bulk approve (admin) |

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

## Swapping the database

1. Implement every ABC in `api/repositories/interfaces.py`
   (12 classes: `IUserRepository`, `IProjectRepository`, etc.)

2. Create your adapter class (e.g. `PostgresDatabase`) that exposes the same
   attribute names as `InMemoryDatabase`.

3. In **`api/db/session.py`** replace the one line:

   ```python
   # Before
   _db = InMemoryDatabase()

   # After
   _db = PostgresDatabase(dsn=os.environ["DATABASE_URL"])
   ```

4. Done — no route or service file needs to change.

---

## Real-time (SSE)

Connect to `GET /api/v1/projects/:id/jobs/:jobId/events` with an
`EventSource` in the browser or `curl -N`:

```bash
curl -N -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/projects/p1/jobs/job1/events
```

Event types: `phase_update`, `activity_update`, `log_line`,
`job_complete`, `job_failed`.
