# Engine Plan

> Forward engine work only. Deep context → [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) ·
> SWE.4 contract → [SWE4_WIKI.md](../docs/spec/SWE4_WIKI.md)

## Now — SWE.4 × DB integration

`feat/swe4-v1` is in review while `integration/poc-4-db` replaces the file model with a database.
`develop` is the default branch, cut at `c15ee42` — the merge base of both, so it fast-forwards to
the DB work and is 23 commits behind swe4-v1.

### Parallel tracks

| track | branch | waiting on |
|---|---|---|
| UT export | `feat/swe4-ut-export` | nothing |
| v1 review fixes | `feat/swe4-v1` | review findings |
| DB merge | `develop` | teammate |

Both SWE.4 tracks edit `views/test_specs.py` and `views/test_steps.py`, so
`feat/swe4-ut-export` needs `git merge feat/swe4-v1` as review fixes land — merge often, or the
conflicts accumulate.

### While the DB work merges

Target format: [UT_EXPORT_SPEC.md](../docs/spec/UT_EXPORT_SPEC.md).

1. **Golden snapshot of `test_specs.json` first** — before any change, or the baseline moves.
   New `tests/e2e/test_test_specs.py`, mirroring `tests/e2e/test_interface_tables.py:254`.
2. **Mock signatures** (REQ-UE-03) — `views/test_specs.py::_mock_functions` returns bare `"Name()"`
   strings. Add return type / params / declaring header *alongside*; two consumers read the
   existing list.
3. **Path conditions** (REQ-UE-04) — decision steps carry the predicate structurally, not only as
   English inside `testSteps[].text`. The CFG has it; the view flattens it.
4. **Per-path cases** (REQ-UE-04) — split one spec per function into one case per path, using
   `expected.returns[].step`. Then input values rather than ranges.

All of these are in SWE.4-owned files, so they cannot conflict with the DB work.

### After it merges

6. `develop` fast-forwards: `git merge --ff-only integration/poc-4-db`. A GitHub *"Squash and merge"*
   instead collapses the 166 commits to 1 — pick deliberately.
7. `feat/swe4-v1` **merges** `develop` — resolve the 8 overlapping files once. (Merge, not
   squash+rebase: same single resolution, and it keeps branches cut off swe4-v1 valid.)
8. Add `writesParams` + `readsFields` to `_FN_PAYLOAD_FIELDS`.
9. Port `functionTestSpecs` / `dynamicBehaviourSpecs` / `dynamicOnly` into `config.defaults.json`.
10. Re-hang `DOC_TYPE_VIEWS["swe4"]` off the new `analyzer.py` dispatcher.
11. Verify against the step-2 golden — byte-identical, or a field was dropped.

### Three things that break silently

Git shows no conflict for any of these.

1. **`core/model_store.py::_FN_PAYLOAD_FIELDS` is an allowlist**, and `writesParams`
   (`parser.py:2235`) and `readsFields` (`parser.py:2229`) are absent. Dropped ⇒ `0a626a9`
   (out-parameter assertions) and `99b94b6` (mock write-back Inputs) silently revert. Sparse in the
   Sample model (7 and 2 of 140 functions), so a smoke run looks fine.
2. **`config/config.json` is deleted** on poc-4-db; defaults moved to `config.defaults.json`, which
   lacks the three SWE.4 view keys. `45c909b` edits a file that is gone ⇒ the hunk is dropped
   silently and SWE.4 stops emitting.
3. **`tools/swe4_audit.py` reads `model/*.json`** directly. Those files no longer exist — route it
   through `core.model_io.load_model`.

### The 8 overlapping files

`parser.py` (109 vs 113 lines changed) · `views/flowcharts.py` (97 vs 113) · `core/group_planner.py`
(51 vs 92) · `run.py` (19 vs 160) · `docx_exporter.py` (10 vs 24) · `run_views.py` (7 vs 65) ·
`flowchart/flowchart_engine.py` (5 vs 255) · `PROJECT_CONTEXT.md`

`views/test_specs.py`, `views/test_steps.py`, `views/dynamic_specs.py` and `swe4_exporter.py` are
untouched by poc-4-db. Still working after the merge, checked: view outputs stay files (so the
`output_dir` CFG bridge survives), and `run.py`/`run_views.py` still exist alongside `analyzer.py`.

### Verify

`pytest --skip-pipeline` (runs on dicts — passes even when the DB drops a field) → full pipeline on
SQLite (`{"driver":"sqlite","path":"engine/config/analyzer-dev.db"}`, no Postgres needed) → diff
against the golden → `tools/swe4_audit.py` → open the DOCX.

## Open

- **Precise test cases — the crux.** Their `cases` array is one object per *test case*; v1 emits one
  per *function*. Needs the per-path split (the bridge, `expected.returns[].step`, already exists),
  input **values** rather than ranges, and structural path conditions.
  See [UT_EXPORT_SPEC.md](../docs/spec/UT_EXPORT_SPEC.md) REQ-UE-04.
- **UT export open items** — `CoreType`, the `Macros` split, `format_version`, one file or two, the
  `id` scheme, and where a dynamic-behaviour spec's step transcription goes.
  `expected.returns[].step` is already the path bridge, so it stays additive provided `testCases[]`
  exists from day one, even holding one entry.
- **Global linkage** (`static` vs `extern`) for the UT export — lands in `parser.py`, the hottest
  conflict file, and needs an allowlist entry. Defer until after the merge.
