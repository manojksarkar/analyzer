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
| `structDescription` | a struct's description | R3 |
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
| `description`, `behaviourInputName`, `behaviourOutputName`, `structDescription` | the entity key |
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

The one exception is `{flowchart_token}`, the flowchart id in base64url without padding. Its
alphabet is `[A-Za-z0-9_-]`, so nothing needs escaping. R7 returns both the id and the token.

---

## 3. Endpoint index

| # | Method | Path | Purpose |
|---|---|---|---|
| **R1** | GET | `/projects/{projectId}/versions/{versionId}/overrides` | The corrections in a version (an overlay — see §6) |
| **R2** | GET | `/projects/{projectId}/versions/{versionId}/overrides/slot` | One slot's correction |
| **R3** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Correct one slot |
| **R4** | DELETE | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Undo — restore the LLM original |
| **R5** | GET | `/projects/{projectId}/versions/{versionId}/overrides/history` | The retained edits of one slot |
| **R6** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/behaviour` | Correct one Dynamic Behaviour row |
| **R7** | GET | `/projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels` | Every node label of one flowchart |
| **R8** | PUT | `/projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels` | Correct a flowchart, one call |
| **R9** | GET | `/projects/{projectId}/versions/{versionId}/export-readiness` | Would exporting now ship stale text? |
| **R10** | GET | `/projects/{projectId}/versions/{versionId}/regeneration-queue` | Slots needing regeneration because a correction invalidated them |
| **R11** | GET | `/projects/{projectId}/versions/{versionId}/slots` | What **can** be edited — the slots themselves, with their text and key |

Every path is under the `/api/v1` prefix. All require project **membership** (`REQ-API-05`).

> **Membership is a row, with one exception.** Access is per project: signing in gives you
> nothing on a project you were not added to, and every endpoint here answers
> `403 "Project membership required."`. `POST /api/v1/projects` adds its creator; CLI onboarding
> adds every **superuser** (`users.is_superuser`), and a superuser reaches every project whether
> or not a row exists. To add someone else:
> `python analyzer.py grant --project-id <p> --email <them>`.

---

## 3a. UI flows — which calls, in which order

The endpoints from a screen's point of view. Each path below is under `/api/v1/projects/{projectId}`;
each R-number's full contract is in §6–§15a. Every call sends `Authorization: Bearer <token>`.
Nothing is pushed: **after a save, refetch** what the screen shows.

**Which versions.** R1–R11 work on any version. The document page (`/documents/{docId}/render`) and
the re-export button need a job row and document rows, which only a run started from the web app
writes. A version generated with `analyzer.py generate` has neither: correct it with these
endpoints, then export with `python analyzer.py reexport --project-id <p> --version-id <v>`.

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
| 3 | — | when `queuedForRegeneration` is not empty, say which other texts the next run rewrites |
| 4 | R11 again, then R9 | show the saved text; update the banner |

### Flow 3 — correct a Dynamic Behaviour row

| step | call | why |
|---|---|---|
| 1 | R11 `GET /versions/{versionId}/slots?slot_kind=behaviourDescription&unit=<unit>` | rows with `bullets`, `functionId`, `externalCallerId` and `slotKey` |
| 2 | R6 `PUT /versions/{versionId}/overrides/behaviour` with `{"function_id", "external_caller_id", "bullets"}` | save the **whole** list; both ids copied from step 1 |
| 3 | R11 again, then R9 | |

### Flow 4 — correct flowchart labels

| step | call | why |
|---|---|---|
| 1 | R11 `GET /versions/{versionId}/slots?slot_kind=nodeLabel&unit=<unit>` | one row per flowchart, with its `flowchartToken`. Coming from the page, match the flowchart by `functionName` within its unit — the page carries no tokens (§17) |
| 2 | R7 `GET /versions/{versionId}/flowcharts/{flowchartToken}/labels` | every node's `nodeId`, `text` and `slotKey`, and the diagram as `dot`. Draw the diagram; list the labels for editing |
| 3 | R8 `PUT /versions/{versionId}/flowcharts/{flowchartToken}/labels` with `{"labels": {"<nodeId>": "<text>"}}` | **only the labels that changed**, all in one call |
| 4 | R7 again | redraw from `dot`: the correction shows at once. `renderPending: true` is about the PNG in the Word file only |

### Flow 5 — undo and history, any kind

| call | notes |
|---|---|
| R4 `DELETE /versions/{versionId}/overrides/slot?slot_kind=…&slot_key=…` | back to the LLM's text. A flowchart label is undone per node, with that node's `slotKey` from R7; a behaviour row with the `slotKey` from R11. Disable Undo when `llmText` is `null` |
| R5 `GET /versions/{versionId}/overrides/history?slot_kind=…&slot_key=…` | every edit of that one slot, oldest first |

### Flow 6 — put the corrections into the Word file

| step | call | why |
|---|---|---|
| 1 | R9 | `stale: true`: show "N corrections are not in the Word file yet" and a Re-export button. `pendingRenders` = flowchart pictures the re-export redraws |
| 2 | `GET /jobs/current` | the job to re-export: `job.id`, when `job.version_id` is this version (snake_case, §4) |
| 3 | `POST /jobs/{jobId}/reexport` | project **admin** only — show the button when `GET /projects/{projectId}` gives `my_role: "admin"`. Runs in the background; the server re-derives first when stale |
| 4 | R9 again | clears the banner once the corrections are re-derived. That happens **before** the Word file is written, so it does not mean "re-export finished" (§17) |
| 5 | `GET /documents/{docId}/download` | the stored file — the previous one until the re-export has finished |

Nothing exports on its own.

### Flow 7 — needs attention (optional panel)

R10 `GET /versions/{versionId}/regeneration-queue`: texts the next run rewrites because a correction
changed what they were written from. Show each with its `reason`.

### Drawing a flowchart

The page payload and R7 both carry the flowchart as **Graphviz DOT, read from the database**:

| where | field |
|---|---|
| page: `flowchart_table.flowcharts[]` | `mermaid` — a legacy name; the content is DOT, not Mermaid |
| R7 | `dot` |

R8 rebuilds that DOT in the same request that saves a label, so **draw the DOT and a reload shows the
corrected flowchart at once**. The PNG (`image_url`) is a file on disk that only the next re-export
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

A missing or non-access token is **401**
(`{"detail": {"code": "UNAUTHENTICATED", "message": "…", "status": 401}}`).

**Timestamps** are ISO-8601 UTC strings (`"2026-09-18T09:14:22Z"`) or `null`. **`null` vs absent:**
every field documented below is always present in a 200 response; optional means it may be `null`,
never missing.

---

## 5. Shared objects

### `Override`

Returned by R1 (in a list), R2 (bare) and R4 (nested). One slot's current state.

| field | type | notes |
|---|---|---|
| `slotKind` | string | one of §1 |
| `slotKey` | string | send this back verbatim; never build it |
| `llmText` | string \| null | the LLM's original, captured on the **first** edit and never rewritten (`REQ-ST-03`). `null` when the slot was empty before the first correction — which is why undo can fail with 409 |
| `humanText` | string | the reviewer's words. In force unless `isOrphaned` — see R11 for the three states |
| `isOrphaned` | boolean | the slot stopped resolving (entity renamed or deleted). The record is **kept** (`REQ-ID-03`) and is **not** applied to the document. Show it greyed rather than hiding it |
| `updatedBy` | string \| null | user id |
| `updatedAt` | string \| null | ISO-8601 UTC |

```json
{
  "slotKind": "description",
  "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "llmText": "Initializes the module.",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "isOrphaned": false,
  "updatedBy": "u-17",
  "updatedAt": "2026-09-18T09:14:22Z"
}
```

### `QueuedSlot`

What a correction invalidated — text that was generated **from** the text just replaced
(`REQ-CS-01`). Appears in R3's response and, with more detail, in R10.

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
| `overrides` | `Override[]` | §5 |
| `total` | integer | matching rows **before** paging, honouring `slot_kind` |
| `limit` | integer | echoed |
| `offset` | integer | echoed |

```json
{
  "overrides": [
    {
      "slotKind": "description",
      "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
      "llmText": "Initializes the module.",
      "humanText": "Initialises the GPIO driver and clears pending interrupts.",
      "isOrphaned": false,
      "updatedBy": "u-17",
      "updatedAt": "2026-09-18T09:14:22Z"
    }
  ],
  "total": 1,
  "limit": 200,
  "offset": 0
}
```

**Errors** — 401, 403, 503. An unknown `versionId` returns an empty list, not 404.

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

**Response 200** — a bare `Override` (§5), not wrapped.

**Errors**

| code | when |
|---|---|
| 404 | `{"detail": "no override on that slot"}` — the slot has never been corrected. Expected, not an error condition: fall back to the LLM text you already have |
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
  "slot_key": "Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initialises the GPIO driver and clears pending interrupts."
}
```

