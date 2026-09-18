# Review & Update Spec — correcting LLM text in a generated document

Update this doc first when changing review/update logic, then code + tests.
Design: [REVIEW_UPDATE_DESIGN](../design/REVIEW_UPDATE_DESIGN.md) · Branch: `review_update_v1`

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

Stored as one text with the bullets **joined by newline**, not as JSON. `human_text` then stays
genuinely text for all seven kinds, so [REQ-ST-06](#req-st-06--no-editable-text-may-be-set-to-empty)
is one rule, the [REQ-TD-01](#req-td-01--corrections-are-stored-as-pairs) pair stays
sentence-against-sentence, and the history is readable — the same reasons a flowchart is stored per
label rather than as a blob.

That separator is safe because a bullet is **collapsed onto one line where it is generated**
(`llm_call_description`). The prompt already asks for one line of at most twenty words and a model
may ignore it, and a stray newline inside a bullet is a DOCX formatting fault in its own right.
Normalising at the source makes the separator safe by construction rather than by a rule someone
must remember.

There is no batch endpoint for this kind. A function has a handful of behaviour rows, not the
~42,000 node labels that made [REQ-API-08](#req-api-08--a-flowchart-is-saved-in-one-call) necessary.

**Verification:** the API accepts and returns the list as a unit; a bullet containing a newline
comes back as one bullet, not two.

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
| behaviour description | the row's `(currentFunctionId, externalCallerId)` — **both entity keys** |
| flowchart node label | `(version_id, entity_key, node_id)` |

**Not** the row's `externalUnitFunction`. That is a display label, `"<unit> - <shortName>"`, built
by dropping the component, the class/namespace and the parameter types, so two different callers
collide on it:

```
CompX|UnitB|AddOperation::apply|        ->  "UnitB - apply"
CompX|UnitB|MultiplyOperation::apply|   ->  "UnitB - apply"
```

As half a slot key that lets a correction to one row silently overwrite the other, since
`(version_id, slot_kind, slot_key)` is unique. The view already learned this on the other half of
the pair — `currentFunctionId` exists precisely because the exporter used to re-find the function
by short name and picked the wrong one for those two methods. The label stays in the row, for
display; the id is what addresses it.

**Verification:** a slot id resolves to the same slot across two generations of unchanged code,
and two callers sharing a display label yield two different slot keys.

### REQ-ID-02 — A node override carries forward only if the node list is unchanged

`cfg.nodes[].id` is `n0, n1, n2…`, assigned by walking the AST. It is a **position, not an identity**.

`source_hash` alone is not a sufficient gate. Identical source produces different node ids when the
CFG builder changes (an analyzer upgrade), or when `cfgSimplification` mutates the graph — it merges
nodes once a function has more than 15 labelable ones, so changing that setting, or a function
crossing the threshold, renumbers everything after the first merge. The override then lands on a
*different* node and nothing reports an error.

So a `nodeLabel` override records the **node-id list of the flowchart it was made against**, and is
applied to a later version only when the function's `source_hash` is unchanged **and** that list
still matches. A mismatch orphans the override
([REQ-ID-03](#req-id-03--rename-and-delete-orphan-an-override-and-it-is-kept)) instead of applying it.

This is the rule the flowchart label cache already follows — `_apply_cached_labels` stores the
node-id set with the labels and discards the whole entry unless it matches exactly, because *"a
change to the BUILDER would shift ids while the source hash stayed the same — that would silently
attach the wrong label to the wrong node"*.

Every override on one flowchart carries the same list, so they carry forward or orphan as a group; a
half-corrected picture is not reachable. Since a flowchart is saved in one call
([REQ-API-08](#req-api-08--a-flowchart-is-saved-in-one-call)), the list is read once per save and
written to each label's row — one reading of the graph, so they cannot disagree.

**Verification:** with `source_hash` unchanged and one node added to the CFG, no node override is
applied and each is flagged orphaned; with both unchanged, every one carries.

### REQ-ID-03 — Rename and delete orphan an override, and it is kept

A renamed function gets a new `entity_key`, so the override no longer resolves. A deleted function
leaves its override pointing at nothing.

In both cases the override row is **kept and marked orphaned** — never auto-deleted. It is the
user's work and it is training data, and a rename may be reverted. Cleanup is a separate, explicit
operation.

**Verification:** renaming a function leaves its override present and flagged, not removed.

### REQ-ID-04 — A flowchart is addressed by its function's id

A flowchart **is** one function's control-flow graph: the picture is `<unit>_<function>.png` and
the CFG hangs off a per-function entry in the unit's flowchart JSON. So the flowchart id is the
function's `entity_key` — no new identifier, per [REQ-ID-01](#req-id-01--reuse-the-ids-that-already-exist).

A node label's slot key stays `entity_key` + `node_id`, so the flowchart id is the first part of
every label key it contains. One id, read two ways; not two ids to keep in step.

Where a URL path segment is needed, the id is base64url-encoded — an `entity_key` contains `|`,
`:`, `,`, `*` and spaces.

**Verification:** every node label key in a flowchart yields that flowchart's id, and the id
resolves to exactly one function.

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
dropped. A **slot**, so for a flowchart that is per label, not per save — a call that changes one
label of twelve appends one history row, not twelve.

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

### REQ-ST-07 — A flowchart label is stored per label, whatever the API granularity

One row per node label, each with its own LLM original, human text and history — even though a
whole flowchart is submitted in one call ([REQ-API-08](#req-api-08--a-flowchart-is-saved-in-one-call)).

Storing a flowchart's labels as one blob was considered and rejected. It wins on exactly one
point, atomic all-or-nothing reuse across versions, which
[REQ-ID-02](#req-id-02--a-node-override-carries-forward-only-if-the-node-list-is-unchanged)'s node
list already provides. It loses on four:

- **undo** would revert labels the reviewer corrected separately and wanted kept;
- the [REQ-TD-01](#req-td-01--corrections-are-stored-as-pairs) training pair degrades from one
  sentence against one sentence to a blob against a blob, which must be diffed to recover what
  actually changed, and after several edits cannot be recovered at all;
- [REQ-ST-04](#req-st-04--history-is-bounded-and-configurable)'s cap would count N edits per
  *flowchart* rather than per label;
- `human_text` stops being a plain string for one of the seven kinds, so
  [REQ-ST-06](#req-st-06--no-editable-text-may-be-set-to-empty)'s emptiness check needs a
  kind-specific structural variant.

**Verification:** a five-label save leaves five rows, each carrying its own original.

---

## AP — Making it appear

### REQ-AP-01 — One source per piece of text, and the output is derived from it

View outputs (interface tables, flowcharts, behaviour rows) are **derived** and are never written
to directly as a way of changing what the document says.

Where the source is depends on which phase produced the text
([REQ-AP-05](#req-ap-05--a-correction-is-applied-where-the-text-is-produced)):

| text produced in | source of truth | a correction |
|---|---|---|
| Phase 2 — descriptions, behaviour names | the **model** | updates the model, then the view is re-derived |
| Phase 3 — node labels, behaviour descriptions | the **override table** | is handed to Phase 3 as an input |

Either way there is exactly one place the text comes from, and the document is rebuilt from it.

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

### REQ-AP-05 — A correction is applied where the text is produced

Two of the seven kinds are not model fields. A flowchart node label lives in `cfg.nodes[].label`
and a behaviour description in `_docxRows[].behaviorDescription` — both **made during Phase 3**,
while the view is being built. There is no model field for a correction to update.

Writing the correction into the view's output file does not work: the next run of Phase 3 rebuilds
that file from the CFG, asks the LLM for labels again, and the correction is gone with no error.
That is the two-copies arrangement this section exists to prevent.

So for text produced in Phase 3, **the correction is an input to Phase 3**, not a patch on its
output. Whenever Phase 3 runs — full, incremental, any group — it is given the corrections for
that version and produces corrected output the first time. Re-running is therefore idempotent: a
correction cannot be lost by regenerating, however often it happens.

This keeps the phases independent. A view still takes its inputs and writes its own output; it
gains one more input. Nothing about phase boundaries changes, which matters because Phase 3 runs
per group and is the phase that can be parallelised.

Two facts make this cheap rather than novel. Phase 3 already hands `knowledge_base.json` to the
flowchart subprocess, so the delivery route exists. And `_apply_cached_labels` already pastes a
stored `{node_id: label}` map onto a freshly built CFG **and refuses unless the node-id set matches
exactly** — the same guard as
[REQ-ID-02](#req-id-02--a-node-override-carries-forward-only-if-the-node-list-is-unchanged).
A human correction becomes a second, higher-priority source into that existing path.

**Verification:** correct a label, regenerate the version from scratch, and the corrected wording
is in the output with no second write and no LLM call for that label.

### REQ-AP-06 — Saving is instant and re-parses nothing

A save must not re-run the pipeline. The CFG is already stored, so applying a correction is:
patch that flowchart's stored CFG, rebuild the DOT from it, re-render that one PNG. No libclang,
no LLM, no flowchart engine subprocess, no C++ source needed.

This is what lets a correction be saved from a machine that does not have the source tree, and
what keeps a twelve-label save to one DOT build and one render
([REQ-API-08](#req-api-08--a-flowchart-is-saved-in-one-call)).

**The DOT is never edited directly.** It is generated syntax: labels are line-wrapped and escaped
on the way in, and a corrected label of a different length needs re-wrapping. Patching the DOT text
would mean writing those rules a second time, in a second place, for them to drift apart. The CFG
is edited and the DOT regenerated from it — which also keeps the picture and the SWE.4 Test Steps
in step, since the Test Steps read the CFG, not the DOT.

**Verification:** a save completes with no parse and no LLM call, and the resulting DOT is
byte-identical to the one a full regeneration produces for the same corrected CFG.

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

"Regenerates" here means *new LLM text*. It is separate from **re-derivation**, which rebuilds view
output from text that already exists and never calls an LLM — see
[REQ-CS-04](#req-cs-04--a-node-label-edit-re-derives-the-components-swe4-specs).

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

### REQ-CS-04 — A node label edit re-derives the component's SWE.4 specs

A Dynamic Behaviour spec does not merely name a cross-unit callee — it **transcribes that callee's
flowchart steps in place**, so the reader sees what actually runs (`test_steps._splice_callee`).
It also chains: if the callee calls on into a third function, those steps are pulled in too, with a
guard against cycles.

So a node label corrected in unit B changes unit **A's** document, and re-deriving only B's
flowchart leaves A reading the old wording — two documents from one project describing the same
step differently, with nothing reporting a problem.

Therefore a node label edit re-derives **every SWE.4 spec in the component**, not only the edited
function's.

Deliberately not "work out which units transcribe this one, transitively". That traversal is
fiddly, easy to get subtly wrong, and buys nothing here: the SWE.4 spec view calls **no LLM** — it
derives everything from the CFG — so re-deriving all of a component's specs is cheap and correct by
construction rather than correct-if-the-traversal-is-right.

Note this affects Dynamic Behaviour specs only. Ordinary per-function test steps transcribe
nothing, so they were never at risk.

**Verification:** correct a node label in unit B where unit A's Dynamic Behaviour transcribes it;
A's Test Steps show the corrected wording without A being edited.

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

Editing a flowchart node label re-renders that flowchart's PNG. Rendering is asynchronous.

**A behaviour description does not appear in any picture**, so editing one renders nothing.
`MermaidBuilder` labels each arrow with `<callee>()` — the function's name — and appends the
description to a separate list that ends up in `_behaviour_pngs.json`. Only that row changes.

Re-rendering must redo the tall-flowchart slicing: a corrected label can change the picture's
height, so a graph that was `_part_1_of_3` may become `_part_1_of_2`, and the leftover
`_part_3_of_3.png` must be removed or the document will find it. This has been a defect once
already.

**Verification:** after the render completes, the PNG differs from the pre-edit one, and no
orphan `_part_N_of_M.png` survives a change in part count; a behaviour-description edit queues no
render at all.

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

A flowchart is also **read** by its id — every node label with its current text and its LLM
original — so the editor can open with one request, matching the one request it saves with
([REQ-API-08](#req-api-08--a-flowchart-is-saved-in-one-call)). Whether the UI marks the corrected
ones is its own choice; the rendered *document* carries no marker
([REQ-API-06](#req-api-06--corrected-text-is-not-highlighted)).

**Verification:** after an update, the read returns the new text.

### REQ-API-03 — Update one slot, except a flowchart's labels

One slot per call for the six text kinds. A reviewer edits one piece of text at a time.

**Flowchart node labels are the exception: they are submitted per flowchart, not per label**
([REQ-API-08](#req-api-08--a-flowchart-is-saved-in-one-call)). A version holds roughly 42,000 of
them against ~2,000 other slots, so a call per label would make the flowchart the only screen in
the product whose save cost scales with how much the reviewer fixed.

This changes the **API** only. Storage stays one row per label
([REQ-ST-07](#req-st-07--a-flowchart-label-is-stored-per-label-whatever-the-api-granularity)).

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

### REQ-API-08 — A flowchart is saved in one call

Addressed by the flowchart's id ([REQ-ID-04](#req-id-04--a-flowchart-is-addressed-by-its-functions-id)),
carrying a map of `node_id → text`.

Three rules:

1. **Only changed labels are sent.** Not the whole flowchart. If a reviewer's stale copy of an
   untouched label were submitted, it would overwrite a correction someone else made to that label
   seconds earlier — and the server cannot tell an unchanged label from a deliberate revert.
   Sending only what changed is what keeps [REQ-API-07](#req-api-07--last-write-wins)'s "last write
   wins" true **per slot**, which is the granularity it was agreed at.
2. **All or nothing.** If any label in the request is rejected — empty text, or a node that no
   longer exists — nothing is written and the response names the offending node. A save that half
   succeeds leaves the flowchart in a state neither the reviewer nor the document expects, and the
   re-render would run against a partial edit ([REQ-AP-02](#req-ap-02--saving-an-override-is-one-operation)).
3. **One re-derivation and one re-render per call**, however many labels it carried. A picture
   cannot be partly redrawn, so the flowchart was always the unit of rebuilding; this makes the
   API agree with it.

**Verification:** a five-label call writes five rows, re-renders once, and leaves every other
label untouched; the same call with one bad node writes nothing.

---

## TD — Training data

Nothing is trained or self-learned in this feature. This is storage only, shaped so it is usable
later.

### REQ-TD-01 — Corrections are stored as pairs

What the LLM wrote **and** what the human replaced it with. A correction without its original teaches
nothing — "right" with no "wrong" carries no signal.

A reviewer may also type the LLM's original wording back. That is an ordinary edit and the row
stays, with its history (undo is a separate, explicit operation —
[REQ-API-04](#req-api-04--undo-restores-the-llm-original)). **A training export must skip pairs
whose two texts are equal**: they are not corrections, and counting them as such would teach the
model that its own output needed changing into itself.

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

**Status: DONE.** `model_deriver._enrich_unit_and_struct_descriptions` generates both after the
function and global descriptions the unit description is built from. The unit description is stored
on `model_units.description` (migration `0009_model_units_description`); the struct description
rides the type's payload, which `persist_types` already stores whole. The exporter reads both and
keeps its deterministic fallback for versions generated before the move.

**Verification:** both appear as stored model fields after Phase 2, and the exporter reads rather
than generates them — `tests/unit/test_unit_struct_descriptions_stored.py` (14).

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
- [x] Design document — [REVIEW_UPDATE_DESIGN](../design/REVIEW_UPDATE_DESIGN.md).
