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
    │   └── session.py          — DB instantiation (swap here to change backend)
    ├── middleware/
    │   └── auth.py             — JWT creation/verification, FastAPI dependency
    ├── services/
    │   └── errors.py           — Standardised HTTP error helpers
    └── routes/
        ├── auth.py             — POST /auth/signin, /refresh, GET /auth/me, ...
        ├── projects.py         — CRUD projects, access requests
        ├── commits_versions.py — Commits list, version CRUD
        ├── jobs.py             — Analysis jobs + SSE streaming + functions
        ├── documents.py        — Document list/detail, review workflow, export
        ├── team.py             — Member invite, role management
        ├── compare.py          — Diff between commits/versions
        ├── functions.py        — Function visibility management
        └── notifications.py    — User notifications

Swapping the database:
    1. Implement every ABC in api/repositories/interfaces.py
    2. In api/db/session.py, replace `InMemoryDatabase()` with your adapter
    3. Nothing else changes — routes and services depend only on the interfaces
"""