**Response 200**

| field | type | notes |
|---|---|---|
| `slotKind` | string | |
| `slotKey` | string | |
| `humanText` | string | what is now in force |
| `llmText` | string \| null | the original, unchanged by this call |
| `previousText` | string \| null | what this call replaced. `null` on the first edit |
| `firstEdit` | boolean | true when this slot had no correction before |
| `viewsDerived` | string[] | **always `[]` over HTTP** — see the note below |
| `queuedForRegeneration` | `QueuedSlot[]` | see below |

```json
{
  "slotKind": "description",
  "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "llmText": "Initializes the module.",
  "previousText": "Initializes the module.",
  "firstEdit": true,
  "viewsDerived": [],
  "queuedForRegeneration": [
    { "slotKind": "unitDescription", "slotKey": "Gpio|GpioDrv" },
    { "slotKind": "description", "slotKey": "App|AppMain|App_Start|void" }
  ]
}
```

**`viewsDerived` is empty over HTTP, and that is correct.** The service can re-derive a view and
stamp it as freshly derived, but only with an output tree, a model and a config — which an API host
is not guaranteed to have. More importantly, stamping a derivation at *save* time would mark the
version **fresh** when its document has not been rebuilt, and R9 would stop reporting the staleness
the export depends on. The field is reserved for a caller that really does re-derive.

