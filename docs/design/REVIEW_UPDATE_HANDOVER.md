# Review & Update — handover for merging `review_update_v1`

For whoever integrates this branch. It says **what changed, what it touches, what must not be
broken, and how to check** — it does not restate the feature. For that:

- **What and why** → [REVIEW_UPDATE_SPEC](../spec/REVIEW_UPDATE_SPEC.md) (`REQ-` ids)
- **The HTTP contract** → [REVIEW_UPDATE_API_SPEC](../spec/REVIEW_UPDATE_API_SPEC.md)
- **How** → [REVIEW_UPDATE_DESIGN](REVIEW_UPDATE_DESIGN.md)
- **Chronology and the reasoning behind each decision** → root `PROJECT_CONTEXT.md`, the
  `> Updated: 2026-09-16 …` through `2026-09-18` entries

Branch: `review_update_v1` · base: `origin/develop` · state at writing: **the feature is functionally complete**. Build-order steps 1–8 done
and wired into the pipeline; step 9 done for the export path, with the three path-taking readers
left (see §7).

---

## 1. What the feature is, in four lines

A reviewer corrects the LLM's wording in a generated document. The correction is stored with the
LLM original beside it, shows in the HTML view, reaches the exported DOCX, survives a
regeneration, and carries into the next version. Seven kinds of text are editable
(`REQ-ED-01`).

---

## 2. Two things to do before anything else

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

`develop` was at `0008` when this was written. **If `develop` has since added its own `0009`,
there will be two heads after the merge** and `alembic upgrade head` will refuse. The fix is to
re-point this branch's `0009` at the new head and renumber — all six migrations are additive
(new tables, one new nullable column) and touch nothing existing, so they can sit anywhere after
`0008`.

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

Nine commits before `5a792ed` are unrelated engine defect fixes and test infrastructure from the
preceding review (the NUL-in-description crash, the `model_repo` flush defect, the interface-id
collision, `tools/audit_project.py`, `tests/live/`). They are independent of Review & Update and
can be reasoned about separately if the merge needs splitting.

The feature itself starts at `5a792ed` (the requirements doc).

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

### 3.2 Modified — the merge conflict surface

Everything else is new files. These are the ones a merge can actually collide on:

| file | change | risk |
|---|---|---|
| `api/db/postgres/schema.py` | +3 tables, +`slot_shape`, +`model_units.description`, all three in `PER_VERSION_TABLES` | low — additive |
| `engine/run.py` | +`_refuse_stale_export`, +`--force-export` (allowlist, parse branch, help) | low — one call beside `_restore_output_from_db` |
| `api/services/pipeline_runner.py` | +`_reexport_from_phase`; the re-export's `from_phase` is now computed, not 4; the source checkout is resolved by `source_checkout`, and the disk-only `model/` check is gone | **medium** — same function as any re-export change |
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
| `engine/run_views.py` | `_with_text_overrides` before `run_views(...)`, `_retire_behaviour_regenerations` after | **medium** — two lines at named points |
| `engine/model_deriver.py` | `_take_regeneration_queue` before the enrichment, `_retire_regeneration_queue` after | **medium** |
| `analyzer.py` | `reexport` refuses a stale `--from-phase 4`; new `--force` | low |
| `engine/run.py` | `_restore_output_from_db` before the phases, for `--from-phase 4` | low |
| `engine/core/model_repo.py` | `flush(conn=None)` — joins a caller's transaction | low — additive, default unchanged |
| `api/routes/__init__.py`, `api/main.py` | register `text_overrides_router` | low |
| `docs/spec/REVIEW_UPDATE_API_SPEC.md` | **new** — the HTTP contract the UI is built against | none |

The `flowcharts.py` and `behaviour_diagram.py` hooks are each ~3 lines at a named point, so a
conflict there is usually resolved by re-inserting the call at the same place. **Where it goes
matters** — see §4.2.

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

