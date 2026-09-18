# Review & Update — API Specification (for UI integration)

The HTTP contract for correcting the LLM's text in a generated document. This is what the UI is
built against.

Update this doc first when changing the endpoints, then code + tests.
Requirements: [REVIEW_UPDATE_SPEC](REVIEW_UPDATE_SPEC.md) (`REQ-` ids below) ·
design: [REVIEW_UPDATE_DESIGN](../design/REVIEW_UPDATE_DESIGN.md) ·
merging the branch: [REVIEW_UPDATE_HANDOVER](../design/REVIEW_UPDATE_HANDOVER.md).

**Conventions** — base URL, prefix, error shape, status codes and the `projectId` / `versionId`
identifiers are shared with
[05-incremental-api-spec §1](../production-redesign/05-incremental-api-spec.md#1-conventions) and
are not repeated here. That document covers the incremental-generation endpoints only; these are a
separate feature with its own surface.

---

## Contents

- [1. What can be edited](#1-what-can-be-edited)
- [2. Slot keys, and why they are not in the path](#2-slot-keys-and-why-they-are-not-in-the-path)
- [3. Endpoint index](#3-endpoint-index)
- [4. R1 — the corrections in a version](#4-r1--the-corrections-in-a-version)
- [5. R2 / R3 / R4 — one slot](#5-r2--r3--r4--one-slot)
- [6. R6 — one Dynamic Behaviour row](#6-r6--one-dynamic-behaviour-row)
- [7. R7 / R8 — a flowchart, in one call](#7-r7--r8--a-flowchart-in-one-call)
- [8. R5 — one slot's history](#8-r5--one-slots-history)
- [9. R9 — export readiness](#9-r9--export-readiness)
- [10. Errors and concurrency](#10-errors-and-concurrency)
- [11. Not yet implemented](#11-not-yet-implemented)

---

## 1. What can be edited

Seven **slot kinds** (`REQ-ED-01`). Every request names one:

| `slotKind` | what it is |
|---|---|
| `description` | a function's or global's description |
| `behaviourInputName` | the behaviour table's input name |
| `behaviourOutputName` | the behaviour table's output name |
| `behaviourDescription` | a Dynamic Behaviour row — a **list** of bullets, edited as one block |
| `unitDescription` | a unit's description |
| `structDescription` | a struct's description |
| `nodeLabel` | one flowchart node's label |

---

## 2. Slot keys, and why they are not in the path

A `slotKey` addresses one slot. It is **built by the server** and returned to you — never assembled
in the UI (`REQ-ID-01`).

| `slotKind` | `slotKey` |
|---|---|
| `description`, `behaviourInputName`, `behaviourOutputName`, `structDescription` | the entity key |
| `unitDescription` | the unit key, `Component\|Unit` |
| `behaviourDescription` | `functionId` + `U+0001` + `externalCallerId` |
| `nodeLabel` | `entityKey` + `U+0001` + `nodeId` |

A key contains `|`, `:`, `,`, `*`, spaces and a `U+0001` separator, so **keys travel in the body or
a query parameter, never in a path segment.** The one exception is `{flowchartToken}`, which is the
flowchart id in base64url (no padding) — its alphabet is `[A-Za-z0-9_-]`, so nothing needs
escaping.

---

## 3. Endpoint index

| # | Method | Path | Purpose |
|---|---|---|---|
| **R1** | GET | `/projects/{projectId}/versions/{versionId}/overrides` | The corrections in a version (an overlay — see §4) |
| **R2** | GET | `/projects/{projectId}/versions/{versionId}/overrides/slot` | One slot's correction |
| **R3** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Correct one slot |
| **R4** | DELETE | `/projects/{projectId}/versions/{versionId}/overrides/slot` | Undo — restore the LLM original |
| **R5** | GET | `/projects/{projectId}/versions/{versionId}/overrides/history` | The retained edits of one slot |
| **R6** | PUT | `/projects/{projectId}/versions/{versionId}/overrides/behaviour` | Correct one Dynamic Behaviour row |
| **R7** | GET | `/projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels` | Every node label of one flowchart |
| **R8** | PUT | `/projects/{projectId}/versions/{versionId}/flowcharts/{flowchartToken}/labels` | Correct a flowchart, one call |
| **R9** | GET | `/projects/{projectId}/versions/{versionId}/export-readiness` | Would exporting now ship stale text? |

All require project **membership** (`REQ-API-05`).

---

## 4. R1 — the corrections in a version

`GET /projects/{projectId}/versions/{versionId}/overrides`

**This is an overlay, not a list of every slot.** A version holds roughly **57,000** slots, so
enumerating them would rebuild the document you already fetched from `/components`, `/functions`
and `/flowcharts`. Fetch this and merge by `slotKey`; a version nobody has corrected returns an
empty list.

Query: `slotKind` (optional), `limit` (1–1000, default 200), `offset`.

**200**
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
  "total": 1, "limit": 200, "offset": 0
}
```

`isOrphaned` — the slot stopped resolving (the function was renamed or deleted). The correction is
**kept**, never auto-deleted (`REQ-ID-03`), and is not applied to the document.

---

## 5. R2 / R3 / R4 — one slot

**R2** `GET …/overrides/slot?slotKind=&slotKey=` returns the object above, or **404** when that
slot has no correction.

**R3** `PUT …/overrides/slot`
```json
{ "slotKind": "description",
  "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "text": "Initialises the GPIO driver and clears pending interrupts." }
```
**200**
```json
{ "slotKind": "description", "slotKey": "Gpio|GpioDrv|Gpio_Init|void",
  "humanText": "Initialises the GPIO driver and clears pending interrupts.",
  "llmText": "Initializes the module.",
  "previousText": "Initializes the module.",
  "firstEdit": true, "viewsDerived": ["interfaceTables"] }
```

`llmText` is captured on the **first** edit and never rewritten (`REQ-ST-03`) — it is what undo
restores and the "wrong" half of the training pair. `previousText` is what this call replaced.

Not offered for `nodeLabel` (use R8) or `behaviourDescription` (use R6).

**R4** `DELETE …/overrides/slot?slotKind=&slotKey=` — undo (`REQ-API-04`).

Undo is an ordinary edit whose text happens to be the original, so **the record survives** with
both texts and its history. **409** when there is no original to restore, which happens when the
slot was empty before the first correction.

---

## 6. R6 — one Dynamic Behaviour row

`PUT /projects/{projectId}/versions/{versionId}/overrides/behaviour`

The row is a **list** of bullets, one per call arrow, edited as one block (`REQ-ED-02`).

```json
{ "functionId": "Gpio|GpioDrv|Gpio_Init|void",
  "externalCallerId": "App|AppMain|App_Start|void",
  "bullets": ["App_Start calls Gpio_Init to bring the port up",
              "Gpio_Init returns the port state"] }
```

**Both ids are entity keys.** Not the row's `externalUnitFunction` display label — that is
`"<unit> - <name>"` and two different callers can share one, so a correction addressed by it would
land on the wrong row (`REQ-ID-01`).

Each bullet is collapsed onto one line. A correction here renders **no image**: the description is
not in the diagram, whose arrows are labelled with the callee's name.

---

## 7. R7 / R8 — a flowchart, in one call

A flowchart **is one function's control-flow graph**, so `flowchartToken` is that function's entity
key, base64url-encoded (`REQ-ID-04`).

**R7** `GET …/flowcharts/{flowchartToken}/labels`
```json
{ "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "flowchartToken": "R3Bpb3xHcGlvRHJ2fEdwaW9fSW5pdHx2b2lk",
  "functionName": "Gpio_Init",
  "labels": [
    { "nodeId": "n0", "text": "Start", "llmText": null, "isOverridden": false },
    { "nodeId": "n7", "text": "Check the write-protect flag",
      "llmText": "Check flag", "isOverridden": true }
  ] }
```

**R8** `PUT …/flowcharts/{flowchartToken}/labels`
```json
{ "labels": { "n7": "Check the write-protect flag", "n9": "Increment the retry count" } }
```

Three rules (`REQ-API-08`):

1. **Send only the labels the reviewer changed.** Not the whole flowchart. A stale copy of an
   untouched label would overwrite a correction somebody else made to it seconds earlier, and the
   server cannot tell that from a deliberate revert.
2. **All or nothing.** If any label is rejected — empty text, or a node that no longer exists —
   nothing is written and the response names the node.
3. **One re-render per call**, however many labels it carried.

**200**
```json
{ "flowchartId": "Gpio|GpioDrv|Gpio_Init|void",
  "applied": ["n7", "n9"], "firstEdits": ["n9"],
  "slotShape": "9f2c…", "renderPending": true,
  "viewsDerived": ["flowcharts", "testSpecs"] }
```

`renderPending` — the picture was redrawn as part of this call when the server has an output tree;
when it does not, the text is stored and the next run redraws. `slotShape` identifies the graph the
correction was written against, so it is not reused later against a renumbered one.

Each label is stored as **its own record** with its own original and history, even though the API
is per flowchart. The two granularities are deliberately different (`REQ-ST-07`).

---

## 8. R5 — one slot's history

`GET …/overrides/history?slotKind=&slotKey=` returns the retained edits of one slot, oldest first,
bounded by `llm.overrideHistoryDepth` (`REQ-ST-04`). The LLM original is **not** in here — it is on
the override itself, which is what makes "the original is never evicted by the cap" structural.

```json
{ "history": [ { "seq": 1, "humanText": "…", "updatedBy": "u-17",
                 "updatedAt": "2026-09-18T09:14:22Z" } ] }
```

---

## 9. R9 — export readiness

`GET …/export-readiness`. Whether exporting now would ship text a correction has already replaced
(`REQ-AP-04`). Call it before offering a download.

**200**
```json
{ "stale": true,
  "reason": "a correction is newer than the derived output",
  "explanation": "a correction is newer than the derived output (3 correction(s) in this version)",
  "overrideCount": 3,
  "newestOverrideAt": "2026-09-18T09:14:22Z",
  "oldestDerivationAt": "2026-09-18T08:02:10Z" }
```

`stale: true` means the views need re-deriving — `reexport --from-phase 3`. The CLI refuses a stale
`--from-phase 4` export for the same reason.

---

## 10. Errors and concurrency

| Code | When |
|---|---|
| 400 | malformed slot key or flowchart token |
| 403 | not a member of the project |
| 404 | unknown version, slot, flowchart, or a node named in a flowchart save |
| 409 | undo with no LLM original to restore |
| 422 | empty or whitespace-only text (`REQ-ST-06`) |
| 501 | a slot kind that has no save path in this build |
| 503 | no database configured — corrections live nowhere else, so the write is refused rather than dropped |

Two people editing the same slot: **last write wins**, no locking and no conflict response
(`REQ-API-07`). Sending only changed labels (§7) is what keeps that true *per slot* when a whole
flowchart is saved at once.

---

## 11. Not yet implemented

Honest gaps, so the UI does not plan around something that is not there.

- **`renderPending` is not a job handle.** Renders happen inside the request today. The background
  queue, and `REQ-IM-02`'s "export waits for pending renders", are build-order step 7.
- **Corrections do not carry into the next version yet** (`REQ-VR-01`, step 8). `slotShape` is
  written and its guard is tested, but nothing reads it across versions.
- **No cascade** (`REQ-CS-01`, step 6): correcting a function description does not yet regenerate
  its unit description or its callers'.
- **No cleanup endpoint** for orphaned corrections — deliberately, pending a decision; see
  [REVIEW_UPDATE_DESIGN Open items](../design/REVIEW_UPDATE_DESIGN.md#open-items).

---

_End of document._
