# Word file updates after corrections — design, contract and plan

> Status: **approved, 2026-10-05; server built 2026-10-05, web being built** (the simple flow). The design is the mockup
> [documents.html](../ui-mockups/documents.html) — `#approve` (an admin), `#review` (a developer), the list, and
> its two mockup-only switches *Generation running* and *Next update fails*. Its words are final.
> Builds on review & update ([REVIEW_UPDATE_API_SPEC](../spec/REVIEW_UPDATE_API_SPEC.md) R9, §3a Flow 6) and
> review & approval ([REVIEW_APPROVE_API_SPEC](../spec/REVIEW_APPROVE_API_SPEC.md) A5, A6, A9, A15, A16).
> The contract (§4) is what the web app is built against; the two specs above carry the same fields.

## 1. The problem, as it is today

| # | What happens | Why it hurts |
|---|---|---|
| 1 | A correction changes the page at once, not the Word file. Only an **admin** can rebuild it ("Re-export"). | The person who made the correction cannot get the corrected file. |
| 2 | "Behind" answers *would an export-only run ship old text?*, not *does this Word file have every correction?* A save re-derives its component's SWE.4 rows and stamps them, so the SWE.4 document reads up to date while its .docx is old — **and Approve can freeze that file**. A picture still being drawn, or a struct description (keyed by no component), puts **every** component behind; a layer added since (`version_components` `stale`) puts **none** behind. | The same word means three different things, and approval can record the wrong file. |
| 3 | A save made while a re-export runs is **lost**: the run restores every stored output row at its start and its capture replaces every row of the version at its end — in every component. Only the web app's pause prevents it. | A rebuild of one component stops every reviewer of the version. |
| 4 | Approve on a document that is behind says "Re-export first"; the re-export route is admin-only; a run that holds the version answers `VERSION_BUSY` without saying what holds it. | Dead ends, in jargon. |
| 5 | A download of an approved document whose kept copy is missing serves the working file. | An approval can silently stop meaning the file it recorded. |

## 2. Decisions

| # | Decision |
|---|---|
| D1 | **The thing is the Word file; the action is Update.** The web app never says "re-export". States: *Up to date* · *Out of date* (why) · *Updating…* · *Update failed* (*Try again*) · *Approved*. The CLI keeps `reexport`. |
| D2 | **"Out of date" means the Word file**, one rule for R9, A15 and Approve: a correction it prints saved after that .docx was written, a layer added to the version since, or a corrected flowchart picture of its component still being drawn. |
| D3 | **The unit of an update is a component**: its SWE.3 and SWE.4 move together (SWE.4's test steps are built from SWE.3's flowchart labels). No one-document update. |
| D4 | **Who may update.** An admin: everything out of date, and *Rebuild all Word files* (every file, also up-to-date ones). A developer (or reviewer): the out-of-date Word files of **the components of the documents they review, plus the document they have open**. The server enforces the bound. |
| D5 | **Editing goes on during an update** except in the components being updated: a save there answers 409 `WORD_FILE_UPDATING` ("Corrections wait until it is done"). Every other document stays editable, and its saves survive the update. |
| D6 | **One update at a time per version, no queue.** A second request joins a running update when that one's components cover it; otherwise it is refused with the running one's job id and components. While a generation (or any run) holds the version, nothing starts, and R9 says what holds it. |
| D7 | **Updates start at five moments**: the reader banner's *Update*, *Update all* / *Update them*, a download's *Corrected file*, Approve's *Update file*, and **Submit**. Done editing only *suggests* one (a toast with *Update*). Every button that starts one on its own asks first (a confirm dialog); inside a dialog that already says what happens (Approve, bulk approve, Download all) and on Submit, that dialog's button is the confirmation. |
| D8 | **Submit updates the document's Word file** when it is out of date, in the background. Submit always goes through; when a generation or another update holds the version its answer says the file stays out of date until that run ends. |
| D9 | **An approved document is never changed by an update.** Its kept Word file (`approved/<doc id>/…`) is what downloads serve; an update may rewrite the working file beside it. A kept file that is missing is an error, never the working file — unless the working file's SHA-256 is the approved one. |
| D10 | **No dead ends.** Approve on an out-of-date file offers *Update file* (Approve turns on when it is done); bulk approve names the out-of-date ones with *Update them*; a failed update says why, with *Try again*. |
| D11 | **Every screen says why it is out of date**: *2 corrections*, *HAL_LAYER added since*, or both. |
| D12 | **The starter is told**: an update's starter gets a notification when it finishes or fails; when an update that Submit started fails, the admins are told too. |

