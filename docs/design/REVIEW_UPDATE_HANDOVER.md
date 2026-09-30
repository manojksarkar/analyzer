# Review & Update — handover for merging `review_update_v3` into `develop`

For whoever reviews and merges this branch. It says **what changed, what it touches, what must not
be broken, how to check, and what is waiting on a decision** — it does not restate the feature. For
that:

- **What and why** → [REVIEW_UPDATE_SPEC](../spec/REVIEW_UPDATE_SPEC.md) (`REQ-` ids)
- **The HTTP contract** → [REVIEW_UPDATE_API_SPEC](../spec/REVIEW_UPDATE_API_SPEC.md)
- **How** → [REVIEW_UPDATE_DESIGN](REVIEW_UPDATE_DESIGN.md)
- **Chronology and the reasoning behind each decision** → the dated entries in
  [project-context/history/](../../project-context/history/): the feature in `2026-09-16` through
  `2026-09-20`, the rebase onto develop in `2026-09-26f` through `2026-09-27d`, the rebase onto
  `5542736` in `2026-09-29b`, the full-feature review and its ten fixes in `2026-09-29d`, one
  response shape for a slot in `2026-09-29e`

Branch: `review_update_v3` = `review_update_v2` rebased onto `origin/develop` `5542736` on 2026-09-29
(develop's six commits; no code conflicts — §3.3). `review_update_v2` = `review_update_v1`
squash-merged onto `origin/develop` at `8628b2d`
(commit `b10a71b`; `e2b59c7` on v3), then separate follow-up commits: fixes the rebase review found, develop's new
LLM text (struct/class/union descriptions) made correctable, and docs — `git log
origin/develop..review_update_v3`. `review_update_v1` and `review_update_v2` are kept unchanged. State: **the feature is
functionally complete** (build-order steps 1–8 wired into the pipeline, step 9 done for the export
path with three path-taking readers left, §7); every suite passes on SQLite; the PostgreSQL run is
still to do. **Six decisions wait on the develop owner — §8.**

---

## 1. What the feature is, in four lines

A reviewer corrects the LLM's wording in a generated document. The correction is stored with the
LLM original beside it, shows in the HTML view, reaches the exported DOCX, survives a
regeneration, and carries into the next version. Seven kinds of text are editable
(`REQ-ED-01`).

---

## 2. Three things to do before anything else

### 2.1 Alembic — check the head is still linear

This branch adds **six** migrations on top of `0008`:

```
0008_class_name_and_llm_timing   (already on develop)
  └─ 0009_model_units_description   model_units.description
      └─ 0010_text_overrides        text_overrides, text_override_history, view_derivations
          └─ 0011_slot_shape        text_overrides.slot_shape
              └─ 0012_regeneration_queue   regeneration_queue
                  └─ 0013_render_jobs          render_jobs
                      └─ 0014_users_is_superuser   users.is_superuser
```

`develop` is still at `0008` (checked at `5542736`), so the chain is linear: `alembic heads` prints
`0014_users_is_superuser (head)`. **If `develop` adds its own `0009` before this merges, there will
be two heads** and `alembic upgrade head` will refuse. The fix is to re-point this branch's `0009`
at the new head and renumber — all six migrations are additive (new tables, new columns) and touch
nothing existing, so they can sit anywhere after `0008`.

`0014` only adds the column, `false` for everyone. Nobody is promoted — not the seeded
`admin@aspice.dev` login, whose password is published — and a superuser is made on purpose:
`python tools/grant_access.py --set-superuser --email <address>`. A database that ran an earlier
build of `0014` has that login promoted; take it back with
`--unset-superuser --email admin@aspice.dev`.

Check with:

```
python -m alembic heads     # must print exactly one
```

**And on a database that already exists, `analyzer.py setup` is not enough on its own** — or it
was not, until this branch. `setup` calls `metadata.create_all()`, which creates missing TABLES
and never alters an existing one, so `0009`'s `model_units.description` was silently skipped on
every database that had been used before. The tables from `0010`/`0012`/`0013` appeared, the
setup looked like it had worked, and the run then died mid-Phase-1 with

```
UndefinedColumn: column model_units.description does not exist
```

A fresh database hides this completely, which is how it survived a full end-to-end run and
reached an office machine. `setup` now adds missing columns after `create_all` and prints each
one; a NOT NULL column with no default is refused and sent here instead, because guessing a
backfill value is how a schema repair becomes data corruption.

`0011`'s `text_overrides.slot_shape` escaped only by luck: its table is new, so `create_all`
built it complete. Do not read that as "column migrations are fine".

### 2.2 This branch carries work that is not this feature

On `review_update_v1`, nine commits before `5a792ed` are unrelated engine defect fixes and test
infrastructure from the preceding review (the NUL-in-description crash, the `model_repo` flush
defect, the interface-id collision `15df7c5`, `tools/audit_project.py`, `tests/live/`). In
`review_update_v3` they are inside the one squash commit `e2b59c7` (`b10a71b` on v2); to reason about them apart,
read them on `review_update_v1`. The interface-id change is output-visible — §8.1.

The follow-up commits on `review_update_v3` also fix develop defects the rebase found — §5.

### 2.3 `PROJECT_CONTEXT.md` is an index on this branch

On 2026-09-28 this branch split the single 8,991-line `PROJECT_CONTEXT.md` into an index plus
`project-context/` (topic files and the dated history), because a new session read only its first
2,000 lines. `develop` still has the single file, so if `develop` edits it before this merges, git
reports a conflict in `PROJECT_CONTEXT.md`. Keep this branch's index, and move `develop`'s changes to
where that content lives now:

- a new `> Updated:` entry → the top of the newest file in `project-context/history/`, plus its line
  at the top of `project-context/history/TIMELINE.md`;
- an edit to a numbered section (`## N.`) → the topic file that holds §N (the table in the index);
- an edit to a status block at the top → the index's *Current state*.

`git diff 8628b2d origin/develop -- PROJECT_CONTEXT.md` lists what `develop` changed;
`tests/unit/test_project_context_fits.py` then checks the sizes and the index's links.

---

## 3. Files, and why each was touched

### 3.1 New — `engine/review/` (the whole feature)

| file | job |
|---|---|
| `slot.py` | the **only** place a slot key is built or split; also `cfg_shape` |
| `resolver.py` | slot → the model field it names (the five model-backed kinds) |
| `override_service.py` | the single entry point for saving a correction |
| `derive.py` | which views an override invalidates |
| `phase3_overrides.py` | the two kinds Phase 3 produces, and where their text sits |
| `redraw.py` | apply a correction to flowchart JSON and rebuild the DOT — **no DB imports** |
| `rerender.py` | the same, plus the database row and the PNG |
| `export_guard.py` | whether an export would ship superseded text, per view, component and document type; the derivation records and stamps it reads |
| `swe4_rederive.py` | a save re-derives the component's SWE.4 specs and UT export from the stored rows (`REQ-CS-04`) |

### 3.2 Modified — the merge conflict surface

Everything else is new files. These are the ones a merge can actually collide on:

| file | change | risk |
|---|---|---|
| `api/db/postgres/schema.py` | +3 tables, +`slot_shape`, +`model_units.description`, all three in `PER_VERSION_TABLES` | low — additive |
| `engine/run.py` | +`_refuse_stale_export`, +`--force-export` (allowlist, parse branch, help) | low — one call beside `_restore_output_from_db` |
| `api/services/pipeline_runner.py` | +`_reexport_from_phase`; the re-export's `from_phase` is now computed, not 4; the source checkout is resolved by `source_checkout`, and the disk-only `model/` check is gone; `_build_cmd` passes **every** name of the scope (`--selected-group` per group, likewise component and layer) — it passed only the first, so re-exporting a version generated for two groups rebuilt one | **medium** — same function as any re-export change |
| `engine/incremental/source_checkout.py` | new: find a version's checkout (expected folder, `base_path`, short-SHA folder) or clone that one commit | low — additive |
| `engine/incremental/clone.py` | `_do_checkout` fetches the exact commit when it is outside the 50-commit shallow window | **medium** — `generate` uses it too; only the failure path changed |
| `engine/views/flowcharts.py` | `_apply_text_overrides()` + one call between the incremental merge and the PNG render | **medium** — that function is large and often edited |
| `engine/views/behaviour_diagram.py` | `_apply_text_overrides()` + one call before the manifest write; `externalCallerId` added to each row | **medium** |
| `engine/behaviour_diagram/llm_call_description.py` | `_one_line()` on the LLM result | low |
| `engine/flowchart/models.py` | `cfg_for_rendering()` + `_node_type()` | low — additive |
| `engine/model_deriver.py` | unit/struct descriptions generated in Phase 2 (`REQ-PRE-01`) | **medium** |
| `engine/docx_exporter.py` | both LLM description calls **removed**; reads stored values | **medium** |
| `engine/incremental/store.py` | `capture_output` also stamps `view_derivations` (the export guard's baseline) | low |
| `engine/incremental/engine.py` | `_carry_review_overrides`, called beside `carry_forward_globals` | low |
| `engine/run_views.py` | `_with_text_overrides` before `run_views(...)`, `_retire_behaviour_regenerations(output_dir, ran, model, config)` after | **medium** — two lines at named points |
| `engine/model_deriver.py` | `_take_regeneration_queue` before the enrichment, `_retire_regeneration_queue` after — each twice: descriptions (with `regenerate=`), then unit descriptions around `_enrich_unit_and_struct_descriptions` | **medium** |
| `engine/llm_enrichment.py` | `enrich_functions_rich(..., regenerate=None)` — the named functions skip the cache lookup in both passes | **medium** — develop's LLM file; default unchanged |
| `engine/core/model_store.py` | + `set_entity_field`, `set_unit_description`, `ModelRowMissing` — one-row writes a save uses | low — additive |
| `analyzer.py` | `reexport` refuses a stale `--from-phase 4`; new `--force` | low |
| `engine/run.py` | `_restore_output_from_db` before the phases, for `--from-phase 4` | low |
| `engine/core/model_repo.py` | `flush(conn=None)` — joins a caller's transaction | low — additive, default unchanged |
| `api/routes/__init__.py`, `api/main.py` | register `text_overrides_router` | low |
| `docs/spec/REVIEW_UPDATE_API_SPEC.md` | **new** — the HTTP contract the UI is built against | none |

The `flowcharts.py` and `behaviour_diagram.py` hooks are each ~3 lines at a named point, so a
conflict there is usually resolved by re-inserting the call at the same place. **Where it goes
matters** — see §4.5.

### 3.3 Changed by the rebase onto develop (after the squash commit — `e2b59c7` on v3, `b10a71b` on v2)

What the follow-up commits change in develop's own code. Each one keeps develop's documented rule
and is argued in the dated history entries 2026-09-26f → 2026-09-29
([project-context/history/](../../project-context/history/)).

| file | change | why |
|---|---|---|
| `engine/views/unit_headers.py` | reads the STORED struct/class/union description (Phase 2 writes it) instead of asking the LLM while the view runs; every row carries `typeKey` | develop's new LLM text (794b95f) must be storable and correctable — §8.5 |
| `engine/model_deriver.py` | describes exactly `utils.described_record_keys(...)` in Phase 2 | one rule for the view, Phase 2 and the review routes |
| `engine/utils.py` | `RECORD_KINDS`, `has_own_header_row`, `is_described_record`, `described_record_keys`; `_run_mmdc` / `_run_dot_render` call `core.subprocess_util.run_capture` | the record rule in one place; a render timeout that stops the whole tree |
| `engine/core/subprocess_util.py` | `stop_tree`, `run_capture` | on Windows `subprocess.run(timeout, shell=True)` killed only `cmd.exe`; a hung mmdc held a run for 61 min — §8.4 |
| `engine/core/group_planner.py` | `plan_runs` qualifies a layer's group names with `make_qualified_id` | since 1df3016 a `layer:` scope planned no document |
| `api/services/doc_render.py` | the page's Component/Unit table reads the stored unit description; the join stays the fallback | the page and the Word file printed different sentences, and a `unitDescription` correction never reached the page |
| `api/services/pipeline_runner.py` | `_make_documents` names directories by the layer-qualified id; a re-export registers documents a version is missing | the web app listed no documents for layer-qualified output |
| `engine/core/db.py`, `engine/run.py` | `finished_status_kept` around the phase loop | a re-export (from Phase 3) left `pipeline_status` unfinished, so the version stopped being a baseline and its corrections were lost at the next version |
| `engine/review/carry_forward.py` | a behaviour row is judged by the function and caller hashes when the new version has no behaviour output yet | every Dynamic Behaviour correction was orphaned on every generation |
| `engine/review/catalog.py`, `resolver.py` | struct rows (`typeKey`, R3 refusal for records no document describes); `shownIn` on every R11 row | develop's struct descriptions made correctable; 470d15c publishes few functions — §8.2 |
| `analyzer.py` | `reexport` refuses another project's version id at once (`_no_such_version`) | 976ee0f's rule reached only part of the command |
| `api/routes/jobs.py` | `reference_version_id` resolved inside the project (id, else version name) and stored as the id | the baseline could be another project's version |
| `engine/views/test_specs.py`, `ut_export.py` | `build(...)` split out of `run(...)`; `run` = `build` + write the file, output unchanged | a save re-derives the SWE.4 rows through the same code, with no output tree (§4.26) |
| `engine/views/test_steps.py` | `cfgs_from_entries` split out of `load_cfgs`; `attach` / `attach_dynamic` take `cfgs=` | the same, from stored flowchart rows |
| `engine/views/__init__.py` | `views_to_run(doc_type, config)` split out of `run_views`, which now returns the views it ran | the derivation record says which views ran, and for which document (§4.9) |
| `engine/run_views.py` | leaves a derivation record (`_derivations.json`) in each output directory; the inputs' read time taken before the model loads | §4.9 |
| `engine/run.py` | `_restore_output_from_db` calls `dump_output_files_to_dir` (it named a function that never existed) and runs before a re-derive too; the guard is asked about the run's `--doc-type` | §4.28, §4.29 |


**Rebased again onto `5542736` (2026-09-29).** develop's six commits changed no file this branch
changed except `PROJECT_CONTEXT.md` (see `2026-09-29b`): `engine/views/unit_headers.py` (develop:
`_declarations_only`, `_code_only`, `_read_decl_snippet`; this branch: `_struct_description`,
`build_rows`) and `engine/model_deriver.py` (develop: `_enrich_behaviour_names` skips a leading
`this`) merged by themselves.

---

## 4. Invariants. Breaking one of these is silent

Each has a test. They are listed here because a merge is exactly when a guard gets dropped and
nothing complains.

### 4.1 A description correction must patch the derived copy

`interface_tables.json` holds a **copy** of `description`, and both the DOCX exporter and the HTML
view read the copy, not the model. Drop `patch_interface_tables` from the save and the model moves
while the page keeps showing the LLM's words — with nothing failing.

→ `tests/unit/test_review_interface_tables.py`.

### 4.2 The output capture must not go quiet again

It used to be `except Exception: pass`, noted "best-effort: disk output is intact" — and the disk
being intact is what made it dangerous. The document served from the database, or from another
node, kept the previous render while that machine looked correct.

→ `tests/unit/test_review_output_from_db.py::TestTheCaptureNoLongerSwallowsFailures`.

### 4.3 Only two things write a `version_output_files` row

`model_store.persist_output_files` and `review.rerender.write_output_row`. A third writer means the
rows can say something the model does not — the bug class that already cost this project once
(`interface_tables.json` holding its own copy of `description`).

→ `tests/unit/test_output_row_writers.py` greps `engine/`, `api/` and `tools/` and fails naming any
third writer. If you add one deliberately, add it to `ALLOWED` **with the reason**.

### 4.4 The pipeline must keep calling the feature

Two one-line call sites carry the whole integration: `_carry_review_overrides` in
`incremental/engine.py` and `_with_text_overrides` in `run_views.py`. Drop either in a merge and
everything still passes except the wiring tests — corrections simply stop travelling between
versions, or stop reaching Phase 3.

→ `tests/unit/test_review_pipeline_wiring.py`, which also maps every piece of the feature to its
caller so an unwired one is a decision rather than an oversight.

### 4.5 Corrections are applied before anything is drawn

`flowcharts.py` must call `_apply_text_overrides(out_dir, config)` **after** the incremental merge
and **before** `render_dot_cached`. Applied later, the JSON carries the human's words and the
picture carries the LLM's.

→ `tests/unit/test_review_phase3_input.py::TestItIsActuallyWiredIn` checks both the call and its
position.

### 4.6 Every editable kind is accounted for

Each of `slot.ALL_KINDS` is either model-backed (`resolver._HOMES`) or applied at derive time
(`phase3_overrides.APPLIED_AT_DERIVE`) — never both, never neither. A kind in neither saves
successfully and never appears in the document.

→ `tests/unit/test_review_phase3_overrides.py::TestEveryKindIsAccountedFor`. Adding an eighth kind
fails three tests across two modules.

### 4.7 The slot-key separator is `0x01`, not `0x1f`

Python counts `0x1c`–`0x1f` as whitespace, so `.strip()` deletes them — and a slot key travels
through request bodies and form fields that trim. `hashing.py` uses `0x1f` legitimately (a hash
input is never trimmed); do not copy it here.

→ `tests/unit/test_review_slot.py::TestTheSeparatorIsNotWhitespace`.

### 4.8 `llm_text` is captured once per correction and never re-read

By the second edit the model holds the *human's* previous text. Re-reading it would replace the LLM
original with human prose, leaving nothing to undo to and a training pair that is human-vs-human.
The one exception is an **orphan**: it is never applied, so the slot holds fresh LLM text for the new
code, and an edit there is a first edit that captures it. Undoing an orphan itself is refused (409).

→ `test_review_override_service.py::test_the_llm_original_survives_a_second_edit`,
`::TestAnOrphanedCorrection`; `test_review_flowchart_save.py::test_an_orphaned_label_starts_a_new_correction`.

### 4.9 Ordinary runs must keep recording what they derived

Phase 3 leaves a record in each output directory (`_derivations.json`): the views it ran, for which
components and document types, from inputs read when. `capture_output` replaces the version's
`view_derivations` rows with what the stored records say, in the transaction that replaces the
output rows. Remove either end and the export guard has no baseline, so the first correction to any
version makes it permanently unexportable. Stamp "the whole version" instead — as this feature did
until 2026-09-29 — and a SWE.3 re-derive waves a stale SWE.4 export through: reproduced, a label
corrected, the SWE.3 re-export, then an export-only `--doc-type all` shipped the old Test Step.

The guard asks only about corrections **in force**. An orphan is never printed; ask about it and a
version whose only corrections are orphans — a component renamed — is unexportable for ever, since
nothing records a derivation for a component that no longer exists.

→ `tests/unit/test_review_export_guard.py::TestTheRecord`, `::TestDocumentTypes`,
`::TestAnOrphanIsNotACorrection`; `test_review_pipeline_wiring.py` for the two call sites.

### 4.10 A model write from the API must reach its one row, in the request's transaction

`ModelAccess.save()` writes the corrected field of the one entity it names
(`model_store.set_entity_field`, `set_unit_description`) through the request's connection, so the
model write and the override row land in one transaction (`REQ-AP-02`). It used to hand the whole
artifact to `DbRepository.flush()`, which rewrites the version's model from a snapshot read before
the save — two saves at once put back each other's change. A row that is gone (a run replaced the
model) fails the save with 409 rather than returning 200 for a correction stored nowhere. Every
save of a version takes `_serialize_saves` first (PostgreSQL advisory lock), so two saves never
act on what the other is changing.

→ `tests/api/test_review_overrides_api.py::TestUpdatingASlot::test_the_model_really_moved`;
`test_review_override_service.py::TestASaveWritesOneRow`, `::TestOneSaveAtATime`;
`test_review_overrides_api.py::TestAnErrorSaysWhoseFaultItIs::test_a_model_replaced_under_the_save_is_a_409_and_saves_nothing`.

### 4.11 The API spec and the router must agree

`docs/spec/REVIEW_UPDATE_API_SPEC.md` §3 is what the UI is built against. A documented route
that is not served becomes a bug report from someone else's sprint.

→ `tests/unit/test_review_api_contract.py::TestTheDocumentedContractExists` parses the spec
table and compares it with the registered routes.

### 4.12 A behaviour row is addressed by two entity keys

`(currentFunctionId, externalCallerId)` — **never** `externalUnitFunction`, which is a display
label two different callers can share (`AddOperation::apply` and `MultiplyOperation::apply` both
render `"UnitB - apply"`).

→ `test_review_behaviour_save.py::TestTheCollisionIsGone`.

### 4.13 `REQ-ID-02` is enforced where the graph exists, not where it is convenient

A node id is a **position**, not an identity: the same source can renumber if the CFG builder
changes or if `cfgSimplification` crosses its 15-node threshold. `slot_shape` — a hash of the
flowchart's node-id list — is what catches that, and it has to be checked against the graph the text
is about to be written into.

That graph exists in exactly one place: `phase3_overrides.apply_to_flowchart_json`, immediately
before the label is replaced. A mismatch there **drops** the correction and leaves the LLM's label —
checked **per row**, since rows on one flowchart can claim different graphs (one carried from a
version numbered differently, one saved after). One shape per flowchart made the row order decide.

The dropped row is then **orphaned** where the stored graph is in hand — after every capture
(`incremental/store.py::_orphan_misplaced_labels`) and in a flowchart save, before it writes — and
an undo refuses one that does not fit. Left live, it read as in force (`isOverridden`, `canUndo`) and
an undo wrote the old graph's LLM label onto the box that now holds its node id.

Carry-forward runs in Phase 2, *before* Phase 3 has produced the new version's flowcharts, so it
cannot make that check — it compares against the baseline's graph, and a mismatch marks the row
orphaned so the reviewer is told. If you ever move the shape check out of Phase 3 "because
carry-forward already does it", a builder change between two versions will write reviewer text onto
the wrong box, silently.

The shape **is** copied onto the carried row (orphans excepted). Nulling it makes the next
generation see "no claim"; `shape_matches` refuses a missing claim, so the correction would orphan
itself one version later.

→ `test_review_phase3_overrides.py::TestTheShapeIsCheckedWhereTheTextLands`,
`::TestEachRowIsJudgedOnItsOwn`; `test_review_carry_forward.py::TestAMisplacedLabelIsOrphaned`,
`::TestTheCaptureOrphansWhatNoLongerFits`,
`test_review_flowchart_save.py::TestACorrectionWrittenForAnotherNumbering`; and
`test_review_carry_forward.py::test_a_target_with_no_flowchart_yet_still_carries`, which pins the
bug a real two-version run found.

### 4.14 A blank description is a request, never an outcome

`cascade.blank_queued_text` empties a description **only** to ask for a rewrite — the enrichment
skips anything already filled in, so emptying the slot asks for it, and `regenerate=` keeps the
description cache from answering with the stale wording (its key moves with the source, not with a
corrected description). If the rewrite then does not happen (LLM unreachable, `--no-llm`,
descriptions off), `clear_rewritten` must put the previous wording **back** and leave the entry
queued.

Delete that restore and one unreachable LLM turns a readable description into an empty cell in the
document — worse than the wording the correction superseded. The obligation alone is not enough:
keeping the debt does not un-publish the blank.

→ `test_review_queue_consumers.py::TestAFailedRewriteLeavesTheModelAsItFoundIt`. Removing either
half — the restore, or `Blanked.previous_text` that feeds it — fails three or four tests.

### 4.15 The export guard belongs to `run.py`, not to `analyzer.py`

`analyzer.py` is not the only front door. The API's re-export spawns `engine/run.py --from-phase 4`
directly. While the guard lived only in `analyzer.py`, the terminal refused a stale export and the
UI produced one — and the UI is where reviewers work.

What went out was not merely old text. A node-label correction patches the database immediately
(`redraw_flowchart` needs no files) and leaves the **picture** owed, so the document's sentence and
the diagram beside it disagreed. If you ever consolidate these, keep the one in `run.py`:
`_restore_output_from_db` is already there for exactly this reason.

`--force` must keep travelling to it as `--force-export`, and `--force-export` must stay on run.py's
KNOWN-flag allowlist — an unlisted flag is rejected outright, which fails the export it was meant
to permit.

→ `test_review_pipeline_wiring.py::TestTheExportGuardCoversBothFrontDoors` and
`::TestTheApiRederivesInsteadOfRefusing`; behaviour in
`test_review_export_guard.py::TestTheApiRederivesRatherThanRefusing`.

### 4.16 `renderPending` is about the PICTURE, not the stored graph

`redraw_flowchart` rebuilds a flowchart's JSON and DOT **in the database** whether or not it has
an output tree — the text is corrected everywhere it is read from. Drawing the PNG needs somewhere
to put it, which an API host usually does not have.

So `redrawn` and "the image exists" are different facts. `render_pending` is derived from whether
the render JOB was completed in the call, never from `redrawn`. It must always agree with R9's
`pendingRenders`; if the two can disagree, one of them is lying to a reviewer about whether the
document's diagrams match its words.

→ `test_review_flowchart_save.py::TestRenderPendingMeansThePictureIsOwed` and
`test_review_overrides_api.py::TestRenderPendingTellsTheTruth::test_it_agrees_with_export_readiness`.

### 4.17 Anything the caller must send back has to come from a read

A node's slot key is `flowchartId + U+0001 + nodeId`, and `REQ-ID-01` says a key is built by the
server and **never** by hand. R7 is what a flowchart editor opens with, so if R7 does not return
each node's `slotKey`, undo and history on a single label are impossible without breaking that
rule. The same test applies to any field added later: if the UI must send it, a read must supply it.
The flowchart itself is named by R11's `flowchartId`, sent back as `flowchart_id` — in R7's query and
R8's body, like every other key (2026-09-29c; a base64 token in the path gave the one id a second
spelling). A node's `slotKey` sent there is a 400 that names the flowchart id.

