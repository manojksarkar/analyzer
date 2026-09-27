# Web-App Plan — Frontend Forward Work

> Forward work for `web-app/`. What's built, what's left, and the real-API cutover. Granular per-page gaps live
> in [INTEGRATION_NOTES.md](INTEGRATION_NOTES.md) (the "Page status" table) — this plan is the summary + themes.
> Coding rules: the `ui-dev` skill. Testing: [TESTING.md](TESTING.md). Product/design: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

## Status

The app is wired to the real FastAPI backend (not mock data) via typed mappers/hooks. All core screens are
functional 1:1 ports of the design mockups: Sign-in, Projects, New-project wizard, Overview (+ run/job SSE),
Documents (+ inspector, review tracker), Compare (rich diff), Versions, Team. Test framework in place
(vitest unit + `npm run test:api` live-contract suite).

## Real-API cutover

- **Single switch:** the backend is chosen only by `VITE_API_URL` (`src/lib/http.ts`). Point it at the real API
  — no code change. `npm run test:api` validates the real responses against the UI's zod schemas (read-only
  against a real backend); it prints exactly which endpoint/field drifted.
- **Two hard requirements** the browser can't satisfy with a Bearer header (must hold on the real API):
  1. **Job-progress SSE** (`GET …/jobs/{id}/events`, opened by `EventSource`) reachable without a Bearer.
  2. **Diagram assets** — `image_url` is a relative path the UI loads via plain `<img>`; the serving endpoint
     must be reachable without a Bearer (shape selectable via `VITE_ASSET_ENDPOINT`).

## Remaining — features that need a backend endpoint before FE wiring

These render placeholder/no-op today because no endpoint exists yet (full per-page list in INTEGRATION_NOTES):

- **Overview** — Last Actions/activity feed; Function Visibility card + Manage editor; stale-commits count.
- **Documents** — reviewer batch/assign picker; layer/component doc-tree hierarchy (payload has process only);
  per-section review endpoint.
- **Projects / shell** — project discovery/search ("Request Access"); Archive; Profile, Help, Settings; SSO;
  Forgot-password reset flow.

## Remaining — backend exists, no screen yet

- [ ] **Review & update** — correct the LLM's wording in a document (descriptions, unit and struct
      descriptions, behaviour names, Dynamic Behaviour bullets, flowchart labels), undo, history, and an
      export-readiness banner. API: [REVIEW_UPDATE_API_SPEC](../docs/spec/REVIEW_UPDATE_API_SPEC.md) — §3a
      lists the calls per screen (on branch `review_update_v2` until it merges). Rules: the `ui-dev` skill §6.
- [ ] **Flowcharts from DOT** — the in-app flowchart view still renders the stored string as Mermaid; the
      engine has written Graphviz DOT since 2026-07-27. Needed by the flowchart label editor too.

## Remaining — frontend-only work

- [ ] Clear pre-existing lint debt (`NewProjectPage` set-state-in-effect / unused-expr).
- [ ] Grow test coverage as screens are added (unit fixtures + api-contract endpoints).
- [ ] **Deferred, not rejected:** migrate `src/` from layered → `features/<domain>/` once the global-vs-local
      boundary settles (the "big page → folder" rule pre-shapes this — see the `ui-dev` skill).