Old D1–D12 of the proposal are folded in above; D13 (More options, settings) is dropped (§7).

## 3. The screens

The mockup is the screen design. What each part reads:

| Where (mockup) | Reads | Starts |
|---|---|---|
| Reader banner: *This Word file is out of date · 2 corrections not in it* **[Update]**, "*N* more … · *Update all* / *Update them*", "Approved, not changed: …", ⋯ *Rebuild all Word files…* (admin) | R9 `outOfDate`, `approvedKept`, `writer`, `reexport` | `POST …/reexport` `out_of_date` (+ `components`, `document_id`); Rebuild: `all` |
| Banner while updating: *Updating Word files… 1 of 2*; then *Word files updated · Download*; *Update failed — <why>* **[Try again]** | R9 `reexport` (`status`, `components`, `componentsDone`, `errorMessage`, `startedBy`) | Try again: the same request |
| Edit bar while its component updates: *Updating this document's Word file. Corrections wait until it is done.* | R9 `outOfDate[].updating` / `reexport.components` | — (saves answer 409 `WORD_FILE_UPDATING`) |
| Documents list card: *N Word files are out of date · reasons* **[Update all / Update them]** | R9 | as the banner |
| A row's download: dot; menu *Corrected file* (updated first) · *Current file* (as it is) | R9 `outOfDate` | `out_of_date`, `components: [its]`, `document_id` |
| Download all: *N files are out of date* · *As they are* · **Corrected files** | R9 | `out_of_date` (an admin: all of it; a developer: theirs) |
| Review tab, *Word file* row: Up to date · Out of date (why) *Update* · Updating… · Update failed *Try again* · Approved | A15 (R9 with `document_id`) | `out_of_date`, `components: [its]`, `document_id` |
| Approve dialog: *Its Word file is out of date.* *Update file* — Approve off until done | A15 | as the Review tab |
| Bulk approve: *N Word files are out of date. Update them* | R9 | `out_of_date`, `components` |
| Submit: toast *Its Word file is updating.* / *Update its Word file after … ends.* | A5's `word_file` | (the server starts it) |
| Bell: *Word files updated: Brake Controller*, *Update failed: …* | A16 | — |
| Any of these while a run holds the version: control off, tooltip *Update after the generation of v1.2.0 ends.* | R9 `writer` | — |

## 4. The API contract

Paths are under `/api/v1`; `V` = `/projects/{project_id}/versions/{version_id}`, `D` =
`/projects/{project_id}/documents`. **Wire format as everywhere**: request bodies snake_case; the review
routes (R9) answer camelCase; the platform routes (jobs, documents, the reexport answer) answer snake_case
with snake_case values. Errors: `{"detail": {"code", "message", "status", …}}`.

### 4.1 Update the Word files — `POST V/reexport`

Body, every field optional:

```json
{"scope": "out_of_date", "components": ["Layer1.Brake-Controller"], "document_id": "docc1442"}
```

