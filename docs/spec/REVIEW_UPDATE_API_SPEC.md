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

Every path is under the `/api/v1` prefix. All require project **membership** (`REQ-API-05`).

> **Membership is a row, not a role.** There is no global admin: `User` has no role field, so
> signing in as any account gives you nothing on a project you were not added to — every endpoint
> here answers `403 "Project membership required."`. A project created through
> `POST /api/v1/projects` adds its creator automatically; one onboarded from the CLI needs
> `python analyzer.py grant --project-id <p> --email <you>` (or `onboard --owner <you>`).

---

## 4. Wire format — read this before writing a client

**Requests are `snake_case`. Responses are `camelCase`.** This is not a typo and it is not
negotiable per-endpoint — it is how the whole platform API is built, and the review routes follow
it.

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
blocks CDNs). The ten endpoints are grouped under **review** and each is named by its R-number, so
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
| `humanText` | string | the text in force now |
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
| `viewsDerived` | string[] | views re-derived inside this request, e.g. `["interfaceTables"]` |
| `queuedForRegeneration` | `QueuedSlot[]` | see below |

```json
{
  "slotKind": "description",
  "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "llmText": "Initializes the module.",
  "previousText": "Initializes the module.",
  "firstEdit": true,
  "viewsDerived": ["interfaceTables"],
  "queuedForRegeneration": [
    { "slotKind": "unitDescription", "slotKey": "Gpio|GpioDrv" },
    { "slotKind": "description", "slotKey": "App|AppMain|App_Start|void" }
  ]
}
```

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
| 401 / 403 / 503 | see §16 |

---

## 10. R5 — one slot's history

`GET /projects/{projectId}/versions/{versionId}/overrides/history`

The retained edits of one slot, **oldest first**, bounded by `llm.overrideHistoryDepth`
(`REQ-ST-04`).

The LLM original is **not** in here — it is `llmText` on the override itself, which is what makes
"the original is never evicted by the cap" structural rather than a rule someone must remember.

**Query parameters** — identical to R2: `slot_kind`, `slot_key`, both required.

**Response 200**

| field | type | notes |
|---|---|---|
| `history` | object[] | empty array for a slot that was never corrected — **not** 404 |
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
land on the wrong row (`REQ-ID-01`).

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
| `labels[].nodeId` | string | e.g. `n7`. Use as the key in R8 |
| `labels[].text` | string | what the document shows now: the correction if there is one, else the LLM's |
| `labels[].llmText` | string \| null | the original. `null` when this node was never corrected |
| `labels[].isOverridden` | boolean | true when a correction exists for this node |

```json
{
  "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "flowchartToken": "R3Bpb3xHcGlvRHJ2fEdwaW9fSW5pdHx2b2lk",
  "functionName": "Gpio_Init",
  "labels": [
    { "nodeId": "n0", "text": "Start", "llmText": null, "isOverridden": false },
    { "nodeId": "n7", "text": "Check the write-protect flag",
      "llmText": "Check flag", "isOverridden": true }
  ]
}
```

**Errors**

| code | when |
|---|---|
| 400 | `flowchartToken` is not valid base64url |
| 404 | no flowchart stored for that function in this version |
| 401 / 403 / 503 | see §16 |

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
| `viewsDerived` | string[] | e.g. `["flowcharts", "testSpecs"]` — editing a node label changes the SWE.4 Test Step too |

```json
{
  "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "applied": ["n7", "n9"],
  "firstEdits": ["n9"],
  "slotShape": "8d08d2a38307c1a44778f12cdb76fd1cb4af0d23dcfa1b25fd7698374f005819",
  "renderPending": true,
  "renderJobs": [412],
  "viewsDerived": ["flowcharts", "testSpecs"]
}
```

**`renderPending`** — the text is corrected everywhere it is read from the database immediately, but
the **picture** may not be. The image is redrawn inside the call when the server has an output tree,
and `renderPending` is then `false`. Where it does not, the job stays pending and a host that has
the tree finishes it. Either way the export consults the same rows, so a document cannot go out
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

---

_End of document._
