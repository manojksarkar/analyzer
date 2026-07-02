# Frontend ↔ API integration notes

The app calls a FastAPI backend over `VITE_API_URL`; wire-format differences are handled in the
boundary mappers ([src/services/mappers/](src/services/mappers/)). For local dev that backend is the
**mock** in [`../../mock-api`](../../mock-api); the **real** API is built separately by another team
under repo-root [`../../api`](../../api). The web-app is backend-agnostic — it picks its backend solely
via `VITE_API_URL`, so switching mock → real is a config change, not a code change (see
**Real-API swap readiness** below). Server-side detail for the wizard endpoints (`repositories/*`,
`users/search`, `access_token` on `POST /projects`):
[mock-api/api/PROJECT_CONTEXT.md](../../mock-api/api/PROJECT_CONTEXT.md) §12.

**Build-config file uploads (macros / data dictionary):** the wizard uploads each file (multipart) to
`POST /repositories/uploads` and sends `{file_name, file_id}` in `build_config` — this is unchanged and
**needs no frontend work**. The *backend* now persists the bytes: the upload stages them on disk and
`POST /projects` finalizes them into a per-project workspace, rewriting `build_config` to carry the
durable **path** (the data dictionary also gets a `data_dict_id` / `current_data_dict_id`) so a later
run/update can hand the path to the analyzer. The overview mapper (`mapBuildConfig`) only reads
`mode`/`file_name`/`defines`, so it tolerates the new shape unchanged. This lives in the mock backend
(`mock-api/`); the real `api/` team mirrors the same upload + finalize contract. Detail:
[mock-api/api/PROJECT_CONTEXT.md](../../mock-api/api/PROJECT_CONTEXT.md) §12 "Build-config file persistence".

## Setup

- Base URL: `VITE_API_URL` ([.env.example](.env.example)) — defaults to `http://localhost:8000/api/v1`.
- Run the mock backend: `cd ../mock-api && uvicorn api.main:app --reload --port 8000`.
- Demo login: `alice@aspice.dev` / `secret` (admin). Seed users in [mock-api/api/README.md](../../mock-api/api/README.md).

## Real-API swap readiness

**Goal:** stop the mock, start the real API — no web-app code change. The app is already wired for
this; the items below are the contract the real API must satisfy and the two things config alone
can't fix.