| field | meaning |
|---|---|
| `scope` | `"out_of_date"` — the components whose Word files are out of date (§4.3's rule), computed by the server. `"all"` — every component with documents, out of date or not (*Rebuild all*). Absent: `"all"`, as before this contract (existing callers). The web app always sends it. |
| `components` | layer-qualified ids (a document's `group`; the config's spelling — spaces, any case — is read as it, e.g. `Layer1.Sample Core` = `Layer1.Sample-Core`). Each must have documents in the version, else 422 `INVALID_COMPONENTS` (both scopes). With `out_of_date`: only these, of the out-of-date ones. With `all`: exactly these. |
| `document_id` | the document the caller has open (the reader, a row's download). Must be a document of this version (else 404). It widens a developer's bound by its component (below). |

**Who.** An admin (or superuser): any scope. A developer or reviewer: `out_of_date` only, within the
components of the documents of this version they review plus the component of `document_id`; without
`components` the request is that bound. `all` by a non-admin: **403**. `components` outside the bound:
**403** `NOT_YOUR_DOCUMENTS`, `components` = the ones refused.

**Answers**

| status | body | when |
|---|---|---|
| 202 | `{"job_id": "job3c9e1f20", "status": "queued", "version_id": "verf6223ff0", "scope": "out_of_date", "components": ["Layer1.Brake-Controller"], "joined": false}` | an update started |
| 200 | same shape, `"joined": true`, the running job's `job_id`, `status` and `components` | an update already running covers every component asked for: follow it |
| 200 | `{"job_id": null, "status": "up_to_date", "version_id": "…", "scope": "out_of_date", "components": [], "joined": false}` | nothing asked for is out of date (`out_of_date` only) |

Follow the job with `GET /projects/{project_id}/jobs/{job_id}` (or `/events`): `queued` → `running` →
`complete` | `failed` (`error_message`). Its components are written one at a time; R9's
`reexport.componentsDone` counts them.

**Errors**

| status | `code` | extra fields | when |
|---|---|---|---|
| 403 | — / `NOT_YOUR_DOCUMENTS` | `components` | not a member; `all` by a non-admin; components outside the bound |
| 404 | — | | the version, or `document_id`, is not this project's / version's |
| 409 | `REEXPORT_RUNNING` | `job_id`, `kind` (`update` \| `rebuild` \| `export` \| `resume`), `scope` (`out_of_date` \| `all` \| `export` -- a Components → Generate export and a resume are `export`), `components` | another update, an export or a resume runs for this version and does not cover the request. Offer *Try again* once it ends |
| 409 | `VERSION_BUSY` | `writer` (§4.2, snake_case) | another process holds the version: a generation, a CLI run |
| 409 | `NO_DOCUMENTS`, `VERSION_NOT_READY` | `job_id` (the latter) | as before |
| 422 | `INVALID_COMPONENTS` | `components` | a component with no documents in the version (either scope) |
| 422 | `VALIDATION_ERROR` | | `scope` other than `out_of_date` or `all` |

The running update is looked for **before** the writer: an update holds the version's writer lock too, and
`REEXPORT_RUNNING` says which one it is where `VERSION_BUSY` could not. The older
`POST /projects/{project_id}/jobs/{job_id}/reexport` stays: admin, `scope: "all"`.

**The job** (`GET …/jobs/{job_id}`, snake_case) gains `started_by` (`{"user_id", "name", "initials"}` or
`null`) and `reason`: `update` (scope `out_of_date`), `rebuild` (scope `all`), `submit` (started by A5),
`export`, `resume`, or `null` (a generation). `mode` is `reexport` for an update, as before.

### 4.2 R9 — which Word files are out of date — `GET V/export-readiness`

R9 keeps every field it had (REVIEW_UPDATE_API_SPEC §14) and gains (camelCase):

```json
{
  "stale": true,
  "staleComponents": ["Layer1.Brake-Controller", "Layer1.HVAC-Ctrl"],
  "outOfDate": [
    {"documentId": "docc1442", "component": "Layer1.Brake-Controller", "name": "Brake Controller",
     "docType": "SWE.3", "why": ["corrections"], "corrections": 2, "pictures": 0, "layer": null,
     "updating": false},
    {"documentId": "docd7a10", "component": "Layer1.HVAC-Ctrl", "name": "HVAC Ctrl",
     "docType": "SWE.4", "why": ["layerAdded"], "corrections": 0, "pictures": 0, "layer": "HAL_LAYER",
     "updating": false}
  ],
  "approvedKept": [
    {"documentId": "doce0b55", "component": "Layer1.HVAC-Ctrl", "name": "HVAC Ctrl", "docType": "SWE.3",
     "why": ["layerAdded"], "corrections": 0, "pictures": 0, "layer": "HAL_LAYER"}
  ],
  "writer": {"kind": "generation", "jobId": "job5e21aa0c", "command": "generate",
             "since": "2026-10-05T08:00:00Z", "components": null,
             "componentsDone": 11, "componentsTotal": 54, "startedBy": null},
  "reexport": {"jobId": "job3c9e1f20", "status": "running", "startedAt": "…", "completedAt": null,
               "errorMessage": null, "scope": "out_of_date", "reason": "update",
               "components": ["Layer1.Brake-Controller"], "componentsDone": 0,
               "startedBy": {"userId": "u2", "name": "Developer B", "initials": "DB"}}
}
```

| field | meaning |
|---|---|
| `outOfDate[]` | every **not approved** document of the version whose Word file is out of date (§4.3), sorted by name then type. An update of its `component` brings it up to date |
| `.docType` | `SWE.3` \| `SWE.4` (the document's `process`) |
| `.why` | a list, one or more of `corrections` (a correction it prints, saved after its file was written), `layerAdded` (a layer added to the version since changed its component's model), `pictures` (a corrected flowchart picture of its component still being drawn — a SWE.3 that prints flowcharts) |
| `.corrections` / `.pictures` | the counts behind `corrections` and `pictures` (0 when not a reason) |
| `.layer` | the layer `layerAdded` names (`HAL_LAYER`), `null` when not a reason or not recorded |
| `.updating` | a running update (or export) of this version has its component in scope: show *Updating…*, not *Update* |
| `approvedKept[]` | approved documents that would be out of date: their kept file is what is approved and is not changed ("Approved, not changed"). Same fields, no `updating` |
| `writer` | what holds the version now, or `null`. `kind`: `generation` \| `update` \| `rebuild` \| `export` \| `resume` \| `other`; `jobId` when a job of this server runs it; `components` for an update or export; `componentsDone` / `componentsTotal` from the run's component states (`null` when not known); `startedBy` a user ref or `null`. While it is set, no update starts: say *Update after the generation of v1.2.0 ends.* (`update`: *after the update of <components> ends*) |
| `reexport` | the newest update job, as before, plus `scope`, `reason`, `components`, `componentsDone`, `componentsFailed` (of its components, those that failed in it: their Word files were not written and stay in `outOfDate`), `startedBy`. `status: "failed"` with `startedBy` the caller = *Update failed — <errorMessage>* with *Try again*; to anyone else the files are simply out of date. An update whose every component failed is `failed`; one where some did is `complete`, with `componentsFailed` |
| `stale` | `outOfDate` is not empty. A version with no documents recorded keeps the old version-wide answer |
| `staleComponents` | the components of `outOfDate`, sorted |

`pendingRenders` and `failedRenders` stay version-wide. **A15** — `?document_id=` — answers the same body
for that one document: `outOfDate` holds it or is empty, `approvedKept` likewise, `stale` is whether it is
out of date, and `pendingRenders` counts its component's pictures only.

### 4.3 The rule — when a Word file is out of date

One function (`api/services/word_files.py` over `engine/review/word_files.py`) answers R9, A15, Approve, the
reexport scope and Submit. For a document of component *C* and type *T* whose working .docx was written
at *W* (`documents.word_file_at`): **when the run that wrote it started**, for every kind of run --

* set as the run's output is stored, for each .docx it wrote: an update's, an export's or a resume's
  start, and a generation's (`version_runs`, the run storing it);
* an update takes it **holding the version's save lock** (`word_files.wait_for_saves`), once its job is
  visible: a save under way commits first and is in what the run reads; a later one is newer than *W*,
  or is refused by the hold (§4.6, checked again under the same lock);
* a document recorded after its run stored (a generation's, a cut-short run's) takes that run's start
  when the file was written while the version's latest run ran, else when the run that derived its
  directory read its inputs (`_derivations.json`), else -- no run start known -- the file's own time.
  A document recorded before 0018 uses the file's time on disk.

| reason | when |
|---|---|
| `corrections` | a correction **in force** (orphans never count) saved after *W*, whose text *T* prints: its key names *C* (a struct description: a unit of *C* shows it in its stored unit header table, or *C*'s own stored table cannot say -- a row from before `typeKey`, or no table: decided per component), and its views include one *T*'s document is read from (`export_guard.views_read`: a flowchart label reaches SWE.3 only where SWE.3 prints flowcharts; a description reaches both) |
| `layerAdded` | a layer added to the version since changed *C*'s model: `version_components.stale_layers` is set (or the state is `stale`, for a row from before 0018). Kept through an update that fails, is cancelled or is killed -- run.py marks the component waiting, generating, failed -- until *C* is `generated` again |
| `pictures` | a render job of *C*'s flowcharts is pending (`render_jobs.flowchart_id` names *C*), and *T* prints flowcharts |

An approved document is never out of date (its kept file is the approved one); it goes to `approvedKept`
instead. A document with no *W* and no file on this server keeps the old answer (the derivation stamps).
A component that **fails** in an update has no new Word file: its *W* does not move, so it stays out of
date. An error reading the component states is an error (R9 and Approve fail; Submit reports it in
`blocked_by`), never "nothing is stale".

**What a run stores.** A re-export, export or resume by component stores only the components it rebuilt
-- plus every component directory the database has never stored (a run cut short after making it and
before its one capture: a generation stores at its end, and a `resume` that makes the rest must store
it too; storing it replaces no row). A `reexport --scope group:/layer:` stores the components run.py
asked for or started (`version_components`). A generation stores the whole version. The derivation
stamps come from the stored records.

### 4.4 A5 — submit for approval

The answer gains `word_file` (snake_case, as every A-route):

```json
{"document": {"…": "Document"},
 "word_file": {"state": "updating", "job_id": "job3c9e1f20", "blocked_by": null}}
```

| `state` | meaning |
|---|---|
| `up_to_date` | its Word file has every correction; nothing started |
| `updating` | an update of its component started now (`reason: "submit"`, started by the submitter), or a running one already covers it — `job_id` |
| `out_of_date` | it could not start: `blocked_by` says what holds the version, always with `kind`, `job_id`, `components` and `message`. Another update or export (`kind` `update` \| `rebuild` \| `export`): its `job_id` and `components`. A generation or a command-line run (`VERSION_BUSY`): the writer, §4.2's fields in snake_case (`command`, `since`, `components_done`, `components_total`, `started_by` too). Anything else: `kind: "other"`. The submit has gone through; the file stays out of date until that run ends |

A refusal never fails the submit.

### 4.5 A6, A9 — approve, approve several

- **A6** **409** `STALE_EXPORT` (code kept) now follows §4.3, with `why`, `corrections`, `pictures` and
  `layer` beside `message`. **409** `WORD_FILE_UPDATING` with `job_id` while an update or export of its
  component runs (Approve turns on when it is done).
- **A9** each `skipped[]` item carries the same `code` and extra fields.

### 4.6 Corrections while an update runs — R3, R4, R6, R8

A save, an undo, a behaviour row or a flowchart answers **409** `WORD_FILE_UPDATING` (`job_id`,
`components`) when the text's component is in the scope of a running update or export of the version (a
struct description: when a component that shows it is), or in a CLI run that holds the version. Nothing is
saved; save again when it ends. Checked after `DOCUMENT_APPROVED`. A save in any other component goes
through, and the update leaves it alone.

### 4.7 Notifications — A16

| `type` | to | `message` (example) | `document_id` |
|---|---|---|---|
| `word_files_updated` | the starter | `Word files updated: Brake Controller in v1.2.0.` · rebuild: `Word files rebuilt: v1.2.0.` | the document the request named, else null |
| `word_files_update_failed` | the starter | `Update failed: Brake Controller in v1.2.0 — flowchart pictures could not be drawn.` · rebuild: `Rebuild failed: v1.2.0 — …` | as above |
| `word_files_update_failed` | the admins, when Submit started it (not the starter) | `Update failed: Brake Controller in v1.2.0, started by the submit of Developer B — …` | the submitted document |

Several components read `Brake Controller and HVAC Ctrl`, then `3 components`. A cancelled update tells nobody.
An update where some components failed tells both: `word_files_updated` for the ones written,
`word_files_update_failed` for the failed ones, with the first one's reason. A Word file that a reader
(a download) holds open on Windows is waited for up to 8 seconds; then that component fails with the
reason, its previous file untouched.

### 4.8 Downloads of an approved document

`GET D/{doc}/download` and the export-all zip serve the kept copy. When it is missing, the working file is
served only if its SHA-256 is the approved one; otherwise **409** `APPROVED_FILE_MISSING` (the zip:
`document_ids` of every such document) — never a file that may differ from what was approved.

## 5. Server tasks

Built 2026-10-05 (all of S0–S6, uncommitted on `feat/cli-wordfiles-bitbucket-components`); tests
`tests/unit/test_word_files.py`, `tests/api/test_reexport_jobs.py` (`TestTheUpdateScope`,
`TestTheStarterIsTold`), `tests/api/test_review_approve.py` (`TestSubmitUpdatesTheWordFile`, the
approve and download cases), `tests/api/test_review_overrides_api.py` (`TestExportReadiness`,
`TestCorrectionsWhileAnUpdateWritesTheirComponent`). A database upgrades with `analyzer.py setup`
(migration 0018).

| # | Task | Where |
|---|---|---|
| S0 | `documents.word_file_at` (migration **0018**), set when a run's output is stored, for each .docx that run wrote, and when a document is recorded. One function per document → `{outOfDate, why, corrections, pictures, layer}`, used by R9, A15, Approve, the reexport scope and Submit | `engine/review/word_files.py`, `api/services/word_files.py`, `incremental/store.py`, `document_registry.py` |
| S0b | Pending renders counted per component (the first part of `flowchart_id`) | `review/render_queue.py` |
| S4a | `reexport`, `export` and `resume` store **only the components they rebuilt**; the derivation stamps are recomputed from the stored records. A save made mid-run in another component survives; one in a rebuilt component reads out of date | `incremental/store.py`, `core/model_store.py`, `export_guard.py`, `analyzer.py`, `pipeline_runner.py` |
| S4b | 409 `WORD_FILE_UPDATING` on R3, R4, R6, R8 | `api/routes/text_overrides.py` |
| S1 | `scope` + `components` + `document_id` on the reexport route; nothing out of date → 200, no job | `api/routes/jobs.py`, `api/services/word_files.py` |
| S2 | Developers within D4's bound; `all` and the old route admin-only | same |
| S3 | R9 `outOfDate`, `approvedKept`, `writer`, and `reexport`'s new fields | `text_overrides.export_readiness` |
| S5b | The running update/export found before the writer: `REEXPORT_RUNNING` with job id and components, join when it covers; `VERSION_BUSY` with `writer` | `pipeline_runner.start_reexport` |
| SA | Approve and bulk approve on §4.3 (layer-added included); 409 while updating. The in-process re-export goes from Phase 3 when a layer made a component stale | `review_workflow.approve`, `pipeline_runner._do_reexport` |
| SD | Atomic .docx writes (temp file + `os.replace`) in both exporters; an approved document's missing kept copy is an error | `docx_common.py`, `docx_exporter.py`, `swe4_exporter.py`, `api/routes/documents.py` |
| S5 | Submit starts the out-of-date update of the document's component; refusals caught; `word_file` | `api/routes/documents.py`, `api/services/word_files.py` |
| S6 | `analysis_jobs.started_by`, `.reason` (0018); notifications at an update's end | `pipeline_runner`, `api/services/word_files.py` |

## 6. Web tasks (another agent, against §4)

| # | Task |
|---|---|
| W0 | The confirm dialog for every update a button starts on its own (D7): the files it writes, each with why; "Corrections to X wait until it is done."; "Approved files are not changed."; Rebuild all: "Rewrites every file. Takes longer." In-dialog buttons and Submit start without a second dialog. |
| W1 | Wording: no "re-export" anywhere — *Update*, *Update all*, *Update them*, *Rebuild all Word files…* (admin ⋯), the rename toast too. |
| W2 | Reader banner (R9 / A15): out of date + why, *Update*, the line for the rest this role reaches, "Approved, not changed", progress *1 of 2*, *Word files updated · Download*, *Update failed — why* + *Try again*; the edit bar's hold while its component updates (and 409 `WORD_FILE_UPDATING` on a save). |
| W3 | A row's download menu (*Corrected file* / *Current file*); Download all (*As they are* / *Corrected files*). |
| W4 | Review tab's *Word file* row; the Approve dialog's *Update file*. |
| W5 | Documents list card row 2 (*N Word files are out of date · reasons* + *Update all* / *Update them*); the Components panel's stale strip sends `scope: "all"` with its components (admin). |
| W6 | Toast + bell at an update's end (A16 types); Done editing's suggestion; Submit's toast from `word_file`. |
| W7 | Bulk approve's *Update them*; the blocked tooltips from `writer` / `REEXPORT_RUNNING`; the reason on every surface. |

## 7. What is out

| Dropped | Why |
|---|---|
| A queue of updates (old S8) | D6: join when covered, else refuse with the running one's id. |
| *More options* in the confirm dialog, the one-document scope, `docTypes`, `rederive` (old D13, S1) | One concept: an update writes a component's SWE.3 and SWE.4; the server decides whether to re-derive. |
| Per-project settings for when updates start on their own (old S10) | Submit always updates; Done editing only suggests. |
| `approvedKept` as a flag on each row (old S7) | It is the `approvedKept` list in R9. |
| "Waits for the run generating v1.2.0, starts on its own after" | Nothing waits: the control is off and says why. |