→ `test_review_overrides_api.py::TestTheFlowchartEditorHasWhatItNeeds`,
`::TestANodeKeyIsNotAFlowchartId`, `::TestAFlowchartIdTravelsAsItIs`.

### 4.18 `text` is what the document prints — never the override row

For every listing (R7, R11), `text` is read from where the document reads it: the model for the
five model-backed kinds, the stored view row for the two Phase-3 kinds. A live correction was
written into those by the save, so for it `text` and `humanText` agree. An **orphan** was never
applied, so they differ — and taking `text` from the row showed a reviewer their stale words as the
current wording of a function whose document printed something else.

`isOverridden` means a correction is IN FORCE; an orphan is not one. The rule lives once, in
`catalog._state`, and R7 imports it.

**Test fixtures must go through the real save.** Both bugs behind this invariant hid behind
fixtures that inserted an override row without writing the model — a state `apply_override`
cannot produce. One of them also stored `behaviorDescriptionList`, the same wrong field the reader
used, so the test passed while every real behaviour row listed no bullets. The field is now
checked against the WRITER (`behaviour_diagram.py`) and the READER (`docx_exporter.py`).

→ `test_review_catalog.py::TestAnOrphanIsNotInForce`, `::TestTheFixtureMatchesWhatTheViewWrites`,
`test_review_overrides_api.py::TestR7ReportsWhatIsInForce`.

