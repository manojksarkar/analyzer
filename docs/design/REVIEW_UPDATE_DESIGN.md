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
- [5. Re-deriving the views](#5-re-deriving-the-views)
- [6. The cascade](#6-the-cascade)
- [7. Images](#7-images)
- [8. Reading: HTML and DOCX](#8-reading-html-and-docx)
- [9. The export guard](#9-the-export-guard)
- [10. Carrying overrides into the next version](#10-carrying-overrides-into-the-next-version)
- [11. API](#11-api)
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

One Alembic revision under [alembic/](../../alembic/). Additive only — no existing table changes, so
it is safe to apply ahead of the code.

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
| `behaviourDescription` | `<functionId>\|<externalUnitFunction>` | the `_docxRows` entry |
| `nodeLabel` | `<entity_key>#<node_id>` | `cfg.nodes[].id` |

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
re-renders. **The DOT is never edited directly** — it is generated syntax, and the SWE.4 Test Steps
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
       and (slot is not nodeLabel or the function's source_hash is unchanged):   REQ-VR-03
        copy the row to the new version
```

A changed function does not carry its override: the human text describes code that no longer exists.
Fresh LLM text is correct there (`REQ-VR-01`).

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
| `PUT` | `…/versions/{vid}/slots/{kind}/{key}` | `REQ-API-03` — one slot per call |
| `DELETE` | `…/versions/{vid}/slots/{kind}/{key}` | `REQ-API-04` — undo, restores `llm_text`, keeps the record |

Pagination on the list is not optional: a version has roughly **57,000 slots**.

`PUT` is last-write-wins (`REQ-API-07`) — no version token, no conflict response.

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
| 1 | `REQ-PRE-01` — descriptions into Phase 2 | two of the seven slot kinds cannot exist until this lands |
| 2 | Schema + migration + `slot.py` | nothing else compiles without addressing |
| 3 | `override_service` — write + re-derive, no cascade | the smallest end-to-end slice: edit → HTML → DOCX |
| 4 | The export guard | closes the `--from-phase 4` hole; independently valuable |
| 5 | API + undo | the UI can be built against it |
| 6 | Cascade | correctness improvement on a working feature |
| 7 | Images | the slowest and most isolated part |
| 8 | Carry-forward into the next version | needs a second version to test against |
| 9 | `REQ-PRE-02` — read output from the database | large, independent; removes the last disk dependency |

Steps 1 and 9 can be done by someone else in parallel — they touch different files from 2–8.

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

**Positional node ids are sufficient.** They renumber when code changes — but an override only
carries forward when `source_hash` is unchanged, and unchanged source produces an identical CFG. A
content hash of the node text was considered and rejected as solving a problem the `source_hash` gate
already closes, at the cost of a collision case (two identical statements in one function).

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

- [ ] Default for `llm.overrideHistoryDepth`.
- [ ] Whether orphaned overrides need a cleanup command.
- [ ] Approval workflow — out of scope (`REQ-API-06`'s note); the schema leaves room for a state
      column without a migration of existing rows.
