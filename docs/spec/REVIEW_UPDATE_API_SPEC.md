# Review & Update — API Specification (for UI integration)

The HTTP contract for correcting the LLM's text in a generated document. This is what the UI is
built against.

Update this doc first when changing the endpoints, then code + tests.
Requirements: [REVIEW_UPDATE_SPEC](REVIEW_UPDATE_SPEC.md) (`REQ-` ids below) ·
design: [REVIEW_UPDATE_DESIGN](../design/REVIEW_UPDATE_DESIGN.md) ·
merging the branch: [REVIEW_UPDATE_HANDOVER](../design/REVIEW_UPDATE_HANDOVER.md).

**Base URL, path prefix, error shape and the `projectId` / `versionId` identifiers** are shared with
[05-incremental-api-spec §1](../production-redesign/05-incremental-api-spec.md#1-conventions) and
are not repeated. That document covers the incremental-generation endpoints only; these are a
separate feature with its own surface.

---

## Contents

- [1. What can be edited](#1-what-can-be-edited)
- [2. Slot keys, and why they are not in the path](#2-slot-keys-and-why-they-are-not-in-the-path)
- [3. Endpoint index](#3-endpoint-index)
- [3a. UI flows — which calls, in which order](#3a-ui-flows--which-calls-in-which-order)
- [4. Wire format — read this before writing a client](#4-wire-format--read-this-before-writing-a-client)
- [5. Shared objects](#5-shared-objects)
- [6. R1 — list the corrections in a version](#6-r1--list-the-corrections-in-a-version)
- [7. R2 — read one slot](#7-r2--read-one-slot)
- [8. R3 — correct one slot](#8-r3--correct-one-slot)
- [9. R4 — undo one slot](#9-r4--undo-one-slot)
- [10. R5 — one slot's history](#10-r5--one-slots-history)
- [11. R6 — correct one Dynamic Behaviour row](#11-r6--correct-one-dynamic-behaviour-row)
- [12. R7 — read a flowchart's labels](#12-r7--read-a-flowcharts-labels)
- [13. R8 — correct a flowchart, in one call](#13-r8--correct-a-flowchart-in-one-call)
- [14. R9 — export readiness](#14-r9--export-readiness)
- [15. R10 — the regeneration queue](#15-r10--the-regeneration-queue)
- [15a. R11 — what can be edited](#15a-r11--what-can-be-edited)
- [16. Errors and concurrency](#16-errors-and-concurrency)
- [17. Not yet implemented](#17-not-yet-implemented)

---

## 1. What can be edited

Seven **slot kinds** (`REQ-ED-01`). Every request names one:

| `slot_kind` | what it is | how it is saved |
|---|---|---|
| `description` | a function's or global's description | R3 |
| `behaviourInputName` | the behaviour table's input name | R3 |
| `behaviourOutputName` | the behaviour table's output name | R3 |
| `unitDescription` | a unit's description | R3 |
| `structDescription` | a struct's, class's or union's description — the information column of its unit header row | R3 |
| `behaviourDescription` | a Dynamic Behaviour row — a **list** of bullets, edited as one block | **R6** |
| `nodeLabel` | one flowchart node's label | **R8** |

The last two are rejected by R3 with **501**. They are produced by Phase 3 rather than stored in the
model, so they have their own save paths.

`slot_kind` is an **enum** everywhere it appears, so Swagger offers these seven as a dropdown and
anything else is refused by validation with **422** naming the allowed values. On R1 it is an
optional filter — omit it for every correction in the version.

---

## 2. Slot keys, and why they are not in the path

A `slot_key` addresses one slot. It is **built by the server** and returned to you — never assembled
in the UI (`REQ-ID-01`). Take it from an R1/R2/R7 response and send it back unchanged.

| `slot_kind` | shape of `slot_key` |
|---|---|
| `description`, `behaviourInputName`, `behaviourOutputName` | the entity key |
| `structDescription` | the type's data-dictionary key, e.g. `AddOperation` or `NS::Wrapped` |
| `unitDescription` | the unit key, `Component\|Unit` |
| `behaviourDescription` | `functionId` + `U+0001` + `externalCallerId` |
| `nodeLabel` | `entityKey` + `U+0001` + `nodeId` |

A key contains `|`, `:`, `,`, `*`, spaces and a `U+0001` separator, so **keys travel in the body or
a query parameter, never in a path segment.** URL-encode them in query strings as usual; `U+0001`
becomes `%01`.

**Copying a key by hand** (Swagger, Postman, a browser): every JSON viewer DISPLAYS the `U+0001`
separator as the six characters `\u0001`, and nobody can type the real character. The
server accepts that displayed spelling as the same key, so a `slotKey` copied from any response and
pasted into R2, R3, R4 or R5 works as it is. A real key never contains a backslash, so this cannot
collide with one. A UI reading the key out of parsed JSON is unaffected — it already holds the real
character.

**A malformed key is a 400 that says what the key is made of.** The commonest mistake is a node
label addressed by its **flowchart id**: labels are stored per node, so a `nodeLabel` key is the
flowchart id, the separator, then the node id — take the node's `slotKey` from R7.

**A flowchart is addressed the same way**, by its function id — `flowchartId` in R11 and R7 — sent
as `flowchart_id` in R7's query and R8's body. It is the same string as the key of that function's
`description`, and that is not a clash: which kind of text a key names never comes from the key. It
comes from `slot_kind` (R2, R3, R4, R5) or from the route itself (R6 is a behaviour row, R7 and R8
are node labels), and a correction is stored under (version, kind, key). Sending one node's
`slotKey` where a flowchart id belongs is a 400 that names the flowchart id it should have been.

---

## 3. Endpoint index

| # | Method | Path | Purpose |
|---|---|---|---|
| **R1** | GET | `/projects/{projectId}/versions/{versionId}/overrides` | The corrections in a version (an overlay — see §6) |
| **R2** | GET | `/projects/{projectId}/versions/{versionId}/overrides/slot` | One slot — its text, and its correction if it has one |
| **R3** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Correct one slot |
| **R4** | DELETE | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Undo — restore the LLM original |
| **R5** | GET | `/projects/{projectId}/versions/{versionId}/overrides/history` | The retained edits of one slot |
| **R6** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/behaviour` | Correct one Dynamic Behaviour row |
| **R7** | GET | `/projects/{projectId}/versions/{versionId}/flowcharts/labels` | Every node label of one flowchart (`?flowchart_id=`) |
| **R8** | PUT | `/projects/{projectId}/versions/{versionId}/flowcharts/labels` | Correct a flowchart, one call |
| **R9** | GET | `/projects/{projectId}/versions/{versionId}/export-readiness` | Would exporting now ship stale text? |
| **R10** | GET | `/projects/{projectId}/versions/{versionId}/regeneration-queue` | Slots needing regeneration because a correction invalidated them |
| **R11** | GET | `/projects/{projectId}/versions/{versionId}/slots` | What **can** be edited — the slots themselves, with their text and key |

Every path is under the `/api/v1` prefix. All require project **membership** (`REQ-API-05`).

**`versionId` is the version's id, not its tag.** A run started from the web app stores the version
under a generated id such as `ver1a2b3c4d`; the name it was given, such as `v1`, is only its tag.
Take the id from the job (`job.version_id`) or from `GET /projects/{projectId}/versions` (`id`, next
to `tag`). A version that is not one of this project's is **404** on every endpoint here, and when
the value sent is the project's tag for a version, the message names that version's id. (A version
generated with `analyzer.py` has the id you gave it, so there the two are the same.)

> **Membership is a row, with one exception.** Access is per project: signing in gives you
> nothing on a project you were not added to, and every endpoint here answers
> `403 "Project membership required."`. `POST /api/v1/projects` adds its creator; CLI onboarding
> adds every **superuser** (`users.is_superuser`), and a superuser reaches every project whether
> or not a row exists. Nobody is a superuser until made one —
> `python tools/grant_access.py --set-superuser --email <address>` — and the seeded
> `admin@aspice.dev` login is an ordinary user. To add someone else:
> `python analyzer.py grant --project-id <p> --email <them>`.

---

## 3a. UI flows — which calls, in which order

The endpoints from a screen's point of view. Each path below is under `/api/v1/projects/{projectId}`;
each R-number's full contract is in §6–§15a. Every call sends `Authorization: Bearer <token>`.
**Every route gives a slot the same fields** (§5 `Slot`), so one piece of UI code renders a slot
whichever call returned it. A save answers with the slot as it now is, so the edited item needs no
second request. Nothing is pushed, though: what *other* reviewers save appears on the next read.

**Which versions.** R1–R11 work on any version. The document page (`/documents/{docId}/render`) and
the re-export button need a job row and document rows, which only a run started from the web app
writes. A version generated with `analyzer.py generate` has neither: correct it with these
endpoints, then export with `python analyzer.py reexport --project-id <p> --version-id <v>`.
A project onboarded with `analyzer.py onboard` cannot be run from the web app either:
`POST /jobs` answers **409 `NO_ARCHITECTURE`**, because its layers live in
`workspaces/<p>/config.json` rather than the database, and a run would replace that file.

### Flow 1 — open a document

| step | call | why |
|---|---|---|
| 1 | `GET /documents?version_id={versionId}` | the version's documents, one per component; `documents[].id` is the `docId` |
| 2 | `GET /documents/{docId}/render` | the page. Draw its flowcharts from their DOT — see *Drawing a flowchart* below |
| 3 | R9 `GET /versions/{versionId}/export-readiness` | the banner: `stale: true` means corrections are not in the Word file yet |
| 4 | R1 `GET /versions/{versionId}/overrides` | optional: mark corrected items. Fetch once, index by `slotKey` |

### Flow 2 — correct a text: `description`, `behaviourInputName`, `behaviourOutputName`, `unitDescription`, `structDescription`

| step | call | why |
|---|---|---|
| 1 | R11 `GET /versions/{versionId}/slots?slot_kind=<kind>&unit=<unit>` | the editable items, each with `slotKey`, `label` and current `text` |
| 2 | R3 `PUT /versions/{versionId}/overrides/slot` with `{"slot_kind", "slot_key", "text"}` | save |
| 3 | — | show the answer: it is the item as it now is (`text`, `humanText`, `canUndo` …). When `queuedForRegeneration` is not empty, say which other texts the next run rewrites |
| 4 | R9 | update the banner |

For `structDescription` the same `unit=` filter returns the structs, classes and unions that unit's
**unit header table** shows; match a row on the page by `label` (the type name). The corrected text
reaches the page and the Word file with the next re-export (§14).

### Flow 3 — correct a Dynamic Behaviour row

| step | call | why |
|---|---|---|
| 1 | R11 `GET /versions/{versionId}/slots?slot_kind=behaviourDescription&unit=<unit>` | rows with `bullets`, `functionId`, `externalCallerId` and `slotKey` |
| 2 | R6 `PUT /versions/{versionId}/overrides/behaviour` with `{"function_id", "external_caller_id", "bullets"}` | save the **whole** list; both ids copied from step 1. The answer is the row as it now is |
| 3 | R9 | update the banner |

### Flow 4 — correct flowchart labels

| step | call | why |
|---|---|---|
| 1 | R11 `GET /versions/{versionId}/slots?slot_kind=nodeLabel&unit=<unit>` | one row per flowchart, with its `flowchartId`. Coming from the page, match the flowchart by `functionName` within its unit — the page carries no tokens (§17) |
| 2 | R7 `GET /versions/{versionId}/flowcharts/labels?flowchart_id=<flowchartId>` | every node's `nodeId`, `text` and `slotKey`, and the diagram as `dot`. Draw the diagram; list the labels for editing |
| 3 | R8 `PUT /versions/{versionId}/flowcharts/labels` with `{"flowchart_id": "<flowchartId>", "labels": {"<nodeId>": "<text>"}}` | **only the labels that changed**, all in one call |
| 4 | — | the answer carries each saved node as it now is (`labels`) and the rebuilt diagram (`dot`): redraw from it, and the correction shows at once. `renderPending: true` is about the PNG in the Word file only |

### Flow 5 — undo and history, any kind

| call | notes |
|---|---|
| R4 `DELETE /versions/{versionId}/overrides/slot?slot_kind=…&slot_key=…` | back to the LLM's text. A flowchart label is undone per node, with that node's `slotKey` from R7; a behaviour row with the `slotKey` from R11. Offer Undo exactly where the slot says `canUndo: true`. The answer is the slot as it now is (for a node label, with the rebuilt `dot`) |
| R5 `GET /versions/{versionId}/overrides/history?slot_kind=…&slot_key=…` | every edit of that one slot, oldest first |

### Flow 6 — put the corrections into the Word file

| step | call | why |
|---|---|---|
| 1 | R9 | `stale: true`: show "N corrections are not in the Word file yet" and a Re-export button. `pendingRenders` = flowchart pictures the re-export redraws. `reexport.status` `queued` or `running`: one is already under way — follow `reexport.jobId` (step 3) instead of offering the button |
| 2 | `POST /versions/{versionId}/reexport` | project **admin** only — show the button when `GET /projects/{projectId}` gives `my_role: "admin"`. **Any** version, not only the newest. Answers **202** `{"job_id", "status": "queued", "version_id"}` at once; the server re-derives first when the version is stale. **409 `REEXPORT_RUNNING`** while one is running for this version — its `detail.job_id` is the job to follow |
| 3 | `GET /jobs/{job_id}` every few seconds, or the stream `GET /jobs/{job_id}/events` | `status` goes `queued` → `running` → `complete`, or `failed` with `error_message` saying why. Keep the button disabled until then. The job has `mode: "reexport"` and phases 3 and 4 only (3 is `skipped` when there was nothing to re-derive). Jobs answer in snake_case (§4) |
| 4 | R9 again | `stale: false` and `reexport.status: "complete"` |
| 5 | `GET /documents/{docId}/download` | the new Word file. Until step 3 says `complete`, the previous one |

Nothing exports on its own. `GET /jobs/current` is the project's latest *generation*; a re-export is
never "current", so follow it by its own `job_id`.

### Flow 7 — needs attention (optional panel)

R10 `GET /versions/{versionId}/regeneration-queue`: texts the next run rewrites because a correction
changed what they were written from. Show each with its `reason`.

### Drawing a flowchart

The page payload and R7 both carry the flowchart as **Graphviz DOT, read from the database**:

| where | field |
|---|---|
| page: `flowchart_table.flowcharts[]` | `mermaid` — a legacy name; the content is DOT, not Mermaid |
| R7, R8, and R4 on a node label | `dot` |

R8 rebuilds that DOT in the same request that saves a label, and answers with it (`dot`), so **draw
the DOT and the corrected flowchart shows at once** — after the save and after a reload. The PNG (`image_url`) is a file on disk that only the next re-export
redraws, so a page that shows the PNG shows the old label until then. Keep the PNG as the fallback.

Draw it with **`@viz-js/viz`**: Graphviz compiled to WebAssembly, and the library the pipeline itself
uses for the Word file's pictures (`engine/config/render_dot.mjs`), so the browser and the document
lay the graph out alike. Use the pipeline's version range, `^3.29.0` (root `package.json`).

```ts
import { instance } from '@viz-js/viz'   // import lazily: the WebAssembly is large

const viz = await instance()              // create once, reuse
try {
  const svg = viz.renderSVGElement(dot)   // an SVGSVGElement: put it in a scrollable, zoomable box
} catch {
  // throws when the DOT cannot be drawn: show the PNG (image_url) instead
}
```

A long flowchart is cut into **parts** for the Word page (`label` ends "Part K of N"; the later parts
have `mermaid: null`). In the browser, draw the first part's DOT once as one scrollable diagram and
skip the later parts.

---

## 4. Wire format — read this before writing a client

**Requests are `snake_case`. Responses are `camelCase`.** This is not a typo, and it holds for
every review endpoint (R1–R11). **The platform endpoints a review screen also calls — jobs,
documents, the page payload — answer in `snake_case`** (`job.version_id`, `image_url`, `my_role`);
the web-app's mappers (`web-app/src/services/mappers/`) convert those. Do not expect one convention
across both.

| direction | convention | example |
|---|---|---|
| request body field | `snake_case` | `{"slot_kind": "description", "slot_key": "…", "text": "…"}` |
| query parameter | `snake_case` | `?slot_kind=description&slot_key=…` |
| **path** parameter | `snake_case` in code, but they are positional — `{projectId}` above is just the value | `/projects/ftl-a1b2c3/versions/v-7/…` |
| response field | `camelCase` | `{"slotKind": "description", "humanText": "…"}` |

Sending `slotKind` in a body or query string yields **422**, with pydantic's `detail` array naming
the missing field. This is the single most likely thing to cost an afternoon, so it is stated here
rather than left to be discovered.

**Headers**

```
Authorization: Bearer <access token>
Content-Type: application/json
```

**Trying it by hand** — Swagger UI is at `/docs` (self-hosted, so it works behind a firewall that
blocks CDNs). The eleven endpoints are grouped under **review** and each is named by its R-number, so
the list reads in the order of this document. Sign in with `POST /api/v1/auth/signin`, paste the
`access_token` into **Authorize**, then use Try-it-out. Take a `slot_key` from an R1 response
rather than typing one — Swagger URL-encodes it for you.

**Sample bodies** for `POST /projects` and `POST /projects/{id}/jobs`, on SampleCppProject, are in
`engine/config/` (set `repo_url` to a git copy of the sample and `commit_sha` to a commit in it):

| pair | runs | use it to try |
|---|---|---|
| `api_create_project.sample_full.example.json` + `api_start_job.sample_full.example.json` | group `Full`, the shipped defaults | every kind but `behaviourDescription`. Only `opsAdd`/`opsSub` are published in this scope, so most function slots show `shownIn: []` |
| `api_create_project.sample_behaviour.example.json` + `api_start_job.sample_behaviour.example.json` | group `Layer1.My Sample`, one behaviour diagram per external caller (`views.sequenceDiagrams.filterMode: all_callers`) | `behaviourDescription` (R6): 18 rows. The default filter draws none on the sample |

**To run the whole contract against a server** — onboard, generate, every correction, every
read, undo, the mistakes, the re-export and the Word file — use `tools/review_api_test/` (its
README). It takes these two bodies from its config and every id from the server's answers.

A missing or non-access token is **401**
(`{"detail": {"code": "UNAUTHENTICATED", "message": "…", "status": 401}}`).

**A sign-in lasts 8 hours** by default; after that every call answers 401 `"Signature has
expired"` and Swagger needs a fresh token from `/auth/signin`. The server sets it with
`auth.accessTokenMinutes` in `engine/config/config.local.json`. The web app renews on its own with
the refresh token, so a UI only needs to handle a 401 once it has tried that.

**Timestamps** are ISO-8601 UTC strings (`"2026-09-18T09:14:22Z"`) or `null`. **`null` vs absent:**
every field documented below is always present in a 200 response; optional means it may be `null`,
never missing.

---

## 5. Shared objects

### `Slot`

**One slot, in the same shape from every route** (`REQ-API-09`): R1 (in a list), R2 (bare), R3, R4
and R6 (with what the save did, below), R7 and R8 (each node), R11 (each row, with listing fields).
Read these names whatever the kind or the route.

| field | type | notes |
|---|---|---|
| `slotKind` | string | one of §1 |
| `slotKey` | string | send this back verbatim; never build one (§2) |
| `text` | string | **what the document prints now**, read from where the document reads it. `""` when the slot is empty — or when it is no longer in this version and only an orphaned correction remains |
| `llmText` | string \| null | **what the LLM wrote** for this slot: the original that a correction in force replaced; otherwise the same as `text`. `null` only when the LLM wrote nothing — the slot was empty before its first correction |
| `humanText` | string \| null | the reviewer's words; `null` when never corrected. An orphan keeps its words here |
| `isOverridden` | boolean | a correction is **in force**: the document prints `humanText` |
| `isOrphaned` | boolean | a correction exists but was written for code that has since changed, so it is **not** printed. The record is **kept** (`REQ-ID-03`) — show it greyed, as "your correction no longer applies", never as current wording |
| `canUndo` | boolean | R4 would change the text: a correction in force, an original to go back to, and the two differ. **Show Undo exactly when this is `true`** |
| `updatedBy` | string \| null | who last saved the correction (user id); `null` when none |
| `updatedAt` | string \| null | when, ISO-8601 UTC |

The states a slot can be in:

| state | `text` | `llmText` | `humanText` | `isOverridden` | `isOrphaned` | `canUndo` |
|---|---|---|---|---|---|---|
| never corrected | the LLM's | = `text` | `null` | `false` | `false` | `false` |
| corrected | the human's | the original | the human's | `true` | `false` | `true` |
| undone (R4) | the LLM's | the original | = `llmText` | `true` | `false` | `false` |
| orphaned | the LLM's, fresh for the new code | = `text` | the human's, for the old code | `false` | `true` | `false` |

An undone slot keeps its record (`REQ-API-04`), so it still appears in R1. An edit over an orphan
starts a new correction (`firstEdit: true`) whose original is the orphan's `text`.

**Where the key has parts, the slot carries them** — so nothing is ever taken apart on the client:

| kind | also carries |
|---|---|
| `nodeLabel` | `flowchartId`, `nodeId` |
| `behaviourDescription` | `functionId`, `externalCallerId` (what R6 takes), and `bullets` — `text` split into its lines, one bullet per line. The text fields hold the bullets joined by `\n` |

```json
{
  "slotKind": "description",
  "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initialises the GPIO driver and clears pending interrupts.",
  "llmText": "Initializes the module.",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "isOverridden": true,
  "isOrphaned": false,
  "canUndo": true,
  "updatedBy": "u-17",
  "updatedAt": "2026-09-18T09:14:22Z"
}
```

### What a save did

R3, R4 and R6 answer with the `Slot` **plus** these four; R8 with the four on **each** saved node:

| field | type | notes |
|---|---|---|
| `previousText` | string \| null | what the document printed **before** this save; `null` when it printed nothing. Two reviewers saving the same slot: the later save wins (`REQ-API-07`), and its `previousText` is the earlier one's words — show it as "you replaced …" |
| `firstEdit` | boolean | the save **started** a correction — none was in force (no correction, or only an orphaned one) |
| `viewsDerived` | string[] | the SWE.4 views this request re-derived — see R3. `[]` when none |
| `queuedForRegeneration` | `QueuedSlot[]` | what this save made out of date (`REQ-CS-01`). Always present: `[]` for the kinds that cascade to nothing (node labels, behaviour rows, names, unit and struct descriptions) |

### `QueuedSlot`

What a correction invalidated — text that was generated **from** the text just replaced
(`REQ-CS-01`). Appears in every save's answer and, with more detail, in R10.

| field | type | notes |
|---|---|---|
| `slotKind` | string | |
| `slotKey` | string | |

---

## 6. R1 — list the corrections in a version

`GET /projects/{projectId}/versions/{versionId}/overrides`

**This is an overlay, not a slot enumeration.** A version holds roughly **57,000** slots, so listing
them would rebuild the document you already fetched from `/components`, `/functions` and
`/flowcharts`. Fetch this once, index it by `slotKey`, and merge as you render. A version nobody has
corrected returns an empty list.

**Query parameters**

| name | type | required | default | notes |
|---|---|---|---|---|
| `slot_kind` | string | no | — | filter to one kind; also narrows `total` |
| `limit` | integer | no | `200` | 1–1000; outside that range is 422 |
| `offset` | integer | no | `0` | ≥ 0 |

**Response 200**

| field | type | notes |
|---|---|---|
| `overrides` | `Slot[]` | §5 — every slot with a correction, orphans included, newest first |
| `total` | integer | matching rows **before** paging, honouring `slot_kind` |
| `limit` | integer | echoed |
| `offset` | integer | echoed |

```json
{
  "overrides": [
    {
      "slotKind": "description",
      "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
      "text": "Initialises the GPIO driver and clears pending interrupts.",
      "llmText": "Initializes the module.",
      "humanText": "Initialises the GPIO driver and clears pending interrupts.",
      "isOverridden": true,
      "isOrphaned": false,
      "canUndo": true,
      "updatedBy": "u-17",
      "updatedAt": "2026-09-18T09:14:22Z"
    }
  ],
  "total": 1,
  "limit": 200,
  "offset": 0
}
```

**Errors** — 401, 403, 503, and **404** when `versionId` is not one of this project's versions (§3).
An empty list means a real version with no corrections.

---

## 7. R2 — read one slot

`GET /projects/{projectId}/versions/{versionId}/overrides/slot`

**Query parameters**

| name | type | required | notes |
|---|---|---|---|
| `slot_kind` | string | **yes** | |
| `slot_key` | string | **yes** | URL-encoded |

```
GET /api/v1/projects/ftl-a1b2c3/versions/v-7/overrides/slot
    ?slot_kind=description&slot_key=Gpio%7CGpioDrv%7CGpio_Init%7Cvoid
```

Any slot of the version, **corrected or not** (`REQ-API-02`): use it to open an editor on one slot,
or to confirm a save landed.

**Response 200** — a bare `Slot` (§5), not wrapped. A slot nobody corrected answers with
`isOverridden: false` and `humanText: null` — until 2026-09-29 that was a 404.

**Errors**

| code | when |
|---|---|
| 404 | the slot is not in this version and has no correction — take the key from R11, or from R7 for a node label |
| 400 | malformed `slot_key` for the kind — e.g. a flowchart id given for `nodeLabel`. `detail` says what the key should be and where to copy it from (§2) |
| 401 / 403 / 503 | see §16 |

---

## 8. R3 — correct one slot

`PUT /projects/{projectId}/versions/{versionId}/overrides/slot`

For the five model-backed kinds. `nodeLabel` → R8, `behaviourDescription` → R6.

**Request body**

| field | type | required | notes |
|---|---|---|---|
| `slot_kind` | string | **yes** | one of §1 |
| `slot_key` | string | **yes** | from a previous response |
| `text` | string | **yes** | the corrected wording. Empty or whitespace-only is **422** (`REQ-ST-06`) |

```json
{
  "slot_kind": "description",
  "slot_key": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initialises the GPIO driver and clears pending interrupts."
}
```

**Response 200** — the `Slot` as it now is, and what the save did (§5): `previousText`,
`firstEdit`, `viewsDerived` (the SWE.4 views this save re-derived — see the note below; `[]` for a
version with no SWE.4 output, which is every web-app version), `queuedForRegeneration`.

```json
{
  "slotKind": "description",
  "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initialises the GPIO driver and clears pending interrupts.",
  "llmText": "Initializes the module.",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "isOverridden": true,
  "isOrphaned": false,
  "canUndo": true,
  "updatedBy": "u-17",
  "updatedAt": "2026-09-18T09:14:22Z",
  "previousText": "Initializes the module.",
  "firstEdit": true,
  "viewsDerived": [],
  "queuedForRegeneration": [
    { "slotKind": "unitDescription", "slotKey": "Layer2.Gpio|GpioDrv" },
    { "slotKind": "description", "slotKey": "Layer1.App|AppMain|App_Start|void" }
  ]
}
```

**`viewsDerived` names only views this request rebuilt.** A `description` correction reaches the
SWE.4 test spec that copies it, so on a version with SWE.4 output — one generated from the CLI — the
save re-derives the component's specs and the UT export built from them, from the stored rows
(`REQ-CS-04`), and returns `["testSpecs", "utExport"]`. Those views are then stamped as derived, and
only those: the SWE.3 rows a save changes are patched in place, not re-derived, so R9 keeps
reporting the staleness the SWE.3 export depends on. `[]` on a version with no SWE.4 output, or when
the specs cannot be rebuilt as they were built (output from before 2026-09-29) — the export guard
then keeps SWE.4 stale until Phase 3 runs.

**Show `queuedForRegeneration`.** The reviewer is about to see wording change in places they did not
touch, on the next run. An unannounced change reads as a bug.

**Errors**

| code | when |
|---|---|
| 404 | the slot does not resolve in this version |
| 409 | a run is regenerating this version and replaced the model while the save was writing it. Nothing was saved — save again once the run has finished |
| 422 | empty or whitespace-only `text`; a NUL character (`\u0000`) in `text` or `slot_key`; or a `snake_case` field is missing |
| 501 | `slot_kind` is `nodeLabel` or `behaviourDescription` — use R8 / R6 |
| 401 / 403 / 500 / 503 | see §16 |

---

## 9. R4 — undo one slot

`DELETE /projects/{projectId}/versions/{versionId}/overrides/slot`

Restores the LLM's original wording (`REQ-API-04`).

**Undo is an ordinary edit whose text happens to be the original**, so **the record survives** with
both texts and its full history. It is not a delete, and the slot still appears in R1 afterwards —
with `humanText` equal to `llmText`, and `canUndo: false`.

**Query parameters** — identical to R2: `slot_kind`, `slot_key`, both required.

**Response 200** — like a save: the `Slot` as it now is, and what the undo did (§5); `previousText`
is the correction it took back. For a `nodeLabel` also `renderPending`, `renderJobs` and the
rebuilt `dot`, as R8.

```json
{
  "slotKind": "description",
  "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initializes the module.",
  "llmText": "Initializes the module.",
  "humanText": "Initializes the module.",
  "isOverridden": true,
  "isOrphaned": false,
  "canUndo": false,
  "updatedBy": "u-17",
  "updatedAt": "2026-09-18T10:02:41Z",
  "previousText": "Initialises the GPIO driver and clears pending interrupts.",
  "firstEdit": false,
  "viewsDerived": [],
  "queuedForRegeneration": []
}
```

**Errors**

| code | when |
|---|---|
| 409 | no original to restore — the slot was empty before the first correction, so `llmText` is `null` |
| 409 | the correction is **orphaned** (`isOrphaned: true`): it was written for code that has since changed, it is not applied, and the document already shows the LLM's text for the current code — there is nothing to undo; a new edit (R3, R6, R8) starts a new correction |
| 404 | the slot does not resolve in this version |
| 400 | malformed `slot_key` for the kind (§2) |
| 401 / 403 / 500 / 503 | see §16 |

Both 409s are what `canUndo: false` already says: show Undo only where it is `true`.

**R4 undoes every kind**, not just the ones R3 saves: a `nodeLabel` (one node at a time — take its
`slotKey` from R7; the flowchart is redrawn as for R8) and a `behaviourDescription` (the whole bullet
list goes back).

---

## 10. R5 — one slot's history

`GET /projects/{projectId}/versions/{versionId}/overrides/history`

The retained edits of one slot, **oldest first**, bounded by `llm.overrideHistoryDepth`
(`REQ-ST-04`).

The LLM original is **not** in here — it is `llmText` on the override itself, which is what makes
"the original is never evicted by the cap" structural rather than a rule someone must remember.

**R1 or R5?** R1 answers "what has been corrected in this version" — one row per corrected slot,
showing its current text. R5 answers "how did THIS slot change" — every edit, oldest first. Correct a
description three times and R1 shows one row (the last text); R5 for that slot shows three.

**Query parameters** — identical to R2: `slot_kind`, `slot_key`, both required.

**Response 200**

| field | type | notes |
|---|---|---|
| `history` | object[] | empty array for a slot that was never corrected — **not** 404. A MALFORMED key is a 400 instead (§2), so an empty list always means "well-formed, never corrected" |
| `history[].seq` | integer | 1-based, ascending |
| `history[].humanText` | string | |
| `history[].updatedBy` | string \| null | |
| `history[].updatedAt` | string \| null | ISO-8601 UTC |

```json
{
  "history": [
    { "seq": 1, "humanText": "Initialises the GPIO driver.",
      "updatedBy": "u-17", "updatedAt": "2026-09-18T09:14:22Z" },
    { "seq": 2, "humanText": "Initialises the GPIO driver and clears pending interrupts.",
      "updatedBy": "u-17", "updatedAt": "2026-09-18T09:31:05Z" }
  ]
}
```

---

## 11. R6 — correct one Dynamic Behaviour row

`PUT /projects/{projectId}/versions/{versionId}/overrides/behaviour`

The row is a **list** of bullets, one per call arrow, edited as one block (`REQ-ED-02`).

**Request body**

| field | type | required | notes |
|---|---|---|---|
| `function_id` | string | **yes** | entity key of the function the row belongs to |
| `external_caller_id` | string | **yes** | entity key of the **caller** |
| `bullets` | string[] | **yes** | the whole list. Empty array is **422**; each bullet is collapsed onto one line |

```json
{
  "function_id": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "external_caller_id": "Layer1.App|AppMain|App_Start|void",
  "bullets": [
    "App_Start calls Gpio_Init to bring the port up",
    "Gpio_Init returns the port state"
  ]
}
```

**Both ids are entity keys.** Not the row's `externalUnitFunction` display label — that is
`"<unit> - <name>"`, and two different callers can share one, so a correction addressed by it would
land on the wrong row (`REQ-ID-01`). Copy both from the row R11 returns: `functionId` and
`externalCallerId`.

**Response 200** — the row as a `Slot` (§5), with `functionId`, `externalCallerId` and
`bullets` (as stored, each collapsed to one line; the text fields hold them joined by `\n`), and
what the save did. `viewsDerived` is always `[]` (the row is patched in place, and no SWE.4 view
prints this text), and so is `queuedForRegeneration`.

```json
{
  "slotKind": "behaviourDescription",
  "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void\u0001Layer1.App|AppMain|App_Start|void",
  "text": "App_Start calls Gpio_Init to bring the port up\nGpio_Init returns the port state",
  "llmText": "App_Start calls Gpio_Init\nGpio_Init returns",
  "humanText": "App_Start calls Gpio_Init to bring the port up\nGpio_Init returns the port state",
  "isOverridden": true,
  "isOrphaned": false,
  "canUndo": true,
  "updatedBy": "u-17",
  "updatedAt": "2026-09-18T10:05:12Z",
  "functionId": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "externalCallerId": "Layer1.App|AppMain|App_Start|void",
  "bullets": [
    "App_Start calls Gpio_Init to bring the port up",
    "Gpio_Init returns the port state"
  ],
  "previousText": "App_Start calls Gpio_Init\nGpio_Init returns",
  "firstEdit": true,
  "viewsDerived": [],
  "queuedForRegeneration": []
}
```

**No image is re-rendered.** The description is not in the diagram — its arrows are labelled with
the callee's name — so there is nothing to redraw and no render job.

**Errors**

| code | when |
|---|---|
| 404 | no such behaviour row in this version (wrong `function_id` or `external_caller_id`) |
| 409 | the stored behaviour output cannot be read — re-derive the version |
| 422 | `bullets` empty, or a bullet that is blank; a NUL character (`\u0000`) in a bullet, `function_id` or `external_caller_id` |
| 401 / 403 / 500 / 503 | see §16 |

---

## 12. R7 — read a flowchart's labels

`GET /projects/{projectId}/versions/{versionId}/flowcharts/labels?flowchart_id=<flowchartId>`

A flowchart **is one function's control-flow graph**, so it is named by that function's entity key
— `flowchartId` in R11 (`REQ-ID-04`). One request opens the editor; one R8 saves it.

**Query parameters**

| name | type | required | notes |
|---|---|---|---|
| `flowchart_id` | string | **yes** | the function's id, e.g. `Layer2.Gpio\|GpioDrv\|Gpio_Init\|void`. URL-encoded like any query value: `\|` → `%7C`, a space → `%20`, and a `+` (`operator+`) → `%2B`, which an unencoded query would read as a space |

**Response 200**

| field | type | notes |
|---|---|---|
| `flowchartId` | string | the flowchart id, as sent |
| `functionName` | string \| null | display name, e.g. `Gpio_Init` |
| `labels` | `Slot[]` | **every** node, in graph order — corrected or not; each a `Slot` (§5) with its `flowchartId` and `nodeId` |
| `graphAvailable` | boolean | `false` when the stored output carries no graph; `labels` is then `[]` |
| `note` | string | present only when `graphAvailable` is `false`, saying why |
| `dot` | string | the flowchart as **Graphviz DOT**, read from the database — draw it (§3a, *Drawing a flowchart*). R8 rebuilds it in the same request, so after a save it already carries the new labels; the PNG does not. `""` when none is stored |
| `labels[].nodeId` | string | e.g. `n7`. Use as the key in R8 |
| `labels[].slotKey` | string | **this node's slot key** — send it to R4 (undo) or R5 (history). Never assemble one yourself (§2) |
| `labels[].text` | string | **what the picture carries now** — the stored label |
| `labels[]` … | | and the rest of the `Slot` fields — `llmText`, `humanText`, `isOverridden`, `isOrphaned`, `canUndo`, `updatedBy`, `updatedAt` (§5) |

```json
{
  "flowchartId": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "functionName": "Gpio_Init",
  "labels": [
    { "slotKind": "nodeLabel", "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void\u0001n0",
      "flowchartId": "Layer2.Gpio|GpioDrv|Gpio_Init|void", "nodeId": "n0",
      "text": "Start", "llmText": "Start", "humanText": null,
      "isOverridden": false, "isOrphaned": false, "canUndo": false,
      "updatedBy": null, "updatedAt": null },
    { "slotKind": "nodeLabel", "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void\u0001n7",
      "flowchartId": "Layer2.Gpio|GpioDrv|Gpio_Init|void", "nodeId": "n7",
      "text": "Check the write-protect flag", "llmText": "Check flag",
      "humanText": "Check the write-protect flag",
      "isOverridden": true, "isOrphaned": false, "canUndo": true,
      "updatedBy": "u-17", "updatedAt": "2026-09-18T10:02:41Z" }
  ],
  "graphAvailable": true,
  "dot": "digraph G {\n  rankdir=TB;\n  …\n  n7 [shape=box, label=\"Check the write-protect flag\"];\n  …\n}"
}
```

**Errors**

| code | when |
|---|---|
| 400 | `flowchart_id` is empty, or is one node's `slotKey` — the flowchart id is the part before the separator, and `detail` names it |
| 404 | no flowchart stored for that function in this version |
| 422 | `flowchart_id` missing |
| 401 / 403 / 503 | see §16 |

**An empty `labels` list is not always an empty flowchart.** `cfg` has only been stored since
2026-09-01, so a version generated before that carries the picture and the DOT but not the graph
they were built from. Its labels cannot be listed or corrected until the version is re-derived
(`reexport --from-phase 3`, which rebuilds the CFG from the model — no re-parse). `graphAvailable`
tells the two apart, and R8 on such a flowchart answers **409**, not 404: the flowchart is there,
its graph is not, and those are different things to fix.

---

## 13. R8 — correct a flowchart, in one call

`PUT /projects/{projectId}/versions/{versionId}/flowcharts/labels`

**Request body**

| field | type | required | notes |
|---|---|---|---|
| `flowchart_id` | string | **yes** | the function's id — `flowchartId` from R11 or R7 |
| `labels` | object | **yes** | `{nodeId: text}` — **only the labels the reviewer changed** |

```json
{ "flowchart_id": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "labels": { "n7": "Check the write-protect flag", "n9": "Increment the retry count" } }
```

Three rules (`REQ-API-08`):

1. **Send only what changed.** Not the whole flowchart. A stale copy of an untouched label would
   overwrite a correction somebody else made to it seconds earlier, and the server cannot tell that
   from a deliberate revert.
2. **All or nothing.** If any label is rejected — empty text, or a node that no longer exists —
   nothing is written and the response names the node.
3. **One re-render per call**, however many labels it carried.

**Response 200**

| field | type | notes |
|---|---|---|
| `flowchartId` | string | the flowchart id, as sent |
| `labels` | object[] | **each saved node as it now is**, in request order: a `Slot` (§5, with `flowchartId` and `nodeId`) and what the save did to it — `previousText`, `firstEdit`, `viewsDerived`, `queuedForRegeneration` |
| `viewsDerived` | string[] | `["testSpecs", "utExport"]` when the version has SWE.4 output: a label is a Test Step ("Check whether <label>"), and a return's label the expected return of a UT case, so the component's specs are re-derived in this request — see §8. `[]` otherwise |
| `queuedForRegeneration` | `QueuedSlot[]` | always `[]`: a node label is built from the source, and nothing is built from it (`REQ-CS-01`) |
| `renderPending` | boolean | `true` while the picture is **owed** |
| `renderJobs` | integer[] | job ids raised by this call |
| `dot` | string | the flowchart's Graphviz DOT, rebuilt by this call — draw it (§3a) and the correction shows at once |

```json
{
  "flowchartId": "Layer2.Gpio|GpioDrv|Gpio_Init|void",
  "labels": [
    { "slotKind": "nodeLabel", "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void\u0001n7",
      "flowchartId": "Layer2.Gpio|GpioDrv|Gpio_Init|void", "nodeId": "n7",
      "text": "Check the write-protect flag", "llmText": "Check flag",
      "humanText": "Check the write-protect flag",
      "isOverridden": true, "isOrphaned": false, "canUndo": true,
      "updatedBy": "u-17", "updatedAt": "2026-09-18T10:02:41Z",
      "previousText": "Check flag", "firstEdit": true,
      "viewsDerived": [], "queuedForRegeneration": [] }
  ],
  "viewsDerived": [],
  "queuedForRegeneration": [],
  "renderPending": true,
  "renderJobs": [412],
  "dot": "digraph G {\n  …\n  n7 [shape=box, label=\"Check the write-protect flag\"];\n  …\n}"
}
```

Until 2026-09-29 this answered only `applied` and `firstEdits` — node ids, with no text — and
`slotShape`, an internal fingerprint of the graph that no client needs.

**`renderPending`** — the text is corrected everywhere it is read from the database immediately, but
the **picture** may not be. It is `true` whenever a render job was raised and **not finished inside
this call**, which on a host with no output tree is always. Note that the stored JSON and DOT *are*
rebuilt either way: "the graph was rebuilt" and "the image was drawn" are different facts, and this
flag reports the second. It always agrees with R9's `pendingRenders`. A picture not drawn here stays
pending, and the next run or re-export on a host with the tree draws it. **A UI that draws the `dot`
shows the corrected flowchart straight after the save** — this flag is only about the PNG the Word
file carries. Either way the export consults the same rows, so a document cannot go out
carrying new text and an old image (`REQ-IM-02`) — R9 reports it as `pendingRenders`.

The server still records, with each label, which graph it was written against, so the same text
is not reused later against a renumbered one: node ids are **positions**, not identities
(`REQ-ID-02`). Nothing a client sends or reads.

Each label is stored as **its own record** with its own original and history, even though the API is
per flowchart. The two granularities are deliberately different (`REQ-ST-07`) — which is why R2, R4
and R5 still work on a single `nodeLabel` slot key.

**Errors**

| code | when |
|---|---|
| 400 | `flowchart_id` is empty, or is one node's `slotKey` — `detail` names the flowchart id |
| 404 | the flowchart, or a node id named in `labels`, does not exist — `detail` names it |
| 409 | the flowchart has no stored graph (see R7). Re-derive the version first |
| 422 | a label is empty or whitespace-only; a NUL character (`\u0000`) in a label, a node id or `flowchart_id`; or `flowchart_id` or `labels` missing |
| 401 / 403 / 500 / 503 | see §16 |

---

## 14. R9 — export readiness

`GET /projects/{projectId}/versions/{versionId}/export-readiness`

Whether exporting now would ship text a correction has already replaced (`REQ-AP-04`). **Call it
before offering a download.** It asks about the SWE.3 document — the one the web app exports — so
only the views SWE.3 prints count: a label on a flowchart SWE.3 does not embed (`views.flowcharts`
off, the default) does not make it stale. A SWE.4 document of a CLI-generated version is exported
from the CLI, which asks its own question (`analyzer.py reexport --doc-type swe4`).

No parameters.

**Response 200**

| field | type | notes |
|---|---|---|
| `stale` | boolean | `true` ⇒ the views need re-deriving before a download is honest |
| `reason` | string | short, always present: `"up to date"`, `"no corrections"`, or the reason it is stale |
| `explanation` | string | one line fit to show as-is, including any failed renders |
| `overrideCount` | integer | corrections in force in this version. Orphans are not counted and never make a version stale: they are not printed |
| `pendingRenders` | integer | pictures still owed — **any of these makes it stale** |
| `failedRenders` | integer | renders that gave up — reported, **does not block** |
| `newestOverrideAt` | string \| null | ISO-8601 UTC |
| `oldestDerivationAt` | string \| null | ISO-8601 UTC; `null` when the views were never derived |
| `reexport` | object \| null | the version's newest **re-export job**, `null` when it was never re-exported. `status` `queued` or `running` means one is under way: follow its `jobId` instead of starting another (§3a Flow 6) |
| `reexport.jobId` | string | follow it with `GET /jobs/{jobId}` or `GET /jobs/{jobId}/events` |
| `reexport.status` | string | `queued` \| `running` \| `complete` \| `failed` \| `cancelled` |
| `reexport.startedAt` / `completedAt` | string \| null | ISO-8601 UTC |
| `reexport.errorMessage` | string \| null | why it failed |

```json
{
  "stale": true,
  "reason": "a correction is newer than the derived output",
  "explanation": "a correction is newer than the derived output (3 correction(s) in this version)",
  "overrideCount": 3,
  "pendingRenders": 1,
  "failedRenders": 0,
  "newestOverrideAt": "2026-09-18T09:14:22Z",
  "oldestDerivationAt": "2026-09-18T08:02:10Z",
  "reexport": { "jobId": "job3c9e1f20", "status": "running",
                "startedAt": "2026-09-18T09:20:03Z", "completedAt": null, "errorMessage": null }
}
```

**What the UI should do with `stale: true`** — nothing special. Re-export through the normal
endpoint: the server now **re-derives first** rather than refusing, so a download taken afterwards
is correct. R9 is for telling the reviewer *why* this one will take longer than usual. (The CLI
refuses instead and prints `reexport --from-phase 3`; the difference is deliberate — see
[DESIGN §13.3](../design/REVIEW_UPDATE_DESIGN.md#133-the-export-guard-lives-in-runpy-not-only-in-analyzerpy).)

**`pendingRenders` also makes a version stale** (`REQ-IM-02`), even when every sentence is current:
an export now would carry the new wording and the old picture — when the SWE.3 document embeds the
flowcharts at all.

**`failedRenders` does not block.** A render that gave up cannot be waited for, and blocking would
make one unrenderable flowchart permanently unexportable. It appears in `explanation` instead, so a
document goes out with somebody knowing the image is out of date rather than nobody.

### How the Word document gets the corrections

**Nothing exports automatically.** A save (R3/R6/R8) updates the database in the same request and
never starts an export. The Word file changes only when someone runs a re-export:

```
POST /api/v1/projects/{projectId}/versions/{versionId}/reexport   (project admin; 202, runs in the background)
```

A re-export is **a job of its own** (`mode: "reexport"`): follow it by the `job_id` it answers with,
one at a time per version (§3a Flow 6). The older `POST /projects/{projectId}/jobs/{jobId}/reexport`
does the same for the version that job produced, and answers with the new job's id.

The server decides how much to rebuild — R9's question, asked for you: when the version is stale it
re-derives the views first (Phase 3: corrected text into the view rows, owed flowchart pictures
drawn), then exports; otherwise it exports only.

**Download serves the stored file as it is.** `GET .../documents/{docId}/download` neither rebuilds
nor checks staleness, so a download taken after corrections and before a re-export is the OLD
document. That is what R9 is for in the UI:

| R9 says | the UI shows |
|---|---|
| `stale: false` | the normal Download button |
| `stale: true` | "N corrections are not in the Word file yet" + a Re-export action, and Download marked as the previous version |
| `pendingRenders > 0` | "N flowchart pictures will be redrawn by the re-export" |
| `failedRenders > 0` | a warning that those pictures are out of date |

### When a correction becomes visible

Every kind is saved to the database in the request. What the document PAGE (`.../render`) shows
depends on where the page reads that kind from — it is re-read on every page load, never pushed, so
the UI must refetch after a save:

| kind | on the page after a save | in the Word file |
|---|---|---|
| `description` | next page load — the stored interface table is patched | after re-export |
| `behaviourInputName`, `behaviourOutputName` | next page load — read from the model | after re-export |
| `behaviourDescription` | next page load — the stored behaviour row is written | after re-export |
| `nodeLabel` | next page load **when the UI draws the DOT** (§3a, *Drawing a flowchart*): the payload's DOT is read from the database, and R8 rebuilt it. The PNG (`image_url`) changes only after the owed render (next re-export), so a page that shows the PNG shows the old label until then. Today's web-app does, and prints the DOT as text only when no PNG exists | after re-export |
| `unitDescription` | next page load — the Component/Unit table reads the stored description from the model, as the Word file does | after re-export |
| `structDescription` | **after re-export** — the unit header table on the page is the Phase-3 view's output (`unit_headers.json`), and the re-export rebuilds it | after re-export |

**A correction to a text the document does not show is saved and never seen — and R11 says which
those are.** A function gets an interface row — and a flowchart, and behaviour names in its
flowchart table — only when a unit OTHER than its own calls it, among the files this run parsed
(develop 470d15c: a `PUBLIC` marking no longer publishes by itself). A run scoped to one group
cannot see its callers in other groups, so most of its functions are private and absent from the
SWE.3 document. Every R11 row carries `shownIn` (§15a): the units whose document prints the text,
`[]` when none does. Show or hide those rows accordingly.

---

## 15. R10 — the regeneration queue

`GET /projects/{projectId}/versions/{versionId}/regeneration-queue`

Slots whose LLM text was built from wording a human has since corrected, and which therefore need
regenerating (`REQ-CS-01`). The same facts R3 returns as `queuedForRegeneration`, for the whole
version.

No parameters.

**Response 200**

| field | type | notes |
|---|---|---|
| `pending` | object[] | |
| `pending[].slotKind` | string | the slot that needs rewriting |
| `pending[].slotKey` | string | |
| `pending[].reason` | string | plain-language, safe to show |
| `pending[].causedBy` | `QueuedSlot` | the correction that invalidated it |
| `pending[].requestedAt` | string \| null | ISO-8601 UTC |
| `total` | integer | `pending.length`; not paged |

```json
{
  "pending": [
    {
      "slotKind": "description",
      "slotKey": "Layer1.App|AppMain|App_Start|void",
      "reason": "its description was written with this function as context",
      "causedBy": { "slotKind": "description", "slotKey": "Layer2.Gpio|GpioDrv|Gpio_Init|void" },
      "requestedAt": "2026-09-18T09:14:22Z"
    }
  ],
  "total": 1
}
```

They are **recorded, not regenerated** at save time, for reasons that were checked rather than
assumed: generating a description needs the function's **source**, which lives in the git checkout
and not in the model, and it is an LLM call — a saved sentence must not take minutes.

Nor can it be skipped. The description cache is keyed on the callee's *source* plus its dependency
hashes, and correcting a *description* changes neither, so the next run would hit the cache and the
caller would keep its stale wording for ever.

A slot a human has already corrected never appears here (`REQ-CS-03`) — their text is not
regenerated over — and correcting a slot that is listed here takes it off the list. The cascade is
**one level** (`REQ-CS-02`): a caller's own callers are not invalidated, because a transitive cascade
is unbounded in a deep call graph.

**When an entry leaves the list.** A description or unit description when a run's Phase 2 wrote it
afresh; a behaviour row when a run's behaviour view rebuilt it — not a SWE.4-only run, and not a run
over another component. A run with no LLM, or with descriptions switched off, pays nothing: the
entries stay, and the slots keep their previous wording until a run with an LLM rewrites them. A
version generated from this one owes the same entries for what it still contains.

---

## 15a. R11 — what can be edited

`GET /projects/{projectId}/versions/{versionId}/slots`

R1 lists what **has been** corrected, and is empty until somebody corrects something. This lists
what is **there to correct** — so a `slotKey`, which you may never invent (§2), can be read from a
response instead of dug out of stored view output.

**Query parameters**

| name | type | required | default | notes |
|---|---|---|---|---|
| `slot_kind` | string | **yes** | — | one of §1 |
| `unit` | string | no | — | narrow to one unit, by its name (`Core`). For `structDescription`: the records that unit's header table shows (see `shownIn`) |
| `component` | string | no | — | narrow to one component, by its **layer-qualified id** (`Layer1.Sample-Core`) — the same string as a document's `group` in `GET /documents`. The config's spelling (`Layer1.Sample Core`) and any letter case find the same component. For `structDescription`, as for `unit` |
| `limit` | integer | no | `200` | 1–1000 |
| `offset` | integer | no | `0` | ≥ 0 |

**Response 200** — `{"slotKind", "slots", "total", "limit", "offset"}`. `total` is the count
**before** paging.

A row, for the six per-slot kinds: a `Slot` (§5) — **send its `slotKey` to R2–R6 verbatim** — and
where it is listed:

| field | type | notes |
|---|---|---|
| `label` | string | a display name — the function, unit or type |
| `component` / `unit` | string \| null | for `structDescription`: the first unit that shows it, or `null` when no document of this version does |
| `shownIn` | string[] | **every kind**: the unit keys (`Layer1.Cross\|Dispatch`) whose SWE.3 document prints this text, read from the version's stored views. `[]` = no document of this version shows it — the save works and nobody will see it. `description`: the units whose interface table lists the function or global. `behaviourInputName` / `behaviourOutputName`: those units where the function's flowchart was drawn, plus the units whose Dynamic Behaviour rows show it. `unitDescription`: the unit, when it has a section. `structDescription`: the units whose unit header table shows it. `behaviourDescription`: its own unit. A hidden function is shown nowhere |
| `kindOfType` | string | `structDescription` only: `struct`, `class` or `union` |
| `artifact` | string | where a model-backed slot lives: `functions`, `globalVariables`, `units` or `dataDictionary` |

`text` may be `""` — a slot can be legitimately empty and is still editable. A behaviour row
carries `functionId` and `externalCallerId` (the two ids R6 takes) and `bullets`, like every
`behaviourDescription` slot (§5).

```json
{
  "slotKind": "description",
  "slots": [
    { "slotKind": "description", "slotKey": "Layer1.Sample-Core|Core|coreAdd|int,int",
      "text": "Adds two integers.", "llmText": "Adds two integers.", "humanText": null,
      "isOverridden": false, "isOrphaned": false, "canUndo": false,
      "updatedBy": null, "updatedAt": null,
      "label": "coreAdd", "component": "Layer1.Sample-Core", "unit": "Core",
      "artifact": "functions", "shownIn": ["Layer1.Sample-Core|Core"] }
  ],
  "total": 158, "limit": 200, "offset": 0
}
```

**`nodeLabel` is listed per FLOWCHART, not per node.** A version holds ~42,000 node labels; one row
each would be hundreds of pages of something nobody reads linearly. A flowchart is one function's
graph, so each row carries the `flowchartId` **R7** and **R8** take:

```json
{ "slotKind": "nodeLabel",
  "flowchartId": "Layer1.Sample-Core|Core|coreAdd|int,int",
  "functionName": "coreAdd", "component": "Layer1.Sample-Core", "unit": "Core",
  "nodeCount": 7, "overriddenCount": 1, "shownIn": ["Layer1.Sample-Core|Core"] }
```

A flowchart's `shownIn` is where its flowchart table is printed: a function the interface table
lists. A flowchart is stored for every function, published or not.

`overriddenCount` excludes orphans: they are kept but not applied, so counting them would promise
an edit the document does not carry.

**`structDescription` lists the structs, classes and unions a document can describe** — each one
with a row of its own in the unit header table, or named by a typedef row there. Not primitives,
`#define`s, enums, typedefs or records declared inside a class: their rows show a value or nothing,
so a correction would be saved and never seen (R3 refuses them with 404). The key is the type's
data-dictionary key, so it names no unit; `shownIn` says where the description is printed, read
from the version's stored unit header rows, and `unit` / `component` filter on it:

```json
{ "slotKind": "structDescription", "slotKey": "AddOperation",
  "text": "Adds two operands.", "llmText": "Adds two operands.", "humanText": null,
  "isOverridden": false, "isOrphaned": false, "canUndo": false,
  "updatedBy": null, "updatedAt": null,
  "label": "AddOperation", "kindOfType": "class", "component": "Layer1.Cross", "unit": "Dispatch",
  "shownIn": ["Layer1.Cross|Dispatch"], "artifact": "dataDictionary" }
```

**`text`, `humanText` and the flags** follow §5's states table. For a live correction `text` and
`humanText` are the same sentence — the save wrote it into the model. They differ for an
**orphan**, which is kept (`REQ-ID-03`) but never applied: its function's code changed, so the
document prints fresh LLM text while the row still holds words written for the old code.

**The text here is the text a save replaces.** It is read through the same resolver
`PUT …/overrides/slot` writes through, so the listing and the write cannot disagree about which
field a kind lives in.

**Errors**

| code | when |
|---|---|
| 400 | `unit` or `component` given for `structDescription` on a version whose unit header rows were derived before they named their type — they cannot say which unit shows what. Refused rather than answered empty; re-export the version, or list without a filter |
| 422 | `slot_kind` missing or not one of the seven |
| 401 / 403 / 503 | see §16 |

---

## 16. Errors and concurrency

Error bodies are `{"detail": "…"}`, except 401 (an object, §4) and 422 from schema validation
(pydantic's array).

| Code | When |
|---|---|
| 400 | malformed slot key, or one node's key sent as a flowchart id (R7, R8) |
| 401 | missing, malformed or non-access Bearer token |
| 403 | not a member of the project |
| 404 | a version that is not one of the project's (every endpoint; a tag sent instead of the id is answered with the id — §3), or an unknown slot, flowchart, or node named in a flowchart save |
| 409 | undo with no LLM original to restore, or of an orphaned correction; a flowchart with no stored graph; stored output that cannot be read; a save that met a run regenerating the version (nothing saved — save again once it has finished) |
| 422 | empty or whitespace-only text (`REQ-ST-06`); a NUL character (`\u0000`) anywhere in a save's body (R3, R6, R8) — PostgreSQL cannot store one, and `loc` names the field; or a request body/query field missing — **check `snake_case` first** (§4) |
| 500 | a fault on the server, not in the request. `detail` names only the kind of error; the server log has the rest. Nothing was changed |
| 501 | a slot kind with no save path on that endpoint (`nodeLabel`, `behaviourDescription` on R3) |
| 503 | no database configured — corrections live nowhere else, so the write is refused rather than dropped |

A **4xx is always about the request**: fix it before sending it again. A 500 is not — send the same
request again later, or report it.

Two people editing the same slot: **last write wins**, no edit lock and no conflict response
(`REQ-API-07`). Saves of one version are taken one at a time on the server — each is milliseconds —
so a second save waits rather than failing, and then applies on top of the first: both answer 200,
the document prints the later text, the history holds both, and the later answer's `previousText`
is the earlier reviewer's words. The earlier reviewer's screen shows their own text until it reads
the slot again — nothing is pushed. Sending only changed labels (§13) is what keeps that true *per
slot* when a whole flowchart is saved at once.

---

## 17. Not yet implemented

Honest gaps, so the UI does not plan around something that is not there.

- **Both queues are drained by a RUN, not by a timer.** A pending picture is drawn when a host with
  the output tree captures a version's output, and a queued regeneration is rebuilt by Phase 2
  (descriptions) or Phase 3 (behaviour rows). Between a correction and the next run,
  `pendingRenders` and R10 report what is still owed. Nothing runs on a schedule, so do not poll
  expecting these to clear on their own.
- **No cleanup endpoint** for orphaned corrections — deliberately, pending a decision; see
  [REVIEW_UPDATE_DESIGN Open items](../design/REVIEW_UPDATE_DESIGN.md#open-items).
- **No bulk or batch write** beyond R8's one flowchart. Correct slots one call at a time.
- **A corrected flowchart's PNG is redrawn by the next run or re-export**, not by the save — R8
  over HTTP has no output tree to draw into, so `renderPending` is `true`. Its DOT is rebuilt by the
  save: draw that (§3a) and the page is current at once.
- **The page payload carries no slot keys**, so "edit this sentence" on the page means finding the
  item in R11 (same unit, by `label` or `functionName`) and using its `slotKey`.

---

_End of document._
