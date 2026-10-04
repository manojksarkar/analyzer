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

1. **This file, whole** — [What changed after the numbered sections](#what-changed-after-the-numbered-sections)
   included. CLAUDE.md imports it; AGENTS.md sends every other assistant here.
2. **The [timeline](project-context/history/TIMELINE.md)** — every dated change in one line, newest
   first, in one read. It is how you learn what the older sections do not say.
3. **The role skill before you change code** — `.claude/skills/<role>/SKILL.md`: `engine-dev` (pipeline,
   model, views, DOCX, LLM, review & update), `engine-flowchart` (flowcharts, CFG, the incremental
   engine), `engine-behaviour` (behaviour diagrams), `ui-dev` (web app), `docs-maintainer` (any doc).
4. **The topic file for your area**, whole — see [which file for which task](#which-file-for-which-task).
5. **The dated entries that touch your task** — the detail and the reasoning behind each change. Find
   them from the timeline, or by date tag or keyword in `project-context/history/`.

The numbered sections (§1–§24) were mostly written before September 2026 and kept current by hand, and
some have drifted — §1–§3 still name `engine/run.py` as the entry point and `model/*.json` as the model
store, and §24 names `frontend/`, now `web-app/`. Where a section and a newer dated entry disagree, the
newer entry and the code win.

## Current state

> **⭐ Review & Update — on `develop` since PR #70 (correcting LLM text in a document).** Merged from
> `review_update_v3` (`review_update_v1` squashed onto `develop`, follow-up commits, rebased onto
> `5542736`); the three branches are kept as records.
> - **Still open:** six decisions waiting on the develop owner — BACKLOG `RU-1`…`RU-6`, HANDOVER §8 —
>   and the follow-ups from the PR #70 review, BACKLOG `RF-1`…`RF-15`.
> - **Changing it? Read [docs/design/REVIEW_UPDATE_HANDOVER.md](docs/design/REVIEW_UPDATE_HANDOVER.md) first.**
>   Migration chain, what it changed in develop's code, file by file (§3.3), and the invariants that
>   break silently with the test that catches each (§4).
> - Contract: [docs/spec/REVIEW_UPDATE_SPEC.md](docs/spec/REVIEW_UPDATE_SPEC.md) (`REQ-` ids) ·
>   how: [docs/design/REVIEW_UPDATE_DESIGN.md](docs/design/REVIEW_UPDATE_DESIGN.md) ·
>   HTTP: [docs/spec/REVIEW_UPDATE_API_SPEC.md](docs/spec/REVIEW_UPDATE_API_SPEC.md).
> - Code lives in `engine/review/`; the rules for engine code that touches it are in the `engine-dev`
>   skill §8. Reasoning for every decision is in the dated history ([project-context/history/](project-context/history/)): the feature 2026-09-16 →
>   2026-09-20, the rebase onto develop 2026-09-26f → 2026-09-27d, the export guard per document
>   and the save-time SWE.4 re-derive 2026-09-29, the rebase onto `5542736` 2026-09-29b, the
>   full-feature review and its ten fixes 2026-09-29d, one response shape for a slot 2026-09-29e,
>   the REST API test tool (`tools/review_api_test/`) and the multi-group re-export fix 2026-09-29f,
>   the PR #70 review's seven fixes and the PostgreSQL run 2026-09-30.

- `develop` is the integration branch: work branches open their PR into it, and `main` has not moved
  since 2026-07-02.
- **The web app** (`web-app/` + `api/`) is built on branch `integrate/ui-v5`, which merged develop —
  review & update included — on 2026-09-30g. Its own history before that merge, 2026-09-29 …
  2026-09-30f, is [history file 12](project-context/history/12-2026-09-29-web-app.md). Review & update's
  screen is the document reader's **edit mode** (2026-10-01; [API_AND_FRONTEND.md](project-context/API_AND_FRONTEND.md)
  "Review & update in the web app").
- **Review and approval** (assign a reviewer, submit, approve, request changes, reopen; a version is
  approved when all its documents are) — built on branch `feat/review-approve` (committed `a55c9c5`, not pushed), 2026-10-01d.
  Backend complete before the office's 4-day generation, so what remains is web work. Contract
  [REVIEW_APPROVE_API_SPEC](docs/spec/REVIEW_APPROVE_API_SPEC.md), design
  [REVIEW_APPROVE_DESIGN](docs/design/REVIEW_APPROVE_DESIGN.md) (its open questions are still open), rules in
  `api/services/review_workflow.py`, recording in `api/services/document_registry.py` (every run, CLI too;
  `analyzer.py register` for older versions); a database upgrades with `analyzer.py setup` (migration 0015).
- **Staged generation** (2026-10-02, same branch, committed `a55c9c5`): one model per version, documents per
  component by any number of runs (`export`, `reexport`, `resume`), `--detach` for runs that last days, one
  writer per version (migration 0016); web runs go on in the background when the API restarts, and a
  run that dies keeps its version for `resume` (2026-10-02c); an `export` of a component from another
  layer adds that layer to the same version, the old layers' documents marked stale where it changes
  them (2026-10-04e). For the office's multi-day run — guide
  [CLI_COMMANDS](docs/CLI_COMMANDS.md#a-run-that-lasts-days), detail
  [API_AND_FRONTEND.md](project-context/API_AND_FRONTEND.md) "Staged generation".
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
- **Front door.** `python analyzer.py <command>`: `setup`, `onboard`, `grant`, `generate`, `export`, `reexport`, `resume`, `progress`, `components`, `register`, `user`,
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

## What changed after the numbered sections

The big shifts since most of §1–§24 were written. Each names its dated entry: find the tag in the
[timeline](project-context/history/TIMELINE.md), then open the entry in its history file.

- **Storage.** PostgreSQL became the source of truth (2026-08-13) and the file-backed model was removed
  (2026-08-23): the model lives only in the database, per version id; SQLite works for local runs and
  tests. Create or upgrade a database with `analyzer.py setup` — `alembic upgrade head` cannot build a
  fresh one (2026-09-01, 2026-09-21).
- **One CLI.** `analyzer.py` replaced four front doors (2026-08-24); `engine/run.py` still runs the
  phases beneath it. Re-derive without re-parsing (2026-08-25); a run says what it will do before it
  parses (2026-09-24g).
- **Config** has three sources with three roles (2026-08-09, §6): `config.defaults.json` (tracked
  defaults), `config.local.json` (this machine's secrets — database and LLM credentials) and each
  version's resolved config, stored in `versions.resolved_config`.
- **Per-layer inputs.** Macros as JSON, per layer (2026-08-07); the data dictionary per layer
  (2026-08-18); include paths from each core's `compile_commands.json` (2026-09-02), the project-folder
  walk only on request (2026-09-10); `clang.clangArgs` for cross-target parsing (2026-08-13).
- **Identity.** Group and component ids are layer-qualified (2026-09-06); one run may span layers
  (2026-09-07); a CLI version id is `<project>.<name>` (2026-09-24f).
- **Flowcharts** render with Graphviz DOT, not Mermaid, with word-wrapped labels (2026-07-27,
  2026-07-29 — notes in [STATUS_BOARDS.md](project-context/history/STATUS_BOARDS.md)); a component renders
  only its own (2026-08-25b); oversize pictures are handled (2026-09-21). Unit and behaviour diagrams are
  still Mermaid; the behaviour-diagram package was replaced (2026-08-22b).
- **What is published.** A `PUBLIC` marking no longer guarantees a row, and protected counts as private
  (2026-09-20); a function is published only when another UNIT calls it (2026-09-22b), a global only when
  another unit reads or writes it (2026-09-24c); a static member used through an object (`this->s_x`,
  `obj.s_x`) is a global use, for publication and direction alike (2026-09-25b). The client-facing rules:
  [SWE3_WIKI](docs/spec/SWE3_WIKI.md).
- **Unit header table.** No visibility filter (2026-09-23); struct, class and union are listed
  (2026-09-23b); an orphan header is listed once, by one owner unit (2026-09-24b); a declaration is read
  until its braces close, braces in comments and literals aside — no 60-line cap (2026-09-25, 2026-09-25b).
  The unit diagram draws the unit's published globals (2026-09-24).
- **SWE.4** runs on the database pipeline (2026-09-01b), prints class-qualified names (2026-09-21b) and
  agrees with SWE.3 on external callers (2026-09-21d).
- **LLM.** Every call is timed and attributed to a pipeline stage (2026-08-12b); the gateway throttle is
  `llm.rateLimitSeconds` (2026-08-12); `analyzer.py check-llm` asks the LLM directly (2026-09-24e).
- **API and web app.** A CLI-onboarded project is reachable over HTTP — `analyzer.py grant`, and a
  superuser who reaches every project (2026-09-22, 2026-09-22b); web-app runs go through
  `analyzer.py generate` (2026-09-26); a sign-in lasts a working day (2026-09-26b); a re-export is a job
  of its own (2026-09-26d). On `integrate/ui-v5` (history 12): a project has cores, and a config file
  goes in and out of the wizard (2026-09-29b, 2026-09-29d, 2026-09-30f); the SWE.3 page reads like the
  DOCX (2026-09-29e); a web run makes SWE.4 too (2026-09-30); flowcharts are server-drawn SVGs
  (2026-09-30b); `start-app` (2026-09-30c). A re-export writes every document the version has
  (2026-09-30h); a corrected flowchart label redraws the web page's SVG at once (2026-09-30i).
- **Review & update** — reviewers correct LLM-written text (2026-09-16 → 2026-09-29); see
  [Current state](#current-state).
- **Tools.** `tools/doccheck/` compares two generated documents by content (2026-09-22), on five levels
  with P1–P4 priorities, SWE.3 against SWE.4 as a pair (2026-09-26);
  `tools/audit_project.py` audits what a project stored (2026-09-05c).

## Which file for which task

| You are about to… | Read, after this file |
|---|---|
| get the whole picture | [ARCHITECTURE.md](project-context/ARCHITECTURE.md), then [VIEWS_AND_EXPORT.md](project-context/VIEWS_AND_EXPORT.md); the [timeline](project-context/history/TIMELINE.md) for what changed since |
| change parsing, the model or the LLM descriptions (Phases 1–2) | [PARSE_AND_DERIVE.md](project-context/PARSE_AND_DERIVE.md), [CORE_AND_LLM.md](project-context/CORE_AND_LLM.md); skill `engine-dev` |
| change a view, a flowchart, a behaviour diagram or a document (Phases 3–4) | [VIEWS_AND_EXPORT.md](project-context/VIEWS_AND_EXPORT.md); skill `engine-dev`, `engine-flowchart` or `engine-behaviour`; the rules each document section follows: [SWE3_WIKI](docs/spec/SWE3_WIKI.md), [SWE3_SPEC](docs/spec/SWE3_SPEC.md), [SWE4_WIKI](docs/spec/SWE4_WIKI.md) |
| change a CLI flag or the config | [CLI_AND_CONFIG.md](project-context/CLI_AND_CONFIG.md), [docs/CLI_COMMANDS.md](docs/CLI_COMMANDS.md) |
| work on incremental runs, baselines, reuse, the narrowed parse | [INCREMENTAL.md](project-context/INCREMENTAL.md); skill `engine-flowchart` |
| work on the database or storage | [docs/design/DB_SCHEMA.md](docs/design/DB_SCHEMA.md), [PRODUCTION_REDESIGN.md](project-context/PRODUCTION_REDESIGN.md), [docs/production-redesign/](docs/production-redesign/) 07–10 |
| work on the API or the web app | [API_AND_FRONTEND.md](project-context/API_AND_FRONTEND.md), [api/PROJECT_CONTEXT.md](api/PROJECT_CONTEXT.md), [web-app/PROJECT_CONTEXT.md](web-app/PROJECT_CONTEXT.md); skill `ui-dev` |
| work on review & update | [docs/design/REVIEW_UPDATE_HANDOVER.md](docs/design/REVIEW_UPDATE_HANDOVER.md); skill `engine-dev` §8; the history 2026-09-16 → 2026-09-29 |
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
| [TIMELINE.md](project-context/history/TIMELINE.md) | **every dated change in one line, newest first — start here** |
| [11-2026-09-29e.md](project-context/history/11-2026-09-29e.md) | from 2026-09-29e — **the newest: new entries go at the top** |
| [12-2026-09-29-web-app.md](project-context/history/12-2026-09-29-web-app.md) | the web app branch `integrate/ui-v5`, 2026-09-29 … 2026-09-30f (13 entries), written beside files 10–11 and closed when it merged develop (2026-09-30g) |
| [10-2026-09-26.md](project-context/history/10-2026-09-26.md) | 2026-09-26e … 2026-09-29d; at its end, develop's 2026-09-25 … 2026-09-26 (merged 2026-09-29) |
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
  meaningful change → also a dated entry at the **top of the newest history file** (the first numbered
  file under [History](#history)): `> Updated: YYYY-MM-DD[a-z] (**one-line summary.** detail …)`, as
  before, **and its line at the top of [TIMELINE.md](project-context/history/TIMELINE.md)**. A change
  that makes a numbered section wrong → fix the section, or add a line to
  [What changed](#what-changed-after-the-numbered-sections). In-flight work →
  [Current state](#current-state); keep it short, and move what is done into the history. A new area →
  a new file in `project-context/`, added to [the context files](#the-context-files).
- **Size limits**, so any tool reads a file whole: this index at most 300 lines; every file in
  `project-context/` at most 1,200 lines and 60,000 characters (about 20k tokens; one Claude Code read
  returns up to 25k). `tests/unit/test_project_context_fits.py` fails past a limit, when a file is not
  linked from here, or when a dated entry has no line in the timeline. Newest history file full → start `NN-<date of its first entry>.md` with the next
  number and add its row. A topic file full → split it by section and update the table.
- **Links** in `project-context/` are relative to their own folder: `../engine/…`, and `../../docs/…`
  from `history/`.
- **The split (2026-09-28) was checked by a script.** Each of the single file's 8,991 lines is in exactly
  one place — here (title, audience note, the review & update block of Current state), a topic file or a history file — in its
  original order. Nothing else changed except: link paths, rewritten for the new folders (same targets);
  4 links to headings, pointed at the file that now holds the heading (1 of them was broken and now
  works); the 15 lines over 2,000 characters, wrapped at sentence ends (same words, same rendering); and
  one phrase in that block, "the dated entries below", which now names the history folder.
  Rebased onto develop `5542736` (2026-09-29), develop's three newer entries (2026-09-25 … 2026-09-26)
  close history 10, as 09 had no room, and its two section edits are in ARCHITECTURE §2 and
  PARSE_AND_DERIVE §10; a script checked that none of the 195 lines develop added was lost.
