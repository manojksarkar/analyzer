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
| `compare.html` | `ComparePage/` (by version id since 2026-10-04) | `/projects/:projectId/compare` |
| `versions.html` | `VersionsPage.tsx` | `/projects/:projectId/versions` |
| `team.html` | `TeamPage/` | `/projects/:projectId/team` |

`/` and unmatched paths redirect to `/projects`; all non-auth routes are wrapped in `ProtectedRoute`.

- **Shared shell**: the four project-scoped routes render inside `ProjectLayout` → `Sidebar` + `Topbar` + `Subbar` + `<Outlet>`.
- **Data**: `@tanstack/react-query` hooks (`useProject` / `useDocuments` / `useTeam` / `useVersions` / `useCommits`) over mock data in `src/data/mock.ts` (5 projects, 15 documents, 9 team members incl. 1 pending, 3 versions, untagged commits).
- **State**: Zustand `ui` store holds `roleView` (Admin/Dev toggle in the Topbar — drives admin-vs-developer page content) + `sidebarCollapsed`; `auth` store (persisted) gates `ProtectedRoute`. Page state (never / running / in_review / complete / stale) is driven per-project by `project.pageState`, **not** a dev toolbar.
- **Tailwind v4** (`@import "tailwindcss"` + `@theme {}`, no config file). The design HTML uses the Tailwind **v3** CDN, so its named type-scale classes (e.g. `text-body-md`, `font-label-sm`) are not portable — ported with explicit inline styles / v4 utilities. Verify production builds with `npm run build` (`tsc -b` catches `Record<DocStatus,…>` exhaustiveness errors that `tsc --noEmit` misses). **Browser floor = Chrome/Edge 99, Firefox 97, Safari 15.4**: `vite.config.ts` lowers Tailwind v4's nested CSS / range media queries / `color-mix()` via `css.transformer: 'lightningcss'` + `css.lightningcss.targets` (dev server) and `build.cssTarget` (build) — both needed (2026-09-30e entry).

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


### Review & update in the web app (2026-10-01)

The document reader corrects the LLM's wording in place. **Edit** (Subbar, SWE.3 only; any member)
turns each correctable text into a box that saves on leaving it; **Edit flowchart** corrects one
chart's box labels together; a banner says when the Word files lack the latest corrections, with
**Re-export** for admins. Editing pauses while a run or a re-export is going.

- **API** — `api/services/doc_render.py` puts each text's slot in the render payload (`_Slots`,
  `load_overrides`: one query for the version's corrections): `table.cell_slots`,
  `flowchart_table.*_slot`, `behavior_table.*_slot`, `content_slot`, and `flowcharts[].flowchart_id` /
  `editable`. A record row of the unit header shows the model's `structDescription`, which a save
  writes, instead of Phase 3's copy (stale until a re-export). Tests: `tests/api/test_render_carries_slots.py`.
- **Web** — `pages/DocumentInspectorPage/` is a folder now: `components/Sections.tsx` (the section
  views, memoised), `SlotText.tsx` (one text: read mark, editor, Undo, History), `FlowchartLabelDialog.tsx`,
  `ReviewBars.tsx` (R9 banner + Re-export, the Editing bar), `RightPanel.tsx` + `OutlineTab.tsx` +
  `CorrectionsTab.tsx` (+ the moved `ReviewTracker.tsx`), `TreeRail.tsx`; `outline.ts` (pure, tested),
  `editContext.ts`, `useScrollSpy.ts`. Data: `services/api/review.ts`, `services/mappers/review.ts`,
  `hooks/useReview.ts`; `projectKeys.review(…)` keys live under their own prefix. A save reads the
  render again; the flowchart `<img>` URL carries `?v=<source_hash>` (added in the mapper, after
  `resolveAssetUrl`) so a redrawn SVG reloads.
