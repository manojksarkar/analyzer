# Review & Update — handover for merging `review_update_v1`

For whoever integrates this branch. It says **what changed, what it touches, what must not be
broken, and how to check** — it does not restate the feature. For that:

- **What and why** → [REVIEW_UPDATE_SPEC](../spec/REVIEW_UPDATE_SPEC.md) (`REQ-` ids)
- **The HTTP contract** → [REVIEW_UPDATE_API_SPEC](../spec/REVIEW_UPDATE_API_SPEC.md)
- **How** → [REVIEW_UPDATE_DESIGN](REVIEW_UPDATE_DESIGN.md)
- **Chronology and the reasoning behind each decision** → root `PROJECT_CONTEXT.md`, the
  `> Updated: 2026-09-16 …` through `2026-09-18` entries

Branch: `review_update_v1` · base: `origin/develop` · state at writing: build-order steps 1–5 done,
step 6 (cascade) next.

---

## 1. What the feature is, in four lines

A reviewer corrects the LLM's wording in a generated document. The correction is stored with the
LLM original beside it, shows in the HTML view, reaches the exported DOCX, survives a
regeneration, and carries into the next version. Seven kinds of text are editable
(`REQ-ED-01`).

---

## 2. Two things to do before anything else

### 2.1 Alembic — check the head is still linear

This branch adds **three** migrations on top of `0008`:

```
0008_class_name_and_llm_timing   (already on develop)
  └─ 0009_model_units_description   model_units.description
      └─ 0010_text_overrides        text_overrides, text_override_history, view_derivations
          └─ 0011_slot_shape        text_overrides.slot_shape
```

`develop` was at `0008` when this was written. **If `develop` has since added its own `0009`,
there will be two heads after the merge** and `alembic upgrade head` will refuse. The fix is to
re-point this branch's `0009` at the new head and renumber — the three migrations are additive
(new tables, one new nullable column) and touch nothing existing, so they can sit anywhere after
`0008`.

Check with:

```
python -m alembic heads     # must print exactly one
```

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
| `engine/views/flowcharts.py` | `_apply_text_overrides()` + one call between the incremental merge and the PNG render | **medium** — that function is large and often edited |
| `engine/views/behaviour_diagram.py` | `_apply_text_overrides()` + one call before the manifest write; `externalCallerId` added to each row | **medium** |
| `engine/behaviour_diagram/llm_call_description.py` | `_one_line()` on the LLM result | low |
| `engine/flowchart/models.py` | `cfg_for_rendering()` + `_node_type()` | low — additive |
| `engine/model_deriver.py` | unit/struct descriptions generated in Phase 2 (`REQ-PRE-01`) | **medium** |
| `engine/docx_exporter.py` | both LLM description calls **removed**; reads stored values | **medium** |
| `engine/incremental/store.py` | `capture_output` also stamps `view_derivations` (the export guard's baseline) | low |
| `analyzer.py` | `reexport` refuses a stale `--from-phase 4`; new `--force` | low |
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

### 4.1 Only two things write a `version_output_files` row

`model_store.persist_output_files` and `review.rerender.write_output_row`. A third writer means the
rows can say something the model does not — the bug class that already cost this project once
(`interface_tables.json` holding its own copy of `description`).

→ `tests/unit/test_output_row_writers.py` greps `engine/`, `api/` and `tools/` and fails naming any
third writer. If you add one deliberately, add it to `ALLOWED` **with the reason**.

### 4.2 Corrections are applied before anything is drawn

`flowcharts.py` must call `_apply_text_overrides(out_dir, config)` **after** the incremental merge
and **before** `render_dot_cached`. Applied later, the JSON carries the human's words and the
picture carries the LLM's.

→ `tests/unit/test_review_phase3_input.py::TestItIsActuallyWiredIn` checks both the call and its
position.

### 4.3 Every editable kind is accounted for

Each of `slot.ALL_KINDS` is either model-backed (`resolver._HOMES`) or applied at derive time
(`phase3_overrides.APPLIED_AT_DERIVE`) — never both, never neither. A kind in neither saves
successfully and never appears in the document.

→ `tests/unit/test_review_phase3_overrides.py::TestEveryKindIsAccountedFor`. Adding an eighth kind
fails three tests across two modules.

### 4.4 The slot-key separator is `0x01`, not `0x1f`

Python counts `0x1c`–`0x1f` as whitespace, so `.strip()` deletes them — and a slot key travels
through request bodies and form fields that trim. `hashing.py` uses `0x1f` legitimately (a hash
input is never trimmed); do not copy it here.

→ `tests/unit/test_review_slot.py::TestTheSeparatorIsNotWhitespace`.

### 4.5 `llm_text` is captured once and never re-read

By the second edit the model holds the *human's* previous text. Re-reading it would replace the LLM
original with human prose, leaving nothing to undo to and a training pair that is human-vs-human.

→ `test_review_override_service.py::test_the_llm_original_survives_a_second_edit`.

### 4.6 Ordinary runs must keep stamping `view_derivations`

`capture_output` records when Phase-3 output was produced. Remove that and the export guard has no
baseline, so the first correction to any version makes it permanently unexportable.

→ `tests/unit/test_review_export_guard.py::TestTheStamp`.

### 4.7 A model write from the API must flush

`ModelAccess.save()` calls `DbRepository.flush()`. `write()` only **buffers** — without the flush a
correction returns 200 and stores nothing. The flush is handed the request's connection so the
model write and the override row land in one transaction (`REQ-AP-02`).

→ `tests/api/test_review_overrides_api.py::TestUpdatingASlot::test_the_model_really_moved` is the
only test that catches this; reverting the flush leaves every other HTTP test green.

### 4.8 The API spec and the router must agree

`docs/spec/REVIEW_UPDATE_API_SPEC.md` §3 is what the UI is built against. A documented route
that is not served becomes a bug report from someone else's sprint.

→ `tests/unit/test_review_api_contract.py::TestTheDocumentedContractExists` parses the spec
table and compares it with the registered routes.

### 4.9 A behaviour row is addressed by two entity keys

`(currentFunctionId, externalCallerId)` — **never** `externalUnitFunction`, which is a display
label two different callers can share (`AddOperation::apply` and `MultiplyOperation::apply` both
render `"UnitB - apply"`).

→ `test_review_behaviour_save.py::TestTheCollisionIsGone`.

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
python -m pytest tests/unit -q          # 1655 passed, 10 skipped at 90ea69e
```

The review tests specifically:

```
python -m pytest tests/unit/test_review_*.py tests/unit/test_cfg_for_rendering.py \
                 tests/unit/test_output_row_writers.py -q
```

`tests/live/` needs a real database and is not part of the unit run — see `tests/live/README.md`.

---

## 7. What is deliberately not done yet

Build-order steps 6–9 in [REVIEW_UPDATE_DESIGN §13](REVIEW_UPDATE_DESIGN.md#13-build-order): the
cascade, image rendering as a background job, carry-forward into the next version, and
`REQ-PRE-02`.

Two consequences worth knowing:

- **`slot_shape` is written but never read yet.** The `REQ-ID-02` guard is complete and tested;
  its consumer is step 8 (carry-forward). Until then a correction does not carry between versions.
- **Renders are synchronous.** A flowchart correction rebuilds its picture inside the request
  when an output tree is present, and does nothing when it is not (the text is still stored and the
  next run redraws). The background `render_jobs` queue is step 7.

Open items, both pre-existing, are listed in
[REVIEW_UPDATE_DESIGN Open items](REVIEW_UPDATE_DESIGN.md#open-items) — notably `test_steps`
reading the flowcharts view's output directory and silently emptying every Test Step if that view
did not run.