**The single switch.** The backend is chosen only by `VITE_API_URL` ([src/lib/http.ts:18](src/lib/http.ts#L18)).
Run the real API on `http://localhost:8000/api/v1`, **or** point `VITE_API_URL` at wherever it's hosted.
There are no other backend references in the source (`localhost`/`:8000` appear only as the env fallback).

**Verified (2026-06-25):** `npm run build` clean; every read endpoint the app calls returns 200 against
the mock (auth, projects, commits, versions, documents list/detail/render, members, notifications). The
7 lint errors are pre-existing (`NewProjectPage` set-state-in-effect / unused-expr), unrelated to the swap.

**Swap-verification tool — `npm run test:api`.** This is now automated. The API-test suite signs
in, walks every endpoint the app calls, and validates each raw response against the zod schema the UI
expects (the mappers' `Api*` types are `z.infer<>` of those schemas — single source of truth). Green vs
the mock; point it at the real API (`API_TEST_URL=<url> API_TEST_EMAIL/PASSWORD npm run test:api`) and it
prints exactly which endpoint/field drifted (mismatch = fail; new field = warning). **It is read-only
against a real API** — write requests run only against a local mock, so it can't corrupt real data. It
also asserts the two tokenless requirements below — the SSE route and the asset route must not be
`Bearer`-gated, and a real diagram `image_url` must load as an `image/*`. Full guide: [TESTING.md](TESTING.md).

**⚠ Two hard requirements (browsers can't attach a Bearer header here):**
1. **Job progress SSE** — `GET /projects/{id}/jobs/{jobId}/events` is opened by `EventSource`
   ([useJobs.ts:16](src/hooks/useJobs.ts#L16) → [jobs.ts:43](src/services/api/jobs.ts#L43)), which sends
   **no Authorization header**. The real API must keep this route reachable without a Bearer header
   (unauthenticated, like the mock, or accept a `?token=` query param — tell us the param and we'll append it).
2. **Diagram assets** — the render payload returns `image_url` as a relative **path/key**; the UI builds
   the URL in `resolveAssetUrl` ([document.ts](src/services/mappers/document.ts)) and loads it with a plain
   `<img loading="lazy">`, same no-header constraint. The URL shape is config-selectable via
   **`VITE_ASSET_ENDPOINT`**: unset → `${base}/<path>` (mock's REST route); set (e.g. `/assets`) →
   `${base}/assets?path=<path>` (dedicated endpoint, path as a query param — the real-API model). Absolute
   / CDN URLs pass through. The serving endpoint must be reachable **without** a Bearer (the `path` query
   carries the asset path, never a token); if it must be authenticated, the inspector switches to a blob
   fetch (auth GET → objectURL). `npm run test:api` verifies a real `image_url` actually loads as an
   `image/*` under whichever mode is configured.

   *(Authenticated binary endpoints — DOCX `…/download`, `…/export-all` — are fine: they go through a
   `fetch` + Bearer + blob in [http.ts](src/lib/http.ts#L153), not an `<img>`/`EventSource`.)*

**Endpoints the app depends on** (the real API must implement these paths/shapes — the mock is the
executable reference): `auth/{signin,refresh,signout,me}`; `projects` (list/get/create/update/delete,
`access-requests`); `repositories/{test-connection,browse,uploads}` + `users/search` (wizard);
`projects/{id}/{commits,versions,documents,members,members/pending,members/invite,jobs,compare,functions,notifications}`;
document actions (`approve`, `approve-all`, `submit-review`, `request-changes`, `assignments[/self]`,
`sections/{key}`, `download`, `export-all`, `render`); `notifications/{id}/read` + `read-all`.
Snake_case in/out; per-project role via `my_role`. Full shapes: the mock routes + the mappers in
[src/services/mappers/](src/services/mappers/).

**Features still showing placeholder data (no endpoint in the contract — the real API would need to add
one before the web-app can wire it):** Overview **Last Actions** feed and **Function Visibility** card
are hard-coded ([ProjectDetailPage.tsx:742,765](src/pages/ProjectDetailPage.tsx#L742)); several
secondary actions are info-toasts/no-ops (Archive, Request Access, Forgot password, SSO, Profile, Help).
These won't light up just by swapping backends — they need both an endpoint and FE wiring. See the
per-page TODO column below.

## Wire-format mismatches (handled in mappers)

| API gives | UI wants | Handling |
|---|---|---|
| `team_count` (int), no member array | avatar stack | N placeholder avatars from the count |
| `compliance_standard`/`status`/`doc_counts` | `standard`/`pageState`/`progress`/`icon` | derived in `mapProject` (`not_run`→`never`) |
| auth user has no role | per-screen admin check | `isAdmin` from `project.userRole` (`my_role`) |
| sign-in matches **email only** | form takes any identifier | sent as `email` (usernames won't auth) |
| version `status: draft`, doc `status: never` | stricter FE enums | added to types; → `in_review` / fallback badge |
| doc `version_id` (`ver3`) | tag (`v1.2.0`) | resolved from the versions query; falls back to the id |
| doc `assignees[]` | single `assignee` + colour | first assignee; colour hashed from `user_id` |
| `…/members` active only | table shows pending | merge `…/members/pending` (admin) |
| ISO dates / full sha | "Jun 15" / "2h ago" / short sha | [src/lib/format.ts](src/lib/format.ts) |

## Page status (wired vs remaining)

| Page | Route | Wired | Remaining / TODO |
|---|---|---|---|
| Sign in | `/signin` | email + password, remember-me | • SSO button disabled (no endpoint)<br>• **Forgot password** → info-toast (no reset flow)<br>• footer **Request Access** → info-toast (no self-serve signup) |
| Projects | `/projects` | list, delete, role-aware menu, notifications | • header + empty-card **Request Access** → info-toast (no project-discovery/search)<br>• row menu **Archive** → info-toast (no endpoint)<br>• *(shell)* user-menu **Profile** = no-op<br>• *(shell)* **Help** button = no-op<br>• *(shell)* sidebar **Settings** routes to overview only |
| New project | `/projects/new` | full 5-step wizard → `POST /projects`; repo test/browse/upload, user search (`NewProjectPage`) | — |
| Overview | `/projects/:id/overview` | KPIs, docs, Run-Analysis modal, job panel + SSE, self-assign, config panel | • **Last Actions** feed = hard-coded array (no activity/audit endpoint)<br>• **Function Visibility** card = hard-coded "3 of 26" + dead **Manage** button (no endpoint/editor)<br>• dev **My Documents** Open/Download buttons not wired (stopPropagation only)<br>• **stale** banner "3 new commits" count hard-coded |
| Documents | `/projects/:id/documents` | list (version-scoped to the Subbar picker via `useProjectViewState`), left **document-tree rail** (assignee filter + process-grouped docs), process/status/search filters, **not-run / stale / in-review** states, role-aware dev **My Assignments + Show all**, bulk Approve/Download, per-row dev self-assign; row/**View**/rail-leaf → **inspector**, compare button → Compare | • bulk **Assign** + admin per-row **Assign reviewer** → info-toast (no reviewer/batch-assign picker)<br>• rail tree groups by **process only** (`Document` payload has no layer/component hierarchy)<br>• **in-review progress** = approved-vs-total docs (no per-section review endpoint); stale banner HEAD/“N commits ahead” from `version.newCommitsSince` + latest commit<br>• dev **My Assignments** matches "me" by **display name** (`assignee` has no user id on the list payload) |
| Document (inspector) | `/projects/:id/documents/:docId` | left **doc-tree rail** (active doc highlighted) + **`GET …/documents/{id}/render`** rich payload → **cover** (project/version/layer/group/standard chips), **meta banner** (source + units/functions/globals/components/layers), **typed/nested sections** (richtext, real **interface tables**, **diagram** images per component/unit, `children`), **TOC** outline; **diagrams render real PNGs** via the unauth asset route, with a **"View source"** for the mermaid `.mmd`; when `in_review` → **review tracker** (flat `…/documents/{id}` detail) + **assign-reviewers** slide-in; Download `software_detailed_design_<group>` + Compare | • render reads a **committed snapshot** of real output (`api/fixtures/documents/<group>/`), NOT the live (gitignored) `output/`; groups with a fixture → `source:"pipeline"`, others → synthesized `source:"model"` fallback<br>• fixture = `Full`/`Access`/`Diag` only; **behaviour diagrams omitted**; flowcharts capped (8/component)<br>• flowcharts have **no mermaid** (PNG only); other diagram types carry `.mmd`<br>• body (rich `/render`) + review tracker (flat detail) are **two endpoints**; per-section review state keys off the flat sections<br>• **Mark Complete** = `POST …/approve`; per-section accept/decline/edit lives on Compare |
| Compare | `/projects/:id/compare` | **wired + highlighted** — left **Diff/All doc tree** (Diff = `useCompareDocuments` changed docs; All = `useDocuments` + changed flags), **split view** (`useCompareDocumentDetail`: left=baseline, right=current) rendered as a **single shared scroller + 2-column CSS grid** so both sides scroll together AND stay aligned (each section = one grid row → equal height; the shorter side gets filler whitespace), with **sticky pane headers** and a **"Changes only"** toggle. The detail endpoint now returns a **rich, highlight-annotated diff** (`mode: 'rich'`): the full DOCX-mirroring render (descriptions, **interface tables**, **flowchart/behaviour tables**, **mermaid diagrams**) is built for **both** version snapshots and diffed into typed **blocks** — **word-level** text/keyvalue highlights (`add`/`del`), **per-cell** table marks (`add`/`del`/`change`, rows aligned by first column), and **changed-diagram badges** (mermaid source differs); each changed section shows a **diff badge + `source` artifact chip** (provenance). Diagram PNGs load per-version from the snapshot asset route `…/compare/assets/{versionId}/{group}/{path}`. Falls back to the legacy flat interface-table diff (`mode: 'flat'`) when a snapshot render is unavailable. **Changed-section accents** + per-section **Accept/Decline** (in review), and a **review footer** (resolved/total dots + **Submit Review**/**Approve Document**, shown only when `in_review`). Current ref = the shared Subbar picker (default latest version); the **baseline is fixed** to that version's predecessor and shown as a **read-only badge** in the Reference-pane header. | • doc-level change detection covers **all** content (descriptions/flowcharts/diagrams), not just interface tables (`render_fingerprint`, URL-agnostic)<br>• rich-section review state is **optimistic/local** (rich render ids don't round-trip through the stored-section table); the inline **Edit** control is flat-mode only<br>• subbar **Export/Exit** CTAs from the mockup omitted (no per-page subbar-CTA mechanism)<br>• footer **Approve** shares the doc's review state with the inspector; not role-gated (both buttons shown) |
| Versions | `/projects/:id/versions` | list, tag an untagged commit | — |
| Team | `/projects/:id/team` | invite / role / remove / cancel, pending merge | — |

## Backend gotchas

- **Jobs are simulated** ([api/services/job_runner.py](../../api/services/job_runner.py)): `POST /jobs` runs a thread through 4 phases (~10–15 s) streamed over SSE, then synthesises a Version + Documents and flips the project to `in_review`. No C++ is parsed.
- The **SSE events route is unauthenticated** (`EventSource` connects without a token).
- **In-memory data resets on server restart.**
- **Two document-detail endpoints.**
  - `GET …/documents/{id}` → flat detail `{ …meta, sections:[{key,title,order,content,review_state,…}], review_progress }` — drives the inspector's **review tracker** + the list's status. Seeded, no real data.
  - `GET …/documents/{id}/render` → rich `{ cover, toc, sections:[{id,number,title,level,type,content,table,image_url,mermaid,children}], meta:{…,source,layers,components,units_total,functions_total,globals_total} }` — drives the inspector **body**. Built from a **committed snapshot of real analyzer output** at `api/fixtures/documents/<group>/` (a curated copy of `output/<group>/`: real `interface_tables.json` → interface tables; diagram PNGs/MMDs). `cover`/counts come from the fixture + project. **Groups with a fixture (`Full`/`Access`/`Diag`) → `source:"pipeline"`; all others → a synthesized fallback (`source:"model"`).** It deliberately does **not** read the live `output/` (gitignored, machine-specific, not produced by the mock API). Diagrams stream from `…/documents/{id}/assets/{path}` (**unauthenticated**, like SSE; path-restricted to the group fixture). To grow the data: copy more groups into the fixture (or, later, wire to a real pipeline run).