**Show `queuedForRegeneration`.** The reviewer is about to see wording change in places they did not
touch, on the next run. An unannounced change reads as a bug.

**Errors**

| code | when |
|---|---|
| 404 | the slot does not resolve in this version |
| 422 | empty or whitespace-only `text`; or a `snake_case` field is missing |
| 501 | `slot_kind` is `nodeLabel` or `behaviourDescription` — use R8 / R6 |
| 401 / 403 / 503 | see §16 |

---

## 9. R4 — undo one slot

`DELETE /projects/{projectId}/versions/{versionId}/overrides/slot`

Restores the LLM's original wording (`REQ-API-04`).

**Undo is an ordinary edit whose text happens to be the original**, so **the record survives** with
both texts and its full history. It is not a delete, and the slot still appears in R1 afterwards —
with `humanText` equal to `llmText`.

**Query parameters** — identical to R2: `slot_kind`, `slot_key`, both required.

**Response 200**

| field | type | notes |
|---|---|---|
| `undone` | boolean | always `true` on 200 |
| `override` | `Override` \| null | the record as it now stands |

```json
{
  "undone": true,
  "override": {
    "slotKind": "description",
    "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
    "llmText": "Initializes the module.",
    "humanText": "Initializes the module.",
    "isOrphaned": false,
    "updatedBy": "u-17",
    "updatedAt": "2026-09-18T10:02:41Z"
  }
}
```

**Errors**

| code | when |
|---|---|
| 409 | no original to restore — the slot was empty before the first correction, so `llmText` is `null`. Disable the undo control when `llmText` is `null` rather than letting the reviewer discover this |
| 404 | the slot does not resolve in this version |
| 400 | malformed `slot_key` for the kind (§2) |
| 401 / 403 / 503 | see §16 |

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
  "function_id": "Gpio|GpioDrv|Gpio_Init|void",
  "external_caller_id": "App|AppMain|App_Start|void",
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

**Response 200**