### 4.19 One rule decides which records have a description

A struct, class or union gets a description when it has a unit-header row of its own or a typedef
row names it — `utils.has_own_header_row` / `is_described_record`. The unit header view picks its
rows by it, Phase 2 generates for `described_record_keys`, and R3/R11 offer only those records. A
second copy of the rule in any one of them means text that is paid for and never printed, or a
correction that saves and never appears.

→ `test_unit_struct_descriptions_stored.py::TestWhichRecordsHaveADescription`,
`test_review_catalog.py::TestWhereAStructDescriptionIsShown`.

### 4.20 `shownIn` is read from the stored output, never recomputed

R11's `shownIn` says which units' documents print a text. `catalog._placement` reads it from the
stored interface tables, behaviour rows and flowchart file names — not from the publication rule —
so if develop changes who is published, `shownIn` follows by itself.

→ `test_review_catalog.py::TestEveryRowSaysWhereItsTextIsShown`,
`test_review_overrides_api.py::TestR11SaysWhereATextIsShown`.

### 4.21 A behaviour row is judged before Phase 3 has drawn it

Carry-forward runs before Phase 3, so the new version has no behaviour rows yet. A row is then
judged by the hashes of its function and its caller. Judging it by the (missing) row orphaned every
Dynamic Behaviour correction on every generation.

