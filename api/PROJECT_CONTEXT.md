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

## 12. Structured document endpoint (`GET /projects/:id/documents/:doc_id?structured=true`)

Added on branch `feat/api-server`. The `GET /projects/:id/documents/:doc_id`
endpoint gains an optional `?structured=true` query parameter that returns
a **full hierarchical document tree** matching the layout generated by
`src/docx_exporter.py`, suitable for direct rendering in a UI.

### Why

The existing flat `sections[]` array (stored in the DB) was written by
reviewers and doesn't capture the rich SDD structure the pipeline produces:
section numbering, component/unit/function hierarchy, interface tables,
unit-header tables, flowchart Mermaid strings, and behaviour-diagram data.
The new response gives the UI everything it needs to render a faithful
preview of the DOCX without executing the pipeline again.

### Response shape (`?structured=true`)

```json
{
  "document": {
    "id": "doc1",
    "name": "Brake Controller",
    "status": "in_review",
    "review_progress": {"resolved": 2, "total": 4},
    "assignees": [...],

    "cover": {
      "project_name": "VCU Engine Firmware",
      "subtitle": "Software Detailed Design Specification — APP_LAYER Chassis_Mgmt",
      "version": "v1.2.0",
      "document_name": "Brake Controller",
      "document_process": "SWE.3",
      "layer": "APP_LAYER",
      "group": "Chassis_Mgmt"
    },

    "toc": [
      {"id": "s1",      "number": "1",     "title": "1 Introduction",   "level": 1},
      {"id": "s1_1",    "number": "1.1",   "title": "1.1 Purpose",      "level": 2},
      ...
    ],

    "sections": [
      {
        "id": "s2",
        "number": "2",
        "title": "2 Chassis_Mgmt",
        "level": 1,
        "type": "component",
        "content": null,
        "table": null,
        "review_state": null,
        "children": [
          {
            "id": "s2_1",
            "number": "2.1",
            "title": "2.1 Static Design",
            "level": 2,
            "type": "static_design",
            "children": [
              {
                "id": "s2_1_overview",
                "type": "component_overview",
                "table": {
                  "type": "component_unit_table",
                  "columns": ["Component", "Unit", "Description", "Note"],
                  "rows": [...]
                }
              },
              {
                "id": "s2_1_1",
                "number": "2.1.1",
                "title": "2.1.1 brake_ctrl",
                "level": 3,
                "type": "unit",
                "children": [
                  {
                    "id": "s2_1_1_1",
                    "type": "unit_header",
                    "table": {
                      "type": "unit_header_table",
                      "columns": ["global variables / typedef / enum / define", "information"],
                      "rows": [...]
                    }
                  },
                  {
                    "id": "s2_1_1_2",
                    "type": "unit_interface",
                    "table": {
                      "type": "interface_table",
                      "columns": ["Interface ID", "Interface Name", "Information", ...],
                      "rows": [
                        {
                          "interface_id": "IF_APP_CHASSIS_MGMT_BRAKE_CTRL_01",
                          "interface_name": "BrakeCtrl_Run",
                          "information": "Main cyclic execution ...",
                          "data_type": "float32; float32[4]",
                          "data_range": "0.0..100.0; 0.0..3000.0",
                          "direction": "In",
                          "source_dest": "Powertrain/ThrottleCtrl_Run",
                          "interface_type": "Function"
                        }
                      ]
                    }
                  },
                  {
                    "id": "s2_1_1_3",
                    "type": "flowchart",
                    "content": "Main cyclic execution description",
                    "table": {
                      "type": "flowchart",
                      "function_name": "BrakeCtrl_Run",
                      "signature": "void BrakeCtrl_Run(float32 pedalPos, ...)",
                      "input_label": "Brake input",
                      "output_label": "Brake result",
                      "flowcharts": [
                        {
                          "signature": "...",
                          "mermaid": "flowchart TD\n  A[Start] --> ...",
                          "png_key": "Chassis_Mgmt_brake_ctrl_BrakeCtrl_Run"
                        }
                      ]
                    }
                  }
                ]
              }
            ]
          },
          {
            "id": "s2_2",
            "type": "dynamic_behaviour",
            "children": [
              {
                "id": "s2_2_1",
                "type": "behaviour_entry",
                "table": {
                  "type": "behaviour",
                  "current_function": "BrakeCtrl_Run",
                  "external_unit_function": "throttle_ctrl - ThrottleCtrl_Run",
                  "behaviour_description": [...],
                  "png_path": "/abs/path/to/diagram.png"
                }
              }
            ]
          }
        ]
      }
    ],

    "meta": {
      "pipeline_data_available": true,
      "source": "pipeline",
      "components": ["Chassis_Mgmt", "Powertrain"]
    }
  }
}
```

### Section `type` values

| type | description |
|---|---|
| `introduction` | §1 wrapper |
| `purpose` | §1.1 |
| `scope` | §1.2 |
| `terms` | §1.3 abbreviations table |
| `component` | §N top-level per-component |
| `static_design` | §N.1 |
| `component_overview` | Component/Unit/Description index table |
| `unit` | §N.1.K per-unit |
| `unit_header` | §N.1.K.1 globals/typedef/enum/define table |
| `unit_interface` | §N.1.K.2 interface table (8 columns) |
| `flowchart` | §N.1.K.M per-function with optional Mermaid |
| `dynamic_behaviour` | §N.2 wrapper |
| `behaviour_entry` | §N.2.M per-function sequence diagram |
| `metrics` | Code metrics section |
| `appendix` | Appendix A |

### Data sources

| Field | Source |
|---|---|
| Interface rows | `output/interface_tables.json` |
| Flowchart Mermaid | `output/flowcharts/*.json` |
| Behaviour data | `output/behaviour_diagrams/_behaviour_pngs.json` |
| Unit header | `model/units.json` + `model/dataDictionary.json` + `model/globalVariables.json` |
| Function I/O labels | `model/functions.json` (behaviourInputName / behaviourOutputName) |
| Hidden functions | `model/functions.json` (`hidden: true`) |

### Fallback (pipeline not run)

When `output/interface_tables.json` doesn't exist, `source` is
`"stored_sections"` and the response is built from the flat
`DocumentSection` records stored in the DB (what reviewers saved).
Markdown tables in `interfaces` sections are parsed into a
`markdown_table` structured table. The legacy flat response is
always available without `?structured=true`.