| field | type | notes |
|---|---|---|
| `slotKey` | string | the composite key the server built |
| `bullets` | string[] | as stored, each collapsed to one line |
| `llmText` | string \| null | the original list, newline-joined |
| `firstEdit` | boolean | |
| `viewsDerived` | string[] | |

```json
{
  "slotKey": "Gpio|GpioDrv|Gpio_Init|void\u0001App|AppMain|App_Start|void",
  "bullets": [
    "App_Start calls Gpio_Init to bring the port up",
    "Gpio_Init returns the port state"
  ],
  "llmText": "App_Start calls Gpio_Init\nGpio_Init returns",
  "firstEdit": true,
  "viewsDerived": ["behaviourDiagram"]
}
```

**No image is re-rendered.** The description is not in the diagram — its arrows are labelled with
the callee's name — so there is nothing to redraw and no render job.

**Errors**

| code | when |
|---|---|
| 404 | no such behaviour row in this version (wrong `function_id` or `external_caller_id`) |
| 422 | `bullets` empty, or a bullet that is blank |
| 401 / 403 / 503 | see §16 |

---

## 12. R7 — read a flowchart's labels

`GET /projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels`

A flowchart **is one function's control-flow graph**, so `flowchartToken` is that function's entity
key in base64url without padding (`REQ-ID-04`). One request opens the editor; one R8 saves it.

**Path parameters**

| name | type | notes |
|---|---|---|
| `flowchartToken` | string | base64url, no padding. e.g. `Gpio\|GpioDrv\|Gpio_Init\|void` → `R3Bpb3xHcGlvRHJ2fEdwaW9fSW5pdHx2b2lk` |

**Response 200**

| field | type | notes |
|---|---|---|
| `flowchartId` | string | the decoded entity key |
| `flowchartToken` | string | echoed |
| `functionName` | string \| null | display name, e.g. `Gpio_Init` |
| `labels` | object[] | **every** node, in graph order — corrected or not |
| `graphAvailable` | boolean | `false` when the stored output carries no graph; `labels` is then `[]` |
| `note` | string | present only when `graphAvailable` is `false`, saying why |
| `dot` | string | the flowchart as **Graphviz DOT**, read from the database — draw it (§3a, *Drawing a flowchart*). R8 rebuilds it in the same request, so after a save it already carries the new labels; the PNG does not. `""` when none is stored |
| `labels[].nodeId` | string | e.g. `n7`. Use as the key in R8 |
| `labels[].slotKey` | string | **this node's slot key** — send it to R4 (undo) or R5 (history). Never assemble one yourself (§2) |
| `labels[].text` | string | **what the picture carries now** — the stored label |
| `labels[].humanText` | string \| null | the reviewer's words, whenever a correction exists — even an orphaned one |
| `labels[].llmText` | string \| null | the captured original. `null` until the node is first corrected |
| `labels[].isOverridden` | boolean | a correction is **in force** on this node. `false` for an orphan |
| `labels[].isOrphaned` | boolean | a correction exists but no longer applies (§5) |

```json
{
  "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "flowchartToken": "R3Bpb3xHcGlvRHJ2fEdwaW9fSW5pdHx2b2lk",
  "functionName": "Gpio_Init",
  "labels": [
    { "nodeId": "n0", "slotKey": "Gpio|GpioDrv|Gpio_Init|void\u0001n0",
      "text": "Start", "humanText": null, "llmText": null,
      "isOverridden": false, "isOrphaned": false },
    { "nodeId": "n7", "slotKey": "Gpio|GpioDrv|Gpio_Init|void\u0001n7",
      "text": "Check the write-protect flag", "humanText": "Check the write-protect flag",
      "llmText": "Check flag", "isOverridden": true, "isOrphaned": false }
  ],
  "graphAvailable": true,
  "dot": "digraph G {\n  rankdir=TB;\n  …\n  n7 [shape=box, label=\"Check the write-protect flag\"];\n  …\n}"
}
```

**Errors**

| code | when |
|---|---|
| 400 | `flowchartToken` is not valid base64url |
| 404 | no flowchart stored for that function in this version |
| 401 / 403 / 503 | see §16 |