→ `test_review_carry_forward.py::TestABehaviourRowIsJudgedBeforePhase3DrawsIt`.

### 4.22 A re-export leaves a finished version finished

`finished_status_kept` wraps `run.py`'s phase loop when it starts at Phase 2 or later. Without it the
version's `pipeline_status` is left at `exporting`; `list_versions` then no longer offers it as a
baseline, and the next version starts without its corrections. Only a run with
`ANALYZER_VERSION_ID` writes the status (an API job); the API re-exports from Phase 3 or 4 today, so
the Phase-2 half is a guard for the day it re-derives — the incremental engine's own `--from-phase 2`
starts from a status still in progress, which is never put back.

→ `test_reexport_keeps_the_baseline.py::TestAFinishedVersionStaysFinished`, `::TestRunPyWrapsThePhases`.

### 4.23 A version id from outside resolves inside its project

develop's 976ee0f makes a version id a name inside its project. Every door that takes one keeps
that: the review routes (`_version()`), the CLI `reexport`, and the start-job baseline.

→ `test_review_overrides_api.py::TestTheVersionMustBeTheProjectsOwn`,
`test_reexport_refuses_a_foreign_version.py`, `test_start_job_baseline_is_this_projects.py`.

### 4.24 A render's timeout stops the whole process tree

