# Review & Update — Design

How the feature in [REVIEW_UPDATE_SPEC](../spec/REVIEW_UPDATE_SPEC.md) is built. Requirements are
referenced as `REQ-xx-NN`; this doc says **how**, the spec says **what** and **why**.

Written to survive modification and merging: every integration point names the file and the existing
mechanism it hangs off, so a future change can find what it is touching.

---

## Contents

- [1. The shape of it](#1-the-shape-of-it)
- [2. Schema](#2-schema)
- [3. Slot addressing](#3-slot-addressing)
- [4. Writing an override](#4-writing-an-override)
  - [4.1 A whole flowchart in one call](#41-a-whole-flowchart-in-one-call)
- [5. Re-deriving the views](#5-re-deriving-the-views)
- [6. The cascade](#6-the-cascade)
- [7. Images](#7-images)
- [8. Reading: HTML and DOCX](#8-reading-html-and-docx)
- [9. The export guard](#9-the-export-guard)
- [10. Carrying overrides into the next version](#10-carrying-overrides-into-the-next-version)
- [11. API](#11-api)
  - [11.1 The flowchart endpoint](#111-the-flowchart-endpoint)
- [12. Prerequisites](#12-prerequisites)
- [13. Build order](#13-build-order)
- [14. Testing](#14-testing)
- [15. Decisions and their reasons](#15-decisions-and-their-reasons)

---

## 1. The shape of it

One idea holds the design together:

> **The model is the only place text lives. Everything else is derived from it.**

An override is therefore an ordinary model write plus a re-derivation — not a new parallel copy of
the document. That is what makes `REQ-AP-01` true by construction rather than by everyone
remembering.

```
                  ┌──────────────────┐
   PUT /slots/{id}│   override        │  1. record the pair (LLM original, human text)
        ─────────►│   service         │  2. write the model
                  └────────┬─────────┘  3. re-derive affected views      } one transaction
                           │            4. enqueue image renders          } (4 is after commit)
                           ▼
              ┌────────────────────────┐
              │  MODEL (entity rows)   │ ◄── single source of truth
              └───────────┬────────────┘
                          │ derive
             ┌────────────┴────────────┐
             ▼                         ▼
   version_output_files          PNG files on disk
   (interface tables,            (flowcharts, behaviour
    flowcharts, behaviour)        diagrams)
             │                         │
             ├─────────► HTML view ◄───┤   live, per request
             └─────────► DOCX     ◄────┘   export
```

Two things are deliberately **not** in the picture: `llm_description_cache` is never written
(`REQ-VR-02`), and there is no second store of document text.

---

## 2. Schema

Three tables. Names follow the existing convention in
[api/db/postgres/schema.py](../../api/db/postgres/schema.py); all three cascade from `versions`.

### 2.1 `text_overrides` — the current state of a slot

One row per overridden slot. This is what readers consult, so it must be a single indexed lookup
(`REQ-ST-05`).

| column | notes |
|---|---|
| `version_id` | FK → `versions.id`, `ondelete=CASCADE`. Overrides are version-scoped (`REQ-ST-02`) |
| `slot_kind` | `description` / `behaviourInputName` / `behaviourOutputName` / `behaviourDescription` / `unitDescription` / `structDescription` / `nodeLabel` |
| `slot_key` | the addressing string — see [§3](#3-slot-addressing) |
| `llm_text` | the original. Never overwritten after the first override (`REQ-ST-03`) |
| `human_text` | the current human text |
| `is_orphaned` | set when the slot no longer resolves (`REQ-ID-03`) |
| `updated_by`, `updated_at` | |
| `llm_model`, `llm_cache_version` | provenance for `REQ-TD-02` |
| `llm_context` | JSONB — what the LLM was shown (`REQ-TD-02`) |
| `slot_shape` | `nodeLabel` only: a hash of the flowchart's node-id list when the override was made (`REQ-ID-02`). Null for every other kind |

**Why `slot_shape` is its own column and not a key in `llm_context`:** the node list is not something
the LLM was shown, and a column that means two different things depending on the kind is how the
September interface-id collision started. One column, one fact.

`UniqueConstraint(version_id, slot_kind, slot_key)` · `Index(version_id, slot_kind)`

**Why one row per slot rather than reading the newest history row:** the HTML view resolves every
slot on the page on every request. A `max(updated_at)` subquery per slot would make render cost grow
with edit count (`REQ-ST-05`).

### 2.2 `text_override_history` — the audit trail

Append-only. One row per human edit.

| column | notes |
|---|---|
| `version_id`, `slot_kind`, `slot_key` | matches the override |
| `human_text`, `updated_by`, `updated_at` | |
| `seq` | monotonic per slot; drives the N-cap |

Trimmed to the newest **N** rows per slot on write, N from config
(`llm.overrideHistoryDepth`, default 10). `llm_text` lives on `text_overrides`, never here — which
is what makes `REQ-ST-04`'s "the original is never evicted" structural rather than a rule someone
must remember.

### 2.3 `view_derivations` — when each view was last derived

The export guard's input (`REQ-AP-04`).

| column | notes |
|---|---|
| `version_id`, `view_name`, `group_name` | what was derived |
| `derived_at` | |

Guard: `max(text_overrides.updated_at) > min(view_derivations.derived_at)` ⇒ stale.

### 2.4 Migration

Additive only — new tables and a new nullable column, no existing column changed — so it is safe to
apply ahead of the code. `0010_text_overrides` creates the three tables; `0011_slot_shape` adds
`text_overrides.slot_shape`.

---

## 3. Slot addressing

`slot_key` is a string built from ids that already exist (`REQ-ID-01`). No new identifier scheme.

| `slot_kind` | `slot_key` | source of the id |
|---|---|---|
| `description` | `entity_key` | `entities.entity_key`, unique per project |
| `behaviourInputName` | `entity_key` | same |
| `behaviourOutputName` | `entity_key` | same |
| `structDescription` | `entity_key` (kind=`type`) | same |
| `unitDescription` | `unit_key` | `model_units.unit_key` = `Component\|Unit` |
| `behaviourDescription` | `<functionId>` ␁ `<externalUnitFunction>` | the `_docxRows` entry |
| `nodeLabel` | `<entity_key>` ␁ `<node_id>` | `cfg.nodes[].id` |

␁ is **SOH (0x01)**, not `#` or `|`. `entity_key` is itself `component|unit|name|paramTypes`, so a
composite joined with `|` can only be split by counting pipes and hoping, and `#` can appear in a
generated display name. 0x01 can occur in none of them, so parsing is exact.

Deliberately **not** 0x1f, which `hashing.py` uses: Python counts 0x1c–0x1f as whitespace, so
`"a\x1f".strip()` deletes it. A hash input is never trimmed; a slot key travels through request
bodies, JSON and form fields, any of which may trim what they are handed.

**The flowchart id is the function's `entity_key`** (`REQ-ID-04`) — the same string that is the first
part of every node-label key inside it. A flowchart *is* one function's CFG: the picture is
`<unit>_<function>.png` and the graph hangs off a per-function entry in the unit's flowchart JSON.
One id read two ways, not two ids to keep in step.

So `slot.parse(NODE_LABEL, key)["entity_key"]` is the flowchart the label belongs to, and no
mapping table is needed to go either way.

`version_id` is a column, not part of the key, so "the same slot across versions" is a simple query —
which [§10](#10-carrying-overrides-into-the-next-version) needs.

**A single parse/format pair** (`slot.py`) owns this mapping. Nothing else constructs a `slot_key` by
string concatenation; that is how the `_id_seg` interface-id collision happened — two places
computing one key and drifting apart.

---

## 4. Writing an override

`engine/review/override_service.py` — one entry point, used by the API and by tests.

```
apply_override(version_id, slot_kind, slot_key, human_text, user_id):

  reject if human_text is empty or whitespace          REQ-ST-06
  resolve the slot -> the model field it maps to       §3
  reject if it does not resolve (404)

  BEGIN
    read the current model value
    if no override exists yet:
        llm_text = the current model value             REQ-ST-03  (captured once)
    if slot_kind is nodeLabel:
        slot_shape = hash of this CFG's node-id list   REQ-ID-02  (refreshed every edit:
                                                       it describes the graph the text was
                                                       last written against, not the first)
    write human_text into the model
    upsert text_overrides
    append text_override_history, trim to N            REQ-ST-04
    cascade: regenerate dependents                     §6
    re-derive affected views                           §5
    stamp view_derivations
  COMMIT

  enqueue image renders (after commit)                 §7
```

Everything through `COMMIT` is one transaction (`REQ-AP-02`) — a half-applied override, where the
model moved and the views did not, is exactly the failure this feature exists to avoid.

**Five kinds, not seven.** `nodeLabel` and `behaviourDescription` have no model field to resolve
to — see [Open items](#open-items). `override_service` refuses them with `NotEditableHere` rather
than writing somewhere the next derivation overwrites.

### 4.1 A whole flowchart in one call

`apply_override` stays the per-slot primitive. `apply_flowchart_overrides` wraps it for `REQ-API-08`:

```
apply_flowchart_overrides(version_id, flowchart_id, labels, user_id):

  labels is {node_id: text} -- only what the reviewer changed

  VALIDATE EVERY LABEL FIRST, write nothing:
      each text non-empty                              REQ-ST-06
      each node_id present in this version's CFG       REQ-API-08 rule 2
      -> any failure aborts the call, naming the node

  read the CFG's node-id list ONCE -> slot_shape       REQ-ID-02

  BEGIN
    for each label:
        apply_override(..., NODE_LABEL,
                       slot.for_node(flowchart_id, node_id),
                       derive=None)                    one row, own llm_text, own history
    re-derive the flowchart ONCE                       REQ-API-08 rule 3
    stamp view_derivations
  COMMIT

  enqueue ONE image render
```

Three properties fall out of this shape, and each is the reason for it:

**Validate-then-write, not write-as-you-go.** Otherwise labels 1–3 are committed and label 4 fails,
and the picture is redrawn from a half-applied edit.

**`derive=None` on each inner call.** Twelve labels must not mean twelve derivations of the same
JSON and twelve Graphviz runs of the same graph. The flowchart was always the unit of rebuilding —
a PNG cannot be partly redrawn — so this is the API finally agreeing with the renderer. It is the
main saving the change buys, beyond the request count.

**One reading of the graph for the shape.** All of a flowchart's rows get the same `slot_shape`
from a single read, so they cannot disagree about which graph they were written against, and
`REQ-ID-02` carries them forward or orphans them as a group.

Renders are enqueued **after** commit: a render is slow, must not hold a transaction, and is
idempotent if retried.

**Writing to the model** goes through the existing repository gateway
([core/model_repo.py](../../engine/core/model_repo.py)) so the write lands wherever the run's model
lives. Nothing here opens `entity_versions` directly.

---

## 5. Re-deriving the views

The view functions are already pure and already scopeable — no new machinery.

```python
from views.registry import VIEW_REGISTRY
VIEW_REGISTRY["interfaceTables"](model, output_dir, model_dir, config)
```

`interface_tables.run(model, output_dir, model_dir, config)` reads
`config["_analyzerAllowedComponents"]`, so re-deriving **one component** is a matter of passing that
key. No LLM, no parse, no subprocess.

| slot kind | views re-derived |
|---|---|
| `description`, `behaviourInputName/OutputName` | `interfaceTables` for the function's component |
| `unitDescription`, `structDescription` | `interfaceTables` for that component |
| `behaviourDescription` | `behaviourDiagram` rows for that component |
| `nodeLabel` | the flowchart JSON for that unit |

Each derivation stamps `view_derivations`.

**The rule that keeps `REQ-AP-01` true:** nothing except a `VIEW_REGISTRY` call writes a
`version_output_files` row. If a future change adds a second writer, the invariant is gone and the
two-copies bug class returns.

---

## 6. The cascade

`engine/review/cascade.py`. One level only (`REQ-CS-02`).

Dependents of an edited **function description**:

1. **Its unit's description** — `model_units` by the function's `unit_key`
2. **Its direct callers** — one indexed query, the index exists for exactly this:

   ```sql
   SELECT src_key FROM model_edges
    WHERE version_id = :v AND kind = 'call' AND dst_key = :entity_key
   ```

   (`ix_edges_reverse` on `(version_id, kind, dst_key)` — commented in the schema as *"who depends on
   X (impact)"*.)
3. **Behaviour call descriptions** where it is caller or callee

A **global description** regenerates only its unit's description. Every other slot kind cascades to
nothing (`REQ-CS-03` through `REQ-CS-07`).

Regeneration calls the same generators the pipeline uses — `get_description`, `get_unit_description`,
`CallDescriptionGenerator` — so wording stays consistent with a normal run.

**A dependent that already has its own override is skipped** (`REQ-CS-03`). The human's text is never
replaced by a regeneration.

**Flowchart node labels are not dependents of anything.** The summary chain (`function summary → file
→ component → project`) feeds *into* labels and is built from source, never from `description` — see
`REQ-CS-01`'s table. This is what bounds the cascade; without it one edit would invalidate ~42,000
labels.

---

## 7. Images

### 7.1 Trigger

A `nodeLabel` override rewrites `cfg.nodes[].label`, then re-derives the DOT from the CFG and
re-renders — **once per save, not once per label** ([§4.1](#41-a-whole-flowchart-in-one-call)).
**The DOT is never edited directly** — it is generated syntax, and the SWE.4 Test Steps
read the CFG, not the DOT. Editing the CFG keeps the picture and the test specification in step.

A `behaviourDescription` override re-renders that behaviour diagram's mermaid → PNG.

### 7.2 Execution

A daemon thread, matching
[api/services/pipeline_runner.py](../../api/services/pipeline_runner.py)'s existing pattern
(`threading.Thread(..., daemon=True)`), with a `render_jobs` row for state. Not a new job framework.

Flowcharts use `utils.render_dot_cached(project_root, dot, png_path)`, which is content-addressed —
re-rendering an unchanged graph is a file copy, not a render.

### 7.3 Pending renders and export

Export waits (`REQ-IM-02`). A render job is `pending` until its PNG is written; export blocks while
any `pending` job exists for the version.

Without this, an export a second after an edit ships the new text everywhere and the old picture —
the same split-origin failure that produced a stored graph and a document picture from different
versions in September.

---

## 8. Reading: HTML and DOCX

**Neither reader changes.** That is the point of writing through the model.

- **HTML** — `render_document` already builds live from Postgres per request via `ModelReader` and
  `OutputReader`. The override is in the model and in the derived rows, so it appears on the next
  page load (`REQ-AP-03`).
- **DOCX** — the exporter reads `interface_tables`, which the derivation refreshed (`REQ-AP-04`).

The only new read is the API's own "does this slot have an override" for the UI's list
(`REQ-API-01`), which is a direct query on `text_overrides`.

---

## 9. The export guard

`REQ-AP-04`, and the piece that makes this reliable rather than merely correct.

Before Phase 4 runs — in `cmd_reexport` and in the API's export path:

```
stale = EXISTS(text_overrides for this version newer than the oldest view_derivations row)
        OR EXISTS(render_jobs pending for this version)

if stale:
    re-derive the affected views, wait for pending renders, then export
    (or refuse, naming what is stale, when re-deriving is not possible)
```

`reexport --from-phase 4` is documented as *"export only"* and **skips Phase 3** — the step that
rebuilds the view rows from the model. Without this guard it ships the previous text, silently.
Moving output into the database does not fix it: it is still the row Phase 3 wrote last time.

The guard is a **check, not an assumption**. Even if a future change adds a write path that forgets
to re-derive, the export cannot quietly ship stale text.

---

## 10. Carrying overrides into the next version

`REQ-VR-01`. The engine already carries text between versions and it already reads the **model**, not
the cache:

- `carry_forward_globals` / `_CARRY_FIELDS` — `engine.py:130`, copies from the baseline's model
- `carry_forward_from_index` — `engine.py:163`, copies from another version's model

Because an override writes the model, a function whose `source_hash` is unchanged carries the human
text with **no change to those functions**.

What is new is copying the **override records** so the new version knows which slots are
human-authored — needed for undo, for the UI's "overridden" flag, and for `REQ-CS-03`:

```
for each override on the baseline:
    if the slot still resolves in the new version
       and (slot is not nodeLabel or (the function's source_hash is unchanged        REQ-VR-03
                                      and slot_shape matches the new CFG)):          REQ-ID-02
        copy the row to the new version
    else:
        copy it marked orphaned — never drop it                                      REQ-ID-03
```

A changed function does not carry its override: the human text describes code that no longer exists.
Fresh LLM text is correct there (`REQ-VR-01`).

The `slot_shape` half of the `nodeLabel` condition is what stops a correction landing on the wrong
node when the source is byte-identical but the builder or `cfgSimplification` renumbered the graph
(`REQ-ID-02`). Since every override on a flowchart stores the same shape, they pass or fail together.

`--full` has no baseline, so nothing is carried and the overrides simply are not applied
(`REQ-VR-03`) — **they are not deleted**. `--full` is the standing remedy for several problems and
must never destroy a reviewer's work.

---

## 11. API

New router `api/routes/text_overrides.py`, following the conventions in
[api/routes/documents.py](../../api/routes/documents.py) — `Depends(get_current_user)`,
`require_project_member` to read, `require_project_admin`/member to write (`REQ-API-05`).

| method | path | requirement |
|---|---|---|
| `GET` | `…/versions/{vid}/slots` | `REQ-API-01` — list with current text + `isOverridden`; filter by unit/component/kind, paginated |
| `GET` | `…/versions/{vid}/slots/{kind}/{key}` | `REQ-API-02` |
| `PUT` | `…/versions/{vid}/slots/{kind}/{key}` | `REQ-API-03` — one slot per call, the six text kinds |
| `DELETE` | `…/versions/{vid}/slots/{kind}/{key}` | `REQ-API-04` — undo, restores `llm_text`, keeps the record |
| `GET` | `…/versions/{vid}/flowcharts/{fcId}/labels` | `REQ-API-02` — every node label of one flowchart |
| `PUT` | `…/versions/{vid}/flowcharts/{fcId}/labels` | `REQ-API-08` — the changed labels of one flowchart |

Pagination on the list is not optional: a version has roughly **57,000 slots**.

`PUT` is last-write-wins (`REQ-API-07`) — no version token, no conflict response.

### 11.1 The flowchart endpoint

`{fcId}` is the function's `entity_key`, base64url-encoded via `slot.encode()` (`REQ-ID-04`). A raw
`entity_key` contains `|`, `:`, `,`, `*` and spaces, so it does not go in a path segment unencoded.

```http
PUT …/versions/v3/flowcharts/{fcId}/labels
{ "labels": { "n7": "Check write-protect flag", "n9": "Increment retry count" } }
```

**Only changed labels.** The whole flowchart is not submitted. A stale copy of an untouched label
would overwrite a correction someone else made to *that* label seconds earlier, and the server
cannot distinguish an unchanged label from a deliberate revert — `REQ-API-07`'s "last write wins"
was agreed **per slot**, and sending only what changed is what keeps it meaning that.

**All or nothing.** Every label is validated before any is written; one bad node fails the call and
names itself in the response. This is `REQ-AP-02` at flowchart scope: the re-render must not run
against a partial edit.

Rejections, from `override_service`: `EmptyText` → 422, `SlotUnknown` → 404 (naming the node),
`NotEditableHere` → 501 until the model-home item in [Open items](#open-items) is resolved.

The response carries `renderPending` so the UI can show that an image is still being produced.

---

## 12. Prerequisites

Both are independent of this feature and fix defects that exist today.

### 12.1 `REQ-PRE-01` — unit and struct descriptions into Phase 2

Currently generated **during DOCX export and discarded**:

- `docx_exporter.py:371` — *"typedef struct: description from name + fields (on the go, no store)"*
- `docx_exporter.py:1074` — `get_unit_description(...)` called inline

Move both into `model_deriver.py`, store them (unit description on `model_units`, struct description
in the type entity's payload), and have the exporter read rather than generate.

Side effects beyond this feature: the HTML view can show them at all, and every export stops
re-paying for the LLM calls with possibly different wording each time.

### 12.2 `REQ-PRE-02` — view output read from the database

Storage is done (`persist_output_files`). **Reading** is not: `docx_exporter` takes a `json_path`,
the flowchart engine takes `--interface-json`, and the SWE.4 views read the flowcharts directory.

Note `PgStore.capture_output` swallows its own failures (`except Exception: pass` — *"best-effort,
disk output is intact"*), so disk and database can disagree today with nothing reporting it.
[tests/live/test_output_in_db.py](../../tests/live/test_output_in_db.py) already checks this.

---

## 13. Build order

Each step leaves the tree working and is independently useful.

| # | step | why here |
|---|---|---|
| 1 | ~~`REQ-PRE-01` — descriptions into Phase 2~~ **DONE** | two of the seven slot kinds cannot exist until this lands |
| 2 | ~~Schema + migration + `slot.py`~~ **DONE** | nothing else compiles without addressing |
| 3 | ~~`override_service` — write + re-derive, no cascade~~ **DONE, 5 of 7 kinds** | the smallest end-to-end slice: edit → HTML → DOCX |
| 3b | **A model home for `nodeLabel` and `behaviourDescription`** | now blocking: it gates 2 of 7 kinds, the `REQ-ID-02` shape write, and the whole of `REQ-API-08` |
| 4 | The export guard | closes the `--from-phase 4` hole; independently valuable |
| 5 | API + undo, incl. the flowchart endpoint ([§11.1](#111-the-flowchart-endpoint)) | the UI can be built against it |
| 6 | Cascade | correctness improvement on a working feature |
| 7 | Images | the slowest and most isolated part |
| 8 | Carry-forward into the next version | needs a second version to test against |
| 9 | `REQ-PRE-02` — read output from the database | large, independent; removes the last disk dependency |

Steps 1 and 9 can be done by someone else in parallel — they touch different files from 2–8.

**Step 3b was not in the original order.** It surfaced building step 3: `nodeLabel` and
`behaviourDescription` have no model field, so there is nothing for an override to write to. It
was a gap before `REQ-API-08`; it is a blocker now, because the flowchart endpoint is the one
`REQ-API-08` describes and `nodeLabel` is the kind it carries.

---

## 14. Testing

Unit tests for the pure parts; `tests/live/` for the database invariants, following the suite added
in September.

| requirement | test |
|---|---|
| `REQ-AP-04` | override → `reexport --from-phase 4` → DOCX carries the human text |
| `REQ-VR-01` | override in v3 → generate v4 → unchanged function shows human text |
| `REQ-VR-01` | changed function shows fresh LLM text, not the stale human note |
| `REQ-VR-02` | `llm_description_cache` is byte-identical after an override |
| `REQ-CS-01` | edit a description → unit description and direct callers regenerate |
| `REQ-CS-01` | …and node labels do **not** |
| `REQ-CS-02` | A ← B ← C: editing A regenerates B, leaves C |
| `REQ-CS-03` | a cascade does not overwrite a slot that has its own override |
| `REQ-ST-04` | N=3, five edits → original + newest three |
| `REQ-ST-06` | empty update rejected, every slot kind |
| `REQ-ID-03` | rename → override kept and flagged, not deleted |
| `REQ-IM-02` | edit a label, export immediately → exported image carries the new label |
| `REQ-AP-02` | a failure mid-save leaves model and views both unchanged |

**Each test must fail without its fix.** Every defect this codebase shipped in September passed code
review and was caught only by measurement; a test that cannot fail proves nothing.

---

## 15. Decisions and their reasons

Recorded so a future change knows what it would be undoing.

**The model is the single source of truth.** The alternative — writing the override into both the
model and the view rows — was rejected because two stores of one text is precisely the arrangement
that produced the September bugs: `interface_tables.json` holds a copy of `description` and the DOCX
reads the copy, so updating the model alone changes nothing in the document.

**Derive on write, not on read.** Deriving on every request would also give one source of truth, but
pays derivation cost on every page load. Deriving on write pays it once per edit, and edits are rare
(most of ~57,000 slots are never touched).

**The LLM cache is never written.** It has no `version_id` (keyed `project_id, namespace,
cache_version, entity_id, content_hash`), so human text there would leak into every version,
contradicting `REQ-ST-02`. It would also destroy the LLM original and make model output
indistinguishable from human text in the training data.

**Positional node ids, gated on the node list.** `n0, n1, n2…` are positions, not identities. An
earlier draft of this design said `source_hash` alone was enough because "unchanged source produces
an identical CFG" — that is false, and the flowchart label cache already knew it: identical source
renumbers when the CFG builder changes or when `cfgSimplification` merges nodes past the 15-node
threshold. So each `nodeLabel` override stores the node-id list it was made against and is only
reused when that still matches (`REQ-ID-02`).

A content hash of the node *text* as the identifier was considered and rejected: it collides on two
identical statements in one function, and it solves a different problem. `slot_shape` is not an
identifier — the id stays `n7`. It is a validity gate answering "is this still the same graph?".

**The API is per flowchart; the storage is per label.** These are different questions and they get
different answers. A version holds ~42,000 node labels, so a call per label would make the
flowchart the one screen whose save cost scales with how much the reviewer fixed — hence
`REQ-API-08`. But the *record* stays one row per label, because undo, history, the training pair
and the emptiness check all operate on one sentence. The rebuild is per flowchart too, which is
not a compromise: a PNG cannot be partly redrawn, so that was always the unit.

**One slot per node, not one per flowchart.** Storing a whole flowchart's labels as one override was
considered. It wins on exactly one point — atomic all-or-nothing reuse — which `slot_shape` gives
without it. It loses on four: undo would revert corrections the reviewer made separately and wanted
kept; the `REQ-TD-01` training pair degrades from one sentence to a blob that must be diffed to
recover what changed; the `REQ-ST-04` cap would count N edits per *flowchart* rather than per label;
and two reviewers correcting two nodes of one function would clobber each other through a
read-modify-write. Per node keeps `human_text` a plain string for all seven kinds.

The *invalidation* unit is still the whole flowchart — a PNG cannot be partly re-rendered — which is
what [§5](#5-re-deriving-the-views) and [§7](#7-images) already do.

**One level of caller cascade.** Transitive cascade is unbounded in a deep call graph — one edit
could regenerate hundreds of functions, each an LLM call. One level is predictable; a later full
regeneration picks up the rest.

**Orphaned overrides are kept.** Deleting a user's work automatically on a rename is not recoverable,
the rename may be reverted, and the text is training data either way.

**History is capped, the original is not.** Training needs the two ends — what the model wrote, what
the human settled on. The intermediate wording tweaks are the least valuable and are what the cap
drops.

---

## Open items

- [ ] **`nodeLabel` and `behaviourDescription` have no model field** — found building step 3. Their
      text lives only in Phase-3 view output (the flowchart JSON; `_behaviour_pngs.json`'s
      `_docxRows[].behaviorDescription`), so "write the override into the model" has nothing to
      write to, and writing it into the view output would be reverted by the next derivation —
      the two-copies arrangement `REQ-AP-01` exists to remove. `override_service` refuses both
      with `NotEditableHere` (501) rather than pretending. Two candidate fixes: give them model
      fields the way `REQ-PRE-01` did for unit/struct descriptions, or have the two views apply
      overrides at derivation time so the override table *is* the source. Blocks `REQ-ED-01` for
      2 of 7 kinds, and blocks `REQ-ID-02`'s `slot_shape` from ever being written.
- [ ] **`test_steps` is re-derived too narrowly.** `REQ-ED-03` makes a Test Step's wording a node
      label, and `test_steps._splice_callee` nests a *cross-unit* callee's steps under the step
      that calls it. So a `nodeLabel` edit in unit A changes unit B's Test Steps, and
      [§5](#5-re-deriving-the-views)'s "the flowchart JSON for that unit" would leave B stale.
- [ ] Default for `llm.overrideHistoryDepth`.
- [ ] Whether orphaned overrides need a cleanup command.
- [ ] Approval workflow — out of scope (`REQ-API-06`'s note); the schema leaves room for a state
      column without a migration of existing rows.