- **Rules** — the `ui-dev` skill §6; the contract's page section is REVIEW_UPDATE_API_SPEC §3a.
- **Mockup** — `docs/ui-mockups/documents.html` (open with `#edit`).
- **Since 2026-10-05** (history 11 2026-10-05 … and 13): a save met by a run that replaced the model
  answers 409 `{code: VERSION_REGENERATING}` (the other refusals stay strings); a save's queued texts
  carry `label`; R9 adds `staleComponents` (per-component, read in one pass:
  `export_guard.stale_components`) and ignores corrections in components with no document; R12
  `DELETE …/overrides/orphans` (admins) discards orphans; Phase 3 puts back a correction the model
  lost (`carry_forward.restore_missing_corrections`, RF-1). The web reads R1 in pages of 1000, blocks
  U+0000, counts an undone correction as not corrected, shows orphans inline, lists R10 in the
  Corrections tab, and marks only the stale components' downloads.

### Staged generation (2026-10-02)

A version's model (Phases 1-2) covers whole layers; its documents (Phases 3-4) are made per component,
by any number of runs into the same version: `generate` (or `--model-only`), `export` (components not
generated yet), `reexport` (again), `resume` (after a crash). Human guide:
[CLI_COMMANDS](../docs/CLI_COMMANDS.md#a-run-that-lasts-days); decisions: the untracked notes
`staged-generation-2026-10-01.md` (repo root).

- **Tables** (migration 0016): `version_components` — one row per component a run ASKED for
  (waiting → generating → generated | failed; run.py marks them around each component's plan,
  `RunPlan.components`); `version_runs` — the latest run's command line, process, log, frozen code and
  progress (the phases' `ProgressReporter` publishes, ≤ every 20 s). **Alive** is a Postgres advisory
  lock the run's process holds (`engine/core/version_run.py`: `writing`, `holder`, `alive`), never a
  column; SQLite has no lock (alive = unknown).
- **One writer per version** — CLI `generate`/`export`/`reexport`/`resume` and the web jobs
  (`pipeline_runner._version_writer`, on the API's own engine) take the lock; a second is refused
  (`VersionBusy`; web re-export 409 `VERSION_BUSY`). Storing output replaces the version's stored files
  (`persist_output_files`), so two writers lost documents before.
- **The view** — `api/services/version_components.py` `components_view`: the model's components
  (`model_components`) ∪ rows ∪ documents; no row + documents = generated, neither = `not_requested`,
  waiting/generating with no live writer = `stopped`. The rules for which components each command
  makes are `engine/incremental/staged.py` (pure).
- **A layer added to a version** (2026-10-04e). `export` of a component whose layer the model does
  not hold adds the layer to the SAME version (`analyzer.py _layers_adder`, run inside
  `_render_version`'s writer lock via `before=`; `engine/incremental/extend.py`): capture the model's
  LLM text + a per-component fingerprint of the structural fields → widen the manifest scope (a
  `resume` re-parses every layer) → `run.py --to-phase 1` with `--selected-layer` for every layer, old
  and new (a full parse of the union: Layer 1 → Layer 2 calls are only found by re-parsing Layer 1; the
  narrowed-parse merge was rejected — no Layer 1 → Layer 2 edges, same-named types keyed differently)
  → `snapshot_parse_model` → `restore_text` (old text back where the new rows are empty) →
  incremental plan `impactFids`/`impactedGlobals` = new entities only, `unitDescriptions` = the old
  units' text (model_deriver pre-fills them; units are rebuilt blank), `addedLayers: True` →
  `run.py --from-phase 2 --to-phase 2` → the version's previous plan put back → documented components
  whose fingerprint moved are marked **`stale`** (documents left as they are, review status
  untouched) → the finished `pipeline_status` put back → Phases 3-4 for the requested components as
  any export. The view lists the config's components not in the model (`in_model: false`,
  `layer_parsed`); `staged.layers_to_add`; `resume` of a cut-short add runs the export again;
  `reexport` of a stale component goes from Phase 3 (`auto` escalates, an explicit 4 is refused).
  **Proved** on a cross-layer copy of the sample (Layer1.Math ↔ Layer2.Gpio): the extended model
  equals a one-run model of both layers table for table, Layer2.Gpio's documents are byte-identical,
  only Layer1.Math goes stale, and its re-export is identical too (`_derivations.json` differs in
  build times only). Phase 2 asks the LLM only for the new layer; Phase 1 re-parses every layer.
  **Recovery**: the capture is stored before the parse (`parse_snapshots` row `add_layers_pending`)
  and reused by a retry or `resume` (which checks it before anything else); `reexport` is refused
  while it exists; it is removed once the add finishes, or when its parse fails (nothing changed).
  Proved: an add killed mid-parse, then `resume`, equals the one-run model.
- **Routes** (`api/routes/version_components.py`): `GET /projects/{pid}/versions/{vid}/components`
  (components, counts, `run` with `alive`/`stopped`); `POST …/versions/{vid}/documents/generate
  {components}` → 202, a job `mode: "export"` (`RENDER_MODES` = reexport + export: never "the project's
  run") running `analyzer.py export`; 422 `INVALID_COMPONENTS`, 409 `NO_MODEL` / `NOTHING_TO_GENERATE` /
  `VERSION_BUSY` / `EXPORT_RUNNING`; `POST …/versions/{vid}/resume` (below).
- **Web** (2026-10-05t; was the Documents page's `ComponentsPanel`, now gone) — one conditional row,
  `components/run/GenerationBanner.tsx`, above the Overview's KPI strip and above the Documents card (also
  on the Documents page's "running, no documents yet" state; on the Overview's "no documents yet" state for
  a picked version that has a model — the model-first run). It shows only while a component has no
  documents, a run or web job is at work, a run stopped, or a component is out of date: at work it names
  the run by `run.command`, the stage in words (`lib/versionComponents.ts runActivity`) and when it
  started; stopped, the `resume … --detach` command; out of date, a second row (`StaleRow.tsx`, replaced
  by task 1's Word-files row). Everything generated and nothing running → nothing. The Documents page's
  row is compact (no stage, start time or Stop). "View components" opens `ComponentsDrawer.tsx` (a right
  sheet, `ui/Drawer.tsx`; `?components=1` opens it): the Architecture view's layout, layer → group →
  chips (`ComponentChip.tsx`), one word per state — Has documents, Out of date, In progress, Queued,
  Stopped, Failed, Not started — a search and "Without documents"; an admin picks chips (or a layer's
  with "Select N") and Generates (`POST …/documents/generate`), a developer reads it. A chip's group is the
  API's `group` (the version's `resolved_config`, `version_components.config_groups`), else the project's
  architecture. Other Runs skips the version the banner shows (`exceptVersionIds`). Data:
  `services/api/versionComponents.ts`, mapper, `hooks/useVersionComponents.ts` (polls every 10 s while
  something is being made; re-reads the documents when one finishes). **Stop** (admin, 2026-10-02c, on
  the Overview's row): `GET …/components` names the web job at work on the version (`job`: id, mode,
  status — a Components → Generate job is never `jobs/current`); Stop asks first (`StopRunDialog`: an
  export keeps what is finished, the version's own run is removed) and calls `POST /jobs/{id}/cancel`
  (`useCancelJob`). An API that does not send `job` shows no Stop.
- **Exit 3 = partial success**: run.py goes on past a component that fails and exits 3; the CLI and the
  web jobs (`_execute_subprocess(partial_ok)`) store, record and keep what the others made.
- **Web re-export** re-renders every component the version has documents for (`_reexport_scope`), one
  document each (`--component-per-docx` for every scope — a component scope used to come back as one
  bundled document). A web generate job does not hold the writer lock: the `analyzer.py generate` it
  starts does. Since 2026-10-05: also a version made from the command line (it has no generation
  job; commit/branch/tag come from the version; 409 `NO_DOCUMENTS` when nothing is recorded), and
  optionally only `{"components": [...]}` (each with documents; the Components panel sends the stale
  ones). `GET /projects/{pid}/runs` lists the runs at work or cut short from either front door (the
  Overview's card); the versions list carries `run: {made_by, scope, doc_type, model_only}`.
  `analyzer.py clean-runs` removes the code copies of runs that finished (exit 0) days ago.
- **`--detach`** (CLI): `core/frozen_run.py` — a frozen copy of the code under `runs/<version>/<time>/`,
  the same data via `ANALYZER_DATA_ROOT` / `ANALYZER_WORKSPACES_DIR`, output in `run.log`, `run.json`
  (pid, argv, `job_id` from `ANALYZER_JOB_ID`), and `exit.json` written by `analyzer.py` as it exits
  (`_main_recording_exit` → `frozen_run.record_exit`; it pops `ANALYZER_EXIT_FILE`, so the phases do not).
- **Web runs in the background** (2026-10-02c, C4). With a database behind the API (`settings.job_detach`,
  on by default; the in-memory backend keeps the child process), a web Generate and a Components →
  Generate run `analyzer.py generate|export … --detach` through a launcher that exits once the run has
  started (`pipeline_runner._launch_detached`; its output to a temp file, never a pipe), so the run is not
  in the API's process tree and `start_app`'s restart does not reach it. The job thread only FOLLOWS it
  (`_follow_detached`): `run.log` for the live log and the phase (`_LineTracker`, shared with
  `_execute_subprocess`), the process (`frozen_run.process_alive`, by command line, so a reused pid is not
  the run) and the version's lock for life, `exit.json` for the end. Exit 0/3 → `_complete` (export:
  `_complete_render`); no exit code, no process and no lock → it died.
- **A restarted API follows its runs again**: `fail_interrupted_jobs` asks `_reattach_detached` first —
  the run folder whose `run.json` names the job (`frozen_run.find_job_run`) — and replays the log to catch
  the phase up (`_LineTracker.replay`, one write); only a job with no background run is failed as before.
  The check is tried again every 30 s until the database answers (`main._sweep_until_done`; one missed
  try under load left a job "running" with nothing following it), and touches only jobs started before
  this process (`PROCESS_STARTED`).
- **A stop keeps the version** when there is work in it (`_version_has_work`: a stored parse, or
  `pipeline_status` past `parsing`): `_fail_keeping_work` fails the job with "Stopped: …" and the resume
  command instead of deleting the draft. A failure before that frees the draft as always. Cancel stops the
  run (`frozen_run.stop`, its whole tree) and deletes the draft.
- **Resume**: on the server `analyzer.py resume --detach`; a successful CLI resume of a web version finishes
  that version's failed web job as the API would (`analyzer._finish_web_job` → `_complete`), so the version
  leaves draft. Over HTTP `POST …/versions/{vid}/resume` → `start_resume`: the version's unfinished
  generation job reopened (its end runs `_complete`), else a job `mode: "export"`; 409 `VERSION_BUSY` /
  `RUN_ACTIVE` / `NOTHING_TO_RESUME` / `NO_BACKGROUND_RUNS`. `GET …/components` answers `resume_action`
  (`version_components.resume_action` = `staged.resume_plan`'s action, "busy" while a job or a process
  of this machine is at work). **No web button yet** — the user deferred it; the panel prints the command.
- **Hardened 2026-10-04** (a review): unknown work = keep (`_version_has_work`); DB errors at a run's end
  are waited out (`_when_db_answers`, 30 s, up to 6 h); `main._watch_jobs` re-checks every 5 min for
  active jobs nothing follows; cancel refuses ended jobs (`JOB_FINISHED`), stops an unfollowed run first
  (`stop_background_run`), never releases for exports; a generation job whose dead run left a complete
  version is done; the web generate runs on the version's own config (`_freeze_version_config`);
  run.json `create_time` identifies the process; an export waits for the version's own run
  (`RUN_ACTIVE`); `start_app.kill_tree` skips `runs/.../code/` processes. Round 2: only connection
  errors are waited out (`_db_unavailable`); the frozen config keeps its typed macros, and `export` /
  `resume` overlay this machine's current local settings (`analyzer._with_current_secrets`, the run's
  LLM switches kept); the periodic pass only re-attaches, and only while `runner_still_held`.
  `DELETE /versions/{id}` throws a stopped run's kept version away (409 `VERSION_BUSY` / `RUN_ACTIVE` /
  `VERSION_IS_BASELINE`; jobs detached, cached comparisons dropped).
- **Limits**: each web run freezes ~10 MB of code (about a minute on Windows with the virus scanner; never
  deleted automatically — removing a copy must not follow its `node_modules` junction); a web re-export runs in the
  background too since 2026-10-04 (`_reexport_detached`); the launcher's window between spawning the run and writing `run.json`
  (milliseconds) is not covered; an API under systemd with the default `KillMode=control-group`, or in a
  container that restarts, kills its background runs with it (`KillMode=process`).

### Review and approval (2026-10-01d)

A document has **one reviewer** and moves In review → (its reviewer submits, with a comment) Ready for
approval → (an active admin) Approved, or back as Changes requested; an admin reopens an approved one,
with a reason. A **version is approved when every one of its documents is** — derived, never set. Each
step is a `ReviewEvent` (the review evidence) and notifies who it concerns. Contract:
[REVIEW_APPROVE_API_SPEC](../docs/spec/REVIEW_APPROVE_API_SPEC.md); why: [REVIEW_APPROVE_DESIGN](../docs/design/REVIEW_APPROVE_DESIGN.md).

- **Rules** — `api/services/review_workflow.py`, one function per step (`assign`, `claim`, `submit`,
  `approve`, `request_changes`, `reopen`), plus `document_views` (the contract's Document, three repository
  reads for a whole list), `roll_up` (writes the version's derived status, and the project's `complete` /
  `in_review` when it is the latest version), `start_review` (a run's new documents) and
  `refuse_if_approved` (corrections). Routes (`api/routes/documents.py`) only check the role and that the
  document is the path's project's.
- **Approve** refuses while R9 says this document's Word file lacks corrections — `export_guard.staleness(…,
  component=doc.group)` — and keeps a copy of the file (`versions/<ver>/approved/<doc id>/<name>`) and its
  SHA-256; downloads of an approved document serve the copy, so a re-export cannot change what was approved.
  It also stores a fingerprint of the rendered content (`compare_render.render_fingerprint` over
  `document_payload.build_document_render`, the page's own build).
- **A run** (`pipeline_runner._complete` → `start_review`): a new document whose baseline twin (same
  process + component; the run's baseline, else the previous version) was approved and fingerprints the
  same keeps the approval (`carried_from`, event `carried`); the rest are In review with the baseline's
  reviewer kept if still an active member. Checked on real data: unchanged components fingerprint
  identically across an incremental and a full run of the same code.
- **Every version gets its documents recorded** — `api/services/document_registry.py`
  (`register_documents`, idempotent; `new_documents` is the rows alone, what `_make_documents` now is).
  Called by the job's `_complete`, by `analyzer.py generate` at its end (also inside a web job, so a run
  whose server restarted still has its documents), by re-export, by `analyzer.py register` and by A17
  (`POST …/versions/{vid}/documents/register`). Before this a CLI run recorded none. Which component a
  dir is: project layers → version `resolved_config` → `versions/<ver>/config.json` → the project's
  `config.json`; an undeclared dir is skipped unless nothing declares any. Checked on a copy of
  `analyzer_ui`: re-recording a 50-document version carried 9 approvals (8 of them made before
  fingerprints existed) and left the one changed component In review.
- **Carry-over** compares the new document's fingerprint with the stored one, and when they differ (or
  none was stored) fingerprints the baseline twin again with the current code — a change to the render
  code then cannot stop unchanged documents from carrying.
- **Team** — Add member finds people by name or email (`GET /users/search`, `pages/TeamPage/components/AddMemberDialog.tsx`); adding a person (A20) makes an active member, creating the account (temporary password, shown once) when there is none; `POST /auth/change-password` (A21); `analyzer.py user` and `tools/create_users.py` create accounts. Members show `open_reviews` (latest version); a role is `admin|developer|reviewer` (422
  otherwise; `reviewer` acts as a developer); removing a member takes them off their unapproved
  documents (`release_reviews`). `GET /reviews/mine` lists the caller's documents across projects. A
  commit's `doc_status` is derived from its version. `PATCH …/documents/{id}` stores `due_date`.
- **Locked** — a correction (R3, R4, R6, R8) answers 409 `DOCUMENT_APPROVED` while the text's component has
  an approved SWE.3 or SWE.4 (a struct description, keyed by no component: any approved document).
- **Web** — one status vocabulary: `lib/reviewStatus.ts` + `ui/StatusBadge` (no local status maps).
  Data: `services/api/approval.ts`, `services/mappers/approval.ts`, `hooks/useApproval.ts` (A1–A11, A15;
  409 codes → messages). `pages/DocumentsPage/` and `pages/ProjectDetailPage/` are folders now; the
  reader's Review tab is `ReviewTab.tsx` + `ReviewDialogs.tsx` (+ pure `review.ts`), banners in
  `ReviewBars.tsx`, the shared `components/review/AssignReviewerDialog.tsx`; `?tab=review` opens the tab.
  Compare is read-only. `ReviewTracker` / `AssignReviewersPanel` are gone. vitest 185, build clean, lint
  at its baseline (27). Checked live: web on :5180 → API on :8010 over a copy of `analyzer_ui` (assign,
  submit, approve, carried approval), and `npm run test:api` 0 mismatches against it. **Never run a bare
  `npx vitest run`**: it includes the live suite, which writes to whatever API `localhost:8000` is.
- **Storage** — `documents` review columns, `document_review_events`, `notifications.document_id`, one
  reviewer per document (unique index); migration 0015, and `analyzer.py setup` runs the same data repair
  (`api/db/postgres/review_repair.py`: statuses, newest reviewer kept, "approved before the record" events).
- **Access fixes** — every review route checks the document belongs to the path's project; a pending
  admin no longer passes `require_project_admin`; a notification is marked read only by its owner;
  approve-all takes document ids (by version it approved every version's documents).
- **Tests** — `tests/api/test_review_approve.py` (both backends).

### Word file updates — "out of date" means the Word file (2026-10-05u)

Contract and screens: [WORD_FILE_UPDATES.md](../docs/design/WORD_FILE_UPDATES.md) (§4); mockup
`docs/ui-mockups/documents.html`. The web app never says "re-export": *Update*, *Update all*, *Rebuild
all Word files…* (admin).

- **The rule** — `engine/review/word_files.py`: a document's Word file is out of date when a correction in
  its component is newer than `documents.word_file_at`, a layer added since changed it
  (`version_components.stale_layers`), or one of its component's pictures is still being drawn
  (`render_queue.by_component`). One answer for R9 (`outOfDate[]`, `approvedKept[]`, `writer`), A15,
  Approve / bulk approve (`STALE_EXPORT` with `why`) and the update's scope. `word_file_at` is set when a
  run's output is stored, for the .docx files it wrote (`record_word_files`); a document recorded before
  0018 uses its file's time.
- **Partial capture** — re-export, export and resume by component store only the components they rebuilt
  (`model_store.persist_output_files(groups=)`, `incremental/store.py`); stamps are recomputed from the
  stored records. A save in another component survives a run. Generation, resume's "close" and re-exports
  not scoped by component still store the whole version.
- **Update** — `POST …/versions/{vid}/reexport {scope: "out_of_date" | "all", components?, document_id?}`
  (`api/services/word_files.start_update`): a developer reaches the documents they review plus the one
  named; `all` (and no `scope`) is admin-only. A running update is found before the writer lock: covered →
  200 `joined`; else 409 `REEXPORT_RUNNING` (job, scope, components); `VERSION_BUSY` carries `writer`.
  While a component is being written, its corrections answer 409 `WORD_FILE_UPDATING` (R3/R4/R6/R8; web
  jobs and a CLI run holding the version). Submit (A5) starts its component's update and answers
  `word_file {state, job_id, blocked_by}`; a refusal never fails the submit.
- **Jobs and notifications** — `analysis_jobs.started_by`, `.reason`; `word_files_updated` /
  `word_files_update_failed` to the starter (and the admins when a Submit-started update fails).
- **Files** — `.docx` written whole (`docx_common.save_docx`: temp + `os.replace`); an approved document
  whose kept copy is missing answers 409 `APPROVED_FILE_MISSING` unless the working file's SHA-256 matches.
- **Migration 0018** (`documents.word_file_at`, `analysis_jobs.started_by` / `reason`,
  `version_components.stale_layers`): run `analyzer.py setup` after pulling.
- **Web** (2026-10-06) — rules and the mockup's words in `lib/wordFiles.ts`; data `services/api/wordFiles.ts`,
  `services/mappers/wordFiles.ts`, `hooks/useWordFiles.ts` (the update mutation; one end-of-update watcher
  per page: toast, bell refresh, a download that was waiting), `store/wordFiles.ts`. Screens:
  `components/wordfiles/UpdateWordFilesDialog.tsx` (the confirm, every update a button starts on its own;
  in-dialog buttons and Submit start without a second one), `WordFileMenu.tsx` (*Corrected file* /
  *Current file*), `WordFilesRow.tsx` (the Generation banner's second row, on the Overview and the
  Documents page — it replaced task 3's `StaleRow`), `DownloadAllDialog.tsx` (*As they are* / *Corrected
  files*); the reader's `WordFileBanner.tsx` (every state; *Update failed* only to its starter; an admin's
  ⋯ *Rebuild all Word files…*), the edit hold for the component being updated, the Review tab's *Word
  file* row, Approve's *Update file*, Submit's toast from `word_file`, the bell's two kinds, bulk approve's
  *Update them*. No user-visible "re-export" is left.

### Repositories — where a project's code comes from (2026-10-05k, 2026-10-05r)

A project's `repo_url` is a remote URL or a local folder on the server; the wizard's step 1 is
**Remote | Local**. Design: [BITBUCKET_SUPPORT.md](../docs/design/BITBUCKET_SUPPORT.md).

- **Local** — `api/services/local_repos.py` (`is_local`, `clean`, `problem`, `list_folders`;
  `repositories.localRoots` in config.local.json); `GET /repositories/local-folders` feeds the wizard's
  Browse panel. No token is ever sent; `repo_provider` "local".
- **How a token reaches git** — one rule, `engine/incremental/clone.git_auth(url, token)`, used by every
  remote git call (wizard, config preview, a job's checkout, the CLI's `resolve_project_repo`): SSH and
  local → none; `bitbucket.org` → `Authorization: Basic x-token-auth:…`; an http(s) `/scm/` path (Data
  Center) → `Bearer`; any other host → the token as the URL's user name, as always. A header goes through
  `GIT_CONFIG_*` scoped to the repository's host, never argv / URL / `.git/config`; for Bitbucket URLs git
  also asks no credential helper and no askpass, token or not. Errors pass through `clone.scrub`.
- **Page address → clone URL** — `repo_git.clone_url` (Data Center `projects/…/repos/…` and
  `users/…/repos/…`, Cloud `bitbucket.org/<ws>/<repo>/…`), applied in test-connection (its answer's
  `repo_url` is the URL used; the wizard puts it in the box), browse, the config preview and create.
- **Messages** — `repo_git._friendly(msg, token_sent=)`: "Authentication failed — this repository needs an
  access token." / "… — check the access token."; the wizard moves the cursor to the token field.
- **`projects.repo_provider`** is set by the server from the URL on create ("bitbucket", "local", else as
  before) — display only; nothing reads it to decide how to sign in. The token stays in
  `build_config.repo_access_token`, in plain text (study 03 wants it encrypted).
- **The wizard's clone cache** (`workspaces/_wizard/<hash>`) is keyed by URL, branch, depth, blobless
  and the token: a clone made with a token is never served to a request without it.
- **Open:** the office check T0 (BITBUCKET_SUPPORT.md); T7 replace a project's token, T8 a CA bundle, T9
  a CLI token.

---

_End of file._

### Live logs for superusers (2026-10-06)

Contract [LIVE_LOGS_SPEC](../docs/spec/LIVE_LOGS_SPEC.md) (`REQ-LL-01…15`), how
[LIVE_LOGS_DESIGN](../docs/design/LIVE_LOGS_DESIGN.md). Backend only; no page yet.

- **Writing.** `core/logging_setup.py` `LiveLogHandler`, installed by `configure_logging` in every
  process: one JSON line per record, at DEBUG, to `<data root>/logs/live/<YYYY-MM-DD>/<source>-<pid>.jsonl`
  -- one file per process (concurrent appends to one file are unsafe on Windows). `source` is
  `engine`, or `server` in the API (`set_live_source` at the top of `api/main.py`, before the routes
  import engine modules -- the API has always configured engine logging by importing them). Fields:
  `ts` (ms, local offset), `level`, `logger`, `message` (+ traceback), `pid`, `project`/`version`
  (`core.run_context`), `step` by script name (`parser.py` Parse … `swe4_exporter.py` Export SWE.4,
  `flowchart_engine.py` Views), `components` (`--allowed-components`), and the request's ids
  (`REQUEST_CONTEXT` contextvar). Each step script calls `start_phase_logging()` (logging
  configured; its prints copied to the live log; only when the process IS that step), and
  `--version-id`/`--project-id` come from argv where `core.run_context` has none (swe4_exporter).
- **Request lines.** `api/middleware/request_log.py` (plain ASGI): one line per POST/PUT/PATCH/DELETE
  and per status >= 400 or exception, never the query string; `api.request` does not propagate (live
  log only). Sets `REQUEST_CONTEXT` from the path (`projects/`, `versions/`, `jobs/job…`).
- **Reading.** `api/services/live_logs.py` `LiveLogReader`, one thread started at API startup: polls
  today's and yesterday's folders every second (offset per file, partial last line held), masks
  (`Masker`: URL passwords, Authorization/Bearer, `api_key|token|password=`, the configured DB password,
  LLM key and custom-header values), gives engine records `job`/`run` from `db.jobs.list_for_version`
  by time (one writer per version makes it exact), sorts each batch by `ts`, keeps 20 000 in a deque
  with `seq`. Startup backfill from file ends; daily retention by `logs.keepDays`.
- **Routes** (`api/routes/admin_logs.py`, `require_superuser`): `GET /admin/logs` (tail; `lines`
  default `logs.liveLines` 500, cut to `logs.maxLines` 2000), `POST /admin/logs/ticket` (60 s,
  single use), `GET /admin/logs/stream?ticket=&after=` (SSE `log` / `gap`, ping 15 s). Config
  `logs` in `config.defaults.json`, read per request (`core.config.logs_config`).
- **Gotchas.** `seq` restarts with the API (a stale `after` gets `gap`). The test suite's process sets
  `LIVE_LOG_ENABLED = False` (`tests/conftest.py`): its default handler writes nothing and no reader
  starts; a handler given a folder still writes. Only `logging` records reach the stream, not `print()`.