`core.subprocess_util.run_capture`. Through the shell, `subprocess.run(timeout=…)` killed only
`cmd.exe` and then waited on the Node and Chromium beneath it.

→ `test_render_timeout_stops_the_tree.py::test_a_timeout_does_not_wait_for_a_grandchild_holding_the_pipes`.

### 4.25 A save's stamp lives exactly as long as the rows it rebuilt

A save that re-derives rows stamps them and marks the stored record (`saved`, per component —
`export_guard.stamp_saved`). The next capture rebuilds the stamps from the records: a run that
restored the marked record keeps the stamp; a run that overwrote the save's rows overwrote its mark
with them, and the correction reads as stale again — the truth. Merge stamps at capture instead of
replacing them, and a correction saved while a run was building is vouched for by rows that no
longer carry it.

→ `test_review_export_guard.py::TestASaveThatReDerives`.

### 4.26 The save-time SWE.4 re-derive is Phase 3's build, byte for byte

`swe4_rederive` rebuilds one component with `test_specs.build` and merges it into the stored file.
With nothing corrected the rows must come back unchanged, and after a correction they must equal
what a Phase-3 run writes. Both were checked on `SampleCppProject`; the unit tests pin a two-component
document with a Dynamic Behaviour splice.

→ `test_review_swe4_rederive.py::TestNothingChanged`,
`::TestALabel::test_the_result_is_what_phase_3_would_write`, `::TestTheParts`.

