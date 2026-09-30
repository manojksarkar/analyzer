# Frontend ↔ API integration notes

The app calls a FastAPI backend over `VITE_API_URL`; wire-format differences are handled in the
boundary mappers ([src/services/mappers/](src/services/mappers/)). That backend is the **real API** in
repo-root [`../api`](../api) (PostgreSQL, or SQLite for local runs), which runs the real pipeline. (The
mock backend this app was first built against is no longer in the repo; only fragments remain under
`tools/mock-api`.) The web-app picks its backend solely via `VITE_API_URL` (see **Real-API swap
readiness** below). The wizard endpoints (`repositories/*`, `users/search`, `access_token` on
`POST /projects`) live in [api/routes/repositories.py](../api/routes/repositories.py),
[api/routes/users.py](../api/routes/users.py) and [api/routes/projects.py](../api/routes/projects.py).

**Cores (per-core build inputs, since 2026-09-29):** step 2 edits `build_config.cores` - each core's macros
(an upload, or typed `defines`), data dictionary (.csv) and compile commands (upload kind
`compile_commands`) - and each layer sends `core: <name>` (see `api/services/project_cores.py`). A project
from before cores reads as one core, Core1, on every layer; the project view carries `cores` + `layer_cores`.

**Build-config file uploads (macros / data dictionary):** the wizard uploads each file (multipart) to
`POST /repositories/uploads` and sends `{file_name, file_id}` in `build_config` — no other frontend work.
In the real `api/` the upload is stored on disk (`workspaces/uploads/<id>/`), so it survives a restart;
each core's files reach the run as `cores.<name>` (its macros, dictionary and compile commands); a job's
own `data_dict_id` is only what the Run modal names (none today). Until 2026-09-29 neither step reached a
run: nothing passed the dictionary on, and the runner looked for its bytes in memory. The engine reads a
data dictionary as CSV only, although the upload also accepts `.xlsx`/`.xls` (see [PLAN.md](PLAN.md)).

**A config file in and out** ([api/services/project_config.py](../api/services/project_config.py)):
**Import config** (top of step 1, above the fields it fills) posts the file's text to
`POST /projects/config/preview` (creates nothing) and fills steps 1–3 from the returned draft; once the
repository is connected it posts again with `repo_url`/`branch`/`access_token`, and the server checks
every layer and component path against the repository. The report lists each item as filled, to check
or skipped. The token is never read from the file. A core's files (macros, data dictionary, compile
commands) are the user's inputs, never read from the repository: `expected_uploads` carries each path as
the config writes it, and step 2's **Choose folder** (`CoresStep.tsx` `FolderFill`, `helpers.ts`
`matchFolder`) fills every slot the picked folder holds, matching the path's end (the picked folder's own
name may differ); only the matched files are uploaded. **Download config** is
`GET /projects/{id}/config`: the engine's format plus a `project` block (name, repository, branch, typed
defines) that the engine ignores. Wiring: `projectsApi.previewConfig` via `useRepositoryWizard`,
`useDownloadProjectConfig`, mapper [projectConfig.ts](src/services/mappers/projectConfig.ts).

**Every path is checked before a project is created** (`NewProjectPage/helpers.ts` `pathProblems`):
layer folders, component files and folders, relative lib paths, against the selected branch's
tree as it is now (`GET /repositories/browse?refresh=true` — the cached clone is fetched first; a
fetch in the last 60 s counts as current). Step 3 marks each problem and refuses Continue; so does
Initialize. Changing the repository URL or token un-checks an imported config; a branch change
re-checks it; once the user edits the architecture a re-check keeps it and its report lines
(report items carry a `topic`). A run checks again, against the commit it analyses: the run's
warnings reach the web app as `versions.warnings`, and a run the engine stops before the parse
fails with the engine's reason as the job's first line.

## Setup

- Base URL: `VITE_API_URL` ([.env.example](.env.example)) — defaults to `http://localhost:8000/api/v1`.
- Real API, from the repo root: `python analyzer.py setup --demo` once (schema + demo users and
  projects), then `uvicorn api.main:app --port 8000`. It uses the `db` section of
  `engine/config/config.local.json`, or `DATABASE_URL` when set — point `DATABASE_URL` at a scratch
  database to exercise writes without touching real data.
- Demo login: `alice@aspice.dev` / `secret` (admin on the demo projects). A fresh database also gets
  `admin@aspice.dev` / `admin`.

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

**Endpoints the app depends on** (the real API must implement these paths/shapes — the `api/` routes are the
executable reference): `auth/{signin,refresh,signout,me}`; `projects` (list/get/create/update/delete,
`access-requests`); `repositories/{test-connection,browse,uploads}` + `users/search` (wizard);
`projects/{id}/{commits,versions,documents,members,members/pending,members/invite,jobs,compare,functions,notifications}`;
document actions (`approve`, `approve-all`, `submit-review`, `request-changes`, `assignments[/self]`,
`sections/{key}`, `download`, `export-all`, `render`); `notifications/{id}/read` + `read-all`.
Snake_case in/out; per-project role via `my_role`. Full shapes: the `api/` routes + the mappers in
[src/services/mappers/](src/services/mappers/).