**An empty `labels` list is not always an empty flowchart.** `cfg` has only been stored since
2026-09-01, so a version generated before that carries the picture and the DOT but not the graph
they were built from. Its labels cannot be listed or corrected until the version is re-derived
(`reexport --from-phase 3`, which rebuilds the CFG from the model — no re-parse). `graphAvailable`
tells the two apart, and R8 on such a flowchart answers **409**, not 404: the flowchart is there,
its graph is not, and those are different things to fix.

---

## 13. R8 — correct a flowchart, in one call

`PUT /projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels`

**Request body**

| field | type | required | notes |
|---|---|---|---|
| `labels` | object | **yes** | `{nodeId: text}` — **only the labels the reviewer changed** |

```json
{ "labels": { "n7": "Check the write-protect flag", "n9": "Increment the retry count" } }
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
| `flowchartId` | string | the decoded entity key |
| `applied` | string[] | node ids written |
| `firstEdits` | string[] | the subset that had no correction before |
| `slotShape` | string \| null | sha256 hex (64 chars) of the graph these labels were written against — see below |
| `renderPending` | boolean | `true` while the picture is **owed** |
| `renderJobs` | integer[] | job ids raised by this call |
| `viewsDerived` | string[] | **always `[]` over HTTP** — see §8. Editing a node label does change the SWE.4 Test Step, but the next Phase-3 run is what rebuilds it |

```json
{
  "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "applied": ["n7", "n9"],
  "firstEdits": ["n9"],
  "slotShape": "8d08d2a38307c1a44778f12cdb76fd1cb4af0d23dcfa1b25fd7698374f005819",
  "renderPending": true,
  "renderJobs": [412],
  "viewsDerived": []
}
```

**`renderPending`** — the text is corrected everywhere it is read from the database immediately, but
the **picture** may not be. It is `true` whenever a render job was raised and **not finished inside
this call**, which on a host with no output tree is always. Note that the stored JSON and DOT *are*
rebuilt either way: "the graph was rebuilt" and "the image was drawn" are different facts, and this
flag reports the second. It always agrees with R9's `pendingRenders`. A picture not drawn here stays
pending, and the next run or re-export on a host with the tree draws it. **A UI that draws R7's `dot`
shows the corrected flowchart straight after the save** — this flag is only about the PNG the Word
file carries. Either way the export consults the same rows, so a document cannot go out
carrying new text and an old image (`REQ-IM-02`) — R9 reports it as `pendingRenders`.

**`slotShape`** identifies the graph the correction was written against, so the same text is not
reused later against a renumbered one. Node ids are **positions**, not identities. Opaque to the UI.

Each label is stored as **its own record** with its own original and history, even though the API is
per flowchart. The two granularities are deliberately different (`REQ-ST-07`) — which is why R2, R4
and R5 still work on a single `nodeLabel` slot key.

**Errors**

| code | when |
|---|---|
| 400 | `flowchartToken` is not valid base64url |
| 404 | the flowchart, or a node id named in `labels`, does not exist — `detail` names it |
| 409 | the flowchart has no stored graph (see R7). Re-derive the version first |
| 422 | a label is empty or whitespace-only |
| 401 / 403 / 503 | see §16 |

---

## 14. R9 — export readiness

`GET /projects/{projectId}/versions/{versionId}/export-readiness`

Whether exporting now would ship text a correction has already replaced (`REQ-AP-04`). **Call it
before offering a download.**

No parameters.

**Response 200**

| field | type | notes |
|---|---|---|
| `stale` | boolean | `true` ⇒ the views need re-deriving before a download is honest |
| `reason` | string | short, always present: `"up to date"`, `"no corrections"`, or the reason it is stale |
| `explanation` | string | one line fit to show as-is, including any failed renders |
| `overrideCount` | integer | corrections in this version |
| `pendingRenders` | integer | pictures still owed — **any of these makes it stale** |
| `failedRenders` | integer | renders that gave up — reported, **does not block** |
| `newestOverrideAt` | string \| null | ISO-8601 UTC |
| `oldestDerivationAt` | string \| null | ISO-8601 UTC; `null` when the views were never derived |

```json
{
  "stale": true,
  "reason": "a correction is newer than the derived output",
  "explanation": "a correction is newer than the derived output (3 correction(s) in this version)",
  "overrideCount": 3,
  "pendingRenders": 1,
  "failedRenders": 0,
  "newestOverrideAt": "2026-09-18T09:14:22Z",
  "oldestDerivationAt": "2026-09-18T08:02:10Z"
}
```

**What the UI should do with `stale: true`** — nothing special. Re-export through the normal
endpoint: the server now **re-derives first** rather than refusing, so a download taken afterwards
is correct. R9 is for telling the reviewer *why* this one will take longer than usual. (The CLI
refuses instead and prints `reexport --from-phase 3`; the difference is deliberate — see
[DESIGN §13.3](../design/REVIEW_UPDATE_DESIGN.md#133-the-export-guard-lives-in-runpy-not-only-in-analyzerpy).)

**`pendingRenders` also makes a version stale** (`REQ-IM-02`), even when every sentence is current:
an export now would carry the new wording and the old picture.

**`failedRenders` does not block.** A render that gave up cannot be waited for, and blocking would
make one unrenderable flowchart permanently unexportable. It appears in `explanation` instead, so a
document goes out with somebody knowing the image is out of date rather than nobody.

### How the Word document gets the corrections

**Nothing exports automatically.** A save (R3/R6/R8) updates the database in the same request and
never starts an export. The Word file changes only when someone runs a re-export:

```
POST /api/v1/projects/{projectId}/jobs/{jobId}/reexport      (project admin; runs in the background)
```

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
| `unitDescription` | **not shown on the page at all** — the page's unit section has no description | after re-export |
| `structDescription` | **not shown on the page** — struct rows display `N/A` | after re-export |

The last two are gaps in the page renderer (`api/services/doc_render.py`), not in saving: the Word
exporter reads both fields (REQ-PRE-01), the page was never updated to. Recorded in §17.

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
      "slotKey": "App|AppMain|App_Start|void",
      "reason": "its description was written with this function as context",
      "causedBy": { "slotKind": "description", "slotKey": "Gpio|GpioDrv|Gpio_Init|void" },
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
regenerated over. The cascade is **one level** (`REQ-CS-02`): a caller's own callers are not
invalidated, because a transitive cascade is unbounded in a deep call graph.

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
| `unit` | string | no | — | narrow to one unit. Refused with **400** for `structDescription` |
| `component` | string | no | — | narrow to one component. Same exception |
| `limit` | integer | no | `200` | 1–1000 |
| `offset` | integer | no | `0` | ≥ 0 |

**Response 200** — `{"slotKind", "slots", "total", "limit", "offset"}`. `total` is the count
**before** paging.

A row, for the six per-slot kinds:

| field | type | notes |
|---|---|---|
| `slotKind` | string | |
| `slotKey` | string | **send this to R2–R6 verbatim** |
| `label` | string | a display name — the function, unit or type |
| `component` / `unit` | string \| null | `null` for `structDescription`, which has neither |
| `text` | string | **what the document prints now**, read from where the document reads it. May be `""` — a slot can be legitimately empty and is still editable |
| `humanText` | string \| null | the reviewer's words whenever a correction exists, orphaned or not |
| `llmText` | string \| null | the captured original; `null` until the first edit |
| `isOverridden` | boolean | a correction is **in force**. `false` for an orphan |
| `isOrphaned` | boolean | a correction exists but no longer applies |
| `bullets` | string[] | `behaviourDescription` only, in place of `text` |
| `functionId` / `externalCallerId` | string | `behaviourDescription` only: the two ids R6 takes |

```json
{
  "slotKind": "description",
  "slots": [
    { "slotKind": "description", "slotKey": "Sample-Core|Core|coreAdd|int,int",
      "label": "coreAdd", "component": "Sample-Core", "unit": "Core",
      "text": "Adds two integers.", "llmText": null,
      "isOverridden": false, "isOrphaned": false }
  ],
  "total": 158, "limit": 200, "offset": 0
}
```

**`nodeLabel` is listed per FLOWCHART, not per node.** A version holds ~42,000 node labels; one row
each would be hundreds of pages of something nobody reads linearly. A flowchart is one function's
graph, so each row carries the token **R7** takes:

```json
{ "slotKind": "nodeLabel",
  "flowchartId": "Sample-Core|Core|coreAdd|int,int",
  "flowchartToken": "U2FtcGxlLUNvcmV8Q29yZXxjb3JlQWRkfGludCxpbnQ",
  "functionName": "coreAdd", "component": "Sample-Core", "unit": "Core",
  "nodeCount": 7, "overriddenCount": 1 }