### 4.27 A save reads the model through its own connection

After the save has written, a second connection inside its transaction waits on the save's lock
(SQLite) or, under a single-connection pool, rolls the save back when it closes — a 200 that stored
nothing. `swe4_rederive.model_of` uses what the save holds and the save's connection, never the
repository's.

→ `test_review_swe4_rederive.py::TestTheDeriver::test_the_model_is_read_through_the_saves_connection`,
`test_review_overrides_api.py::TestASaveReDerivesTheSwe4Specs` (it failed exactly so before the fix).

### 4.28 The restore must actually run

`run.py`'s restore imported `restore_output_files`, which never existed, and then called `_paths()`,
which `run.py` never defined. Each error was caught as "could not restore", so from 2026-09-19 to
2026-09-29 every run exported from whatever was on disk, and every test passed — they read the
source. A correction saved over the API reached an export-only document only through a Phase-3 run.

→ `test_review_output_from_db.py::test_what_it_calls_exists`, `::test_every_name_it_uses_is_defined`,
`::test_the_stored_row_wins_over_the_disk`.

### 4.29 An export is judged on what its documents print

SWE.4 is read from `testSpecs` and `utExport` (`export_guard.SWE4_VIEWS`), SWE.3 from the views a
SWE.3 run built — the record's `docTypes`. The SWE.3 exporter embeds the flowcharts only when
`views.flowcharts` is on (off by default, and then only SWE.4 draws them), so a label correction
must not hold up such a SWE.3 export, nor a picture being drawn. Without records nobody can say, and
every view counts.

→ `test_review_export_guard.py::TestWhatSwe3Prints`, `::TestDocumentTypes`.

### 4.30 Each queue step pays only what it rewrote

Phase 2 takes the regeneration queue twice, each time with only its own kind and the artifact that
kind lives in: descriptions before the function enrichment, unit descriptions around
`_enrich_unit_and_struct_descriptions` with the units just built. Taken at once with `units: {}`,
every unit entry read as "gone" and was retired unpaid. Phase 3 retires a behaviour entry only when
the `behaviourDiagram` view ran, and only for the rows it covered (the manifest on disk, the run's
components): a SWE.4-only run retired every one of them before. A save removes its own slot's entry.

→ `test_review_queue_consumers.py::TestEachStepTakesOnlyItsOwnKinds`, `::TestPhase3PaysTheRest`,
`::TestPhase3RetiresOnlyWhenTheBehaviourViewRan`, `::TestTheConsumersAreWiredIn`;
`test_aux_desc_cache.py::test_rich_enrichment_regenerate_does_not_answer_from_the_cache`.

### 4.31 The queue travels with the text

`carry_overrides` copies the baseline's still-owed entries after the rows (`carry_queue`). The new
version starts from the baseline's text, stale wording included; without the entries it reads that
text as current and never asks again.

→ `test_review_carry_forward.py::TestTheRegenerationQueueTravels`.

### 4.32 A 4xx is the caller's fault

`_as_http` keeps a refusal's own status, passes an `HTTPException` through, and answers anything it
does not recognise with a 500 that names only the exception type. A 400 with the exception text — as
before — tells the client to fix a request that was fine and hands it internal detail.

→ `test_review_overrides_api.py::TestAnErrorSaysWhoseFaultItIs`.

### 4.33 A slot has one shape in every response

