# Web-App Plan — Frontend Forward Work

> Forward work for `web-app/`. What's built, what's left, and the real-API cutover. Granular per-page gaps live
> in [INTEGRATION_NOTES.md](INTEGRATION_NOTES.md) (the "Page status" table) — this plan is the summary + themes.
> Coding rules: the `ui-dev` skill. Testing: [TESTING.md](TESTING.md). Product/design: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

## Status

The app is wired to the real FastAPI backend (not mock data) via typed mappers/hooks. All core screens are
functional 1:1 ports of the design mockups: Sign-in, Projects, New-project wizard, Overview (+ run/job SSE),
Documents (+ inspector, review tracker), Compare (rich diff), Versions, Team. Test framework in place
(vitest unit + `npm run test:api` live-contract suite).

**Verified end to end on the real pipeline (2026-09-29, branch `ui_v2`):** wizard → project; Run Analysis →
real run with live progress → 13 documents; inspector (all 71 diagram PNGs load), DOCX download, Download All
ZIP; a layer/group-scoped run; Compare across two versions; claim, approve, invite, sign-out, silent token
refresh — on PostgreSQL, admin and developer roles. Also that night: a command-line config file imports into
the wizard, and a project downloads as one; download → import → download round-trips.

## Real-API cutover

- **Single switch:** the backend is chosen only by `VITE_API_URL` (`src/lib/http.ts`). Point it at the real API
  — no code change. `npm run test:api` validates the real responses against the UI's zod schemas (read-only
  against a real backend); it prints exactly which endpoint/field drifted.
- **Two hard requirements** the browser can't satisfy with a Bearer header (must hold on the real API):
  1. **Job-progress SSE** (`GET …/jobs/{id}/events`, opened by `EventSource`) reachable without a Bearer.
  2. **Diagram assets** — `image_url` is a relative path the UI loads via plain `<img>`; the serving endpoint
     must be reachable without a Bearer (shape selectable via `VITE_ASSET_ENDPOINT`).

## Remaining — needs the backend first

- **Overview** — an activity log (Last Actions shows only runs and versions); a function-visibility editor,
  and hiding must reach the DOCX: the visibility API writes `job_functions`, the render reads
  `entity_versions.is_visible`, the exporter reads `hidden` — three stores, none feeding the next; stale
  detection (the API never sets `stale`).
- **Run modal** — pause after Phase 1 (disabled: the runner ignores it).
- **Documents** — reviewer batch/assign picker; per-section review endpoint.
- **Accounts** — nothing creates a user (no sign-up, no admin create), nothing changes a password (the
  default `admin@aspice.dev` / `admin` stays as it is), and a pending invite never becomes active (no
  accept flow). Projects onboarded with the CLI have no members, so they never show in the web app
  (`review_update_v2` adds `analyzer.py grant`).
- **Projects / shell** — project discovery/search ("Request Access"); Archive; Profile, Help; a project
  Settings page (build config and data dictionary cannot change after creation); SSO; forgot password.
- **Runs** — a job left `running` by an API restart stays so until cancelled (no stale-job sweep; a sweep is
  unsafe with more than one API process).
- **Architecture after creation** — nothing can change it (no Settings page). Every path is checked when
  the project is created, and a run stops before the parse on a component that gets no file; so a folder
  moved in the repository later stops every run of the project, naming it, until the architecture can
  be edited.
- **Config import** — a project holds one definitions file and one data dictionary, so a config whose layers
  use different cores imports the first core's files only; `cores.<name>.compileCommands` has no field in
  the wizard (include folders go in per layer as Lib Paths).

## Remaining — decisions

- **Scoped runs** — a layer/group run makes a version holding only its scope's documents, so Compare shows
  every other component as removed. Carry the rest forward from the baseline, or compare only the scope?
- **Tags** — tagging a commit makes an empty draft version that no run fills; a run of that commit needs a
  different name. Should a run adopt the tag?
- **Excel data dictionaries** — the upload accepts `.xlsx`/`.xls` (a test keeps that deliberately), but the
  runner hands the engine a `.csv` and the engine reads CSV only. Convert on upload, or accept CSV only?
- **Run options** — expose `no_llm`, `mode` (full/auto) and a data dictionary in the modal? The API takes all
  three; with the LLM on, a first run of the sample project takes ~2 h on a local Ollama.

## Remaining — backend exists, no screen yet

- [ ] **Review & update** — correct the LLM's wording in a document (descriptions, unit and struct
      descriptions, behaviour names, Dynamic Behaviour bullets, flowchart labels), undo, history, and an
      export-readiness banner. API: [REVIEW_UPDATE_API_SPEC](../docs/spec/REVIEW_UPDATE_API_SPEC.md) — §3a
      lists the calls per screen. Rules: the `ui-dev` skill §6.
- [ ] **Flowcharts from DOT** — the in-app flowchart view still renders the stored string as Mermaid; the
      engine has written Graphviz DOT since 2026-07-27. Needed by the flowchart label editor too.

## Remaining — frontend-only work

- [ ] Clear lint debt (8 errors): set-state-in-effect in `NewProjectPage` and `ProjectDetailPage`,
      unused-expr in `NewProjectPage`, non-component exports in `ui/Dropdown` and `ui/Toast`.
- [ ] The Subbar chip does not follow an older version's document opened in the inspector.
- [ ] Grow test coverage as screens are added (unit fixtures + api-contract endpoints).
- [ ] **Deferred, not rejected:** migrate `src/` from layered → `features/<domain>/` once the global-vs-local
      boundary settles (the "big page → folder" rule pre-shapes this — see the `ui-dev` skill).
