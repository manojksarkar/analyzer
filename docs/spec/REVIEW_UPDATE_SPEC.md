# Review & Update Spec — correcting LLM text in a generated document

Update this doc first when changing review/update logic, then code + tests.
Design: TBD · Branch: `review_update_v1`

A reviewer reads the generated document in the UI. Where the LLM's wording is wrong, they correct
it. The correction is saved, shows immediately in the UI, appears in the exported DOCX, and carries
into the next version. The original LLM text is kept so a correction can be undone and, later, used
to improve the model.

Requirements are grouped by feature area. Each has a **Verification** line: this codebase has been
bitten repeatedly by writes that silently did not reach the document, so "the code looks right" is
not acceptance.

---

## Contents

- [Terms](#terms)
- [ED — What can be edited](#ed--what-can-be-edited)
- [ID — Identifying a slot](#id--identifying-a-slot)
- [ST — Storing an override](#st--storing-an-override)
- [AP — Making it appear](#ap--making-it-appear)
- [CS — Cascading regeneration](#cs--cascading-regeneration)
- [VR — Across versions](#vr--across-versions)
- [IM — Images](#im--images)
- [API — UI and API](#api--ui-and-api)
- [TD — Training data](#td--training-data)
- [PRE — Prerequisites](#pre--prerequisites)
- [Limitations](#limitations)
- [Open items](#open-items)

---

## Terms

**Slot** — a place in the document that holds LLM-written text (one function's description, one
flowchart node's label).

**Override** — the human's replacement text for a slot.

Scale, measured on a real project (`vis-aspice1` v1, 4321 functions with a payload): roughly
**57,000 slots per version** — ~13,000 stored fields, ~42,000 flowchart node labels, ~2,000 others.
Almost all are never edited, so the design must be cheap when a version has **zero** overrides.

---

## ED — What can be edited

### REQ-ED-01 — Seven kinds of slot

| kind | appears in |
|---|---|
| function description | 1.2 Scope table · interface table *Information* · per-function *Requirements* · SWE.4 intro |
| behaviour input name | per-function table · Dynamic Behaviour table |
| behaviour output name | same |
| behaviour description | Dynamic Behaviour *Requirements* + the behaviour diagram arrows |
| unit description | 1.2 Scope table (see [REQ-PRE-01](#req-pre-01--unit-and-struct-descriptions-must-be-stored-first)) |
| struct description | unit header table (see [REQ-PRE-01](#req-pre-01--unit-and-struct-descriptions-must-be-stored-first)) |
| flowchart node label | the flowchart picture **and** every SWE.4 Test Step |

**Verification:** every LLM call site in `engine/` maps to exactly one row here or to
[REQ-ED-04](#req-ed-04--text-that-is-not-editable).

### REQ-ED-02 — A behaviour description is edited as one block

It is a **list** of strings, one bullet per call arrow (`docx_exporter._add_behavior_description_table`
takes `behavior_description_list`). The whole list is edited together, not per bullet.

**Verification:** the API accepts and returns the list as a unit.

### REQ-ED-03 — SWE.4 Test Steps are read-only

A Test Step's wording **is** a flowchart node label — `test_steps.py` derives it from the CFG and
runs no LLM of its own. Editing a node label changes the flowchart picture and the Test Step
together. There is no second entry point.

**Verification:** editing a node label changes both documents; the SWE.4 view exposes no editable
slot of its own.

### REQ-ED-04 — Text that is not editable

Not offered for editing, because it never reaches a document: `pkb.function_phases`,
`pkb.function_summaries`, `pkb.file_summaries`, `pkb.component_summaries`, `pkb.project_summary`.
These are **context** for generating flowchart node labels.

Also not editable because it is not LLM-written: interface IDs, direction, source/destination,
visibility, data ranges (from the data dictionary), and the 1.1/1.2 introduction text (config
templates).

**Verification:** no slot is exposed for any of the above.

---

## ID — Identifying a slot

### REQ-ID-01 — Reuse the ids that already exist

No new identifier scheme where one exists.

| slot kind | id |
|---|---|
| function / struct description, behaviour in/out name | `entities.entity_key` — unique per project (`uq_entity_project_key`) |
| unit description | `model_units.unit_key` (`Component\|Unit`) |
| behaviour description | the row's `(currentFunctionId, externalUnitFunction)` |
| flowchart node label | `(version_id, entity_key, node_id)` |

**Verification:** a slot id resolves to the same slot across two generations of unchanged code.

### REQ-ID-02 — Flowchart node ids are positional, and that is sufficient

`cfg.nodes[].id` is `n0, n1, n2…`, assigned by walking the AST. It is therefore **deterministic for
identical source**: unchanged source ⇒ same tokens ⇒ same AST ⇒ same `n3`.

Carry-forward of a node override is allowed **only when the function's `source_hash` is unchanged** —
which is exactly when the ids are stable. A changed function regenerates its labels anyway.

**Verification:** parsing the same commit twice yields identical node ids; a node override does not
carry forward when `source_hash` differs.

### REQ-ID-03 — Rename and delete orphan an override, and it is kept

A renamed function gets a new `entity_key`, so the override no longer resolves. A deleted function
leaves its override pointing at nothing.

In both cases the override row is **kept and marked orphaned** — never auto-deleted. It is the
user's work and it is training data, and a rename may be reverted. Cleanup is a separate, explicit
operation.

**Verification:** renaming a function leaves its override present and flagged, not removed.

---

## ST — Storing an override

### REQ-ST-01 — Stored in the database, beside the model

Two things, with different jobs:

```
the MODEL           holds the text the document uses      (an override updates it)
the OVERRIDE record holds the LLM original + the human text + who + when
```

**Verification:** after an override, the model carries the human text and the override record
carries both texts.

### REQ-ST-02 — An override belongs to one version

Editing v3 does not change v1's document. A released version does not change retroactively.

**Verification:** an override on v3 leaves v1's export byte-identical.

### REQ-ST-03 — Keep both texts

The LLM's original and the human's replacement. Without the original there is no undo
([REQ-API-04](#req-api-04--undo-restores-the-llm-original)) and no training pair
([REQ-TD-01](#req-td-01--corrections-are-stored-as-pairs)).

**Verification:** the original is readable after any number of edits.

### REQ-ST-04 — History is bounded and configurable

Every edit is recorded. Beyond a configurable **N** human edits per slot, the oldest human edits are
dropped.

**The LLM original is never evicted** — it is not counted against N. Training needs the two *ends* of
the pair (what the model wrote, what the human settled on); the intermediate wording tweaks are the
least valuable part and are the right thing to drop.

**Verification:** with N=3 and five edits, the original plus the newest three remain.

### REQ-ST-05 — Reading the current text does not depend on history size

The current text is a direct lookup, not "the newest row in history". It is read on every page
render.

**Verification:** read cost is unchanged between a slot with one edit and a slot with N.

### REQ-ST-06 — No editable text may be set to empty

Applies to every slot kind, not just descriptions.

**Verification:** an empty or whitespace-only update is rejected.

---

## AP — Making it appear

### REQ-AP-01 — The model is the single source of truth

View outputs (interface tables, flowcharts, behaviour rows) are **derived** from the model and are
never written to directly.

This is the fix for a defect that exists today: `interface_tables.json` holds a **copy** of
`description` (`interface_tables.py:155`), and the DOCX exporter reads the copy, not the model
(`docx_exporter.py:1` — *"Export interface_tables.json -> Software Detailed Design DOCX"*). Updating
only the model changes nothing in the document.

**Verification:** nothing but the derivation writes a view output row.

### REQ-AP-02 — Saving an override is one operation

It updates the model **and** re-derives the affected component's view rows. It must not be able to
half-succeed.

`interface_tables.run(model, output_dir, model_dir, config)` is a pure function of the model plus
config and already scopes to components via `_analyzerAllowedComponents`, so re-deriving one
component is cheap — no LLM, no parse.

**Verification:** a failure mid-save leaves the model and the view rows both unchanged.

### REQ-AP-03 — The UI shows it on the next page load

The HTML view renders live from the database per request (`render_document` → `ModelReader` +
`OutputReader`). No re-render step is needed.

**Verification:** an override is visible in the rendered payload without any pipeline run.

### REQ-AP-04 — Export verifies rather than assumes

Before exporting, check that no override is newer than the last derivation. If one is, re-derive
first or refuse and say so.

This is what makes the feature reliable rather than merely correct. `analyzer.py reexport
--from-phase 4` is *"export only"* — it **skips Phase 3**, which is what rebuilds the view rows from
the model. Without this check it ships the previous text, silently. Moving the data from files into
the database does **not** fix this: it is still the row Phase 3 wrote last time.

**Verification:** override, then `reexport --from-phase 4`; the DOCX carries the human text.

---

## CS — Cascading regeneration

Some LLM text is generated **from** other LLM text. Correcting the input must regenerate what was
built on it, or the document keeps prose derived from wording the human has already rejected.

Four chains exist. Traced from each generator's inputs:

```
1  callee description            -> function description      get_description(source, callee_descriptions, …)
2  function + global descriptions -> unit description          get_unit_description(unit, fn_items, gv_items, …)
3  caller + callee descriptions   -> behaviour call description _build_call_context()
4  source -> function summary -> file summary -> component summary -> project summary -> node labels
```

**Chain 4 starts from the SOURCE, not from descriptions** — `_summarize_function_batch` builds its
prompt from the signature and body and never reads `description`. This is what keeps the cascade
small: editing a description does **not** invalidate the ~42,000 flowchart node labels.

### REQ-CS-01 — What regenerates when a slot is edited

| edited | regenerates |
|---|---|
| function description | its unit's description · the descriptions of its **direct callers** · behaviour call descriptions where it is caller or callee |
| global description | its unit's description |
| unit description | nothing |
| struct description | nothing |
| behaviour in/out name | nothing — built from source, params, globals, return type |
| behaviour description | nothing |
| flowchart node label | nothing — the summary chain feeds *into* labels, not out |

**Verification:** editing a function description changes its unit description and its direct
callers' descriptions, and leaves node labels untouched.

### REQ-CS-02 — Caller cascade is one level only

Correcting A regenerates its direct callers. It does **not** continue transitively to their callers.

Full transitivity could regenerate hundreds of functions from one edit, each an LLM call, with the
effect growing without bound in a deep call graph. One level is predictable and bounded; a later full
regeneration picks up the rest naturally.

**Verification:** with A ← B ← C, editing A regenerates B and leaves C unchanged.

### REQ-CS-03 — A regenerated slot does not overwrite its own override

If a cascade would regenerate a slot that already has a human override, the override wins and is not
replaced.

**Verification:** override B, then edit A; B keeps the human text.

---

## VR — Across versions

### REQ-VR-01 — Unchanged code keeps the human text

Generating a new version from a baseline: a function whose `source_hash` is **unchanged** keeps the
human text; a function whose code **changed** gets fresh LLM text describing the new code.

**Verification:** override in v3, generate v4 from v3; an unchanged function shows the human text and
a changed function does not.

### REQ-VR-02 — This works through the model, not the LLM cache

The carry-forward copies from the baseline's stored **model** (`engine.py:130`
`tg["description"] = bg["description"]`), and cross-version reuse copies from another version's model
(`engine.py:163`). Neither reads `llm_description_cache`.

The cache is **not written to** by this feature. Writing human text there would destroy the LLM
original, leak across versions (the cache has no `version_id` — it is keyed
`project_id, namespace, cache_version, entity_id, content_hash`), and make model output
indistinguishable from human text in the training data.

**Verification:** after an override, `llm_description_cache` is unchanged; v4 still shows the human
text.

### REQ-VR-03 — A full regeneration uses fresh LLM text, and keeps the overrides

`--full` has no baseline (`generate_full` takes no `base_version_id`), so it produces fresh LLM text.
Overrides are **kept, not deleted** — they are simply not applied to that version.

`--full` is the recommended remedy for several problems, so it must never destroy a reviewer's work.

**Verification:** `--full` after overrides leaves every override row present.

---

## IM — Images

### REQ-IM-01 — An edit re-renders the affected image

Editing a flowchart node label re-renders that flowchart's PNG; editing a behaviour description
re-renders that behaviour diagram. Rendering is asynchronous.

**Verification:** after the render completes, the PNG differs from the pre-edit one.

### REQ-IM-02 — Export waits for pending renders

Export does not start while a render triggered by an override is still outstanding.

Without this, an export a second after an edit ships the new text everywhere and the old picture.

**Verification:** edit a label, export immediately; the exported image carries the new label.

### REQ-IM-03 — The document never shows a stale image

**Verification:** no rendered document contains an image older than the override that changed its
source.

---

## API — UI and API

### REQ-API-01 — List the slots in a document

With each slot's id, current text, and whether it is overridden.

**Verification:** the list covers every slot kind in [REQ-ED-01](#req-ed-01--seven-kinds-of-slot).

### REQ-API-02 — Read one slot's current text

So the UI can confirm an update landed.

**Verification:** after an update, the read returns the new text.

### REQ-API-03 — Update one slot

One slot per call. A reviewer edits one piece of text at a time; there is no batch operation.

**Verification:** an update to one slot leaves every other slot unchanged.

### REQ-API-04 — Undo restores the LLM original

**Verification:** after undo, the document shows the LLM's text and the override record survives.

### REQ-API-05 — Permissions

Anyone who can view the document can read the text. Project admins and project members may edit.

**Verification:** a non-member's update is rejected.

### REQ-API-06 — Corrected text is not highlighted

It reads as ordinary document text. A user may re-edit any slot any number of times.

**Verification:** the rendered document carries no visual marker for an overridden slot.

### REQ-API-07 — Last write wins

Two people editing the same slot: the later write is kept. No locking, no conflict error.

**Verification:** two updates in sequence leave the second.

---

## TD — Training data

Nothing is trained or self-learned in this feature. This is storage only, shaped so it is usable
later.

### REQ-TD-01 — Corrections are stored as pairs

What the LLM wrote **and** what the human replaced it with. A correction without its original teaches
nothing — "right" with no "wrong" carries no signal.

**Verification:** every override record yields both texts.

### REQ-TD-02 — Store the context and the provenance

The context the LLM was given, and which model and prompt version produced the original
(`llm.cacheVersion` already exists). Without them a correction cannot be interpreted after a prompt
change.

**Verification:** an override record identifies the model and prompt version of its original.

---

## PRE — Prerequisites

Separate pieces of work this feature depends on.

### REQ-PRE-01 — Unit and struct descriptions must be stored first

Both are generated **during DOCX export and stored nowhere**:

- `docx_exporter.py:371` — *"typedef struct: description from name + fields (on the go, no store)"*
- `docx_exporter.py:1074` — `get_unit_description(...)` called inline in the exporter

Two consequences beyond this feature: the HTML view cannot show them at all, and every export re-pays
for them, possibly with different wording each time.

They must move into Phase 2 and be stored before they can be edited.

**Verification:** both appear as stored model fields after Phase 2, and the exporter reads rather
than generates them.

### REQ-PRE-02 — View output moves into the database

`output/` keeps only `.png` and `.docx`; every flow, including export, reads its text from the
database.

Largely done for **storage** — `persist_output_files` already stores `.json .mmd .txt .md .csv .dot
.svg .html`. Not done for **reading**: the DOCX exporter takes a `json_path`, the flowchart engine
takes `--interface-json`, and the SWE.4 views read the flowcharts directory.

Note the storage path swallows its own failures (`except Exception: pass` — *"best-effort, disk
output is intact"*), so disk and database can disagree today with nothing reporting it.

**Verification:** `tests/live/test_output_in_db.py` passes, and an export succeeds with no `.json`
or `.mmd` under `output/`.

---

## Limitations

- An override is orphaned by a rename or a delete. It is kept, not migrated — the new text cannot be
  assumed still correct for a renamed function.
- The caller cascade is one level. A deep chain is only fully refreshed by a later full regeneration.
- An override is not carried forward when the function's source changed, by design — the human text
  describes the old code.
- Corrected text is not visually distinguished, so a second reviewer cannot tell what has already
  been corrected. This becomes relevant when the approval step is added.

---

## Open items

- [ ] Approval workflow — an edit currently takes effect immediately. The intended flow (request →
      project manager approves) is **out of scope** for this version.
- [ ] Default for **N** in [REQ-ST-04](#req-st-04--history-is-bounded-and-configurable).
- [ ] Whether orphaned overrides ([REQ-ID-03](#req-id-03--rename-and-delete-orphan-an-override-and-it-is-kept))
      need a cleanup command, or accumulate harmlessly.
- [ ] Design document — none yet.