`catalog.slot_view` builds every slot a route returns — R1, R2, R3, R4, R6, R11, and each node of R7
and R8 — so a client reads one set of names (`text`, `llmText`, `humanText`, `isOverridden`,
`isOrphaned`, `canUndo`, `updatedBy`, `updatedAt`) whatever the kind. A route that builds its own
dict drifts: R8 once returned node ids with no text, and `llmText` meant two things in two answers.
`text` comes from `catalog.texts_in_force`, never from the override row (an orphan's row is not what
is printed).

→ `test_review_overrides_api.py::TestEveryRouteGivesASlotInOneShape` (the same slot, read back
through R1, R2, R7 and R11, equals what R3, R6 and R8 answered); `test_review_catalog.py::TestOneShapeForASlot`,
`::TestReadingAnySlot`.

---

## 5. Defects this branch found in existing code

All were pre-existing and are fixed here; mention them if the merge touches the same lines. The
first two were found while building the feature, the rest by the rebase onto develop.

**`llm_call_description` returned multi-line descriptions.** The result was `.strip()`ed and
nothing more, so an internal newline survived despite the prompt asking for one line. Now collapsed
onto one line at the point of generation. Independent of this feature — a stray newline in a bullet
was a DOCX formatting fault already.

**`externalUnitFunction` was a lossy id.** See §4.12. The view had already fixed the *other* half of
the same pair (`currentFunctionId` exists for exactly this reason); this half was left.

**A `layer:` scope planned no document** (since 1df3016): `plan_runs` compared the layer's bare
group names with layer-qualified group ids. `docs/CLI_COMMANDS.md` says one document per component.

**The web app listed no documents** for layer-qualified output: `_make_documents` looked for
directories under the bare group name.

**A hung diagram render held a run for an hour** — §4.24.

**A web job's baseline could belong to another project** — §4.23.

---

## 6. Verifying after the merge

```
python -m alembic heads                           # exactly one: 0014_users_is_superuser
python -m pytest tests/unit tests/api tests/e2e   # 3733 passed, 80 skipped on review_update_v3
```

**The whole feature through the REST API**, against a running server — the check to repeat on
PostgreSQL: `tools/review_api_test/` onboards a project, generates a version, corrects every kind,
reads everything back through every route, edits again, saves one slot twice at once, undoes, tries
a client's mistakes, re-exports and opens the Word file, then generates the next version and checks
the corrections carried. Only the two request bodies come from its config; see its README.

```
python tools/review_api_test/review_api_test.py --config tools/review_api_test/config.json
```

The feature has also been run end to end against a **SQLite** database on a machine with no
PostgreSQL — a full v1, a correction of each kind, an export, then an incremental v2 — and the
corrected text was found in the `.docx`, in `interface_tables.json`, in the stored CFG and in the
regenerated DOT. That run is what found the carry-forward ordering bug behind §4.13. If you change
anything in `engine/review/`, repeat it: the unit suite passed throughout, and did not see it.

After the rebase the same was repeated on develop's code: a `layer:Layer1` web job (11 documents in
75 s), every kind corrected and carried into an incremental v2, the CLI re-derive
(`reexport --from-phase 2`), two CLI projects that both have a `v1`, and the Dynamic Behaviour rows
from `engine/config/api_*.sample_behaviour.example.json` (18 rows). **Not yet run on PostgreSQL.**

The review tests specifically:

```
python -m pytest tests/unit/test_review_*.py tests/unit/test_cfg_for_rendering.py \
                 tests/unit/test_output_row_writers.py -q
```

`tests/live/` needs a real database and is not part of the unit run — see `tests/live/README.md`.

---

## 7. What is deliberately not done yet