**Features limited by a missing endpoint (the API would need to add one first):** Overview **Last
Actions** is built from the latest job and the versions — there is no activity log, so reviews and
assignments do not appear; **Function Visibility** shows the latest run's real counts, and **Manage** is
disabled (no visibility editor). Several secondary actions are info-toasts/no-ops (Archive, Request
Access, Forgot password, SSO, Profile, Help). See the per-page TODO column below and [PLAN.md](PLAN.md).

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
| Projects | `/projects` | list, delete, role-aware menu (**Download config** for every member), notifications | • header + empty-card **Request Access** → info-toast (no project-discovery/search)<br>• row menu **Archive** → info-toast (no endpoint)<br>• *(shell)* user-menu **Profile** = no-op<br>• *(shell)* **Help** button = no-op<br>• *(shell)* sidebar **Settings** routes to overview only |
| New project | `/projects/new` | full 5-step wizard → `POST /projects`; repo test/browse/upload, user search; **Import config** fills steps 1–3 from a config file, re-checked against the repository on Test Connection or a branch change; step 2 **Choose folder** fills the core files it names; every path is checked against the branch before the project is created (`NewProjectPage/`) | • a core's compile commands `rootPrefix` is not imported (worked out at run time) |
| Overview | `/projects/:id/overview` | KPIs, docs, Run-Analysis modal (commit, name, baseline; **Advanced options**: a component tree - every component ticked, sent as one-kind `scope` by `lib/runScope.ts` - and **Skip LLM** → `no_llm`), job panel + SSE with the phase % and time left from the engine's item counter, **failed-run banner** with the job's error, Subbar **RUN ANALYSIS** for admins whenever no run is active, self-assign, config panel with **Download config**, **run-warnings banner** (the viewed version's `warnings`), **Last Actions** from the latest job + versions, **Function Visibility** counts from `…/jobs/{id}/functions` | • no activity/audit endpoint: reviews and assignments never reach Last Actions<br>• **Manage** (visibility editor) disabled: no editor, and hiding would not reach the DOCX (see PLAN)<br>• Run modal cannot force a full run or pick a data dictionary (the API takes `mode`, `data_dict_id`); **pause after Phase 1** disabled — the runner ignores it<br>• **stale** banner never shows: the API never sets `stale` (its "3 new commits" is hard-coded) |
| Documents | `/projects/:id/documents` | list (version-scoped to the Subbar picker via `useProjectViewState`), left **document-tree rail** (assignee filter + process-grouped docs), process/status/search filters, **not-run / stale / in-review** states, role-aware dev **My Assignments + Show all**, bulk Approve/Download (a failed download says so), per-row dev self-assign, Subbar **DOWNLOAD ALL** (the viewed version's DOCX files as one ZIP); row/**View**/rail-leaf → **inspector**, compare button → Compare | • bulk **Assign** + admin per-row **Assign reviewer** → info-toast (no reviewer/batch-assign picker)<br>• rail tree groups by **process only** (`Document` payload has no layer/component hierarchy)<br>• **in-review progress** = approved-vs-total docs (no per-section review endpoint); stale banner HEAD/“N commits ahead” from `version.newCommitsSince` + latest commit<br>• dev **My Assignments** matches "me" by **display name** (`assignee` has no user id on the list payload) |
| Document (inspector) | `/projects/:id/documents/:docId` | left **doc-tree rail** (active doc highlighted) + **`GET …/documents/{id}/render`** rich payload → **cover** (project/version/layer/group/standard chips), **meta banner** (source + units/functions/globals/components/layers), **typed/nested sections** (richtext, real **interface tables**, **diagram** images per component/unit, `children`), **TOC** outline; **diagrams render real PNGs** via the unauth asset route, with a **"View source"** for the mermaid `.mmd`; **flowcharts** are server-drawn **SVGs** (`FlowchartFigure`: lazy, size reserved, **Open** → full-screen zoom/pan; "Too large to draw" / "not drawn for this run" notes); when `in_review` → **review tracker** (flat `…/documents/{id}` detail) + **assign-reviewers** slide-in; Download `software_detailed_design_<group>` + Compare | • render reads the version's own output + the database (`source:"pipeline"`); the synthesized `source:"model"` payload is only the fallback when that output is missing (the seeded demo documents)<br>• flowcharts are drawn as SVGs on **every** run (`views.flowcharts` only adds the DOCX's PNGs); behaviour diagrams appear only when the project turns on `views.behaviourDiagram` (off in `config.defaults.json`; the wizard sets no views)<br>• the Subbar chip keeps showing the Subbar's version while an older version's document is open<br>• a flowchart entry is `{label, status: drawn|too_large|missing, image_url (SVG), width, height, boxes}` — **no source** (the DOT is never sent: a document can hold 500+); other diagram types are PNG + `.mmd`<br>• body (rich `/render`) + review tracker (flat detail) are **two endpoints**; per-section review state keys off the flat sections<br>• **Mark Complete** = `POST …/approve`; per-section accept/decline/edit lives on Compare |
| Compare | `/projects/:id/compare` | **wired + highlighted** — left **Diff/All doc tree** (Diff = `useCompareDocuments` changed docs; All = `useDocuments` + changed flags), **split view** (`useCompareDocumentDetail`: left=baseline, right=current) rendered as a **single shared scroller + 2-column CSS grid** so both sides scroll together AND stay aligned (each section = one grid row → equal height; the shorter side gets filler whitespace), with **sticky pane headers** and a **"Changes only"** toggle. The detail endpoint now returns a **rich, highlight-annotated diff** (`mode: 'rich'`): the full DOCX-mirroring render (descriptions, **interface tables**, **flowchart/behaviour tables**, **mermaid diagrams**) is built for **both** version snapshots and diffed into typed **blocks** — **word-level** text/keyvalue highlights (`add`/`del`), **per-cell** table marks (`add`/`del`/`change`, rows aligned by first column), and **changed-diagram badges** (mermaid source differs); each changed section shows a **diff badge + `source` artifact chip** (provenance). Diagram PNGs load per-version from the snapshot asset route `…/compare/assets/{versionId}/{group}/{path}`. Falls back to the legacy flat interface-table diff (`mode: 'flat'`) when a snapshot render is unavailable. **Changed-section accents** + per-section **Accept/Decline** (in review), and a **review footer** (resolved/total dots + **Submit Review**/**Approve Document**, shown only when `in_review`). Current ref = the shared Subbar picker (default latest version); the **baseline is fixed** to that version's predecessor and shown as a **read-only badge** in the Reference-pane header. | • doc-level change detection covers **all** content (descriptions/flowcharts/diagrams), not just interface tables (`render_fingerprint`, URL-agnostic)<br>• rich-section review state is **optimistic/local** (rich render ids don't round-trip through the stored-section table); the inline **Edit** control is flat-mode only<br>• subbar **Export/Exit** CTAs from the mockup omitted (no per-page subbar-CTA mechanism)<br>• footer **Approve** shares the doc's review state with the inspector; not role-gated (both buttons shown)<br>• a scoped run's version holds only its scope's documents, so Compare shows every other component as **removed** (decision needed, see PLAN) |
| Versions | `/projects/:id/versions` | list, tag an untagged commit; **View docs / Compare** open the clicked version; a `draft` version reads **Not Run** | • a tag makes an empty draft version that no run fills — a run of that commit needs another name (decision needed, see PLAN) |
| Team | `/projects/:id/team` | invite (an existing account only; **Resend** refreshes the same invite) / role / remove / cancel, pending merge | • no way to create an account (no sign-up, no admin create)<br>• a pending invite never becomes active (no accept flow) |

## Backend gotchas

- **Jobs are real** ([api/services/pipeline_runner.py](../api/services/pipeline_runner.py)): `POST /jobs` runs
  `analyzer.py generate` on a thread and streams progress over SSE; the version and one document per
  component are registered when it completes. With the LLM on, the LLM sets the pace: the sample project
  took ~1 h 50 min on a local Ollama (llama3.2); a rerun of one group with the LLM cache warm, ~4 min.
- A **failed or cancelled** run deletes the draft version it reserved, so its name is free for the retry.
- The **SSE events route is unauthenticated** (`EventSource` connects without a token).
- **In-memory data resets on server restart** — only the in-memory backend, used when no database is configured.
- **Two document-detail endpoints.**
  - `GET …/documents/{id}` → flat detail `{ …meta, sections:[{key,title,order,content,review_state,…}], review_progress }` — drives the inspector's **review tracker** + the list's status. Seeded, no real data.
  - `GET …/documents/{id}/render` → rich `{ cover, toc, sections:[{id,number,title,level,type,content,table,image_url,mermaid,children}], meta:{…,source,layers,components,units_total,functions_total,globals_total} }` — drives the inspector **body**. Built from the version's own pipeline output (`workspaces/<pid>/versions/<ver>/output/<component>/`) and the model and views in the database (`meta.source: "pipeline"`); the synthesized `source: "model"` payload is only the fallback when that output is missing (the seeded demo documents). Diagrams stream from `…/documents/{id}/assets/{path}` (**unauthenticated**, like SSE).