### 4.8 `llm_text` is captured once and never re-read

By the second edit the model holds the *human's* previous text. Re-reading it would replace the LLM
original with human prose, leaving nothing to undo to and a training pair that is human-vs-human.

→ `test_review_override_service.py::test_the_llm_original_survives_a_second_edit`.

### 4.9 Ordinary runs must keep stamping `view_derivations`

`capture_output` records when Phase-3 output was produced. Remove that and the export guard has no
baseline, so the first correction to any version makes it permanently unexportable.

→ `tests/unit/test_review_export_guard.py::TestTheStamp`.

### 4.10 A model write from the API must flush

`ModelAccess.save()` calls `DbRepository.flush()`. `write()` only **buffers** — without the flush a
correction returns 200 and stores nothing. The flush is handed the request's connection so the
model write and the override row land in one transaction (`REQ-AP-02`).

→ `tests/api/test_review_overrides_api.py::TestUpdatingASlot::test_the_model_really_moved` is the
only test that catches this; reverting the flush leaves every other HTTP test green.

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
before the label is replaced. A mismatch there **drops** the correction and leaves the LLM's label.

Carry-forward runs in Phase 2, *before* Phase 3 has produced the new version's flowcharts, so it
cannot make that check — it compares against the baseline's graph, and a mismatch marks the row
orphaned so the reviewer is told. If you ever move the shape check out of Phase 3 "because
carry-forward already does it", a builder change between two versions will write reviewer text onto
the wrong box, silently.

The shape **is** copied onto the carried row (orphans excepted). Nulling it makes the next
generation see "no claim"; `shape_matches` refuses a missing claim, so the correction would orphan
itself one version later.

→ `test_review_phase3_overrides.py::TestTheShapeIsCheckedWhereTheTextLands` and
`test_review_carry_forward.py::test_a_target_with_no_flowchart_yet_still_carries`, which pins the
bug a real two-version run found.

### 4.14 A blank description is a request, never an outcome

`cascade.blank_queued_text` empties a description **only** to ask for a rewrite — the enrichment
skips anything already filled in, so emptying the slot IS the instruction. If the rewrite then does
not happen (LLM unreachable, `--no-llm`, descriptions off), `clear_rewritten` must put the previous
wording **back** and leave the entry queued.

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

→ `test_review_overrides_api.py::TestTheFlowchartEditorHasWhatItNeeds`.

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

---

## 5. Two defects this branch found in existing code

Both were pre-existing and are fixed here; mention them if the merge touches the same lines.

**`llm_call_description` returned multi-line descriptions.** The result was `.strip()`ed and
nothing more, so an internal newline survived despite the prompt asking for one line. Now collapsed
onto one line at the point of generation. Independent of this feature — a stray newline in a bullet
was a DOCX formatting fault already.

**`externalUnitFunction` was a lossy id.** See §4.6. The view had already fixed the *other* half of
the same pair (`currentFunctionId` exists for exactly this reason); this half was left.

---

## 6. Verifying after the merge

```
python -m alembic heads                 # exactly one
python -m pytest tests/unit tests/api -q   # 2260 passed, 34 skipped at the tip of this branch
```

The feature has also been run end to end against a **SQLite** database on a machine with no
PostgreSQL — a full v1, a correction of each kind, an export, then an incremental v2 — and the
corrected text was found in the `.docx`, in `interface_tables.json`, in the stored CFG and in the
regenerated DOT. That run is what found the carry-forward ordering bug behind §4.13. If you change
anything in `engine/review/`, repeat it: the unit suite passed throughout, and did not see it.

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

- **`REQ-PRE-02` is half done.** An export-only run restores its text from the database first, so
  every reader gets database content — but `export_docx(json_path=…)`, the flowchart engine's
  `--interface-json` and `test_steps._load_cfgs` still take a path. Rewiring them to read rows
  directly is what would let `output/` hold only `.png` and `.docx`.
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
did not run.