```

`overriddenCount` excludes orphans: they are kept but not applied, so counting them would promise
an edit the document does not carry.

**`text`, `humanText` and the two flags, together.** For a live correction `text` and
`humanText` are the same sentence — the save wrote it into the model. They differ in exactly one
case: an **orphan**, which is kept (`REQ-ID-03`) but never applied. Its function's code changed, so
the document prints fresh LLM text while the row still holds words written for the old code:

| state | `text` | `humanText` | `isOverridden` | `isOrphaned` |
|---|---|---|---|---|
| never corrected | the LLM's | `null` | `false` | `false` |
| corrected | the human's | the human's | `true` | `false` |
| orphaned | the LLM's (fresh) | the human's (stale) | `false` | `true` |

Show an orphan's `humanText` as "your correction no longer applies", never as current wording.

**The text here is the text a save replaces.** It is read through the same resolver
`PUT …/overrides/slot` writes through, so the listing and the write cannot disagree about which
field a kind lives in.

**Errors**

| code | when |
|---|---|
| 400 | `unit` or `component` given for `structDescription`, which has neither — refused rather than ignored, so an unfiltered result is never read as a filtered one |
| 422 | `slot_kind` missing or not one of the seven |
| 401 / 403 / 503 | see §16 |

---

## 16. Errors and concurrency

Error bodies are `{"detail": "…"}`, except 401 (an object, §4) and 422 from schema validation
(pydantic's array).

| Code | When |
|---|---|
| 400 | malformed slot key or flowchart token |
| 401 | missing, malformed or non-access Bearer token |
| 403 | not a member of the project |
| 404 | unknown version, slot, flowchart, or a node named in a flowchart save |
| 409 | undo with no LLM original to restore |
| 422 | empty or whitespace-only text (`REQ-ST-06`); or a request body/query field missing — **check `snake_case` first** (§4) |
| 501 | a slot kind with no save path on that endpoint (`nodeLabel`, `behaviourDescription` on R3) |
| 503 | no database configured — corrections live nowhere else, so the write is refused rather than dropped |

Two people editing the same slot: **last write wins**, no locking and no conflict response
(`REQ-API-07`). Sending only changed labels (§13) is what keeps that true *per slot* when a whole
flowchart is saved at once.

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
- **The document page does not show unit or struct descriptions** (§14, "When a correction becomes
  visible"), so corrections to those two kinds appear only in the Word file. The page renderer lags
  the Word exporter here; both read the same stored fields once it catches up.
- **A corrected flowchart's PNG is redrawn by the next run or re-export**, not by the save — R8
  over HTTP has no output tree to draw into, so `renderPending` is `true`. Its DOT is rebuilt by the
  save: draw that (§3a) and the page is current at once.
- **A re-export has no completion signal.** It runs on the version's existing job and never changes
  that job's `status`, which stays `complete`; so neither `GET /jobs/{jobId}` nor its `events` stream
  can say "started" or "finished" (a failure does show, as `failed`). R9 turning `stale: false`
  means the corrections were re-derived, which happens before the Word file is written. Until the
  job reports its re-export, "Re-export started" is all the UI can honestly say.
- **Only the newest version can be re-exported from the UI.** The endpoint takes a job id, and the
  only way to find one is `GET /jobs/current`, the project's latest job. A version carries no job id.
- **The page payload carries no slot keys**, so "edit this sentence" on the page means finding the
  item in R11 (same unit, by `label` or `functionName`) and using its `slotKey`.

---

_End of document._
