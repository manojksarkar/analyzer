# DB-Native Pipeline

> Removing `model/*.json` entirely: all four phases **and** the flowchart engine read and write
> their model from the database. Postgres in production, SQLite for local/internal testing —
> one code path, selected by config.
> Companion: [07-postgresql-migration-plan.md](07-postgresql-migration-plan.md) ·
> [09-post-migration-consolidation-plan.md](09-post-migration-consolidation-plan.md)

- [0. Where we are](#0-where-we-are)
- [1. Goal and scope](#1-goal-and-scope)
- [2. Decisions](#2-decisions)
- [3. Architecture](#3-architecture)
- [4. Schema changes](#4-schema-changes)
- [5. The flowchart engine](#5-the-flowchart-engine)
- [6. Incremental feature](#6-incremental-feature)
- [7. Configuration: no environment variables](#7-configuration-no-environment-variables)
- [8. Hazards found during analysis](#8-hazards-found-during-analysis)
- [9. Work order](#9-work-order)
- [10. Verification](#10-verification)
- [11. Open items](#11-open-items)

## 0. Where we are

Doc 09's storage work is complete and validated on the office box: the model, parse skeleton, view
outputs, run accounting and report are all in Postgres, `verify_model_parity` reports **OK for
all**, and an incremental run produces a document identical to a full run of the same commit.

But the *files are still there*, because the four phases are separate processes that hand JSON to
each other:

```
Phase 1 parser.py        ──writes──> functions.json ─┐
Phase 2 model_deriver.py ──reads ───────────────────┘──writes──> functions.json ─┐
Phase 3 run_views.py     ──reads ───────────────────────────────────────────────┘
Phase 4 docx_exporter.py ──reads ───────────────────────────────────────────────┘
```

`--prune-model-files` (C11c) deletes them *after* a run. This doc removes them from the run itself.

## 1. Goal and scope

**Goal:** no JSON file is read or written as pipeline state. The database is the only channel.

**In scope**

| | |
|---|---|
| `versions/<ver>/model/` | 15 files → gone |
| `versions/<ver>/parse/` | 10 files → gone (already in `parse_snapshots`) |
| `manifest.json`, `metadata.json`, `report.txt` | gone (already on the `versions` row) |
| `config.json` (per version) | source of truth becomes `versions.resolved_config`; materialized to a temp file only for `run.py --config`, which needs a path |
| `knowledge_base.json` | → new table |
| `incremental_plan.json` | → new table |
| `clang_include_paths.json` | derived in memory, never written |
| `functions_<group>.json`, `functions_incremental.json` | gone — replaced by an indexed query |
| `.flowchart_cache/llm_descriptions`, `aux_descriptions` | **removed, not relocated** — §5.3 |
| `.flowchart_cache/pkb_*.json` | **dropped** — derived from `functions.json`, holds nothing unique |
| flowchart engine **inputs** | all five read from the database |

**Out of scope this round** (deliberate — revisit as one piece for the whole project)

| | |
|---|---|
| `versions/<ver>/output/**` | `.mmd`, flowchart `.json`, `interface_tables.json` — unchanged. Note the consequence: **the flowchart engine still writes JSON output**, only its inputs convert. |
| `documents/*.docx`, PNGs | files by design (D-14) |
| the git checkout | files — libclang needs real source |
| `.mmdc_cache`, `.dot_cache` | rendered PNG binaries; belong with the `output/` work |

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D10-1 | Postgres is **required**; SQLite is a supported backend for local/internal testing | the dev machine has no Postgres, and the gates must be runnable there |
| D10-2 | **One code path** for both backends | the schema is already `JSON().with_variant(JSONB(), "postgresql")`, and `_insert_ignore` is the only dialect branch. If a new query needs a second branch, pick a portable construct instead |
| D10-3 | **No environment variable is ever a source of our configuration** — config file + CLI flags only | §7 |
| D10-4 | The flowchart engine becomes **DB-only**; no file-based input mode, not even for debugging | one path; debug against the SQLite dev database |
| D10-5 | The flowchart engine **reads the incremental plan itself**, by `version_id` | the restricted fid list is far too long for a command line; this is the only shape that avoids a file |
| D10-6 | Any future cache table is named `*_cache` | so that class of data can later move to a cache server without renaming. **Note: this work adds none** — see §5.3 |
| D10-7 | The disk LLM cache is **deleted, not migrated** | [04 §13](04-incremental-changes-implementation.md#13-caches-in-the-database-post-migration-doc-09-c12) already establishes it duplicates the reuse index. Correcting an earlier draft of this doc, which proposed a new table — §5.3 |
| D10-8 | A phase's input is an explicit `--version-id`, not "whatever is in `model/`" | required for phases to remain individually runnable once files are gone; also removes today's ambiguity |

## 3. Architecture

### The seam

```
Phase 1/2/3/4 + flowchart engine
            │
    core/model_io.py            ← 51 of 76 model read/write sites already pass through here
            │
    ModelRepository
       ├── DbRepository         Postgres or SQLite, keyed by version_id
       └── FileRepository       today's behaviour, kept only during the transition
```

Function signatures above the seam do not change: a phase keeps calling
`read_model_file(FUNCTIONS)` and gets the same dict. That is what protects behaviour while the
implementation moves.

`core/model_store.py` (moved down from `incremental/` — `core/` may not import from `incremental/`)
already holds `persist_model` / `load_model`; the repository is a thin façade over it.

### Phase contract

Every phase gains `--version-id`, applied before `paths()` is snapshotted (the ordering bug that
caused the missing-diagram regression — see doc 09 and `tests/unit/test_phase_path_overrides.py`):

```bash
python engine/run.py --from-phase 3 --version-id ver8130ed2e
python engine/model_deriver.py     --version-id ver8130ed2e     # standalone
python engine/flowchart/flowchart_engine.py --version-id ver8130ed2e --component Uart
```

### The 25 sites that bypass `model_io`

`os.path.join(model_dir, …)` reads scattered across `parser.py`, `model_deriver.py`,
`views/flowcharts.py`, `views/behaviour_diagram.py`. Each is routed through `model_io` (or the
repository) individually — no bulk rewrite, because a couple read *derived* files that will not
exist at all.

## 4. Schema changes

One additive migration (`0004`), nothing existing altered:

```
knowledge_base        version_id, payload JSONB          Phase 2 → Phase 3 hand-off
incremental_plans     version_id, payload JSONB          the plan the views + engine read
```

Two tables, both whole-object hand-offs never queried per field — same reasoning as
`parse_snapshots` (doc 09, C2). **No cache table** — see §5.3.

**`tu_includes` already exists in the schema and nothing writes it** — the same
declared-but-unwritten shape as `pipeline_status` and `versions.report`. This work starts writing
it, so the flowchart engine can query the header→TU map on its `(version_id, tu_path)` index
instead of loading a blob.

## 5. The flowchart engine

The engine is a separate program with a file-based CLI. Its inputs all load in **one block**
(`flowchart_engine.py` ≈ lines 543–570), which is what makes this tractable.

| CLI arg today | Becomes |
|---|---|
| `--interface-json <functions_*.json>` | query `entity_versions` + `content_blobs` by `version_id` (+ `--component`) |
| `--metaData-json <metadata.json>` | `versions.base_path` / `versions.project_name` |
| `--knowledge-json <knowledge_base.json>` | `knowledge_base` table |
| `--tu-includes <tu_includes.json>` | `tu_includes` table |
| `--cache-dir .flowchart_cache` | **removed** — §5.3 |

`EngineConfig` swaps those five path fields for `version_id` + `component`.

### 5.3 The LLM cache is deleted, not moved

An earlier draft of this doc proposed an `llm_response_cache` table and a one-time importer for
the existing entries. **That was wrong**, and
[04 §13](04-incremental-changes-implementation.md#13-caches-in-the-database-post-migration-doc-09-c12)
already says why: the disk `EntityCache` and the Postgres reuse index answer the *same* question
with near-identical keys.

```
EntityCache (disk)     sha256( entity source + sorted(callee hashes) + cacheVersion )
reuse index (Postgres) sha256( source_hash   + sorted(dep source-hashes) )
```

The reuse index stores a **pointer** to the version whose stored output already has the text (D3 —
content is never duplicated). Once the model is in the database, that pointer is enough: the
description is fetched from that version's `content_blobs`. So the disk cache has nothing left to
contribute; C12 is **removing a duplicate mechanism**, not relocating one.

Three consequences:

- **Nothing to import.** The reuse index is already populated and already used
  (`carry_forward_from_index`), so no LLM spend is lost by deleting the disk cache. The question of
  migrating those entries simply dissolves.
- **`llm.cacheVersion` becomes obsolete.** Its only job is invalidating the disk cache. Folding it
  into the reuse fingerprint was **deliberately rejected** (§3 / D3, "content-only"): an approved
  document is reused regardless of which model or prompt produced it. Removing the disk cache
  removes the setting.
- **Batched access is mandatory** (doc 09 B5a — already implemented as `get_many`/`put_many`). A
  per-entity index lookup is ~20k connection acquisitions on a 20k-function project.

`.flowchart_cache/pkb_*.json` is an index rebuilt from `functions.json`. It holds nothing unique and
is **dropped** — reading the model from the database makes it disappear on its own.

`.mmdc_cache` / `.dot_cache` hold rendered PNGs, are not database material (D-14), and belong with
the deferred `output/` work.

### Why the per-group filter gets *cheaper*

Today `flowcharts.py` writes a filtered `functions_<group>.json` so the engine sees one group.
The schema already has the index this needs:

```python
Index("ix_ev_version_component", "version_id", "component")
```

So `--component Uart` becomes an indexed query returning only that component's rows, instead of
loading the whole model and filtering in Python.

### What this costs

The engine stops being runnable without a database (D10-4). That removes a debugging path used as
recently as this week — accepted, with the SQLite backend as the replacement.

## 6. Incremental feature

The incremental flow splits cleanly across the scope line, which is why it needs little change:

| Step | Reads | Status |
|---|---|---|
| classify / impact BFS | hashes + model | already DB (doc 09) |
| baseline parse skeleton | `parse_snapshots` | already DB (C2) |
| plan written for the views | `incremental_plan.json` | **→ `incremental_plans` table** |
| restrict the engine to changed fids | `functions_incremental.json` | **→ engine reads the plan (D10-5)** |
| carry forward baseline flowcharts | baseline `output/` | unchanged — `output/` is out of scope |
| splice fresh flowcharts into carried JSONs | `output/` | unchanged |

Plan fields in use today, all of which move into the table unchanged: `impactFids`,
`impactedGlobals`, `impactedFiles`, `flowchartFiles`, `flowchartFids`, `crossVersionFlowcharts`,
`baselineVersionDir`, `merge`, `drop`.

`ANALYZER_BASELINE_FUNCKEYS` (an engine→phase env hand-off pointing at `func_keys.json`)
disappears: that file is already in `parse_snapshots`, so the phase reads it by version id.

## 7. Configuration: no environment variables

### Backend selection

```jsonc
// engine/config/config.local.json  (gitignored)
"db": { "url": "sqlite:///engine/config/analyzer-dev.db" }              // dev machine
"db": { "url": "postgresql+psycopg://analyzer:secret@10.0.0.9:5432/analyzer" }
// the existing field form keeps working:
"db": { "driver": "postgresql+psycopg", "host": "…", "port": 5432, "user": "…",
        "password": "…", "database": "analyzer" }
```

Precedence: `db.url` → `db.driver`+fields → error. `db` is a **machine-level** setting read from
`config.local.json` by every process independently, so nothing has to be propagated to a
subprocess — and credentials never enter a per-project workspace file or a command line where
`ps`/Task Manager would show them.

### Replacements

| Env var today | Replacement |
|---|---|
| `DATABASE_URL` ×6 | `db.url` |
| `ANALYZER_CONFIG` ×3 | `--config <path>`, forwarded to every phase |
| `ANALYZER_DATA_ROOT` ×3 | `--data-root <path>` |
| `ANALYZER_NO_DB` ×3 | `--no-db` |
| `ANALYZER_BASELINE_FUNCKEYS` ×4 | gone — read from `parse_snapshots` |
| `ANALYZER_VERSION_ID` | `--version-id` |
| `API_DB_BACKEND`, `DATABASE_CONNECT_TIMEOUT` | `db.*` keys |
| `LOG_LEVEL` | already `--verbose`/`--quiet`; forwarded as a flag |
| `LLM_TRACE_PROMPTS`, `FLOWCHART_TRACE`, `LLM_PROMPT_DUMP`, `LLM_FAKE_RESPONSES` | debug flags on `run.py`, forwarded |
| `LLM_API_KEY` | `llm.apiKey` (key already exists) |
| `LIBCLANG_PATH` | new `clang.libclangPath` key |

### The four that must stay, and why

These are not our configuration — they are how the OS or an external program is addressed. Their
**values come from config**; only the delivery is an env var.

| | Why it cannot move |
|---|---|
| `PYTHONIOENCODING` | read by the Python interpreter at startup, before any code runs |
| `PUPPETEER_EXECUTABLE_PATH`, `CHROME_PATH` | read by puppeteer / mmdc, third-party programs |
| `PATH`, `APPDATA` | the operating system's |
| `PYTEST_CURRENT_TEST` | set by pytest |

## 8. Hazards found during analysis

Each of these was missed by the first two drafts of this plan and is now a work item.

| # | Hazard | Handling |
|---|---|---|
| H1 | **`entities` and `content_blobs` both do read-then-insert on shared tables.** `content_blobs` is keyed on a global `content_hash`, and every entity with an empty payload hashes identically — so concurrent jobs collide near-certainly, not rarely | use the existing dialect-aware `_insert_ignore` (ON CONFLICT DO NOTHING) in both; move it to `core/` so `model_store` can reach it |
| H2 | Whole-model writes in one transaction; per-phase writes multiply that | chunk at the `_MAX_IN_PARAMS` bound `pg_stores` already uses; one transaction per phase persist, so a phase dying mid-write leaves the previous state |
| H3 | `--use-model` means "reuse existing `model/` files"; re-export stages `adir/model` | both become "reuse the stored model for this version" — needs the version id |
| H4 | `--clean` deletes the `model`/`output` dirs — misleading once the model is in the database | also delete the version's rows, or rename the flag |
| H5 | Three test files `skipif(not HAS_MODEL)` against `<repo>/model` — they would **skip permanently and silently**, losing the real-model round-trip coverage | fixture that materializes a model from the database |
| H6 | `verify_model_parity` compares database against files — it becomes meaningless with no files, exactly when it is most wanted | **resolved:** keep the file writer behind a debug-only `--dump-model-files <dir>` so the check works forever. Never used by a job; §10 |
| H7 | Memory: a DB read holds query rows *and* assembled dicts at peak, so it may be **worse** than `json.load` | measured at step 8, not argued. If it lands badly the fix is the per-target context service (doc 09, C7) |

## 9. Work order

Steps 1–7 leave current behaviour intact — the file path stays default and nothing is deleted.
**Stop at step 8 for sign-off** before flipping the default or removing code.

Progress as of **2026-08-17** (branch `db-migration`): steps **1-6 done**, each verified on
SQLite with all gates green. In database mode the model dir is down from 14 files to **5** —
`clang_include_paths`, `entity_files`, `func_keys`, `metadata`, `override_pairs`.

| Step | Work | Reversible |
|---|---|---|
| ✅ 1 | SQLite backend + `db.url`; verify end-to-end on the dev machine | done |
| 2 | `ModelRepository`; `model_io` delegates; files still default | yes (flag) |
| ✅ 3 | `--version-id` threaded to all four phases, applied before `paths()` is snapshotted | done |
| ✅ 4 | H1 + H2: conflict-tolerant inserts, chunking, per-phase transactions | done |
| ✅ 5 | convert the 25 raw path sites | done |
| ✅ 6 | `knowledge_base`, `incremental_plans`, `tu_includes` tables + writers | done |
| 7 | flowchart engine → DB inputs (D10-4, D10-5); `clang_include_paths` derived; config → temp file | yes |
| 8 | H3–H6: `--use-model`, re-export, `--clean`, test fixtures, parity replacement · **then both modes run on the office project and the documents are diffed** | — |
| 9 | flip the default to the database | yes (flag) |
| 10 | **C12** — delete the disk LLM cache + `pkb_*.json` (§5.3). Must come AFTER the model is in the database (04 §13.4): every cache key derives from model content | **no** |
| 11 | delete the file code paths, except the debug-only writer (§10) | **no** |

## 10. Verification

Every step ends with all four gates green, and steps that change behaviour additionally require
**both modes producing identical documents**:

| Gate | Catches |
|---|---|
| `pytest tests/unit tests/api --skip-pipeline` | unit regressions |
| `tools/verify_incremental.py` | baseline resolution + reuse — **this is the gate that caught the wiring bugs the unit suite missed** |
| `tools/verify_model_parity.py` | fields silently dropped by the database |
| `tools/verify_incremental_parity.py --fast` | a diagram the incremental path fails to carry forward |

Lesson carried from doc 09's regressions: the unit suite repeatedly proved a *function* worked
while missing that it was *connected*. Any step that spans a module or process boundary also gets
a test asserting the wiring, not only the behaviour.

### Keeping parity checkable after the files are gone (H6)

The model **writer** survives behind a debug-only flag, so `verify_model_parity` keeps working
forever:

```bash
python engine/run.py … --dump-model-files <dir>      # debug/verification only
python tools/verify_model_parity.py <ver> --model-dir <dir>
```

Never used by a job, never a fallback, and not a second code path through the pipeline — it writes
the same dicts the database round-trip returns. It exists because this is the check that caught the
dropped global `description`, and the cost of keeping it is one flag.

## 10b. Corrections found by reviewing the work (2026-08-17)

| Finding | Fix |
|---|---|
| `_try_narrowed_parse` referenced `_stored` without ever assigning it — a **NameError on every call, in file mode too**. Shipped in C2 and described in that commit as applied; only half the edit landed | assignment restored (store-first, then files). `tests/unit/test_narrowed_parse_guards.py` now CALLS the function — 4 of its 5 tests fail against the broken version |
| Narrowed parse merges through model_dir **files**, so in database mode it would read empty dicts and write an **empty** skeleton — a wrong model, silently | refuses in database mode and falls back to a full parse, which is what the function already promises for anything unsafe. Converting the merge is follow-on work |
| Dead `_load_model_json_from_file` in `docx_exporter`, introduced with a comment claiming tests used it. Nothing did | removed |
| `insert` became an unused import in `pg_stores` when `_insert_ignore` moved to `core/db_util` | removed |

Why the first two survived: `--narrowed-parse` is opt-in, the API never sets it, and **neither
gate exercises it**. A code path no gate touches is a code path where a claim of "done" is
unverified — the same lesson as the diagram regressions, in a corner nobody runs.

## 11. Open items

- [ ] H7 — measure peak RSS in DB mode on the office project; decide whether C7 becomes a
      prerequisite rather than a follow-on
- [ ] `JOB_MAX_CONCURRENCY` raise is **independent of this work** and still pending its
      measurement (doc 09, D2b) — H1 is a prerequisite for it either way
- [ ] Whether `output/` conversion (deferred here) also moves the flowchart engine's *writes*, or
      keeps them as files under a temp dir
