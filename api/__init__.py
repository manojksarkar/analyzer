"""
API package for the ASPICE Documentation Platform.

Architecture:
    api/
    ├── main.py                 — FastAPI app, router registration, CORS
    ├── requirements.txt        — pip dependencies for the API
    ├── models/
    │   └── domain.py           — Pure Python dataclasses (no DB coupling)
    ├── repositories/
    │   └── interfaces.py       — Abstract repository ABCs (the DB contract)
    ├── db/
    │   ├── in_memory.py        — In-memory adapter + seed data
    │   ├── json_db.py          — JSON-file adapter (reads model/ via ModelReader)
    │   └── session.py          — DB instantiation (swap here to change backend)
    ├── middleware/
    │   └── auth.py             — JWT creation/verification, FastAPI dependency
    ├── services/
    │   ├── errors.py           — Standardised HTTP error helpers
    │   ├── model_reader.py     — ModelReader: structured access to model/ directory
    │   └── document_renderer.py — Builds structured document tree from pipeline output
    └── routes/
        ├── auth.py             — POST /auth/signin, /refresh, GET /auth/me, ...
        ├── projects.py         — CRUD projects, access requests
        ├── commits_versions.py — Commits list, version CRUD
        ├── jobs.py             — Analysis jobs + SSE streaming + functions
        ├── documents.py        — Document list/detail, review workflow, export
        ├── team.py             — Member invite, role management
        ├── compare.py          — Diff between commits/versions
        ├── functions.py        — Function visibility management
        ├── notifications.py    — User notifications
        └── model.py            — GET /model/* — pipeline model data access

Swapping the database:
    1. Implement every ABC in api/repositories/interfaces.py
    2. In api/db/session.py, replace `InMemoryDatabase()` with your adapter
    3. Nothing else changes — routes and services depend only on the interfaces

Model data access:
    The pipeline writes model/*.json after each run.  ``ModelReader``
    (api/services/model_reader.py) is the single point of access for all
    those files; it is used by ``JsonDatabase``, ``document_renderer``, and
    the ``/api/v1/model`` routes.  Call ``model_reader.refresh()`` or POST
    ``/api/v1/model/refresh`` to reload data after a pipeline run.
"""