Build-order steps 1–9 in [REVIEW_UPDATE_DESIGN §13](REVIEW_UPDATE_DESIGN.md#13-build-order) are
all built, including the cascade, the render queue and carry-forward into the next version.
`REQ-PRE-02` is the one that is only half done.

Consequences worth knowing:

- **`REQ-PRE-02` is half done.** A run that exports or re-derives restores its text from the
  database first, so every reader gets database content (§4.28 — true only since 2026-09-29) — but
  `export_docx(json_path=…)` and the flowchart engine's `--interface-json` still take a path. The
  SWE.4 builders can already read stored rows (`test_steps.cfgs_from_entries`), which is how a save
  re-derives them. The restore writes the stored rows over the disk; it does not delete a text file
  the database no longer has, which the capture would then store again.
- **The save re-derives SWE.4, not SWE.3.** A SWE.3 row a save changes is patched in place (the
  interface-table copy, the flowchart JSON, the behaviour row) and not stamped, so the web app's
  re-export still runs Phase 3 after any correction. A stamp is per (view, component), not per
  output directory: a component in two documents of one version counts the newest derivation.
- **A save made while a run is building can be lost.** A run that started before it writes its
  whole model back at the end of Phase 2 and replaces every output row at capture. The export guard
  then reports the correction as stale (§4.25) and the next run applies it again from the override
  table — but between the two the document does not carry it. (A save no longer does this to anyone
  else: it writes one row, saves of a version take turns, and a save that finds its row replaced by
  a run fails with 409 — §4.10. Coordinating a save with a *run* would need the run to take the
  same lock for the length of Phase 2; not done.)
- **Both queues are drained by a run, not a timer.** A pending picture is drawn when a host with
  the output tree captures a version's output; a queued regeneration is rebuilt by Phase 2 or
  Phase 3. Between a correction and the next run the work is *owed and reported* — which is why
  the export blocks on a pending picture. That is the design, not a gap, but it does mean a
  correction's cascade is not applied until something runs.
- **Nothing drives the render queue on a schedule.** A correction raises a `render_jobs` row and
  the export blocks on it, but a pending job is finished by `render_queue.run_pending` being called
  on a host that has the output tree.

Open items, both pre-existing, are listed in
[REVIEW_UPDATE_DESIGN Open items](REVIEW_UPDATE_DESIGN.md#open-items) — notably `test_steps`
reading the flowcharts view's output directory and silently emptying every Test Step if that view
did not run. What the HTTP API does not do yet (no orphan clean-up, no bulk write, no slot keys in
the page payload) is in [REVIEW_UPDATE_API_SPEC §17](../spec/REVIEW_UPDATE_API_SPEC.md#17-not-yet-implemented).
The web app has no review screen yet (`web-app/PLAN.md`).

---

## 8. Waiting on the develop owner

Things this branch met in develop's area and did not settle alone. None blocks the merge; where
the branch had to pick, the pick is reversible. Tracked as `RU-1`…`RU-6` in
[BACKLOG](../BACKLOG.md).

### 8.1 Interface ids of units whose ids start the same — `RU-1`

`SWE3_WIKI` counts `<NN>` **within the unit**; `SWE3_SPEC` REQ-IT-04 requires the id to be
**unique**. They disagree only when two units' ids start the same: `Map` and `Map2` in one group both
give `IF_<L>_<G>_MAP_…`, and develop numbers each from `_01`, so the document prints
`IF_…_MAP_01` twice. This branch (`15df7c5`, `model_deriver._iface_scope_key`) numbers by what the id
encodes — `Map` gets `_01`, `_02`, `Map2` continues at `_03` — and says so under the wiki's existing
⚠ To confirm. On `SampleCppProject` no two units collide: all 229 ids are identical to develop's.

- **Keep:** add a `Map` / `Map2` pair to `SampleCppProject` (the Definition of done asks for a
  fixture), extend `tests/unit/test_interface_id_uniqueness.py` with it, move the wiki sentence out of
  the ⚠ To confirm.
- **Revert to per-unit counting:** key `_build_interface_index`'s buckets by unit again and delete
  the wiki sentence — and accept duplicate ids until the client decides how names are shortened.

### 8.2 Most corrections in a group run print nowhere — `RU-2`

develop's rule (470d15c, `SWE3_WIKI` Public vs. private): a function is public only if a function in
another file calls it. In a group or layer run the parse is the layer, so a caller in another layer is
invisible and its callee reads as private — the trap develop's S3-7 note names. On the sample layer
run, 25 of 229 descriptions are printed. Reviewers are offered every slot; R11's `shownIn` says which
ones a document prints (`[]` = none), read from the stored output (§4.20).

- **The rule is as meant:** nothing to do; the UI shows `shownIn`.
- **The rule changes** (e.g. publish by the whole model): only `model_deriver` changes;
  `shownIn` follows by itself.

### 8.3 The default behaviour filter draws no Dynamic Behaviour on the sample — `RU-3`

The shipped profile has `views.behaviourDiagram` off (develop's VW-9). With it on,
`views.sequenceDiagrams.filterMode` is still absent from `config.defaults.json`, so
`generator._get_filter_mode` uses `skip_within_unit` — which draws no row on `SampleCppProject`;
`all_callers` draws 18 for `Layer1.My Sample`. The branch changes no default: to exercise
`behaviourDescription` corrections it ships `engine/config/api_*.sample_behaviour.example.json`.

- **Default as meant:** nothing to do.
- **Change it:** set `views.sequenceDiagrams.filterMode` in `config.defaults.json` (with VW-9's
  decision on the profile) — every project's documents gain diagrams.

### 8.4 An intermittent mmdc hang — `RU-4`

The first layer-scoped run took 66 minutes, 61 of them in one unit diagram
(`Layer1.Diag|ArmIntrinsics`) whose mmdc render hung past its 60-second timeout. The next run drew it
normally. The branch makes the timeout real (§4.24): a hung render now fails in 60 s and the document
goes on without that picture, as for any failed render. Why mmdc hung is not known.

- **Nothing to decide unless it recurs.** A `mmdc could not run: TimeoutExpired` line in the log marks
  one.

### 8.5 Unit and struct descriptions are generated in Phase 2 — `RU-5`

`REQ-PRE-01`: a text a reviewer can correct must be stored in the model. develop generated the unit
description inside the exporter, so the page never showed it, and the struct/class/union description
while the unit header view ran (101e3f0), writing it afresh on every run — neither had a model field
a correction could live in, and the next render would have put the LLM's words back. Both are now
generated in Phase 2 with develop's prompts and fallbacks (`_enrich_unit_and_struct_descriptions`)
and only read afterwards; the page shows the same unit sentence as the Word file. One text per record: for `typedef struct S_s {…} S_t;` the `S_t` row
reads `S_s`'s text, where develop asked the LLM once per name — the intent of develop's own
docstring, "one type reads the same however it was declared". With the LLM off the output is
unchanged.

- **Agree:** nothing to do.
- **Disagree:** the text has to stay stored for a correction to reach the document; talk before
  moving it back.

### 8.6 doccheck's pair check reads the behaviour bullets a reviewer can rewrite — `RU-6`

develop's doccheck v2 (`66f7f97`) pairs a SWE.3 document with its SWE.4 one and finds each call of a
Dynamic Behaviour row by the words `A calls B` at the start of a Behaviour Description bullet
(`tools/doccheck/pairing.py` `_ARROW_RE`). That bullet is `behaviourDescription` text: the LLM writes
the whole forward-call bullet (`llm_call_description`, asked for "A calls B to …"), and R6 lets a
reviewer replace the list with any wording. "Primes the pump" in place of "start calls doThing to
prime the pump" drops the arrow from the pair check, which then reports a false P1: "the
specification calls doThing, which the design draws no arrow for". An LLM that does not follow its
prompt does the same.

- **Keep the call at the front (this branch's suggestion):** R6 refuses a list whose bullets do not
  start as the stored ones do — "A calls B", "B returns to A" — so a reviewer corrects the wording
  after them. One check in `apply_behaviour_override`, a 422 naming the bullet.
- **Leave it:** a corrected row can show as a P1 in a pair report; say so in the doccheck README.
- **Change doccheck:** read the arrows from something a correction cannot touch. The document holds
  only the picture, so this needs a new field in the page or the DOCX.
