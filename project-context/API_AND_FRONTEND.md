# API server, the superseded backend, the frontend designs

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Some of it has drifted since: read the index's [What changed
> after the numbered sections](../PROJECT_CONTEXT.md#what-changed-after-the-numbered-sections) first.

**Sections:** [19. API Server (`api/`)](#19-api-server-api) · [21. Companion: the older FastAPI backend (SUPERSEDED)](#21-companion-the-older-fastapi-backend-superseded) · [24. Frontend — `frontend/designs/`](#24-frontend--frontenddesigns)

## 19. API Server (`api/`)

> Full context lives in **[`api/PROJECT_CONTEXT.md`](../api/PROJECT_CONTEXT.md)** — read that file for anything API-related. This section is a brief pointer only.

The `api/` directory is a standalone FastAPI REST server added on branch
`feat/api-server`. It exposes all platform functionality over HTTP and ships
with an in-memory database seeded with realistic dummy data.

Key facts:
- **Start:** `uvicorn api.main:app --reload --port 8000` (after `pip install -r api/requirements.txt`)
- **Docs:** http://localhost:8000/docs (Swagger UI)
- **Auth:** `POST /api/v1/auth/signin` → Bearer token → `Authorization: Bearer <token>` on every request
- **Seed credentials:** any of the five seed users (e.g. `alice@aspice.dev`) with password `secret`
- **Swap the DB:** set `API_DB_BACKEND=json` env var (or change one line in `api/db/session.py`) — two built-in adapters: `InMemoryDatabase` (default) and `JsonDatabase`
- **JSON DB:** `API_DB_BACKEND=json` persists state to `api/db/data/*.json` and automatically loads `model/functions.json` from the pipeline output on startup
- **51 endpoints** across auth, projects, commits/versions, analysis jobs, documents, team, compare, functions, notifications

See [`api/PROJECT_CONTEXT.md`](../api/PROJECT_CONTEXT.md) for architecture decisions, known issues, seed data, SSE streaming, error envelope, the full route list, and JSON DB adapter details (§11).

---

## 21. Companion: the older FastAPI backend (SUPERSEDED)

> **⚠️ Superseded / historical.** This section documents an older version3/4 FastAPI
> backend, replaced by the current `api/` server (§19). Path/name references below
> predate the `src → backend → engine` renames and may be stale (e.g. an `engine/main.py`
> mentioned here never existed at that path — it was the old server's `backend/main.py`).

> **Integration status (version4):** the `engine/` layer and the
> `docs/production-redesign/` design docs were brought onto this branch from
> `version3`, on top of the newer `main` code line. The backend was written
> against the **older `modulesGroups` / `module` schema** and the
> `model/modules.json` filename. This `main`-based code line instead uses the
> **`layers` config + `component` terminology + `model/components.json`** (see
> §4d, §6) and adds CLI flags (`--selected-layer`, `--selected-component`,
> `--data-dictionary`, `--macros`, `--include-path`, `--project-name`).
> **Adapting the backend to that schema and flag set is an open follow-up**
> before it runs correctly against this analyzer. The description below is the
> backend *as built on version3*.

Starting in version3, the analyzer pipeline is also reachable over HTTP
through a small FastAPI service that the external UI talks to. This
section is intentionally short — it orients you to the layer; the
authoritative reference is **[engine/PROJECT_CONTEXT.md](../engine/PROJECT_CONTEXT.md)**
(~930 lines covering all endpoints, request/response shapes, design
decisions, and the development history).

### What the backend is, and isn't

- **What it is**: a thin async wrapper around `run.py`. It spawns the
  analyzer as a subprocess (`_spawn_run_py`), tails its stdout+stderr
  to per-job log files, parses `[N/M] === Phase X: ... ===` markers
  for progress, and exposes the model artifacts that the analyzer
  already produces (functions, components, flowcharts, the exported
  DOCX).
- **What it isn't**: a re-implementation of the pipeline. The backend
  never imports analyzer internals — it only reads JSON the analyzer
  writes and shells out to `python engine/run.py`. The pipeline contract
  documented in §3, §10–§14 is the single source of truth.

### Process model

- FastAPI on `:8000`, CORS pinned to `http://localhost:5173` (the Vite
  dev server the UI runs on).
- Jobs live in an in-memory `_jobs: dict[str, JobState]` — **no
  persistence by design**. Restarting the backend forgets in-flight
  jobs, but already-exported DOCX files on disk remain downloadable
  via `GET /jobs/{jobId}/download` (the endpoint resolves by reading
  `output/*.docx` directly).
- Each spawned subprocess writes to
  `logs/job_<job_id>.out.log` (interleaved stdout+stderr). The
  `GET /jobs/{jobId}/preplogs` endpoint tails this file rather than
  buffering in process memory.
- Process tree kill uses `taskkill /F /T` on Windows and `killpg(SIGKILL)`
  on POSIX so cancelling a job actually stops the whole subprocess tree
  (parser/model_deriver/run_views/docx_exporter can spawn children).

### Progress: canonical 4-phase mapping

The pipeline has variable plan counts (build-only vs build+views vs
views-only, multi-group runs) and inside-plan phase counts (some plans
have 2 phases, others 4). To give the UI a stable progress bar:

- A **canonical 4-phase** taxonomy is exposed regardless of the
  actual plan shape: Parse C++ source → Derive model → Generate
  views → Export to DOCX.
- `_PHASE_NAME_TO_NUMBER` maps phase labels (case-folded) to
  `phaseNumber` 1..4.
- `_CANONICAL_TOTAL = 4` is always returned as `totalPhase` (even when
  the actual plan has only 2 phases — `totalPhase` is canonical, not
  literal).
- `_expected_phase_markers(selected_group, from_phase)` predicts the
  total number of `=== Phase ... ===` markers the run will emit, used
  to compute `overallProgress` monotonically. This was the fix for the
  "75% → 25% → 100%" regression: previously `overallProgress` was
  computed from "markers seen / markers in current plan", which jumped
  backwards across plan boundaries.
- The `phase` field strips a leading `Phase N: ` prefix
  (`_PHASE_LABEL_PREFIX_RE`) — the UI wants the bare phase name.

### Config editing: surgical JSONC splice

`POST /api/v1/config` updates only the `modulesGroups` key inside
`engine/config/config.defaults.json` while preserving every comment and every other
key in the file. The implementation (`_find_modules_groups_key_pos`)
is a small JSONC-aware state machine that tracks strings, line
comments, block comments, and brace nesting depth — a regex or a
`json.loads` + `json.dumps` round-trip would either miss commented
duplicates or strip every `//` and `/* */` comment from the file.
Earlier attempts to do this with `json.loads` deleted ~80% of the
config; the surgical splice is the only safe path. Backup files are
**not** written (the user explicitly opted out — git is the backup).

> **Schema note (version4):** on this `main`-based code line the config key
> is **`layers`** (two-level), not `modulesGroups`, and the model file is
> `model/components.json`, not `modules.json`. The splice target and the
> component/module-keyed read paths must be updated when the backend is
> adapted (see the Integration status note above).

### Multi-repository CRUD

`engine/repository_config.json` is a list of `{name, path}` entries
(see `engine/models.py:Repository`). Endpoints that previously took
just a path now accept `?name=<repo>` query parameters; the backend
resolves the name to a directory via `_resolve_repository_path` and
auto-migrates legacy single-repo `{path: "..."}` files to
`[{name: "default", path: "..."}]` on first read.

### Where to read more

The full endpoint catalog (17 endpoints), request/response examples,
and the lessons-learned section (12 entries: venv mismatches, the
config splice 80% bug, progress monotonicity, hiddenFns evolution,
PNG slicing, ELK feedbackEdges, lossy-rewrite reversal, Windows
shell=True quirks, etc.) is in
[engine/PROJECT_CONTEXT.md](../engine/PROJECT_CONTEXT.md). API examples
with curl payloads are in [engine/API_DOC.md](../engine/API_DOC.md). A
sample response fixture lives at
[engine/fixtures/get_components_FTL.json](../engine/fixtures/get_components_FTL.json).

---

## 24. Frontend — `frontend/designs/`

Branch: `feat/frontend-app`. HTML design mockups in `frontend/designs/` are the reference specs; the working React app lives in `frontend/app/` (Vite + React + TS + Tailwind v4) and ports each design 1:1. Full UI context in `frontend/UI_CONTEXT.md`.

> **On `feat/web-app-api-port` the app moved to `web-app/` and is wired to the live FastAPI API (§19), not mock data.** The detail below describes the earlier `frontend/app/` mock-data state. For the current app, read the web-app docs directly: the **`ui-dev` skill** (`.claude/skills/ui-dev/`, engineering rules — was `web-app/CONVENTIONS.md`), **`web-app/INTEGRATION_NOTES.md`** (API wiring, per-page gaps), **`web-app/TESTING.md`** (vitest unit + `npm run test:api` contract suite).

**Team-facing doc:** `frontend/app/README.md` — stack, run commands, folder structure, and the core conventions (tokens-not-hex, read data through `hooks/`, thin pages, commit style). `UI_CONTEXT.md` covers the product/design *what & why*; the README covers the engineering *how*.

### Design system

- Tailwind CSS + Material Symbols Outlined (self-hosted via the `material-symbols` npm package — `@import "material-symbols/outlined.css"` in `web-app/src/index.css`; no Google Fonts `<link>`, fully offline)
- Fonts: Inter (body/headlines), JetBrains Mono (labels/code)
- Color tokens: navy `#041627`, blue `#0058be`, green `#00a572`

### Page inventory

| # | File | Sidebar | Subbar | What it covers |
|---|------|---------|--------|----------------|
| 1 | `signin.html` | none | no | Two-panel auth: branding left, SSO + email/password form right |
| 2 | `projects.html` | 220px | yes | All-projects table; ADMIN/DEV badges, row kebab menu (Settings / Archive / Delete) |
| 3 | `projects-empty.html` | 220px | yes | Empty state + 5-step onboarding wizard; Request Project Access modal |
| 4 | `project-detail.html` | 220px | yes | Project overview: KPI cards, generation progress, documents table, team list, review queue, function-visibility slide-over, Run Analysis modal, Admin/Developer role switcher |
| 5 | `documents.html` | 56px collapsed | yes | Document list: process filter tabs, status/assignee filters, batch actions, edit-section modal, assign-reviewers slide panel |
| 6 | `compare.html` | 56px collapsed | yes | Split diff: reference left / current right; per-section Accept/Decline/Edit; review footer with progress dots |
| 7 | `versions.html` | 56px collapsed | yes | Tagged version cards (In Review / Approved); untagged commits timeline; filter tabs |
| 8 | `team.html` | 220px | yes | Team table: role dropdowns, pending invites, Invite Member modal, permission legend |
| 9 | `projects-portfolio.html` | none | no | Org-level (portfolio) variant of the main Projects screen for a new role **above** project admin: a portfolio roll-up above the unchanged projects table — 4-card KPI strip (projects · overall approval % · in-review backlog · needs-attention), then a 3-panel insight row (Projects-by-status donut, Needs-attention list → `project-detail.html`, Review-workload bars). Role surfaced via an `ORG ADMIN` header pill. Static design artifact only; roll-up numbers derived from the same 5 sample rows as `projects.html` so the strip matches the table |

### React app implementation (`frontend/app/`)

The Vite + React + TS app under `frontend/app/` ports every design HTML to a route. As of `98af777` all screens — **including the five inner pages** — are faithful 1:1 ports of their design HTML. (Earlier those five were simplified sketches missing 50–80% of the design DOM — panels, KPI strips, sub-bars, state variants, detail rows; rebuilt 2026-06-22.)

| Design HTML | React page (`src/pages/`) | Route |
|---|---|---|
| `signin.html` | `SignInPage.tsx` | `/signin` |
| `projects.html` | `ProjectsPage.tsx` | `/projects` |
| `projects-empty.html` | `ProjectsEmptyPage.tsx` | `/projects/new` |
| `project-detail.html` | `ProjectDetailPage.tsx` | `/projects/:projectId/overview` (index) |
| `documents.html` | `DocumentsPage.tsx` | `/projects/:projectId/documents` |
| `compare.html` | `ComparePage.tsx` | `/projects/:projectId/compare` |
| `versions.html` | `VersionsPage.tsx` | `/projects/:projectId/versions` |
| `team.html` | `TeamPage.tsx` | `/projects/:projectId/team` |

`/` and unmatched paths redirect to `/projects`; all non-auth routes are wrapped in `ProtectedRoute`.

- **Shared shell**: the four project-scoped routes render inside `ProjectLayout` → `Sidebar` + `Topbar` + `Subbar` + `<Outlet>`.
- **Data**: `@tanstack/react-query` hooks (`useProject` / `useDocuments` / `useTeam` / `useVersions` / `useCommits`) over mock data in `src/data/mock.ts` (5 projects, 15 documents, 9 team members incl. 1 pending, 3 versions, untagged commits).
- **State**: Zustand `ui` store holds `roleView` (Admin/Dev toggle in the Topbar — drives admin-vs-developer page content) + `sidebarCollapsed`; `auth` store (persisted) gates `ProtectedRoute`. Page state (never / running / in_review / complete / stale) is driven per-project by `project.pageState`, **not** a dev toolbar.
- **Tailwind v4** (`@import "tailwindcss"` + `@theme {}`, no config file). The design HTML uses the Tailwind **v3** CDN, so its named type-scale classes (e.g. `text-body-md`, `font-label-sm`) are not portable — ported with explicit inline styles / v4 utilities. Verify production builds with `npm run build` (`tsc -b` catches `Record<DocStatus,…>` exhaustiveness errors that `tsc --noEmit` misses).

### Shell rules

**Sidebar** — context-progressive:
- `signin.html` and `projects.html` have **no sidebar** — full-width, logo top-left.
- All project-scoped pages (4–8): **project sidebar** (220px expanded / 56px collapsed):
  - `← All Projects` → `projects.html`
  - Project name label (10px uppercase)
  - Overview → `project-detail.html` · Documents → `documents.html` · Compare → `compare.html` · Versions → `versions.html` · Team → `team.html`
  - Settings at bottom (below `border-t`)
- `documents.html`, `compare.html`, `versions.html` default to **collapsed (56px)**.

**Subbar** (all project-scoped pages):
```
[ 📁 VCU Engine Firmware ▾ ]  ·  [ v1.2.0 ▾ ]  ·  ⑂ main @ d9a0c55  ·  Jun 15    [CTA]
```
- CTAs: project-detail `[▶ RUN ANALYSIS]`, documents `[↓ Download All]`, compare `[✓ Accept All] [✗ Reject All]`, team `[+ Invite]`, versions — none

**Breadcrumbs** — always start with `[⬡]` home (→ `projects.html`):
`Overview` · `Documents` · `Documents / Compare` · `Versions` · `Team`

### Navigation flow

```
signin.html → projects.html (no sidebar)
  └─ click row → project-detail.html (220px sidebar)
       ├─ Documents → documents.html (56px) → Compare → compare.html (56px)
       ├─ Versions  → versions.html (56px)
       └─ Team      → team.html (220px)
```

---

_End of file._
