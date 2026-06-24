# Frontend ↔ API integration notes

The app calls the real FastAPI server in [`../../api`](../../api); wire-format differences are handled
in the boundary mappers ([src/services/mappers/](src/services/mappers/)). `api/` is treated as fixed —
the one exception is the new-project wizard, which needed `repositories/*`, `users/search`, and an
`access_token` on `POST /projects` (server-side detail: [api/PROJECT_CONTEXT.md](../../api/PROJECT_CONTEXT.md) §12).

## Setup

- Base URL: `VITE_API_URL` ([.env.example](.env.example)) — defaults to `http://localhost:8000/api/v1`.
- Run the API (repo root): `pip install -r api/requirements.txt && uvicorn api.main:app --reload --port 8000`.
- Demo login: `alice@aspice.dev` / `secret` (admin). Seed users in [api/README.md](../../api/README.md).

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
| Compare | `/projects/:id/compare` | **wired** — left **Diff/All doc tree** (Diff = `useCompareDocuments` changed docs; All = `useDocuments` + changed flags), **split view** (`useCompareDocumentDetail`: left=baseline, right=current; markdown pipe-tables parsed via `lib/markdown.parseSectionBody`) rendered as a **single shared scroller + 2-column CSS grid** so both sides scroll together AND stay aligned (each section = one grid row → equal height; the shorter side gets filler whitespace), with **sticky pane headers** and a **"Changes only"** toggle that collapses unchanged sections, **changed-section accents** + per-section **Accept/Decline/Edit** (persisted via `useReviewSection` → `PATCH …/sections/{key}`; review_state + edited content overlaid from the flat `useDocument` detail), **edit modal**, **empty/no-baseline states**, and a **review footer** (resolved/total dots + **Submit Review**/**Approve Document** → `useSubmitReview`/`useApproveDoc`, shown only when the doc is `in_review`). Current ref = the shared Subbar picker (`selectedRef`, default latest version); the **baseline is fixed** to that version's predecessor and shown as a **read-only badge** in the Reference-pane header (not user-pickable — matches the mockup). | • backend `compare` is a **shallow mock**: `get_or_create` **ignores the refs** (one canned diff per project; only **p1** seeded → `doc1` changed, `doc2` added) — switching current/baseline does **not** change the diff<br>• section diff is **section-level only** (`changed`/`unchanged`); baseline content for changed sections is the literal placeholder `"[previous version content]"` — **no row-level +added/−removed**<br>• subbar **Export/Exit** CTAs from the mockup omitted (no per-page subbar-CTA mechanism)<br>• footer **Approve** shares the doc's review state with the inspector (same `review_state`); not role-gated (both buttons shown) |
| Versions | `/projects/:id/versions` | list, tag an untagged commit | — |
| Team | `/projects/:id/team` | invite / role / remove / cancel, pending merge | — |

## Backend gotchas

- **Jobs are simulated** ([api/services/job_runner.py](../../api/services/job_runner.py)): `POST /jobs` runs a thread through 4 phases (~10–15 s) streamed over SSE, then synthesises a Version + Documents and flips the project to `in_review`. No C++ is parsed.
- The **SSE events route is unauthenticated** (`EventSource` connects without a token).
- **In-memory data resets on server restart.**
- **Two document-detail endpoints.**
  - `GET …/documents/{id}` → flat detail `{ …meta, sections:[{key,title,order,content,review_state,…}], review_progress }` — drives the inspector's **review tracker** + the list's status. Seeded, no real data.
  - `GET …/documents/{id}/render` → rich `{ cover, toc, sections:[{id,number,title,level,type,content,table,image_url,mermaid,children}], meta:{…,source,layers,components,units_total,functions_total,globals_total} }` — drives the inspector **body**. Built from a **committed snapshot of real analyzer output** at `api/fixtures/documents/<group>/` (a curated copy of `output/<group>/`: real `interface_tables.json` → interface tables; diagram PNGs/MMDs). `cover`/counts come from the fixture + project. **Groups with a fixture (`Full`/`Access`/`Diag`) → `source:"pipeline"`; all others → a synthesized fallback (`source:"model"`).** It deliberately does **not** read the live `output/` (gitignored, machine-specific, not produced by the mock API). Diagrams stream from `…/documents/{id}/assets/{path}` (**unauthenticated**, like SSE; path-restricted to the group fixture). To grow the data: copy more groups into the fixture (or, later, wire to a real pipeline run).
