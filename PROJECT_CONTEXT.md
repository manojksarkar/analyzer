# C++ Codebase Analyzer — Complete Project Context

> **Audience: agents, not humans.** This file is read by Claude/other agents at the start of every session.
> Optimize it for findability and completeness, not polish — no prose warm-up, no formatting for human readers.
> A section outline is fine purely as an agent-navigation aid. Humans read the docs under `docs/` instead.

> **This file is the index — read all of it.** The detail is in [`project-context/`](project-context/):
> ten topic files and the dated history, each small enough to read in one go. Until 2026-09-28 all of it
> was this one file — 8,991 lines, and a reader got only its first 2,000: the newest change notes, never
> the architecture, which began at line 4,831. The split moved every line and dropped none
> ([how that was checked](#keeping-the-context-readable)).

## How to read the context

1. **This file, whole.** CLAUDE.md imports it; AGENTS.md sends every other assistant here.
2. **The role skill before you change code** — `.claude/skills/<role>/SKILL.md`: `engine-dev` (pipeline,
   model, views, DOCX, LLM, review & update), `engine-flowchart` (flowcharts, CFG, the incremental
   engine), `engine-behaviour` (behaviour diagrams), `ui-dev` (web app), `docs-maintainer` (any doc).
3. **The topic file for your area**, whole — see [which file for which task](#which-file-for-which-task).
4. **The history for the why.** Every change has a dated entry with its reasoning. All of them, one line
   each: `grep -n "^> Updated:" project-context/history/*.md` — or search a keyword.

The numbered sections (§1–§24) were kept current by hand and some have drifted — §1–§3 still name
`engine/run.py` as the entry point and `model/*.json` as the model store, and §24 names `frontend/`,
now `web-app/`. Where a section and a newer dated entry disagree, the newer entry and the code win.

## Current state

> **⭐ IN FLIGHT — branch `review_update_v2`, PR to `develop` (Review & Update: correcting LLM text
> in a document).** `review_update_v1` squash-merged onto `develop` 8628b2d (`b10a71b`) + follow-up
> commits; `review_update_v1` kept unchanged. Suites pass on SQLite; **the PostgreSQL run is next**.
> - **Merging or reviewing it? Read [docs/design/REVIEW_UPDATE_HANDOVER.md](docs/design/REVIEW_UPDATE_HANDOVER.md) first.**
>   Migration chain, the merge conflict surface file by file (§3.3: what the rebase changed in
>   develop's code), the invariants that break silently with the test that catches each, and
>   **§8: five decisions waiting on the develop owner** (BACKLOG `RU-1`…`RU-5`).
> - Contract: [docs/spec/REVIEW_UPDATE_SPEC.md](docs/spec/REVIEW_UPDATE_SPEC.md) (`REQ-` ids) ·
>   how: [docs/design/REVIEW_UPDATE_DESIGN.md](docs/design/REVIEW_UPDATE_DESIGN.md) ·
>   HTTP: [docs/spec/REVIEW_UPDATE_API_SPEC.md](docs/spec/REVIEW_UPDATE_API_SPEC.md).
> - Code lives in `engine/review/`; the rules for engine code that touches it are in the `engine-dev`
>   skill §8. Reasoning for every decision is in the dated history ([project-context/history/](project-context/history/)): the feature 2026-09-16 →
>   2026-09-20, the rebase onto develop 2026-09-26f → 2026-09-27d.

- **The PR is not opened yet** (2026-09-28). `develop` is the integration branch: work branches open
  their PR into it, and `main` has not moved since 2026-07-02. `review_update_v2` was cut from
  `develop` at `8628b2d` (2026-09-25).
- **The database-native pipeline (doc 10) has landed.** The model lives only in the database, keyed by
  version id; `model/*.json` is no longer a store, and a phase without `--version-id` refuses to run.
- The status boards that used to head this file (2026-07-20, 2026-08-14) are kept, unchanged, in
  [history/STATUS_BOARDS.md](project-context/history/STATUS_BOARDS.md). **They are not current** — the
  doc-10 work they call "planned, not started" is done; treat their other open items as unverified.

## The project in one screen

- **What it does.** Reads a C++ code base with libclang, builds one model of every function, global
  and type, and writes ASPICE documents from it, normally one per component: SWE.3 Software Detailed
  Design (`software_detailed_design_<group>.docx`) and SWE.4 Software Unit Test Specification
  (`software_unit_test_specification_<group>.docx`). The LLM writes only wording — descriptions, names,
  flowchart labels ([SWE3_WIKI](docs/spec/SWE3_WIKI.md#descriptions-the-only-llm-written-content)); ids,
  rows, arrows and every flowchart's shape come from the code.
- **Front door.** `python analyzer.py <command>`: `setup`, `onboard`, `grant`, `generate`, `reexport`,
  `status`, `check`, `report`, `doctor`, `check-llm`, `check-datadict`, `llm-stats`, `verify`. Human
  guide: [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md).
- **Pipeline.** Four phases, each its own Python process, run by `engine/run.py` through
  `engine/core/orchestration.py`: **1 parse** `engine/parser.py` → **2 derive** `engine/model_deriver.py`
  (units, components, call graph, interface ids, LLM descriptions) → **3 views** `engine/run_views.py` +
  `engine/views/` (`interfaceTables`, `unitHeaders`, `unitDiagrams`, `flowcharts`, `behaviourDiagram`,
  `testSpecs`, `utExport`) → **4 export** `engine/docx_exporter.py` (SWE.3), `engine/swe4_exporter.py`
  (SWE.4).
- **Storage.** Model, view output and run records are in the database, keyed by version id —
  PostgreSQL in production, SQLite for local runs and tests. Schema `api/db/postgres/schema.py` +
  `alembic/versions/`; map [docs/design/DB_SCHEMA.md](docs/design/DB_SCHEMA.md).
- **Identity.** Group and component ids carry their layer (`Layer1.My Sample`). A CLI version id is
  `<project>.<name>`, an API one `ver` + 8 hex; either is looked up only inside its own project.
- **Incremental.** A new version reuses what did not change from a baseline version
  (`engine/incremental/`).
- **API and web app.** FastAPI server in `api/`, whose job runner (`api/services/pipeline_runner.py`)
  runs `analyzer.py generate`; React web app in `web-app/`.
- **Review & update.** Reviewers correct LLM-written text: `engine/review/`, routes in
  `api/routes/text_overrides.py`.
- **Tests.** `python -m pytest tests/unit tests/api tests/e2e` — e2e runs the real pipeline on
  `SampleCppProject` (group `Layer1.My Sample`); `tests/live/` needs a real database.

## Which file for which task

| You are about to… | Read, after this file |
|---|---|
| get the whole picture | [ARCHITECTURE.md](project-context/ARCHITECTURE.md), then [VIEWS_AND_EXPORT.md](project-context/VIEWS_AND_EXPORT.md) |
| change parsing, the model or the LLM descriptions (Phases 1–2) | [PARSE_AND_DERIVE.md](project-context/PARSE_AND_DERIVE.md), [CORE_AND_LLM.md](project-context/CORE_AND_LLM.md); skill `engine-dev` |
| change a view, a flowchart, a behaviour diagram or a document (Phases 3–4) | [VIEWS_AND_EXPORT.md](project-context/VIEWS_AND_EXPORT.md); skill `engine-dev`, `engine-flowchart` or `engine-behaviour`; the rules each document section follows: [SWE3_WIKI](docs/spec/SWE3_WIKI.md), [SWE3_SPEC](docs/spec/SWE3_SPEC.md), [SWE4_WIKI](docs/spec/SWE4_WIKI.md) |
| change a CLI flag or the config | [CLI_AND_CONFIG.md](project-context/CLI_AND_CONFIG.md), [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) |
| work on incremental runs, baselines, reuse, the narrowed parse | [INCREMENTAL.md](project-context/INCREMENTAL.md); skill `engine-flowchart` |
| work on the database or storage | [docs/design/DB_SCHEMA.md](docs/design/DB_SCHEMA.md), [PRODUCTION_REDESIGN.md](project-context/PRODUCTION_REDESIGN.md), [docs/production-redesign/](docs/production-redesign/) 07–10 |
| work on the API or the web app | [API_AND_FRONTEND.md](project-context/API_AND_FRONTEND.md), [api/PROJECT_CONTEXT.md](api/PROJECT_CONTEXT.md), [web-app/PROJECT_CONTEXT.md](web-app/PROJECT_CONTEXT.md); skill `ui-dev` |
| work on review & update | [docs/design/REVIEW_UPDATE_HANDOVER.md](docs/design/REVIEW_UPDATE_HANDOVER.md); skill `engine-dev` §8; the history 2026-09-16 → 2026-09-27d |
| debug a failure that "cannot happen" | [RISKS_DECISIONS_LESSONS.md](project-context/RISKS_DECISIONS_LESSONS.md) — known risks, decisions, past mistakes |
| find out why something is the way it is | the [history](#history) — search the date or a keyword |

## The context files

| File | Holds |
|---|---|
| [ARCHITECTURE.md](project-context/ARCHITECTURE.md) | §1 What this project does · §2 Top-level layout · §3 The 4-phase pipeline · §15 Test fixture — `SampleCppProject/` · §20 Dependencies · §21 End-to-end code flow — single command, full pipeline |
| [PARSE_AND_DERIVE.md](project-context/PARSE_AND_DERIVE.md) | §10 Phase 1 — `engine/parser.py` · §11 Phase 2 — `engine/model_deriver.py` |
| [VIEWS_AND_EXPORT.md](project-context/VIEWS_AND_EXPORT.md) | §12 Phase 3 — `engine/run_views.py` + `engine/views/` · §13 The flowchart engine — `engine/flowchart/` · §14 Phase 4 — `engine/docx_exporter.py` |
| [CLI_AND_CONFIG.md](project-context/CLI_AND_CONFIG.md) | §5 CLI — `run.py` · §6 Config — `engine/config/config.defaults.json` |
| [CORE_AND_LLM.md](project-context/CORE_AND_LLM.md) | §7 `engine/core/` — infrastructure layer · §8 `engine/llm_core/` — unified LLM client + token-budget toolkit · §9 `engine/utils.py` — analyzer-specific helpers |
| [INCREMENTAL.md](project-context/INCREMENTAL.md) | §23 version4 — Incremental Changes feature (this session, 2026-06-18) |
| [PRODUCTION_REDESIGN.md](project-context/PRODUCTION_REDESIGN.md) | §22 Production Redesign (POC → Production) — design decisions |
| [API_AND_FRONTEND.md](project-context/API_AND_FRONTEND.md) | §19 API Server (`api/`) · §21 Companion: the older FastAPI backend (SUPERSEDED) · §24 Frontend — `frontend/designs/` |
| [RISKS_DECISIONS_LESSONS.md](project-context/RISKS_DECISIONS_LESSONS.md) | §16 Known risks / technical debt · §17 Key design decisions · §18 Past mistakes / lessons learned |
| [BRANCH_HISTORY.md](project-context/BRANCH_HISTORY.md) | §4 Refactor history (`version2` branch) · §4b LLM layer upgrade (`version3` branch) · §4c Test-framework branch (`feat/test-framework`) · §4d feat/from-main changes · §4e feat/auto-clang-includes changes · §4f Component-level DOCX export + space normalization |

Old references still resolve: "PROJECT_CONTEXT §N" → the table above (the headings keep their
numbers); "Risk N" → §16; a decision "D-NN" or a dated note → search `project-context/`.

## History

Dated `> Updated:` entries, newest first. A few sat out of date order in the single file and still do,
so neighbouring files can overlap by a few days — search the date tag.

| File | Entries |
|---|---|
| [10-2026-09-26.md](project-context/history/10-2026-09-26.md) | from 2026-09-26e — **the newest: new entries go at the top** |
| [09-2026-09-24.md](project-context/history/09-2026-09-24.md) | 2026-09-24 … 2026-09-26d (17 entries) |
| [08-2026-09-21.md](project-context/history/08-2026-09-21.md) | 2026-09-21 … 2026-09-23f (15 entries) |
| [07-2026-09-18.md](project-context/history/07-2026-09-18.md) | 2026-09-18b … 2026-09-21 (16 entries) |
| [06-2026-09-06.md](project-context/history/06-2026-09-06.md) | 2026-09-06 … 2026-09-21e (13 entries) |
| [05-2026-08-25.md](project-context/history/05-2026-08-25.md) | 2026-08-25b … 2026-09-08 (9 entries) |
| [04-2026-08-18.md](project-context/history/04-2026-08-18.md) | 2026-08-18 … 2026-08-29 (13 entries) |
| [03-2026-08-03.md](project-context/history/03-2026-08-03.md) | 2026-08-03 … 2026-08-14 (13 entries) |
| [02-2026-07-01.md](project-context/history/02-2026-07-01.md) | 2026-07-01 … 2026-08-09 (27 entries) |
| [01-2026-06-22.md](project-context/history/01-2026-06-22.md) | 2026-06-22 … 2026-07-01 (21 entries) |
| [STATUS_BOARDS.md](project-context/history/STATUS_BOARDS.md) | the two status boards that headed the single-file context, 2026-07-20 and 2026-08-14 — historical, not current |

## Other context and docs

- **Subsystem context:** [api/PROJECT_CONTEXT.md](api/PROJECT_CONTEXT.md) — partly stale by its own
  header, which points to [api/README.md](api/README.md) and [api/PLAN.md](api/PLAN.md);
  [web-app/PROJECT_CONTEXT.md](web-app/PROJECT_CONTEXT.md), with
  [INTEGRATION_NOTES](web-app/INTEGRATION_NOTES.md) and [TESTING](web-app/TESTING.md).
- **Role skills:** `.claude/skills/` — each role's coding rules and definition of done.
- **Human docs**, all linked from [README.md](README.md): [DESIGN.md](docs/design/DESIGN.md);
  [DB_SCHEMA.md](docs/design/DB_SCHEMA.md) and its viewer [schema-atlas.html](docs/design/schema-atlas.html);
  the rules each document section follows, [SWE3_WIKI](docs/spec/SWE3_WIKI.md) and
  [SWE4_WIKI](docs/spec/SWE4_WIKI.md); the contracts in [docs/spec/](docs/spec/); the CLI in
  [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md); open work in [docs/BACKLOG.md](docs/BACKLOG.md),
  [docs/planning/ROADMAP.md](docs/planning/ROADMAP.md) and the forward plans
  [engine/PLAN.md](engine/PLAN.md), [api/PLAN.md](api/PLAN.md), [web-app/PLAN.md](web-app/PLAN.md); the
  studies in [docs/production-redesign/](docs/production-redesign/).

## Keeping the context readable

- **Where a change goes.** The current truth about an area → the topic file that holds it. Every
  meaningful change → also a dated entry at the **top of the newest history file** (first row under
  [History](#history)): `> Updated: YYYY-MM-DD[a-z] (**one-line summary.** detail …)`, as before.
  In-flight work → [Current state](#current-state); keep it short, and move what is done into the
  history. A new area → a new file in `project-context/`, added to [the context files](#the-context-files).
- **Size limits**, so any tool reads a file whole: this index at most 300 lines; every file in
  `project-context/` at most 1,200 lines and 60,000 characters (about 20k tokens; one Claude Code read
  returns up to 25k). `tests/unit/test_project_context_fits.py` fails past a limit, or when a file is not
  linked from here. Newest history file full → start `NN-<date of its first entry>.md` with the next
  number and add its row. A topic file full → split it by section and update the table.
- **Links** in `project-context/` are relative to their own folder: `../engine/…`, and `../../docs/…`
  from `history/`.
- **The split (2026-09-28) was checked by a script.** Each of the single file's 8,991 lines is in exactly
  one place — here (title, audience note, the IN FLIGHT block), a topic file or a history file — in its
  original order. Nothing else changed except: link paths, rewritten for the new folders (same targets);
  4 links to headings, pointed at the file that now holds the heading (1 of them was broken and now
  works); the 15 lines over 2,000 characters, wrapped at sentence ends (same words, same rendering); and
  one phrase in the IN FLIGHT block, "the dated entries below", which now names the history folder.
