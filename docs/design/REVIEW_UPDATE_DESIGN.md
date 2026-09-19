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
  - [5.1 Text that Phase 3 produces](#51-text-that-phase-3-produces)
  - [5.2 Applying a correction without running Phase 3](#52-applying-a-correction-without-running-phase-3)
  - [5.3 What stays broken, deliberately](#53-what-stays-broken-deliberately)
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
| `behaviourDescription` | `<functionId>` ␁ `<externalCallerId>` | the `_docxRows` entry — **both entity keys**, see `REQ-ID-01` |
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

### 5.1 Text that Phase 3 produces

`REQ-AP-05`. Five kinds are model fields and follow §4: write the model, re-derive the view. The
other two are made *during* Phase 3 and have no model field:

| kind | where it is made | where it lands |
|---|---|---|
| `nodeLabel` | the flowchart engine subprocess | `cfg.nodes[].label` in the unit's flowchart JSON |
| `behaviourDescription` | `MermaidBuilder` while building arrows | `_docxRows[].behaviorDescription` |

For these, **the override table is the source and the correction is an input to Phase 3.** Not a
patch applied to Phase 3's output — the next run would rebuild that output from the CFG, ask the
LLM again, and drop the correction with no error.

```
                      text_overrides  (the only home for these two kinds)
                             │
                             ▼  handed in, like knowledge_base.json
   source ──► flowchart engine ──► CFG with corrected labels ──► DOT ──► PNG
                                                             └─► flowchart JSON
```

**One module owns the mapping**, `engine/review/phase3_overrides.py`:

```python
APPLIED_AT_DERIVE = {
    NODE_LABEL:            Target("flowcharts",       "cfg.nodes[].label",  key=node_id),
    BEHAVIOUR_DESCRIPTION: Target("behaviourDiagram", "_docxRows[].behaviorDescription", …),
}
```

with a test asserting every kind in `slot.ALL_KINDS` is either model-backed (`resolver._HOMES`) or
here — the same coverage shape as `derive.views_for`. A kind that is in neither would save fine and
never appear, which is the failure mode this whole design is built against.

**Why this does not disturb the pipeline.** A view still takes its inputs and writes its own
output; it gains one more input. Phase boundaries are untouched — which matters, because Phase 3
runs per group and is the phase that parallelises. The alternative considered, moving label
generation into Phase 2 so labels become model data, was rejected for exactly this: it would take
the largest LLM cost in the system (~42,000 labels, ~10,000 calls) out of the parallel phase and
make it a serial, global one. See [§15](#15-decisions-and-their-reasons).

**Two mechanisms already exist**, so this is assembly rather than invention:

- Phase 3 already passes `knowledge_base.json` into the flowchart subprocess
  (`views/flowcharts.py`), so the delivery route is established.
- `flowchart_engine._apply_cached_labels` already pastes a `{node_id: label}` map onto a fresh CFG
  **and rejects it unless the node-id set matches exactly** — the same guard as `slot_shape`. A
  human correction is a second, higher-priority source into that path, and inherits the guard.

### 5.2 Applying a correction without running Phase 3

`REQ-AP-06`. A save must be instant, so it re-parses nothing:

```
read that flowchart's CFG from the stored JSON      already in version_output_files
set cfg.nodes[n].label for each corrected node
rebuild the DOT from the corrected CFG              pure function, no LLM
re-render the PNG                                   Graphviz; redo tall-PNG slicing
re-derive the component's SWE.4 specs               REQ-CS-04, no LLM
write the flowchart JSON row back
```

No libclang, no LLM, no flowchart subprocess, and **no C++ source required** — which is what lets a
correction be saved from a machine that does not have the tree checked out.

**The DOT is regenerated, never patched.** Labels are line-wrapped and escaped on the way into the
DOT, so a corrected label of a different length needs re-wrapping. Editing the DOT text would put
those rules in a second place to drift from the first. Editing the CFG also keeps the picture and
the SWE.4 Test Steps in step, since the Test Steps read the CFG.

**Slicing must be redone.** A corrected label can change the picture's height, so a graph written
as `_part_1_of_3` may become `_part_1_of_2` and the orphan `_part_3_of_3.png` must go —
`_cleanup_stale_slice_parts` exists because this has been a defect once already.

**A behaviour-description edit renders nothing.** `MermaidBuilder` labels each arrow
`<callee>()` — the function's name — and appends the description to a separate list. The text is
not in the picture, so only the `_behaviour_pngs.json` row changes. (An earlier draft of
[§7](#7-images) said otherwise.)

#### The second writer, and how it is kept honest

§5 states that nothing but a `VIEW_REGISTRY` call writes a `version_output_files` row. The save path
above breaks that: it updates one row without running a view, and it cannot run the view instead,
because `persist_output_files` deletes every row for the version and rebuilds from a full
`output_dir` walk — it has no single-row form, and a save has no output dir.

Rather than leave the invariant quietly false, it is restated:

> A `version_output_files` row is written by `persist_output_files` (after a view runs) or by
> `review.rerender.write_flowchart_json` — **and by nothing else**. Both call one shared writer.

Enforced by a test that greps `engine/` and `api/` for other writers, the same way
`test_unit_struct_descriptions_stored` greps the exporter for LLM calls. An invariant nobody checks
is a comment.

### 5.3 What stays broken, deliberately

`test_steps._load_cfgs` reads the **flowcharts view's output directory** and returns `{}` — "no
steps", not an error — when it is absent:

```python
fc_dir = os.path.join(output_dir, "flowcharts")
if not os.path.isdir(fc_dir):
    return {}
```

A view reading another view's output, and silently emptying every Test Step if that view did not
run. Real, and older than this feature. Moving CFGs into the model would have fixed it as a side
effect; this design does not, and does not make it worse. Logged in [Open items](#open-items) as
its own fix.

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
nothing — `REQ-CS-01`'s table is the whole list. (An earlier draft of this line cited `REQ-CS-04`–`07`, which were never written; the cases were collapsed into that table.)

**The dependents are RECORDED, not regenerated where the correction is saved** — a deviation from
this section's first draft, for two reasons that were checked rather than assumed:

* `get_description` needs the function's **source**, and the source is not in the model; it is in
  the git checkout. The host saving a correction is not guaranteed to have one.
* regenerating is an LLM call, and saving a sentence must not take minutes.

Skipping it instead is not available either: the description cache is keyed on the callee's source
plus its dependency hashes (`llm_core.cache.compute_hash`), and correcting a *description* changes
neither — so the next run hits the cache and the caller keeps its stale wording for ever.

So `cascade.dependents_of` computes the set (cheap, indexed, exact) and `cascade.enqueue` records it
in `regeneration_queue`. A run with a checkout and an LLM consumes it, calling the same generators
the pipeline uses — `get_description`, `get_unit_description`, `CallDescriptionGenerator` — so
wording stays consistent with a normal run.

**A dependent that already has its own override is skipped** (`REQ-CS-03`). The human's text is never
replaced by a regeneration.

### 6.1 Paying the debt

The queue is drained in **two places**, because its kinds live in different phases:

| kind | where | how |
|---|---|---|
| `description`, `unitDescription` | Phase 2, `model_deriver._take_regeneration_queue` | blank the stale text; the enrichment rewrites it |
| `behaviourDescription` | Phase 3, `run_views._retire_behaviour_regenerations` | the behaviour view rebuilds every row it writes, so running it IS the regeneration |

**No force-regenerate switch exists, and none is needed.** `_enrich_from_llm` already documents
that function descriptions "skip when already present (the engine carries them forward)", so
removing the stale text *is* the instruction to generate it again. Adding a second way to say that
would be two expressions for one fact.

**Only what came back is retired.** An entry whose slot is still empty after the enrichment means
the regeneration did not happen — the LLM was unreachable, or `llm.descriptions` is off — and
clearing it would convert "still owed" into "done". An entry whose slot has left the version
entirely *is* retired, or it would be retried for ever against something that is not there.

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

A `behaviourDescription` override renders **nothing**. `MermaidBuilder` labels each arrow
`<callee>()` — the function's name — and appends the description to a separate list that becomes
`_docxRows[].behaviorDescription`. The text is not in the picture, so only that row changes. An
earlier draft of this section said it re-renders the diagram; it does not, and queueing a render
for it would be wasted work (`REQ-IM-01`).

### 7.2 Execution

`engine/review/render_queue.py` and a `render_jobs` row per picture owed. **No daemon thread was
added.** The row, not a thread, is what the design actually needed: a durable answer to "is this
version's picture current" that an export on *another host* can read. A thread would have given a
faster redraw on one host and no answer anywhere else.

So the render runs inline when the saving host has an output tree — the job is `done` before the
response is sent — and otherwise stays `pending` until `run_pending` is called where the tree
lives. Both paths write the same rows.

`run_pending` re-reads the **current** CFG rather than anything carried on the job: by the time it
runs the flowchart may have been corrected again, and the picture must match what the document will
show, not what was true when the job was made.

It is called from `incremental/store.py::capture_output`, right after that host has written the
version's output into a tree it owns — the first moment both the job and the resources to satisfy
it are in the same place. Nothing runs it on a timer, deliberately: a schedule would be a second
way for a picture to appear, and the export already blocks until the job is done.

Two corrections to one flowchart make **two** jobs. Collapsing them would let a render that began
before the second edit satisfy it, leaving the picture one edit behind with nothing pending to say
so. Rendering twice is cheap by comparison: `render_dot_cached` is content-addressed, so the second
is a file copy when the graph has not changed again.

### 7.3 Pending renders and export

Export waits (`REQ-IM-02`). A render job is `pending` until its PNG is written; export blocks while
any `pending` job exists for the version — reported by `export_guard.staleness` alongside the text
check, so the CLI and the API ask one question and get one answer.

**A `failed` render does not block.** It cannot be waited for, and blocking on it would make one
unrenderable flowchart permanently unexportable — a cure worse than the disease. It is surfaced
instead, through `failed_renders` and `explain()`, so the document goes out with somebody knowing
the picture is stale rather than nobody.

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
rebuilds the view rows from the model. Only phase 4 is gated: phases 2 and 3 re-derive on the way
through, so refusing them would block the very command that fixes the problem. `--force` exports
anyway, because a guard with no override is one people route around by other means.

**The baseline.** `view_derivations` has to be written by ordinary runs, not only by the override
path, or the first correction to any version would report it stale for ever — there would be
nothing to compare against. `incremental/store.py::capture_output` stamps it, that being the one
point Phase-3 output reaches the database. It writes `view_name = "*"` (`export_guard.PIPELINE_ALL`)
for the whole group: Phase 3 runs as a subprocess and the capture point does not know which
individual views ran, so naming them there would invent precision this code does not have. The
guard needs `min(derived_at)`, which is correct either way.

**Absence of evidence counts as stale.** Corrections with no derivation row at all is not proof of
freshness. A guard that reads "no data" as "fine" is the guard that does not guard.

**Pending renders are not part of the check yet** — `render_jobs` arrives with step 7. Without this guard it ships the previous text, silently.
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

Built as `engine/review/carry_forward.py`. Three things it does that the pseudocode above does not
say:

**The shape is not carried onto the new row.** It describes the graph the text was written against,
and that graph belongs to the baseline. Copying it would let the *next* version's carry-forward
check a correction against a shape nothing ever verified for it.

**An orphan carries a reason.** A reviewer whose correction stopped applying is owed an
explanation — "that function's code changed", "the flowchart was renumbered even though the code did
not" — rather than a silent disappearance.

**A correction already made against the target wins.** It is newer than anything the baseline can
offer, so carry-forward leaves it alone.

`overrides_for_config` then builds what a Phase-3 run feeds to
[§5.1](#51-text-that-phase-3-produces)'s `from_config`. Only the two Phase-3 kinds appear in it: the
other five are in the model already, carried there by the engine's own `carry_forward_globals`, and
Phase 3 derives from the model — putting them in both places would be the second copy this design
exists to avoid.

`--full` has no baseline, so nothing is carried and the overrides simply are not applied
(`REQ-VR-03`) — **they are not deleted**. `--full` is the standing remedy for several problems and
must never destroy a reviewer's work.

---

## 11. API

Built. The HTTP contract the UI is written against lives in
[REVIEW_UPDATE_API_SPEC](../spec/REVIEW_UPDATE_API_SPEC.md), and
`tests/unit/test_review_api_contract.py` fails if a documented route is not served.

**Undo is an ordinary edit whose text happens to be the LLM original** (`REQ-API-04`), not a
separate state. The row survives with both texts and its history, re-applying it during a
Phase-3 run writes the LLM's own words back (a no-op), and `REQ-TD-01`'s rule that a training
export skips pairs whose texts are equal already excludes it. Refused with 409 when the slot
was empty before the first correction, since `REQ-ST-06` forbids writing empty text and
deleting the row instead would destroy the user's work to express "there was nothing here".

**`GET .../overrides` is an overlay, not a slot enumeration.** `REQ-API-01` asks for the
document's slots with their text; a version has ~57,000, so the endpoint returns only the
corrected ones and the UI merges them by `slotKey` into the document it already fetched.

Router `api/routes/text_overrides.py`, following the conventions in
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
| 4 | ~~The export guard~~ **DONE** | closes the `--from-phase 4` hole; independently valuable |
| 5 | ~~API + undo, incl. the flowchart endpoint ([§11.1](#111-the-flowchart-endpoint))~~ **DONE** | the UI can be built against it |
| 6 | ~~Cascade~~ **DONE (recording half)** | correctness improvement on a working feature |
| 6b | ~~Consume the queue during a run~~ **DONE** | needs a checkout and an LLM, so it belongs to the pipeline |
| 8b | ~~Wire carry-forward + the Phase-3 payload into a run~~ **DONE** | the pieces were built and tested but nothing called them |
| 7 | ~~Images~~ **DONE** | the slowest and most isolated part |
| 8 | ~~Carry-forward into the next version~~ **DONE** | needs a second version to test against |
| 9 | `REQ-PRE-02` — read output from the database | large, independent; removes the last disk dependency |

Steps 1 and 9 can be done by someone else in parallel — they touch different files from 2–8.

**Step 3b was not in the original order.** It surfaced building step 3: `nodeLabel` and
`behaviourDescription` have no model field, so there is nothing for an override to write to. It
was a gap before `REQ-API-08`; it is a blocker now, because the flowchart endpoint is the one
`REQ-API-08` describes and `nodeLabel` is the kind it carries.

---

### 13.1 Where the pipeline calls this feature

Two call sites, both deliberately thin — everything beneath them is tested on its own:

| what | where | why there |
|---|---|---|
| `carry_overrides` | `incremental/engine.py::_carry_review_overrides`, beside `carry_forward_globals` | the two belong together: one moves the words, the other the record of who wrote them |
| `config_with_overrides` | `run_views.py::_with_text_overrides`, immediately before `run_views(...)` | the RUNNER attaches them, so a view stays a pure function of `(model, config)` and never opens a database |
| `stamp_pipeline_derivation` | `incremental/store.py::capture_output` | the one point Phase-3 output reaches the database |
| `assert_exportable` | `analyzer.py::cmd_reexport` | before the subprocess, so a stale export is refused rather than produced |

Both new call sites are **non-fatal**. A generation that has already paid for the parse and the LLM
must not be lost because corrections could not be copied or loaded — they are logged, and the
corrections stay where they are for a later run.

`tests/unit/test_review_pipeline_wiring.py` checks each call site exists, that it runs at the right
point, and — in `TestEveryPieceHasACaller` — that no piece of the feature is left with no caller by
accident. It also asserts that `run_pending` and the regeneration-queue consumer still have **none**,
so when one acquires a caller the docs listing them as missing fail with it.

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

**Phase 3's text is corrected at Phase 3, not moved into the model.** `nodeLabel` and
`behaviourDescription` are made while the view is built, so they have no model field. The
alternative was to give them one — move flowchart label generation into Phase 2 so labels become
model data like descriptions. That was rejected, and not on effort:

- **It would fight the threading plan.** Phase 3 runs once per group, so it is the phase that
  parallelises. Flowchart labels are the largest LLM cost in the system — ~42,000 labels, ~10,000
  calls. Moving them into Phase 2 takes the most expensive work out of the parallel phase and makes
  it serial and global.
- **Phase 3 cannot write the model instead.** It runs per group, so the model would hold whichever
  groups happened to run — complete or partial depending on what was last generated.
- **It would also cost scoping.** Phase 2 has no component scoping (`model_deriver.py` and
  `parser.py` contain none); five Phase-3 views do. Generating one component's document would start
  paying for every component's labels.

What it would have bought — one uniform rule, and a fix for `test_steps` scraping the flowcharts
view's output — is real. The first is recovered by `REQ-AP-05` stating a single rule that covers
both cases (*a correction is applied where the text is produced*). The second is a separate,
independent fix, logged in [Open items](#open-items).

And for these two kinds the chosen design keeps **fewer** copies of the human text than the
alternative would: under a model home the correction would sit in the model *and* in the override
row, while here the override table is its only home and every rebuild re-applies it.

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

- [x] ~~**`nodeLabel` and `behaviourDescription` have no model field**~~ — **resolved**: they keep no
      model field; the override table is their source and the correction is an input to Phase 3
      (`REQ-AP-05`, [§5.1](#51-text-that-phase-3-produces)). The rejected alternative and why is in
      [§15](#15-decisions-and-their-reasons).
- [ ] **`test_steps` reads another view's output** — `_load_cfgs` opens `output_dir/flowcharts/` and
      returns `{}` when it is missing, so every Test Step silently empties if the flowcharts view
      did not run. Predates this feature and is not made worse by it; needs its own fix, most likely
      by passing the CFGs in rather than scraping the directory.
- [x] ~~**`test_steps` is re-derived too narrowly**~~ — **resolved**: a node label edit re-derives
      every SWE.4 spec in the component (`REQ-CS-04`). The spec view calls no LLM, so this is cheap
      and correct by construction rather than dependent on a transitive traversal being right.
- [ ] Default for `llm.overrideHistoryDepth`.
- [ ] Whether orphaned overrides need a cleanup command.
- [ ] Approval workflow — out of scope (`REQ-API-06`'s note); the schema leaves room for a state
      column without a migration of existing rows.
