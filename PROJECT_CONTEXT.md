# C++ Codebase Analyzer — Complete Project Context

> **Audience: agents, not humans.** This file is read by Claude/other agents at the start of every session.
> Optimize it for findability and completeness, not polish — no prose warm-up, no formatting for human readers.
> A section outline is fine purely as an agent-navigation aid. Humans read the docs under `docs/` instead.

> **⭐ WORK STATUS — 2026-08-14 · branch `db-with-increment-changes` (READ THIS FIRST in a new chat).**
> - **The PostgreSQL migration is COMPLETE and validated on the office box.** Postgres holds the model,
>   view outputs, reuse index, run metadata, resolved config and all app data. `JsonDatabase` is deleted;
>   the API is Postgres-only. The commit dir now holds ONLY the git checkout + `manifest.json` + `report.txt`
>   + `parse/`. Full detail: the dated entry below (2026-08-13) and §6.
> - **NEXT WORK IS PLANNED, NOT STARTED → [docs/production-redesign/10-db-native-pipeline.md](docs/production-redesign/10-db-native-pipeline.md)**
>   (2026-08-17). Removes `model/*.json` from the pipeline itself: all four phases **and** the
>   flowchart engine read/write their model from the database; SQLite becomes a supported backend so
>   the gates run on a machine with no Postgres; no environment variable remains a source of our
>   configuration. That doc is the source of truth for what to do next — 10 steps, gates after each,
>   with a **sign-off stop at step 8** before anything is deleted.
> - Doc 09 is **largely done** — see [09-post-migration-consolidation-plan.md](docs/production-redesign/09-post-migration-consolidation-plan.md)
>   for the remainder (concurrency raise pending its RSS measurement; C4/C7 context service; IN-4/IN-5).
> - **B0 DONE (2026-08-14):** the `job_max_concurrency` **default is now 1**
>   ([settings.py:47](api/services/settings.py#L47)). `<repo>/output` is gone too — runs render into
>   `versions/<ver…>/output`. **`<repo>/model` is the last shared dir** and the only remaining reason
>   concurrency must stay at 1; it goes with **C11**, not with a per-job folder.
>   ⚠ **Multi-node:** the semaphore is per API **process**, so N replicas give N × the limit — a global
>   cap needs a DB-backed lease (**B0c**, unfiled).
> - **Decided:** target concurrency **5–6 jobs** ⇒ adds **B5** (connection budget — engine subprocesses take
>   SQLAlchemy's default 15-connection pool each, so 6 jobs + API ≈ 100 vs `max_connections=100`; **solution is
>   designed and written up in doc 09 §B5** — `NullPool` for the engine, sized pool for the API) and **B6**
>   (LLM rate limits per process × 6).
> - **Deferred by decision:** group **A** (removing the Python→Python subprocesses). Measured at ~5–20s per
>   multi-minute run — a debuggability/simplicity win, not speed, and it does not address concurrency. **A0**
>   (capture subprocess `stderr`) is pulled out and still scheduled — 1h, no risk, kills the
>   "exited with code 1, no reason" bug class.
> - **⚠ Known gap — narrowed parse (M4.4/M4.6) has ZERO automated coverage**, is off by default and not
>   UI-reachable, but the **user requires it for large codebases** and its fingerprint gate was re-sourced to
>   the DB during the cutover. Validate before enabling (doc 09 **D1**) — same commit narrowed vs full, assert
>   identical model (what `--verify-parse` does at runtime).
> - **Gates to run after any change:** `pytest tests/unit tests/api` · `python tools/verify_incremental.py`
>   (DB-less two-version incremental) · `python tools/verify_pg_readers.py` (proves data is really IN Postgres —
>   every reader falls back to disk, so a green run alone proves nothing). API paths (sections, re-export,
>   document render) are NOT covered by the gates — they need a real two-commit run.
>
> **WORK STATUS / QUEUE — 2026-07-20 (SWE.3 content work; still open, separate track).**
> - **DONE + removed from the active batch lists:** 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7,
>   flowcharts-in-DOCX, orphan-header handling, 3.14, 3.15, 3.18, macro ingestion (2026-08-07).
>   **Remaining open:** function hide/unhide (Phase-3 JSON), 3.8, 3.9, 3.10, 3.11, 3.12,
>   3.13, 3.16, 3.19; 3.17 interim-landed (full precedence spec still pending).
> - **2026-07-20 — unit-header value-column batch (3.20–3.22):** all fixed in
>   `docx_exporter._build_unit_header_table` (exporter-only; **no parser/model change**, so no
>   snapshot/hash churn). New `_strip_comments()` helper (reuses `_COMMENT_STRING_RE`; removes
>   `//` and `/* */` incl. multi-line, **preserves string/char literals**) is applied to BOTH
>   columns before dedup → **3.20 done** (comments gone from declaration + value; Korean handled
>   by removal, not translation, per user). The globals branch now takes the value column from
>   the RHS of the brace-depth `_read_decl_snippet` (multi-line-safe) instead of the single-line
>   `g["value"]` → **3.22 done** (arrays show `{ … }`, not a stray comment). **3.21 partial:**
>   comment-strip makes the `#define` value clean (`(24)`), but value *evaluation* (`(1<<6)`→`64`)
>   and the description fallback for value-less macros were **deliberately deferred** (eval/LLM
>   risk). Tests: `tests/unit/test_unit_header_comments.py` (9 cases). 3.20/3.22 removed from the
>   remaining list above.
> - **2026-07-21 — 3.23 conditional `#define` shows both branches (DONE):** a macro `#define`d once
>   per `#if/#else` branch appeared **twice** in the unit header (once per branch). Root: `_scan_defines`
>   is a **textual** scan (`parser.py`) that keys by `name@file:line` and never evaluates `#if`, so it
>   emitted every branch. Fix: libclang already parses with `PARSE_DETAILED_PROCESSING_RECORD` and its
>   preprocessor keeps only the **active** branch — new `_collect_macro_defs` (called in `parse_file`)
>   records active `MACRO_DEFINITION` lines per `(name, relFile)` into `_active_macro_lines`;
>   `_scan_defines` is now two-pass and, for a name with >1 textual definition in a file, keeps only the
>   line(s) libclang took (**fallback = keep all** when libclang has no info or no line matches, so a
>   macro is never lost). Branch follows the parse `-D` config → fully client-correct once per-layer
>   macros lands. **Parser/model change → snapshots regenerate.** Verified A/B (SOMETHING undef→else,
>   def→if). Test: `tests/unit/test_define_conditional.py` (libclang-guarded skip).
> - **2026-07-21 — e2e test suite resurrected + snapshots regenerated (DONE, test-only):** the
>   pipeline-backed e2e suite had been **dead since PR #19** (`2a1064f`), which renamed the fixture
>   group `Sample`→`My Sample` (component `Core`→`Sample Core`) in `engine/config/config.defaults.json` but
>   never updated the tests. Pipeline output now lives under `output/My-Sample/` (space→hyphen);
>   view/model keys are `Sample-Core|Core` (unit name still `Core`), diagram node `Sample-Core_Core`,
>   subgraph label `"Sample Core"`, interface ids `IF_LAYER1_*`. Fixed the harness group
>   (`tests/conftest.py`), all `output/Sample`→`output/My-Sample` paths, and every `Core|Core`→
>   `Sample-Core|Core` / `SAMPLE_COMPONENTS`→`{Sample-Core,Lib,Util}` key. **Rewrote the obsolete
>   topology assertions** in `test_unit_diagrams.py` and the mock tests in `test_unit_diagrams_view.py`
>   to the current 3.6/3.15 semantics: a unit diagram draws **only its OWNED (caller) edges** (built
>   from each function's `calledByIds`, oriented by the owner's In/Out); **callee edges are dropped**
>   (they render in the provider's own diagram). `_unit_part_id` now maps space→`-`, pipe→`_`. Added
>   `behaviour_diagram_on` skip-guard (Dynamic Behaviour section is empty when `views.behaviourDiagram`
>   is off) and relaxed the interface-id regex to allow the alphanumeric layer segment (`LAYER1`).
>   Regenerated `tests/snapshots/Sample/{interface_tables,unit_diagrams}.json`. Full suite: **627
>   passed, 4 skipped, 0 failed** (`pytest --skip-pipeline`). No engine code changed.
> - **2026-07-27 — flowcharts now render with Graphviz, not Mermaid (branch `fix/flowchart-issue`):**
>   the Phase-3 flowchart engine emits a **Graphviz DOT** script instead of Mermaid.
>   `engine/flowchart/dot_builder.py::build_dot(cfg)` replaces `build_mermaid(cfg)` at the
>   `_process_function` step (`FlowchartResult.mermaid_script` field kept for schema compat but now
>   holds DOT; `validate_mermaid` call dropped). Motivation: two client asks — **Return/End must sit at
>   the bottom** and **no crossing back-edge lines**. `dot_builder` runs a loop-aware pass
>   (`_analyze_loops`): **DFS-based back-edge detection** (NOT insertion order — the builder emits `End`
>   as N2 early, so a source-order test mis-flags every `return→End`), natural-loop bodies via reverse
>   reachability, then (a) invisible `tail→exit` push-down edges anchor Return/End below the loop body,
>   (b) back-edges get `constraint=false,headport=e` and the loop-exit branch `tailport=w,headport=w` so
>   the two run in separate lanes. Loop-free functions are a no-op. **Rendering:** new
>   `engine/config/render_dot.mjs` (viz-js DOT→SVG + full `puppeteer` SVG→PNG, auto-locates Chromium) +
>   `engine.utils.render_dot_cached` (content-addressed `.dot_cache`, mirrors `render_mermaid_cached`);
>   `views/flowcharts.py` calls it instead of `mmdc` and now guards on `node` availability. **Scope =
>   PNG/DOCX pipeline only** — behaviour/unit diagrams still use Mermaid (`render_mermaid_cached`/`mmdc`
>   untouched); the **web-app still renders the `mermaid` string client-side, so its in-app flowchart
>   view is NOT yet ported to DOT** (open follow-up). Verified e2e via the engine CLI on `SampleCppProject`
>   (`--no-llm`): 123 ✓ / 1 ✗ (pre-existing `_SOME_FUNCTION` cursor-resolve failure in `VoidAsVar.cpp`),
>   JSON carries `digraph`, PNGs render with Return/End at the bottom and no crossings.
>   **Reproducibility fixes (same day):** `package.json` now declares `@viz-js/viz` + `puppeteer` as real
>   `dependencies` (previously only transitive/manual → a fresh `npm ci` would miss viz-js and break the
>   renderer); lockfile synced offline. New **`tools/doctor.py`** prerequisite checker: probes each dep
>   **local→global in the pipeline's real resolution order** (python+pkgs, node, `@viz-js/viz`, puppeteer,
>   the Chromium puppeteer launches, `mmdc`, libclang via `LIBCLANG_PATH`→`config.defaults.json`→pip-bundled),
>   reports which location satisfied each, exits non-zero on missing REQUIRED. `run.py` calls
>   `doctor.preflight(need_flowchart, need_mermaid)` before `plan_runs` — **view-gated** (parse-only runs
>   aren't blocked by a missing browser/mmdc; flowchart views require viz+chromium, mermaid views require
>   mmdc+chromium), wrapped so the check itself can never abort a run. **Offline:** render path is fully
>   local at runtime (bundled viz-js WASM + already-cached Chromium); internet only at `npm ci`/install.
> - **2026-07-28 — flowchart engine console output cleaned up (branch `fix/flowchart-issue`):**
>   `flowchart_engine.py` now prints a **global `[idx/total] Processing: <name>` progress counter**
>   (running across all source files, denominator = `non_header`) so a run's progress is visible like the
>   PNG renderer's `[x/n]` (`tools/render_flowchart_pngs.py`). **Duplicate-log + stray-DEBUG bug fixed:**
>   the module-top `logging.basicConfig(...)` installed a second, level-less root handler that both
>   double-printed every line and leaked DEBUG to the console once `configure_logging` lowered the root
>   level to DEBUG; removed it (single config point = `core.logging_setup.configure_logging`, with a
>   `basicConfig` fallback moved **inside** the `except` branch for when the import fails). **Levels
>   right-sized:** startup banner/paths, LLM config banner, `Project:`/`Loaded N`, `── File:` headers,
>   no-llm/knowledge/budget notes, and per-function `✓ OK: N chars` are now **DEBUG (file-only)**; console
>   keeps the `Processing N function(s)` summary (now also counted from `non_header`, so it matches the
>   `[x/n]` denominator), the progress counter, and the final `Done. ✓ N ✗ N` line. Full detail still lands
>   in `logs/run_YYYYMMDD.log`. Log-output only — no CFG/structure change, determinism tests unaffected.
> - **2026-07-29 — flowchart node labels are word-wrapped (branch `fix/flowchart-issue`):** long
>   single-line labels made Graphviz size nodes very **wide** (height fixed) — DECISION diamonds, which
>   inscribe their text, sprawled worst. New `dot_builder._wrap_label(text, width=26)` greedily wraps a
>   label to ≤ `_LABEL_WRAP_WIDTH` chars/line, **breaking ONLY at spaces** (per user pref) and inserting
>   only newlines — identifiers are **never** split mid-word (a lone token longer than width keeps its own
>   over-wide line rather than a misleading hard cut). Applied in `_node_def` before `_escape`. Long **LLM
>   phrases** (spaced) wrap cleanly; the **no-LLM raw-identifier fallback** degrades gracefully (a 50-char
>   identifier with no space stays whole → that node is still wide, but 2 lines tall not 1). Label-only,
>   pure string transform — no node/edge/shape change, CFG/topo + shape-count determinism tests unaffected
>   (17 unit tests pass; no test asserts on label text). Width `26` is the tunable knob. Verified via a
>   long-identifier fixture render. **Also removed `splines=ortho`** from `_GRAPH_ATTRS` (same session, per
>   user): edges now use Graphviz's default **curved splines** (diagonal/curved) instead of right-angle
>   orthogonal routing — more compact, loop back-edges curve naturally. This **reverses** the 2026-07-27
>   "corner-routed / no crossing back-edges" client ask; the loop-anchor machinery (`constraint=false`
>   back-edges + invisible push-down edges) is kept and still works. Stale ortho comments in `dot_builder`
>   updated. `nodesep=1.5`/`ranksep=0.9` retained (could be lowered now that ortho no longer cuts through
>   nodes). **Docs synced to the DOT reality** (were still Mermaid-framed from before the 2026-07-27 switch):
>   `engine/flowchart/README.md` + `FLOW.md` (render step, module map, examples, testing section) and the
>   `engine-flowchart` SKILL. **One debt item filed** (`docs/BACKLOG.md` S3-6): the flowchart **Layer-2
>   test is stale** — `_count_mermaid_shapes` (`tests/unit/test_cfg_topo.py`) parses Mermaid syntax but the
>   persisted `flowchart` is DOT; it's opt-in via `--out-dir` so **dormant in CI** (Layer-1 CFG/topo still
>   runs). Also noted (not backlogged — cosmetic only): the flowchart `mermaid/` package is now **partly
>   legacy** (`build_mermaid`/`validate_mermaid` dead; `validate_cfg` + `normalize_edge_label` still used by
>   `dot_builder`). Project-wide Mermaid is unaffected — behaviour + unit/header diagrams still render via Mermaid/mmdc.
> - **⚠ Merge state:** 3.1/3.2/3.4/3.5/3.6/3.7 landed on feature branches with **PRs
>   pending into `poc-4`** (not merged); 3.14/3.15/3.17/3.18 are on `v1-fixes-more`. The
>   detailed per-branch bullets below are retained as the record of where each fix lives
>   and what is not yet merged — they are history, not open work.
> - **Landed on `poc-4`** (the current integration branch, origin/poc-4 = `61003f6`): flowchart-in-DOCX
>   (3.7), 3.5 (interface-table Source/Destination lists all non-self units, REQ-IT-12), ELK renderer
>   for unit + header-dependency diagrams.
> - **Committed + pushed on branch `fix/parser-emul-and-headers`** (commit `5774e61`, **PR pending into
>   poc-4**): **3.1** (exclude `*emul*` files from parse scope, `--include-emulator` opt-out wired through
>   run.py→group_planner) + **3.2** (parse `.h/.hpp/.hxx` as C++ TUs for header-only defs). Fixtures under
>   `SampleCppProject/Layer1/Signal/` (`SignalEmul.cpp`, `SignalInline.h`).
> - **DONE — orphan-header handling** (2026-07-17, branch `fix/interface-tables-and-unit-diagrams`).
>   An **orphan header** (`.h/.hpp/.hxx` with no same-name source) contributes its `#define`/`enum`/
>   `typedef` to the unit-header table of **every unit that USES it** — each unit shows only the subset
>   it references (never the header's full contents, never in a non-using unit). The "hard part" the
>   2026-07-15 exploration assumed didn't exist was **already solved**: `model/edges.json` carries
>   `macroUsers`/`typeUsers` (fid-keyed usage). Whole fix is in
>   `docx_exporter._build_unit_header_table` (loads edges + a `source_unit_paths` set; an entry not
>   matched by own-path is included iff it lives in an orphan header AND the unit uses it). **No
>   `model_deriver` change** — the exporter already emits only `.cpp`-backed unit sections, so the
>   orphan header never shows as its own unit. **Kept current kinds** (`define`/`enum`/`typedef`); the
>   `class`/`struct` skip at `docx_exporter.py:251` was **deliberately left as-is** per user. **Usage =
>   edges.json ∪ textual scan** of the unit's own source (comments/strings stripped) — the scan closes
>   the edges gap for **file-scope** macro usage (array size / global initializer / macro-in-macro) that
>   `macroUsers` misses. **Enumerator-only usage** (a unit references `eNone` but never the enum type
>   `SomeEnum` — parser records no `typeUsers` edge for a bare enum-constant `DECL_REF_EXPR`, and the
>   type name never appears in text) is now recovered by also matching an orphan enum when **any of its
>   enumerator names** appears in the unit's own text (2026-07-20, `_build_unit_header_table` enum
>   fallback). Fixture:
>   `SampleCppProject/Layer1/Sample/Core/SharedDefs.h` (orphan; `SHARED_MAX/MIN/SCALE` + `enum
>   SharedLevel : UINT8`) used by `coreLevelBudget` (Core: MAX+MIN+enum) and `libScaleShared` (Lib:
>   SCALE), Util uses none. **NOTE:** the header must live in a **mapped component dir** or
>   `is_project_file` (`_FILE_COMPONENT_MAP`) drops it from the parse entirely. Spec: `SWE3_SPEC.md`
>   REQ-UH-01/02. Test: `tests/unit/test_unit_header_orphan.py` (6 cases, filesystem-free). Verified
>   A/B: Core baseline 2 rows → 5 (+MAX,+MIN,+enum), own `enum Mode` unaffected.
> - **Committed on branch `fix/direction-transitive-writes`** (off `poc-4`, **PR pending into poc-4**):
>   **3.4** — interface direction re-derived from `writesGlobalIdsTransitive` at `model_deriver` finalize
>   (Phase 2), so a function that writes a global only *transitively* (e.g. `indirectWrite`,
>   `directionAdd`) now shows `In`, not `Out`. Header-defined globals need no special case (global-ID
>   based). See dated note below.
> - **Committed on branch `fix/unit-diagram-direction`** (off `fix/direction-transitive-writes`, so it
>   includes 3.4): **3.6** — unit-diagram edges now oriented by the interface **owner's** In/Out
>   (`In` → arrow *towards* owner, `Out` → *away*); one interface = one arrow; mutual pairs = two arrows
>   with the box drawn once. Diagram-only, no model change. See dated note below.
> - **Pending — partial machinery exists in code, but the issues are NOT fixed** (audited 2026-07-15,
>   status corrected with user — do not read "code exists" as "done"): ~~**macros ingestion**~~ →
>   **DONE 2026-08-07**, see the dated note below (JSON + per-layer + API/UI wiring).
>   **Function hide/unhide (task 4)** — `docx_exporter.py:1282-1568`
>   already drops functions flagged `f["hidden"]` from the DOCX (interface-table rows, call edges, unit
>   flowcharts); Phase-3 view JSON does NOT filter `hidden` (only Phase 4 does); exact pending scope still
>   **TBD with user** → **pending**. **3.8 if/else** — the flowchart builder already renders DECISION
>   diamonds `{…}` + labeled branch edges (`builder.py`), but the reported depiction issue is unfixed
>   (needs a concrete repro) → **pending**. **3.9 bending/overlapping edges** — already ELK with tuned
>   config (`builder.py:54-73`), but the tuning levers (`mergeEdges:true`, ↑spacing, explicit
>   `edgeRouting:ORTHOGONAL`) are not yet applied → **pending**.
> - **Next (greenfield):** **3.10** dynamic-behaviour — under-specified / other team. (3.6 is now done on
>   its branch — see above.)

> Updated: 2026-09-01b (**SWE.4 ported onto the DB-native pipeline; explicit `PUBLIC` was being
> ignored** — branch `feat/swe4-port`.
>
> **SWE.4 port.** `feat/swe4-v1` predates the Postgres cutover (it still carried `api/db/json_db.py`)
> and `feat/swe4-ut-export` sits on top of it — the UT export is a SEPARATE branch, easy to miss.
> Ported by copying the new files and 3-way-applying the deltas, NOT by merging: 22 new + 22 modified.
> `parser.py`, `flowcharts.py`, `run.py`, `group_planner.py` merged clean. Five conflicts, each keeping
> both sides: `flowchart_engine.py` (`NodeType` + `serialize_cfg`), `run_views.py` (`__none__` guard +
> `doc_type`), `docx_exporter.py` (accepted the extraction into the new `docx_common.py`),
> `tests/conftest.py` (**kept develop's DB-native e2e**, took only ut-export's `--doc-type all`; its own
> version reverted e2e to a direct `engine/run.py` call and would have dropped DB coverage), `README.md`.
> `engine/config/config.json` had to be hand-translated — develop renamed it `config.defaults.json`.
>
> **Two fixes the port needed, neither of them ported code.**
> (1) `docx_common.load_model_json` opened `model/<name>.json` DIRECTLY — the Phase-4 bypass doc 10
> step 5 removed. Left alone, SWE.4's exporter reads disk on a DB-backed run. Now `read_model_file`.
> (2) `--doc-type` existed all through the engine (`run.py` → `group_planner` → exporter registry) but
> was NOT exposed by `analyzer.py generate`, so the DB front door could never ask for SWE.4. Threaded
> through `analyzer.py` → `incremental/generate.py` → `incremental/engine.py` (only the `--from-phase 2`
> resume needs it; the `--to-phase 1` parses do not).
>
> **NO database work was required.** `test_specs.json` / `ut_export.json` ride `version_output_files`,
> which is extension-driven (`persist_output_files`, `.json` included) — not view-specific. `documents
> .process` is a free-text String, so SWE.4 needs no column. **Do not add a typed `view_test_specs`
> table**: `view_interface_tables` and `view_behaviour_rows` are already declared in `schema.py` and
> written by NOTHING — superseded by `version_output_files`, and they read as permanently-empty tables.
>
> **`_fn_is_private` ignored an explicit `PUBLIC`** (`model_deriver.py`, pre-existing on develop, NOT
> from the port). Explicit `PRIVATE` short-circuits to private and `addressTakenByUnits` short-circuits
> to public, but a `PUBLIC`-marked function fell through to the cross-file-caller rule — so a marked
> entry point with no by-name caller (ISR, registered callback, API called from outside the tree) was
> buried as private, given a `PIF_` id and DROPPED from the document. `_detect_visibility` had read it
> correctly; line 444 then overwrote it. Fixed by making `PUBLIC` authoritative, symmetric with
> `PRIVATE`. **Impact: 27 functions private→public (87→60 / 45→72) and 28 interface-ids renumber**, so
> **`tests/snapshots/Sample/*.json` must be regenerated** (not done — needs a full pipeline run).
> Verified on `Layer1/Poly/OpsTable` (the purpose-built fixture): `opsAdd`/`opsSub` public via the
> address-taken table, `opsDispatch`/`opsSeedValue` public via the annotation, and `opsSeed` — called
> from a file-scope initializer, not address-taken — correctly STAYS private.
>
> **Traceability gap (open, not a bug):** an address-take records only `addressTakenByUnits` (the
> registering UNIT), never the pointer variable. Nothing links `opsAdd` to `g_opsTable`. The forward
> direction (`g_opsTable[index]` → which entry) is genuinely unknowable; the backward one is not — the
> initializer cursor is in hand when the address-take is detected.
>
> **Verified:** one `--doc-type all` run emits SWE.3 + SWE.4 + `ut_export.json` (9 cases from 4 specs,
> 1 dynamic behaviour spec), status complete, 0 errors; `pytest tests/unit tests/api` green incl. 129
> SWE.4/UT tests. **Dynamic behaviour specs need BOTH ends of the interaction in the model** — the
> sample has exactly one (`Signal|acquireAndNormalize` ← `Cross|Hub|hubCompute`), so a scope holding
> only one side yields 0; that is correct, not a defect.)

> Updated: 2026-09-01 (**`llm_call_stats` timing columns were dead everywhere; `alembic upgrade head`
> cannot build a fresh DB (KNOWN, deliberately NOT fixed)** — found by running a real local Postgres,
> which the API tests' in-memory SQLite hides.
>
> **Fixed:** `schema.py` never received migration 0008's four columns — `llm_call_stats` declared only
> `{version_id, phase, kind, outcome, n}` while 0008 adds `latency_seconds`, `throttle_seconds`,
> `prompt_tokens`, `completion_tokens`. Both directions were dead: the WRITE in
> `llm_core/callstats.py::flush` renders only the 5 declared columns, so `sa.insert()` **silently
> discarded** the four values (proven — the insert reached Postgres and failed only on the FK), and
> the READ in `load_timing_for_version` guards on `hasattr(cols, "latency_seconds")` → `{}`. So LLM
> latency/token telemetry never persisted **anywhere, including boxes where the DB columns exist**,
> and `except Exception: pass` in `flush` hid it. The four columns are now declared (0008's types +
> `server_default="0"`); verified round-tripping through real Postgres.
>
> **KNOWN LIMITATION — do not run `alembic upgrade head` on an empty database.** It fails at 0002 with
> `DuplicateTable: relation "parse_snapshots" already exists`. Cause: `0001_initial` calls
> `metadata.create_all()`, and `metadata` is the schema as of TODAY — so on a fresh DB it creates all
> 36 tables including everything 0002–0008 add. A baseline that references "now" cannot be replayed,
> because replay happens at one moment and history did not. Deployed DBs never hit it (they walked the
> chain as each revision landed) and the API tests never run alembic at all.
> **Not fixed by decision (2026-09-01):** pre-production, no data worth preserving, and the migration
> discipline is already not followed — `job_functions` and `version_output_files` are in `schema.py`
> with **no creating migration**, so what a database contains depends on WHEN it was built, not on the
> chain. Half-maintained migrations give false confidence. **To create a database, use
> `python analyzer.py setup` (`tools/db_setup.py`) / `metadata.create_all()`, not the alembic chain.**
> Revisit when there is production data to preserve; at that point `create_all` on a fresh prod DB
> becomes the correctly-frozen 0001.
>
> **Local dev Postgres (no Docker, no admin):** portable PG 16.10 at `C:\Users\User\pgsql` — start with
> `bin\pg_ctl -D <root>\data -l <root>\server.log -o "-p 5432" start`, stop with `... stop`. Not a
> service; does not survive a reboot. pgAdmin 4 is bundled at `pgAdmin 4\runtime\pgAdmin4.exe`.
> `engine/config/config.local.json` (gitignored) carries the `db` block — it must exist even though it
> equals the compose default, because `core.db.is_database_configured()` deliberately does not count
> that fallback, so without it `run.py` silently skips Postgres.)

> Updated: 2026-08-25b (**the flowchart engine was rendering the WHOLE version for every
> component** — branch `integration/poc-4-db`. Reported as "it processes 2817 functions where the
> old JSON build processed 15", and it is the most serious defect the migration left behind.
>
> **Root cause.** With `--version-id` the engine loads the model from the database and ignores
> `--interface-json` entirely. The scope used to travel inside that file: `views/flowcharts.py`
> wrote a pre-filtered `functions_<group>[_units_X].json` and passed its path. That write is
> guarded by `os.path.isfile(model/functions.json)` — a file that does not exist in database
> mode — so it never happens, and nothing replaced it. `_load_inputs_from_db` had a `component`
> filter but the view never passed `--component`, and no unit filter existed at all.
>
> Measured on SampleCppProject before the fix: `App/flowcharts` and `Math/flowcharts` each held
> 35 PNGs covering BOTH units — 70 renders where 35 were wanted, every component's directory
> holding the whole project. After: App 19 (Main only), Math 16 (Utils only), and the engine logs
> `loaded 9 function(s) ... component=app`.
>
> **Fix:** `--component` is repeatable and `--unit` is new on the engine; both filter the loaded
> model, case-folded. `flowcharts.py` passes the run's components and selected units whenever it
> passes `--version-id`. The engine's "loaded N function(s)" line was promoted from debug to info
> so the count is visible without turning logging up — it is the number that makes this class of
> bug obvious.
>
> **A correction to the earlier entry:** the "70 -> 35 with --unit Utils" measurement recorded on
> 2026-08-25 was wrong. It was not narrowing — it was the App component's Phase 3 CRASHING on the
> unresolvable unit, before the strict/tolerant split fixed that. Unit narrowing genuinely reached
> the flowchart engine for the first time here.
>
> **Parity with poc-4, checked rather than assumed.** The question that matters is whether the
> database filter picks the same functions poc-4's file filter picked — same behaviour, only the
> storage changed. The selection logic now lives in one place, `flowchart_engine._apply_scope()`,
> lifted out of `_load_inputs_from_db` so it can be exercised without a database.
> `tests/unit/test_flowchart_scope_matches_poc4.py` carries poc-4's `_in_scope` verbatim from
> `origin/poc-4:engine/views/flowcharts.py` and runs both over the same keys across 9 scope
> combinations, including the cases that decide the edges: a component typed in a different case,
> a signature with extra `|` separators, a key with no separator, and empty halves. Zero
> divergence. Two source-text grep tests were retired in favour of it — matching an expression in
> a file proves nothing once the expression moves; only one structural test remains, that the
> loader still *routes through* the filter, since a filter nobody calls is the original bug.
>
> Verified on the live loader too, against `verdev1` (281 functions, 26 components, 92 units):
> every scoped load returns exactly one component or one unit, lowercase spelling matches, and
> **the 26 per-component loads sum to exactly 281** — the scope partitions the version precisely,
> losing and duplicating nothing.
>
> **Also fixed here, both found by the suite and both artefacts of the integration merge
> `8fca95b`, not of poc-4:** `engine/config/config.defaults.json` carried `llm.rateLimitSeconds`
> TWICE (`3.0` then `3`) — both sides of the merge contributed one and both were kept. JSON takes
> the last, so the effective value was and remains `3`; the duplicate is simply gone. And
> `tests/e2e/test_flowcharts.py` parsed that file with a strict `json.load`, which cannot read the
> JSONC the project writes — it now uses `core.config._strip_json_comments` like every other
> reader. That parse error aborted COLLECTION of the whole e2e directory, which is why earlier
> runs reported a clean suite without ever executing those tests.
>
> 1364 passed, non-e2e, plus the three gates green. The e2e directory now collects and shows 131
> failures, all of them a Phase 1 parse failing in this environment: identical, 31-for-31, with
> these changes stashed, so they pre-date this work and are untouched by it — they are a separate
> thing to chase, not a regression.
>
> **`--scope` and `--unit` combine, and the wording when they conflict.** Asked whether
> `--scope "component:App" --unit Utils` still considers the component: it does — `cmd_reexport`
> passes `scope_to_args(scope)` AND `--selected-unit` both, and they AND, exactly as poc-4's
> `_in_scope` ANDed them. Verified on `verdev1`: App 9, Math 7, `unit=Utils` 7,
> `component=Math + unit=Utils` 7, `component=App + unit=Utils` **0**.
>
> That last combination exposed a bad message. `_resolve_units` already separates *unknown* from
> *elsewhere* internally, then printed `unknown --selected-unit 'Utils'` for both. Utils is not
> unknown — it is in Math. The two failures need different fixes (a typo is fixed in the name, an
> out-of-scope unit in `--scope`), so they now read differently: the out-of-scope error names the
> component the unit IS in and suggests the `--scope` that reaches it, while a genuine typo keeps
> its spelling suggestion. New `_unit_home()` does the lookup. Four tests pin both halves,
> including that narrowing the one wording did not swallow the other.
>
> **The model lost 8 fields between Phase 1 and Phase 2 — the worst defect of the migration.**
> Reported from a poc-4 vs integration/poc-4-db document comparison run on Manoj's machine
> (reviewed at 87452f0): every interface-table row read VOID where the signature belonged.
> Comparing the two `model_functions.json` dumps: `parameters` 112->0, `returnExpr` 122->0,
> `className` 4->0, `addressTakenByUnits` 2->0, `readsGlobalIds` 12->0, `writesGlobalIds` 11->0,
> and both transitive sets 35/31->0.
>
> **TWO independent root causes, neither of them the storage layer.** A persist->load probe with
> a complete record showed the store drops only three fields, so it could not explain `returnExpr`
> or the globals; instrumenting the live `persist_functions` showed Phase 1 never produced them.
>
>   1. `parse_calls_and_globals()` did ONE walk, not two. poc-4 ran `parse_calls` then
>      `parse_global_access`; those were merged into one parse for speed, and the merged function
>      calls `visit_calls` and NOT `visit_global_access`. The old `parse_global_access` was left
>      in the file uncalled — which is how it hid, the code looked present. That visitor is the
>      sole producer of `readsGlobalIds`/`writesGlobalIds` and, on `RETURN_STMT`, of
>      `function_return_expr`: six of the eight fields, plus every direction collapsing to
>      "Out: accesses no globals". Nothing failed; the run reported success.
>   2. `_FN_PAYLOAD_FIELDS` listed `parameters`, but Phase 1 emits `params` (parser.py:2072) and
>      Phase 2 is what renames it (model_deriver.py:449,1180). The allow-list dropped the only
>      spelling that exists at hand-off time, so Phase 2 found neither and computed []. `className`
>      and `addressTakenByUnits` have no column and no edge, so the payload was their only route
>      and they were not listed either.
>
> After both fixes all 140 functions agree with poc-4 on all 18 fields VALUE for value, not merely
> in presence. All 63 differing DOCX blocks trace to cause 2. Flowchart counts are back to poc-4's
> 22/12/11 per component (from 139/139/139) — that half was already fixed in d1a09df, before the
> review ran.
>
> **A sibling found by looking:** there are exactly two payload allow-lists and both had the same
> hole — `_GLOBAL_PAYLOAD_FIELDS` omitted `className`, so a class-scoped global lost its scope.
> Latent (the sample has none), fixed, and a test now pins the count of allow-lists so a third
> arrives with its own coverage.
>
> **Still open, and #1 of them matters most:** `tests/conftest.py:92` drives
> `run.py <proj> --clean --selected-group` with no `--version-id`, which DB-only mode now
> requires — Phase 1 dies with "no model repository is installed for this run". That is the true
> cause of all 131 e2e failures, which I had earlier called pre-existing environmental noise: true
> but beside the point, since they share one fixable cause. Until it is fixed nothing in CI can
> catch a regression of this class, which is exactly how eight fields went missing. Also open:
> `tools/verify_model_parity.py` is gone (it compared file- vs DB-backed models, which cannot
> exist now — the replacement worth building compares a version's model against the parse it came
> from); doc 10 §10 still promises `--dump-model-files` and `--model-store files`, neither of
> which exists; `tools/parity/capture_baseline.py:52` points at the renamed
> `engine/config/config.json`; and `llm.descriptions`/`behaviourNames` ship `true` here where
> poc-4 shipped `false` — consistent with "--no-llm must never be default".
>
> **All three now closed.**
>
> **The e2e suite runs again (was 131 failures, now 0).** `tests/conftest.py` drove
> `run.py <proj> --clean --selected-group` with no version, which DB-only mode requires. It now
> drives the supported CLI — `analyzer.py onboard` then `analyzer.py generate --scope
> "group:My Sample"` — against a scratch git repo made from SampleCppProject, because a version
> is identified by a commit. Two consequences of deliberate product changes had to be absorbed,
> both recorded in `tests/e2e_paths.py`: output lands under `workspaces/<pid>/versions/<vid>/
> output/<Component>/` rather than `PROJECT_ROOT/output/<Group>/`, and documents are per
> COMPONENT (`--component-per-docx` is the default for every non-component scope), so
> `test_docx.py` reads the group's three documents through one Document-shaped facade and the
> tests themselves are unchanged. Phase 1/2 write no files at all, so conftest materialises the
> model with `dump_model_to_dir` for the model-shape tests. One snapshot was re-baselined
> through `--update-snapshots`, NOT hand-edited: Core came back byte-identical, and Lib/Util
> differ only in which side of the module box a consumer sits on — same edges, same interface
> ids — which follows from the document unit changing from group to component. A trap worth
> knowing: `tests/` and `tests/api/` are both packages, so putting `tests/` on `sys.path`
> shadows the repo's real `api` — import `tests.e2e_paths`, with the REPO ROOT on the path.
> 1511 tests, 133 of them e2e.
>
> **`verify db-sync` is now the model-parity gate** rather than a dialect check. It asserted
> only `load_hashes() == what went in`; a field dropped on the way in changes no hash, which is
> why it passed all through the eight-field loss, and its fixture named almost none of the
> fields anyway. Its `f1` now carries every field a parsed function can have — both `params` and
> `parameters` — and `_field_diffs` compares them value for value after the round-trip.
> Confirmed by re-breaking the allow-list: it reports `f1.params: sent [...], got '<MISSING>'`
> and fails. This is the replacement for the deleted `tools/verify_model_parity.py`, which
> compared file- against DB-backed models and cannot come back in that form.
>
> **LLM defaults confirmed ON** by the user and now commented in `config.defaults.json` as a
> decision rather than an inherited value.
>
> **A poc-4 vs database DOCUMENT comparison, run scenario by scenario.** A `poc-4` worktree
> (`c15ee42`) and this branch, the same SampleCppProject-as-a-git-repo, the same config written
> in each branch's own spelling — every view on, LLM off, `--project-name` pinned on both sides
> because poc-4 defaults it to the checkout dir basename while the database side uses the
> project's display name. Each side's `output/` is collected whole (DOCX text and tables, .mmd,
> .json, PNG names) with timestamps, absolute paths and shas scrubbed, then compared.
>
> **All seven scenarios MATCH**, up to and including `project`: 777 artifacts, 26 documents,
> every block equal.
>
> **What that sweep does NOT cover — behaviour diagrams.** The config turns `behaviourDiagram`
> on and the view runs, but SampleCppProject produces ZERO diagrams from it: every component's
> `_behaviour_pngs.json` comes out as `{"_docxRows": {}}` on BOTH branches. So the sweep
> exercised the view's invocation and not its output, and "every view on" must not be read as
> "every view verified". The gate is the default `skip_within_unit` filter mode, which needs the
> target's FORWARD call chain to span more than one unit as well as an external caller; a
> purpose-built three-component fixture (Alpha -> Beta -> Gamma, cross-unit call edges confirmed
> present in the model) still produced zero on both branches, so the real gate is narrower than
> that and is not yet pinned down. Anything about behaviour-diagram embedding in the DOCX is
> therefore UNVERIFIED by this work, in either direction.
>
> **That gap immediately cost something.** Reported from a real project: the
> behaviour_diagrams directory holds .mmd and .png files, `_behaviour_pngs.json` reads
> `{"_docxRows": {}}`, and the document's Dynamic Behaviour section is empty. Reproduced with a
> two-component fixture (Alpha calls into Beta; Beta must hold TWO units, because the default
> `skip_within_unit` selector counts only units inside the target's OWN component — that is why
> the first two fixture attempts produced nothing).
>
> **Root cause: the view and the generator disagreed about what "external" means.** The
> generator decides which diagrams to write, and an external caller is one in a DIFFERENT
> COMPONENT (`selector.get_external_callers_with_component`: `caller_component !=
> current_component`). The view then paired the returned .mmd files with callers POSITIONALLY —
> `if idx >= len(external_callers): break` — having recomputed the list as "outside the selected
> components" whenever a scope was set. Those two definitions diverge the moment ONE DOCUMENT
> SPANS SEVERAL COMPONENTS (`--scope "component:Alpha,Beta"`, or any group-level document): a
> caller in a sibling component is external to the generator and internal to the view, so
> `external_callers` came out empty, the loop broke at idx 0, and the row was never recorded —
> after the files had already been written. The view now uses the generator's rule, and only
> that rule.
>
> **poc-4 has the identical defect** — same fixture, `--selected-group Both` without
> `--component-per-docx`, same `{"_docxRows": {}}` beside a written .mmd. Not something the
> migration introduced; it surfaces here because a multi-component document is more reachable
> (`per_component_docx_args` returns `[]` for a component scope, so `component:A,B` is one
> document). Fixed on this branch only.
>
> **A SECOND, unrelated cause of the same symptom — and this one is ours, not poc-4's.**
> Reported again from the real project: 8 diagram files on disk, 0 rows, after
> `generate` (interrupted at phase 3) then `reexport --unit completion`.
> `_behaviour_pngs.json` is the only thing the exporter reads, and the view rewrote it
> UNCONDITIONALLY at the end of every run. Right for a full run, which regenerated
> everything the component has; wrong under `--selected-unit`, where the view only looked at
> the named units. On every component that does not hold that unit the filter leaves zero
> functions, so the manifest written by the earlier full run is overwritten with `{}` — while
> every `.mmd`/`.png` stays on disk, which is precisely why it reads as an exporter bug.
>
> **poc-4 cannot hit this: its behaviour view has NO unit filter at all** (`--selected-unit`
> there narrows flowcharts only), so behaviour diagrams are always regenerated in full and the
> unconditional write is always correct. The filter came from `87452f0` — my own commit, the
> one that made `--unit` narrow every image view. In that same commit `unit_diagrams` got the
> guard it needed ("A full run wipes and regenerates. NOT when narrowed to a unit") and
> `behaviour_diagram` got the filter without the matching guard. Same commit, same reasoning
> applied to one sibling and not the other.
>
> A narrowed run now merges: the named units are fully recomputed so their old entries are
> dropped first (otherwise a unit whose diagram has since gone keeps a row pointing at a file
> nobody writes), everything else is preserved, and a full run still replaces. Reproduced end
> to end before fixing and verified after, including that re-exporting the diagram's own unit
> still yields exactly one row rather than two.
>
> The testing lesson is specific: my earlier verification of `reexport --unit` passed because I
> re-exported the unit that HAD the diagram — the single case that regenerates its own row and
> so hides the wipe.
>
> **Then the narrowing moved off the function list entirely.** `--unit` exists to re-check one
> unit's images against an already-generated model, and it could not do that for behaviour
> diagrams while it narrowed WHICH FUNCTIONS GET A ROW. Deciding whether a function needs a
> diagram is free — the selector returns nothing for almost every function, measured at ~0.01s
> across 2817, and 8 of 2817 qualify on the reported project; the cost is mmdc, seconds per PNG.
> So every function is evaluated and every row recorded, and only the RENDER is skipped for units
> the caller did not name, reusing whatever PNG is on disk. The manifest is complete by
> construction, `--unit` still skips the expensive work, and a narrowed run now HEALS a manifest
> an earlier one emptied — 0.14s against 5.6s for the full render. The merge became dead code and
> went; the orphan check is keyed on the .mmd files a run recorded rather than on whether a PNG
> exists, because a row whose image `--unit` skipped is still a row.)

> Updated: 2026-08-29 (**a missing baseline `address_taken` snapshot silently made
> pointer-table functions private** — reported against `integration/poc-4-db`, and confirmed
> independently before touching anything.
>
> A function reached ONLY through a file-scope table (`static const fp_t t[] = { fx, fy };`) has
> no named caller, so `calledByIds` is empty and `_fn_is_private` keeps it public through
> `addressTakenByUnits` ALONE. `_merge_address_taken` is file-aware and correct: it carries a
> baseline record forward when the target's file was not re-parsed. `_apply_address_taken` was
> not — it popped the field whenever the merged records held nothing for a function, so a
> MISSING baseline artifact was indistinguishable from a deliberate removal, and the field was
> wiped from functions in files nobody had touched.
>
> Not hypothetical: `address_taken` was registered in `DB_BACKED_PARSE` only in 421f4e5, so any
> version generated in database mode before that wrote it to a file nothing reads and has no such
> parse snapshot. Chain an incremental run off one and every table-published function flips to
> private with a `PIF_*` id, leaving the interface tables, the unit and behaviour diagrams, and
> the document.
>
> Reproduced A/B on SampleCppProject's `Layer1/Poly/OpsTable.cpp` fixture: A (intact baseline)
> kept `opsAdd`/`opsSub` public; B (same run, `fpv1`'s `address_taken` snapshot deleted first)
> flipped both to `private` + `PIF_*` with `addressTakenByUnits` gone. After the fix
> **B == A == baseline** on visibility, interface id AND `addressTakenByUnits`.
>
> The clear is now restricted to functions whose defining file was actually re-parsed, where the
> fresh records ARE authoritative — deletion semantics verified separately by removing `opsSub`
> from the table in a re-parsed file, which correctly sends it private while `opsAdd` stays. A
> baseline that has no `address_taken` records while its own functions carry
> `addressTakenByUnits` now logs a warning, because inheriting that silently is the whole
> failure mode.
>
> Workaround for an already-poisoned version: re-run with `--full`, or point `--base-version` at
> a version whose snapshot actually contains `address_taken.json`. Check with
> `select name from parse_snapshots where version_id = '<baseline>'`.) The harness is kept as `tools/parity/compare_with_poc4.py` — point it at a
> detached poc-4 worktree with `--poc4`, and junction node_modules into that worktree so both
> sides render mermaid identically.
>
> Three things must be equalised or every scenario "differs" for no reason, and all three are
> written into the tool's docstring: the CONFIG (each branch spells it differently — poc-4 reads
> `engine/config/config.json`, this branch takes `--config`), `--project-name` (poc-4 defaults it
> to the checkout directory's basename, this branch to the project's display name), and the rule
> that `--component-per-docx` cannot be combined with `--selected-component` — `run.py` refuses,
> and `per_component_docx_args` returns `[]` for a component scope. Getting that last one wrong
> is what failed both component scenarios on the first sweep; it was the harness, not the product.
>
> A poc-4 Phase 2 crash on the first sweep did NOT reproduce and was contention with a pytest run
> started alongside it — worth recording because it looked like a real failure for a while.
>
> That first scenario found ONE defect, and it is a real one: **the database returned the model
> in no particular order.** Of 84 artifacts and three documents, one block differed — `utilBlend`'s Requirements
> cell, listing the functions it calls, had `utilClamp` before `utilHalve` where poc-4 had them
> the other way round. Util.cpp calls `utilHalve` twice and then `utilClamp`, so poc-4 was
> right, and it got that for free by reading `functions.json`, which carries the parser's order.
> Neither database read asked for an order: `_entity_rows` had no ORDER BY (now file, then line,
> then `entity_key`, with `coalesce` rather than NULLS LAST so SQLite and Postgres agree on the
> unlocated entities), and the call/global-access and type/macro edge reads had none (now
> `edge_id`, which is insertion order, which is the order the parser found the calls). Views
> iterate the model without re-sorting, so it reached the documents — and it would have drifted
> between two runs on the same data, which is worse than differing from poc-4 consistently.
>
> A third `model_edges` query is deliberately unordered: it accumulates into sets that are
> `sorted()` before use. It says so in an `# order-independent:` comment, and the guard test in
> `tests/unit/test_model_order_is_deterministic.py` accepts that justification rather than its
> absence — opting out is a claim you have to write down. That guard is what found the third
> query in the first place, after I had already fixed the two I knew about.
>
> **The sweep then found the rest of the same family.** `load_units` read `model_units` with no
> ORDER BY, so the unit sections of `interface_tables.json` came out shuffled; poc-4 writes
> units.json in PATH order (the order the parser walks the files) and `model_units` has a `path`
> column, so that is now reproduced exactly, with `unit_key` as tiebreak. The entity join that
> fills `functionIds`/`globalVariableIds` was unordered too — now file, then line, like
> `_entity_rows`.
>
> **One difference was NOT ours, and saying so mattered.** `Iface/flowcharts/Flowcharts.json`
> differed in 2 of 25 flowcharts, and only in the order of `style=invis` push-down edges — the
> DOT is line-identical when sorted. `dot_builder.py` builds `back_sources` as a SET and iterates
> it raw, and lines 140/156 are byte-identical on both branches, so the order changes per PROCESS
> (string hashing is randomised per run) rather than per branch: two poc-4 runs disagree with each
> other the same way. Demonstrated with PYTHONHASHSEED 1..6 flipping `{'N6','N7'}`. Pre-existing,
> shared, not caused by the migration — fixed here anyway with `sorted()`, because a flowchart
> JSON that changes every run is worthless for diffing and for reuse hashing. To get an exact
> comparison the same one-line sort was applied to the poc-4 WORKTREE COPY, local only and
> labelled as such; patching the reference to make it agree is normally how a real defect gets
> hidden, and it was justified here only because the difference had already been proven to be
> process-level set iteration and nothing semantic.)

> Updated: 2026-08-25 (**re-derive without re-parsing; unit narrowing made to work** — branch
> `integration/poc-4-db`.
>
> **`reexport --from-phase 2`** re-runs derive -> views -> export from the stored parse skeleton.
> Phase 1 is never re-run: parsing is the expensive part and it is already rows. `--use-model` is
> now passed only for phases 3 and 4 — it means "skip phases 1 AND 2", so passing it with
> `--from-phase 2` would have skipped the very phase being asked for. Verified by deleting a
> version's `model_units` rows and watching them come back with
> `Phase 1: Parse C++ source - skipped (--from-phase 2)` in the log.
>
> **`--unit` now narrows every image view, not just flowcharts.** Its purpose is checking one
> unit's generated images, and unit diagrams and behaviour diagrams ignored it — so the flag
> saved the flowchart time and then drew every other unit's diagrams anyway. Both views honour
> `_analyzerSelectedUnits` now, with the same short-name matching, and a narrowed run does NOT
> wipe other units' diagrams (they are still valid, and the caller asked to re-check one).
>
> **The bug that made it unusable:** documents are produced per component, so Phase 3 runs once
> per component. `--selected-unit Utils` reached the App invocation as well as the Math one and
> killed the whole run with `unknown --selected-unit 'Utils'` — AFTER Math's diagrams had been
> rendered. A unit that is elsewhere is not an unknown unit. `_resolve_units` now takes
> `strict`: run.py validates once against the whole run's scope (strict, unchanged - a unit
> outside it still errors, and the two tests that guard this still pass untouched), while the
> per-component view invocation narrows to nothing and says which component it skipped.
>
> Three cases now: in scope -> rendered; in another component of the same run -> skipped with a
> message, run continues; nowhere or outside the requested scope -> hard error listing the real
> units. All three verified end to end.
>
> 1334 passed, 10 skipped; verify incremental / flowchart-reuse / parity green.)

> Updated: 2026-08-24e (**re-export left the database holding the OLD render** — branch
> `integration/poc-4-db`. Chasing "is per-phase execution correct?" properly turned up a real
> defect in the new `reexport`.
>
> **The verdict on phases:** each phase writes its own model rows correctly and independently —
> verified by clearing a version and rebuilding it a phase at a time (entity_versions 0 -> 60 and
> edges 0 -> 18 at phase 1, units 0 -> 2 at phase 2, unchanged through 3 and 4, all exit 0). What
> a phase does NOT do is everything the ORCHESTRATOR does around it: `versions.base_path`,
> `version_output_files`, the manifest, the report, fingerprints and the reuse index. So invoking
> phases by hand is right for iterating and wrong for producing a version — the model rows would
> be correct while base_path stayed stale, the stored render stayed old, and the next run found
> nothing to reuse.
>
> **The defect:** `reexport` ran run.py and stopped. It re-rendered `output/` on the local disk
> and left `version_output_files` holding the PREVIOUS render, so the document served from the
> database — or from any other node — silently stayed stale. The API's re-export path has always
> called `_capture_reexport_output`; the CLI's did not. It now calls `store.capture_output` and
> says what it stored. Proved it replaces rather than merges: wipe output/, re-export one
> component -> 1 stored file; full re-export -> 2.
>
> This is the same class as the manifest disk fallback and the label cache that silently stored
> nothing — a write that succeeds locally while the durable copy stays behind. Counting rows was
> not enough to see it; the count was identical because the previous render was still on disk.
>
> 1334 passed, 10 skipped; verify incremental + parity green.)

> Updated: 2026-08-24d (**generate reads branch and commit from the database** — branch
> `integration/poc-4-db`. Five things a real run through the new CLI turned up.
>
> **The version identity was being typed twice.** `onboard` records the project's branch and the
> version's commit; `generate` then asked for both again. `--branch` also defaulted to "main",
> so a project on `br_trunk` died at the clone with `fatal: Remote branch main not found` — from
> a flag the caller never typed. Both are optional now and resolved from `projects.default_branch`
> and `versions.commit_sha`; `generate --project-id X --version-id v1` is the whole command.
> Reproduced the failure first, then fixed it, then re-ran it.
>
> **A GitError reached the terminal as a traceback.** Now a message that names the branch and
> says to pass --branch or re-onboard.
>
> **new_project's "Ready. Next:" still printed `cd engine; python -m incremental.generate ...`** —
> the one message whose entire job is to say what to run next was naming an entry point that now
> only prints a redirect.
>
> **Per-phase database behaviour verified**, not assumed: cleared a version's rows and rebuilt it
> one phase at a time. entity_versions 0 -> 60 and model_edges 0 -> 18 at phase 1, model_units
> 0 -> 2 at phase 2, unchanged through phases 3 and 4 (they only read). All four exited 0.
>
> **Non-git local paths do not work, for any run.** Confirmed empirically: a plain directory fails
> at `fatal: Could not read from remote repository`. A commit is not optional anywhere — the
> version's directory is named `<commit[:16]>`, the checkout is `git clone --branch` plus
> `git checkout <sha>`, and baseline selection compares commits. Analysed only, no change made.)

> Updated: 2026-08-24c (**phase-level flexibility confirmed intact and exposed** — branch
> `integration/poc-4-db`. Two questions checked by running, not reading.
>
> **Was any of Manoj's unit work lost in the merge?** No. Diffed every engine file against
> origin/poc-4: the only unit-related lines poc-4 has that this branch does not are the four in
> run.py's pre-check that were deliberately REWRITTEN to read units through the repository
> instead of opening `model/units.json`, a file that stopped existing when the model became rows.
> The SWE.4 work Manoj may be thinking of is on `feat/swe4-v1`, which is 22 commits ahead of
> poc-4 and NOT merged into it — it adds `software_unit_test_specification_*.docx`, a different
> deliverable, scoped per component exactly as SWE.3 is.
>
> **Does per-phase scoping still work with the model in the database?** Yes, fully. Verified end
> to end: parse the whole project once (3 components, 3 documents), then re-render
> `component:Math` alone (1 document), `group:Support` alone (2), and phase 4 by itself rebuilding
> the DOCX from phase 3's `interface_tables.json` in 1.77s. Phases 3-4 read the model from
> Postgres instead of `model/*.json`; nothing else about the flexibility changed.
>
> What was missing was only the CLI surface: `reexport` hard-coded the version's stored scope.
> `--scope` now overrides it, which is the whole point of running the later phases alone — the
> model covers a layer and you re-render one component of it for the cost of the views. Scoping
> DOWN is free; scoping up beyond what the model holds is not possible and never was.
>
> 1334 passed, 10 skipped; verify incremental + parity green.)

> Updated: 2026-08-24b (**`--unit` reaches the pipeline; re-export stopped changing the document
> set** — branch `integration/poc-4-db`. Two findings from checking what Manoj's `--selected-unit`
> actually does.
>
> **What it does:** narrows the per-function FLOWCHART work in Phase 3 and nothing else. Measured
> A/B on the sample project — 70 flowchart PNGs without it, 35 with `--unit Utils`, exactly the
> other unit's suppressed. The model, interface tables, unit diagrams and the DOCX set are all
> untouched, so it is a speed aid for iterating on one unit, NOT a scope. `--scope unit:X` does
> not exist and cannot without a unit filter in the DOCX exporter, which has none — the smallest
> document unit is a component.
>
> **What was missing:** it was only reachable from `run.py`, never from a generate run — the
> orchestrators did not thread it. Now threaded through `generate_full` and `generate_incremental`
> to the one invocation that reaches Phase 3 (the `--to-phase 1` parses have no views to narrow),
> and exposed as `analyzer.py generate --unit` / `reexport --unit`.
>
> **A defect in the new `reexport`:** it did not pass the version's scope, so a project-scoped
> version came back as a single `Support.docx` where `generate` had produced `App.docx` and
> `Math.docx`. Re-export now reads the scope from the version's stored manifest and rebuilds the
> same document set. Caught by comparing output, not by reading code.
>
> 1334 passed, 10 skipped; verify incremental / narrowed-parse / flowchart-reuse / parity green.)

> Updated: 2026-08-24 (**one CLI: `analyzer.py`** — branch `integration/poc-4-db`. There were four
> front doors (`tools/new_project.py`, `python -m incremental.generate`, `python -m
> incremental.engine`, `engine/run.py`) and knowing which one a job wanted was folklore. Worse,
> two of them produced a version — `generate` for the first, `engine` for the rest — and picking
> wrong either wasted an hour re-parsing or failed outright. **That choice is gone**: `analyzer.py
> generate` always asks for incremental, and `generate_incremental` already resolves a baseline
> and delegates to `generate_full` when there is no usable one, so the data decides. `--full`
> forces the long way.
>
> Twelve commands, all with `--help`: setup, onboard, generate, reexport, status, check, report,
> doctor, check-llm, check-datadict, llm-stats, verify. Every one is a thin wrapper — the CLI
> decides nothing about how a version is produced, it parses arguments and calls the same
> functions the API calls. `verify` runs the gates by name (`verify --list`), cheapest first,
> stopping at the first failure unless `--keep-going`.
>
> The old entry points now PRINT A POINTER and exit 2 rather than quietly working: two ways to do
> one thing is the confusion being removed, so leaving them functional would have defeated it.
> `engine/run.py` keeps its CLI because it is what the orchestrator spawns per phase — it is not a
> front door, and `reexport` is the supported way to drive phases 3-4 by hand. Every user-facing
> message that named an old command (`core/db.py`, `run_context.py`, `report.py`, `store.py`,
> `api/main.py`) now names the new one.
>
> Two fixes fell out of the audit: `check_db` and `dump_db` wrote `check_db_report.txt` /
> `db_dump.txt` into the working directory on EVERY run — for commands whose whole job is to show
> you something, that is litter; `--out` is now opt-in and both print to stdout. `tools/
> diag_dialect.py` deleted (a one-off from a SQLAlchemy dialect incident, long since resolved).
>
> docs/CLI_COMMANDS.md rewritten from scratch around the one command, and audited mechanically in
> both directions: every flag the CLI accepts appears in it, and every flag it shows exists.
> Verified by running the whole walkthrough on a local-path repo — setup, onboard, generate (chose
> FULL by itself), commit a change, generate again (chose INCREMENTAL by itself), reexport, status,
> check, report — plus all six gates through `analyzer.py verify`. 1334 passed, 10 skipped.)

> Updated: 2026-08-23 (**poc-4 merged onto the DB architecture; the file backing removed** — branch
> `integration/poc-4-db`. Manoj's 34 commits (typedef/data ranges, per-layer data dictionary and macros,
> class scope in interface names, `address_taken`, unit-diagram edge layout, call-name flowchart labels,
> strict CLI validation, `--selected-unit`, LLM stage timing, clangArgs, the behaviour-diagram rewrite) on
> top of the Postgres migration. 17 files conflicted; resolved by intent, never by side. Four SILENT
> breaks the merge produced: `_KNOWN_FLAGS` did not list the eight database flags, so every DB run would
> have died at argv parse; `address_taken` was unregistered in the repository and fell through to a file
> nothing reads; `_looks_like_fallback` was deleted by the label rewrite while the label cache still
> imported it INSIDE a try, so the cache silently stored nothing; two `--clean` blocks survived, ours
> before the path guard, so a typo'd path still deleted `model/` and `output/`. The parser fingerprint
> needed BOTH sides — his per-layer include/macro args (or a macro change slips the gate) and our
> `base_path` fold (or the fingerprint changes every commit and narrowed parse never runs).
> **`--project-name` now carries the job's version tag**, reversing D-3: re-exporting v1 and v2 gives
> "v1.0" and "v2.1" rather than both naming the project. Migration **0008** adds `job_functions.class_name`
> (its absence failed every API insert with "Unconsumed column names") and latency/throttle/token columns
> on `llm_call_stats`. LLM accounting unified: Manoj's per-attempt measurement feeds BOTH
> `logs/llm_stats_*.json` and the database, and the run report now says where the wall clock went —
> throttle vs model, which a call count cannot distinguish. **File backing deleted**: `FileRepository`,
> `--model-store`, `--dump-model-files`, `FileStore`, `HashStore`/`EdgeStore`/file `ReuseIndex`, the
> commit-dir `manifest.json`, and the C11a dual-write hook. `make_store` now REFUSES without a database
> rather than silently returning a DB-less store nothing reads. `tools/verify_model_parity.py` went with
> it — it compared the DB against `model/*.json`, and with nothing writing those it could only compare
> against stale leftovers or a dump of the database itself. `verify_db_sync` survives, rewritten to build
> its own small model: what it proves is the DIALECT, which three rows exercise as well as three hundred.
> ONE file-writing path is deliberate — `ScratchRepository`, reached by `--model-scratch`, for the
> narrowed parse's partial pass, which carries no version id so it cannot write rows by accident.
> Gates: pytest 1334 passed / 10 skipped, verify_incremental, verify_narrowed_parse,
> verify_flowchart_reuse, verify_incremental_parity --fast, verify_db_sync, verify_db_rebuild —
> all green.
>
> **The rest of the JSON went with it.** `FileStore` (a second ArtifactStore writing
> versions/<ver>/ as JSON, reachable only with no database - `make_store` now REFUSES instead);
> `HashStore`/`EdgeStore`, which every run still CONSTRUCTED and never used once their readers
> moved to the store; `VersionStore`'s `config.json` and `manifest.json` written beside the git
> checkout; `functions_incremental.json` in the file-level flowchart branch; and four
> `ArtifactStore` file defaults that PgStore overrides and no subclass could reach any more -
> now `@abstractmethod`, so a future store cannot inherit a JSON writer by accident. The
> manifest DISK FALLBACK in `_read_engine_manifest` went too, and it had been merging the file
> OVER the database, so a version with both took the stale copy.
>
> **Deliberately still files, each for a reason that is not legacy:** the run's `output/`;
> `logs/llm_stats_*.json` and the metrics jsonl; the per-run `config.json`, `macros.json` and
> `clang_include_paths.json`, which cross a PROCESS BOUNDARY (the phases are separate processes
> handed `--config`; the source of truth is the project row and the file is only the delivery);
> and `ScratchRepository`.
>
> **D-19 (decision): the narrowed parse's partial output stays OUT of the database.** Doc 10
> records that the migration tried to land it in the real version and backed out during
> verification: `--use-model --from-phase 4` re-export reads the version's model, so a partial
> persisted there exports a document holding only the changed files. That decision is now
> enforced structurally rather than by a flag value - the partial phase runs with
> `--model-scratch` and is handed NO version id, so it has nothing to write rows against. Moving
> it into the database would also be slower, not faster: it is ~10 small JSON files for the
> changed TUs only, and a Postgres round trip per artifact would replace a few milliseconds of
> local disk. Parse is no longer where incremental time goes - LLM calls x `rateLimitSeconds`
> is, which is why the report now separates model time from throttle time.)

> Updated: 2026-08-22b (**behaviour diagram package replaced + LLM path rewired** — branch
> `fix/behaviour-diagram`. All 7 modules under `engine/behaviour_diagram/` swapped for an external version;
> it did not run as delivered (3 crash bugs) and its LLM imports pointed at `llm_client`, deleted in the
> version3 refactor. Now on `llm_core.LlmClient` with token-report staging + domain anchoring. **Default
> filter mode changed to `skip_within_unit`, which yields 0 diagrams on SampleCppProject** where the old
> default gave 11 — read the View 3 note before assuming the view is broken. First tests for the package
> (19). Full detail: §"behaviour diagram package replaced".)

> Updated: 2026-08-22 (**the CSV-failing-silently work rebased onto the per-layer data dictionary**
> — the two landed on `poc-4` in parallel and both rewrote the same merge function, so this is the
> reconciliation, not new behaviour. `_merge_external_data_dictionary` is now a thin shim over
> `_merge_dd_rows(path, layer)` and **passes the report lines through**, so the tests that drive the old
> name still see them.
> **(1) The merge report and the layer key had to be resolved by ONE rule.** The layered merge seeds a
> row from the global tier when the bare slot is not this layer's; the report decides matched-vs-new
> against a pre-loop snapshot. Written twice, those two answers drift. New `_dd_row_base(source, name,
> target_key)` holds the rule once and is called twice per row — with the **live** dictionary to build
> the entry from, and with the **snapshot** to file the report. `pre_existing` is now a shallow
> `dict(data_dictionary)`, not a set of keys, because the layered lookup has to read each candidate's
> `layer` and the loop stamps `layer` on what it writes. Shallow is enough: the loop rebinds
> `data_dictionary[target_key]` to a fresh `dict(existing)` and never mutates a snapshot value in place.
> **(2) `_csv_top_level_names` is keyed by layer** (`None` = the global tier), not one flat set. It
> licenses `_reresolve_struct_field_ranges` to overwrite a measured field width, and flat it would have
> let a **Layer2** CSV naming `BOOL32` rewrite a **Layer1** struct's `BOOL32` field — the layer-blending
> the per-layer work exists to stop. Same pass now calls `get_range(ftype, data_dictionary,
> entry.get("layer"))`; it was the last dictionary read still unscoped.
> **(3) `tools/check_data_dictionary_csv.py` gained `--layer`.** Passes C and D looked names up by
> BARE name, so against a layered model a correctly applied `--data-dictionary-layer` CSV reported
> *"NOT ONE row from this CSV is in dataDictionary.json"* and exited 1 — the tool's loudest ERROR, on a
> correct run. New `dd_key(dd, name, layer)` mirrors `_dd_target_key` + `_visible_to_layer` (layer key
> first, then the bare name only if it is global or this layer's); pass D resolves through
> `get_range(t, dd, layer)`. Omit the flag for a project-wide CSV and nothing changes.
> **(4) `parse_merge._merge_keyed` needed no reconciliation** — file-less keys take fresh (the CSV fix)
> and `_dd_store` registers `entity_files` for `qn@Layer` keys (the layer fix); they are disjoint.
> New tests: `TestLayeredMergeReport` in `tests/unit/test_data_dictionary_csv.py` (3 — a layer row on a
> global type is *matched* and leaves the global entry alone; duplicate layer rows on an unparsed type
> count **once** as new under the `name@layer` key; another layer's CSV does not license a field
> rewrite) — the layer-by-report interaction neither branch had a case for — and `TestAppliedPassLayerScoped`
> in `tests/unit/test_check_data_dictionary_csv.py` (4). No snapshot regen needed.)

> Updated: 2026-08-21 (**`tools/check_data_dictionary_csv.py` — pre-flight validator for the
> `--data-dictionary` CSV, written while diagnosing "all SWE.3 data ranges are NA" on the client
> project.** UNCOMMITTED, on `poc-4`. Reads the CSV exactly as `_merge_external_data_dictionary` does
> and reports what that merge stays silent about. Four passes: **A** encoding (the merge opens
> `encoding="utf-8"` and catches only `csv.Error`, so a cp1252 export aborts Phase 1 with an uncaught
> `UnicodeDecodeError`), delimiter, header — a renamed/absent `Name` column or a title row above the
> header makes `row.get("Name")` `None` for every row → *merged 0*, no other sign; **B** per-row —
> duplicate `Name`s, rows with an empty `Name` and a non-child `Kind` (dropped by `if not name:
> continue`, counted in **neither** `merged` nor `orphan_children`), unquoted commas past the header,
> non-identifier Names (`get_range` strips `const`/`*`/`&` **before** the lookup), and top-level
> `enum`/`struct` rows with no child rows below them — those reset `enumerators`/`fields` to `[]` and
> **destroy the parsed list**; **C** applied? — the merge writes top-level rows *unconditionally*, so a
> CSV name absent from `dataDictionary.json` proves the CSV never ran for that model; **D** NA audit —
> resolves every parameter/return/global spelling through the real `utils.get_range` (imported, not
> re-implemented) and buckets the NAs into *named in the CSV but still NA* / *unknown scalar — add these*
> / *aggregate or derived, NA is correct*. Exit 1 on any ERROR.
> `python tools/check_data_dictionary_csv.py <csv> --model-dir model [--quiet] [--limit N]`.
> Tests: `tests/unit/test_check_data_dictionary_csv.py` (one case per failure mode).
>
> **Engine fixes landed with it** (same branch, all tested):
> **(a) The merge report no longer lies** (`_merge_external_data_dictionary` +
> `_format_csv_merge_report`). matched-vs-new is now decided against a `pre_existing = set(data_dictionary)`
> snapshot taken **before** the row loop — testing `data_dictionary.get(name)` per row meant the 2nd row of
> a duplicated Name saw the entry the 1st row had just written and was filed under *"matched a parsed
> type"*, reporting a type absent from the source as a successful override. Two new report lines:
> duplicated Names (last row wins) and rows dropped for an empty `Name` on a non-child `Kind` (a
> merged-cell Excel export becomes a file of these; they were counted in **neither** `merged` nor
> `orphan_children`). The function now **returns** its report lines as well as logging them, so the
> counting is directly assertable.
> **(b) Struct fields can no longer contradict their own type** — new `_reresolve_struct_field_ranges()`,
> run after the CSV merge and before `write_model_file`. Field ranges are baked during the parse from the
> canonical clang type, ~1300 lines before the CSV is read, so a `BOOL32` field kept `0-0xFFFFFFFF` while
> the type entry said `0-1`. Re-answers only two cases: baked range is `"NA"`, or the field's base type was
> named by the CSV (`_csv_top_level_names`) — a **measured width outranks anything name-derived**.
> ⚠️ **Derived spellings are skipped unless CSV-named**: `get_range` answers a pointer from its pointee, so
> the first cut stamped `-0x80-0x7F` on `Widget_t.name` (`const char *`) — a signed-char range on a string,
> worse than the `NA` it replaced. Caught on the Sample; guarded by `_is_derived_type`.
> **(c) Incremental no longer discards file-less dictionary entries** (`parse_merge._merge_keyed`) —
> see the dedicated note below.
> **Verified end-to-end** on SampleCppProject: full suite **975 passed / 4 skipped**; the two snapshots
> (`interface_tables.json`, `unit_diagrams.json`) carry no struct-field ranges so **no snapshot regen was
> needed**; a run with a deliberately broken CSV logs all four report lines with `BOOL32` counted **once**
> as new despite two rows.
>
> **Not fixed, still live:** (1) types declared in include paths are never in the dictionary at all —
> `visit_type_definitions` returns early unless `is_project_file()` (`parser.py:1004`), so the CSV is the
> *only* source of a range for them — this is the design, not a bug; (2) there is **no `config.json` key**
> for the data dictionary — CLI `--data-dictionary` or the API's `data_dict_id` only (the Phase 1 banner
> *does* log the resolved path — that line already existed); (3) `api/routes/repositories.py:44` accepts
> `.xlsx`/`.xls` uploads but `pipeline_runner.py:643` only ever builds `datadict/<id>.csv` and guards with
> `if dd_path.is_file():` — **no xlsx→csv conversion exists anywhere in the repo**, so an Excel upload
> silently omits the flag. Deprioritised: the client is not using xlsx today.)

> Updated: 2026-08-21b (**incremental: a `--data-dictionary` CSV never reached an incremental run's model**
> — `engine/incremental/parse_merge.py::_merge_keyed`. `_file_of()` returns `""` for an entry with no
> `entity_files` mapping and no `@file` in its key: CSV-added dataDictionary entries, the `PRIMITIVES` seed,
> and the canonical builtins `_register_builtin_range` records. `""` is never in `drop`, so the by-file rule
> kept every baseline file-less entry and discarded every fresh one — **a CSV added after the baseline never
> landed at all, and an edited range lost to the stale baseline value**, silently, on every incremental run.
> The narrowed parse *does* receive the flag (`incremental/engine.py:184-185`), so the fresh model had the
> right data; the merge threw it away. `dataDictId` is recorded in the manifest but never compared, and
> `parseFingerprint` covers only clang args/std/toolchain — nothing forces a full re-parse when the CSV
> changes. Fix: file-less keys are owned by no file, so the by-file rule cannot arbitrate them — take fresh.
> **Union, not replace**, deliberately: a narrowed parse only registers the builtins its re-parsed TUs use,
> so dropping baseline file-less entries absent from `fresh` would lose builtin ranges owned by untouched
> TUs. **Residual, documented in the docstring:** a row DELETED from the CSV survives until the next full
> parse; the exact alternative (folding a CSV content hash into `parseFingerprint`) forces a full re-parse
> on every CSV edit and defeats the point of incremental. Tests:
> `tests/unit/test_incremental_parse_merge.py::TestFileLessEntries`, incl. one pinning that a type WITH a
> file still follows the baseline-wins rule.)

> Updated: 2026-08-18 (**Per-layer data dictionary — closes backlog SH-3.** Branch
> `feat/per-layer-data-dictionary` off `poc-4`. **The rule, decided with the user and general to every
> per-layer input: resolving anything for layer `L` uses global + `L` only; another layer's inputs are
> never consulted, and layers are never blended.** Macros (`args_for_scope`) and the Phase-3 flowchart
> include dirs (`_resolve_layer_dirs`) already obeyed it; the data dictionary and the Phase-1 include
> dirs did not.
> **(1) Root cause.** `data_dictionary` is keyed by bare qualified name and written by straight
> assignment, so two layers defining `UINT8`/`enum Status` meant **the last file parsed silently won,
> for every layer** — from source alone, before any client CSV. `run_views._filter_model_to_components`
> filters functions/globals/units/components and deliberately **not** `dataDictionary`, so every
> layer's DOCX could show another layer's range.
> **(2) Entries carry `layer`.** `parser.layer_for_rel_file()` resolves file → component → layer (the
> same path `clang_args_for` uses, so a type's layer and its TU's `-D` set cannot disagree). New
> `_dd_store()` keeps the bare key for the first writer and any same-layer redefinition (today's
> last-wins, unchanged) and writes `qn@<layer>` for a *different* layer, following the existing
> `typedef@qn:file:line` idiom. Builtins/`PRIMITIVES` are stamped `layer: None` = the global tier,
> visible to everyone. `_log_dd_collisions()` prints one line per name defined in >1 layer — these were
> invisible before, because the loser was overwritten.
> **(3) `get_range(type, dd, layer=None, _depth=0)`.** The layer filter is applied at **all three**
> lookup paths, because guarding only the direct hit lets the `qualifiedName` scan find the very entry
> just rejected, and the alias recursion resolve one hop down against another layer: direct hit
> (`utils.py:533`), qualifiedName scan (`:561`), alias recursion (`:549`/`:569` — `layer` is threaded).
> That scan is also where the pre-existing first-match-wins ambiguity lived, so one filter fixes both.
> `layer=None` keeps the pre-layer behaviour exactly, so every existing caller and test is unaffected.
> **(4) Config carries PER-LAYER inputs only.** `layers.<L>.dataDictionary` and `layers.<L>.macros` sit
> beside `path`/`groups`, so no layer name is repeated in a by-layer map where a typo matches nothing.
> New `core.config` helpers: `layer_source()`, `layer_sources()`. `clang.macrosByLayer` still works,
> deprecated; `layers.<L>.macros` wins for the same layer.
> **Project-wide sources are CLI-only** (user decision, 2026-08-18): `--data-dictionary` / `--macros`.
> A top-level `dataDictionary.file` key was built and then **removed** — every entry point already
> passes the project-wide dictionary as a flag (`run.py`; API/incremental via `currentDataDictId` →
> `--data-dictionary`, `incremental/generate.py:214`), so the key was a second silent source for one
> input. **`clang.macrosFile` / `clang.macroScopes` are the deliberate exception and stay honoured in
> code** — they are pre-existing (S3-1) and the API has **no** CLI path for macros: the main job path
> runs `incremental/{generate,engine}.py` (`_build_cmd` is re-export only, `pipeline_runner.py:1253`)
> and passes `--data-dictionary` but no macro flag, so the wizard's `preprocessor_definitions` reach
> Clang *only* through `cfg["clang"]["macrosFile"]` (`pipeline_runner.py:460`). Dropping that key would
> break the web macro feature end-to-end. Neither macro key appears in the shipped `config.json`.
> The shipped config wires the **per-layer** keys to the committed examples (Layer1/Layer2 populated,
> Layer3 left `""` to show both are optional) — empty/whitespace is treated as absent by
> `layer_source()`. Values, not `//` comments: the file is `.json`, so comments light up every editor
> with "Comments are not permitted in JSON" even though `load_config` strips them.
> **(5) CLI `--data-dictionary-layer <layer> <path>`** mirrors `--macros-layer` (repeatable, unknown
> layer → exit 1, missing file → exit 2). `_KNOWN_FLAGS` + the module docstring + `group_planner`'s
> call sites moved together, as `test_cli.py`'s AST walk requires.
> **(6) Phase-1 include paths were the same leak (was a deferred finding, promoted to a task).**
> `parser.py` flattened **every** layer's dirs into the module-level `CLANG_ARGS`, discarding the layer
> keys — masked in a single-layer run because run.py writes only the selected layer's dirs, so it bit
> exactly the multi-layer run. They now live in `_LAYER_INCLUDE_ARGS` and are appended by
> `clang_args_for()`, making that function the single per-TU resolution point for both includes and
> defines. A file outside every layer still gets all dirs (no global include set exists to fall back
> on; that is the pre-change behaviour and the only way an orphan header parses). Two consequences
> handled: `parse_global_access` was parsing with raw `CLANG_ARGS` (so it already missed per-layer
> macros) → now `clang_args_for(path)`; and `parseFingerprint` would no longer notice an include/macro
> change → it now hashes the global args plus every layer's includes and defines, sorted.
> **(7) Phase 4 needed no change** (the plan flagged it as unknown): `docx_exporter` reads ranges only
> from the already-resolved `interface_tables.json`, and its unit-header table selects dd entries by
> `location.file`, which is inherently layer-correct.
> **(8) Narrowed-parse trap found + fixed.** `parse_merge._file_of` falls back to the text after `@`
> when `entity_files` has no entry — for `qn@Layer2` that yields a *layer name*, which matches no
> dropped file, so the entry would be kept from the baseline forever and never refresh. `_dd_store`
> now registers `entity_files[key] = <real file>`.
> **Known limit → new backlog SH-5:** `entity_hashes` / `_type_keys` stay bare-qn on purpose. They must
> match `edges.json` `typeUsers`, which `visit_usage` keys by bare name and `impact_set` looks a changed
> hash key up in directly — a `qn@Layer` hash key would find no users and silently skip regenerating
> them. So two layers defining one type still share a hash (last definition wins) and a narrowed parse
> can miss a change in the loser; fixing it means keying `type_users` by layer too.
> **Verified:** full suite green (739 unit + pipeline), `tests/snapshots/Sample/interface_tables.json`
> **unchanged**. A/B on `SampleCppProject` with both layers given a dictionary overriding `int`:
> `model/dataDictionary.json` carries all three keys — `int` (global, libclang-measured, untouched by
> either CSV), `int@Layer1`, `int@Layer2` — and the Layer1 run renders `L1-ONLY-RANGE` for all 114
> occurrences, never Layer2's, while the default config still renders the ordinary
> `-0x80000000-0x7FFFFFFF`. (Sample `Layer2/Platform` has 156 functions all marked `private`, so its
> interface tables are empty — pre-existing, confirmed identical on a stashed baseline.)
> **(9) CLI naming made consistent — `--include-path` → `--include-path-layer`.** Every other
> layer-scoped flag says so in its name (`--macros-layer`, `--data-dictionary-layer`); `--include-path`
> took a layer as its first argument and did not, so you could not tell from the name that it was
> scoped. It has no project-wide sibling (an include dir always belongs to a layer), which is why the
> suffix was originally omitted — but "suffix it if it takes a layer" is a rule a reader can apply from
> the name alone, whereas "suffix it only when a global sibling exists" requires already knowing the
> flag set. Straight rename, no deprecation alias: every caller is in-repo
> (`api/services/pipeline_runner.py:660` is the only programmatic one), the flag was ~2 months old, and
> `run.py`'s unknown-option handler already suggests the new name — `--include-path` scores **0.824**
> against `--include-path-layer`, above the 0.7 `difflib` cutoff. An alias would be permanent cruft that
> recreates the same "which one is current?" ambiguity. Internal `include_path_args` renamed to match.
> Historical PROJECT_CONTEXT entries (2026-06-15 etc.) keep the old name deliberately — a dated log that
> gets rewritten to match today's names stops being a record.
> **Known inconsistency left alone (needs a decision):** `--include-path-layer` exits **1** on a missing
> directory, while `--macros-layer` / `--data-dictionary-layer` exit **2** on a missing file. Aligning
> them is a behaviour change, not a rename, so it was not folded in here.
> New tests: `tests/unit/test_data_dictionary_layers.py` (18 — isolation asserted once per lookup path,
> same-name-two-layers, global tier, collision bookkeeping) + `TestLayerSources` in
> `tests/unit/test_core_config.py` (7). Samples: `engine/config/data_dictionary.layer{1,2}.example.csv`,
> sharing `BufferSize_t` at different ranges, shipped **unreferenced** like the macro examples.)

> Updated: 2026-08-13 (**`clang.clangArgs` is now a discoverable config key — the fix for cross-target parse
> errors like `use of undeclared identifier '__builtin_arm_wfi'`.** No new plumbing: the key was already
> honored by both parse paths (`engine/parser.py:251` appends it to `CLANG_ARGS`; `engine/views/flowcharts.py:813`
> re-reads it for the Phase 3 flowchart subprocess) and overridable per project via `build_config.clang`
> (`api/services/pipeline_runner.py:444`) — it just appeared in **no config file**, so nobody knew it existed.
> Now present in `engine/config/config.json`, set to `["--target=arm-none-eabi"]`.
> **Why it matters:** clang declares the ARM hint builtins (`__builtin_arm_wfi/wfe/sev/sevl/nop/yield`,
> `isb/dsb/dmb`) **only when the target is ARM/AArch64**. CMSIS headers reach them via
> `#define __WFI __builtin_arm_wfi`, so parsing firmware with a host (x86) libclang errors on every use.
> Two fixes: (a) cross-target — `--target=arm-none-eabi` **alone is sufficient** (measured); add `-mcpu=<core>
> -mthumb` so the preprocessor takes the same `#if` branches as the real build, since the bare triple defaults
> to a generic ARMv4 core. On a project that includes libc headers this also drops the host system headers
> (expect `'stdio.h' file not found` unless `--sysroot` / `-I` is added) — **not** an issue for
> `SampleCppProject`, which has zero `#include <...>`; or (b) stub the builtins to no-ops through a
> forced-include header, `["-include", "<abs path>"]`.
> **Enabled in the base config**, which merges into every per-project config (`pipeline_runner.py:439-447`).
> Verified safe on 2026-08-15 by parsing the e2e scope (`--selected-group "My Sample"`) both ways:
> `functions.json` (141) and `dataDictionary.json` (91) come out **byte-identical**; the only delta is TUs with
> errors, 6 → 5, i.e. the 4 ARM builtin errors gone. The 5 remaining are pre-existing `unknown type name 'VOID'`
> in `Layer1/Signal/` + `Layer1/Diag/`, unrelated to the target. Override per project via `build_config.clang`,
> or in `engine/config/config.local.json`.
> **Trap:** changing `clangArgs` changes the parse fingerprint (`engine/incremental/fingerprint.py:30`),
> so the next run is a **full reparse**, not an incremental one.
> **Correction to an earlier claim in this entry** (it said clang's 20-error limit truncates the TU and drops
> declarations — **it does not**). Measured with libclang on 2026-08-13: an undeclared identifier in a body, an
> unknown return type, an unknown param type, a macro-mangled signature and a missing semicolon **all** leave
> the `FUNCTION_DECL` in the AST. The error limit caps *diagnostic output*, not parsing, so `-ferror-limit=0`
> buys log visibility, **not** recovered functions. The only tested shape that removes a function is an
> **inactive `#if` branch — which emits zero errors**. Consequence for triage: clang errors in the log are not
> evidence that a function is missing, and a missing function is usually a preprocessor/`-D` problem or
> pipeline-level filtering (`not-project-file`, `dedup-hit`, `_DIAG_FUNCTIONISH_KINDS`), not a parse error.
> **Fixtures encoding both halves** (`SampleCppProject/Layer1/Diag/`, picked up by the existing `Diag`
> group — no config change, and outside the `tests/snapshots/Sample/` surface so snapshots are unaffected):
> `ArmIntrinsics.h` (CMSIS-style `#define __WFI() __builtin_arm_wfi()`), `ArmIntrinsics.cpp` (4 errors on the
> host target, 0 with `--target=arm-none-eabi`, **all 4 functions recorded either way**), and `ArmGuarded.cpp`
> (`ArmEnterLowPower` behind an undefined `FEATURE_ARM_PM`: absent from the model with **no** diagnostic —
> the live example for `_scan_unrecorded_functions`, fixed by `-DFEATURE_ARM_PM`, not by the target flag).
> **Also fixed:** `.gitignore` listed `backend/config/config.local.json`, a path that has not existed since the
> `backend/` → `engine/` rename, so local machine-specific overrides were never actually ignored → corrected to
> `engine/config/config.local.json` (+ `last_run.json`). All three config loaders — `engine/core/config.py`,
> `pipeline_runner._load_base_config`, `doc_render._load_config` — strip JSONC comments, so the inline comment
> is safe; verified against all three, and `tests/unit/{test_core_config,test_utils,test_macro_input}.py` pass.)

> Updated: 2026-08-12c (**Phase 1 parse diagnostics — a log trail for "why is this function missing from
> `model/functions.json`?"** Branch `feat/phase1-parse-diagnostics`, `engine/parser.py` only.
> Motivation: Phase 1 had **zero `.debug()` calls**, ~17 bare `print()` (which never reach
> `logs/run_<date>.log`), and **discarded `tu.diagnostics` entirely** — so a function absent from the model
> left no trail at all. The flowchart engine already read diagnostics
> (`flowchart/ast_engine/parser.py::_log_diagnostics`), which is much of why Phase 3's logs felt usable.
> **Design constraints that shaped this** (all deliberate, don't "fix" them):
> (1) **Counters, not per-cursor logging.** `configure_logging` gives the file handler `DEBUG`
> unconditionally, so a `logger.debug()` in `visit_definitions` would format + write millions of lines on
> *every* run, `--verbose` or not. Everything accumulates in module-level `_diag_*` counters and is formatted
> **once** by `_log_parse_summary()` at the end of `main()`.
> (2) **DEBUG is bounded to per-FILE scale, never per-cursor** (one line per TU / per skipped file).
> (3) **No new CLI flag** — user rejected one explicitly; `--verbose` already exists and the summary is
> always-on anyway.
> (4) **Nothing in `logs/` is read by code.** The summary is built from in-memory counters, never by re-reading
> the log; Phases 2-4 still read `model/*.json` only. An earlier design wrote `model/parse_report.json` and was
> rejected — `model/` is the DOCX data contract, not a diagnostics dump.
> **Levels:** `CRITICAL` = the 4 fatal `sys.exit(2)` paths (bad macro CSV, data-dictionary CSV
> missing/empty/unparseable) + a top-level `except BaseException` in `__main__` that logs the traceback and
> **re-raises** (never swallows); `ERROR` = a TU that fails to load (run continues, model is *partial*);
> `WARNING` = TUs that parsed *with* clang errors, functions declared but never defined, text-scan misses;
> `INFO` = resolved-input banner, stage accounting, drop tallies, the ex-`print()` output-file lines;
> `DEBUG` = per-TU ledger (`TU x.cpp: ok, N def(s), M clang error(s)`), full `CLANG_ARGS`, skipped files,
> drop samples.
> **Drop reasons** are recorded by a branch added at the **end** of the `visit_definitions` if/elif chain (so
> it cannot intercept a cursor the existing branches would take), scoped by new cached `_under_project_base()`
> so system-header cursors don't bury the signal: `not-project-file`, `dedup-hit`, `kind=<CursorKind>`.
> **`declaration-only` is resolved late, not counted inline** — counting every declaration cursor gave a
> useless `749` on SampleCppProject (nearly all *are* recorded via their `.cpp`, parsed later). Declarations
> are collected into `_diag_decl_only` keyed by `get_function_key`, then filtered against `functions` at
> summary time → **2 genuinely never-defined functions**. Keep this shape.
> **Text reconciliation** (`_scan_unrecorded_functions`, `_FUNC_DEF_RE`) piggybacks the read loop
> `_scan_defines` already runs over every project file, so it costs no extra I/O. It is the **only** way to see
> a definition in an inactive `#if` branch — libclang creates no cursor, so there is no rejection to log.
> **Known limitation:** line-based, so a signature split across lines (return type on its own line, as in
> `Layer1/Diag/PreprocIfFunction.cpp`) is not matched; output is capped at `_DIAG_SAMPLE_CAP` and labelled a
> heuristic hint list, never an input to anything.
> **Also:** `is_project_file` is now **memoized** (`_compute_is_project_file` + `_project_file_cache`) — it was
> doing `abspath`/`normcase`/`relpath` per cursor from 13 call sites. Safe because `MODULE_BASE_PATH`,
> `_FILE_COMPONENT_MAP`, `_EXCLUDE_NAME_PATTERNS` are each assigned once at import and never mutated **in the
> pipeline** — but tests re-point `MODULE_BASE_PATH`, so anything doing that must clear
> `_project_file_cache` + `_under_base_cache` (the test file has a local `_clear_path_caches()` helper;
> deliberately **not** a reset function in `parser.py`, which would be dead production code). Module-level `_log = get_logger("parser")` added at import: the macro-loading report at
> import time previously had **no handler installed**, so those INFO lines were silently dropped. Emitted
> strings are ASCII-only (standalone `python engine/parser.py` lacks run.py's UTF-8 forcing → em-dashes
> mangled).
> **Findings surfaced, deliberately NOT fixed** (each would change output): (a) SampleCppProject has **5 TUs
> with `unknown type name 'VOID'`** (`Layer1/Signal/*`, `Layer1/Diag/{ForwardVoidDecl,VoidIsVoid}.cpp`) — real
> preprocessor/macro gap; (b) the `declarationOnly` branch in `visit_definitions` is **dead code** — the outer
> gate already requires `cursor.is_definition()`, so `elif fk not in functions` can never run, and
> declaration-only functions never enter `functions.json` at all; (c) **two log directories** — `run.py` passes
> `project_root=SCRIPT_DIR` (= `engine/`) to `configure_logging` while phase subprocesses auto-configure to
> `cwd` (= repo root), so orchestrator and phase logs can land in different files (`engine/logs/*.log` are
> 0 bytes; `logs/*.log` has the real content) and `paths().logs_dir` says `<root>/logs`.
> (d) **the unit suite clobbers `model/clang_include_paths.json`** — `tests/unit/test_cli.py` invokes
> `engine/run.py`, which rewrites that file before Phase 1; against its throwaway project the result is `{}`.
> The real `model/` is left with **zero include dirs**, so the *next* parse silently resolves fewer headers and
> drops call edges (`calledByIds`) — 64 of 292 entries changed on SampleCppProject, same count with the
> unmodified parser, i.e. pre-existing and unrelated to this work. Found while A/B-verifying; cost an
> investigation. **Any future A/B of parser output must confirm `clang_include_paths.json` is populated first**
> (restore it, or re-run `run.py`) or the comparison is meaningless.
> **Verification:** `model/functions.json` **byte-for-byte identical** A/B on SampleCppProject (292 entries) —
> the gate split is behaviour-preserving; that comparison is the gate for any future change here. Unit suite
> 697 passed (678 + 19 new in `tests/unit/test_parse_diagnostics.py`). Phase 1 timing: OLD 30.5-34.3s vs NEW
> 27.0-39.5s over interleaved runs — libclang dominates and variance swamps the delta, so **no measurable
> change**, no regression.)

> Updated: 2026-08-12b (**LLM observability: every call is now timed and attributed to a pipeline stage.**
> Motivation: nothing in the project reported LLM latency, so "which phase/view is slow, and is it our logic,
> the server, or the throttle?" was unanswerable — the old report printed only `calls=N` + token counts, and
> even that undercounted because failures never reached `record()`.
> **`engine/llm_core/tokens.py` rewritten.** Records per HTTP *attempt*: latency, throttle seconds, outcome
> (`ok`/`empty`/`error`), tokens. Adds `stage()` — a **contextvar** context manager, so a label set by a caller
> follows the call down through helper layers without threading a parameter through every signature (no thread
> pools anywhere in `engine/`, so nothing is lost to a fresh thread context). Also `write_json()`,
> `merge_dir()`, `format_merged()`.
> **`client.py`:** new `_attempt()` context manager wraps all four `_call_*` paths and records in `finally`, so
> a timeout is counted with its full latency instead of vanishing; `_throttle()` measures the sleep;
> `record_config()` captures provider/model/baseUrl/rateLimit/numCtx at construction.
> **Stage labels:** `flowchart.labels` / `.coherence` / `.simplify`, `pkb.*` (5 scanner call sites),
> `enrich.*` via a new `stage=` param on `llm_enrichment._call_llm` (defaults to `kind`; `kind` is NOT reused
> for reporting because it drives behaviour — domain anchoring + blocklist scrubbing).
> **Cross-process:** each phase is its own subprocess with its own counter, so `ANALYZER_RUN_ID` (set by
> `run.py`) keys `logs/llm_stats/<run-id>/`, every process writes one file at exit
> (`logging_setup._emit_token_report`), and `run.py` merges them into `logs/llm_stats_<run-id>.json` + prints
> one table. Both new I/O paths are `try/except`-wrapped — reporting must never fail a run.
> **`tools/llm_stats.py`** compares two saved runs, **config diff first** (the point is attributing a delta to
> a specific config change — server, `rateLimitSeconds`, batch size), then per-stage deltas marked
> better/worse. `python tools/llm_stats.py A.json [B.json]`.
> **Bug found and fixed on the way:** `llm_enrichment._get_client` builds `LlmClient(...)` directly rather than
> via `from_config`, so it never received `rateLimitSeconds` — Phase 2/4 enrichment silently ignored the config
> key added earlier the same day. Now passed explicitly and added to `_client_cache_key`.
> **Overhead:** ~10 µs/call (2 `perf_counter` reads + a dict update inside the lock the counter already took)
> against multi-second calls; one JSON write per process at exit, never per call.
> **Cost to anything grepping logs:** the report header changed from `LLM token usage:` to `LLM calls by
> stage:`. Verified: 702 unit tests pass — one test needed fixing (`test_aux_desc_cache.py` fakes had closed
> signatures that rejected the new `stage` kwarg). **Not yet done: unit tests for the new tokens/compare code,
> and a real end-to-end run — every number seen so far is mocked or synthetic.**)

> Updated: 2026-08-12 (**the OpenAI gateway throttle is now a config key, `llm.rateLimitSeconds`** — it was
> the hardcoded `_OPENAI_RATE_LIMIT_SEC = 3.0` in [engine/llm_core/client.py](engine/llm_core/client.py).
> **Why it matters:** the pause is in a `finally` inside `_OPENAI_LOCK`, so it fires after *every* OpenAI
> call including failed ones, and the flowchart engine has **no parallelism at all** — every sleep is
> wall-clock. Measured from `logs/run_*.log`: ~**1.5 label batches + ~0.25 coherence calls per function**
> (212 batches / 139 functions on 2026-08-10), i.e. **~5.4 s of pure sleep per function** — ~12 min on a
> 139-function run, ~45 min at 500. **Changes:** (1) `core.config.load_llm_config` parses optional
> `rateLimitSeconds` (float ≥ 0, default 3.0, env `LLM_RATE_LIMIT_SECONDS`); explicit `null` raises with a
> "use 0 to disable" hint rather than being read as auto. (2) `LlmClient.__init__` takes
> `rate_limit_seconds`, stores `self._rate_limit`, and both OpenAI paths guard `if self._rate_limit > 0`.
> (3) `from_config` threads it through — which is what gives `flowchart_engine._build_llm_client` the
> setting for free. (4) Added to `engine/config/config.json` + the startup banner. Behaviour is unchanged
> when the key is absent. **Note for anyone measuring the win:** `tokens.record()` sits on the success path
> only, so timeouts/HTTP errors sleep but are never counted — the `calls=N` report understates the true
> throttle cost. Tests: `TestRateLimit` in `tests/unit/test_llm_client.py` (6) + 7 in
> `tests/unit/test_core_config.py`.)

> Updated: 2026-08-11 (**`run.py` rejects unknown options and stray positionals instead of ignoring them**
> — branch `fix/cli-strict-args`. Reported symptom: `python engine/run.py <proj> --phase 3` printed nothing
> unusual and re-ran the whole pipeline **from Phase 1**. Root cause: the hand-rolled argv loop's final
> `else` appended *anything* unmatched to `raw_args` (§5 "Argument parsing"), and only `raw_args[0]` was
> ever read as `<project_path>` — so a mistyped flag after the path was silently dropped, and a mistyped
> flag *before* it became the path (`Project path not found: …\--clen`). **Fix, all in
> [engine/run.py](engine/run.py):** (1) new `elif a.startswith("-")` branch → `Unknown option: <flag>` +
> a `difflib.get_close_matches(..., n=3, cutoff=0.7)` "did you mean" line + exit **1**. Cutoff is 0.7, not
> difflib's 0.6 default: 0.6 pairs `--phase` with `--help` and `--verbos` with `--macros`, which reads as
> noise beside the real match. (2) `len(raw_args) > 1` → `Unexpected extra argument(s): …`, exit 1 —
> catches the orphaned value of a mistyped flag (`--phase 3` leaves a stray `3`). Runs **before** the path
> check and before `--clean`, so nothing is deleted on a bad command line. (3) New **`--help` / `-h`**,
> answered at the very top of the file (before `configure_logging`, `chdir`, and the config load) by
> printing `__doc__` and exiting 0 — so help still works when the config is broken, and no log file is
> created. The module docstring IS the help text, so it was completed to list every flag: `--llm-summarize`,
> `--selected-layer`, `--selected-component`, `--component-per-docx`, `--filter-mode`, `--output-name`,
> `--only-files` were all missing. Also escaped the `\` line-continuation in the `--macros-layer` example —
> inside a non-raw docstring it was silently joining the two example lines. (4) New module-level
> **`_KNOWN_FLAGS`** tuple feeds both the rejection and the suggestions; `tests/unit/test_cli.py` walks
> run.py's AST and asserts it equals the set of flag literals the parse loop compares `a` against, so a new
> branch without an entry fails the suite. **Bug found + fixed on the way:** **`--filter-mode` had no parse
> branch at all** — it was documented here (§5), in the docstring, and passed to
> `plan_runs(filter_mode=filter_mode_arg)`, but `filter_mode_arg` was never assigned, so the flag was dead
> and `--filter-mode X` made `--filter-mode` the project path. Branch added; flag **kept** per user
> decision. **Was inert downstream until 2026-08-22** — `group_planner` forwarded it to Phase 3 and
> `run_views.py:89` wrote `config["views"]["sequenceDiagrams"]["filterMode"]`, but no view read that key.
> The replacement `behaviour_diagram` package now consumes it (see §"behaviour diagram package replaced").
> The value is still accepted **unvalidated** — unknown modes fall back to `skip_within_unit` silently. **Callers unaffected:** `api/services/pipeline_runner.py`,
> `engine/incremental/{engine,generate}.py`, and `tests/conftest.py` were audited — all pass only real flags
> and exactly one positional. **Second destructive bug found + fixed:** the `--clean` block ran **before**
> `<project_path>` was validated, so `run.py --clean <typo'd path>` deleted `model/` and `output/` and *then*
> exited 1 — a mistyped path cost a full re-parse. `--clean` now runs after the path check (and after the new
> unknown-option/extra-positional checks), so no bad command line deletes anything. Guarded by
> `test_clean_runs_only_after_project_path_is_validated`, which asserts the ordering **via AST** — a
> functional test would have to destroy the real `model/`/`output/` to detect the regression.
> Tests: 664 unit pass; `tests/unit/test_cli.py` gained `TestStrictArgValidation`,
> `TestHelp`, `TestFilterMode`. Phase scripts (`parser.py`, `run_views.py`, `docx_exporter.py`) still swallow
> unknown args the same way — **open follow-up**, they are only spawned by `group_planner` today.)

> Updated: 2026-08-10 (**flowchart labels: every call is named, always as `Name()`.** Reported symptom: a
> node that calls a function sometimes rendered as the call (`Call ServerReplicate(...)`), sometimes as pure
> prose (`Replicate server state`) — a per-node coin flip. **Root cause: two contradictory rules in the same
> system prompt.** `prompts.py` rule 2 said the label MUST name a callee ("Call ServerReplicate(...)"), while
> the ABSTRACTION GUIDELINE listed that exact shape as its **Bad** example and dropped the name in the
> **Good** rewrite. Three amplifiers: (a) the rule keyed off `called_functions`, which
> `NodeEnricher._resolve_calls` only emits for callees in `calls_ids` that also resolve in the PKB, capped at
> 3 — external/unresolved/4th-plus calls were never covered; (b) `_fallback_label` returns raw C++ for ACTION
> nodes, and `_looks_like_fallback` prefix-sniffed `Check: `/`Loop: ` only, so ACTION fallbacks went
> uncounted; (c) the coherence pass fixes labels "too literal *or* too abstract" (either direction) and only
> runs at ≥5 labels, so small functions were never normalised.
> **The rule now:** a label is descriptive prose naming **every** call, each written `Name()` — arguments
> always stripped, uniform rendering, shorter against the 26-char DOT wrap. Phrasing is **not** a fixed
> connector: `via X()` is wrong wherever the callee doesn't perform the action (in `functionX()->timeSlot =
> False` it only returns the object being written). The prompt carries a **shape → phrasing table** — call
> does the work → "with/using `Name()`"; call only supplies an object/value → "in `fnX()`" / "by calling
> `fnJ()`" — plus an explicit *don't stamp one connector on every node*.
> **New `engine/flowchart/cpp_tokens.py`** is the single definition of "a call": `CPP_KEYWORDS` (moved out of
> `prompts.py`), `extract_call_names()` (source order, deduped, receiver kept: `doc.AddMember`, `Ops::fn`),
> `render_call()`, `short_name()`. Excluded: keywords, casts, ALL-CAPS macros (logging/assert/`MAX`), lowercase
> `assert`. **Constructors can't be told from calls textually** (`Point(1,2)` vs `process(1,2)`), so the
> enricher passes known struct/enum/typedef names as `exclude=`. `NodeEnricher` now emits `ctx["call_names"]`
> (complete) beside `function_calls` (PKB-described, capped) — the naming rule keys off the former.
> **`generator.enforce_call_names(cfg)`** runs LAST in `label_cfg`, *after* the coherence pass so a rewrite
> can't strip names back out: it normalises existing mentions to `Name()` and appends only missing ones as a
> trailing `<br/>Calls: X()` segment (deliberately not a connector phrase — the pass can't know where the name
> belongs in the sentence). **Prose-safety rule:** a bare word matching a call name is only converted when it
> **cannot** be read as English (`_is_identifier_shaped`: qualified/member, snake_case, or an internal
> capital). Otherwise "Validate the request" would become "Validate() the request"; ambiguous bare words count
> as *absent* and get appended instead. Also: `_looks_like_fallback` replaced by a `self._fallback_ids` set
> populated where fallbacks are applied; coherence prompt gained *never remove a function name*; DECISION
> rule 3 no longer tells the model to drop the name via camelCase decomposition.
> **No cache bump needed** — flowchart-level reuse is unimplemented (M2.4; `_CARRY_FIELDS` excludes
> flowcharts, `generate.py` reports `carried: 0`), so flowcharts fully regenerate every run and `.dot_cache` is
> content-addressed. `engine/few_shot_examples/labels/` updated (`02_action_sequence` had the old
> name-dropping output; new `04_call_shapes`) — note **nothing reads that pool today**: `FewShotPool.select` is
> called once, for `"descriptions"`. Tests: `tests/unit/test_call_name_labels.py`; 653 unit tests pass.
> **Fixture:** `SampleCppProject` had **no `fn()->field` code at all**, so the hardest shape was unproven on
> real input. Added `FlowSlot_t` + `flowSlotHandle()` and four functions to `Layer1/Flow/Flowcharts.{h,cpp}`
> — `fnCallResultFieldWrite/Read/Address/Mixed` — covering write/read/address-of/branching, all called from
> `runFlowTests()` so they have callers. `Layer1/Flow` is in the **Full** group; the e2e snapshots are group
> **"My Sample"** (Core/Lib/Util), so `tests/snapshots/` is unaffected. Verified with a real LLM run
> (qwen2.5-coder:14b): `flowSlotHandle()->timeSlot = slot` → *"Set time slot in flowSlotHandle() to value"*,
> `&flowSlotHandle()->retryCount` → *"Return address of retry count in flowSlotHandle()"* — **zero repairs
> fired**, and the struct member comments surfaced as "time slot"/"retry count" via `struct_member_context`.)

> Updated: 2026-08-07 (**macro ingestion: JSON input + per-layer scoping + the API/UI path that was
> silently dropping defines.** Branch `feat/macros-json-per-layer` off `poc-4`. Closes backlog **S3-1**.
> **(1) One reader — `engine/core/macro_input.py`.** `--macros` took a 2-column CSV only; the client hands
> over an armclang/`fromelf` dump: `{"metadata": {toolchain, macro_source, total_macros, fully_resolved},
> "macros_by_cu": {"<cu>": {"<NAME>": {name, raw_value, expanded_value, computed_value|null,
> is_fully_resolved, dependency_chain[], note|null}}}}` (schema confirmed with the user; one CU key in all
> observed files). The module detects shape by **content, not extension** and reads: legacy CSV ·
> toolchain dump · `{"NAME":"VALUE"}` map · `["NAME=VALUE"]` list (what the web wizard stores) ·
> `{"Layer1": {…}}` scoped · a bare name→entry table. **Value precedence per macro:** resolved
> `computed_value` (a plain number — cannot half-resolve) → `expanded_value` → `raw_value` → bare `-DNAME`.
> **Unresolved macros are passed through as text, deliberately** (their `dependency_chain` names are often
> defined by the project's own headers, which libclang *does* see; dropping the define would silently flip
> an `#ifdef` branch) — counted + named in the load report. `ne` skip and empty→bare carry over from CSV;
> **function-like names (`MAX(a,b)`) are skipped + logged**. A dump's `metadata.total_macros` is
> cross-checked against what was read (mismatch ⇒ warning: we misread the file).
> **(2) Scope is an opaque key, not "layer".** Defs are `{scope: {NAME: value}}` with `"*"` = all layers.
> Today one list per layer; the user flagged that a layer may later need **several** macro sets (build
> variants), so only scope *resolution* has to change when that lands. **Same-name collisions across lists
> are reported, never silently reconciled** (`find_conflicts`) — the precedence strategy across lists is an
> open question the user deferred.
> **(3) Per-TU clang args (the actual S3-1 fix).** `CLANG_ARGS` was one module-level global for every TU, so
> layer scoping only ever restricted *which files* got parsed. New `parser.clang_args_for(path)` resolves
> file → component (`_FILE_COMPONENT_MAP`) → layer (`get_component_layer_name`) and appends global then
> layer defines — Clang honours the **last** `-D`, so the layer overrides the global by position. Used at
> both `index.parse` sites. `model/clang_macros.json` is now **scope-keyed** (`{"*": [...], "Layer1": [...]}`);
> a flat list (pre-change shape) still loads as global via `normalize_scoped_args`. It is also written
> **when empty** — a previous run's file used to survive a later macro-less run and keep feeding Phase 3.
> `views/flowcharts.py` picks `"*"` + its group's layer via the new `_resolve_layer_name` (extracted from
> `_resolve_layer_dirs`).
> **(4) CLI:** `--macros <path>` unchanged (global); new repeatable **`--macros-layer <layer> <path>`**,
> mirroring `--include-path`'s two-arg validation (unknown layer → exit 1, missing file → exit 2; that flag
> is now `--include-path-layer` — see the 2026-08-18 entry). A second
> flag rather than overloading `--macros` arity, which would have to guess layer-vs-path.
> **(5) Config-driven sources — `clang.macrosFile` / `clang.macrosByLayer` / `clang.macroScopes`**
> (CU→layer map for a multi-CU dump). Read by `parser.py` **before** the CLI flags, so a flag wins. This is
> why the API needs no new flag plumbing: the real job path runs `engine/incremental/{generate,engine}.py`,
> not `run.py` (only re-export uses `_build_cmd`), and every entry point already passes `--config`.
> **(6) API/UI, previously broken end-to-end:** `build_config.preprocessor_definitions` never reached Clang
> at all — `_write_project_config` forwards only `("clang","llm","views","docx")`. It now materializes them
> (`_materialize_macros`: manual list → `workspaces/<pid>/macros.json`; upload → the stored file) and sets
> `clang.macrosFile`. Uploads are **written to `workspaces/uploads/<id>/`** instead of a process-local dict
> that lost them on restart (`resolve_upload` falls back to the directory), and `/repositories/uploads` now
> validates extensions per kind (`.csv`/`.json` for defs). Wizard accepts `.csv,.json`; its "Drop Makefile
> or CSV" copy promised a Makefile parser that **does not exist anywhere in the repo** — now "CSV or JSON".
> **Verified** on `SampleCppProject` Phase 1: `Layer1/Diag/PreprocIfFunction.cpp` is gated on `SOME_THING`,
> and `--macros-layer Layer2 <dump>` leaves it on the `#else` branch while `--macros-layer Layer1 <dump>`
> takes the `#if` branch. Note that in the `#if` branch its symbol collides with `MultilineOvlyinit.cpp`'s
> `_SOME_FUNCTION(GG *)` and is dropped by the **pre-existing** cross-TU dedupe on mangled name
> (`get_function_key`, `parser.py:554`) — a fixture artifact (two files defining one symbol would not link),
> not a regression.
> **Sample lists (client schema, committed):** `engine/config/macros.layer1.example.json` (cu `fcore`) and
> `macros.layer2.example.json` (cu `hil`) — two files, the real per-target setup, covering every macro type:
> int/hex/shift/suffixed/big/negative/**zero**, value-less, unresolved (single + multi dep), string literal
> with spaces, empty string, float, identifier value, function-like (skipped), `ne` (skipped). They share
> `BUFFER_SIZE` at different values, which is the deferred cross-list collision case.
> **Gotcha found while verifying:** `views.flowcharts` is **false** in the shipped config, so a plain full run
> never exercises the Phase-3 macro consumer — enable it (`--config` with `views.flowcharts: true`) or the
> check passes vacuously. With it on, the response file `model/.flowcharts_clang_args.txt` carries all 12
> flags verbatim (argparse `fromfile_prefix_chars` reads one arg per line, so spaces and quotes survive), and
> a `Layer2`-scoped set correctly reaches **zero** args for a `Layer1` group.
> Tests: `tests/unit/test_macro_input.py` (27), `tests/unit/test_flowcharts_macro_scope.py` (12, Phase-3
> scope selection), `tests/api/test_materialize_macros.py` (11, the wizard→file path). Full suite green;
> plus a 40-check manual matrix (every shape, per-layer A/B, collisions, error exit codes, back-compat,
> config-driven, full pipeline → DOCX + flowcharts). **No model-schema change** beyond `clang_macros.json`'s
> shape → no snapshot regeneration.)

> Updated: 2026-08-03c (**data ranges now measured by libclang instead of guessed from type names.**
> `parser._range_from_clang_type` (canonical kind + `get_size()`) supplies typedef and struct-field
> ranges; `_register_builtin_range` records every parameter/return/global/field builtin under its
> CANONICAL spelling, so the dictionary answers exactly for the builtins a project actually uses.
> `PRIMITIVES` seeding switched from assignment to `setdefault` — it was overwriting measured values
> with a portable guess (`long` hardcoded 32-bit). `get_range_for_type` is now the last-resort fallback
> only, is CASE-SENSITIVE (lowercasing made `Size_t` match `size_t` and gave a two-int struct a 64-bit
> range), matches `size_t` by exact name rather than substring, and returns `0-1` for `bool` to match
> `PRIMITIVES` (the test pinning `NA` was wrong and was updated). Ranges are deliberately NOT stored per
> parameter in `functions.json`: parameters are collected before the CSV merge, so baking them would
> break `--data-dictionary` override — see [§9 Where a data range comes from](#where-a-data-range-comes-from-precedence-2026-08-03).
> Full suite incl. pipeline: 698 passed / 3 skipped, snapshot unchanged. SH-4 closed; only the array
> case (`int[6]` → `NA`) remains open.)

> Updated: 2026-08-03b (**root cause of the `NA` Data Range column: typedefs never recorded what they
> alias.** `parser.visit_type_definitions` read `cursor.type.spelling` on a `TYPEDEF_DECL`, which is the
> typedef type *itself* — so `typedef int UNIT;` stored `underlyingType: "UNIT"` and every typedef came
> out self-referential with `range: "NA"`. New `parser._typedef_underlying` uses
> `underlying_typedef_type` + strips elaborated keywords; anonymous enum/struct forms stay
> self-referential deliberately (the unit header table resolves the enumerator list through that name).
> `_maybe_add_typedef_for_struct` now stores `"NA"` instead of a range derived from the type's own name.
> Full-project parse: `UNIT` → `int` → `-0x80000000-0x7FFFFFFF`, `UINT8` → `unsigned char` → `0-0xFF`
> (via the dictionary, which only works because of the `get_range` fix below), `Size_t` poison gone.
> **Sample snapshot unchanged** (`My Sample` group has no typedef'd signatures) — full suite incl.
> pipeline: 669 passed / 3 skipped, generated `interface_tables.json` == committed snapshot. Tests:
> `test_typedef_underlying.py`. Detail in [§10 Type collection](#type-collection-visit_type_definitions).)

> Updated: 2026-08-03 (**data-dictionary range lookup: `"NA"` now means "unknown", not an answer**
> — branch `fix/data-dictionary-range-lookup`. Phase 1 bakes a typedef's `range` with
> `get_range_for_type()`, which never sees the dictionary, so an alias of a project type is stored
> `"NA"` and a range supplied later by the external CSV never reached the interface tables.
> `utils.get_range` now treats a `"NA"` direct hit as "keep looking" and resolves the alias chain, with
> a `underlying != base` self-reference guard; it deliberately does **not** fall through to the
> qualifiedName scan, because sibling `typedef@Name:file:line` entries can carry a garbage baked range
> (Sample `Size_t` → `0-0xFFFFFFFFFFFFFFFF`, from a `"size_t" in base` substring match now logged as
> backlog **SH-4**). Verified **0 diffs** across all 21 Sample signature types → no snapshot regen, no
> SampleCppProject change. New tests: `test_utils.py::TestGetRangeBakedNA`, `test_data_dictionary_csv.py`
> (also pinned `MODULE_BASE_PATH` in `test_define_conditional.py`'s fixture — `parser` is a module-level
> singleton and the first importer was binding it). Full suite 658 passed / 3 skipped. Details in
> [§9 `get_range` resolution order](#get_range-resolution-order-2026-08-03).)
> Updated: 2026-08-14 (`db-with-increment-changes`: **doc 09 Phase 0/1 + B5a + C1 + B1(output) landed.**
> Gates green throughout: `pytest tests/unit tests/api --skip-pipeline` **652 passed**, `verify_incremental` green.
> **B0** — `job_max_concurrency` **default 2 → 1** ([settings.py:47](api/services/settings.py#L47)); the old default
> corrupted output on any box that hadn't read doc 09. ⚠ the semaphore is per API **process**, so N replicas give
> N × the limit — a global cap needs a DB lease (unfiled, **B0c**).
> **A0** — new `engine/core/subprocess_util.py`: stderr **streamed through** (the API tails it for SSE progress, so
> buffering would freeze the UI) with a bounded 50-line tail logged on failure; cp1252-safe echo. Wired into
> `PhaseRunner`, the flowchart-engine spawn (the site that hid a `LibclangError` for a session), and both renderers in
> `utils.py` — which were capturing stderr and **discarding** it. API side: the non-zero-exit path already did this; the
> real gaps were the **timeout path** (dropped the tail) and `_mark_failed` (DB only, no module logger).
> **D2a** — new `engine/core/run_metrics.py`: one JSON line per phase to `logs/metrics_<date>.jsonl` with elapsed +
> **peak RSS of the process tree**. LLM call counts already existed in `llm_core/tokens.py` and now land there too.
> Suppressed under pytest — the at-exit hook was writing fake providers (`test-model`, `gpt-4`) into the real file
> (32 records/run); `PYTEST_CURRENT_TEST` alone is not enough, pytest clears it before at-exit, so it also checks
> `sys.modules`.
> **B5a** — `PgReuseIndex.get_many`/`put_many` (chunked `ANY(…)`), threaded through `ArtifactStore`/`FileStore`/
> `PgStore`/`StoreReuseIndex` + both hot loops. `get` opened a connection **per entity** and the seeding loop ran it for
> every fingerprinted entity — ~20k acquisitions on a 20k-function project. Free against a pool, ruinous under B5b's
> `NullPool` (~200s/run added). **Measured 50 → 1**, results identical; 5 tests, verified to fail against the old path.
> **B5a is now a prerequisite for B5b.**
> **C1** — `persist_run_outcome`/`load_run_outcome` put decision/baseline/regenerated/reused on the `versions` row
> (mirrors `write_run_metadata`); `PgStore.write_manifest` writes both, API reads **DB-first with file fallback**.
> `PhaseRunner` writes `versions.pipeline_status` per phase (keyed by `phase.script`, not the display name) via a raw-SQL
> `core.db.set_pipeline_status` — raw SQL because `engine/core/` is the bottom layer and the schema sits two layers up.
> Best-effort: no version id (CLI) or no DB (the DB-less gate) are silent no-ops.
> **B1 (output half)** — runs render **straight into `versions/<ver…>/output`** via new `run.py --output-root`;
> `<repo>/output` is gone and the capture copy step with it. Deliberately **not** `ANALYZER_DATA_ROOT`, which also moves
> `logs_dir`+`cache_dir` — that would give every run a private `.flowchart_cache` (0% hit rate, silently undoing M-A/M-B).
> A **flag, not an env var**, per user preference: no phase subprocess needs the value (`group_planner` already hands each
> phase an absolute `--output-dir`; `docx_exporter.OUTPUT_DIR` is only a fallback), and a config key would put a
> machine-specific path into `versions.resolved_config` — the mistake C3 exists to undo. `capture_output` gained a
> `_same_dir` guard against copying a directory onto itself.
> **Repo hygiene** — the two tracked `api/models/__pycache__/*.pyc` are untracked (`.gitignore` had `__pycache__/`, but
> ignore rules don't apply to tracked files; they came from the `git add -f api/models/` in §18). They had already broken
> a `git stash pop` mid-session.
> **Docs** — doc 09 marks B0/A0/D2a/B5a/C1/B1(output) done, splits B5→B5a/B5b and D2→D2a/D2b, promotes D2 above B4, adds
> **M1/M2** (unbounded flowchart TU cache — full-body ASTs, never cleared, grows with file count not change size; the
> first thing to exhaust a container) and **C12** (consolidate the disk caches; design in
> [04 §13](docs/production-redesign/04-incremental-changes-implementation.md#13-caches-in-the-database-post-migration-doc-09-c12)).
> **Key C12 finding:** the disk `EntityCache` and the DB reuse index answer the same question with near-identical keys —
> C12 removes a duplicate mechanism, not just a directory.
> **Corrected when C12 landed (doc 10 step 10):** that holds only on the *incremental* path.
> `carry_forward_from_index` is called from `incremental/engine.py` and nowhere else — `generate_full` never calls it,
> and `llm_enrichment` uses `EntityCache` directly without consulting the reuse index. On a **full** generation the
> cache is the only thing preventing a complete re-describe (~17 h on a 20k-function project at one gateway call per
> 3 s). So the LLM cache was **relocated to Postgres**, not deleted; only `pkb_*.json` was dropped.
> **C11a (dual-write) — landed, NOT yet validated against a real Postgres.** New
> `PhaseRunner.run(..., on_phase_done=)` hook: `engine/core/` is the bottom layer and cannot import the
> store, so it defines the hook and `run.py` supplies the callback (new `--version-id` / `--project-id`
> flags, again flags not env vars). The model is persisted **at each phase boundary** instead of once at
> the end; `PgStore.write_model` already wraps `persist_model_from_dir` in `engine.begin()` and that
> function already `clear_version`s first — so it is one transaction and idempotent, and **C6 (phase
> atomicity) falls out for free**. Persisted only after `parser.py`/`model_deriver.py` (phases 3-4 only
> read), and **never after a narrowed partial parse** — that model is incomplete until `parse_merge`.
> Files remain authoritative; nothing reads from the DB yet (that is C11b).
> Oracle built FIRST: new **`tools/verify_model_parity.py`** compares a version's DB model against the
> on-disk model, tolerating DB-only fields (`isVisible`) and edge-list ORDER, and hunting fields the
> payload allow-lists (`_FN_PAYLOAD_FIELDS`) silently drop — the failure mode that would otherwise only
> surface as a wrong document. 7 tests prove it detects each difference class and stays quiet on order.
> +5 tests on the hook (fires per success, NOT after a failed phase, a raising hook cannot fail the run).
> **⚠ Remaining for C11a: run `verify_model_parity.py` after each phase on the office box** — there is no
> Postgres on the dev machine, so the dual-write path itself is unexercised (the DB-less gate proves only
> that it correctly no-ops). **Do not start C11b until that is clean.**
> **Next:** validate C11a on the office box, then C11b (reads from Postgres).)

> Updated: 2026-08-13 (`db-with-increment-changes`: **PG-7b cutover COMPLETE — Postgres is the source of
> truth.** Validated on the office box first (two different commits: non-zero changed files, `regenerated ≥ 1`,
> compare shows the change; `tools/verify_pg_readers.py` — new — reports per version whether view outputs,
> model, run metadata and resolved_config are genuinely IN Postgres, since every reader falls back to disk and
> a working run otherwise proves nothing). Then the deletions, each gated by the suite + `verify_incremental`:
> **(1)** `_sync_model_to_db` dropped — the engine already persists via `PgStore.write_model`, and both were
> gated on the same condition. **(2)** the **commit-dir model/output dual-write** (`vstore.capture_artifacts`)
> dropped — the commit dir is now just the git checkout + manifest/report; artifacts live in
> `versions/<ver…>/` + Postgres. Readers repointed first: engine baseline/cross-version reuse via a new
> `_artifact_dir_for` (this ordering mattered — deleting first would have silently broken flowchart reuse),
> `_make_sections`, the re-export flow (which had conflated *checkout* and *artifacts* in one `cdir`), and
> ModelReader's disk fallback. **(3)** the reuse index moved into the store (`StoreReuseIndex`) — it was still
> entirely `cache/index.json`, so the `reuse_index` table built in PG-4 had never been exercised. **(4)** run
> metadata moved onto the `versions` row: the engine writes it via a new `store.write_run_metadata`
> (`model_store.persist_run_metadata` → base_path/project_name/parse_fingerprint), the API stopped reading
> `metadata.json`, and the narrowed-parse gate now takes the baseline fingerprint from
> `store.read_run_metadata`. **(5)** `JsonDatabase` deleted (D-7) after moving `tools/import-output-project`
> onto `SqlDatabase`; backend = Postgres whenever configured, else `InMemoryDatabase` as a **test seam only**
> (startup now says loudly that an unconfigured server persists nothing, rather than looking healthy).
> **Kept as files by design:** PNG/DOCX binaries (D-14), the git checkouts, and `model/metadata.json` — now
> only an *in-run* intermediate between the parser and the store, with no cross-run consumer. **Kept as
> test-only seams:** `InMemoryDatabase`, `FileStore`, and `project_db`'s read-only JSON lookup (what
> `verify_incremental` feeds from a temp dir — the API never uses it). **Bugs found and fixed during this
> work:** the version FK-ordering 500 on job start; a **self-baseline** regression (the reserved row became its
> own baseline → 0 changed files → nothing regenerated, which is why a real code change never showed in
> Compare); run metadata silently NULLing when the commit-dir model went away; and a pre-existing crash where a
> string `behaviorDescription` reached the UI as `descriptionList` and killed the document view. **Known gap:**
> narrowed parse has **no automated coverage** and its gate was re-sourced here — off by default and not
> UI-reachable, but required for large codebases, so validate before enabling.)

> Updated: 2026-08-10 (`db-with-increment-changes`: **storage cutover, reader half — PG-5a/5b/7a.** The API no
> longer depends on disk snapshots for the model or the Phase-3 views; disk remains as a fallback until the
> dual-writes are removed (PG-7b). Three increments, each additive + gated:
> **PG-5a** — new **`version_output_files`** table (composite PK `version_id`+`rel_path`, text `content`,
> `group_name`); `model_store.persist_output_files` walks the run's `output/` and stores every TEXT file
> (interface tables, flowchart + unit-diagram `.mmd`, behaviour rows), skipping binaries (PNG/DOCX stay files,
> D-14); `PgStore.capture_output` overrides the base disk capture to also persist, best-effort.
> **PG-5b** — new **`api/services/output_reader.py::OutputReader(db, version_id, snap_dir)`**: reads view text
> files **Postgres-first** (queries `version_output_files` through `db._engine`, self-contained — no engine
> import) with disk fallback. `compare_engine._groups/_itf` now take a reader; `compute_compare` +
> `compute_document_sections_diff` build one per version; the gate flipped from "snapshot dir exists" to "the
> reader yields groups", so a version whose views live only in PG compares correctly.
> **PG-7a** — new **`api/services/model_reader.py::ModelReader(db, version_id, model_dir)`**: serves
> functions/units/globals/dataDictionary from Postgres via the engine's `incremental.model_store` loaders
> (delegation, not a second manifest-of-pointers implementation; API→`incremental.*` imports already exist in
> `services/git_cli.py` + `pipeline_runner.py`), disk fallback. Wired through a new optional
> `build_render(..., model_reader=)` kwarg (omitted → disk exactly as before) from the documents render route
> and `compare_render._version_render`. **Fixed a staleness bug**: repo-backed projects passed
> `model_root=None`, so `build_render` read the **shared repo `model/` dir** (whatever the LAST run left) — an
> older version's document could render against a newer version's model; reads are now keyed by `version_id`.
> **Field parity**: the DB carries `entity_versions.is_visible` (default True) as `isVisible` while the
> renderers filter on `hidden` — ModelReader translates `isVisible=False → hidden=True` (behaviour-identical
> today, since the on-disk model carries neither field); `metadata` has no DB equivalent and stays disk-only.
> Tests: `tests/api/test_output_reader.py`, `tests/api/test_model_reader.py`, `tests/unit/test_output_files_store.py`.
> Suite green (183) + `verify_incremental` gate green. **Remaining → PG-7b (destructive, after office
> validation):** drop `_sync_model_to_db`, the model/output dual-writes, the commit-dir layout, `api/db/data`,
> `JsonDatabase`; migrate the `functions` route + `compare_render`'s remaining disk asset paths.
> **Ops note:** the new table is additive — re-run `tools/db_setup.py` (idempotent `create_all`) to create it.)

> Updated: 2026-08-09 (`db-with-increment-changes`: **config redesign — three sources, three roles** (see §6).
> Problem: `config.json` + `config.local.json` overlapped (both could hold any key), and per-version analysis
> config had no home. Fix, two commits: **(1)** renamed the base `engine/config/config.json` →
> **`config.defaults.json`** (pure rename, every BASE reference updated — loader, `core/paths.py`,
> `flowchart_engine` libclang/llm probes, `pipeline_runner` base_path, `run.py --config`, `doctor.py`, two e2e
> tests, `test_utils` fixtures; the per-project **workspace** `config.json` under `workspaces/<pid>/` is a
> different file, left untouched). Now the name pairs self-document: `config.defaults.json` (tracked defaults)
> vs `config.local.json` (gitignored **secrets** — `db` + `llm` creds, the one file an operator edits).
> **(2)** wired the long-dormant **`versions.resolved_config`** JSONB column: `Version.resolved_config`
> (`Optional[dict]`, auto-mapped by the field-generic `to_row`/`from_row`; json_db round-trips it too).
> `pipeline_runner._write_project_config` now returns `(workspace_path, analysis_cfg)` and splits two configs
> **by design** — `analysis_cfg` = `config.defaults.json` + project `build_config` + `layers` (+ `no_llm`),
> **non-secret**, deep-copied *before* any secret overlay → stored per version via `_store_resolved_config` on
> the row reserved at job start; the materialized workspace `config.json` the engine reads = `analysis_cfg`
> with `config.local.json`'s `llm` secrets overlaid but the **`db` section stripped** (engine reaches PG via
> `DATABASE_URL`, so the password is never written to a workspace file). `_make_version` carries
> `resolved_config` through finalize (the repo's `_put` replaces the whole row). The engine never writes the
> `versions` row (store.py owns only model artifacts under the FK), so the API is the sole writer — nothing
> clobbers it mid-run. `load_config` now **deep**-merges (nested keys, not shallow), so `config.local.json` can
> override just `llm.baseUrl` / one `customHeaders` entry. Tests: `tests/api/test_project_config.py` (secret
> split), `test_utils` nested-merge case; full api+unit suite green (166), `verify_incremental` gate green.
> Deferred: the `versions.config` per-version schema was already present as `resolved_config` — no migration.)

> Updated: 2026-07-23 (**docs restructure + agent role-skills.** Introduced `.claude/skills/` role skills:
> `docs-maintainer` (owns **all** docs repo-wide — audience/register/naming/outline conventions + the doc-gen
> method) and `ui-dev` (frontend rules, replacing the deleted `web-app/CONVENTIONS.md`). Doc suite tidied:
> this file marked **agent-facing** (top header); `docs/design/REDESIGN.md` deleted (v2-from-scratch,
> superseded by `docs/production-redesign/`); `DOCX_generation_walkthrough.md` merged into
> `docs/design/DESIGN.md`; `api/IMPLEMENTATION_PLAN.md` → `api/PLAN.md` (status refreshed: M0–M3 done, M4
> remaining); new `web-app/PLAN.md`; ArtiFex name locked in `web-app/PROJECT_CONTEXT.md`; root README +
> subsystem README doc-indexes filled. New convention: each subsystem may keep a `PLAN.md` (forward work only,
> ≠ ROADMAP/BACKLOG).)

> Updated: 2026-07-23 (**SWE.4 test-case generation methods scoped.** Client names **three** generation
> methods — **Analysis of Requirements** (the unit's specified behaviour), **Equivalence Class Analysis**
> (input/output partitioning), **Boundary Value Analysis** (input boundaries) — recorded in Table B's "Test
> Case Generation Method" field (REQ-UT-09). **The first complete SWE.4 implementation emits `Analysis of
> Requirements` only:** cases derived from the function signature + SWE.3 detailed design/description +
> return/OUT, as functional cases with expected results (no systematic CFG/input partitioning yet).
> **Equivalence Class + Boundary Value — and the branch-coverage-targeted input sizing (the old `function +
> branch coverage` generation-method string, and REQ-TC-01…05) — are DEFERRED** to a follow-on method-pass;
> the 24-function derivation spike (`tools/swe4-derivation-spike/`) validates that deferred pass, **not** the
> first implementation. Model shape unchanged: one Table B / one Test Case ID per public function, though
> Table A may carry multiple input sets; each set is attributed to a method and Table B lists the distinct
> set. **No `generationMethod` config key** — the method is a fixed code constant (`Analysis of Requirements`)
for this build, not a user toggle (supersedes the `docx.swe4.generationMethod` mention in the 2026-07-22
entry below). Contract:
> `docs/spec/SWE4_SPEC.md` REQ-TC-08 + the scope banner over the derivation section; leadership: plan
> Decisions 2026-07-23. NOTE this narrows the first build vs. the 2026-07-22 entry below, which assumed
> branch-coverage sizing as the core work.)

> Updated: 2026-07-22 (**SWE.4 unit-test-spec generation — discovery + design locked; implementation plan
> approved.** Requirements + test-case derivation logic + limits: **`docs/spec/SWE4_SPEC.md`** (REQ-UT /
> REQ-TC); leadership summary: `docs/planning/SWE4_PLAN.md`; plan file:
> `~/.claude/plans/now-plan-for-swe4-snug-pascal.md`.
> **Architecture — doc type is a *dimension*, not a phase.** Phases 1–3 (parse→derive→views) stay a shared,
> doc-type-agnostic substrate; only export diverges. New run param `--doc-type swe3|swe4|all` (default
> `swe3`, back-compat); an `EXPORTER_REGISTRY` (mirrors `views/registry.py::VIEW_REGISTRY`) dispatches one
> export sub-run per selected doc type in Phase 4 — so a SWE.4-only run emits **no** SWE.3 DOCX, and a
> future SWE.2 = register one more exporter, no new phase. (Rejected the earlier "append Phase 5" idea for
> this reason.) Phase 3 runs only the **union of views** each doc type needs (config-gated via
> `views/__init__.py`): SWE.4 = `interfaceTables` + `behaviourDiagrams` + a new `testSpecs` view; **not**
> `unitDiagrams`; the SWE.3-only container/header-dependency diagrams live inside `docx_exporter` so they
> never run for SWE.4.
> **Transform = new Phase-3 view `engine/views/test_specs.py`** (`@register("testSpecs")` →
> `output/<group>/test_specs.json`), rendered by a new `engine/swe4_exporter.py`. Per public function,
> derive cases from: interface ranges (`get_range`/`get_range_for_type`, `utils.py`) for
> boundary/equivalence; the **re-materialized CFG** (`CFGBuilder`, `engine/flowchart/ast_engine/cfg_builder.py`
> — only mermaid is persisted, the structured `ControlFlowGraph` is discarded, so we rebuild it) for branch
> coverage + Test Steps; return/OUT ranges for Expected; and a new LLM kind `test_case` (via `_call_llm`,
> cached through `EntityCache`/`cacheVersion`) for error/precondition cases + labels. Scope = full transform
> (deterministic floor + CFG + LLM).
> **Document = per group, mirrors the SWE.3 DOCX; two tables per function** (Table A horizontal content,
> Table B vertical metadata — fields in `SWE4_SPEC.md`): reuse `docx_exporter._add_interface_table`
> (Table A) + `_add_flowchart_table` (Table B); shared helpers extracted to `engine/docx_common.py` (both
> exporters import — avoids `docx_exporter.py`↔`api/services/doc_render.py` drift).
> **Table A (client-confirmed) + derivation (REQ-TC) + limits** are the single source in
> `docs/spec/SWE4_SPEC.md` — not repeated here. **Code-anchored facts (verified this session):** locals are
> **not** in the model (parser records only local `VAR_DECL` *types*, `parser.py:1142-1143`); a global
> carries a value only when its declaration initializes one (`_get_var_init_value`, `parser.py:914/924`).
> **Delivery this pass = engine only** (writes the `.docx`); the API `doc_render.py` mirror + `process="SWE.4"`
> tagging (`pipeline_runner.py::_make_documents/_make_sections`) + a web-app doc-type picker are a fast
> follow-up. Config: a new `docx.swe4` block (env-field defaults, testCasePolicy, generationMethod) under
> `docx` so the API config-forward whitelist `("clang","llm","views","docx")` passes it through unchanged.
> **Macros (confirmed 2026-07-22):** SWE.3 & SWE.4 **share the same macros, per layer** — SWE.4 reuses the
> same parse/model, so the per-layer-macros work (landed 2026-08-07, see the newest entry) serves both docs. **Still open (take to client):** Table B metadata fields (Alias Test ID · Risk · Test Method ·
> Test Environment · Linked Work Items — only Table A was covered); how private callees' branches get
> covered when callees are mocked. `docs/planning/SWE4_PLAN.md` updated + kept leadership-facing.)

> Updated: 2026-07-22 (**engineering backlog gets a home: `docs/BACKLOG.md`.** Single running list of
> known issues / deferred fixes / needs-input (Type + Status tags, grouped SWE.3 · SWE.4 · SWE.2 · Shared)
> — kept OUT of `docs/planning/` (leadership-facing) and out of this deep-context file. It's the Phase-2
> burn-down list under the plan "implement all doc types to ~70–80% first, then improve." Each row's `Ref`
> points back HERE (§16 / the `> Updated:` log) or the plan docs for the detail; the backlog itself stays
> terse. Seeded from the still-open items: per-layer macros, flowchart 3.8/3.9, dynamic-behaviour 3.10,
> SWE.4 Table B metadata + §3 metrics, SWE.2 feature-list + resource/config data, and the shared
> requirements/Polarion source. (The 3.11–3.19 SWE.3 correctness items are deliberately NOT in the backlog
> — tracked via git/PRs + §16.) `ROADMAP.md` "Remaining work" links to it.)

> Updated: 2026-07-21 (**planning docs made leadership-facing + consolidated.** `docs/planning/` is now
> shared with the director, so those files were slimmed to milestones / decisions / remaining work only —
> no file paths, commit hashes, root-cause detail, or day-estimates (that depth stays HERE). Changes:
> **ROADMAP.md** gutted from the ~165-line effort ledger (18 tasks + per-repo DB breakdown + day-estimates
> + the resolved 3.1–3.19 write-ups) down to a one-page Milestones / Key decisions / Remaining-work doc;
> new **DOC_GENERATION_PLAYBOOK.md** holds the shared method that SWE2_PLAN + SWE4_PLAN used to each repeat
> (one-model consistency, code-anchored derivation, floor/gaps/optional inputs, draft-then-confirm, the
> shared requirements/Polarion blocker); **SWE2_PLAN.md** / **SWE4_PLAN.md** trimmed to just their own
> "what it is" + TOC + section-readiness + their one open crux (feature list / test-case sizing), pointing
> at the playbook for the rest; **SYS2_PLAN.md** gained a playbook pointer. Nothing was lost — the resolved
> 3.1–3.19 detail and estimates live in §16 + this `> Updated:` log. The §16 "Pre-V1 correctness batch"
> heading no longer cites the removed roadmap task numbers.)

> Updated: 2026-07-19 (**second V1 correctness batch logged (3.11–3.19) from client/office review — all ADDITIONS, nothing reversed** per user. In `docs/planning/ROADMAP.md` task 3. Verified against code where noted: **3.11** BOOL32 return shows literal `TRUE` not `TRUE/FALSE` in **Output Name** — root cause `model_deriver._enrich_behaviour_names` (`:548-564`) uses the return **expression's** first identifier; fix = boolean return → `TRUE/FALSE` (+ Data Range, `get_range_for_type` has no bool case) [needs more checking]. **3.12** void param → Input Name should be `VOID` not a global (`:539-546` falls back to first written/read global) [pending manager]. **3.13** some `#define`s missing from header [needs repro; likely file-scope/macro-in-macro edges gap]. **3.14** LLM descriptions contain irrelevant domain words (audio/video) → **blocklist now** (audio, video; extensible), root-cause dig later [approach agreed]. **3.15** Source/Dest + unit diagrams keep **only callers** (`calledBy`), drop callees (`calls`); refines 3.5/3.6 [**IMPLEMENTED 2026-07-19, uncommitted** on `v1-fixes-more`: `interface_tables.py` `sourceDest` = callers only; `unit_diagrams.py` callee loop deleted. Verified A/B (8 Sample rows drop `; <callees>`; provenance holds; diagram has no orphan nodes). **Sample snapshot regen DEFERRED to end of 3.11–3.19 batch** (per user 2026-07-19: regenerate all Sample snapshots once, after all fixes). The snapshot is *already* stale on this branch independent of 3.15 (vs 3.5/REQ-IT-12 + the return-type commits), so e2e `test_snapshot` stays red until the batch-end regen — expected, not a 3.15 regression]. **3.16** Source/Dest missing via macro-wrapped **SVC** call (a unit in the *service* component of the **client's** project, not our sample) [needs client project]. **3.17** In/Out new precedence: (1) Get/Set in name (Get→Out, Set→In), (2) returns value→Out, (3) void return → Set→In / Get→Out / both→In — supersedes current global-only logic (`:1016-1066`, the 3.4 rule) [confirmed, full spec coming]. **3.18** Data Type column add variable name alongside type (`docx_exporter.py:1002` shows type only) [confirmed]. **3.19** unit-header type visibility: same-component types used in functions shown; cross-component type shown only if not used in any other unit [look later]. Framed as additions, not reversals of 3.4/3.5/3.6.)

> Updated: 2026-07-18 (**V1-fixes status reconciled + flowchart-in-DOCX verified resolved**. Traced the Phase-3→Phase-4 name-matching chain end to end: the flowchart engine writes PNGs as `{source_basename_stem}_{safe_filename(qualifiedName)}.png` (`views/flowcharts.py:1157`; JSON stem = source basename via `flowchart/output/writer.py:44`), and `docx_exporter._append_flowchart_entries`/`_resolve_flowchart_pngs` now try **4 candidate stems** (`{unit_prefix|unit_name_flowchart}_{func_qn|func_name}`, `docx_exporter.py:1611-1616`) — the 2nd matches the engine exactly. Slice-aware (`{stem}_part_K_of_N.png` from `_maybe_slice_tall_png`) with a diagnostic log emitted before the mermaid-text fallback (`docx_exporter.py:944-956`). All committed (predates the `backend/`→`engine/` rename; landed on `poc-4`). **`docs/planning/ROADMAP.md` synced:** task-3 top item "flowcharts missing from DOCX" ✅ resolved; 3.5 ✅ (REQ-IT-12, all non-self units), 3.7 ✅ (access specifier) marked done; 3.1–3.4/3.6 already done. **Remaining V1 fixes:** 3.8 (if/else depiction — needs repro), 3.9 (bending/overlapping edges — ELK tuning levers not yet applied), 3.10 (dynamic-behaviour — blocked/under-specified), and **per-layer macros** (`--macros` is still a single global CSV). Plus non-fix V1 work: deploy (task 2), function hide/unhide scope (task 4, TBD with user), release/client review (task 5).)

> Updated: 2026-07-17 (**multi-line `#define` value no longer truncated in the unit-header table**. `parser._scan_defines` collected continuation lines (`\`-terminated) into the `text`/declaration field but parsed **`value`** from the **first line only** (`after = stripped[len("#define"):]`), so a macro like `#define SHARED_MASK ((1<<0) | \ (1<<1) | \ (1<<2))` showed only `((1 << 0) | \` in the **Information** column. Fix (`engine/parser.py` ~L1400): build a `logical` one-line form by joining all `macro_lines` with the trailing `\` stripped, then parse name/value from that → `value = ((1 << 0) | (1 << 1) | (1 << 2))`. `text` (declaration column) still shows the raw multi-line macro. Verified via `SampleCppProject/Layer1/Sample/Core/SharedDefs.h` `SHARED_MASK` (used by `coreLevelBudget`): dataDictionary `value` full + DOCX Information cell full. Parser is a script (not importable — runs argv parse + libclang at import), so no isolated unit test; the fixture macro is the regression anchor.)

> Updated: 2026-07-17 (**orphan-header symbols surface in the using unit's header table**. Branch `fix/interface-tables-and-unit-diagrams`. An **orphan header** = a `.h/.hpp/.hxx` with no same-name source file; it is never its own unit (the DOCX exporter already emits only `.cpp`-backed unit sections), so its `#define`/`enum`/`typedef` previously showed **nowhere** (the reported office bug: a shared header's `#define` + `enum … : UINT8` missing). Fix is isolated to `engine/docx_exporter.py::_build_unit_header_table`: besides the existing own-path matches, it now also emits a `define`/`enum`/`typedef` row when the symbol is defined in an orphan header **and this unit uses it**. "Uses" is the **union** of (1) the already-existing usage index `model/edges.json` (`macroUsers` keyed `name@relFile`, `typeUsers` keyed by qualifiedName) intersected with the unit's own `functionIds`, and (2) a **textual fallback** — the symbol name found among identifiers in the unit's own source text after stripping comments + string/char literals (`_COMMENT_STRING_RE`). So each unit shows **only the subset it references**, never the full header, never in a non-using unit. The fallback exists because `edges.json` only records **function-body/signature** tokens, so a macro used at **file scope** (array size / global initializer / macro-in-macro) is absent from `macroUsers` — reproduced with `#define SHARED_BUFSZ (6)` used as `int g_utilBuf[SHARED_BUFSZ]` in Util (in dataDictionary, NOT in edges); the text scan recovers it. Comment/string stripping stops a symbol merely mentioned in a comment (e.g. `// … NOT SHARED_SCALE_FACTOR`) from falsely counting as usage. An orphan header is told apart from a **companion** header via a new `source_unit_paths` set (extension-less paths that have a `.cpp/.cc/.cxx`), computed from the **full** unit list before layer filtering; companion-header content is not pulled into other units. The exporter loads `edges.json` (`_load_model_json("edges")`, `{}` if absent) and threads `macro_users`/`type_users`/`source_unit_paths` into the builder. **Kinds unchanged** (`define`/`enum`/`typedef`); the `class`/`struct` skip at `docx_exporter.py:251` was **left as-is** per user. **Known coverage gap (accepted):** edges records usage inside function bodies/signatures only → a macro used only in a global initializer or inside another macro, or an enum referenced only by enumerator value (not its type), is not surfaced. **Fixture placement gotcha:** an orphan header must live in a **mapped component dir** or `parser.is_project_file` (`_FILE_COMPONENT_MAP`) excludes it from the parse entirely — a header under an unconfigured folder (e.g. `Sample/Shared/`) is silently dropped. Fixture: `SampleCppProject/Layer1/Sample/Core/SharedDefs.h` (`SHARED_MAX_ITEMS`/`SHARED_MIN_ITEMS`/`SHARED_SCALE_FACTOR` + `enum SharedLevel : UINT8`), used by `coreLevelBudget` (Core → MAX+MIN+enum) and `libScaleShared` (Lib → SCALE); Util uses none. **Verified A/B** (My Sample, Phase 4 build path): Core header rows 2 → 5 (adds `#define SHARED_MAX_ITEMS`, `#define SHARED_MIN_ITEMS`, `enum SharedLevel`), Lib gets only `SHARED_SCALE_FACTOR`, Util none; own `enum Mode` unaffected; empty-edges baseline reproduces the old (no-surfacing) behavior. Docs: `SWE3_SPEC.md` new `## Unit Header Table` REQ-UH-01/02. Test: `tests/unit/test_unit_header_orphan.py` (6 cases, filesystem-free, green). Pre-existing broken e2e `test_docx.py` (output/Sample vs output/My-Sample) and stale `test_unit_diagrams_view.py` `_unit_part_id` `-`-vs-`_` failures are **unrelated**. Not committed — working-tree only pending review.)

> Updated: 2026-07-16 (**fix 3.6 — unit-diagram edges oriented by the interface owner's In/Out**. Branch `fix/unit-diagram-direction` off `fix/direction-transitive-writes` (builds on 3.4-correct `direction`). **Diagram-only — no model change** (`model/*.json` untouched; only `output/<group>/unit_diagrams/*.mmd|png` and the embedded DOCX images change; `interface_tables.json` unchanged). `engine/views/unit_diagrams.py` built every cross-unit edge from the raw call relationship (`caller → callee`, labelled with the callee's `interfaceId`) and never consulted `f["direction"]`, so the diagram disagreed with the interface table — a getter (`Out`) *called by* a peer was drawn inbound, opposite the table. Fix: orient each edge by the interface **owner's** direction (owner = unit of the called function) — **`In` → arrow towards owner, `Out` → away**; caller's own direction irrelevant. New `_add_edge(owner, other, iface, dir)` keys `(owner→other)` for `Out`, `(other→owner)` for `In`, fed by two loops (this unit's `calledByIds` oriented by `f`; its `callsIds` oriented by the callee). Owner-relative (unlike the stranded `da5f07d`, which is "this-unit"-relative and makes the two diagrams contradict) ⇒ the **same interface renders as the identical arrow in both units' diagrams**. One interface = one arrow; same-direction interfaces between a pair stack labels on one arrow; a mutual pair = two arrows with the partner **box drawn once** (`external_all = (caller_ids|callee_ids) - internal_set`; both external-edge emit tests gate on it, node-declaration lists unchanged ⇒ no dropped edge, no duplicate node). **Net: only `Out` (getter) edges flip; `In` edges already pointed into the owner so they're unchanged.** Docs: `SWE3_SPEC.md` REQ-UD-05 ("Call edges"→"Interface edges", owner-oriented) + REQ-UD-06 (placement by arrow direction, mutual partner once). **Verified A/B** (My Sample, Phase 3): 48/48 edge-labels match owner direction in `interface_tables.json`; in-group shared edges identical across diagrams; no self/duplicate. Fix stashed → `CORE_01…11` (Out) `App→Core`/`Hub→Core` (✗) + `Core→Lib`/`Core→Util`; restored → `Core→App`/`Core→Hub` + `Lib→Core`/`Util→Core` (✓), `CORE_02` (In) `App→Core` both ways. Not committed — working-tree only pending review.)

> Updated: 2026-07-15 (**fix 3.4 — interface direction from transitive global writes**. Branch `fix/direction-transitive-writes` off `poc-4`. Direction was set once in the parser (`parser.py:1308`) from **direct** writes only (`write_raw`), *before* Phase 2's `_propagate_global_access` fills the transitive global sets — so a function that writes a global **only via a callee** (e.g. `indirectWrite(v){ writeGlobal(v); }`, or `directionAdd` → `add` → `g_utilsCounter`) wrongly showed `Out`. Fix (isolated to `engine/model_deriver.py`, ~L1015): in the finalize normalize (runs **after** `_propagate_global_access`, so `writesGlobalIdsTransitive` is populated) re-derive `direction = "In" if (writesGlobalIdsTransitive or writesGlobalIds) else "Out"`. The parser's direct-only value is now **preliminary**; the deriver refines it — `parser.py` unchanged. Two-phase converge-then-derive is order-safe (X = In iff any callee's write-set is non-empty ⇒ folded into X's transitive set). Only transitive-only writers flip `Out→In`; reads-only and no-access stay `Out`; direct writers stay `In`. **Header-defined globals need no special case** — direction is global-**ID** based, so a global DEFINED in a header (`g_hdrGlobal` in `ReadWrite.h`, non-`extern`) is tracked like any other: `setHdrGlobal` (direct) = In, `setHdrGlobalIndirect` (transitive) = In. Fixtures: `SampleCppProject/Layer1/Direction/ReadWrite.{h,cpp}` gained `g_hdrGlobal` + `setHdrGlobal`/`setHdrGlobalIndirect`; the stale direction comments (had read→In / write→Out **backwards**) were corrected to read→Out / write→In. **Verified A/B** (Full group, Phase 2): fix stashed → `indirectWrite`/`directionAdd`/`setHdrGlobalIndirect` = `Out`; restored → `In`; direct writers `writeGlobal`/`setHdrGlobal` = `In` both ways. **Impact note:** broad by design — any function transitively reaching a common writer (logger/counter) becomes `In`. Also confirmed this run: **poc-4 advanced to `f4fc004` = the merge of PR #41 (3.1 + 3.2)**, so 3.1/3.2 is now *on poc-4* and this branch sits on top of it. Committed; PR pending into `poc-4`. **3.3** is resolved by 3.1 — verification-only, no code.)

> Updated: 2026-07-15 (**fixes 3.1 + 3.2 — parser scope: exclude emulator files, parse headers**. Branch `fix/parser-emul-and-headers` off `poc-4`; both isolated to Phase 1 (`engine/parser.py`). **3.1:** emulator/stub files polluted the model (root of **3.3** over-visible functions). `is_project_file` now skips any file whose basename contains an excluded substring (case-insensitive), from config `excludeNamePatterns` (default `["emul"]`) → `_EXCLUDE_NAME_PATTERNS`; a new `--include-emulator` flag empties the list. **3.2:** only `.cpp/.cc/.cxx` were collected, so a function **defined in a header** that no parsed `.cpp` `#include`s was never captured (root of **3.4**). `_collect_source_files` now buckets `.h/.hpp/.hxx` and returns them **after** the `.cpp` TUs (a full-context `.cpp` def wins the mangled-key dedup; header-as-TU only *adds* header-only defs); `CLANG_ARGS` gains `-x c++` so `.h` load as C++. `_SOURCE_EXTS` already included `.h` so headers already pass the `_FILE_COMPONENT_MAP` gate — no map change. **Beyond the upstream parser-only commits (`a8dd0d5`/`16ef182`):** `--include-emulator` was dead via `run.py` (it errored as the project path), so I threaded the flag through `run.py` → `core/group_planner.py` (`plan_runs` → `_build_model_phases` → `parser_args`), mirroring `--project-name`. Fixtures under `SampleCppProject/Layer1/Signal/`: `SignalEmul.cpp` (`emulReset`, excluded) + `SignalInline.h` (header-only `signalGain`, caller-less → invisible). **Verified A/B** (Phase-1 parse, Signal group): `emulReset` in `model/functions.json` = **0** default / **3** with `--include-emulator`; `signalGain` = **0** with parser reverted / **3** with the fix. Not committed — working-tree only pending review.)

> Updated: 2026-07-15 (**fix 3.5 — interface-table Source/Destination lists all non-self units (REQ-IT-12)**. Branch `fix/interface-table-source-dest` off `poc-4`. `engine/views/interface_tables.py` built the `sourceDest` string by keeping only **external** caller/callee units (old `_is_external_unit`/`self_component`: different component, and when `allowed_components` was set, *outside the selected group*). On a normal group-scoped run this dropped **every** intra-group relationship → the column collapsed to `-`, contradicting the static unit diagram (`unit_diagrams.py`), which draws an edge to every interacting unit except a same-unit self-loop. Fix: replace the predicate with `_keep_unit(u) = (u != unit_key)` — keep every caller/callee unit except the function's **own unit**; `allowed_components` still scopes which units become *rows* (unchanged). Only the formatted `sourceDest` changes; `callerUnits`/`calleesUnits` (full lists incl. same-module) untouched. **Verified A/B** on the "My Sample" group: `utilCompute` `sourceDest` `-` → `Lib/Lib, Sample-Core/Core`, `utilScale` `-` → `Sample-Core/Core` (own unit `Util/Util` correctly excluded). Docs: `docs/spec/SWE3_SPEC.md` REQ-IT-12 + the summary-row wording updated; e2e `test_sourcedest_dash_when_no_external_connections` → `test_sourcedest_includes_cross_unit_callers` (asserts a `.../Core` caller appears, prefix-robust since this config names the component "Sample Core" → `Sample-Core/Core`, not `Core/Core`). **Caveat (pre-existing, NOT 3.5):** the e2e interface_tables suite can't run green on `poc-4` — `tests/e2e/conftest.py` expects `output/Sample/` + component key `Core|Core`, but the current config emits `output/My-Sample/` + `Sample-Core|Core`; realigning that harness (also affects docx/flowchart/direction/snapshot tests) is a separate task. Not committed — working-tree only pending review.)

> Updated: 2026-07-12 (**docs: web-app context doc relocated + mockups dir flattened**. `git mv docs/ui/UI_CONTEXT.md web-app/PROJECT_CONTEXT.md` (retitled H1 "Frontend UI Design Context" → "Web App — Project Context") so the `web-app/` client gets a per-folder context doc mirroring the existing `api/PROJECT_CONTEXT.md`; the folder scope disambiguates it from **this** authoritative root file. With `UI_CONTEXT.md` gone, `docs/ui/` held only `mockups/`, so `git mv docs/ui/mockups docs/ui-mockups` flattened the single-child nesting (empty `docs/ui/` removed). The 8 mockup HTMLs cross-link only within their own folder → intra-folder links survive the rename. Swept `docs/ui/mockups` → `docs/ui-mockups` everywhere it appears (this file ×3, `web-app/PROJECT_CONTEXT.md` ×2, `web-app/README.md`, `web-app/CONVENTIONS.md`). **Deep historical §** refs (~L3268: `frontend/UI_CONTEXT.md`, `frontend/designs/`, `frontend/app/`) describe the pre-`web-app/` layout and are left as dated noise per the same policy as the `backend/→engine/` sweep below. Not committed — working-tree only pending review. NOTE: `web-app/PROJECT_CONTEXT.md` body still carries the old `[PRODUCT NAME]` placeholder + "product name TBD" open-decision; brand is now locked to **ArtiFex** — a content refresh of that doc is a pending follow-up, deliberately out of scope for this structural move.)

> Updated: 2026-07-11 (**engine folder renamed `backend/` → `engine/`** — "backend" clashed with `api/` (the actual FastAPI backend, §19) and the older §21 companion server. The top-level triad now reads cleanly: **`engine/` (analysis) · `api/` (server) · `web-app/` (client)**. Surgical rename: `git mv backend engine` + the ~100 folder path-refs (flat imports untouched → nothing breaks); db-backend / api-server "backend" prose deliberately left as-is. The `> Updated` history + numbered sections below were swept `backend/`→`engine/`; a few **deep historical** refs to the old companion server (§21/§23 — e.g. `engine/main.py`, which doesn't exist) are dated noise, not current paths. Tests: 3 pre-existing unit fails only, api 50/50. NOTE: the restructuring entry just below still reads `engine/` throughout because it was swept — it describes the net `src → engine` outcome.)

> Updated: 2026-07-11 (**folder restructuring — engine consolidated under `engine/`** (branch `refactor/folder-restructuring`, roadmap task 1). Landed in tested stages (unit: only the 3 pre-existing `unit_diagrams` mermaid-label failures; `tests/api` 50/50 with `--skip-pipeline`): **(1) `src/` → `engine/`** — flat imports (`from core…`) unaffected; fixed ~30 literal `"src"` path refs (core/paths.py, run.py, test `sys.path` inserts, api/{pipeline_runner,git_cli}, flowcharts default engine path). **(2) `config/` → `engine/config/`** — `load_config(<dir>)` keeps its `<dir>/config` contract, so engine callers now pass the **backend dir** (`paths().src_dir` / `SCRIPT_DIR`); direct config-path sites (paths.py, flowchart_engine walk, puppeteer in views+utils, api base-config in pipeline_runner+doc_render, e2e tests) point at `engine/config`; abbreviations caller passes backend. **(3) `few_shot_examples/` + `assets/` → `engine/`** — few-shot resolves against the analyzed project's `base_path` (no code change); `assets/` was repo-root-relative in docx_exporter → `engine/assets`. **(4) generators → `engine/`** — `fake_flowchart_generator.py` (the `_resolve_script` fallback, now `project_root/engine/fake_flowchart_generator.py`) + the orphaned `behaviour_diagram_generator.py`. **(5) `run.py` → `engine/run.py`** — `SCRIPT_DIR` now resolves **two** dirs up so it still equals the repo root → every repo-root-relative join in run.py is unchanged (chdir, model dir, `SCRIPT_DIR/backend` on sys.path, PhaseRunner root); api root-detection (`json_db._find_root`) keys off `engine/run.py`; `pipeline_runner` + incremental `generate/engine` + the e2e/test_cli harness invoke `engine/run.py`. **`api/` kept as-is** — absolute `from api.` imports (and a hyphen in `api-server`) would break. **Deferred (NOT done):** `tools/` (mock-api + dev scripts) and gitignored `.data/` (model/output/workspaces/logs) — those still sit at the repo root. Every `src/…` **engine** path in this doc was rewritten to `engine/…`; the remaining `src/…` mentions are the **web-app frontend** (`web-app/src/…`), correctly unchanged.)

> Updated: 2026-07-10 (**pre-V1 correctness batch logged** — 10 review findings (2026-07-10) tracked as `docs/planning/ROADMAP.md` task **3.1–3.10** and detailed in §16 "Known risks / technical debt" → "Pre-V1 correctness batch". In brief: exclude emulator files from the parse scope (3.1, root); parse header files `.h/.hpp` (3.2, root); some functions over-visible (3.3, **re-test after 3.1**); interface direction shows "Out" instead of "In" (3.4, **re-test after 3.2**); include same-component source/destination pairs (3.5); make interface-table direction consistent with the static diagram — **decision: follow the function-call relationship, stop factoring global-variable access into direction** (3.6); functions missing from DOCX by access specifier (3.7, known); if/else depiction (3.8) and overlapping edges (3.9) in the flowchart; under-specified dynamic-behaviour issue (3.10, needs repro). **Planning only — no code changed.**)

> Updated: 2026-07-02 (brand: **ArtiFex product mark (logo icon)**. New shared component `web-app/src/components/ui/BrandMark.tsx` (exported from `components/ui/index.ts`) renders the mark: **‹ A ✦ ›** — code angle-brackets framing a half-drawn "A" whose right leg dissolves into an AI spark (coding + documentation/AI + the ArtiFex "A"). **No background/container** — every stroke/fill is `currentColor`, so callers set color per surface: the 5 branding spots pass `text-secondary` on light bars (Sidebar, ProjectsPage top bar, NewProjectPage header, SignInPage mobile logo) and `text-white` on the dark sign-in panel (SignInPage desktop). Replaced the earlier `bg-secondary rounded-lg` box + Material `account_tree` glyph at all 5 spots (functional `account_tree` tree/empty-state icons unchanged). `web-app/public/favicon.svg` is the same mark, **color-adaptive** via an inline `<style>` `@media (prefers-color-scheme: dark)` (brand-blue #0058be on light tabs → #fff on dark tabs) so it stays visible on any browser tab; `index.html` `<link rel=icon href="/favicon.svg?v=5">` carries a cache-buster (bumped through the design iterations) because browsers cache favicons hard. Iterated with the user through many concepts (craftsman/anvil → code/doc/testing → AI spark → hexagon frame → hexagon *outer box* badge → no-background mark) landing on the transparent ‹A✦› with "more gap" bracket spacing. `npm run build` clean; vitest 19/19.)

> Updated: 2026-07-01 (merge-claude: **new tool — import a viewable project from existing analyzer output, no pipeline re-run**. `scripts/import-output-project/import_output_project.py` (+ README) takes a per-commit snapshot dir (auto-discovers `output/`, `model/`, and the project `config.json` one level up) or a bare `output/` folder (with `--model`/`--config` overrides), copies the artifacts into the render-addressed layout `workspaces/<newpid>/<commit[:16]>/{output,model}`, and inserts Project + Version + Commit + Documents (+ sections) + admin member into the **JSON-backed** DB (`api/db/data/*.json` — so run the API with `API_DB_BACKEND=json` to see it). It **reuses the pipeline's own record builders** `pipeline_runner._make_documents` / `_make_sections` (and `_load_base_config`/`_strip_jsonc` to parse the JSONC `layers`) so imported projects are identical to real runs — one SWE.3 "Detailed Design" doc per output dir holding a real `software_detailed_design_<group>.docx`. Architecture: the analyzer `config.json` `layers` nested-dict (`{LAYER:{path,groups:{GROUP:{COMPONENT:files}}}}`) is converted to the API `architecture_layers` list shape so doc `layer`/`group` labels are correct (e.g. `LAYER1`/`App`,`Math`); groups the config misses fall back to a synthesized `--layer` (default `LAYER1`). **No git commit/tag required** — `--commit` defaults to a synthesized 40-hex sha (used only as the workspace dir key + `version.commit_sha` + Commit record) and `--tag` defaults to `v1.0.0`; pass them to match a real revision. Owner defaults to seed user `admin@aspice.dev` (u1). **Companion render change** (`api/routes/documents.py::render_document`), **scoped to imported/repo-less projects so real flows are byte-for-byte unchanged**: when `project.repo_url` is empty **and** a per-commit `model/` exists at `out_root.parent/"model"`, it passes `model_root = <that dir>` to `doc_render.build_render` so the imported project renders its **own** copied functions/units/dataDictionary/metadata; otherwise `model_root=None` → the pre-existing default (shared repo `model/`). Real projects always have a `repo_url` (wizard requires it for cloning), so they hit the unchanged path. `build_render` already accepted `model_root` (compare engine uses it). **Deliberately NOT unconditional**: an earlier unconditional version was reverted per user because it would change what *every* real project's every version renders — today all versions share the last run's repo `model/` (a latent bug: e.g. `pd1672c12` versions currently render `SampleCppProject2-mnz`'s model), and fixing that for real projects was out of scope for this tool. Verified e2e: `p51dd294c` (imported, `repo_url=''`) → PER-COMMIT model, cover reads copied `projectName='SampleCppProject2-mnz'`; `pd1672c12`/`pb701836d` (real, `repo_url` set) → shared repo `model/`, identical to before. Note: deleting the shared repo `model/` is NOT a fix — `_load_model_json` returns `{}` for missing files, blanking model-derived content (function descriptions, data dictionary, cover name) for ALL projects; only per-version tables/flowcharts/diagrams (read from `group_dir`) would survive. Import verified e2e: `workspaces/pb701836d/08d2f565cd03e72e` → `p51dd294c` "Imported Demo", 2 docs (App/Math, SWE.3, LAYER1), rich render with interface tables + flowcharts + diagrams.)
> Updated: 2026-07-01 (merge-claude: **UI — job phase stepper: removed the "Phase N" ordinal, promoted the step name**. On the Project Detail running-job panel the stepper previously made "Phase 1/2/3/4" the headline (11px semibold) and the descriptive step name ("Parse C++", "Derive Model", "Run Views", "Export DOCX") a small muted 10px sub-line. Inverted per user: the ordinal line is **dropped** and the descriptive name is now the headline (13px `text-body`, semibold, status-colored). Live UI: `web-app/src/pages/ProjectDetailPage.tsx::PhaseStep` (~L203) collapsed the two `<p>`s into one — `<p className={cn('mt-1.5 font-semibold text-body', pending?'text-outline':'text-on-surface')}>{label}</p>` (`label` is already `p.name` from L1002; `n` prop still used by the pending step-circle at L200). Mockup kept in sync: `docs/ui-mockups/project-detail.html` (4 phase blocks, ~L438-467) — deleted each `<p>Phase N</p>` and moved its `id="phN-name"`/classes onto the descriptive `<p>` at `font-size:13px` (ph1/ph2 `text-on-surface`; ph3/ph4 keep the pending `color:#74777d`); the mockup JS at L2334/2342/2350 only recolors `ph{n}-name` by status, so the id had to stay on the promoted element (no JS change). Unchanged: backend `_PHASES`/`AnalysisPhase`/`group_planner` phase-name strings (UI already receives "Parse C++"/… as `p.name`), and the "Pause after Phase 1" checkbox copy. `npm run build` clean; vitest 19/19 pass.)
> Updated: 2026-07-01 (merge-claude: **brand — enlarged the ArtiFex lockup in the web app**. The wordmark previously rendered at `text-title` (15px) beside a 32px (`w-8 h-8`, icon 18) logo tile in all 5 brand spots. Bumped both proportionally: wordmark `text-title`→`text-xl` (20px) and tile `w-8 h-8`→`w-9 h-9` (icon 18→20) in `components/shell/Sidebar.tsx`, `pages/ProjectsPage/index.tsx`, `pages/NewProjectPage.tsx` (wizard `PageHeader`). On `pages/SignInPage.tsx` the brand was being visually dominated by the 28px marketing headline, so both its lockups (desktop panel + mobile logo) go **larger** — `text-3xl` (30px) wordmark + `w-11 h-11` tile (icon 24) — so the brand out-weighs the headline. Tagline (`text-caption`) and `constants/branding.ts` strings unchanged; scope web-app only (mockups/API/favicons untouched). `npm run build` clean; vitest 19/19.)
> Updated: 2026-07-01 (merge-claude: **fix — commit sha shown as the project name in the DOCX cover + 1.1 Purpose/Scope**. The visible name comes from `model/metadata.json → projectName`, written by Phase 1 `engine/parser.py:64` as `PROJECT_NAME = _project_name_override or os.path.basename(MODULE_BASE_PATH)`; the override is set **only** by the `--project-name` CLI flag. Normal runs do NOT go through `pipeline_runner._build_cmd`/`run.py` directly — `pipeline_runner._run` dispatches to the incremental engine (`engine/incremental/generate.py` for `mode=full`, else `engine/incremental/engine.py`), and **neither engine passed `--project-name`** when building its `run.py` command, so `MODULE_BASE_PATH` = the per-commit checkout dir `workspaces/<pid>/<commit[:16]>/` → its basename (the 16-char sha) became `projectName` → the sha surfaced in the cover title and the `{project_name}` placeholder of `docx.introduction.purpose`/`scopeIntro`. Fix (**source-level, both surfaces at once**): both engines already load the project record via `incremental.project_db.get_project(project_id)` (dict carries `name`), so now they forward it as `--project-name`. `generate.py::generate_full` derives `project_name = (project.get("name") or "").strip()` and appends `--project-name` to `base_cmd` (used for both the `--to-phase 1` parser run and `--from-phase 2`). `engine.py::_run_analyzer` gained an optional `project_name` kwarg (appends the flag when set); `generate_incremental` derives `project_name = (project.get("name") or "").strip() or None` and threads it through `_try_narrowed_parse` (which forwards to its `--to-phase 1 --only-files` call) and all `_run_analyzer` Phase-1 calls (also passed to the `--from-phase 2` call, harmless — `--project-name` only affects the parser). No change to `run.py`/`group_planner.py`/`parser.py` (they already accept + forward the flag). Fixing `metadata.json` at the source corrects **both** the web inspector (`api/services/doc_render.py:582` reads `meta_data.get("projectName")`) and the exported DOCX (`engine/docx_exporter.py:1286-1289`). Note: `pipeline_runner._build_cmd:616` still passes `job.version_tag` as `--project-name`, but that path is only the Phase-4 re-export (`from_phase=4`, `use_model=True`) which doesn't re-run the parser, so it doesn't touch `metadata.json` — left as-is. **Pre-existing versions are not migrated** — docs generated before this fix keep the sha `projectName` in their snapshot until re-run. `tests/api` 50 pass (`--skip-pipeline`; no test asserts projectName). **Requires API restart to pick up the changed `engine/incremental/*` modules.**)
> Updated: 2026-07-01 (merge-claude: **product name locked = ArtiFex** (tagline "Crafted from Code"). The web UI previously shipped a literal `[PRODUCT NAME]` placeholder + an "Automotive Tier 1" category label wherever the brand appears. New single source of truth `web-app/src/constants/branding.ts` (`APP_NAME='ArtiFex'`, `APP_TAGLINE='Crafted from Code'`) is imported into the 4 branding spots — `components/shell/Sidebar.tsx`, `pages/SignInPage.tsx` (desktop logo has name+tagline, mobile logo name-only), `pages/ProjectsPage/index.tsx`, `pages/NewProjectPage.tsx` (the `uppercase` mono class still renders the tagline in caps). `web-app/index.html` `<title>` hardcoded to "ArtiFex" (static HTML can't import the TS constant). **Scope was web app only** — deliberately NOT touched: `api/main.py` FastAPI title ("ASPICE Documentation Platform"), the 8 `docs/ui-mockups/*.html`, README/CLAUDE.md/AGENTS.md, `package.json` names, favicon SVGs — all still carry the placeholder/working title and are a possible follow-up. `npm run build` clean; vitest 19/19 (no test asserts the brand string).)
> Updated: 2026-07-01 (merge-claude: **fix — wide Document Inspector sections (Interface Table) were clipped/invisible**. `web-app/src/pages/DocumentInspectorPage.tsx` renders a rigid 3-column layout: left `DocTreePanel` (`w-60`, `flex-shrink-0`), center canvas (`flex-1` capped at **`max-w-3xl`** = 768px with nested `px-6`+`px-12` padding → only ~620px usable), right Review-status/outline panel (`w-48`, `flex-shrink-0`, always shown). The 8-column Interface Table and the flowchart/behaviour tables exceeded ~620px, and **all three table wrappers used `overflow-hidden`** (`TableView`, `FlowchartTableView`, `BehaviorTableView`) so overflowing columns were *clipped with no scrollbar* — worse on ≤1024px screens where the `flex-1` center is starved below 768px because both side panels refuse to shrink. Fix (frontend-only, "Combined" approach chosen by user): (1) the three table wrappers `overflow-hidden`→**`overflow-x-auto`** so nothing can be clipped (4px scrollbar already styled in index.css); (2) canvas cap `max-w-3xl`→**`max-w-5xl`** (768→1024px) and heavy inner `px-12`→`px-8` on the cover header, `MetaBanner`, and sections container so the extra width reaches the tables; (3) the right `<aside>` is now **collapsible** — new persisted `inspectorPanelCollapsed` + `toggleInspectorPanel()` in the zustand UI store (`web-app/src/store/ui.ts`, added to the `partialize` list beside `sidebarCollapsed`); collapsed state renders a thin `w-9` rail with a `chevron_left` expand button + a `fact_check`/`toc` context icon, expanded state adds a `chevron_right` collapse button to the panel header (the `ReviewTracker`/TOC bodies are unchanged). No engine/type/mapper/route change. `npm run build` clean; vitest 19/19 pass.)
> Updated: 2026-07-01 (merge-claude: **fix — sliced (tall) flowcharts rendered as mermaid text, no image, in the web UI**. When a flowchart PNG is too tall, `engine/views/flowcharts.py::_maybe_slice_tall_png` writes `{stem}_part_K_of_N.png` siblings and **deletes** the original `{stem}.png` (`os.unlink`, line 681) — state is "single OR N parts, never both." The DOCX exporter is slice-aware (`_resolve_flowchart_pngs`/`_append_flowchart_entries`, `engine/docx_exporter.py:827/858`), but the web render path was not: `api/services/doc_render.py` hardcoded the single-file name `flowcharts/{stem}.png` (+ `unit_name_fc` alt) in **both** flowchart lookups (main function + private callee). Post-slice the original is gone → `png_rel` None → each entry shipped `image_url:null` → frontend correctly fell back to the mermaid `<pre>` (DocumentInspectorPage.tsx:349-352) → "only mermaid." Fix (**one file, `doc_render.py`**, no imports from `src/` — API stays self-contained): added `_resolve_flowchart_pngs(group_dir, base_stems)` (mirrors the docx resolver: regex `^{stem}_part_(\d+)_of_(\d+)\.png$`, prefers slices sorted by K, else the single png; returns rel paths `flowcharts/<name>` + "Part K of N" label) and `_flowchart_entries(group_dir, base_stems, mermaid, label, asset_base)` (mirrors `_append_flowchart_entries`: one entry per part — first carries full label + `" - Part K of N"` + mermaid, continuations carry `"(continued - Part K of N)"` + `mermaid=None`; no PNG → one `image_url:None` entry so mermaid fallback still runs). Both call sites now `flowchart_entries.extend(_flowchart_entries(...))`. **No frontend/model/route/schema change** — the frontend already renders one image per `flowcharts[]` entry (DocumentInspectorPage.tsx:346-352), the mapper passes fields 1:1 (mappers/document.ts:157-160), and the compare view (`compare_render.py`, reads `fc.image_url`) is fixed transitively since it consumes the same entries. The asset route already serves any file under the group dir by rel path, so part PNGs need no new wiring. `tests/api` 50 pass (`--skip-pipeline`). **Requires API server restart to pick up the changed module.**)
> Updated: 2026-07-01 (merge-claude: **fix — generated design docs reclassified SWE.2 → SWE.3**. The pipeline emits `output/<component>/software_detailed_design_<component>.docx` — a **Software Detailed Design**, which in ASPICE is **SWE.3** (Software Detailed Design and Unit Construction), not **SWE.2** (Software Architectural Design). `api/services/pipeline_runner.py::_make_documents` tagged every generated record `add("SWE.2", disp, "Component Design", …)`, filing real detailed-design docs under the wrong process. Fix (**one line + comment**, `pipeline_runner.py:1096`): `add("SWE.3", disp, "Detailed Design", …)`. This reverses the classification the earlier `fix/ui-offline-and-commit-issues` punch-list had set to SWE.2 — but needs **no frontend change**: `mapDocument` already passes `process` through untouched (the old SWE.2→SWE.3 remap was dropped), and the UI is fully SWE.3-ready (Badge color, `docTree.DOC_PROCESSES`, `DocumentsPage.PROCESSES`, `ProjectDetailPage.PROCESSES` "Detailed Design" row). Docs now surface under the existing SWE.3 tab/dashboard row; SWE.2 becomes an empty ASPICE process (renders "Not generated yet" like SYS.1/SYS.2/SWE.1). `_make_sections` already seeds the 4-section body for SWE.3 via its `else` branch, and `doc_render` cover + inspector read `doc.process` directly, so SWE.3 propagates everywhere for free. **Pre-existing `documents.json` rows are not migrated** — they keep SWE.2 "Component Design" until re-run. Seed/demo data in `api/db/in_memory.py` (doc3 sample) left as-is. `tests/api` 50 pass (`--skip-pipeline`; no test asserts the process). **Requires API restart to pick up the changed module.**)
> Updated: 2026-07-01 (merge-claude: **fix — compare view showed no changes** (per-document detail rendered every section `unchanged` with identical current/baseline content). Same version-id-vs-commit confusion in the compare layer: `compare_engine._snap` locates a snapshot at `workspaces/<pid>/<commit[:16]>` (slices `[:16]`), but the two **per-document** functions passed the API `Version.id` (`ver…`) instead of the commit — `compute_document_diff` (`compare_engine.py:215-216`) and `compute_document_sections_diff` (`compare_engine.py:363-364`). `ver6154f950`[:16] → nonexistent dir → `_snap` None → the rich renderer (`compare_render.compute_document_render_diff`) got null snaps → returned None → the route fell to the **DB-stored sections fallback** where seeded sections are all `unchanged`. (`compute_compare`, the summary/left panel, already used `.commit_sha` — that's why only the detail was broken; frontend was fine — `mapCompareDocumentDiff` already renders both `mode:"rich"` blocks and flat.) Fix #1 (`compare_engine.py`, 4 lines): pass `cur_ver.commit_sha`/`base_ver.commit_sha` to `_snap`. Fix #2 (`compare_render.py`, diagram images): `_version_render` built the asset URL from `version.id` and `resolve_snapshot_asset` resolved under the removed `workspaces/<pid>/versions/<id>/…` tree; both now key by `commit[:16]` (`workspaces/<pid>/<commit[:16]>/output/<group>`), the only caller being the `compare_asset` route. Verified end-to-end on project `pd1672c12` (2 on-disk versions): `compute_document_diff` now returns `mode:"rich"` (App summary changed 3/unchanged 13; Math changed 5/removed 4) with word/table/diagram marks, and a diagram `image_url` resolves to a real PNG on disk. `tests/api` 50 pass. No frontend/model/route-signature change.)
> Updated: 2026-07-01 (merge-claude: **fix — explicit incremental baseline ignored** (`baseVersionId 'ver…' not found; using auto baseline`). Two version-id namespaces were never translated: the API stores `job.reference_version_id` as its own DB `Version.id` (`ver6154f950`), but the incremental engine's version list is `versionId == commit[:16]` (`incremental/project_db.py:66-80 list_versions`, used by `engine.py:318` + `preview_baseline`). `api/services/pipeline_runner.py` passed the `ver…` id **raw** into the engine's namespace, so `select_baseline` (`engine/incremental/baseline.py:60-63`) never matched → warning + silent auto fallback (correct but slower; chosen base dropped). Same mismatch hit **three** spots, all fixed by a new `pipeline_runner._resolve_ref_commit(db, version_id)` (uses `db.versions.get(...).commit_sha`): (1) the engine `--base-version-id` arg → now `commit[:16]` when resolvable, else raw id (a deleted base still warns); (2) `_load_and_register_functions` → `_baseline_fn_keys` was getting the `ver…` id where `_commit_dir` expects a commit (slices `[:16]`, line 869) → nonexistent dir → `None` → the "is this function new?" diff was **silently disabled**; now passes the full commit; (3) `preview_baseline` → translates the UI's `base_version_id` query the same way (unknown values pass through so a real versionId still works). No engine/model/namespace change — `reference_version_id` stays a `ver…` id everywhere it's stored/echoed; only values handed to the engine layer are translated. Verified: `ver6154f950` → `08d2f565cd03e72e82c…` → engine versionId `08d2f565cd03e72e` (a real prior version); `tests/api` 50 pass (`--skip-pipeline`).)
> Updated: 2026-07-01 (merge-claude: **fix — flowcharts never generated**. The flowchart engine subprocess crashed at `clang.cindex.Index.create()` (`engine/flowchart/ast_engine/parser.py:92`, reached from `TranslationUnitParser.__init__`) with `LibclangError: Could not find module 'libclang.dll'` on **every** run, so the DOCX exported with **zero flowcharts** while `engine/views/flowcharts.py` swallowed the child traceback (`shell=True`, no stderr capture) and logged only `generator exited with code 1` — the failure was invisible (log jumps straight from `Processing N function(s)` to the error, never reaching the `--no-llm`/`── File:` lines). Root cause: `engine/flowchart/` **never called `Config.set_library_file()`** — unlike Phase 1's `engine/parser.py:79-90` — and relied on default OS discovery of libclang, which fails when LLVM's `bin` isn't on PATH (the installed `clang` pip binding, 21.1.7, bundles no DLL). Reproduced under the subprocess's Python 3.14: default `Index.create()` → LibclangError; `set_library_file(r'C:\Program Files\LLVM\bin\libclang.dll')` → OK. Fix (**one file, per user "minimum changes"**): added `engine/flowchart/flowchart_engine.py::_configure_libclang()`, called as the first line of `run()` (before `TranslationUnitParser` is built), which resolves the DLL from `LIBCLANG_PATH` env (set by the API's `_execute_subprocess` when `cfg.libclang_path` is configured) **or** the analyzer config's `clang.llvmLibPath` (loaded via the same cwd-walk `_load_analyzer_llm_config` uses — config is proven reachable, it's the source of the LLM banner), then `os.add_dll_directory` + `Config.set_library_file`. Verified end-to-end: engine now logs `libclang configured: …`, processes functions, writes `output/<c>/flowcharts/*.json`, exits 0 (Math model → 3/3 OK). Deferred (not done, per minimum-changes): stderr capture in `views/flowcharts.py`, `run.py` setting `LIBCLANG_PATH`. See corrected §4c — its prior claim that run.py sets `LIBCLANG_PATH` and the engine reads it at import was never true.)
> Updated: 2026-07-01 (fix/ui-offline-and-commit-issues: Documents page now has a **SWE.2 filter** and shows real docs under SWE.2. Since the `_make_documents` rewrite the backend emits documents with `process="SWE.2"` ("Component Design"), but three frontend spots were stale from the original web-app-api commit and hid/mislabelled them: (1) `web-app/src/services/mappers/document.ts::mapDocument` **rewrote `SWE.2`→`SWE.3`**, so every real doc surfaced under the SWE.3 tab and a SWE.2 tab would have been dead; (2) `web-app/src/pages/DocumentsPage.tsx` `PROCESSES` tab list omitted `SWE.2`; (3) `web-app/src/lib/docTree.ts` `DOC_PROCESSES` (shared by the list grouping + the DocTree rail order) omitted `SWE.2`. Fix: dropped the remap (`process: d.process`) and inserted `'SWE.2'` between `SWE.1` and `SWE.3` in both process lists (ASPICE order). Consequence: the Component-Design docs now display/group/filter as **SWE.2** everywhere the mapper feeds — including `ProjectDetailPage`'s AdminDocsCard, where they shift from the "Detailed Design (SWE.3)" row to the "SW Architecture (SWE.2)" row (both rows already existed in that page's 5-process `PROCESSES`). No engine/API/type change. `ProcessBadge` (`Badge.tsx`) already had SWE.2 styling and `DocTreePanel`'s collapsible-group logic is doc-count-based (not hardcoded to SWE.3, only its comment names SWE.3), so both worked unchanged. No test asserted the remap. `web-app` build clean (304 modules) + vitest 19/19 pass.)
> Updated: 2026-07-01 (fix/ui-offline-and-commit-issues: docs now re-scope on commit/version switch (#5). The Subbar commit/version **picker** drives which version's documents are shown, shared across project pages via the zustand UI store (`web-app/src/store/ui.ts`) and resolved by `web-app/src/hooks/useProjectViewState.ts` (yields `viewVersion`, whose `id` scopes `useDocuments(pid, { versionId })`). Selection was keyed by **commit sha only** (`selectedRef: Record<string, string>`); when >1 version shares a commit (a re-run on the same sha, or a tagged commit), `versions.find(v => v.sha === selectedSha)` returned the **first** match, so picking a different version resolved to the same `viewVersionId` and the docs never re-scoped. Fix: selection is now **id-based** — a new exported discriminated `Selection = { type:'version'; id } | { type:'commit'; sha }`; `selectedRef: Record<string, Selection>`, `setSelectedRef(projectId, sel)` (still in-memory only; `partialize` persists just `sidebarCollapsed`). `useProjectViewState` resolves a version **by id** and a commit **by sha** (`selVersion`/`selCommit`); the tagged-commit→version lookup stays by `tag`; `viewVersion = selVersion ?? selCommitVersion ?? (selection ? undefined : versions[0])`; the page-state gate keys on `selection`. The hook's **return contract is unchanged** (`pageState`/`isLoading`/`viewVersion`/`viewVersionId`/`selectedCommit`/`selectedSha`) so its five consumers (`ProjectDetailPage`, `DocumentsPage`, `DocumentInspectorPage`, `ComparePage`, `ProjectLayout`) need **no** edits — Task 5 ended up not touching `ProjectDetailPage.tsx` after all (the #3 note anticipated a collision that didn't materialise). `selectedSha` is derived for back-compat (`selVersion?.sha ?? selCommit?.sha`, undefined when nothing is explicitly selected — `ComparePage` still falls back to `versions[0].sha`). `Subbar.tsx` `CommitPicker` reads the `Selection`, resolves `activeVersion`/`activeCommit` (defaulting to the layout-supplied latest, version preferred over commit so they're mutually exclusive), writes `{type:'version',id}` for version rows (sha-fallback `{type:'commit',sha}` for id-less mock versions) and `{type:'commit',sha}` for commit rows, and highlights rows by id/sha. `ProjectLayout.tsx` now also fetches `useCommits` and passes `selectedCommit={latestCommit}` so the picker renders even on **never-run** projects (no versions). Known limitation (out of scope, not one of the 4 named files): `ComparePage` still resolves its "current" version from `selectedSha` by sha, so it keeps the same-sha ambiguity for its own picker. `npm run build` clean (304 modules); vitest unit suite 19/19 pass.)
> Updated: 2026-06-30 (fix/ui-offline-and-commit-issues: dashboard document numbers scoped to the latest version (#4). `api/routes/projects.py::_project_view` built `doc_counts` via `db.documents.get_stats(project.id)` with **no version** — summing every document the project ever produced across all runs. That count feeds the home project list (`web-app/src/pages/ProjectsPage/components/ProjectRow.tsx`) via `mapProject`: `inReviewCount` and `progress` (`approved/total`), so a multi-run project showed the all-versions sum instead of the version on display. Fix (one line): pass the already-computed `latest` version → `get_stats(project.id, version_id=latest.id if latest else None)`; `latest is None` (no versions) keeps the prior behaviour and `get_stats` still returns the full zero-filled key set (`total/approved/in_review/never/unchanged`), so the response shape is unchanged. **No store change** — both `get_stats` backends (`api/db/in_memory.py`, `api/db/json_db.py`) already filter on `version_id`. Seed proof (p1): 6 docs in `ver3` (latest) + 1 in `ver2` → was `total` 7 / `approved` 3, now `total` 6 / `approved` 2. Plus a UI fix per user direction: the project dashboard's per-process Documents card (`web-app/src/pages/ProjectDetailPage.tsx::AdminDocsCard`) **hid** a process row entirely when the selected version had no docs for it (`if (!docs.length) return null`); removed so **all 5 ASPICE process rows always render**, and a `total === 0` process now renders a **distinct, muted, non-clickable "Not generated yet" row** (dimmed process cell + a single italic label spanning the Assignment/Team columns, `colSpan={2}`, no hover/arrow) so empty processes are visually set apart from rows that have real documents. Regression test `tests/api/test_smoke.py::test_project_doc_counts_scoped_to_latest_version` asserts `doc_counts.total` == the latest version's document count **and** is strictly below the all-versions sum. `tests/api` 50 passing; `web-app` build clean. `DocumentsPage` grouping left as-is (different surface, out of scope). **Follow-on (root cause): document records now map 1:1 to real generated DOCX files.** Debugging a real run (`api/db/data/documents.json`, json_db backend) showed 1 DOCX but 3 doc records per version because `api/services/pipeline_runner.py::_make_documents` **always** created 2 hardcoded placeholders (`SYS.2` "System Requirements", `SWE.1` "Software Requirements") with no file behind them, plus architecture-walk SWE.2/SWE.3 fallbacks. Rewrote `_make_documents` to create **one `SWE.2` "Component Design" doc per group output dir that holds a real `software_detailed_design_<group>.docx`** — verified via `doc_render.find_docx` (the same path download/render serve), restricted to groups declared in `architecture_layers` (stale-dir guard via `name.replace(" ","-")`). Dropped the SYS.2/SWE.1 placeholders and all no-DOCX fallbacks; returns `[]` when the commit has no `output/`. This also corrects `version.docs_count = len(docs)` and the job's "N document(s) generated" message (`_complete`). `_make_sections`' `SYS.2/SWE.1` intro-only branch is now unreachable for new runs (left in place, harmless). Pairs with the AdminDocsCard change above: the dashboard still shows all 5 process rows, now honestly at "0 docs" for processes with no real output. **Pre-existing data is not migrated** — `documents.json` rows from earlier runs keep their placeholders until re-run. **Follow-on: generation is now per-component, not per-group (per user direction).** Runs previously produced one DOCX per group (analyzer default). **Key gotcha: normal runs do NOT go through `pipeline_runner._build_cmd`/`run.py` directly** — `pipeline_runner._run` dispatches to the **incremental engine** (`engine/incremental/generate.py` for `mode=full`, else `engine/incremental/engine.py`), which is what actually invokes `run.py`. So the per-component flag had to be injected there, not only in `_build_cmd` (which covers only the Phase-4 re-export path). Added `per_component_docx_args(scope)` to `engine/incremental/generate.py` (returns `["--component-per-docx"]` for project/layer/group scope, `[]` for a specific-component run since `run.py` rejects the combo) and appended it in **both** run.py command builders: `generate.py::generate_full` (`base_cmd`) and `engine.py::_run_analyzer` (`cmd`); `_build_cmd` also keeps it for re-export. The analyzer then emits `output/<component>/software_detailed_design_<component>.docx` per component (`engine/core/group_planner.py` per-component dispatch over `grp.keys()`). `_make_documents` maps each component declared under a group in `architecture_layers` to its normalized output-dir name → `(display name, parent layer)`, creating one `SWE.2` "Component Design" record per component dir that holds a real DOCX (`name`=component, `group`=dir so download/render resolve, `layer`=parent layer). **Decision: groups with no components mapped generate nothing** (no per-group fallback). Example: project `p1e6c2c97` config has `L1 → group g1 → component ss` (3 files), so a run produces `output/ss/` → one `ss` record (not a `g1` group doc). `_make_sections` already keys off `doc.group` so per-component sections read `output/<component>/interface_tables.json`. `tests/unit/test_incremental_engine.py` + `tests/api` 60 passing. **Requires the API server to be restarted to pick up the changed modules** (pipeline_runner/incremental are loaded into the running process).)
> Updated: 2026-06-30 (fix/ui-offline-and-commit-issues: loaders / no empty-state flash (#3). The dashboard flashed the "No documents generated yet" empty-state on every load (and the Compare page flashed "Select a document", the Subbar badge flickered to "Not Run", the pickers showed "No versions/commits/projects") because `web-app/src/hooks/useProjectViewState.ts` defaulted `pageState` to `'never'` while its queries (`useProject`/`useVersions`/`useCommits`/`useCurrentJob`) were still loading and exposed no loading flag. Fix: the hook now also returns `isLoading` (OR of those four queries' React-Query `isLoading` — first-load only, not `isFetching`, so background refetches don't re-skeleton). Two reusable skeletons added to `web-app/src/components/ui/Skeleton.tsx` (`DashboardSkeleton` mirroring the KPI-strip + two-column body; `CompareSectionSkeleton` for the diff pane) + exported from `ui/index.ts`. Consumers gate empty states on loading: `ProjectDetailPage.tsx` shows `DashboardSkeleton` while `isLoading && !project` (and again while documents refetch on a version switch — `documentsLoading && !documents`) instead of the `pageState==='never'` branch; `ComparePage.tsx` shows skeleton rows in the DocTree, a `CompareSectionSkeleton` in the right pane while the diff list loads (so the "Select a document" empty-state only shows once loaded-and-empty) and again per-section while a selected doc's detail loads, with a tree-mode-aware `loading` prop (`diff`→compareDocs, `all`→allDocs); `ProjectLayout.tsx` renders a `Skeleton` chip for the Subbar status badge until the view state resolves; `Subbar.tsx` shows skeleton rows in the Versions/Commits picker panels and the ProjectSwitcher panel while their queries load. Pages already correct and untouched: Projects/Versions/Team/Documents/DocumentInspector. Frontend-only; `npm run build` clean (304 modules) + `npm test` green (19). Note: Task 5 (id-based selection) will also touch `ProjectDetailPage.tsx` + `useProjectViewState.ts` — edits kept surgical to avoid collision.)
> Updated: 2026-06-30 (fix/ui-offline-and-commit-issues: JSONC base config (#7). `api/services/pipeline_runner.py::_write_project_config` parsed the base `engine/config/config.json` with plain `json.load`; that file is documented JSONC (`//`, `/* */`, trailing commas), so a single comment raised `JSONDecodeError`, the `except` swallowed it, and `cfg` fell back to `{}` — silently **wiping** the base (layers/clang/views/llm/docx) so the per-project `--config` carried only `build_config` overrides. Fix: a new **self-contained, string-aware** JSONC stripper local to `pipeline_runner.py` — `_strip_json_comments` + `_strip_trailing_commas` (char-by-char state machines that skip `"..."` literals) combined as `_strip_jsonc`, with `_load_base_config(base_path)` doing strip→`json.loads` and keeping the prior `{}`-on-failure fallback. The two strippers are **deliberately duplicated** from `engine/core/config.py` (not imported): per user direction the API stays self-contained — **no imports from `src/`**. The in-package `api/services/doc_render.py::_strip_jsonc` was **not** reused because it is regex-based (`re.sub(r"//[^\n]*", ...)`) and not string-aware, so it would corrupt `"baseUrl": "http://localhost:11434"` → `"http:` → invalid JSON (same latent bug lives in doc_render; a follow-up could converge both on one correct API stripper). Verified: real `engine/config/config.json` parses with `baseUrl`/Windows `llvmLibPath` intact; a commented config that breaks `json.load` now yields the full key set; `tests/api` 49 passing. Downstream merge logic (`_convert_layers`, build_config overrides, `no_llm`, the `json.dump` write) unchanged.)
> Updated: 2026-06-30 (fix/ui-offline-and-commit-issues: layer-config conversion now preserves the wizard's per-file/per-folder selection (#6). `api/services/pipeline_runner.py::_convert_layers` built the workspace `config.json` `layers` block from the API `architecture_layers`, but `_derive_component_path` collapsed each component's selected `files` to their **common-ancestor directory** and stripped the layer prefix. When a selection spanned sibling dirs (e.g. `Layer1/Flow/*` + `Layer1/Math/*`) the common ancestor was the layer root → stripped to `""` → fell back to the component **name** (`"ComponentName": "ComponentName"`), pointing at nothing real. Fix: replaced `_derive_component_path` with `_component_paths_from_files(files, layer_path)` + a `_norm_rel` helper — it strips the layer prefix from **each** entry (preserving files-as-files and folders-as-folders, order-preserving, deduped; drops whole-layer/empty entries; keeps out-of-layer entries verbatim). `_convert_layers` now writes a **string for a single path and a list for several** (e.g. `"ComponentName": ["Flow/Flowcharts.cpp","Flow/Flowcharts.h","Math/Utils.cpp","Math/Utils.h"]`), matching the documented `str | list` component schema (§4d). **No downstream change needed**: `core.config._resolve_layer_paths` and `parser._build_file_component_map` already accept both forms (per-entry: known C/C++ ext → exact file, else directory walk). **No DB/response/swagger change**: `architecture_layers` is still stored + echoed verbatim; only the generated `workspaces/<pid>/config.json` content changes. New tests `tests/api/test_convert_layers.py` (18 cases: bug case, single/multi file+folder, backslash/`./`/trailing-slash/dup normalization, whole-layer, empty, out-of-layer, multi-segment layer path). API smoke tests still pass.)
> Updated: 2026-06-30 (fix/ui-offline-and-commit-issues: new commits now sync on every commit-list view (#2) + "last synced" shown in picker. Before, `api/routes/commits_versions.py::list_commits` only backfilled commits from the repo when the stored list was **empty** (`if not commits and page == 1`), so a push to a connected repo never appeared unless the project was re-created. Fix: page-1 `list_commits` runs `_backfill_commits_from_repo` whenever `_should_sync(project)` is true — a per-project throttle (`_COMMIT_SYNC_THROTTLE_SECONDS = 60`) so rapid refreshes don't re-scan the repo. The backfill is **insert-only**: it skips any sha already stored (`db.commits.get(project.id, sha)`), so an existing commit's `doc_status`/`version` link is never overwritten. **Non-blocking by design** so the API isn't slowed by the git round-trip: the route advances + persists the throttle clock synchronously, then the **first-ever** sync for a project (no prior timestamp) runs **inline** (so a fresh wizard project shows commits immediately — the only sync that blocks, once per project), while **every subsequent** sync is dispatched as a FastAPI `BackgroundTasks` task that fetches after the response is sent (new commits appear on the next refetch). `_backfill_commits_from_repo` therefore takes a `project_id` (not the object) and re-reads the project, since it may run post-response; reusing `db` is safe because the in-memory/json backends are process-global singletons, not per-request sessions. The throttle clock is a new `Project.last_commit_sync_at` field (`api/models/domain.py`, defaulted None; round-tripped in `api/db/json_db.py` `_project_*_dict`); a repo-less project never syncs. That same timestamp doubles as the displayed value: `list_commits` returns `last_synced_at` (added to `CommitListResponse` + swagger), the web-app `commitsApi.list` now returns `{ commits, lastSyncedAt }`, `useCommits` keeps yielding `Commit[]` via a `select` (zero ripple on its 6 call sites) and a sibling `useCommitsLastSync` selects the time from the same cached query, rendered as a "Synced 2m ago" footer in the Commits tab of the picker (`web-app/src/components/shell/Subbar.tsx`, via `relativeTime`). `npm run build` clean; API smoke tests pass. **Follow-up root-cause fix (stale clone cache):** even with the above, a newly-pushed commit still never appeared because `api/services/repo_git.py::_clone_or_reuse` reuses the transient `workspaces/_wizard/<hash>/` clone forever and **never fetched** — so `git_cli.list_commits` ran `git log origin/<branch>` against a snapshot frozen at first-clone time. Fix: added `git_cli.fetch(repo_dir, url, user, token, ref, depth)` (fetches `+refs/heads/<ref>:refs/remotes/origin/<ref>` straight from the credential-injected URL so private repos work without persisting the token) and a `refresh` flag on `_clone_or_reuse`; `list_commits` now passes `refresh=True`, so a reused clone is updated to the current remote tip before `git log`. `browse` (wizard tree) still uses the frozen cache (refresh defaults False). Verified live against `github.com/manojksarkar/SampleCppProject`: pushing a commit then calling `repo_git.list_commits` returns it as newest. Note: the running API server must be restarted to pick up this fix.)
> Updated: 2026-06-30 (fix/ui-offline-and-commit-issues: offline Material Symbols font (#1). The icon font was loaded at runtime from Google Fonts via a `<link>` in `web-app/index.html` — a network dependency that breaks offline/air-gapped use. Fix: added the `material-symbols` npm dep (`^0.45.4`), `@import "material-symbols/outlined.css"` in `web-app/src/index.css` (alongside the existing `@fontsource` Inter/JetBrains-Mono imports), and removed the Google Fonts `<link>`. `npm run build` now emits the font as a local hashed asset (`dist/assets/material-symbols-outlined-*.woff2`, ~3.96 MB full variable font) and `dist/` contains zero `fonts.googleapis.com`/`fonts.gstatic.com` references — fully self-hosted, no runtime network calls. The existing `.material-symbols-outlined` rule in index.css (font-variation-settings, 20px) still overrides the package defaults; family name "Material Symbols Outlined" is unchanged so all icon usage works as before.)
> Updated: 2026-07-01 (perf/wizard-folder-browse: Run Analysis modal — "Start Analysis" stayed disabled when the commit list loaded *after* the modal opened. Root cause in `web-app/src/pages/ProjectDetailPage.tsx::RunAnalysisModal`: `const [commitSha, setCommitSha] = useState(defaultSha ?? cs[0]?.sha ?? '')` — `useState`'s initializer runs once at mount, so if `commits` were still loading (the commit sync/clone is slow) it initialised to `''` and never updated when the list arrived; the `<select>` visually showed the first commit (browser default for an unmatched `value=""`) but the controlled value stayed empty, so `disabled={!commitSha}` kept Start disabled until the user closed + reopened the modal. Fix: (1) an effect `useEffect(() => { if (!commitSha && commits?.length) setCommitSha(defaultSha ?? commits[0].sha) }, [commitSha, commits, defaultSha])` adopts the default commit as soon as the list loads (no-ops once set, so a manual pick is never overridden); (2) a new `commitsLoading` prop (from `useCommits().isLoading`) makes the empty-commit branch show a spinning "Loading commits…" instead of the misleading "No commits available to analyze yet." Frontend-only, `npm run build` clean. Pairs with punch-list #2 (commits sync on load) — that fixed the backend data, this fixes the modal reacting when the data lands late.)

> Updated: 2026-07-01 (design mockups: added `docs/ui-mockups/projects-portfolio.html` — the main Projects screen as seen by a **new org-level role above project admin** (project admin → developers, plus a higher portfolio-owner tier). It is a copy of `projects.html`'s chrome/table with a **portfolio roll-up inserted above the unchanged projects table**: a 4-card KPI strip (Projects 5 · Overall Approval 21% · In Review 29 · Needs Attention 2) and a 3-panel insight row — Projects-by-status **donut** (in-review 3 / stale 1 / never 1, reusing the `project-detail.html` donut idiom), a **Needs-attention** list (stale + never-run rows → `project-detail.html`) and **Review-workload** bars (VCU 26 / ADAS 2 / EPS 1). The role is shown via an `ORG ADMIN` header pill. **Static design artifact only — no `web-app/` or `api/` change, no real RBAC**; all roll-up numbers are derived from the same 5 sample projects already in `projects.html` so the strip stays consistent with the table (In-Review 29 = 26+2+1; Needs-Attention 2 = the stale + never-run rows). See §24 page inventory (row 9). An earlier plan to build this as a real React page + seeded backend `org_role` was **descoped by the user to a mockup only**.)
> Updated: 2026-07-01 (perf/wizard-folder-browse: new-project wizard Step 3 folder tree was slow to appear. Root cause: `GET /repositories/browse` (`api/services/repo_git.py::browse` → `_clone_or_reuse` → `api/services/git_cli.py::shallow_clone` → `engine/incremental/clone.py::shallow_clone`) did a plain `git clone --depth 1 --branch <ref>`, which trims history but still downloads **every file's full contents at HEAD** — even though browsing only needs path names (`git ls-tree -r --name-only`). The whole recursive tree is also fetched up front (the frontend always requests `path=''`; there is no lazy per-folder load) and a branch switch re-clones from scratch. Fix (two parts): (1) **blobless partial clone for browsing** — `shallow_clone` gained an opt-in `blobless` flag that adds `--filter=blob:none --no-checkout`, so the wizard clone fetches commit + tree objects but no blobs (order-of-magnitude faster on large repos); threaded through `git_cli.shallow_clone` and used **only** by `repo_git.browse` (`blobless=True`), with the flag added to the `_wizard` clone-cache key (`@b{0|1}`) so it can't collide with the full clones `list_commits` makes. Analysis clones (jobs/CLI via the same shared primitive) are unchanged — they parse source and still need blobs. `git ls-tree`/`HEAD` resolve fine against a `--no-checkout` partial clone (only blobs are filtered, and ls-tree reads tree objects, so no lazy blob fetch is triggered). (2) **Step 3 loaders** — `web-app/src/pages/NewProjectPage.tsx` now tracks `repoTreeLoading` around `loadRepoTree` and shows an inline `TreeLoading` spinner in both right-side panels (Add-Component tree + the Select-Folder picker) instead of an empty root while the clone runs. Frontend build clean; `tests/api` green (`--skip-pipeline`). Branched off `main` (not stacked on the fix/ui-offline punch-list branch).)

> Updated: 2026-06-30 (feat/web-app-api: fix new-project wizard branch/tree mismatch — selecting a non-default branch in Step 1 still showed the default branch's folder structure in Add Layer / Add Component / folder picker. Root cause: `web-app/src/pages/NewProjectPage.tsx` fetched the source tree once in `testConnection` using `res.defaultBranch` and never re-fetched when the Branch `<select>` changed. Fix: extracted `loadRepoTree(ref)` (calls `repo.browse(repoUrl, ref, '', token)` → `setRepoTree`); `testConnection` now pre-fetches with the resolved initial branch, and the Branch dropdown's `onChange` calls `loadRepoTree(b)` so the tree always matches the selected branch. Backend `/repositories/browse` already honoured `ref` — no API change. Note: switching branches after layers are already defined does not auto-clear prior file selections.)

> Updated: 2026-06-30 (feat/web-app-api: fix new-project wizard Step 4 "developers vanish after create" + team UI cleanup. Root cause: `api/routes/projects.py::create_project` added team members only `if user:` (silently dropping unmatched emails) and with `status="pending"` — pending members are excluded from `list_members` (active-only) and `team_count`, so selected developers didn't appear. Fix (single API edit): the team loop now adds every selected developer as an **active** member (`status="active"`, `joined_at=now`, mirroring the creator-add above), resolving `user_id` via `get_by_email` with a `pending_<email>` fallback so nothing is dropped — no pending/invite path. Frontend `web-app/src/pages/NewProjectPage.tsx` Step 4: removed the invite-by-email affordance (the `showInvite` "Send invite" dropdown row, `showInvite`/`EMAIL_RE`, "Add / Invite member"→"Add member", "type a full email to invite" copy) and the pending/invite concept (`Member.pending` field, "Invite pending"/"Invited" labels in member list + Step-5 review); Step 4 now only searches the org directory and adds existing users. UI: the add-member Role `<select>` was oversized (`inp w-[130px]`) vs the compact in-list role selects — restyled to match (`w-[120px]` + compact font/padding) and the results-dropdown offset adjusted `right-[140px]`→`right-[128px]`. `npm run build` clean (304 modules). The Team page's separate `/members/invite` flow is untouched.)
> Updated: 2026-06-27 (feat/web-app-api: fix compare page rendering raw JSON — `api/services/compare_engine.py` `compute_document_sections_diff` was serialising raw `interface_tables.json` unit data via `json.dumps`, causing `ComparePage.tsx` `SectionBody` to display unparseable JSON text. Added `_itf_unit_to_markdown()` which converts the `entries` list into a GitHub-style pipe table; the existing `parseSectionBody` in `web-app/src/lib/markdown.ts` parses it correctly into rendered HTML tables. No frontend changes needed; see §19 / `api/PROJECT_CONTEXT.md §8`).
> Updated: 2026-06-27 (feat/web-app-api-port: React app now lives in `web-app/` (was `frontend/app/`) and is wired to the live FastAPI API (§19) via typed mappers/hooks; **test framework added** — vitest Tier-1 unit tests (jsdom + MSW fixtures, `npm test`) + Tier-2 live-API contract validation (`npm run test:api`, ~46 endpoints vs zod schemas); commit `c888ae4`. Reference docs (not duplicated here): `web-app/TESTING.md`, `web-app/INTEGRATION_NOTES.md`, and the `ui-dev` skill (`.claude/skills/ui-dev/`, was `web-app/CONVENTIONS.md`)).
> Updated: 2026-06-23 (feat/frontend-app: all five inner React pages — `ProjectDetailPage`, `DocumentsPage`, `ComparePage`, `VersionsPage`, `TeamPage` — rebuilt as faithful 1:1 ports of their design HTML (they were previously simplified sketches missing 50–80% of the design DOM: panels, KPI strips, sub-bars, state variants, detail rows); `Document`/`TeamMember` types + `data/mock.ts` extended to the design datasets (15 docs, 9 members incl. pending, `unchanged` doc status); `npm run build` clean (263 modules); commit `98af777`; see §24 React-app implementation table).
> Updated: 2026-06-22 (feat/frontend-app branch created from `main`; `frontend/app/` (51 files, full React/Vite/TS/Tailwind v4 app) landed here; see §24 for frontend stack detail; branch supersedes `feat/product-ui-redesign`).
> Previous update: 2026-06-18 (version4 — **Incremental Changes feature** design + foundations: backend **adapted** to main's `layers`/`component` schema; `engine/git_service.py` added (git ingestion — done); **P1 onboarding stub `engine/seed_workspace.py` — done** (seeds `workspaces/samplecpp/` from the `github.com/vishal9359/SampleCppProject` test repo; branches `main`+`feature1/2/3` built for nearest/far/divergent-ancestor tests); incremental design docs `docs/production-redesign/04` (approach, v2.1) + `05` (UI API spec); implementation plan M1–M3; **M1.1 `--config`/`ANALYZER_CONFIG` config-injection — done**; **M1.2 entity hashing + slim usage index — done** (`engine/incremental/{hashing,edges}.py`; `parser.py` writes `model/hashes.json` `{entityKey→token-sha256}` for functions/globals/types/macros **and** `model/edges.json` `{typeUsers, macroUsers}`; token-based, deterministic, edges cross-reference hashes); **M1 fully done** (`--config`/`ANALYZER_CONFIG`; entity hashing `model/hashes.json`; slim usage index `model/edges.json`; D9 stores `engine/incremental/stores.py` + fingerprints + version-producing full-gen `generate.py`; backend `POST …/generate` + `versions` APIs in `engine/main.py`; verified e2e on `samplecpp` → `versions/v2` + seeded `cache/index.json`); **M2 in progress** — **M2.1** baseline+preview (`git_ops.py`+`baseline.py`) **+ M2.2** classify+impact BFS (`impact.py`) **+ M2.3** the incremental engine (`engine.py::generate_incremental`) **done** (verified e2e on `samplecpp`: v1@C3→v2@HEAD, 3 new + 6 impact incl. transitive deleted-caller, 109 reused); **parse strategy = FULL-parse + selective-LLM-regen (D10)**; **M2 fully done** — **M2.4a** `mode:"auto"` dispatch + **M2.4b** file-level flowchart reuse (`views/flowcharts.py` gated on `model/incremental_plan.json`); **M1+M2 complete; M3.1 (precise flowchart reuse) + M3.2 (function-summary reuse) + M3.3 (full Phase-2 enrichment reuse — behaviour-names/descriptions/globals restricted to the impact set; file/component summary gating; PNG reuse; + documents-capture bug fix) done**. The LLM-on payoff is now real (behaviour-names were the hidden 417s cost — config has descriptions+behaviourNames on). Re-test LLM-on **with a real diff** (baseline at an earlier commit than the target). **M3.4 end-of-run report done** (`engine/incremental/report.py`: logged to `logs/run_<date>.log` + saved to `versions/<id>/report.txt`; inputs + change classification + reuse accounting %). Remaining M3: version-scoped reads (`?versionId=`), git_ops/git_service consolidation. **Full session summary + decisions + status in §23** — read it first when resuming incremental work).
> Updated: 2026-06-23 (version4 — **Incremental Changes feature** design + foundations: backend **adapted** to main's `layers`/`component` schema; `engine/git_service.py` added (git ingestion — done); **P1 onboarding stub `engine/seed_workspace.py` — done** (seeds `workspaces/samplecpp/` from the `github.com/vishal9359/SampleCppProject` test repo; branches `main`+`feature1/2/3` built for nearest/far/divergent-ancestor tests); incremental design docs `docs/production-redesign/04` (approach, v2.1) + `05` (UI API spec); implementation plan M1–M3; **M1.1 `--config`/`ANALYZER_CONFIG` config-injection — done**; **M1.2 entity hashing + slim usage index — done** (`engine/incremental/{hashing,edges}.py`; `parser.py` writes `model/hashes.json` `{entityKey→token-sha256}` for functions/globals/types/macros **and** `model/edges.json` `{typeUsers, macroUsers}`; token-based, deterministic, edges cross-reference hashes); **M1 fully done** (`--config`/`ANALYZER_CONFIG`; entity hashing `model/hashes.json`; slim usage index `model/edges.json`; D9 stores `engine/incremental/stores.py` + fingerprints + version-producing full-gen `generate.py`; backend `POST …/generate` + `versions` APIs in `engine/main.py`; verified e2e on `samplecpp` → `versions/v2` + seeded `cache/index.json`); **M2 in progress** — **M2.1** baseline+preview (`git_ops.py`+`baseline.py`) **+ M2.2** classify+impact BFS (`impact.py`) **+ M2.3** the incremental engine (`engine.py::generate_incremental`) **done** (verified e2e on `samplecpp`: v1@C3→v2@HEAD, 3 new + 6 impact incl. transitive deleted-caller, 109 reused); **parse strategy = FULL-parse + selective-LLM-regen (D10)**; **M2 fully done** — **M2.4a** `mode:"auto"` dispatch + **M2.4b** file-level flowchart reuse (`views/flowcharts.py` gated on `model/incremental_plan.json`); **M1+M2 complete; M3.1 (precise flowchart reuse) + M3.2 (function-summary reuse) + M3.3 (full Phase-2 enrichment reuse — behaviour-names/descriptions/globals restricted to the impact set; file/component summary gating; PNG reuse; + documents-capture bug fix) done**. The LLM-on payoff is now real (behaviour-names were the hidden 417s cost — config has descriptions+behaviourNames on). Re-test LLM-on **with a real diff** (baseline at an earlier commit than the target). **M3.4 end-of-run report done** (`engine/incremental/report.py`: logged to `logs/run_<date>.log` + saved to `versions/<id>/report.txt`; inputs + change classification + reuse accounting %). **M3.5 flowchart impact-scoping fix done** (flowcharts scoped to directly-changed files, not the full impact set — a flowchart is its own CFG, independent of callee bodies). **M3.6 function-level flowchart granularity done** (per-function splice via `flowchartFids` + `_merge_incremental_flowcharts`: regenerate only the changed function, carry the rest, drop deleted; report counts flowcharts per-function). **M4.0 per-TU include-closure capture done** (`engine/incremental/parse_includes.py`; `parser.py` writes `model/tu_includes.json` `{tuRelPath → in-repo included rel paths}` every parse — foundation for **M4 narrowed parse**, fully specced in doc 04 §11 / D10, v2.3). **M3.8 branch/commit endpoints + M3.9 version-scoped reads done** (backend `?projectId=&versionId=` on components/functions/flowcharts via a request-scoped `_ReadRoots`; `GET /projects/{id}/branches` + `/commits`). **M3.7 cross-version reuse-index lookup done** (engine now reads `cache/index.json` → reverts / cross-branch-identical entities are copied from a prior version, not LLM-regenerated; verified 0/113 regenerated re-genning C3). **Move/rename orphan cleanup done** (`_prune_orphan_flowcharts` drops carried flowchart JSON/PNG for deleted/renamed files). **git_ops/git_service consolidation done** (git_ops is the single local-git module; git_service keeps only clone/fetch/auth + re-exports; `GitError` unified). **M3.7b flowchart cross-version reuse done** (a reverted directly-changed fn's flowchart is spliced from its index source version, not regenerated → a re-gen/revert is 0 LLM end-to-end). **Virtual-dispatch over-approximation done** (D7 audit: virtual-family caller-edge spreading via `engine/incremental/virtual_dispatch.py` + the `clang_getOverriddenCursors` C API; fn-ptr dispatch is a documented limitation). **M3.10 unit-diagram incremental reuse done** (carry-forward + affected-unit-only regen; no-LLM view). **All doc-05 incremental APIs implemented.** **The incremental feature is functionally complete + hardened for the POC** — only the deferred production track remains (M4 narrowed parse, M5 Postgres, M6 storage/dedup). **Full session summary + decisions + status in §23** — read it first when resuming incremental work).
> Previous update: 2026-06-17 (version4 integration branch: brought the FastAPI backend (§21) + the production-redesign design docs (§22; `docs/production-redesign/`) from `version3` onto the newer `main` code line. The backend was built against the older `modulesGroups`/`module` schema — adapting it to main's `layers`/`component`/`components.json` schema and new CLI flags is an open follow-up; see §21).
> Previous update: 2026-06-16 (fix/issues branch: three DOCX fixes — (1) TOC field depth extended from `"1-3"` to `"1-4"` so Heading 4 entries (`2.1.1.1`, `2.1.1.2`, …) appear in the table of contents; (2) `scopeItems` in 1.2 Scope section now render with `-` instead of `•` while actual component names keep `•`; (3) copyright sentence added below `assets/copyright.png` on cover page — 8 pt, gray (`#808080`), left-aligned, text defaults to `"© <year> All Rights Reserved."` and is overridable via `config.docx.copyrightText`; `_build_cover_page` gains a `copyright_text` param; see §12).
> Previous update: 2026-06-16 (feat: styled DOCX cover page — `_build_cover_page(doc, project_name, group_name)` added to `docx_exporter.py`; replaces the old bare `Heading 0` title; first page now renders: project name (54 pt bold, navy, thick double underline) right-aligned, subtitle `"Software Detailed Design Specification — <group>"` (16 pt bold, right-aligned), version + date (12 pt, right-aligned), copyright image left-aligned below text, full-width decorative arc at bottom; project name read from `model/metadata.json → projectName` at export time; group label derived from `selected_group` / `selected_components` / `"All Components"`; static assets stored in `assets/copyright.png` and `assets/bottom_arc.png`; OOXML schema order (`w:spacing` before `w:jc`) enforced to avoid Word silently ignoring alignment; see §12).
> Previous update: 2026-06-16 (`--project-name <name>` CLI flag — overrides the project name written into `model/metadata.json` as `projectName`; default remains `os.path.basename(project_path)`; parsed in `parser.py` and forwarded via `group_planner._build_model_phases`; propagates automatically to `model_deriver` (reads `projectName` from metadata), flowchart engine, and LLM prompts; `ui/app.py` derives display name from path directly and is unaffected; see §5).
> Previous update: 2026-06-15 (fix: DOCX component display names — `component_name` (normalized identifier, spaces→`-`) was being used as visible text in section headings and the Component/Unit table; introduced `component_display = component_name.replace("-", " ")` in the `export_docx` loop and passed it to `_add_component_unit_table` and `_build_component_container_mermaid`; all key lookups and filenames keep using `component_name`; see §12).
> Previous update: 2026-06-15 (`interfaceId` format change — first segment is now the layer name instead of project name: `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` / `PIF_<LAYER>_<GROUP>_<UNIT>_<NN>`; digits preserved via new `_id_seg_layer` helper so "Layer1" → "LAYER1" not "LAYER"; `get_component_layer_name(config, component)` used per entry; falls back to project name for configs without a `layers` key; see §11).
> Previous update: 2026-06-15 (feat/component-level-doc branch: `--include-path <layer> <dir>` CLI flag (repeatable) — merges extra `-I` include directories into `model/clang_include_paths.json` under the named layer before Phase 1 runs; existing layer-scoping in Phase 1 (`parser.py`) and Phase 3 (`flowcharts.py` `_resolve_layer_dirs`) handles the rest automatically; unknown layer or missing directory exits with code 1; see §5).
> Previous update: 2026-06-12 (feat/component-level-doc branch: `--macros <path>` CLI flag — reads 2-column CSV (Name, Value; header row required), converts to `-D` Clang flags for Phase 1; rows with `Value="ne"` (case-insensitive) are skipped; empty Value → `-DNAME`; written to `model/clang_macros.json` so Phase 3 flowchart engine picks them up via `flowcharts.py`; sample at `engine/config/macros.csv`; see §5, §10).
> Previous update: 2026-06-11 (feat/auto-clang-includes branch: component-level DOCX export + space normalization — `--selected-component` (repeatable, bundles into one DOCX), `--component-per-docx` (splits group/layer into one DOCX per component); spaces in group/component names replaced with `-` in all identifiers (keys, filenames, output dirs, Mermaid IDs) while display names keep spaces; `_build_file_component_map` in `parser.py` now normalizes component name values; `safe_filename` spaces→`-`; `get_component_layer_name` uses normalized comparison; see §4f, §5, §7, §9, §10).
> Previous update: 2026-06-11 (feat/auto-clang-includes branch: `--selected-component` flag added — repeatable, accumulates a list; all components must be in the same layer; output to `output/<C1_C2>/`; new `get_component_layer_name` in `core.config`; `group_planner` has a fifth dispatch shape; `run_views` and `docx_exporter` both handle the new flag; see §5).
> Previous update: 2026-06-09 (feat/auto-clang-includes branch: Phase 1 parsing scoped to selected layer — `--selected-group` passes itself to `parser.py` which derives the layer via `get_group_layer_name`; new `--selected-layer` flag parses one layer and generates DOCX for all its groups; both flags together are an error; `clang_include_paths.json` also scoped to the selected layer; new `get_group_layer_name` / `get_layer_flat_groups` helpers in `core.config`; see §4e, §5, §7).
> Previous update: 2026-06-09 (feat/from-main branch: `module` → `component` rename throughout source + model + config; `modulesGroups` → `layers` two-level config schema; same-layer model filtering in Phase 3 + Phase 4; `SampleCppProject` restructured with Layer1 + Layer2/Platform; `model/modules.json` → `model/components.json`; new `get_flat_groups` / `get_layer_components` helpers in `core.config`; `--trace-prompts` + `--filter-mode` CLI flags; `model/clang_include_paths.json` written by `run.py` before any phase; see §5, §6, §7, §9, §10, §11, §12, §15).
> Current active branch: `feat/web-app-api` (React web app + FastAPI API server, real pipeline integration; `web-app/` Vite+React+TS+Tailwind v4 app connected to real `api/` backend; supersedes `feat/frontend-app` mock-data app).
> Previous active branch: `feat/frontend-app` (React frontend with mock data — superseded by `feat/web-app-api`).
> Pipeline branch: `version4` (integration base off `main`: main code + version3 backend + production-redesign docs).
> Validated against current source. Reading this file end-to-end is the
> intended way to onboard or to refresh context after compaction.
>
> Quick orientation:
> - §4 covers the version2 refactor batches (architecture layer `engine/core/`, `engine/llm_core/`).
> - §4b covers the version3 LLM layer upgrade (token budgeting, two-pass descriptions, few-shot, cache, review, CFG simplify, strict config + startup banner).
> - §4c covers the feat/test-framework changes (test overhaul, LIBCLANG_PATH, llm.summarize).
> - §4d covers the feat/from-main changes (component rename, layers config, same-layer filtering, SampleCppProject restructure).
> - §4e covers the feat/auto-clang-includes changes (layer-scoped Phase 1 parsing, `--selected-layer` flag).
> - §4f covers component-level DOCX export (`--selected-component`, `--component-per-docx`) and space normalization in identifiers.
> - §19 covers the current FastAPI **API server** (`api/`). §21 documents an *older,
>   superseded* version3/4 backend (kept for history).
> - §22 orients you to the Production Redesign (POC→production design; docs in docs/production-redesign/).
> - All pre-existing sections have been updated in place where these branches changed behaviour.

---

## 1. What this project does

Parses a C++ source tree with **libclang**, derives a structured model of every
function / global / type, runs a set of "views" that turn the model into JSON
+ Mermaid + PNG artifacts, and finally renders a **Software Detailed Design**
DOCX document. An optional LLM pipeline enriches the model with descriptions,
behaviour names, and per-function CFG flowcharts.

The pipeline is **subprocess-based and crash-recoverable**: each of the four
phases is its own Python entry point, and `run.py` resumes from any phase via
`--from-phase N`.

---

## 2. Top-level layout

```
analyzer/                     (repo root — cwd of the pipeline; model/ output/ logs/ resolve here)
  engine/                    The analysis engine + CLI + its own config/assets
    run.py                    Entry point — argv parsing, plan + dispatch (SCRIPT_DIR = repo root, one up)
    parser.py                 Phase 1 — libclang AST → model/*.json
    model_deriver.py          Phase 2 — units / modules / call-graph / LLM enrich
    run_views.py              Phase 3 — load model, dispatch view registry
    docx_exporter.py          Phase 4 — output/* → software_detailed_design_*.docx
    utils.py                  Analyzer-specific helpers (keys, types, ranges)
    llm_enrichment.py         Prompt builders + enrichment loops (uses llm_core)
    core/                     Cross-cutting infrastructure (no upward imports)
    llm_core/                 Unified LLM HTTP client (Ollama + OpenAI gateway)
    views/                    View registry + four built-in views
    flowchart/                Real C++ → Mermaid CFG flowchart engine
    behaviour_diagram/        Sequence/behaviour diagram generator package (SequenceDiagramGenerator)
    config/
      config.defaults.json    Base defaults (JSONC: // and /* */ comments allowed)
      config.local.json       Secrets (gitignored): db + llm creds; deep-merged over defaults
      config.local.json       Local overrides (gitignored)
      abbreviations.txt       Abbreviation expansions for LLM prompts
      data_dictionary.csv     Sample data-dictionary CSV (--data-dictionary <path>)
      data_dictionary.layer1.example.csv  Per-layer sample (layers.Layer1.dataDictionary)
      data_dictionary.layer2.example.csv  Second sample — shares BufferSize_t at a
                                          different range (the per-layer case). Both
                                          shipped UNREFERENCED, like the macro examples.
      macros.csv              Sample macros CSV (--macros <path>)
      macros.layer1.example.json   Sample toolchain macro list, client schema (cu "fcore")
      macros.layer2.example.json   Second sample list (cu "hil") — the per-layer / two-file case
      puppeteer-config.json   Optional headless-chrome args for mmdc
    few_shot_examples/        Few-shot pools (descriptions / behaviour_names / globals)
    assets/                   DOCX cover assets (bottom_arc.png, copyright.png)
  api/                        FastAPI backend — kept at repo root, imports `api.*` (see §19/§21)
  web-app/                    React web client (Vite + TS + Tailwind; see §24)
  SampleCppProject/           Fixture C++ tree — Layer1 + Layer2/Platform (see §15)
  tools/                      Dev-only tooling — mock-api (mock backend), create-sample-project, import-output-project,
                              dump_docx.py (flatten a generated .docx to diffable text: headings/tables/`[image … sha=…]`)
  tests/  docs/
  model/                      Phase 1+2 output (JSON) — at repo root (cwd)
    clang_include_paths.json  Written by run.py before Phase 1; {LayerName:[abs_dirs]}
  output/                     Phase 3+4 output (JSON, .mmd, .png, .docx)
  workspaces/                 Per-project API checkouts + per-commit output
  logs/                       Daily log files (run_YYYYMMDD.log)
  CLAUDE.md                   Onboarding pointer (says "read PROJECT_CONTEXT.md")
  PROJECT_CONTEXT.md          This file

Note: config/ few_shot_examples/ assets/ and both generators live UNDER engine/;
load_config(<dir>) reads <dir>/config, so engine callers pass the engine dir
(paths().src_dir). Dev tooling (mock-api + dev scripts) now lives under `tools/`.
model/ output/ workspaces/ logs/ stay at the repo root (the gitignored `.data/`
grouping is still deferred). api/ is intentionally not renamed (absolute `from api.`
imports + a hyphen would break).
```

---

## 3. The 4-phase pipeline

```
Phase 1  engine/parser.py          C++ source → model/metadata.json,
                                             model/functions.json,
                                             model/globalVariables.json,
                                             model/dataDictionary.json
Phase 2  engine/model_deriver.py   model/ → model/units.json,
                                          model/components.json,
                                          model/knowledge_base.json (for flowchart engine),
                                          model/summaries.json (LLM hierarchy summaries)
                                  + enriches functions.json with interfaceId,
                                    direction, transitive globals, behaviour
                                    names, and (optionally) LLM descriptions
Phase 3  engine/run_views.py       model/ → output/interface_tables.json,
                                          output/unit_diagrams/*.mmd|.png,
                                          output/behaviour_diagrams/*.mmd|.png,
                                          output/flowcharts/*.json|.png
Phase 4  engine/docx_exporter.py   output/ → software_detailed_design_<group>.docx
```

Each phase is launched as a subprocess by [engine/core/orchestration.py](engine/core/orchestration.py).
That keeps the phases hermetic (separate Python processes inherit `LOG_LEVEL`)
and lets `--from-phase N` skip earlier phases on a resume.

---

## 4. Refactor history (`version2` branch)

Six refactor batches landed on this branch on top of `main`. Each batch is a
self-contained consolidation; together they introduce the `engine/core/` and
`engine/llm_core/` layers and shrink the legacy hot files.

| # | Batch | Result |
|---|---|---|
| 1 | LLM Foundation | New `engine/llm_core/` — single `LlmClient` for OpenAI gateway + Ollama with shared retry, think-section stripping, token tracking |
| 2 | Progress & Logging | `core.logging_setup` (stderr + daily file), `core.progress.ProgressReporter`, `LOG_LEVEL` env propagation to subprocesses |
| 3 | Config & Paths | `core.paths.ProjectPaths` (cached snapshot), `core.config` typed accessors with JSONC parser |
| 4 | Model IO | `core.model_io` — canonical filename constants, `read_model_file` / `write_model_file` (opt-in atomic), `load_model(*required, optional=...)` |
| 5 | Phase Orchestration | `core.orchestration.Phase` + `PhaseRunner` (single subprocess authority), `core.group_planner.plan_runs` (collapses 3-branch dispatch), run.py 257 → 152 lines |
| 6 | Config Relocation | Moved `load_config` / `load_llm_config` / JSONC strippers from `utils.py` into `core.config`, leaving thin re-export shims so existing call sites keep working |

The result: `engine/core/` is the bottom of the dependency graph and has no
imports from analyzer-level modules. Verified by `grep -r "from utils" engine/core/`
returning nothing.

---

## 4b. LLM layer upgrade (`version3` branch)

Three commits on top of `version2` implement a full LLM upgrade plan. Original
plan lives at `.claude/plans/zippy-riding-shell.md`. Shipped commits:

| Commit | Title |
|---|---|
| `17f6636` | feat: LLM layer upgrade — budgeting, two-pass, cache, review, ensemble, CFG simplify |
| `66cc98f` | fix: make maxContextTokens authoritative for coherence + simplify passes |
| `4d10df6` | feat(config): strict LLM validation + startup banner |

### Goals (why this exists)

The version2 LLM layer shipped with hardcoded char caps (`MAX_PROMPT_CHARS=6000`,
`CONTEXT_BUDGET=1200`), single-pass descriptions that never saw caller context,
nearly-useless global-variable descriptions, no few-shot examples, no cache, no
self-review, and no structured-output repair. On large models this wasted the
context window; on small models prompts silently overflowed and returned empty.
version3 rewrites the LLM subsystem around a token budget and a set of
reusable helpers in `engine/llm_core/`.

### What was NOT adopted (explicit out-of-scope)

- Tool-calling agentic loop (Ollama doesn't support it reliably).
- YAML config migration (keep JSONC).
- Full pipeline rewrite — still the same 4-phase subprocess architecture.

### Batch matrix (what every phase delivered)

| Phase | Delivered | Key files |
|---|---|---|
| **P1 — Foundation** | TokenCounter (tiktoken + char fallback), ContextBudget with `TASK_RATIOS`, `LlmClient.call()` multi-message API, config additions (`maxContextTokens`, `enrichment.*`, `fewShotExamplesDir`, `cacheVersion`) | `llm_core/token_counter.py`, `llm_core/budget.py`, `llm_core/client.py`, `core/config.py`, `engine/config/config.defaults.json` |
| **P2 — Context quality** | Degradation ladder (`ContextBuilder`), scoped `RepoMap` (neighborhood → file → module → project tiers), `get_rich_description()` with callees / callers / types / globals / siblings / repo-map, `get_rich_global_description()` for variables | `llm_core/context_builder.py`, `llm_core/repo_map.py`, `llm_enrichment.py` |
| **P3 — Two-pass + few-shot** | Two-pass descriptions (Pass 1 bottom-up, Pass 2 refines with caller context), `FewShotPool` with keyword-overlap ranking, seed example directories (`few_shot_examples/{descriptions,labels,globals,behaviour_names}`) | `llm_core/few_shot.py`, `llm_enrichment.py`, `few_shot_examples/` |
| **P4 — Cache + structured output** | `EntityCache` with composite hash keys (source + sorted callee hashes + version), `extract_and_validate()` (strip fences → extract JSON → repair → validate keys), `parse_label_response()` for flowchart batches | `llm_core/cache.py`, `llm_core/structured_output.py` |
| **P5 — Self-review, ensemble, CFG simplify** | `self_review()` generate→review→revise (≥20-line functions), `ensemble_generate()` for unit/module summaries (3 temperatures + synthesis), LLM-guided CFG simplification (merge linear ACTION chains + drop single-in/single-out), strengthened coherence prompt | `llm_core/review.py`, `llm_enrichment.py`, `flowchart/llm/generator.py` |
| **Follow-up — strict config + banner** | `LlmConfigError`, strict validation of every required and optional llm field, `format_llm_config_banner()` displayed at the start of every subprocess, removal of `getattr(client, "_num_ctx", 8192)` style hardcoded fallbacks, `LlmClient.num_ctx` property | `core/config.py`, `run.py`, `flowchart/flowchart_engine.py` |

### `llm.enrichment` flag semantics

Every feature ships gated behind `config.llm.enrichment.<flag>`:

| Flag | Default | What it does | Cost multiplier |
|---|---|---|---|
| `twoPassDescriptions` | `true` | Pass 2 refines function descriptions using caller context from Pass 1 | 2x descriptions |
| `selfReview` | `false` | generate → review → revise for function descriptions (≥20 non-blank lines) and high-visibility summaries | 3x on reviewed items |
| `ensemble` | `false` | 3 temperatures + synthesis call for unit / module summaries | 4x on synthesized items |
| `cfgSimplification` | `false` | LLM proposes merge/drop plan for CFGs with >15 nodes; only linear chains + single-in/single-out drops are applied, decisions/loops/returns are never touched | 1 extra call per large CFG |
| `variableEnrichment` | `true` | Rich global-variable descriptions (write-site + read-site evidence vs. the old one-line declaration) | — |

The defaults trade conservative cost for quality on the features that most
affect DOCX output (`twoPassDescriptions`, `variableEnrichment`). The expensive
features (`selfReview`, `ensemble`, `cfgSimplification`) are **opt-in** — set
them in `engine/config/config.json` or `config.local.json`.

### Token budgeting — `ContextBudget` + `TASK_RATIOS`

One config knob (`maxContextTokens`) now scales every prompt allocation.
[engine/llm_core/budget.py](engine/llm_core/budget.py) defines `TASK_RATIOS` — a
dict of per-task section ratios summing to ~1.0 — for:

- `function_description`, `function_description_refined`
- `variable_description`, `behaviour_names`
- `function_summary`, `file_summary`, `module_summary`, `project_summary`
- `cfg_node_labeling`, `cfg_coherence`, `cfg_simplification`
- `self_review`, `ensemble_synthesis`

`ContextBudget(max_tokens, task, counter)` reserves a 10 % safety margin then
hands each named section (`system_prompt`, `few_shot`, `callees`, …) its
absolute token budget. Callers feed content through `ContextBuilder` /
`RepoMap` / `FewShotPool` which return text sized to fit the section budget.

`resolve_max_tokens(llm_cfg)` derives `max_context_tokens`:
1. Explicit `llm.maxContextTokens` in config → used as-is.
2. Otherwise `openai` → 127488 (~128K − 512 reserve).
3. Otherwise `ollama` → `numCtx − 512`.

No silent default for `provider` or `numCtx` any more — the field must be
validated first by `load_llm_config()`.

### Strict config + startup banner (why runs are now self-documenting)

`core.config.load_llm_config()` raises **`LlmConfigError`** with the exact
failing field name when any required field is missing / empty / wrong type:
`provider`, `baseUrl`, `defaultModel`, `timeoutSeconds`, `numCtx`, `retries`.
Optional fields (`enrichment.*`, `descriptions`, `behaviourNames`,
`maxContextTokens`, `cacheVersion`, `fewShotExamplesDir`, `customHeaders`,
`rateLimitSeconds`)
are type-checked the same way. `provider` is restricted to
`"ollama"`|`"openai"`.

`core.config.format_llm_config_banner(llm_cfg)` returns a multi-line summary.
Both [run.py](run.py) and [engine/flowchart/flowchart_engine.py](engine/flowchart/flowchart_engine.py)
print it at the top of every run so the user sees exactly which
provider / baseUrl / model / `numCtx` / `maxContextTokens` (resolved, e.g.
`auto -> 7680`) / timeout / retries / enrichment flags are active:

```
------------------------------------------------------------
LLM configuration (will be used for this run)
------------------------------------------------------------
  provider          : ollama
  baseUrl           : http://localhost:11434
  defaultModel      : qwen2.5-coder:14b
  numCtx            : 8192  (used)
  maxContextTokens  : auto -> 7680
  timeoutSeconds    : 120
  retries           : 1
  rateLimitSeconds  : 3.0  (ignored on ollama)
  apiKey            : (none)
  cacheVersion      : 1
  fewShotExamplesDir: few_shot_examples
  descriptions      : False
  behaviourNames    : False
  enrichment ON     : twoPassDescriptions, variableEnrichment
  enrichment OFF    : cfgSimplification, ensemble, selfReview
------------------------------------------------------------
```

The banner is ASCII-only — `─` and `→` were removed because Windows cp1252
stderr choked on the Unicode characters.

### Quality impact ranking (original plan — for reference)

1. Richer description prompts (get_rich_description) — biggest DOCX impact
2. Two-pass descriptions — fixes the biggest blind spot (no caller context)
3. Degradation ladder — stops silently dropping callees
4. Variable enrichment — global descriptions go from useless to useful
5. Few-shot examples — teaches output style, helps weaker models
6. CFG simplification — complex flowcharts become readable
7. Scoped repo map — reduces hallucinated symbols
8. Self-review — polish for high-visibility descriptions
9. Entity cache — productivity (10× faster re-runs), no quality impact
10. Structured output — robustness (fewer fallback labels)

---

## 4c. Test-framework branch (`feat/test-framework`)

Three categories of change landed on this branch on top of `version3`:

### 1. `LIBCLANG_PATH` auto-wiring

> **Corrected 2026-07-01** — the original text below was aspirational/never true.
> `run.py` does **not** set `LIBCLANG_PATH`, and the flowchart engine did **not**
> read it. The API (`api/services/pipeline_runner.py::_execute_subprocess`) sets
> `env["LIBCLANG_PATH"]` only when `cfg.libclang_path` is configured, but nothing
> in `engine/flowchart/` consumed it — `clang.cindex` never auto-reads that env var —
> so flowcharts failed with `LibclangError` on any host where `libclang.dll` isn't
> on the loader path. Now fixed: `flowchart_engine.py::_configure_libclang()` (called
> first thing in `run()`) resolves the DLL from `LIBCLANG_PATH` **or** the analyzer
> config's `clang.llvmLibPath`, does `os.add_dll_directory` + `Config.set_library_file`
> (mirroring `engine/parser.py:79-90`), before any `Index.create()`.

_Original (inaccurate) note:_ "`run.py` reads `clang.llvmLibPath` and exports it as
`os.environ["LIBCLANG_PATH"]`; `flowchart_engine.py` picks it up at import time." Only
Phase 1 (`engine/parser.py`) ever configured libclang; the flowchart engine did not until
the fix above.

### 2. `llm.summarize` config flag

`run.py` now respects a new optional `llm.summarize` boolean in
`config.defaults.json`. When `false`, it sets `no_llm_summarize = True` before calling
`plan_runs`, suppressing Phase 2 hierarchy summarization. This mirrors what
`--no-llm-summarize` does on the CLI, but can be committed in `config.local.json`
for a permanent local preference.

### 3. Unit-test suite overhaul

| File | What changed |
|---|---|
| `tests/unit/test_llm_client.py` | Fully rewritten to test `llm_core.client.LlmClient` + `from_config` (was testing legacy `llm_client` module). Covers constructor validation, `generate()` / `call()`, retry logic, `from_config` builder. |
| `tests/unit/test_behaviour_diagram_generator.py` | Switched from `fake_behaviour_diagram_generator.FakeBehaviourGenerator` to the real `behaviour_diagram_generator.SequenceDiagramGenerator` (alias kept as `FakeBehaviourGenerator`). Patch target updated to `behaviour_diagram_generator.llm_client`. No-LLM pass: module docstring now lists which classes need no LLM (ExternalCallerFiltering, FileNaming, MmdContent) vs which are xfail (LlmContract); repeated `functions` dict extracted into `_ONE_EXTERNAL_CALLER` module-level constant; stale fence-strip comment removed from `TestMmdContent`. |
| `tests/unit/test_utils.py` | `_strip_json_comments` / `_strip_trailing_commas` now imported from `core.config`, not from `utils`. |
| `engine/flowchart/tests/test_cfg_topo.py` | Added `src/` to `sys.path` so `ast_engine.*` imports resolve when running from the project root. |
| `tests/conftest.py` | Logs the full pipeline command string before executing it (aids debugging failed CI runs). |
| `tests/unit/test_unit_diagrams_view.py` | Expanded with 10 new tests covering: subgraph module label, `mainUnit`/`internal` CSS classes, incoming caller edges, multi-iface edge joining, external caller/callee layout (before-subgraph / after-end), combined escape sequences, `_fid_to_unit` with missing key. Snapshot `tests/snapshots/Sample/unit_diagrams.json` refreshed to match current output. |

---

## 4d. feat/from-main changes

### `module` → `component` rename

Every occurrence of "module" in source, model files, config, and keys was
renamed to "component". Specific impacts:

| Old | New |
|---|---|
| `model/modules.json` | `model/components.json` |
| `core.model_io.MODULES` constant | `core.model_io.COMPONENTS` |
| `get_module_name(file, base)` in `utils.py` | `get_component_name(file, base)` |
| `init_module_mapping(config)` in `utils.py` | `init_component_mapping(config)` |
| `_MODULE_OVERRIDES` / `_MODULE_FOLDERS` | `_COMPONENT_OVERRIDES` / `_COMPONENT_FOLDERS` |
| `function["moduleName"]` in model JSON | `function["componentName"]` |
| `_build_units_modules(...)` in Phase 2 | `_build_units_components(...)` |
| `module_functions` / `function_to_module` | `component_functions` / `function_to_component` |
| `config.modulesGroups` | `config.layers` (new two-level schema, see §6) |
| `_analyzerAllowedModules` in config | `_analyzerAllowedComponents` in config |
| `moduleStaticDiagram` view key | `componentStaticDiagram` view key |
| `knowledge_base.json: "modules"` key | `knowledge_base.json: "components"` key |
| `summaries.json: "modules"` key | `summaries.json: "components"` key |
| `run.py` checks for `MODULES` on `--use-model` | checks for `COMPONENTS` |

### New `layers` config schema

`config.defaults.json` now uses a two-level `layers` structure instead of the flat
`modulesGroups`. Format:

```jsonc
"layers": {
  "Layer1": {
    "path": "Layer1",          // relative to <project_path>
    // Per-layer INPUTS live in the layer block, beside path/groups — so no layer
    // name is repeated in a by-layer map where a typo would match nothing. Both
    // optional; both are paths, never inline content. Shipped as "" (= absent) so
    // the keys are discoverable without changing the default run. See §17.
    "dataDictionary": "engine/config/data_dictionary.layer1.example.csv",
    "macros":         "engine/config/macros.layer1.example.json",
    "groups": {
      "Sample": {              // group name (for --selected-group)
        "Core": "Sample/Core", // component → path (relative to layer path)
        "Lib":  "Sample/Lib",
        "Util": "Sample/Util"
      },
      "Full": {
        "Iface": ["Direction", "Types", "Flow"],  // list of paths also OK
        "Cross": ["Hub", "Poly"]
      }
    }
  },
  "Layer2": {
    "path": "Layer2",
    "groups": {
      "Platform": {
        "Gpio": "Platform/Gpio",
        "Uart": "Platform/Uart",
        ...
      }
    }
  }
}
```

`core.config.get_flat_groups(cfg)` flattens this into
`{groupName: {componentName: resolvedPath}}` with layer paths prepended.
Falls back to the old `layer` key for backwards compatibility. `_resolve_layer_paths`
reads only `path` + `groups`, so the per-layer input keys above are ignored there and
adding more of them needs no change.

Per-layer inputs are read via `core.config.layer_source(cfg, layer, key)` /
`layer_sources(cfg, key)` → `{layer: path}`. Adding a third per-layer input costs one
call, not a new schema. `clang.macrosByLayer` still works but is **deprecated** —
`layers.<L>.macros` wins for the same layer.

**Config is per-layer only.** The project-wide dictionary and macro list are CLI
(`--data-dictionary`, `--macros`); there is no `dataDictionary.file` key. The single
exception is `clang.macrosFile` / `clang.macroScopes`, still honoured in code because
the API has no CLI path for macros (see §17, 2026-08-18) — but absent from the shipped
`config.json`.

### Same-layer model filtering

When generating a group's SDD (Phase 3 + 4), the model is now filtered to
**all components in the same layer** — not just the selected group's
components. This ensures cross-component call edges within the layer remain
visible.

- `run_views.py` calls `get_layer_components(config, group)` and then
  `_filter_model_to_components(model, layer_comps)` before passing the model
  to `views.run_views()`.
- `docx_exporter.py` applies the same filter to `units_data`, `components_data`,
  `global_variables_data`, and `functions_data`.
- `_analyzerAllowedComponents` (set on the config dict) still contains only
  the **selected group's** component names — this is what `interface_tables.py`
  and other views use to filter their output. The same-layer filter just
  ensures the model fed to the views has all same-layer data available for
  cross-component edge discovery.

### Layer include paths (`model/clang_include_paths.json`)

Before Phase 1, `run.py` walks every directory under every configured layer
path and writes the results to `model/clang_include_paths.json` as
`{layerName: [dir1, dir2, ...]}`. Phase 1 (`parser.py`) reads this file and
adds a `-I` flag for each directory so all layer headers are resolvable.

### `SampleCppProject` restructure

The test fixture was reorganised from a flat `SampleCppProject/` into:

```
SampleCppProject/
  Layer1/        — existing test fixtures (Access, App, Diag, Direction, Flow, Hub,
                   Math, Outer/Inner, Poly, Types) + new Sample/ group
    Sample/
      Core/      — Core.cpp / Core.h
      Lib/       — Lib.cpp / Lib.h
      Util/      — Util.cpp / Util.h
  Layer2/
    Platform/    — 15 new platform components (stub .cpp/.h files):
                   Adc, Cache, Config, Display, EventBus, Gpio, I2c,
                   Logger, Network, Protocol, Scheduler, Spi, Storage,
                   Timer, Uart  (each with 3-5 sub-files)
```

`config.defaults.json` defines two layers pointing at these directories. The old
`test_cpp_project/` fixture is **no longer used** (replaced by
`SampleCppProject/`).

---

## 4e. feat/auto-clang-includes changes

### Layer-scoped Phase 1 parsing

Previously, Phase 1 always parsed every file across all configured layers regardless of `--selected-group`. Since there is no cross-layer communication (only cross-group/cross-component within the same layer), this was wasted work.

**What changed:**

- `parser.py` now accepts `--selected-group <G>` and `--selected-layer <L>` flags (passed by `group_planner`).
  - `--selected-group`: calls `get_group_layer_name(cfg, G)` to find the layer, then `get_layer_flat_groups(cfg, layer)` to build `_COMPONENT_FOLDERS` from that layer only.
  - `--selected-layer`: calls `get_layer_flat_groups(cfg, L)` directly.
  - No flag: falls back to `get_flat_groups(cfg)` — all layers (existing behaviour).

- `run.py` resolves the target layer before walking directories for `clang_include_paths.json`, so only the selected layer's directories are written to that file.

- `group_planner._build_model_phases` passes `--selected-group G` or `--selected-layer L` to `parser.py` depending on which CLI flag was given.

- `--selected-group` and `--selected-layer` are **mutually exclusive** — `run.py` exits with code 1 if both are set.

### New `--selected-layer` CLI flag

`--selected-layer <L>` is a new top-level flag that:
1. Restricts Phase 1+2 to layer L only.
2. Runs Phase 3+4 for every group defined inside layer L.

This is equivalent to running `--selected-group G` once per group in the layer, but in one command.

### New helpers in `core.config`

- `get_group_layer_name(cfg, group_name)` → layer name or `None`
- `get_layer_flat_groups(cfg, layer_name)` → `{groupName: {componentName: resolvedPath}}` for one layer

---

## 4f. Component-level DOCX export + space normalization

### New CLI flags

**`--selected-component <name>`** (repeatable) — generate one DOCX covering the named component(s). Repeat the flag for each component; all must be in the same layer. Phase 1+2 parse that layer only. Output: `output/<C1_C2>/software_detailed_design_<C1_C2>.docx`. Mutually exclusive with `--selected-group`, `--selected-layer`, and `--component-per-docx`.

```bash
python engine/run.py --selected-component Gpio SampleCppProject
python engine/run.py --selected-component "Sample Core" --selected-component Lib SampleCppProject
```

**`--component-per-docx`** — modifier flag (no value). When combined with `--selected-group`, `--selected-layer`, or no selection, splits output into **one DOCX per component** instead of one per group. Cannot be combined with `--selected-component`.

```bash
python engine/run.py --selected-group "My Sample" --component-per-docx SampleCppProject
python engine/run.py --selected-layer Layer1 --component-per-docx SampleCppProject
python engine/run.py --component-per-docx SampleCppProject   # all components in all layers
```

### Naming conventions for identifiers

Group and component names may contain spaces (e.g. `"My Sample"`, `"Sample Core"`). Two rules apply everywhere a name becomes an identifier (filename, output dir, model key, Mermaid node ID):

- **Space within a name → `-`**: `"Sample Core"` → `Sample-Core`
- **Separator between component names in a bundle → `_`**: `["Sample-Core", "Lib"]` → `Sample-Core_Lib`

Display contexts (DOCX section headings, log labels) keep the original name with spaces.

### Where normalization is applied

| Location | What changed |
|---|---|
| `engine/utils.py` — `safe_filename` | Spaces → `-` before unsafe-char replacement |
| `engine/utils.py` — `_resolve_component_from_rel` | Returns `component.replace(" ", "-")` |
| `engine/parser.py` — `_build_file_component_map` | Both `setdefault` calls store `component.replace(" ", "-")` |
| `engine/views/unit_diagrams.py` — `_unit_part_id` | `replace(" ", "_")` → `replace(" ", "-")` |
| `engine/core/group_planner.py` — group output paths | `g.replace(" ", "-")` for dir + DOCX name |
| `engine/core/group_planner.py` — component bundle | `virtual_name = "_".join(selected_components)` |
| `engine/run_views.py` — `_filter_model_to_components` | `{c.lower().replace(" ", "-") for c in allowed}` |
| `engine/run_views.py` — `_analyzerAllowedComponents` | Keys normalized on set: `k.replace(" ", "-")` |
| `engine/docx_exporter.py` — same-layer filter | Both `lower` sets normalized with `.replace(" ", "-")` |
| `engine/core/config.py` — `get_component_layer_name` | Normalizes both sides of comparison |
| `run.py` — `--selected-component` collection | Normalizes input at `append` time |

**Important after this change**: any existing `model/functions.json` built before this change will have `"Sample Core|..."` keys (with spaces). Re-run from Phase 1 (`--clean` or `--from-phase 1`) after updating to get normalized `"Sample-Core|..."` keys.

### `plan_runs` dispatch shapes (updated)

`--component-per-docx` adds a new branching mode inside the existing per-group loop. When set, `plan_runs` iterates each group's components and emits one `RunPlan` per component (using `--selected-component`) instead of one per group.

| `--component-per-docx` | CLI selection | Plans emitted |
|---|---|---|
| No | `--selected-group G` | 1 plan (whole group) |
| No | `--selected-layer L` | 1 plan per group in L |
| **Yes** | `--selected-group G` | 1 plan **per component** in G |
| **Yes** | `--selected-layer L` | 1 plan **per component** across all groups in L |
| **Yes** | (none) | 1 plan **per component** across all groups in all layers |

### flowcharts.py — scoped functions temp file

`model/functions_<key>.json` casing and separator:
- Group run: `functions_My-Sample.json` (group name, spaces → `-`)
- Single component: `functions_Sample-Core.json` (component name, correct casing from `_analyzerAllowedComponents`)
- Multi-component bundle: `functions_Lib_Sample-Core.json` (sorted, `_`-joined, correct casing)

### interface_tables.py — log fix

The hardcoded log string `"output/interface_tables.json"` was replaced with the actual `out_path` so the log shows the real absolute path written.

---

## 5. CLI — `run.py`

### Syntax

```bash
python engine/run.py [options] <project_path>
```

### Flags

| Flag | Effect |
|---|---|
| `--clean` | Delete `model/` and `output/` before starting. Runs **after** `<project_path>` is validated (since 2026-08-11) — it used to run first, so `--clean <typo'd path>` wiped both dirs and then aborted. In database mode it also warns that the stored model **survives** — the directories are no longer where the model is. |
| `--model-scratch` | The model of THIS invocation is scratch, not a version's: it goes to JSON in the run's model dir and carries no version id. One caller - the narrowed parse's partial pass, whose output covers only the changed translation units and is valid only after `parse_merge`. Not a storage choice; no flag points a real run at it. |
| `--version-id <id>` / `--project-id <id>` | The run identity every phase needs once the model is rows rather than files. Applied **before** `paths()` is snapshotted. |
| `--help` / `-h` | Print the option list (the `run.py` module docstring) and exit 0. Handled at the top of the file, before `configure_logging`/`chdir`/config load, so it works even with a broken config and writes no log file. |
| `--config <path>` | Use this config file instead of `engine/config/config.json` — a per-project/per-version config (carries the project's `layers`). Resolved+validated, then exported as `ANALYZER_CONFIG` **before** the import-time config load in `utils`, so every phase subprocess (env inherited) honors it. `config.local.json` is **not** merged on top (used as-is, for reproducibility); a set-but-missing path fails loud. Foundation for incremental per-project runs (§23, M1.1). |
| `--use-model` (alias `--skip-model`) | Skip Phases 1+2; verify required model files exist; run Phases 3+4 only |
| `--no-llm-summarize` | Skip Phase 2 LLM hierarchy summarization (faster, lower quality). Summarization is **on by default**. Can also be set via `llm.summarize: false` in config (see §4c). |
| `--llm-summarize` | Accepted for back-compat; no-op (already default) |
| `--selected-group <name>` | Export only the named group. Phase 1+2 parse only that group's layer. Case-insensitive. Mutually exclusive with `--selected-layer` and `--selected-component`. |
| `--selected-layer <name>` | Parse only the named layer (Phase 1+2) and generate DOCX for every group in it (Phase 3+4 per group). Mutually exclusive with `--selected-group` and `--selected-component`. |
| `--selected-component <name>` | Export a DOCX for the named component only. Repeatable — use once per component to bundle multiple into one DOCX. All named components must be in the same layer. Output: `output/<C1_C2>/software_detailed_design_<C1_C2>.docx` (`_` between names, `-` replaces spaces). Mutually exclusive with `--selected-group`, `--selected-layer`, and `--component-per-docx`. |
| `--component-per-docx` | Modifier: split group/layer runs into one DOCX per component instead of one per group. Compatible with `--selected-group`, `--selected-layer`, or no selection. Cannot be combined with `--selected-component`. See §4f. |
| `--from-phase N` | Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export). Lets you continue after a Phase 4 crash without re-parsing |
| `--data-dictionary <path>` | CSV file merged into `model/dataDictionary.json` at end of Phase 1. **Project-wide**: its entries answer for every layer. External entries win on conflict. See `engine/config/data_dictionary.csv` for format. **CLI-only — no config key by design** (§17). |
| `--data-dictionary-layer <layer> <path>` | Same format, scoped to one layer. Repeatable, once per layer. Unknown layer → exit 1, missing file → exit 2. A layer's entries answer **only** for that layer; another layer's dictionary is never consulted. Config equivalent: `layers.<name>.dataDictionary`. |
| `--project-name <name>` | Override the project name written into `model/metadata.json` as `projectName`. Default: `os.path.basename(project_path)`. Propagates to `model_deriver` (interfaceId fallback segment, LLM knowledge base), flowchart engine, and LLM prompts. |
| `--macros <path>` | Macro file passed as `-D` flags to Clang in Phase 1, applied to **every** layer. CSV (`Name`, `Value`; header row) **or** JSON — toolchain dump (`macros_by_cu`), `{"NAME":"VALUE"}` map, `["NAME=VALUE"]` list, or `{"Layer1": {…}}`; shape is detected by content, not extension (`core/macro_input.py`). `Value` `"ne"` (any case) skips the entry; empty → `-DNAME`; function-like names are skipped + logged. Written to `model/clang_macros.json` (scope-keyed) so the Phase 3 flowchart engine picks them up. Sample: `engine/config/macros.csv`. |
| `--macros-layer <layer> <path>` | Same formats, applied to the named layer only. Repeatable — once per layer. Unknown layer → exit 1, missing file → exit 2. Clang honours the last `-D`, so a layer value overrides a `--macros` global one. Config equivalents: `clang.macrosFile` / `clang.macrosByLayer`; `clang.macroScopes` maps a multi-CU dump's compilation units to layers. |
| `--include-path-layer <layer> <dir>` | Add an extra `-I` include directory for the named layer. Repeatable — use once per directory. The directory is merged into `model/clang_include_paths.json` under the named layer key before Phase 1 runs, so Phase 1 (`clang_args_for`) and Phase 3 (`_resolve_layer_dirs`) pick it up automatically via existing layer-scoping. **No project-wide form** — an include dir always belongs to a layer. Unknown layer → exit 1. Missing directory → exit 1. Renamed from `--include-path` on 2026-08-18 (§17). |
| `--filter-mode <mode>` | Override `views.sequenceDiagrams.filterMode` for this run. Forwarded by `group_planner` to Phase 3, where `run_views.py` writes it into the in-memory config. **Live since 2026-08-22** — `SequenceDiagramGenerator._get_filter_mode` reads the key and `create_diagram_selector` maps it to a selector class. Vocabulary: `single_per_function`, `single_per_external_component`, `all_callers`, `multi_unit_functions`, `skip_within_unit` (**default**). Still **unvalidated** — an unknown value falls through the factory's `else` to `skip_within_unit` silently, so a typo degrades instead of erroring. Had **no parse branch in `run.py` until 2026-08-11** — the flag was dead and `--filter-mode X` made `--filter-mode` the project path. |
| `--trace-prompts` | Print full LLM prompts (system + user) to stdout. Sets `LLM_TRACE_PROMPTS=1` env var. **Warning**: large runs emit tens of MB. |
| `--quiet` | stderr handler raised to WARNING |
| `--verbose` | stderr handler lowered to DEBUG |

`--quiet` and `--verbose` set `LOG_LEVEL` in the environment so child phases
inherit the same verbosity.

### Argument parsing

Hand-rolled token-scanning loop in [run.py](engine/run.py) (no `argparse`).
**Strict since 2026-08-11** — the loop has no silent fall-through: a token is a
known flag, a `-`-prefixed unknown (rejected), or the single positional
`<project_path>`. Four historical bugs are guarded against here:

1. `--selected-group core` used to leave `core` as a positional after the flag
   was consumed. Fix: each flag explicitly consumes its value (`i += 1`).
2. `--from-phase` is validated to 1–4 and exits with a clear error otherwise.
3. **Unknown options** (`elif a.startswith("-")`) exit 1 with `Unknown option: <flag>`
   plus a `difflib` "did you mean" line (`n=3, cutoff=0.7` — 0.6 suggests `--help`
   for `--phase`). They used to fall into `raw_args` and be ignored, so
   `run.py <proj> --phase 3` re-ran the whole pipeline from Phase 1 in silence.
4. **Extra positionals** (`len(raw_args) > 1`) exit 1 — usually the orphaned value
   of a mistyped flag. Checked before the path check and before `--clean`, so a bad
   command line never deletes `model/`/`output/`.

`_KNOWN_FLAGS` (module level) backs both the rejection and the suggestions.
`tests/unit/test_cli.py` AST-compares it against the flag literals in the parse
loop, so adding a branch without a `_KNOWN_FLAGS` entry fails the suite.

The phase scripts (`parser.py`, `run_views.py`, `docx_exporter.py`) still ignore
unknown args — open follow-up; they are only spawned by `group_planner` today.

### Plan + dispatch

After parsing flags, run.py:

0. **Layer include paths** — resolves the selected layer (from `--selected-group` or `--selected-layer`), then walks only that layer's directories (or all layers if neither flag is set) and writes `model/clang_include_paths.json`. Phase 1 reads this to extend `CLANG_ARGS` with `-I<dir>` for each collected directory.
1. Loads `engine/config/config.json` (+ `config.local.json`) via `load_config`.
1a. **Collects layer include paths** — walks the relevant layer directory/directories under `<project_path>` recursively (skipping hidden dirs), stores result as `{LayerName: [abs_dir, …]}`, and writes it to `model/clang_include_paths.json` before any phase starts. When `--selected-group` or `--selected-layer` is set, only the targeted layer is walked. Read by Phase 1 (`parser.py`) and Phase 3 (`flowcharts.py`) — neither re-walks the filesystem.
2. **Resolves the LLM block strictly via `load_llm_config(cfg)`** and prints the
   `format_llm_config_banner` to the log so the operator sees exactly which
   provider, baseUrl, model, `numCtx`, resolved `maxContextTokens`, retries,
   cache version, and enrichment flags will be used. If the LLM block is
   missing, malformed, or has an invalid value, `LlmConfigError` is raised and
   `run.py` exits with code 2 — there are no silent defaults. (See §17 design
   decision "Fail loud on config errors".)
3. Validates `<project_path>` exists.
4. If `--use-model` is set, verifies `model/functions.json`, `globalVariables.json`,
   `units.json`, and `modules.json` are all present (paths via
   `core.model_io.model_file_path`). Exits 2 if missing.
5. Calls [core.group_planner.plan_runs(...)](engine/core/group_planner.py) which
   returns a flat `List[RunPlan]`.
6. Iterates the plans through a single [PhaseRunner](engine/core/orchestration.py)
   instance. Each plan corresponds to one `runner.run(plan.phases, from_phase=plan.runner_from_phase)` call.

The banner also re-renders inside `flowchart_engine.py::run()` when Phase 3
(flowchart engine) starts, because that engine can be invoked standalone — see
§13.

### Dispatch shapes (collapsed inside `plan_runs`)

| Config state | CLI | Phase 1+2 parses | Phase 3+4 generates |
|---|---|---|---|
| No `layers` (or `layer`) | (any) | everything | one DOCX |
| `layers` present | no flag | all layers | DOCX per group (all groups) |
| `layers` present | `--selected-group <G>` | G's layer only | DOCX for G only |
| `layers` present | `--selected-layer <L>` | L only | DOCX per group in L |
| `layers` present | `--selected-component C [--selected-component C2 …]` | C's layer only (all named components must be same layer) | 1 DOCX for C[_C2…] |
| `layers` present | any of above + `--component-per-docx` | same as without flag | 1 DOCX **per component** instead of per group |

`--selected-group`, `--selected-layer`, and `--selected-component` are mutually exclusive; combining any two exits with code 1. `--component-per-docx` cannot be combined with `--selected-component` (already at component granularity).

Phase 4 (`docx_exporter.py`) receives the group's `interface_tables.json`
and DOCX path as positional args plus `--selected-group <G>` (group path) or
`--selected-component C [--selected-component C2]` (component path) so it can
apply the same-layer model filter (see §4d).

`--from-phase` translation also lives here:
- `from_phase ≤ 2`: build-model plan starts at that index, group plans start at 1.
- `from_phase ≥ 3`: build-model plan is **suppressed**; each group plan uses `local_from = max(1, from_phase - 2)` (so 3→1, 4→2 inside the views+export plan).

---

## 6. Config — `engine/config/config.defaults.json`

JSONC: `//`, `/* */`, and trailing commas are tolerated by
`core.config._strip_json_comments` + `_strip_trailing_commas`.

### Where each setting lives (three sources, three roles)

Config is split by **role**, not scattered — each source has one job:

| Source | Role | Holds | Tracked | Scope |
|---|---|---|---|---|
| `engine/config/config.defaults.json` | built-in **defaults** | the schema below (views/clang/llm-non-secret/layers/docx) | yes | shared |
| `engine/config/config.local.json` | **secrets / infra** | `db` connection + `llm` credentials (baseUrl, customHeaders/token) | **gitignored** | per machine |
| `versions.resolved_config` (Postgres) | **per-version** analysis config | defaults + project `build_config` + `layers` (+ `no_llm`) — **non-secret** | in DB | per version |

Resolution:
- **`load_config(engine_dir)`** deep-merges `config.defaults.json` then `config.local.json`
  (`core.config._deep_merge` — nested dicts merge per key, scalars/lists replace; so
  `config.local.json` can override just `llm.baseUrl` or one `llm.customHeaders` entry without
  restating the block). Used by standalone `python engine/run.py` and by the CLI/db tools.
- **`ANALYZER_CONFIG=<file>`** (set by `run.py --config`) loads that one file *instead* — no merge.
  This is how a per-project/per-version config is injected into the analyzer and every phase
  subprocess (they inherit the env var).
- **API-driven jobs**: `pipeline_runner._write_project_config` builds the per-version **non-secret**
  analysis config (`config.defaults.json` + `build_config` + `layers`), stores it in
  `versions.resolved_config` (via `_store_resolved_config`, on the version row reserved at job
  start), and **materializes** the workspace `config.json` the engine runs with = that config with
  `config.local.json`'s secrets overlaid (llm creds), **`db` section stripped** (the engine reaches
  Postgres via `DATABASE_URL`, so the password is never written to a workspace file). The engine
  reads the workspace file via `ANALYZER_CONFIG`. `_make_version` carries `resolved_config` through
  finalize (the repo's `_put` replaces the whole row).

**Secrets never enter `config.defaults.json` (tracked) or `versions.resolved_config` (per-version).**
Copy `config.local.json.example` → `config.local.json` and fill in `db` + `llm` credentials.

### Current schema (`config.defaults.json` — non-secret defaults)

```jsonc
{
  "views": {
    "interfaceTables": true,
    "unitDiagrams":     false,
    "flowcharts":       false,
    "behaviourDiagram": false,
    "componentStaticDiagram": true   // was "moduleStaticDiagram" in older versions
  },
  "clang": {
    "llvmLibPath":       "C:\\Program Files\\LLVM\\bin\\libclang.dll",
    "clangIncludePath":  "C:\\Program Files\\LLVM\\lib\\clang\\17\\include"
  },
  "llm": {
    // ── required fields — load_llm_config raises LlmConfigError if missing ──
    "provider":          "ollama",        // "ollama" | "openai"  (strictly validated)
    "baseUrl":           "http://localhost:11434",
    "defaultModel":      "llama3.2",
    "timeoutSeconds":    300,             // positive int
    "numCtx":            8192,            // Ollama context window (positive int)
    "retries":           1,               // >=0; up to (1+retries) total tries

    // ── optional fields ──
    "descriptions":      false,           // enable LLM function descriptions (Phase 2)
    "behaviourNames":    false,           // enable LLM behaviour input/output names
    "summarize":         false,           // false = suppress Phase 2 hierarchy summarization
    // SECRETS below → put in config.local.json (gitignored), NOT here. baseUrl also if private.
    "apiKey":            "",              // openai bearer; prefer env LLM_API_KEY
    "rateLimitSeconds":  3.0,             // pause after every OpenAI call (>=0; 0 = off; ollama ignores)
    "customHeaders":     { "x-dep-ticket": "credential:", "User-Type": "AD_ID", ... },

    // version3 — token budgeting
    "maxContextTokens":  127488,          // null → auto: numCtx-512 for Ollama, 127488 for OpenAI
    "cacheVersion":      1,               // bump to invalidate llm entity cache
    "fewShotExamplesDir": "few_shot_examples",

    // version3 — enrichment feature flags (every flag must be a bool)
    "enrichment": {
      "twoPassDescriptions": true,   // Pass 2 refines with caller context   (2x desc cost)
      "selfReview":          false,  // generate→review→revise (≥20-line fns) (3x cost)
      "ensemble":            false,  // 3 temps + synthesis for unit/component summaries (4x cost)
      "cfgSimplification":   false,  // LLM proposes merge/drop plan for >15-node CFGs
      "variableEnrichment":  true    // rich global-variable descriptions
    }
  },
  // Two-level layer structure (replaces old "modulesGroups").
  // paths inside groups are relative to the layer's "path".
  "layers": {
    "Layer1": {
      "path": "Layer1",
      "groups": {
        "Sample": {
          "Core": "Sample/Core",
          "Lib":  "Sample/Lib",
          "Util": "Sample/Util"
        },
        "Full": {
          "Iface": ["Direction", "Types", "Flow"],
          "Cross": ["Hub", "Poly"]
        },
        "Support": { "Math": "Math", "App": "App", "Outer": "Outer/Inner" },
        "Access":  { "Access": "Access" },
        "Diag":    { "Diag": "Diag" }
      }
    },
    "Layer2": {
      "path": "Layer2",
      "groups": {
        "Platform": {
          "Gpio": "Platform/Gpio", "Uart": "Platform/Uart",
          "Spi":  "Platform/Spi",  "I2c":  "Platform/I2c",
          "Adc":  "Platform/Adc",  "Display": "Platform/Display",
          // … (15 components total)
        }
      }
    }
  },
  "ui": { "theme": "Light" }
}
```

### Environment-variable overrides for `llm`

`load_llm_config()` (in [engine/core/config.py](engine/core/config.py)) honors:

| Env var | Wins over |
|---|---|
| `LLM_PROVIDER` | `llm.provider` |
| `LLM_BASE_URL` | `llm.baseUrl` |
| `LLM_DEFAULT_MODEL` | `llm.defaultModel` |
| `LLM_TIMEOUT_SECONDS` | `llm.timeoutSeconds` |
| `LLM_NUM_CTX` | `llm.numCtx` |
| `LLM_RETRIES` | `llm.retries` |
| `LLM_API_KEY` | `llm.apiKey` |
| `LLM_RATE_LIMIT_SECONDS` | `llm.rateLimitSeconds` |

Custom-header values can be overridden via `X_DEP_TICKET`, `USER_TYPE`,
`USER_ID`, `SEND_SYSTEM_NAME` (handled inside `llm_core.headers`).

### Config rules

- Group names and component names: **CapitalCamelCase or snake_case**, both are tolerated.
- Each folder path should appear in exactly one component; the parser merges all
  layers/groups into one big folder set so cross-layer calls are still discoverable.
- `selectedGroup` is **not** a config key — group selection is CLI-only.
- Layer `"path"` is relative to `<project_path>`. Component paths inside a group
  are relative to the layer's path and are prepended by `get_flat_groups()`.
- Old `modulesGroups` / `layer` top-level keys still load via `get_flat_groups()`
  for backwards compatibility. New code always uses `layers`.
- LLM is off by default for descriptions/behaviour names. Phase 2 hierarchy
  summarization (which writes `summaries.json` + `knowledge_base.json`) is
  on by default and is controlled by `--no-llm-summarize`.
- **Strict validation** (version3): missing/empty/wrong-type required fields
  cause `run.py` (and `flowchart_engine.py`) to print `Invalid LLM config:
  <specific field>` and exit(2). There are no silent defaults for the required
  fields. Fix the JSON (or the matching env var) and re-run.
- **Startup banner** (version3): every run prints the resolved LLM
  configuration — provider, baseUrl, model, numCtx, `maxContextTokens`
  (resolved, e.g. `auto -> 7680`), timeout, retries, apiKey status,
  `cacheVersion`, `fewShotExamplesDir`, and which enrichment flags are ON/OFF.
  See §4b for an example.

---

## 7. `engine/core/` — infrastructure layer

Eight modules, all with no upward imports. Anything analyzer-specific stays
in `engine/utils.py` or one of the phase scripts.

### `core.paths` — [engine/core/paths.py](engine/core/paths.py)

- `ProjectPaths` frozen dataclass with `project_root`, `src_dir`, `config_dir`,
  `config_path`, `config_local_path`, `model_dir`, `output_dir`, `logs_dir`,
  `cache_dir`.
- `paths()` returns a cached singleton; `set_project_root(path)` clears it.
- Auto-detects root by walking two parents up from `paths.py` (so the snapshot
  works no matter where you launch from).

### `core.config` — [engine/core/config.py](engine/core/config.py)

- `_strip_json_comments` / `_strip_trailing_commas` — JSONC parser.
- `load_config(project_root)` — merges `engine/config/config.json` + `config.local.json`. **If `ANALYZER_CONFIG`
  env points to a file, that file is loaded instead, as-is (JSONC), with no local merge** — the per-project
  config-injection seam (§23, M1.1); set-but-missing fails loud.
- `load_llm_config(cfg)` — env-var overlay + normalised `llm` block (see §6).
- `app_config(*, refresh=False)` — process-cached merged dict.
- Typed accessors: `llm_config()`, `views_config()`, `exporter_config()`,
  `clang_config()`, `components_groups()`.
- `get_flat_groups(cfg)` — flattens `layers` (or fallback `layer`) into
  `{groupName: {componentName: resolvedPath}}` with layer path prepended.
- `get_layer_components(cfg, group_name)` → `set` of all component names in
  the same layer as `group_name`. Used by Phase 3 and Phase 4 for same-layer
  model filtering.
- `get_group_layer_name(cfg, group_name)` → the layer name that owns `group_name`, or `None`. Used by `parser.py` and `run.py` to derive the layer from `--selected-group`.
- `get_component_layer_name(cfg, component_name)` → the layer name that owns `component_name` (searches all layers/groups), or `None`. Comparison is space-normalized (both sides `.replace(" ", "-")`) so normalized identifiers match raw config keys. Used by `run.py` and `group_planner` to derive the layer from `--selected-component`.
- `get_layer_flat_groups(cfg, layer_name)` → flat groups for a single named layer only (layer paths resolved). Used by `parser.py` to restrict `_COMPONENT_FOLDERS` when a layer is selected.
- `_resolve_layer_paths(layers_cfg)` — internal helper that prepends
  `layer.path` to each component path inside the layer's groups.
- `default_clang_macro_defs()` — returns the `-D` macro list shared by
  Phase 1 and the flowchart engine's per-function re-parser.

### `core.model_io` — [engine/core/model_io.py](engine/core/model_io.py)

Canonical filenames (use these constants, never bare strings):
`METADATA`, `FUNCTIONS`, `GLOBALS`, `UNITS`, `COMPONENTS`, `DATA_DICTIONARY`,
`KNOWLEDGE_BASE`, `SUMMARIES`. Tuple `ALL_MODEL_NAMES` lists them all.
(`MODULES` constant was removed; `COMPONENTS` is its replacement.)

Functions:
- `model_file_path(name)` → absolute path under `paths().model_dir`.
- `model_files_present(*names)` → list of MISSING canonical names.
- `read_model_file(name, *, required=True, default=None)` → dict, raises
  `ModelFileMissing` if required and absent.
- `load_model(*required, optional=None)` → `{name: data}`. Optional names
  default to `{}` when missing.
- `write_model_file(name, data, *, atomic=False, indent=2)` → writes JSON.
  When `atomic=True`, writes to a sibling tempfile then `os.replace()`s into
  place.
- `ensure_model_dir()` → mkdirs and returns the model dir.

### `core.logging_setup` — [engine/core/logging_setup.py](engine/core/logging_setup.py)

- `configure_logging(*, project_root, quiet, verbose, log_dir)` installs:
  - **stderr** handler at INFO (or DEBUG/WARNING based on flags + `LOG_LEVEL`)
  - **daily file** handler at DEBUG → `<project_root>/logs/run_YYYYMMDD.log`
- Idempotent; later calls just adjust the stderr level.
- `get_logger(name)` auto-configures with defaults if no caller has yet.
- `set_level(level)` re-tunes stderr after the fact.
- Registers an `atexit` hook that dumps `llm_core.tokens.format_report()` so
  every subprocess records its own LLM token usage to the log file.

### `core.progress` — [engine/core/progress.py](engine/core/progress.py)

`ProgressReporter(component, *, total, logger, log_every)` with `start()`,
`step(label=...)`, `done(summary=...)`, and a context-manager API. On a TTY
it uses `\r` for live updates; when piped it falls back to periodic INFO log
lines (every ~10% by default). Quiet mode suppresses the live line entirely
but still logs the final summary.

### `core.orchestration` — [engine/core/orchestration.py](engine/core/orchestration.py)

```python
@dataclass(frozen=True)
class Phase:
    name: str               # "Phase 1: Parse C++ source"
    script: str             # "parser.py"
    args: List[str]         # CLI argv after the script

class PhaseRunner:
    def run(self, phases, *, from_phase=1) -> float
```

Single subprocess authority. Phases with `idx < from_phase` are skipped with a
log line. On a non-zero exit code the runner emits
`resume with: --from-phase {idx}` and raises `SystemExit(returncode)`.

### `core.group_planner` — [engine/core/group_planner.py](engine/core/group_planner.py)

Constants: `PHASE_PARSE=1`, `PHASE_DERIVE=2`, `PHASE_VIEWS=3`, `PHASE_EXPORT=4`.

```python
@dataclass
class RunPlan:
    label: str
    phases: List[Phase]
    runner_from_phase: int = 1

def plan_runs(cfg, *, project_path, selected_group, use_model,
              no_llm_summarize, from_phase=1) -> List[RunPlan]
```

Implements the three dispatch shapes from §5 in one place. Raises `ValueError`
on unknown `--selected-group`.

### `core.__init__` — [engine/core/__init__.py](engine/core/__init__.py)

Re-exports every public symbol so call sites can write
`from core import PhaseRunner, plan_runs, FUNCTIONS, ...`.

---

## 8. `engine/llm_core/` — unified LLM client + token-budget toolkit

Post-version3, `engine/llm_core/` is a full toolkit: one HTTP client plus a set of
composable helpers (counter, budget, context builder, repo map, few-shot,
cache, structured output, review). Everything LLM-related in the project
flows through this layer.

```
engine/llm_core/
  client.py              LlmClient + from_config — single HTTP client (ollama + openai)
  headers.py             build_openai_headers + resolve_api_key
  think.py               strip_think_section
  tokens.py              per-process LLM call metrics — latency/throttle/outcome/tokens,
                         stage() attribution, format_report, write_json, merge_dir
  token_counter.py       TokenCounter (tiktoken wrapper + char/3.5 fallback) — version3
  budget.py              ContextBudget + TASK_RATIOS + resolve_max_tokens      — version3
  context_builder.py     ContextBuilder — callee/caller/types degradation ladder — version3
  repo_map.py            RepoMap — scoped repo signature view (4 tiers)          — version3
  few_shot.py            FewShotPool — keyword-ranked example selection          — version3
  cache.py               EntityCache — composite-hash cache, `llm_description_cache` table (doc 10 step 10)
  structured_output.py   extract_and_validate + parse_label_response             — version3
  review.py              self_review + ensemble_generate                        — version3
```

Public API re-exported from `llm_core.__init__`:
`LlmClient`, `from_config`, `strip_think_section`, `tokens`,
`TokenCounter`, `get_counter`, `ContextBudget`, `resolve_max_tokens`,
`extract_and_validate`, `parse_label_response`, `self_review`,
`ensemble_generate`.

### `llm_core.client.LlmClient` — [engine/llm_core/client.py](engine/llm_core/client.py)

Two providers behind one interface:

| Provider | Endpoint (single-call / chat) | Auth |
|---|---|---|
| `ollama` | `POST {baseUrl}/api/generate` and `/api/chat` | none |
| `openai` | `POST {baseUrl}/chat/completions` | bearer + custom headers |

Two public call methods:
- `generate(system_prompt, user_prompt)` — simple system+user pair.
- `call(messages, *, temperature=None)` (version3) — multi-message chat API
  with per-call temperature override. Backing for ensemble + self-review.

Shared pipeline:
1. **Retry loop** — `max_retries+1` total tries, retries on Timeout /
   ConnectionError / HTTPError / empty response.
2. **`strip_think_section`** — strips `<think>...</think>` blocks before returning.
3. **Token tracking** — every successful call records prompt+completion tokens
   into `llm_core.tokens` (process-wide counter dumped at exit).

Hard rules baked in for the OpenAI route:
- A class-level `_OPENAI_LOCK` serialises every OpenAI request process-wide.
- Every OpenAI call is followed by `time.sleep(llm.rateLimitSeconds)` even on
  failure, because the corporate gateway throttles ~1 req/3s. Default `3.0`
  (`_OPENAI_RATE_LIMIT_SEC`); `0` disables the pause entirely. Ollama never
  sleeps. Cost: the engine is single-threaded, so this is ~1.5 batches +
  ~0.25 coherence calls per function ≈ **5.4 s/function** on a flowchart run.

Public properties (version3 adds `num_ctx`):
`client.provider`, `client.model`, `client.num_ctx` — prefer these over
poking `_provider` / `_model` / `_num_ctx`.

`from_config(llm_cfg)` builds an `LlmClient` from a `load_llm_config()` dict.
Legacy positional args (`url=`, `use_openai_format=`) still accepted so the
flowchart engine's standalone subprocess invocation keeps working.

### `llm_core.headers`, `llm_core.think`, `llm_core.tokens`

- `headers` — `build_openai_headers`, `resolve_api_key`. Resolves `LLM_API_KEY`
  env var first, falls back to `llm.apiKey`. Handles the corporate-gateway
  custom-header format and `X_DEP_TICKET`/`USER_TYPE`/`USER_ID`/`SEND_SYSTEM_NAME`
  env overrides.
- `think.strip_think_section(text)` — removes `<think>...</think>` sections
  (gpt-oss / DeepSeek R1 style) so downstream consumers see just the answer.
- `tokens.record(provider, model, prompt, completion)` + `format_report()` —
  process-wide counter dumped automatically by the logging atexit hook so
  each subprocess writes its own report into `logs/run_YYYYMMDD.log`.

### `llm_core.token_counter.TokenCounter` (version3)

Thin wrapper around `tiktoken.get_encoding("cl100k_base")` when tiktoken is
installed, otherwise falls back to `len(text) / 3.5` (C++ code tokenizes at
roughly 2–3 chars/token, so 3.5 is conservative).

```python
counter = TokenCounter(model="qwen2.5-coder:14b")
counter.count(text)                          # int
counter.fits(text, budget)                   # bool
counter.truncate_to_budget(text, budget)     # str — binary-search by token count
```

Module-level `get_counter(model)` caches one instance per model.

### `llm_core.budget.ContextBudget` + `TASK_RATIOS` + `resolve_max_tokens` (version3)

See §4b for the full story. Summary:

- `TASK_RATIOS: Dict[str, Dict[str, float]]` — per-task section ratios
  (sum to ~1.0, enforced by assertion). Tasks include `function_description`,
  `function_description_refined`, `variable_description`, `behaviour_names`,
  `function_summary`, `file_summary`, `module_summary`, `project_summary`,
  `cfg_node_labeling`, `cfg_coherence`, `cfg_simplification`, `self_review`,
  `ensemble_synthesis`.
- `ContextBudget(max_tokens, task, counter)` — holds a 10 % safety margin;
  `.allocate(section)` returns the section's token budget.
- `resolve_max_tokens(llm_cfg)` — priority: explicit `maxContextTokens` →
  `numCtx − 512` (ollama) → 127488 (openai). Expects a validated llm_cfg —
  no silent default for `provider` or `numCtx` any more.

### `llm_core.context_builder.ContextBuilder` (version3)

Degradation ladder: prefers breadth over depth. Starts every callee / caller /
type at Level 0 (full source + description), and when the total exceeds the
budget it promotes the lowest-priority items one level at a time until it
fits. Levels:

```
Level 0: Full source + description
Level 1: Signature + 3-line description
Level 2: Signature + 1-line purpose
Level 3: Signature only
Level 4: Qualified name only
```

Public methods: `fit_callees(callees, budget)`, `fit_callers(callers, budget)`,
`fit_types(types, budget)`. Priority ranking is by call-site count,
public/exported status, and usage frequency in the target function.

### `llm_core.repo_map.RepoMap` (version3)

Compact signature-level view built from `knowledge_base.json` (no extra
parsing). Four tiers tried from most-specific to most-general until one fits
the budget:

1. Function neighborhood — callees + callers + same-file functions
2. File level — all functions in the same file with signatures
3. Module level — all files in the module with function counts
4. Project level — module names with file counts

```python
RepoMap(knowledge).for_function(qn, budget, counter) -> str
```

Injected as a new section in both `pkb/builder.build_base_context_packet()`
(for flowchart labels) and `llm_enrichment.get_rich_description()` (for
function descriptions).

### `llm_core.few_shot.FewShotPool` (version3)

Loads hand-curated examples from
`few_shot_examples/{descriptions,labels,globals,behaviour_names}/*.json`.
Each example: `{"tags": [...], "input_context": "...", "ideal_output": "..."}`.

```python
FewShotPool(examples_dir).select(task, target_input, budget, counter) -> str
```

Ranking: keyword overlap (callee names, param types, tags). Budget-aware
greedy fill. Returns `""` if the directory is missing or empty — that is the
supported off-path, not an error.

### `llm_core.cache.EntityCache` (doc 10 step 10 — now database-backed)

Per-entity cache with composite hash keys, stored in the **`llm_description_cache`
table** (migration `0005`). It was one JSON file per entity under
`.flowchart_cache/`; on the container deployment that dies with the container and
is invisible to other nodes, giving N nodes a ~1/N hit rate.

```python
EntityCache(project_id, namespace, cache_version)   # namespace: llm_descriptions | aux_descriptions
  .get(entity_id, content_hash) -> Optional[str]
  .put(entity_id, content_hash, value, metadata=None)   # buffered
  .flush()                                              # call at the end of a pass
  .stats() -> "N hits, M misses, W writes, X% hit rate [db|in-memory only]"
```

**Scoped per project, not per version** — the hit that matters is the next version
finding a description an earlier one paid for. The whole scope loads in **one
query** at construction and `get()` is a dict lookup; per-entity SELECTs would be
~20k round trips on a 20k-function project. Writes buffer and flush with
`ON CONFLICT DO NOTHING`.

`cache_version` is part of the unique key, so bumping `llm.cacheVersion`
invalidates by construction and leaves old rows unreferenced.

With no database it degrades to an **in-process memo** — still dedupes within a
run (several call sites ask for the same struct during one export), just does not
survive it. `put()` never raises; a cache failure costs LLM calls, never output.

Cache key = `sha256(entity_source + sorted_callee_hashes + str(cache_version))[:16]`.

Dependency tracking is implicit: when function A's source changes, its hash
changes, so its cache misses. When A's callee B changes, B's hash changes,
so A's composite hash (which includes B's hash) also changes, causing A to
miss too. Bumping `llm.cacheVersion` invalidates everything.

### `llm_core.structured_output.extract_and_validate` (version3)

```python
extract_and_validate(raw_response, expected_keys=None) -> Optional[Dict]
```

Robust JSON extraction + repair + schema validation in one function. Handles
markdown fences, trailing commas, single quotes, explanatory text around JSON,
and missing closing braces. Replaces the old ad-hoc `_extract_json()` in
`flowchart/llm/generator.py` and ad-hoc parsing paths in `llm_enrichment.py`.

`parse_label_response(raw)` is the flowchart-specific helper that extracts
a `{node_id: label}` dict from an LLM reply.

### `llm_core.review` — `self_review`, `ensemble_generate` (version3)

```python
self_review(client, draft, evidence) -> str
ensemble_generate(client, system, user, temperatures=[0.0, 0.3, 0.7]) -> str
```

- `self_review` — generate → review → revise cycle. Review prompt asks
  "is this accurate? does it miss behaviours? are side effects listed?".
  Returns an issues list or "OK"; revision happens only if issues are found.
  3 LLM calls worst case. Applied to function descriptions (≥20 non-blank
  lines) and high-visibility summaries when `llm.enrichment.selfReview=true`.
- `ensemble_generate` — 3 temperatures + synthesis call (4 total). Only
  applied to unit / module / project summaries when
  `llm.enrichment.ensemble=true`. Scales to ~80 extra calls for a
  ~20-module project.

Both helpers use `extract_and_validate` when parsing verdicts.

---

## 9. `engine/utils.py` — analyzer-specific helpers

Post-Batch-6, this file is ~360 lines and only owns analyzer-specific logic.
Anything that touches files or env or generic infra has moved into `core.*`.

### Re-exports (back-compat shims)

```python
from core.config import load_config, load_llm_config
```

So legacy `from utils import load_config` still works.

### What lives here

| Function / constant | Purpose |
|---|---|
| `KEY_SEP = "\|"` | Separator for module / unit / function / global keys |
| `log(msg, component, *, err=False)` | Thin wrapper around `core.logging_setup.get_logger` |
| `timed(component)` ctx-mgr | Logs `<elapsed>s` on exit |
| `mmdc_path(project_root)` | Local `node_modules/.bin/mmdc` or system `mmdc` |
| `safe_filename(s)` | Replace spaces with `-`, then `<>:"/\\|?*,&;` with `_` |
| `init_component_mapping(config)` | Build `_COMPONENT_OVERRIDES` from `components` or merged `layers` groups (via `get_flat_groups`) |
| `_resolve_component_from_rel(rel)` | Match relative path against `_COMPONENT_OVERRIDES` (case-insensitive) |
| `make_unit_key(rel_file)` | `component\|unitname` |
| `make_global_key(rel_file, qn)` | `component\|unit\|qualifiedName` |
| `make_function_key(component, rel_file, qn, params)` | `component\|unit\|qualifiedName\|paramTypes` |
| `path_from_unit_rel(rel)` | Strip extension, normalise slashes |
| `short_name(qn)` | Last `::` segment |
| `path_is_under(base, candidate)` | Safe containment via `os.path.relpath` |
| `get_component_name(file_path, base_path)` | Absolute path → component name (uses `_resolve_component_from_rel`) |
| `resolve_group(component)` | Component name → group name (from `_GROUP_MAP` built at import) |
| `norm_path(path, base_path)` | Resolve relative paths against `base_path` |
| `PRIMITIVES` dict | C++ primitive types → range string |
| `get_range_for_type(type_str)` | Map a **known primitive** to a range; anything else `NA`. **Case-sensitive** (2026-08-03) — lowercasing made `Size_t` match `size_t`; `size_t` is matched by exact name, not substring |
| `get_range(type_str, data_dictionary)` | Range lookup with typedef recursion (depth 10). **`"NA"` on a dd entry means "unknown", not an answer** — see below |

Note: `init_component_mapping` runs at import time using the on-disk config, so
`make_*_key` works immediately. `parser.py` builds its own folder list from
the same config via `get_flat_groups` (kept separate to avoid the analyzer's
import order constraints).

### `get_range` resolution order (2026-08-03)

Ranges reaching the interface tables are resolved **lazily here**, not in Phase 1 —
`interface_tables` is the only caller (parameters, `returnRange`, globals). Phase 1
*bakes* a `range` into typedef/struct-field entries with `get_range_for_type()`, which
never sees the dictionary, so an alias of a project type is stored as `"NA"` even when
the underlying type has a range (e.g. one supplied later by the external CSV).

Order, for the direct key hit (`dd[base]` / `dd[base.lower()]`):
1. `range` present and ≠ `"NA"` → return it.
2. `kind == "typedef"`, `underlyingType` set **and ≠ the entry's own name** → recurse
   (depth 10); return the result only if it is not `"NA"`.
3. Otherwise return the entry's own `"NA"` — **do not** fall through to the
   qualifiedName scan.

The qualifiedName scan (reached only when no key matches) applies the same precedence,
and first-match still wins.

Two traps this encodes:
- **Self-referential aliases.** `_maybe_add_typedef_for_struct` stores
  `underlyingType == the type's own name` (`UINT8 → UINT8`), so recursion needs the
  `underlying != base` guard or it burns the depth budget doing O(n) scans.
- **qualifiedName collisions.** The parser emits both `Name` and
  `typedef@Name:file:line` for the same type (Sample: `GG`×4, `Size_t`, `Rect`,
  `Widget_t`, `Mode_t`, `DB_TYPE`, `PUBLIC`). Letting a `"NA"` direct hit fall through
  to the scan lets a *sibling* answer — and the sibling's baked range can be garbage:
  `get_range_for_type` matches `"size_t" in base` on the lowercased name, so the struct
  `Size_t {int width; int height;}` has a sibling carrying `0-0xFFFFFFFFFFFFFFFF`.
  That substring rule is still in `get_range_for_type` (baked into parser output, so
  fixing it needs a re-parse) — see `docs/BACKLOG.md`.

Tests: `tests/unit/test_utils.py::TestGetRangeBakedNA`,
`tests/unit/test_data_dictionary_csv.py`.

---

## 10. Phase 1 — `engine/parser.py`

### Initialization

- Reads `core.config.app_config()` and `clang_config()`.
- Loads libclang from `clang.llvmLibPath`. On Windows, calls
  `os.add_dll_directory(<llvm/bin>)` so dependent DLLs are found, with a
  `PATH`-extension fallback.
- Builds `_FILE_COMPONENT_MAP` via `_build_file_component_map` from merged `layers` groups via `get_flat_groups` (or `components`/`modules` top-level fallback). Component name values are stored normalized (spaces → `-`) so all model keys use the identifier form.
- Reads `model/clang_include_paths.json` (written by `run.py` before any phase)
  and extends `CLANG_ARGS` with `-I<dir>` for every directory in every layer.
- Sets `CLANG_ARGS`:
  - `-std=c++14`
  - `-I<MODULE_BASE_PATH>`, `-I<clangIncludePath>`
  - `-I<every dir from clang_include_paths.json>` (all layer subdirectories)
  - `-DPRIVATE=` `-DPROTECTED=` `-DPUBLIC=` `-D__OVLYINIT=` (visibility macros via `default_clang_macro_defs()`)
  - **Auto-derived layer paths** — reads `model/clang_include_paths.json`
    (written by `run.py` before Phase 1) and appends `-I<dir>` for every
    directory across all layers. No manual listing in `clang.clangArgs` needed
    for directories already declared in `layers` config.
  - Any extras from `config.clang.clangArgs`.
  - **User macros** (`--macros <path>` global, `--macros-layer <layer> <path>` per
    layer, or `clang.macrosFile` / `clang.macrosByLayer` in config) — read by
    `core/macro_input.py` from CSV or any accepted JSON shape, then written to
    `model/clang_macros.json` **scope-keyed** (`{"*": [...], "Layer1": [...]}`) so
    `flowcharts.py` applies the same flags to the Phase 3 re-parser. Args are
    resolved **per TU** by `clang_args_for(path)` (file → component → layer), not
    baked into the global `CLANG_ARGS`. Sample: `engine/config/macros.csv`
    (`VOID,void`).

### Visibility detection (`_detect_visibility`)

Scans **backwards up to 5 source lines** from a declaration line looking for
the first token `PRIVATE`, `PUBLIC`, or `PROTECTED`. Returns the matching
lowercase string or `default`. Required because the visibility macros are
expanded to nothing by `-DPRIVATE=` and Clang doesn't surface them.

### File filtering (`is_project_file`)

Rejects anything outside `MODULE_BASE_PATH` and (when `_COMPONENT_FOLDERS` is
non-empty) anything whose relative path doesn't start with one of the
configured folder prefixes (case-insensitive after `os.path.normcase`).

> **Known risk** — uses `startswith` rather than `path_is_under()`, so
> `C:\foo` and `C:\foobar` would alias. The fix is in `utils.path_is_under`;
> migrating `is_project_file` to use it is open work.

### Three traversal passes (`main`)

1. `parse_file` → `visit_definitions` + `visit_type_definitions` — collects
   functions, globals, and type declarations.
2. `parse_calls` → `visit_calls` — builds `call_graph` (caller → callees) and
   `reverse_call_graph` (callee → callers) by walking `CALL_EXPR` cursors
   inside function bodies. Tries `cursor.referenced` first, falls back to
   name match in known functions.
3. `parse_global_access` → `visit_global_access` — for each function body,
   walks `DECL_REF_EXPR` cursors that point at global `VAR_DECL`s. Distinguishes:
   - Pure write (`=`) → adds to `global_access_writes`
   - Compound op (`+=`, `-=`, …) → both reads and writes
   - `++` / `--` → writes
   - Otherwise → reads
   Uses its own `_visited_global_access_keys` set (separate from `visit_calls`)
   so function bodies are not skipped. When a nested `FUNCTION_DECL` or
   `CXX_METHOD` (e.g. a lambda) is encountered inside an outer function, its
   children are visited under the inner key and any writes are propagated back
   to the outer function's `global_access_writes`.
   Also captures the first `RETURN_STMT` token sequence as `returnExpr`.

### Function collection (`visit_definitions`)

- Cursor kinds: `FUNCTION_DECL`, `CXX_METHOD`. Forward decls are kept with
  `declarationOnly: True`.
- Internal key during collection: mangled name, or `qualified@file:line`.
- Captures `parameters` via `cursor.get_arguments()`, records `extent.end.line`
  as `endLine`.
- Handles `_var_decl_should_record_as_function_not_global` — when Clang emits
  a `VAR_DECL` for `TYPE FuncName(id1)` because a `__OVLYINIT`-style macro
  expanded to nothing, it's reclassified as a function with
  `syntheticFromVarDecl: True` and parameters reconstructed from the
  `DECL_REF_EXPR` children.

### Global variable collection

Only globals at translation-unit or namespace scope (excludes class members).
The initializer value is extracted by scanning the source line for `=`.

### Type collection (`visit_type_definitions`)

Builds `data_dictionary`:
- `STRUCT_DECL` / `CLASS_DECL` with field list
- `ENUM_DECL` with enumerators and computed range
- `TYPEDEF_DECL` with underlying type (`_typedef_underlying`) and range lookup

**`_typedef_underlying(cursor)` (2026-08-03).** `cursor.type` on a `TYPEDEF_DECL` is
the typedef type *itself*, so its spelling is the alias's own name — never what it
aliases. Reading it (the pre-2026-08-03 behaviour) made **every** typedef
self-referential with `range: "NA"`, so every typedef'd parameter printed `NA` in the
Data Range column. Now uses `cursor.underlying_typedef_type`, then strips elaborated
keywords (`struct `/`enum `/`union `/`class `) via `_ELABORATED_RE` so the value works
as a dataDictionary key:

| source | before | after |
|---|---|---|
| `typedef unsigned char UINT8;` | `UINT8` | `unsigned char` |
| `typedef int UNIT;` | `UNIT` | `int` |
| `typedef enum {…} Mode_t;` | `Mode_t` | `Mode_t` (from `enum Mode_t`) |
| `typedef struct {…} Widget_t;` | `Widget_t` | `Widget_t` (from `struct Widget_t`) |

The anonymous enum/struct forms stay self-referential **on purpose** — the unit header
table looks `underlyingType` up in the dictionary to print the enumerator list
(`docx_exporter._build_unit_header_table`, `api/services/doc_render.py:281`), and an
elaborated `"enum Mode_t"` would miss.

`_maybe_add_typedef_for_struct` stores `range: "NA"` rather than
`get_range_for_type(qn)` — its `underlyingType` is the type's own *name*, so deriving a
range from it reads a range out of a type name (`"size_t" in "Size_t"` stamped
`0-0xFFFFFFFFFFFFFFFF` on a `{int width; int height;}` struct).

### Where a data range comes from (precedence, 2026-08-03; layer scoping 2026-08-18)

**Scope is resolved before precedence.** `get_range(type, dd, layer)` first decides *which
entries may answer at all*: the layer's own (`name@<layer>`, or a bare entry stamped with
that layer) and the global tier (`layer: None` — builtins, `PRIMITIVES`, the project-wide
CSV). **Another layer's entry is never eligible**, at any of the three lookup paths. Only
among the eligible entries does the order below apply. `layer=None` disables the filter
entirely, which is what keeps every layer-unaware caller behaving as before.

Highest wins. The order is enforced by *when* each source runs in Phase 1, not by
branching logic:

1. **External CSV** — merged last (`_merge_dd_rows`), so it overrides everything *within its
   scope*. This is why ranges must NOT be frozen onto each parameter in `functions.json`:
   parameters are collected before the merge, and a baked parameter range would make
   `--data-dictionary` unable to override anything.
2. **libclang** — `_range_from_clang_type(ctype)`: `get_canonical()` walks the typedef
   chain to the real builtin, `get_size()` gives its width **for the parsed target**
   (`long` = 4 bytes on Windows, 8 on Linux — the table below cannot express that).
   `VOID` for void, `0-1` for bool, `NA` for structs/enums/pointers/floats.
   `_register_builtin_range(ctype)` runs for every parameter / return type / global /
   field and records the range under the type's **canonical** spelling
   (`unsigned char`, `long`) — never the written spelling, which would let a `UINT8`
   parameter overwrite the `UINT8` *typedef* entry with a primitive one and lose the
   location the unit header table needs. It also refuses to shadow a non-primitive.
3. **`PRIMITIVES` table** — seeded with `setdefault` (not assignment), so it fills gaps
   without overwriting a measured value.
4. **`get_range_for_type(name)`** — last resort for CSV-authored or unparsed types.
5. `NA`.

Consequence: the **dataDictionary is the single registry**; views keep resolving by type
name (`get_range(p["type"], dd)`) and need no libclang, no schema change, and no
`functions.json` churn.

**Coverage log.** `interface_tables.run()` logs one line per group —
`data ranges: 64/65 resolved, 1 NA (int[6] x1)` — via the pure helpers
`_range_coverage` / `_format_range_coverage`. Deliberately a log, **not** a per-entry
`rangeSource` field: nothing renders `directionReason` into the DOCX either, so a
provenance field would ride on every row and churn the snapshot for an audit aid with no
reader. To trace one type, see the precedence above or query `model/dataDictionary.json`
directly.

Tests: `tests/unit/test_typedef_underlying.py`.
- Special pattern: `_maybe_add_typedef_for_struct` adds a typedef entry when
  the source uses `typedef struct { ... } Name;`

### Define scanning (`_scan_defines`)

Plain text scan of every `.cpp`, `.h`, `.hpp` for `#define` lines. Honours
backslash continuation. Stores `name`, `value`, full macro text, and
`location`.

### Direction assignment (`build_metadata`)

Based on direct global access recorded by `visit_global_access`:
- writes any global (including via nested lambda) → `direction = "In"`
- reads globals, writes none → `direction = "Out"`
- no global access → `direction = "Out"` (pure function)

Phase 2 forces every function's direction to `"In"` or `"Out"` (never empty)
and every global to `"In/Out"`.

**Phase 2 direction precedence (roadmap 3.17).** The finalize loop in `model_deriver`
(after `_propagate_global_access`) decides each function's direction by the first rule
that applies — the parser's `build_metadata` value above is only the rule-3 fallback:
1. **Name match.** Tokenize the function's short name into words (camelCase + snake_case
   aware, via `_name_words`/`_WORD_RE`). If a whole word equals `set` → **In** (tested
   first: write intent dominates, mirroring the both-read-and-write → In fallback); else
   if a whole word equals `get` → **Out**. Whole-word matching catches `SetX`/`setX`/
   `Module_SetX`/`coreSetResult` (infix camelCase) while excluding `Setup`/`Settings`/
   `Setter`/`Reset`/`offset`/`target`. Known edge: predicate names like `isSet` match.
2. **Non-void return** (`returnType` present and ≠ `"void"`; `void *` counts as a value)
   → **Out** (data flows out through the return value).
3. **Global-access fallback (the 3.4 rule).** Writes a global directly or transitively
   → **In**; else reads one → **Out**; else **Out** (pure). Reuses
   `writesGlobalIdsTransitive`/`readsGlobalIdsTransitive`.

**`directionReason` (audit trail).** Alongside `direction`, the same loop writes a
human-readable `directionReason` on every function and global so the decision is
verifiable in the interface tables (which surface `f["directionReason"]` as the `reason`
field). Forms:
- `In: function name '<n>' contains 'Set' (writes/updates state).` — rule 1 set.
- `Out: function name '<n>' contains 'Get' (reads/returns state).` — rule 1 get.
- `Out: returns a value (<type>).` — rule 2.
- `In: writes global(s) <names> directly.` — rule 3, direct write.
- `In: writes global(s) transitively: <g> (via <callee(s)>); …` — rule 3, transitive-only
  write; names the direct callee(s) that actually write each global, so the chain
  is auditable.
- `Out: reads global(s) <names> but writes none.` — rule 3.
- `Out: accesses no globals (reads none, writes none).` — rule 3, pure function.
- Globals: `In/Out: global variables are bidirectional interfaces.`

### Final keying (`build_metadata` + `utils.make_function_key`)

Final model key: `component|unit|qualifiedName|paramTypes`.

- `component` from `get_component_name(file_path, base_path)` → `_resolve_component_from_rel`.
- `unit` from filename without extension.
- `qualifiedName` includes namespace + class.
- `paramTypes` is the comma-joined list of normalised parameter type strings.

> **Never change `get_qualified_name`.** Every fid is built from it, so any change re-keys
> the whole model — breaking interface IDs, the fid-keyed hidden-function rows in
> `api/db/json_db.py`, and every incremental baseline. To surface more of a symbol's scope,
> add a separate field (see `className` below), never widen `qualifiedName`.

### `className` — class scope for display (2026-08-08)

Interface tables built every Name cell with `short_name()`, which keeps only the last `::`
segment. `AddOperation::apply` and `MultiplyOperation::apply` — two real methods in unit
`Cross|Dispatch` of SampleCppProject — both rendered as `apply`, indistinguishable.

The class *is* in `qualifiedName`, but that string cannot be split back into namespace vs
class parts (`pos::QosEventManager::_RateLimit` — is `pos` a namespace or an outer class?).
So the class is captured separately at parse time, where the cursor's `semantic_parent`
kinds are still known:

- `parser.get_class_scope(cursor)` — walks `semantic_parent` keeping only `CLASS_DECL`,
  `STRUCT_DECL`, `CLASS_TEMPLATE` and its partial specialization. Namespaces and
  empty-spelling parents are dropped. Nested classes join as `Outer::Inner`; `""` for free
  functions. Stored as `className` on functions and globals.
- `utils.scoped_name(qualifiedName, className)` — the display form, `ClassName::foo`.
  Falls back to `short_name()` when `className` is absent, so models parsed before this
  existed render as they did rather than half-qualified.

**`CLASS_TEMPLATE` is matched here but not by `get_qualified_name`** — a template class's
method therefore has a *bare* `qualifiedName` (`run`, not `Foo::run`), with the class
already lost upstream. `get_class_scope` recovers it, so the rendered name is still
`Foo::run`. Template arguments are not in the spelling, so `Foo<int>::run` and
`Foo<char>::run` both read `Foo::run`; mangled names still keep them apart in the model.

**Where it shows:** interface-table cells, DOCX per-function headings, flowchart table
titles + signatures, behaviour subheaders, and the API's `class_name` field for the hide
list. **Where it does not:** flowchart diagram nodes and behaviour message arrows stay
short — qualifying every arrow re-creates the label crowding the static diagram already
suffers from.

**`name` vs `interfaceName`.** Interface-table entries keep `name` **short**, because
downstream code uses it as a lookup key (flowchart stems, behaviour rows); `interfaceName`
carries the qualified display form. Don't collapse the two.

Three genuine short-name collisions were fixed alongside (wrong-function bugs, not
cosmetics): `doc_render` looked flowcharts up by short name although they are keyed by
`qualifiedName`, so **class methods silently got no flowchart in the web preview**;
behaviour Input/Output labels were resolved by first short-name match within a unit, so
both `apply` sections got the first one's labels; and hiding was matched against a
short-name-per-unit set, so hiding one `apply` suppressed every `apply` in the unit. All
three now key on the fid or `qualifiedName`. Behaviour rows carry `currentFunctionId` and
`currentFunctionDisplay` for this, with the old short-name path kept as a fallback for
artifacts written before those fields existed.

### Address-taken functions are public (2026-08-08)

`_fn_is_private` (`model_deriver.py`) equates "public" with "has a caller in another file".
A layered-firmware entry point reached only through a registration table has
`calledByIds == []`, so it was relabelled `visibility: "private"`, given a `PIF_` id, and
dropped from the interface table (`views/interface_tables.py`) and behaviour diagrams —
missing from the very ASPICE artifact it belongs in. The parser detected **no** address-of-
function usage at all.

**Rule: a function named in a file-scope array/struct initializer is public.**

```c
static const fp_t table[] = { fn1, fn2 };   // detection point
table[0]();                                 // the reason — NOT resolved
```

Which entry `table[0]()` reaches is statically unknowable and is deliberately not resolved
(the long-standing documented limitation stands). Membership in the table is sufficient
evidence on its own.

The rule is by **shape, not by file**: a file-scope initializer counts even when the table
sits in the same `.c` as the function — the canonical firmware pattern, which a cross-file
rule would have missed entirely. An **in-body** take (`p = &helper;`) is different: it
becomes an ordinary `call_graph` edge, so the existing cross-file caller rule applies
unchanged and a locally-used comparator stays private.

- `parser._walk_address_taken(cursor, on_hit, in_callee=False)` — a bare function name used
  as a value is a take; the same name in **callee position** is not. clang wraps a call's
  callee as `CALL_EXPR → UNEXPOSED_EXPR → DECL_REF_EXPR`, so the suppression flag propagates
  through `_CALLEE_WRAPPER_KINDS`. **If it ever stops propagating, every direct call reads
  as an address-take.** The exposure is the file-scope path (which ignores the file rule):
  `static int g = compute();` would wrongly publish `compute`. Guarded by a fixture and a
  test; only *resolved* `referenced` cursors count — never the spelling-match fallback used
  for calls, or any identifier sharing a function's name would qualify.
- Hooked in `visit_definitions` (both the file-scope `VAR_DECL` branch and each function
  body) rather than `visit_calls`, so the rule lives in one place and the call visitor's hot
  loop is untouched. `_get_var_init_value` only slices one declaration line, so a multi-line
  table is invisible to it — the AST walk is what actually sees these.
- `addressTakenByUnits` on the function = the registering unit **plus the units that read
  the table**. The consumers matter more: the table usually lives in the same unit as the
  function it publishes, and `_keep_unit` filters the own unit out of Source/Destination.
  Readers are matched by the global's **qualified name**, not var id, so an `extern`
  redeclaration in the consuming file (its own cursor, its own var id) still resolves.
- `_fn_is_private` gains a third escape clause, ranked **below** the explicit `PRIVATE`
  annotation — a source-level marking stays authoritative.
- Consumed by `interface_tables` (Source/Destination) and `unit_diagrams` (edge).
- Persisted to `model/address_taken.json` (`ADDRESS_TAKEN`, not in `ALL_MODEL_NAMES`) and
  replayed by `incremental/parse_merge._merge_address_taken` + `_apply_address_taken`,
  mirroring `override_pairs`. **Also added to `_PARSE_ARTIFACTS` (`incremental/engine.py`)
  and `_PARSE_SNAPSHOT_FILES` (`incremental/generate.py`)** — miss either and a narrowed
  parse silently demotes the function back to private, so the same source produces a
  different document run to run.

**Known consequence:** `_build_interface_index` numbers public and private separately, so
each function flipped private→public shifts `IF_*_NN` for the rest of its unit. Client docs
cite those IDs; a version diff will show the renumbering.

Fixture: `SampleCppProject/Layer1/Poly/OpsTable.cpp` (table + ops, deliberately plain
`static` not `PRIVATE`, plus an `opsSeed()` call-in-initializer false-positive guard) and
`OpsClient.cpp` (a different unit consuming the table via `extern`). Verified: `opsAdd`/
`opsSub` get `IF_` ids with Source/Destination `Cross/OpsClient`; `opsSeed` stays private.

### External data dictionary merge

After `_scan_defines()` and before writing `dataDictionary.json`, every source in `_dd_sources` is merged by `_merge_dd_rows(path, layer)` (`_merge_external_data_dictionary(path)` is the thin project-wide wrapper the tests drive). Sources in order — **config first, CLI second**, matching the macro block:

1. `layers.<L>.dataDictionary` — config, scoped to that layer
2. `--data-dictionary <path>` — CLI, project-wide
3. `--data-dictionary-layer <layer> <path>` — CLI, repeatable, scoped

**The project-wide dictionary is CLI-only — it has no config key, by design.** Every entry point already passes it as a flag: `run.py` from `--data-dictionary`, and the API/incremental path from `currentDataDictId` → `ws.datadict_path(...)` → `--data-dictionary` (`incremental/generate.py:214`). A config key would be a second, silent source for the same input. Config carries **per-layer** dictionaries only.

A layer's rows never touch another layer's entries: `_dd_target_key()` writes the bare name only when the slot is free or already that layer's, and `name@<layer>` when the global tier or another layer holds it. So "last wins" applies **within one scope only**. In the API/incremental path the project-wide CSV still arrives from `currentDataDictId` → `ws.datadict_path(...)`. Because the merge happens inside Phase 1, these are a **silent no-op with `--from-phase 2+` or `--use-model`**; changing a CSV requires a re-parse.

- Reads a CSV with columns: `Name, Kind, EntryName, Range, Comment`.
- **Top-level rows** (non-empty `Name`): copy existing auto-parsed entry, overwrite `kind`/`range`/`comment` from CSV, reset `enumerators`/`fields` list if the kind uses them.
- **Child rows** (empty `Name`, Kind=`enumerator` or `field`): carry forward the last non-empty `Name` as parent key and append `{name: EntryName, value/range, comment}` to the parent's list. Empty `Name` matches Excel merged-cell CSV exports.
- External entries win on conflict. New entries (not in parsed source) are added as-is.
- `location` and other auto-parsed fields are preserved on updated entries via `dict(existing)` copy.
- A range set here reaches the interface tables through `utils.get_range`, including via an alias whose own range was baked `"NA"` — see [§9 `get_range` resolution order](#get_range-resolution-order-2026-08-03). `fields[].range` inside a struct entry is **re-answered after every CSV** by `_reresolve_struct_field_ranges()` — it is baked during the parse from the canonical clang type, long before the CSV is read, so a `BOOL32` field kept `0-0xFFFFFFFF` while the CSV set the `BOOL32` *type* to `0-1`. Only two cases are re-answered: baked range is `"NA"`, or the field's base type was named by a CSV **visible to that entry's layer** (`_csv_top_level_names`, keyed by layer) — a measured width outranks anything name-derived. Derived spellings (`*`, `&`, `[`, `(`) are skipped unless CSV-named, so a `const char *` keeps `NA` instead of taking a signed-char range from its pointee. The lookup is layer-scoped (`get_range(ftype, dd, entry.layer)`).
- **Merge report** (`_format_csv_merge_report`): after the count, the parser prints which rows landed on a parsed type and which were **new, not found in source**. A typo'd or renamed type name is otherwise silently added as its own entry and looks identical to a successful override. Orphan child rows (no `Name` above them) are counted too, as are **duplicated Names** (last row wins, and the earlier entry's `enumerators`/`fields` are reset out from under it) and **rows dropped for an empty `Name` on a non-child `Kind`** — a merged-cell Excel export becomes a file of these, and they were previously counted in neither `merged` nor the orphan tally. matched-vs-new is decided against a snapshot taken **before** the row loop, so the second row of a duplicated Name cannot see what the first wrote and be mis-filed as a successful override. The function **returns** its lines as well as logging them, so the counting is assertable in tests. The line is prefixed `[<layer>]` for a layer-scoped source.
  ```
  data dictionary: merged 6 entries from data_dictionary.csv
      4 matched a parsed type: DB_TYPE, Status, Color, GG
      2 new, not found in source: MotorSpeed_t, Voltage_t
      1 name(s) appear on more than one row (last row wins): BOOL32
      3 row(s) dropped: empty Name on a row that is not Kind=enumerator/field
  ```

### Outputs

`metadata.json`, `functions.json`, `globalVariables.json`, `dataDictionary.json`
written to `model/` via `core.model_io.write_model_file`.

---

## 11. Phase 2 — `engine/model_deriver.py`

Loads via `core.model_io.load_model(METADATA, FUNCTIONS, GLOBALS)` and exits
with a clear "Run Phase 1 first" message on `ModelFileMissing`.

### `_build_units_components`

Groups all functions and globals by file path. Produces:
- `model/units.json` — one entry per `.cpp/.cc/.cxx` (headers excluded from
  unit keys). Each entry has `name`, `path`, `fileName`, `functionIds` (sorted
  by source line), `globalVariableIds`, `callerUnits` (set), `calleesUnits` (set),
  and `includedHeaders` (read from local `#include` directives).
- `model/components.json` — one entry per component containing its unit keys
  and `headerFiles` list. (Was `model/modules.json` in older versions.)

### `_build_interface_index` / `_enrich_interfaces`

Assigns a per-file sequential index and sets `interfaceId` on each function and global. Rules:

- **Functions are numbered first** (sorted by line), then **globals continue the same counter** — so globals always have higher indices than functions in the same file.
- **Public entries** use prefix `IF_` → `IF_<LAYER>_<GROUP>_<UNIT>_<NN>`
- **Private entries** use prefix `PIF_` → `PIF_<LAYER>_<GROUP>_<UNIT>_<NN>`, numbered in a separate independent sequence (so public IDs have no gaps).
- Private functions/globals are excluded from `output/interface_tables.json` (view filter unchanged).

`<LAYER>` is resolved per entry via `get_component_layer_name(config, component)` and processed by `_id_seg_layer` (keeps uppercase letters **and digits**, so "Layer1" → "LAYER1"). Falls back to `_id_seg(project_name)` for old-style configs without a `layers` key. `<GROUP>`, `<UNIT>` use the existing `_id_seg` (uppercase letters only). Example: `IF_LAYER1_FULL_READWRITE_01`.

**Function privacy rule (call-graph based, `_fn_is_private`):**
A function is private if either condition holds:
1. Its source-level `visibility` is `"private"` (detected by `_detect_visibility` in parser.py), OR
2. None of its `calledByIds` entries belong to a different file — i.e. it has no cross-unit callers (including the case of zero callers).

Explicit `PUBLIC` source annotation does **not** protect a function from being classified private — the call graph is authoritative. Two helpers implement this:
- `_has_external_caller(f, functions_data, base_path)` — returns `True` if any caller lives in a different file.
- `_fn_is_private(f, functions_data, base_path)` — combines the two conditions above.

Globals use the old visibility-only rule (they have no call graph).

Also normalises `parameters` to `[{name, type}]`, dropping any extra fields the parser captured.

### `_propagate_global_access`

Fixed-point: each function's read/write set is unioned with each callee's
sets. Stored as `readsGlobalIdsTransitive` / `writesGlobalIdsTransitive`.
Used by behaviour-name heuristics so a wrapper function can be labelled by
what it ultimately touches.

### `_enrich_behaviour_names` (static heuristics)

**Input name** priority:
1. First parameter name (run through `_readable_label`: strip `g_`/`s_`/`t_`,
   underscores → spaces).
2. First written global name.
3. First read global name.
4. Fallback: `"<FunctionBaseName> input"`.

**Output name** priority:
1. First identifier-looking token of `returnExpr`.
2. Last word of `returnType` if non-primitive.
3. First written global name.
4. First read global name.
5. Fallback: `"<FunctionBaseName> result"`.

`_static_behaviour_name_is_poor` returns True if the name ends with ` input`
or ` result` (i.e. fell through to the fallback) — used to gate the LLM call.

### `_enrich_behaviour_names_llm`

When `config.llm.behaviourNames: true` and the static result is poor: calls
`llm_enrichment.get_behaviour_names(...)` with source, params, globals
read/written, return type, return expression, draft input/output names, and
abbreviations. The unified `LlmClient` runs the request through the
appropriate provider.

### `_enrich_from_llm` (version3 — rich path)

When `config.llm.descriptions: true`:

1. Tries to load `model/knowledge_base.json` (may not exist on first run —
   the rich path still works, just without repo-map / sibling context).
2. Calls **`enrich_functions_rich(functions_data, base_path, config, knowledge=…)`**
   from [engine/llm_enrichment.py](engine/llm_enrichment.py) — the version3
   budget-aware function enrichment path. It:
   - Resolves `max_context_tokens` via `resolve_max_tokens(llm_cfg)`.
   - Builds `ContextBuilder`, `RepoMap`, `FewShotPool`, `EntityCache`.
   - Topologically orders functions (callees first) and skips any that
     already have a source `comment`.
   - **Pass 1 (always)** — bottom-up. Each function sees callee descriptions
     built at this pass. Uses `get_rich_description()` with budget-allocated
     sections: repo_map, function source, callees, types/globals, siblings,
     few_shot, abbreviations.
   - **Pass 2 (when `enrichment.twoPassDescriptions=true`, default true)** —
     re-runs in the same order. Now both callee AND caller descriptions from
     Pass 1 are available. Uses `_get_refined_description()` which compares
     the prior description against caller context.
   - **Self-review (when `enrichment.selfReview=true`)** — for functions with
     ≥20 non-blank lines, runs `_run_self_review()` which wraps
     `llm_core.review.self_review(client, draft, evidence)`. 3 LLM calls
     worst case per reviewed function.
   - Every result goes into `EntityCache` keyed on
     `sha256(source + sorted_callee_hashes + cache_version)[:16]`. Re-runs
     are 10× faster because unchanged functions (and functions whose callees
     are unchanged) hit the cache.
3. Calls **`enrich_globals_rich(...)`** when `enrichment.variableEnrichment=true`
   (default true). This replaces the old one-line declaration prompt with
   rich evidence: declaration + write-site 2–3-line snippets + read-site
   snippets + containing-file summary + related functions. Falls back to
   `enrich_globals_with_descriptions` (the old version2 path) when
   `variableEnrichment=false`.
4. A `ProgressReporter` reports `[idx/total]` progress for every pass.

### Domain anchoring + description blocklist (task 3.14)

Every description prompt — `get_description`, `get_global_description`,
`get_unit_description`, `get_struct_description`, `get_rich_description` —
routes through **`_call_llm(prompt, config, *, system, kind)`** in
[engine/llm_enrichment.py](engine/llm_enrichment.py) with `kind="description"`.
Two guards apply there, and **only** for `kind="description"` (behaviour-name
and other calls are untouched):

- **Domain anchoring (root-cause fix).** `load_domain_context(project_root,
  config)` reads a free-text brief from `config.llm.domainContextPath` (default
  `config/domain.txt`; `#` lines are comments) and `_call_llm` **appends it to
  the `system` message** — so the model is told the codebase's real domain and
  stops inventing unrelated vocabulary. The brief is memoized per path
  (`_get_domain_context`, project root resolved via `core.paths`) so the file is
  read once, not per description. It stacks on top of `get_rich_description`'s
  own `_RICH_DESCRIPTION_SYSTEM`. The shipped `config/domain.txt` describes the
  client's flash-storage firmware (FTL/HIL/FIL layers, explicitly *not*
  audio/video). Per-layer briefs are a future option.
- **Blocklist (deterministic backstop).** `_scrub_blocklist(text, config)`
  strips `config.llm.descriptionBlocklist` words (default `["audio", "video"]`)
  from the returned description — whole-word, case-insensitive, so identifiers
  like `videoDecoderId` are left intact; it also tidies the leftover
  whitespace/punctuation. Empty list = no-op. Stays on permanently even with
  anchoring, as a safety net.

Because both affect output, `llm.cacheVersion` was bumped **1→2** so
previously-cached descriptions regenerate. Offline runs are unaffected —
`_call_llm` returns `""` early when the client is `None`, before either guard.
Tests: [tests/unit/test_llm_scrub.py](tests/unit/test_llm_scrub.py) (14 cases:
scrubber, loader, and prompt-only anchoring assertions).

### `_enrich_with_hierarchy_summaries`

Default-on (disabled by `--no-llm-summarize`). Uses the flowchart engine's
`HierarchySummarizer` (in `engine/flowchart/pkb/`) to produce a 4-level summary:

1. Function level — one-sentence summary for any undocumented function.
2. File level — 2–3 sentences per source file.
3. Module level — 2–3 sentences per module directory.
4. Project level — overall description (prefers a README if present).

The summarizer is fed a `ProjectKnowledge` object built from the parsed
`functions_data` (no extra libclang or scanning). The LLM client is built via
`_build_llm_client_from_config(load_llm_config(config))`, so provider
switching, custom headers, and retries all work.

After the run, `phases` and `comment` fields are written back into
`functions_data` so they're persisted in `functions.json`.

### `_generate_knowledge_base`

Writes `model/knowledge_base.json` in the format the flowchart engine's
`pkb.builder.ProjectKnowledgeBase` consumes:

```jsonc
{
  "functions": { qn: { qualifiedName, signature, file, line, comment, calls[], phases[] } },
  "enums":     { qn: { values: { name: { value, comment } } } },
  "macros":    { name@file:line: { value, text, comment } },
  "typedefs":  { qn: { underlyingType, comment } },
  "structs":   { qn: { fields: [...] } }
}
```

This file is what `views/flowcharts.py` passes to `flowchart_engine.py` via
`--knowledge-json` so the per-function LLM prompts get rich context.

### Final cleanup

- Direction forced to `"In"` or `"Out"` for all functions.
- Globals assigned `direction = "In/Out"`.
- `params` field dropped (replaced by normalised `parameters`).
- All four files (`functions.json`, `globalVariables.json`, `units.json`,
  `modules.json`) plus `summaries.json` and `knowledge_base.json` written via
  `core.model_io.write_model_file`.

---

## 12. Phase 3 — `engine/run_views.py` + `engine/views/`

### Orchestration — [engine/run_views.py](engine/run_views.py)

CLI:
```
python engine/run_views.py [--output-dir <dir>] [--selected-group <name>]
```

Loads model via `core.model_io.load_model(FUNCTIONS, GLOBALS, UNITS, COMPONENTS, optional=[DATA_DICTIONARY])`.

When a group is selected, run_views resolves the name case-insensitively
against `get_flat_groups(config)` and stuffs two extra keys into the config
dict that's passed down into views:

- `_analyzerSelectedGroup` = the resolved group name
- `_analyzerAllowedComponents` = sorted list of component names from that group's entry

It also calls `get_layer_components(config, resolved)` and passes the result to
`_filter_model_to_components(model, layer_comps)` — this filters all four model
dicts (functions/globals/units/components) to only entities in the same layer,
so cross-component call edges within the layer stay visible in the views.

Then it calls `views.run_views(filtered_model, output_dir, model_dir, config)`.

### View dispatch — [engine/views/__init__.py](engine/views/__init__.py)

```python
def run_views(model, output_dir, model_dir, config):
    views_cfg = (config or {}).get("views", {})
    for view_name, run_fn in VIEW_REGISTRY.items():
        default = view_name == "interfaceTables"
        val = views_cfg.get(view_name)
        enabled = default if view_name not in views_cfg else (val is not False)
        if enabled:
            with timed(view_name):
                run_fn(model, output_dir, model_dir, config)
```

`interfaceTables` is the only view enabled by default; the others must be
explicitly configured. Setting any view's value to `false` disables it.

The four view modules are imported at the bottom of `__init__.py` so their
`@register("name")` decorators populate `VIEW_REGISTRY`.

### View 1: `interfaceTables` — [engine/views/interface_tables.py](engine/views/interface_tables.py)

Output: `output/interface_tables.json` (or `output/<group>/interface_tables.json`).
Full logic and column definitions: `docs/spec/SWE3_SPEC.md` — Interface Tables.

- Iterates `.cpp` units only; header-only units skipped.
- Filters by `_analyzerAllowedComponents` if set.
- Includes `PUBLIC` and `PROTECTED` functions and globals; excludes `PRIVATE`.
- Entries sorted by source line number within each unit.
- For each function: builds `callerUnits` / `calleesUnits` (all units including
  same-module). **3.15:** `sourceDest` (rendered as Source/Destination) lists
  **callers only** (external units; `"-"` if none) — each cross-unit relationship is
  documented once, from the provider (callee) unit's row. `calleesUnits` is still
  emitted as a JSON field but no longer feeds `sourceDest`.
- Enriches parameters with `range` from the data dictionary via `get_range()`.
- Function entries also carry `returnType` (verbatim from the model; `""` when
  absent → rendered as `VOID`). Globals have no `returnType`.
- Strips file extensions from `location.file`.
- Columns: Interface ID, Interface Name, Information, Data Type, Data Range,
  Direction (In/Out), Source/Destination, Interface Type.

### View 2: `unitDiagrams` — [engine/views/unit_diagrams.py](engine/views/unit_diagrams.py)

One Mermaid `.mmd` (and optionally `.png`) per unit into
`output/unit_diagrams/`.
Full logic and layout rules: `docs/spec/SWE3_SPEC.md` — Unit Diagrams (REQ-UD-XX).

- `.cpp` units only; filtered by `allowed_modules` when set.
- Layout: partners on the left / right of the **yellow** module box in the centre,
  flowing left-to-right (In-oriented owned interfaces inbound on the left, Out-oriented
  outbound on the right; a mutual partner appears on both sides).
- **3.15:** only edges the unit **owns** (from `calledByIds`, i.e. its callers) are
  drawn; the callee/consumer loop (interfaces this unit *uses*, `callsIds`) is dropped —
  those edges render in the provider unit's own diagram, so every relationship appears
  once model-wide. 3.6 owner-orientation is unchanged; it now operates over the reduced
  (caller-only) edge set.
- The main unit is **blue with a thick border** (`mainUnit` class); sibling units in the module subgraph are blue thin (`internal` class).
- Edges labelled with `interfaceId` values, **blank-line separated** for multi-edge
  (`_edge_label` / `_LABEL_SEP` — see "Edge-label spacing" below).
- Self-calls (callee in the same unit) produce no edge.
- Functions published by a function-pointer table (`addressTakenByUnits`) also draw an
  edge to the registering/consuming unit — they have no caller function, so without it
  the relationship would never be drawn.
- Project root resolved from `dirname(model_dir)` (NOT `output_dir`) so
  grouped output paths work.
- PNG rendered by `mmdc` (mermaid-cli). 60s timeout per diagram.
- Header uses the **ELK renderer** (`%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%`).
  See **"ELK renderer everywhere"** below for the rationale and the version caveats.

#### Edge-label spacing — the ELK options are a no-op here (2026-08-08)

Reported: *"function mapping is difficult to read in the Static Diagram, there is less
space between the lines/labels."* REQ-UD-05 puts every interface id for a unit pair on ONE
arrow, so a busy edge stacks 10+ ids in a single label; joined with a bare `<br/>` they
render as contiguous rows with no leading.

**Measured, do not re-litigate.** Rendering `Sample-Core_Core` (edges of 1 / 10 / 7 ids)
through the pinned mermaid **10.9.5**:

| variant | PNG |
|---|---|
| baseline | 1374 × 700 |
| `elk.spacing.edgeEdge` + `edgeLabel` + `edgeNode` + `nodeNode` + `layered.spacing.*` | **1374 × 700 — byte-identical** |
| blank-line label separator (text only) | 1374 × 1270 |
| both | 1374 × 1270 |

Mermaid 10.9.5 **silently ignores** the `elk.*` spacing options, so no config block was
added — it would be dead weight that reads as if it does something. Spacing lives in the
**graph text**, in `_edge_label(ifaces)`.

**The whitespace goes between GROUPS, not between rows.** ELK lays every edge's label out in
one column, so a uniform blank line between rows still let two arrows' ids run together —
the reader could see each id but not where one arrow's group ended. Ids on the SAME arrow
stay tight (`_ROW_SEP = "<br/>"`) and each label is padded above and below
(`_GROUP_PAD_ROWS = 2`), so Mermaid's grey label background reads as one block per arrow.
Padding rows are a single space; an empty string renders as no row at all.

The blank-line node-padding hack (`n_extra_lines`) was deliberately **left keyed to edge
count**. Re-keying it to label height was tried and rejected: padding of 10 and 18 lines
both rendered byte-identically to none, because once labels are tall the label column —
not the node — sets the height. Only an absurd 36 lines moved it, and that draws the unit
as a grotesque tall bar.

Not changed, per the user: no label splitting (REQ-UD-05 mandates the shared arrow), no id
capping (the diagram stays complete), no DOCX width change, and diagram height is
explicitly not a concern. A `to <partner>` header on each block was tried and **reverted**
(`76fa866` / `fb281cb`) — the ask was spacing, not relabelling.

**Private functions are now skipped when building edges.** `interface_tables.py` skips
`visibility == "private"`, but this view never did, so a function annotated `PRIVATE` in
source that still has cross-unit callers (explicit annotation wins in `_fn_is_private`) drew
an edge labelled with a `PIF_*` id that appears in no table — e.g. `PIF_LAYER1_FULL_
READWRITE_01/02`, `PIF_LAYER1_FULL_POINTRECT_01`, `PIF_LAYER1_FULL_TYPES_01`, all called
from `App|Main`. Table and diagram now agree.

`render_mermaid_cached` is content-addressed on the Mermaid text, so changed text
re-renders automatically; no cache wipe needed.

#### ELK renderer everywhere (2026-07-14)

**All** non-placeholder diagram generators now emit the ELK renderer directive
`%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%`, replacing the older dagre
headers (`splines: 'ortho'` on unit diagrams; `ranksep`/`nodesep` on the three
component diagrams in [src/docx_exporter.py](src/docx_exporter.py)). Flowcharts
([builder.py](src/flowchart/mermaid/builder.py)) were already ELK.

- **Why:** dagre's `splines: 'ortho'` silently fails to route edges orthogonally
  (peripheral edges render diagonal on both mermaid v10 and v11); ELK routes at true 90°.
- **Keep the header minimal** — do NOT copy the flowchart builder's *full* header, whose
  `theme: base` + `themeVariables` override `classDef` fills (nodes go white on v10). The
  one-line `defaultRenderer: elk` directive preserves `classDef` node colours on both versions.
- **Known caveat — inline subgraph `style … fill`** (the unit-diagram yellow module box and
  the component-container yellow box) is **dropped by ELK on mermaid 10.x** (renders default
  purple) but **preserved on 11.x**. Node `classDef` colours survive on both. The component
  container diagram has no edges, so ELK there is purely for consistency.
- **mmdc version caveat for diamonds:** v11's ELK renderer draws diagonal stubs off decision
  diamonds (flowcharts / future behaviour diagrams); **v10 gives clean 90°**. Rectangle-only
  diagrams (unit + component) are unaffected. Net tension: flowcharts want **v10**,
  subgraph-fill styling wants **v11**. The pipeline's [mmdc_path](src/utils.py#L59) prefers the
  local `node_modules` mmdc (pinned to mermaid **10.9.5** via `@mermaid-js/mermaid-cli ^10.6.1`);
  a global mmdc (currently **11.x**) is only used as a fallback when local deps are absent —
  which is what silently changed flowchart rendering. Run `npm ci` before generating.
- Placeholder generators (`behaviour_diagram_generator.py`, `fake_flowchart_generator.py`,
  disabled behaviour-diagram view) were left on plain `flowchart TD` — not real product output.

### View 3: `behaviourDiagram` — [engine/views/behaviour_diagram.py](engine/views/behaviour_diagram.py)

Generates one `.mmd` per (current function, external caller) pair via
`SequenceDiagramGenerator` in the
[engine/behaviour_diagram/](engine/behaviour_diagram/) package.

> **behaviour diagram package replaced — 2026-08-22** (branch `fix/behaviour-diagram`, off `poc-4`; commit
> `9a22f0c` = the transcribed drop-in, later fixes uncommitted). All 7 modules (`generator`, `selector`,
> `tracer`, `mermaid_builder`, `llm_call_description`, `cli`, `utils`) were replaced wholesale with an
> external version; `__init__.py` was left as-is and still matches. What changed that callers care about:
> **(1) `filterMode` is now consumed** — `_get_filter_mode` reads `views.sequenceDiagrams.filterMode`,
> `create_diagram_selector` maps it to one of 5 selector classes. **Default changed** from the old
> `default`→`AllExternalCallersDiagramSelector` to **`skip_within_unit`**, which emits a diagram only when
> the target's own component spans 2+ units. On `SampleCppProject` (3 units, 3 separate components) that
> means **0 diagrams by default** where the old code produced 11 — verified, not theoretical. The old mode
> vocabulary (`all_external_callers`, `single_external_module`, `single_function`, `multi_unit_function`,
> `default`) is **gone**; those strings now fall through to `skip_within_unit` silently.
> **(2) `generate_all_diagrams` return shape changed** `List[str]` → `List[List[str]]` (one description
> list per diagram). This **fixes a silent docx bug**: `_add_behavior_description_table` guards on
> `isinstance(..., list)`, so the old string made the Requirements cell render **empty** in every Dynamic
> Behaviour table. **(3) `skip_within_unit` bridges** — `tracer.trace_forward_within_component` threads an
> `origin` arg so a skipped intra-unit hop re-attributes the downstream cross-unit edge to the last real
> boundary instead of orphaning it. The reachability filter in `generate_diagram_for_caller` is now
> redundant (its own comment says so) and prunes nothing.
> **(4) LLM path rewired to `llm_core`** — the transcribed code imported `_ollama_available` / `_call_llm`
> from `llm_client`, a module deleted in the version2→version3 refactor (it was `src/llm_client.py`, renamed
> to `engine/llm_enrichment.py`; `_ollama_available`→`llm_provider_reachable`, `_call_ollama`→`_call_llm`).
> Both imports failed → `except ImportError` → every description silently fell back to `"X calls Y"`.
> `CallDescriptionGenerator` now builds a real `LlmClient` via `from_config(load_llm_config(config))` into
> the `self._llm_client` field the code already declared but never used, gates on
> `llm.descriptions and llm_provider_reachable(...)` (same pattern as `docx_exporter.py:404`), calls
> `.generate()` inside `tokens.stage("behaviour.call_description")` so calls appear in the LLM report, and
> passes `_get_domain_context(config)` as the system prompt for Task 3.14 anchoring. `except ImportError`
> widened to `except Exception` — `llm_provider_reachable` **raises** `LlmConfigError` on a config missing
> `llm.defaultModel`, which would otherwise kill the whole view.
> **(5) A behaviour description is *call*-specific and is NOT the callee's function description.** Both the
> old code and an interim fix here used `functions_data[calleeFn]["description"]` as a fallback; that is
> wrong — it answers "what is this function" where the table asks "why does this caller call it", and the
> docx already prints the function description at `docx_exporter.py:1072/1143/1726`. Fallback chain is now
> **LLM call-description → `"X calls Y"`**, both call-shaped.
> **Bugs fixed in the transcribed code** (it did not run as delivered): `generator.py:322` joined unit ids
> with `_` while `mermaid_builder.py:247` splits on `/` → `IndexError` in **all 5 modes**;
> `generator.get_selection_summary` never returned `summary`; `SkipWithinUnitDiagramSelector.get_selection_summary`
> called `_get_units_in_call_chain`, which only exists on `MultiUnitFunctionDiagramSelector`.
> **Tests:** [tests/unit/test_behaviour_diagram_package.py](tests/unit/test_behaviour_diagram_package.py) —
> 19 tests, the package's first coverage. Mutation-checked: reintroducing the `_`/`/` bug fails 12 of 19.
> Note `tests/unit/test_behaviour_diagram_generator.py`, described in the test-inventory table below, **does
> not exist** — that row is stale.
> **Known gap:** `generator.py` was transcribed from screenshots that ended at line 460; the closing
> `return summary` is reconstructed, and anything after it is unknown.

- Filtered to `allowed_modules` (only generates diagrams for functions inside
  the selected group, but uses the full model so external callers outside the
  group are still discovered).
- Excludes `private` functions.
- Filename: `current_key__caller_key.mmd` (sanitized via `safe_filename`).
- Each `.mmd` currently contains a fixed sample Mermaid string (placeholder).
- Renders to PNG via `mmdc` with the puppeteer config when present.
- Writes `output/behaviour_diagrams/_behaviour_pngs.json`:

```jsonc
{
  "_docxRows": {
    "<module>": {
      "<unit>": [
        { "currentFunctionName": "...", "externalUnitFunction": "...", "pngPath": "..." }
      ]
    }
  }
}
```

This file is what `docx_exporter.py` reads to build the Dynamic Behaviour
section.

### View 4: `flowcharts` — [engine/views/flowcharts.py](engine/views/flowcharts.py)

Wraps the **real flowchart engine** under `engine/flowchart/`. Steps:

1. Resolves `out_dir = output_dir/flowcharts/`.
2. Builds clang args in three layers (in order):
   - Manual `clang.clangArgs` from config (if set).
   - `-I<basePath>` from `metadata.json` (always added).
   - **Layer-scoped paths** from `model/clang_include_paths.json` via
     `_resolve_layer_dirs(config, group_name, layer_paths)`: when a group is
     selected, only the dirs belonging to that group's layer are added (e.g.
     group "Sample" → Layer1 dirs only). When no group is selected, dirs from
     all layers are added. This prevents headers from unrelated layers
     polluting the include path for a single-group run.
3. If a group is selected, **filters `functions.json` by module-prefix** and
   writes `model/functions_<group>.json`. The filtered file is passed to the
   engine instead of the full one. (Module-prefix filtering, not units.json
   traversal — see Risk 2 in §16.)
4. Builds the engine command:
   ```
   python engine/flowchart/flowchart_engine.py
       --interface-json <functions[_group].json>
       --metaData-json  model/metadata.json
       --std            c++14
       --out-dir        output/flowcharts
       --llm-url        <baseUrl>/api/generate
       --llm-model      <defaultModel>
       --llm-num-ctx    <numCtx>
       [--knowledge-json model/knowledge_base.json]
       [--clang-arg=... ]+
   ```
5. Runs the subprocess with `cwd=project_root`. Logs full argv on launch.
6. When `renderPng: true`, walks every per-unit JSON in `out_dir`, writes a
   temp `.mmd` per `(unit, function)`, calls `mmdc` (with puppeteer config if
   present), captures the PNG to `<unit>_<func>.png`, deletes the temp file.
   Progress is reported via `core.progress.ProgressReporter`.

---

## 13. The flowchart engine — `engine/flowchart/`

A self-contained C++ → Graphviz **DOT** CFG generator (switched from Mermaid
2026-07-27; the `FlowchartResult.mermaid_script` field name is kept for schema
compat but carries DOT). Invoked as a subprocess by the `flowcharts` view but
can also run standalone.

### Label policy (2026-08-10)

**A label is descriptive prose that names every function the node calls, each
written `Name()` with arguments stripped.** Held constant: the content (every
call present, uniform `Name()` form). Not constant: the phrasing — the name
goes where the code puts it, because `via X()` misattributes the action
whenever the callee only supplies an object rather than performing the work.

| C++ shape | What the call does | Label |
|---|---|---|
| `sz = functionJ();` | supplies a value | Get somethingZ by calling `functionJ()` |
| `functionX()->timeSlot = False;` | supplies the object written | Set the time slot in `functionX()` to False |
| `sa = &functionA()->sa;` | supplies the object read | Update sa with the address of sa in `functionA()` |
| `ServerReplicate(part, id);` | **is** the action | Replicate partition state with `ServerReplicate()` |

Enforced in three places that must agree, all keyed off
[cpp_tokens.py](engine/flowchart/cpp_tokens.py): the enricher declares
`call_names`, the prompt requires every one of them, and
`enforce_call_names` verifies/repairs afterwards. **Not named** (each has its
own prompt rule): logging macros, assertions, casts, constructors.

### Subpackage layout

```
engine/flowchart/
  flowchart_engine.py        Main entry, orchestrates per-function pipeline
  project_scanner.py         Standalone scanner that builds project_knowledge.json
  config.py                  EngineConfig dataclass (CLI defaults)
  cpp_tokens.py              Single definition of "a call": CPP_KEYWORDS,
                             extract_call_names / render_call / short_name
  models.py                  CfgNode / CfgEdge / ControlFlowGraph / FunctionEntry / …
  ast_engine/
    parser.py                SourceExtractor + TranslationUnitParser
    cfg_builder.py           libclang AST → ControlFlowGraph (handles ASSERT, goto/label, switch/break)
    resolver.py              find_function_cursor — resolve qn+location to a cursor
  pkb/
    builder.py               ProjectKnowledgeBase (in-memory index, BFS callee context)
    knowledge.py             ProjectKnowledge dataclass + load/save
    cache.py                 PkbCache (disk cache keyed by functions.json hash)
  enrichment/
    enricher.py              NodeEnricher — attach PKB context to CFG nodes
  llm/
    prompts.py               SYSTEM_PROMPT + build_user_prompt
    generator.py             LabelGenerator — batched LLM labeling with auto-halving
  mermaid/
    builder.py               build_mermaid(cfg) → Mermaid string
    normalizer.py            label sanitisation
    validator.py             validate_cfg + validate_mermaid
  output/
    writer.py                Per-file JSON output + _summary.json
  tests/
    test_cfg_topo.py         CFG topology asserts
    diagnose_assert.py       Repro for the ASSERT-pollutes-CFG bug
```

### Per-function pipeline (`_process_function`)

1. **Source extraction** — `SourceExtractor.extract_by_lines(file, line, end_line)`
   reads the function body text by line range.
2. **TU parse** — `TranslationUnitParser.get_tu_full(abs_path)` parses the
   file with bodies (cached per-file).
3. **Cursor resolution** — `find_function_cursor(tu, func_entry, abs_path)`.
   Strategy 1 is direct position lookup using `loc.file.name == abs_path`;
   fallback strategies use qualified name + line range.
4. **CFG build** — `CFGBuilder.build(func_cursor, func_entry)`. Walks AST
   traversal that distinguishes statement nodes (`IF_STMT`, `FOR_STMT`,
   `WHILE_STMT`, `DO_STMT`, `CXX_FOR_RANGE_STMT`, `SWITCH_STMT`, `RETURN_STMT`,
   `BREAK_STMT`, `CONTINUE_STMT`, `CXX_TRY_STMT`, `GOTO_STMT`, `LABEL_STMT`)
   from sequential statement segments. Rules are absolute:
   - structural truth comes only from the AST (no heuristics)
   - loop back-edges are explicit
   - `break` → after-loop / after-switch
   - `continue` → loop head
   - `return` → END node
   - all open exits connect to the next sequential node
5. **ASSERT filtering** — `_collect_assert_locations(src_lines)` pre-builds a
   `frozenset` of `(line, col)` pairs by regex-scanning source for assert
   macro calls (`ASSERT(`, `static_assert(`, `(?:[A-Z][A-Z0-9_]*_)*ASSERT(`).
   The CFG traversal then does O(1) lookups against
   `cursor.extent.start.line/.column` (NOT `get_expansion_location()`, which
   was the original bug source) and skips ASSERTs so they don't pollute the
   diagram. **Do not modify this code without re-running
   `tests/diagnose_assert.py`** — the linter has previously reverted this fix.
6. **Enrichment** — `NodeEnricher.enrich(cfg, func_entry)` attaches PKB
   context (callee descriptions, type meanings, project-knowledge comments).
   Also emits **`call_names`** — every call in the node via
   `cpp_tokens.extract_call_names`, in source order, receiver kept
   (`doc.AddMember`), with known type names excluded so constructors don't
   register as calls. This is the list the label naming rule is written
   against; `function_calls` is a PKB-resolved subset capped at 3 and carries
   descriptions only.
7. **Optional CFG simplification** (version3) — if
   `llm.enrichment.cfgSimplification=true` and the CFG has >15 labelable
   nodes, `LabelGenerator._simplify_cfg()` asks the LLM for a merge/drop
   plan: `{"merge": [["N3","N4"], ["N7","N8","N9"]], "drop": ["N12"]}`.
   Safety constraints enforced AFTER the LLM replies (regardless of what it
   proposed):
   - Only merges **strict linear chains**: each inner node has exactly one
     predecessor (= its prev-in-group) and one successor (= its next-in-group).
     `_is_linear_chain()` verifies this on the live `cfg.edges`.
   - Only drops nodes with one incoming and one outgoing edge
     (`_has_single_in_single_out`). Merges are capped at 2–4 nodes per group.
   - Only touches `NodeType.ACTION` — decisions, loops, switches, returns,
     breaks, continues, and case nodes are never offered to the LLM and
     never mutated.
   - Uses `extract_and_validate()` to parse the JSON plan.
8. **LLM labeling** — `LabelGenerator.label_cfg(cfg, func_entry, source, base)`
   batches up to `BATCH_SIZE=4` nodes per LLM call. Two failure modes are
   handled differently:
   - Empty response (`raw=None`, prompt > num_ctx) → retry **without** any
     "retry note" (would inflate the prompt). After all retries fail, the
     batch is auto-halved and recursed up to depth 3. This adapts to any
     model's actual context window without manual tuning.
   - Bad JSON / missing nodes → append a targeted retry note with the failing
     `node_id`s so the LLM can correct precisely.
   Version3: JSON parsing routes through `llm_core.structured_output.parse_label_response()`
   which handles markdown fences, trailing commas, single quotes, and
   partial/missing braces — significantly fewer fallback labels than the
   version2 ad-hoc `_extract_json()` path. `MAX_PROMPT_CHARS=6000` stays as
   a legacy-standalone fallback only; the coherence pass now sizes via
   `ContextBudget(task="cfg_coherence")` when `max_context_tokens` is
   threaded in (it is, from `flowchart_engine.py`).
9. **Coherence pass** — `_coherence_pass()` normalises terminology and
   phrasing across all labels in one LLM call. Version3: prompt strengthened
   (inconsistent terminology, passive voice, too-literal vs. too-abstract
   labels, decision nodes without "?"). Sized via
   `_fits_coherence_budget()` using the authoritative
   `self._max_context_tokens` — no more `getattr(client, "_num_ctx", 8192)`
   fallback.
9b. **Call-name enforcement** — `generator.enforce_call_names(cfg)`,
    deterministic, no LLM. Runs **last**, after the coherence pass, so a
    coherence rewrite can't strip a name back out. Two steps per node:
    normalise existing mentions to `Name()` (arguments stripped, bare
    identifiers parenthesised), then append names with no mention at all as a
    trailing `<br/>Calls: X()` segment. The appended form is deliberately not
    a connector phrase — the pass can't know where the name belongs in the
    sentence, and inventing one produces the mechanical "… via X()" filler the
    prompt forbids. **Prose safety:** a bare word is only converted when
    `_is_identifier_shaped` says it can't be English (qualified/member,
    snake_case, or an internal capital), otherwise "Validate the request"
    becomes "Validate() the request"; ambiguous bare words count as absent and
    are appended instead. Also normalises the raw-C++ fallback labels
    (`result = add(result, a)` → `result = add()`). A per-function append count
    is logged — a high count means the prompt isn't landing, which is the thing
    to fix, not this pass.
10. **Validation** — `validate_cfg(cfg)` then `validate_mermaid(script)`.
    Failures are logged at WARNING but don't abort the run.
11. **Build DOT** — `build_dot(cfg)`. (`_escape` turns `<br/>` into the DOT
    line-break sequence, which is how the enforcement pass's appended segment
    renders.)

### `LIBCLANG_PATH` env var (feat/test-framework)

At import time, `flowchart_engine.py` checks `os.environ["LIBCLANG_PATH"]`.
If set (and the path is a file), it calls
`clang.cindex.Config.set_library_file(path)` before any libclang call.
`run.py` sets this env var from `clang.llvmLibPath` in config so the value
propagates automatically into the flowchart engine subprocess.

### LLM client construction + banner + enrichment config (version3)

At the top of `run()`, [engine/flowchart/flowchart_engine.py](engine/flowchart/flowchart_engine.py)
calls `_load_analyzer_llm_config()` which walks `cwd` and one parent for
`engine/config/config.defaults.json`, loads it with `utils.load_config`, then resolves it
strictly with `utils.load_llm_config` (raising `LlmConfigError` with the
specific failing field on any invalid input). The resolved llm_cfg is
displayed via `format_llm_config_banner()` before any real work begins, so
the subprocess is self-documenting.

`_build_llm_client(config, llm_cfg_resolved)` then builds the `LlmClient`:
- When the analyzer config is reachable: `llm_core.client.from_config(llm_cfg)` —
  provider, custom headers, retries, and API key all flow through. CLI
  `--llm-num-ctx` still wins if it is explicitly larger than the config
  value (useful for one-off standalone invocations).
- When running outside the analyzer tree: falls back to the legacy
  positional constructor (Ollama only, backwards compatible).

The `LabelGenerator` is constructed with two version3 parameters threaded
from the resolved config:
- `enrichment_config=llm_cfg["enrichment"]` — feature flags.
- `max_context_tokens=resolve_max_tokens(llm_cfg)` — authoritative
  budget used by the coherence pass and CFG simplification pass. This
  replaces the old `getattr(client, "_num_ctx", 8192)` fallback.

A log line `Coherence/simplify budget = N tokens (provider=…)` is printed
right after the banner.

### PKB caching

`pkb.cache.PkbCache` keys on the SHA of `functions.json` text. If unchanged,
the in-memory PKB is restored from disk under `.flowchart_cache/`. Pass
`--no-cache` to force rebuild.

### project_scanner.py (separate tool)

A standalone scanner that walks every C++ source file under `--project-dir`
with libclang and writes a richer `project_knowledge.json`: function
signatures + Doxygen comments + call graph + enum definitions with per-value
comments + `#define`s with values + typedefs + struct member fields. With
`--llm-summarize`, also runs the 4-level hierarchy summarization.

This tool is **not** in the standard run.py pipeline — it's used to bootstrap
a richer knowledge base for projects where the analyzer's `model_deriver`
output isn't enough. The flowchart engine accepts either kind of knowledge
file via `--knowledge-json`.

### Outputs

Per source file: `out_dir/<source_file_name>.json` containing
`[{name, flowchart}, …]`. Plus `_summary.json` with per-file counts.

---

## 14. Phase 4 — `engine/docx_exporter.py`

### Entry: `export_docx(json_path, docx_path, selected_group)`

- `json_path` defaults to `output/interface_tables.json`.
- `artifacts_dir = os.path.dirname(json_path)` — every PNG path, every
  flowchart JSON, every behaviour-pngs file is resolved relative to this.
  This is the critical fix for grouped output (`output/<group>/`).
- Loads `model/functions.json`, `globalVariables.json`, `units.json`,
  `dataDictionary.json`.
- Loads abbreviations from `config.llm.abbreviationsPath`.
- Iterates modules in sorted order.

### Function hiding (Phase 4 only, no Phase 3 needed)

Functions can be hidden from DOCX output without re-running Phase 3.
The `hidden` flag lives in `model/functions.json` per function entry:
`{"hidden": true, ...}`. It is set via the UI (§14b) and never written
by any pipeline phase.

At the top of `export_docx`, after loading `functions_data`:
- `_hidden_fids` — set of all fids where `hidden == True`.
- `_hidden_by_mod_unit` — `(module, unit) → set of base function names`,
  built from `_hidden_fids` for the Dynamic Behaviour lookup.

What is filtered in Phase 4:

| Output | Filtered? |
|---|---|
| Interface table entries | ✅ fid not in `_hidden_fids` |
| Per-function DOCX section + its flowchart | ✅ iface excluded before loop |
| Private callee flowcharts | ✅ callee_fid not in `_hidden_fids` |
| Dynamic Behaviour entries | ✅ currentFunctionName in `_hidden_by_mod_unit` |
| Component/Unit description table | ✅ uses already-filtered interfaces |
| Unit diagram PNG | ❌ pre-rendered in Phase 3 |
| Behaviour diagram PNG | ❌ pre-rendered in Phase 3 |
| Module container/header PNG | ❌ pre-rendered in Phase 3 |

Pre-rendered PNGs from Phase 3 are embedded as-is — they still show
hidden functions as nodes. Only text sections are filterable in Phase 4.

### CLI

```
python engine/docx_exporter.py [json_path] [docx_path] [--selected-group <name>]
```

`--selected-group` is stripped before positional parsing.

### Cover page (`_build_cover_page`)

Rendered as the first page before the TOC. Layout (top → bottom):

- **Project name** — 54 pt, bold, navy (`#1E3C78`), thick double underline, right-aligned. Read from `model/metadata.json → projectName`.
- **Subtitle** — `"Software Detailed Design Specification  —  <group>"` (16 pt bold navy, right-aligned). Group label: `selected_group` with `-`→space, or joined `selected_components`, or `"All Components"`.
- **Version** — `"Version 1.0.0"` (12 pt, right-aligned). Hardcoded default; override via `_build_cover_page(..., version=...)`.
- **Date** — `YYYY-MM-DD` of export run (12 pt, right-aligned).
- **Copyright image** — `assets/copyright.png`, 2.6 in wide, left-aligned. Falls back to plain text if file missing.
- **Copyright text** — one line below the image, 8 pt, gray (`#808080`), left-aligned. Defaults to `"© <year> All Rights Reserved."`. Override via `config.docx.copyrightText`.
- **Bottom arc** — `assets/bottom_arc.png`, full body width, centered. Omitted if file missing.
- Page break added after cover before TOC.

**OOXML note:** `w:spacing` must appear before `w:jc` in `w:pPr` — Word silently ignores alignment if order is wrong. Both XML manipulation and `para.alignment` API are set together as belt-and-suspenders.

### DOCX section structure

```
[Cover page — see above]
[Table of Contents — _add_toc(); field ' TOC \o "1-4" \h \z \u '; covers Headings 1-4;
 w:updateFields=true auto-updates on open; placeholder text shown until field is refreshed]
1 Introduction                                                 (Heading 1)
  1.1 Purpose   — text from config.docx.introduction.purpose
  1.2 Scope     — scopeIntro text, then component names (• bullet each),
                  then scopeBody text, then scopeItems (- dash each)
                  (config.docx.introduction.scopeIntro/scopeBody/scopeItems)
  1.3 Terms, Abbreviations and Definitions
2 <ModuleName>                                                 (Heading 1)
  2.1 Static Design                                            (Heading 2)
    [Module container diagram — light-yellow subgraph box, blue unit nodes inside (TB)]
    [Horizontal rule]
    [Header dependency diagram — BT flowchart, header nodes at top, source nodes below]
    [Component / Unit table — Component | Unit | Description | Note]
    2.1.1 <UnitName>                                           (Heading 3)
      [Unit diagram PNG if available]
      2.1.1.1 unit header                                      (Heading 4)
        Path: <path/without/extension>
        [Unit header table — globals/typedef/enum/define | information]
      2.1.1.2 unit interface                                   (Heading 4)
        [Interface table — 8 cols, see below]
      2.1.1.3 <UnitName>-<FuncName>                            (Heading 4)
        [Flowchart table — 5 rows, see below]
      ... one Heading-4 sub-section per **function** (globals excluded) ...
  2.2 Dynamic Behaviour                                        (Heading 2)
    2.2.1 <UnitName> - <FuncName> (<ExternalUnitFunc>)         (Heading 3)
      [Behaviour description table]
      [Behaviour PNG if rendered]
N Code Metrics, Coding Rule, Test Coverage                     (Heading 1)
Appendix A. Design Guideline                                   (Heading 1)
```

### Module container diagram (`_build_module_container_mermaid`)

Mermaid TB `subgraph` — light-yellow container (`fill:#fef9c3, stroke:#fbbf24`)
holding all unit nodes as blue boxes (`fill:#2563eb`). Rendered into
`artifacts_dir/module_container_diagrams/<module>.png` at 6 inches wide.
Appears first under `{N}.1 Static Design`, followed by a horizontal rule.

### Header dependency diagram (`_build_module_header_dependency_mermaid`)

Mermaid BT flowchart (no outer box): header nodes at top (dark, `fill:#1e293b`),
source file nodes at bottom (blue, `fill:#2563eb`), edges `source → header`.
Node labels strip extensions — headers show `<name>\nHeader`, sources show `<name>`.
Only same-module headers are shown; folder prefix is derived from unit paths
(not module name, since config module name ≠ filesystem folder). Rendered into
`artifacts_dir/module_header_dependency_diagrams/<module>.png` at 6 inches wide.
Appears after the horizontal rule, before the Component/Unit table.
`includedHeaders` field populated in `units.json` by `model_deriver._read_local_includes`
during Phase 2 — re-run from Phase 2 after any source tree changes.

### Component/Unit table (`_add_component_unit_table`)

4 columns: Component | Unit | Description | Note

Description derivation:
1. If LLM available → `llm_enrichment.get_unit_description(unit_name, fn_items, gv_items, config, abbreviations)` produces a summary (≤25 words).
2. Fallback → join all function/global descriptions, truncate to 120 chars.
3. Final result truncated to **140 chars max** (hardcoded).
4. Note column is always `N/A`.

The Component column is merged vertically across all unit rows of a module.

### Unit header table (`_build_unit_header_table`)

2 columns: `global variables / typedef / enum / define` | `information`

Rows from:
- **Globals** (`globalVariables.json`) — private excluded, declaration read
  from source line, value from `initializer`.
- **Typedefs** (`dataDictionary`) — declaration snippet from source; info
  column shows enum values for typedef-to-enum, struct description for
  typedef-to-struct, else `NA`. Multiple aliases from the same declaration
  (`typedef struct {…} one_s, *one_s_2;`) are suppressed: libclang stores
  each alias as a separate `TYPEDEF_DECL` at the line where the alias name
  appears (e.g. `} one_s, *one_s_2;`), so `_read_decl_snippet` returns
  `"-"` for those entries (line doesn't start with `typedef`). Any typedef
  whose snippet is `"-"` is skipped entirely — the full declaration is
  always emitted by the entry at the actual `typedef struct` line.
- **Enums** — declaration snippet; info column is `NAME=value, …`.
- **Defines** — full macro text; info column is the value. Include guards
  (`#define __FILE_NAME_H__` — empty value, name matches
  `^_*[A-Z][A-Z0-9_]*(?:_H|_HPP)_*$`) are skipped.

Struct/class entries are NOT shown directly — only via `typedef struct {…}
Name;`. Deduplicates by declaration text, preferring richer `name=value` info.

### Interface table (`_add_interface_table`)

8 columns: Interface ID | Interface Name | Information | Data Type |
Data Range | Direction(In/Out) | Source/Destination | Interface Type

- Functions: `Data Type` = `; `.join of param types (or `VOID` if none), then a
  second line `return: <returnType>`. `void` (any casing) is displayed as `VOID`;
  other types render verbatim. `Data Range` = `; `.join of param ranges from
  `get_range()`, then a second line `return: <returnRange>` where `returnRange` is
  `get_range(returnType)` (the view enriches each function entry with `returnRange`;
  a void return shows range `NA`, not a range value). When a function has **no** captured return type the
  `return:` line is omitted from both columns (not shown as `VOID`/`NA`). The `\n`
  renders as a Word line break in DOCX and needs `whitespace-pre-line` on the web
  cell (`DocumentInspectorPage.tsx`); the compare/diff view flattens it to a space
  via `_table_to_markdown`. Return type is captured verbatim from Clang's canonical
  spelling (`parser.py` unchanged — a `VOID` **macro** resolves to `void` via
  `--macros`, then the renderer uppercases it back to `VOID`).
- Globals: `Data Type` = variable type; `Data Range` from data dictionary.
- Private functions/globals are already filtered out by Phase 3.
- `Interface Name` is generated by `_readable_label(qn)` (strip prefixes,
  underscores → spaces).

### Flowchart table per interface (`_add_flowchart_table`)

The per-interface loop (`2.1.1.3`, `2.1.1.4`, …) iterates **functions only**
— global variable entries are excluded from this loop even though they appear
in the interface table above. Globals have no flowchart section.

5-row table: Requirements | Risk | Capacity(Density) | Input Name | Output Name

Requirements cell contains:
1. Function description (or function name as fallback).
2. The function's own flowchart (PNG if available, else Mermaid text)
   labelled with the signature `returnType functionName(params)`.
3. Each **private callee's** flowchart labelled with its signature, deduped
   per unit via a `rendered_private_fids` set so the same private helper isn't
   embedded twice.

Input/Output Name = `behaviourInputName` / `behaviourOutputName` from
`functions.json`. Risk = `"Medium"` (hardcoded). Capacity(Density) =
`"Common"` (hardcoded).

### Dynamic Behaviour section

Reads `artifacts_dir/behaviour_diagrams/_behaviour_pngs.json`. For every
`(module, unit, [{currentFunctionName, externalUnitFunction, pngPath}])`:
- Heading: `<sec>.2.<idx> <unitName> - <functionName> (<externalUnitFunction>)`
- Behaviour description table (`_add_behavior_description_table`) with input/output names from the model.
- Embedded PNG if `pngPath` is non-empty and exists.

---

## 15. Test fixture — `SampleCppProject/`

`SampleCppProject/` is **vendored directly in this repo** — committed as normal tracked
files, so a plain `git clone` has the full fixture (no submodule, no `git submodule update
--init`, no empty folder). It is the single source of truth for the fixture. It was briefly
a git submodule → `github.com/manojksarkar/SampleCppProject`; that standalone repo is now
abandoned and the analyzer no longer depends on it. The incremental-diff **unit tests build
their own throwaway git repos** in a temp dir, so they don't need any external fixture repo;
for a manual incremental-UI demo, onboard the analyzer repo's own URL (a shallow, single-
branch clone) rather than maintaining a separate sample repo.

The old `test_cpp_project/` fixture is superseded. Current fixture (matches
`config.defaults.json` `layers`):

```
SampleCppProject/
  Layer1/
    Access/   AccessVisibility.cpp/.h  — PRIVATE/PUBLIC/PROTECTED macros
    App/      Main.cpp                 — top-level entry
    Diag/     ForwardVoidDecl, MultilineOvlyinit, PreprocIf*, VoidAsVar,
              VoidIsVoid               — synthetic-from-VAR_DECL recovery cases
    Direction/ ReadWrite.cpp/.h        — In/Out direction from globals
    Flow/     Flowcharts.cpp/.h        — control-flow patterns (if/else, switch, loops)
    Hub/      Hub.cpp/.h               — cross-component fan-out
    Math/     Utils.cpp/.h             — small math helpers
    Outer/Inner/ Helper.cpp/.h         — nested-directory component path
    Poly/     Dispatch.cpp/.h          — virtual dispatch / polymorphism
    Sample/
      Core/   Core.cpp/.h              — Sample group, Core component
      Lib/    Lib.cpp/.h               — Sample group, Lib component
      Util/   Util.cpp/.h              — Sample group, Util component
    Types/    PointRect.cpp/.h, Types.cpp/.h — struct + union types, enum/typedef
  Layer2/
    Platform/                          — 15 stub platform components (3-5 files each)
      Adc/ AdcCal/ AdcFilter/          — ADC components
      Cache/ CachePol/ LruCache/       — Cache components
      Config/ CfgParse/ CfgStore/      — Config components
      Display/ DispBuf/ DispFont/ FrameBuf/ — Display components
      EventBus/ EvbQueue/ Event/       — EventBus components
      Gpio/ Gpio{Alt,Cfg,Debounce,Group,Input,Irq,Mux,Output,Pin,Port}/ — GPIO
      I2c/ I2cMaster/ I2cScan/         — I2C components
      Logger/ LogBuf/ LogFmt/          — Logger components
      Network/ NetBuf/ Socket/ TcpClient/ — Network components
      Protocol/ ProtoCrc/ ProtoFrame/ ProtoHdlr/ — Protocol components
      Scheduler/ SchedCfg/ Task/ TaskQueue/ — Scheduler components
      Spi/ SpiCfg/ SpiDev/             — SPI components
      Storage/ Eeprom/ Flash/ StorCache/ — Storage components
      Timer/ TmrHw/ TmrMgr/            — Timer components
      Uart/ Uart{Buf,Clock,Debug,Dma,Error,Fifo,Flow,Init,Irq,Mode,...}/ — UART
```

`config.defaults.json`'s `layers` maps these to:
- **Layer1**: groups `Sample` (Core/Lib/Util), `Full` (Iface/Cross), `Support`
  (Math/App/Outer), `Access`, `Diag`
- **Layer2**: group `Platform` (all 15 platform components)

### Key docs

- `docs/spec/SWE3_SPEC.md` — view logic requirements with verification criteria (REQ-IT-XX for Interface Tables, REQ-UD-XX for Unit Diagrams). Update first before changing any view logic.
- `docs/spec/TEST_INVENTORY.md` — maps every SWE3_SPEC requirement to its test case. Update after adding/changing tests.
- `.coveragerc` — single `.coverage` file written per run.

### Quick run commands

```bash
# Full run, all groups
python engine/run.py SampleCppProject

# Full clean run, single group
python engine/run.py --clean SampleCppProject --selected-group Sample

# Skip the LLM hierarchy summaries (faster, lower quality)
python engine/run.py --no-llm-summarize SampleCppProject

# Reuse model/, regenerate views + docx for one group
python engine/run.py --use-model SampleCppProject --selected-group Platform

# Resume after a Phase 4 crash without re-parsing
python engine/run.py --from-phase 4 SampleCppProject

# Verbose stderr (DEBUG); inherited by every subprocess phase
python engine/run.py --verbose SampleCppProject --selected-group Sample
```

---

## 16. Known risks / technical debt

### Risk 1 — `parser.is_project_file()` uses `startswith` for path containment

```python
abs_path = os.path.normcase(os.path.abspath(file_path))
abs_base = os.path.normcase(os.path.abspath(MODULE_BASE_PATH))
if not abs_path.startswith(abs_base):
    return False
```

Allows `C:\foo` to match `C:\foobar`. The correct helper exists at
[utils.path_is_under](engine/utils.py); migrating `is_project_file` to use it
is open work.

### Risk 2 — flowchart filtering uses module prefix, not units.json

`views/flowcharts.py` filters `functions.json` to a group via
`fid.split(KEY_SEP, 1)[0].lower() in allowed_modules`. A more accurate
approach would walk `units.json → functionIds` for the units in that group.
The current approach can include stray functions whose key happens to start
with the right module token but whose source file isn't in any of the
group's configured folders.

### Risk 3 — `make_function_key` module fallback

If `module` is empty when called, it falls back to `parts[0]` (first path
segment). This shouldn't happen any more (`get_module_name` always returns a
real module or `"unknown"`), but a regression here would silently change keys.

### Risk 4 — ASSERT-fix linter regressions

The CFG builder skips ASSERT calls using
`cursor.extent.start.line/.column` checked against a frozen set of
`(line, col)` pairs from a regex source-scan. **Do not switch back to
`get_expansion_location()`** — that's the original bug. Linters and
auto-formatters have reverted this fix in the past. After any change to
[engine/flowchart/ast_engine/cfg_builder.py](engine/flowchart/ast_engine/cfg_builder.py),
re-run `python engine/flowchart/tests/diagnose_assert.py`.

### Risk 5 — header inline function appears in interface table but gets no flowchart — RESOLVED 2026-07-31 (first attempt reverted; see "Why the first fix was reverted")

**Symptom:** a public inline function defined in a header (e.g. `Foo.h`) showed an interface row /
section header with a description but **no flowchart figure** ("header but no table"). Unit keys
strip the extension ([utils.py `_path_to_component_unit`](engine/utils.py#L238)) so `Foo.h`+`Foo.cpp`
collapse into one unit and the interface table renders the header fn's row
([interface_tables.py:43](engine/views/interface_tables.py#L43)), but the flowchart engine
**dropped every header-defined function** via a blanket file-extension filter (`_is_header_file`).

**Root cause + fix (flowchart engine only):** the drop keyed on the wrong thing — file extension.
The correct criterion is "has a body." `functions.json` only ever holds **definitions** (parser's
`visit_definitions` is guarded by `cursor.is_definition()`, so the `declarationOnly` branch at
[parser.py:873](engine/parser.py#L873) is **dead code — never emitted**; verified 0 across all
functions), *plus* one no-body category: `syntheticFromVarDecl` (var-decls parsed as pseudo-functions,
e.g. a macro-obscured `UNIT _f(arg);`). Fix: `FunctionEntry` gained `synthetic_from_var_decl` (plumbed
through `pkb/builder.py` build/to_dict/from_dict); `flowchart_engine.run()` now skips only
`synthetic_from_var_decl` entries and processes everything else — **including header-defined inline
functions**, which libclang parses fine as their own TUs (3.2 already parses headers as TUs). Verified:
`signalGain` (`SignalInline.h`) now emits a real CFG/DOT; `_SOME_FUNCTION` (synthetic) is cleanly
skipped (previously an empty/error entry); `.cpp` inline fns unchanged (the old filter never touched
them). **Follow-up (engine-dev):** the dead `declarationOnly` branch in `parser.py` can be removed or
its guard relaxed — out of the flowchart engine's scope.

#### Why the first fix was reverted — output-filename collision (2026-07-30 → re-fixed 2026-07-31)

`fa42e6b` (drop the header filter) was reverted by `1a59190` because it made **functions declared
`extern` in a header and defined in the `.cpp` disappear** from the document. Root cause is NOT the
header filter — it is [output/writer.py:44-45](engine/flowchart/output/writer.py#L44-L45), which names
each output `Path(source_file).stem + ".json"` with the **extension stripped**, while `run()` grouped
by full path. `Foo.h` and `Foo.cpp` therefore became two `FileResult`s that both wrote `Foo.json`, and
`sorted(by_file.items())` puts `.h` last (`'c' < 'h'`) → **the header write clobbered every `.cpp`
flowchart in that unit**. Invisible while headers were filtered out; guaranteed the moment they weren't.

**Fix (2026-07-31, flowchart engine only):** keep the `synthetic_from_var_decl` filter from `fa42e6b`
*and* group by **output stem** rather than path, so `Foo.h` + `Foo.cpp` merge into one `FileResult` →
one `Foo.json` holding both. `FileResult.source_file` = first non-header path in the group (`.cpp`
still named in `_summary.json`); entries sorted by `(file, line)` for determinism. Stem grouping also
matches the rest of the pipeline, which already collapses `Foo.h`+`Foo.cpp` into one unit
([utils.py `_path_to_component_unit`](engine/utils.py#L238)) and whose incremental path
([views/flowcharts.py `_apply_incremental_plan`](engine/views/flowcharts.py#L150)) already assumes one
JSON per stem. Side benefit: two same-stem `.cpp`s in different components now merge instead of one
silently overwriting the other.

#### Follow-up — "Could not resolve cursor" for header-defined functions (2026-08-02)

Once headers stopped being skipped, real projects surfaced a second failure:
`Could not resolve cursor for '<fn>' in <path>.h:<line>`. Cause: `_process_function` parses the
function's **own file** as the TU ([flowchart_engine.py:270-271](engine/flowchart/flowchart_engine.py#L270-L271)),
so a header that is **not self-contained** (macros/types supplied by an include the `.cpp` pulls in
first — `#include "cfg.h"` then `#include "foo.h"`) is a syntax error when parsed alone and yields no
cursor. Phase 1 is immune because it captures the function from the **`.cpp` TU**; headers-as-TUs is
only its additive fallback.

**Fix:** on resolution failure, retry inside a TU that **includes** the header. Phase 1 already writes
`model/tu_includes.json` (TU → included project headers); `_build_including_tus` reverses it (same-stem
`.cpp` first, then sorted — deterministic), `views/flowcharts.py` passes `--tu-includes`, and
`EngineConfig.tu_includes_json_path` carries it. `abs_path` stays the header — only the TU changes,
since the cursor still reports the header as its location. Purely additive: self-contained headers
still resolve on the first try. Failure messages now append the real clang diagnostics
(`_parse_error_hint`). Repro'd + verified on a `SIG_API`/`SIG_VAL`-macro header fixture: before =
`✗ 1` with the cursor error, after = `Resolved 'clampSignal' via including TU …/SignalDriver.cpp`,
`✓ 5 ✗ 0`, CFG identical to the self-contained case.

**A/B verified** on a two-function fixture (`Foo.h` = `extern int fooMain(int);` + inline `fooInline`;
`Foo.cpp` = `fooMain`): path-grouping wrote `Foo.json` twice and left only `fooInline`; stem-grouping
writes once with **both** `fooMain` and `fooInline`. Full sample run: 124 ✓ / 1 ✗ across 21 units with
`SignalInline.json` (`signalGain`, header-only) now emitted. `pytest --skip-pipeline`: 631 passed, 0 failed.

### Risk 6 — duplicate interfaceId when a unit spans .h and .cpp — RESOLVED 2026-08-03

**Symptom:** two different public interfaces in one unit carry the **same** interface ID, e.g.
`IF_LAYER1_SIGNAL_SIGNAL_01` on both `normalize` (`Signal.cpp`) and `clampSignal` (`Signal.h`).
Duplicate IDs break traceability in an ASPICE deliverable.

**Root cause:** mismatch between what the ID *encodes* and what the counter is *keyed by*. The ID
string carries the **unit** — `make_unit_key(rel)` strips the extension, so `Foo.h` and `Foo.cpp`
collapse to one unit ([model_deriver.py:385-387](engine/model_deriver.py#L385-L387)) — but
`_build_interface_index` bucketed **by file** and restarted `idx = 1` for each, so both halves of a
`.h`+`.cpp` unit numbered from 01.

**Pre-existing, not caused by the header-flowchart work** (Risk 5): the pristine sample model already
carried one — `PIF_LAYER1_FULL_READWRITE_01` shared by `writeGlobal` (`ReadWrite.cpp`) and
`g_hdrGlobal` (`ReadWrite.h`). Header-defined *functions* simply never reached the document before, so
the collision was rare; once they did, it became routine.

**Fix:** bucket by unit, not by file. `_unit_of(data, base_path)` derives the same `component|unit`
key the ID uses; `_iface_sort_key` orders within a bucket by `(file, line)` since a bucket can now
span two files. Buckets renamed `*_by_file` → `*_by_unit`, `all_files` → `all_units`. `.cpp` sorts
before `.h` (`'c' < 'h'`), so **existing `.cpp` numbering is preserved and header entries append
after it** — chosen deliberately to minimise churn on IDs that may already be in delivered documents.

**Blast radius measured, not assumed:** re-deriving the sample changed **1 interfaceId out of 139** —
`g_hdrGlobal` `PIF_..._01` → `PIF_..._06`, exactly the colliding entity. Every other ID byte-identical
(`writeGlobal` keeps `_01`). Duplicates 1 → 0. A unit living in one file numbers exactly as before,
because bucketing by unit then equals bucketing by file and the sort collapses to `line`.

**Follow-on — table row ORDER (same root shape, different file):** the interface table sorted rows by
source **line** ([interface_tables.py](engine/views/interface_tables.py)) while numbering sorts by
`(file, line)`. Those agree only while a unit's interfaces live in ONE file, so once a unit spans
`.h`+`.cpp` the table rendered IDs shuffled — reproduced as `02 clampSignal / 01 normalize / 03 SIG_VAL`
when the header function sits at a lower line than the `.cpp` ones. Verified this was NOT a
pre-existing defect: the pre-change artifact had 0 of 3 unit tables out of order. **Fix:** sort rows by
the interface ID's trailing index (`_iface_order`, numeric so `_99` precedes `_100`), rather than
re-deriving the numbering's sort key in a second place — the table now tracks the numbering by
construction. Also fixes the per-function section order (`2.1.1.3`, `2.1.1.4`, …), which follows the
same list.

**Still open — cross-unit collisions (latent, NOT fixed):** `_id_seg` keeps only letters, so units whose
names differ solely by digits/underscores collapse to one ID stem (`Signal2` → `SIGNAL`, `Timer_1` →
`TIMER`) and each restarts at 01 — e.g. `IF_LAYER1_PLATFORM_UART_01` issued in both `Uart1` and `Uart2`.
The layer segment is immune (`_id_seg_layer` keeps digits); group + unit segments were never given the
same treatment. Sample project is clean (0 shared stems), but digit-suffixed unit names are everyday
firmware naming. Fix = keep digits in the unit/group segments; deferred because it renames IDs for
every unit with a digit in its name (far larger churn than the 1-of-139 above, and IDs may already be
in delivered documents).

**Regression tests:** `tests/unit/test_model_deriver.py::TestInterfaceIndexUnitKeyed` — uniqueness
across `.h`+`.cpp`, header-numbered-after-cpp, header-global vs cpp-function collision (the original
defect), and single-file numbering unchanged (the churn guard). Verified meaningful: 3 of the 4 fail
against the pre-fix code; the churn guard passes on both by design.

### Pre-V1 correctness batch (targets V1; numbered 3.1–3.19 internally — status in git/PR history + the `> Updated:` log above)

Of the ten findings from pre-V1 review (2026-07-10), **3.1–3.7 are done and
removed** (roots + interface direction/consistency + export; see WORK STATUS
block at top). Remaining open items below.

**Flowchart rendering (§13):**
- **3.8 — if/else condition depiction.** Conditional branches are not rendered
  correctly in the flowchart.
- **3.9 — overlapping edges.** Flowchart edges overlap — layout / ELK spacing.

**Behaviour:**
- **3.10 — dynamic-behaviour issue.** Under-specified; needs a concrete repro /
  definition before it can be scoped (flagged in the roadmap open questions).

---

## 17. Key design decisions

### Subprocess phases (vs in-process)

Each phase is its own process, launched by `core.orchestration.PhaseRunner`.
Trade-off: a fresh Python interpreter per phase costs ~200ms but gives:
- Isolated libclang state (no leaks across phases).
- `LOG_LEVEL` env propagation just works.
- `--from-phase N` is a one-line skip in the runner.
- Pre-existing CLI entry points stay unchanged.

### Plan-once / run-many (Batch 5)

`group_planner.plan_runs()` returns a flat `List[RunPlan]`. The runner has no
knowledge of groups or `--from-phase` translation. Translation happens once at
plan time:
- `from_phase ≤ 2`: build-model plan included; group plans use local index 1.
- `from_phase ≥ 3`: build-model plan omitted; group plans use `from_phase - 2`.

### Model always built for all groups

Phase 1 parses the **union** of all configured module folders, regardless of
`--selected-group`. The group filter only affects Phases 3 + 4. This ensures
cross-group call edges remain visible even when exporting one group.

### Function hidden flag in model, not config

`hidden: true/false` is stored per-function in `model/functions.json`,
not in `config.local.json`. Rationale: it is function-specific data that
lives alongside descriptions, direction, interfaceId, etc. Config is for
pipeline behaviour settings, not per-entity data. This also means the flag
survives config resets and is visible to any future tool that reads the
model, not just the DOCX exporter.

Phase 3 does not read the `hidden` field — it still writes every function
to `interface_tables.json`. Phase 4 filters at export time, so hiding and
re-running export only (Phase 4) is the correct workflow.

### Artifacts dir from `json_path`, not `output_dir`

`docx_exporter.export_docx` uses `os.path.dirname(json_path)` as
`artifacts_dir`. This is what fixes embedded-PNG paths under `output/<group>/`.

### Project root in views from `model_dir`

The three diagram views all compute
`project_root = os.path.dirname(os.path.abspath(model_dir))`. Stable
regardless of `output_dir` value (which can be `output/<group>/`).

### Single LLM client class

Anything LLM goes through `llm_core.client.LlmClient`. There is no second
HTTP client, no per-feature wrapper. Provider switching is a config change,
not a code change. Token tracking and think-section stripping are baked in.

### `selectedGroup` is CLI-only

Was previously a config field; intentionally removed to keep group selection
unambiguous. There is no env-based override either.

### LLM is off by default for `descriptions` / `behaviourNames`

Both default to `false`. Hierarchy summarization (`--no-llm-summarize` to
disable) is the **only** LLM step that runs by default in Phase 2, because
its outputs (`summaries.json`, `knowledge_base.json`) feed the flowchart
engine.

### JSONC config

`//`, `/* */`, and trailing commas are accepted. The strippers live in
`core.config` and operate before `json.loads`.

### Fail loud on config errors (version3)

The version2 LLM config path silently defaulted missing fields (e.g.
`.get("provider", "ollama")`, `.get("numCtx", 8192)`). Debugging the
difference between "what config says" and "what's actually used" wasted
enough time that version3 replaced every silent default with a
`LlmConfigError` that names the failing field. If a user wants a different
provider/model/budget they must put it in the config — the tool will not
guess. The startup banner exists so the user can verify which values were
actually read before the long-running pipeline starts. See §4b.

### One token budget, many sections (version3)

Every LLM call in the project derives its section limits from one knob
(`llm.maxContextTokens`) via `ContextBudget(task, …)` + `TASK_RATIOS`.
Adding a new LLM task type means adding an entry in `TASK_RATIOS` — no
other code changes. Section ratios must sum to ~1.0 (enforced by assertion).

### Enrichment features are individually gated (version3)

Every enrichment feature (`twoPassDescriptions`, `selfReview`, `ensemble`,
`cfgSimplification`, `variableEnrichment`) can be turned on or off
independently via `llm.enrichment.*`. Defaults favour the cheapest safe
option: the two features with the biggest quality payoff for DOCX output
(`twoPassDescriptions`, `variableEnrichment`) are ON; the expensive ones
are OFF. Users opt into cost by flipping the flag.

---

## 18. Past mistakes / lessons learned

### `visit_global_access` used wrong visited-set (fixed)

`visit_global_access` was checking `_visited_call_keys` (shared with `visit_calls`)
instead of its own `_visited_global_access_keys`. Since `visit_calls` runs first and
adds every function, `visit_global_access` skipped every function body — no global
reads were ever recorded, so every function defaulted to `"In"`. Fixed by using
`_visited_global_access_keys` (which already existed but was never used).

### Direction default was wrong (fixed)

Functions with no global access were assigned `"In"` (the `else` branch fallback).
The correct value is `"Out"` — a pure function that touches no globals provides a
result without side effects. Fixed by making the `else` branch return `"Out"`.

### Shell on this machine

Native shell is `bash` (Git Bash) on Windows 11; `&&` chaining works there
but **not** in PowerShell. Use forward slashes for paths even on Windows.
Use `/dev/null`, not `NUL`.

### `run.py` arg parsing bug (fixed)

An older version stripped `--selected-group` from argv but left the value
(e.g. `core`) as a positional, which then became `project_path`. Fix: each
flag explicitly consumes its own value via `i += 1`.

### Broken grouped output paths (fixed in two places)

Root cause: `output_dir` was used to derive the repo root. When group output
went to `output/<group>/`, `dirname(output_dir) = output/`, not the repo
root. Fix 1: views use `dirname(abspath(model_dir))`. Fix 2: exporter uses
`dirname(json_path)` as artifacts dir.

### `--all-groups` removed

Was present in an intermediate version as a redundant flag. Removed because
all-groups is the default whenever `modulesGroups` is set and no
`--selected-group` is passed.

### Env-based group override removed

An `os.environ`-driven selected-group was added then removed. Preference in
this codebase: minimal optional code paths, explicit CLI control.

### Linter reverts the ASSERT fix

See Risk 4 in §16. The ASSERT fix in `cfg_builder.py` has been reverted by
linters/tools more than once. Always re-run `diagnose_assert.py` after
touching that file.

### Flowchart filtering implementation mismatch

Discussion in earlier sessions described traversing `units.json → functionIds`
for the group filter. The actual code in `flowcharts.py` still uses module
prefix matching (Risk 2). Re-read source after edits — discussion is not
implementation.

### Configs with `core` / `support` / `tests` vs current group names

Earlier docs referenced `InterfaceTables`, `Flowcharts`, `BehaviourDiagram`,
… as group names, then `core`, `support`, `tests`. The current `config.defaults.json`
uses `Sample`, `Full`, `Support`, `Access`, `Diag`, `Platform` (matching the
`SampleCppProject` fixture). When validating CLI behaviour, always check
which config is active before quoting group names.

### `module` → `component` rename is pervasive — don't mix old and new

The rename from "module" to "component" touched source, model JSON keys,
config, and constants. Any code that uses the old names (`MODULES`,
`_analyzerAllowedModules`, `get_module_name`, `moduleName`, `modulesGroups`,
`moduleStaticDiagram`) will silently fail to filter or produce empty output.
After any refactor, grep for the old names to confirm nothing was missed.

### `interface_tables.json` total = components in the file, not the group

Phase 4 (`docx_exporter.py`) counts sections from the `interface_tables.json`
it reads — never from the selected group's component count. If that file was
generated with more components than the selected group has, the progress
total will be wrong. Ensure Phase 3 was run for the group (which writes a
group-filtered `interface_tables.json` to `output/<group>/`) before running
Phase 4. Stale files from a previous full-project run cause the mismatch.

### Do not reach into private `_attrs` on `LlmClient` (version3)

The coherence pass used to have
`int(getattr(self._client, "_num_ctx", 8192) or 8192)` as a fallback. That
kind of access is indistinguishable from a hardcode — the config file could
say 32000 and the pass would still silently use 8192 if anything upstream
misreferenced the attribute. Fix: threaded `max_context_tokens` down from
the caller via a constructor parameter, added `LlmClient.num_ctx` as a
public property, and removed every `getattr(client, "_*", default)`. If a
new LLM helper needs to know a budget, take it as a parameter — do not
peek.

### Windows cp1252 stderr kills Unicode box-drawing (version3)

The first version of `format_llm_config_banner()` used `─` (U+2500) and
`→` (U+2192) and crashed on Windows because Python's stderr defaults to
cp1252. Fixed by switching to ASCII `-` and `->`. Rule of thumb: if text
may be printed to stderr on Windows without a deliberate UTF-8 setup, keep
it to ASCII.

### Shell heredocs fail under Git Bash on Windows (ongoing)

Multi-line `python -c "…"` with indented code hits
`IndentationError: unexpected indent` because `bash.exe` (Git Bash) on
Windows does weird things to newlines inside double-quoted strings. When
you need a multi-line Python snippet, write a temp `.py` file and run it,
or use a single expression with `;` separators. Do not try to fix heredocs
on this machine — it's a known loss.

---

## 19. API Server (`api/`)

> Full context lives in **[`api/PROJECT_CONTEXT.md`](api/PROJECT_CONTEXT.md)** — read that file for anything API-related. This section is a brief pointer only.

The `api/` directory is a standalone FastAPI REST server added on branch
`feat/api-server`. It exposes all platform functionality over HTTP and ships
with an in-memory database seeded with realistic dummy data.

Key facts:
- **Start:** `uvicorn api.main:app --reload --port 8000` (after `pip install -r api/requirements.txt`)
- **Docs:** http://localhost:8000/docs (Swagger UI)
- **Auth:** `POST /api/v1/auth/signin` → Bearer token → `Authorization: Bearer <token>` on every request
- **Seed credentials:** any of the five seed users (e.g. `alice@aspice.dev`) with password `secret`
- **Swap the DB:** set `API_DB_BACKEND=json` env var (or change one line in `api/db/session.py`) — two built-in adapters: `InMemoryDatabase` (default) and `JsonDatabase`
- **JSON DB:** `API_DB_BACKEND=json` persists state to `api/db/data/*.json` and automatically loads `model/functions.json` from the pipeline output on startup
- **51 endpoints** across auth, projects, commits/versions, analysis jobs, documents, team, compare, functions, notifications

See [`api/PROJECT_CONTEXT.md`](api/PROJECT_CONTEXT.md) for architecture decisions, known issues, seed data, SSE streaming, error envelope, the full route list, and JSON DB adapter details (§11).

---

## 20. Dependencies


```
libclang (LLVM 17)        — C++ AST parsing (clang.cindex)
python-docx               — DOCX generation
requests                  — HTTP client for both Ollama and OpenAI gateways
mermaid-cli (mmdc)        — Mermaid → PNG (npm install @mermaid-js/mermaid-cli)
```

Python deps: `requirements.txt`. Node.js: `package.json` (mmdc installed
locally into `node_modules/.bin/`). The analyzer prefers the local mmdc
binary and falls back to system `mmdc`.

---

## 21. End-to-end code flow — single command, full pipeline

For the literal-minded: this is what happens when you run

```bash
python engine/run.py --selected-group Sample SampleCppProject
```

1. **`run.py` startup** — sets `cwd` to its own directory; prepends
   `src/` to `sys.path`; calls `core.logging_setup.configure_logging` (which
   creates `logs/run_YYYYMMDD.log` and the stderr handler).
2. **Argv loop** — parses flags. Sets `selected_group_arg = "Sample"`,
   `from_phase = 1`, `use_model = False`, `no_llm_summarize = False`.
3. **`load_config(SCRIPT_DIR)`** (re-exported from `core.config`) — reads
   JSONC, merges `config.local.json` if present. Sets `LIBCLANG_PATH` env var
   from `clang.llvmLibPath` if the file exists (propagates to all subprocesses).
   If `llm.summarize` is `false` in config, forces `no_llm_summarize = True`.
3a. **Layer include path collection** — walks each `layers.<L>.path` directory
   under `SampleCppProject/`, collecting every subdirectory. Writes
   `model/clang_include_paths.json` as `{LayerName: [abs_dirs…]}`. Runs before
   any subprocess so Phase 1 can extend its `-I` flags from it.
3b. **`load_llm_config(cfg)` + banner** — strictly validates the `llm` block
   (required: `provider`, `baseUrl`, `defaultModel`, `timeoutSeconds`, `numCtx`,
   `retries`; type-checked enrichment toggles; env-var overrides). Renders
   `format_llm_config_banner` and writes it to the log so the run begins with a
   visible record of which provider/model/budget will be used. On any
   validation failure → `LlmConfigError` → exit 2 (no silent defaults).
4. **`plan_runs(cfg, …)`** — calls `get_flat_groups(cfg)`, sees `layers` is set
   and `selected_group = "Sample"`. Returns two plans:
   - Plan 1: "Build model (all modules)" → `[parser.py <abs_project_path>, model_deriver.py]`
   - Plan 2: "Group: Sample" → `[run_views.py --output-dir output/Sample --selected-group Sample, docx_exporter.py output/Sample/interface_tables.json output/Sample/software_detailed_design_Sample.docx --selected-group Sample]`
5. **`PhaseRunner.run(plan1.phases)`** — subprocess `python engine/parser.py
   <abs_project_path>`. The parser inherits `LOG_LEVEL` from env.
6. **Parser (Phase 1)** — loads libclang, reads `model/clang_include_paths.json`
   and extends `CLANG_ARGS` with `-I<dir>` for all layer subdirs. Walks every
   `.cpp/.h` under `MODULE_BASE_PATH`, runs three traversal passes, calls
   `build_metadata`, writes `metadata.json` / `functions.json` /
   `globalVariables.json` / `dataDictionary.json` to `model/`.
7. **`PhaseRunner.run(plan1.phases)` continues** — subprocess
   `python engine/model_deriver.py`.
8. **Model deriver (Phase 2)** — loads model via `core.model_io.load_model`.
   Builds units + components, propagates global access transitively, assigns
   interface IDs, runs static behaviour-name heuristics, optionally calls
   the LLM for descriptions and behaviour names, optionally runs the
   `HierarchySummarizer` for `summaries.json`, generates `knowledge_base.json`
   for the flowchart engine. Writes everything back to `model/` including the
   new `model/components.json`.
9. **`PhaseRunner.run(plan2.phases)`** — subprocess
   `python engine/run_views.py --output-dir output/Sample --selected-group Sample`.
10. **`run_views.py`** — loads model (`load_model(FUNCTIONS, GLOBALS, UNITS, COMPONENTS, optional=[DATA_DICTIONARY])`),
    resolves the group name case-insensitively, calls `get_layer_components` to
    find all Layer1 components, filters the full model to same-layer components
    via `_filter_model_to_components`, sets `_analyzerSelectedGroup = "Sample"`
    + `_analyzerAllowedComponents = ["Core","Lib","Util"]` on the config dict,
    calls `views.run_views(filtered_model, output/Sample, model_dir, config)`.
11. **`interface_tables` view** — writes `output/Sample/interface_tables.json`
    filtered to the Sample group's components (Core/Lib/Util). Other Layer1
    components are in the filtered model for call-edge discovery but not in the
    output.
12. **`unit_diagrams` view** — emits one `.mmd` per `.cpp` unit into
    `output/Sample/unit_diagrams/`, then renders each with `mmdc`.
13. **`behaviour_diagram` view** — uses `FakeBehaviourGenerator` to emit
    `.mmd` files plus `_behaviour_pngs.json`.
14. **`flowcharts` view** — filters `functions.json` to `functions_Sample.json`
    via component prefix, launches `python engine/flowchart/flowchart_engine.py …`
    with `--knowledge-json model/knowledge_base.json`. The engine:
    - builds (or restores from `.flowchart_cache/`) the PKB
    - groups functions by source file
    - for each function: source extract → libclang TU parse → cursor resolve
      → CFG build (with ASSERT skip) → enrich with PKB → batched LLM labeling
      with auto-halving on empty responses → validate → build Mermaid
    - writes one JSON per source file into `output/Sample/flowcharts/`
    - writes `_summary.json`
    The view then walks the per-unit JSONs and renders every flowchart to
    PNG via `mmdc`.
15. **`PhaseRunner.run(plan2.phases)` continues** — subprocess
    `python engine/docx_exporter.py output/Sample/interface_tables.json output/Sample/software_detailed_design_Sample.docx --selected-group Sample`.
16. **`docx_exporter.py`** — `artifacts_dir = output/Sample/`, loads model +
    abbreviations, applies same-layer filter (all Layer1 components) to model
    dicts, iterates only Sample's components (Core/Lib/Util), builds the DOCX
    via `python-docx`. Embeds component static diagrams, unit diagrams, flowchart
    PNGs, and behaviour-diagram PNGs from paths under `artifacts_dir`. Writes
    `output/Sample/software_detailed_design_Sample.docx`.
17. **Back in `run.py`** — `runner.run` returns elapsed seconds; the loop logs
    `Done. Total: <secs>s` and `Full log: logs/run_YYYYMMDD.log`. Each
    subprocess's `atexit` hook has already dumped its LLM token usage to the
    log file.

If anything in steps 5–16 fails with a non-zero exit code, the runner logs
`<phase> failed with exit code N; resume with: --from-phase <idx>`. The user
can fix the underlying issue and rerun with that flag, skipping straight to
the failed step.

---

## 21. Companion: the older FastAPI backend (SUPERSEDED)

> **⚠️ Superseded / historical.** This section documents an older version3/4 FastAPI
> backend, replaced by the current `api/` server (§19). Path/name references below
> predate the `src → backend → engine` renames and may be stale (e.g. an `engine/main.py`
> mentioned here never existed at that path — it was the old server's `backend/main.py`).

> **Integration status (version4):** the `engine/` layer and the
> `docs/production-redesign/` design docs were brought onto this branch from
> `version3`, on top of the newer `main` code line. The backend was written
> against the **older `modulesGroups` / `module` schema** and the
> `model/modules.json` filename. This `main`-based code line instead uses the
> **`layers` config + `component` terminology + `model/components.json`** (see
> §4d, §6) and adds CLI flags (`--selected-layer`, `--selected-component`,
> `--data-dictionary`, `--macros`, `--include-path`, `--project-name`).
> **Adapting the backend to that schema and flag set is an open follow-up**
> before it runs correctly against this analyzer. The description below is the
> backend *as built on version3*.

Starting in version3, the analyzer pipeline is also reachable over HTTP
through a small FastAPI service that the external UI talks to. This
section is intentionally short — it orients you to the layer; the
authoritative reference is **[engine/PROJECT_CONTEXT.md](engine/PROJECT_CONTEXT.md)**
(~930 lines covering all endpoints, request/response shapes, design
decisions, and the development history).

### What the backend is, and isn't

- **What it is**: a thin async wrapper around `run.py`. It spawns the
  analyzer as a subprocess (`_spawn_run_py`), tails its stdout+stderr
  to per-job log files, parses `[N/M] === Phase X: ... ===` markers
  for progress, and exposes the model artifacts that the analyzer
  already produces (functions, components, flowcharts, the exported
  DOCX).
- **What it isn't**: a re-implementation of the pipeline. The backend
  never imports analyzer internals — it only reads JSON the analyzer
  writes and shells out to `python engine/run.py`. The pipeline contract
  documented in §3, §10–§14 is the single source of truth.

### Process model

- FastAPI on `:8000`, CORS pinned to `http://localhost:5173` (the Vite
  dev server the UI runs on).
- Jobs live in an in-memory `_jobs: dict[str, JobState]` — **no
  persistence by design**. Restarting the backend forgets in-flight
  jobs, but already-exported DOCX files on disk remain downloadable
  via `GET /jobs/{jobId}/download` (the endpoint resolves by reading
  `output/*.docx` directly).
- Each spawned subprocess writes to
  `logs/job_<job_id>.out.log` (interleaved stdout+stderr). The
  `GET /jobs/{jobId}/preplogs` endpoint tails this file rather than
  buffering in process memory.
- Process tree kill uses `taskkill /F /T` on Windows and `killpg(SIGKILL)`
  on POSIX so cancelling a job actually stops the whole subprocess tree
  (parser/model_deriver/run_views/docx_exporter can spawn children).

### Progress: canonical 4-phase mapping

The pipeline has variable plan counts (build-only vs build+views vs
views-only, multi-group runs) and inside-plan phase counts (some plans
have 2 phases, others 4). To give the UI a stable progress bar:

- A **canonical 4-phase** taxonomy is exposed regardless of the
  actual plan shape: Parse C++ source → Derive model → Generate
  views → Export to DOCX.
- `_PHASE_NAME_TO_NUMBER` maps phase labels (case-folded) to
  `phaseNumber` 1..4.
- `_CANONICAL_TOTAL = 4` is always returned as `totalPhase` (even when
  the actual plan has only 2 phases — `totalPhase` is canonical, not
  literal).
- `_expected_phase_markers(selected_group, from_phase)` predicts the
  total number of `=== Phase ... ===` markers the run will emit, used
  to compute `overallProgress` monotonically. This was the fix for the
  "75% → 25% → 100%" regression: previously `overallProgress` was
  computed from "markers seen / markers in current plan", which jumped
  backwards across plan boundaries.
- The `phase` field strips a leading `Phase N: ` prefix
  (`_PHASE_LABEL_PREFIX_RE`) — the UI wants the bare phase name.

### Config editing: surgical JSONC splice

`POST /api/v1/config` updates only the `modulesGroups` key inside
`engine/config/config.defaults.json` while preserving every comment and every other
key in the file. The implementation (`_find_modules_groups_key_pos`)
is a small JSONC-aware state machine that tracks strings, line
comments, block comments, and brace nesting depth — a regex or a
`json.loads` + `json.dumps` round-trip would either miss commented
duplicates or strip every `//` and `/* */` comment from the file.
Earlier attempts to do this with `json.loads` deleted ~80% of the
config; the surgical splice is the only safe path. Backup files are
**not** written (the user explicitly opted out — git is the backup).

> **Schema note (version4):** on this `main`-based code line the config key
> is **`layers`** (two-level), not `modulesGroups`, and the model file is
> `model/components.json`, not `modules.json`. The splice target and the
> component/module-keyed read paths must be updated when the backend is
> adapted (see the Integration status note above).

### Multi-repository CRUD

`engine/repository_config.json` is a list of `{name, path}` entries
(see `engine/models.py:Repository`). Endpoints that previously took
just a path now accept `?name=<repo>` query parameters; the backend
resolves the name to a directory via `_resolve_repository_path` and
auto-migrates legacy single-repo `{path: "..."}` files to
`[{name: "default", path: "..."}]` on first read.

### Where to read more

The full endpoint catalog (17 endpoints), request/response examples,
and the lessons-learned section (12 entries: venv mismatches, the
config splice 80% bug, progress monotonicity, hiddenFns evolution,
PNG slicing, ELK feedbackEdges, lossy-rewrite reversal, Windows
shell=True quirks, etc.) is in
[engine/PROJECT_CONTEXT.md](engine/PROJECT_CONTEXT.md). API examples
with curl payloads are in [engine/API_DOC.md](engine/API_DOC.md). A
sample response fixture lives at
[engine/fixtures/get_components_FTL.json](engine/fixtures/get_components_FTL.json).

---

## 22. Production Redesign (POC → Production) — design decisions

> This section captures the forward-looking **production platform** design work done in the
> 2026-06 design sessions. Everything in §1–§21 is the **POC**; this is the plan to productionize it.
> **Full detail lives in three design docs under `docs/production-redesign/` (brought onto `version4`).
> Read those for depth — this section is the orientation + the decisions, so a fresh session can
> pick up without re-deriving them.** Where this section references analyzer specifics it uses this
> code line's `layers`/`component` terminology (§4d).

### 22.1 Design documents (read these for full detail)

- **`docs/production-redesign/01-technology-selection-study.md`** (v1.2) — overall production stack + deployment.
- **`docs/production-redesign/02-database-design-study.md`** — DB selection (PostgreSQL), POC-grounded, with storage estimation.
- **`docs/production-redesign/03-incremental-changes-design.md`** (**v1.2** — §12 records the chosen path: **Approach 2**, git-diff narrowed parse) — the incremental / delta regeneration feature.

### 22.2 The vision

A **multi-tenant, on-premise production platform**: users register a C++ project (a path or, going
forward, a **git/Bitbucket URL → clone**), the platform runs the analyzer and produces the ASPICE
SWE.3 document, browsable/downloadable in a UI. Must be **scalable, reliable, durable, consistent**.

### 22.3 Hard constraints (these drive every decision)

- **On-prem only** — C++ firmware IP must not leave the corporate network → **no cloud services**.
- **Open-source only (OSI-approved)** → rules out *source-available* licenses: **SSPL** (MongoDB),
  **CSL** (CockroachDB, since 2024), **BSL** (ArangoDB/Memgraph), and **MinIO/Redis** post-relicense.
- **Firmware-scale** — up to ~50k functions/project (~20k typical), ~40 tenants/project
  (tenants **share** the codebase, so they do *not* multiply data), 10+ branches/project.
- **Rewrite the analyzer to read/write the DB directly** (no more `model/`+`output/` JSON files) —
  this also removes the local-disk phase handoff, which is what enables **distributed workers**.

### 22.4 Selected stack (key decisions)

- **Database: PostgreSQL 16+** (single-primary + HA via **CloudNativePG/CNPG**) with **pgvector**.
  The **system of record** (replaces the JSON files).
  - *Why Postgres:* one engine covers **relational + JSONB (document) + recursive CTEs
    (graph/impact analysis) + pgvector (similarity)**; ACID; OSI open-source; on-prem; won't rug-pull;
    modest structured scale **fits one node**.
  - **NOT a distributed DB** (Citus/Cockroach/Yugabyte) — structured data fits one node; we scale the
    **stateless worker tier**, not the DB.
- **Job queue:** Postgres-as-queue (`SELECT … FOR UPDATE SKIP LOCKED`) — **not** RabbitMQ/Kafka/Redis
  (extra stateful system for throughput we don't need; long, few jobs).
- **Graph / impact analysis:** Postgres **recursive CTE / materialized closure table** (not a graph DB;
  **Apache AGE** is the in-Postgres graduation path, then NebulaGraph).
- **Object storage: DEFERRED to a future phase.** History worth knowing: chose MinIO → discovered
  **MinIO Community Edition was archived ("no longer maintained") in Feb 2026** → switched to
  **SeaweedFS** (Apache-2.0) → then **deferred object storage entirely for now**. v1: keep **latest
  document per branch** in the DB; **flowchart images generated on demand, not stored**; **Mermaid
  scripts kept in the DB** (text).
- **Deployment:** containers on **Kubernetes**, **3-node cluster** (quorum = 2, survives **1** node
  failure; 5 nodes survive 2). **Stateless tier** (API + workers) vs **stateful quorum-bound data
  core** (Postgres + etcd [+ object store later]). **Local SSD (NVMe-ready)** via TopoLVM/OpenEBS
  LocalPV; redundancy = **app-level replication** (CNPG), not a storage layer. No existing
  CSI/distributed storage. Worker VMs are **not** quorum members → scale them freely.
- **LLM:** internal **corporate gateway** (OpenAI-compatible, off-cluster) → **no GPU nodes** in-cluster.
- **Auth:** **in-app auth + RBAC on PostgreSQL** (simple roles now); **Keycloak + corporate SSO** is the
  graduation path. Tenant isolation via `tenant_id` + optional Postgres **Row-Level Security (RLS)**.

### 22.5 Rejected DB options (for the record)

- **MongoDB** — SSPL (not OSI); weak graph/relational; on-prem vector is Atlas-only.
- **CockroachDB** — CSL (not OSI since 2024); distributed-scale we don't need.
- **Citus / YugabyteDB** — solve a write-scale problem we don't have; AGPL (Citus); less-mature pgvector.
- **MySQL / MariaDB** — weaker JSONB; immature vector ecosystem vs pgvector.
- **SQLite** — single-writer; no multi-tenant concurrency.
- **Neo4j / dedicated graph DB** — GPLv3 Community has no open-source clustering; our graph need is
  bounded transitive closure that Postgres handles.
- **Qdrant / Milvus as the primary store** — augment, not replace; pgvector covers current scale
  (kept as a graduation path).

### 22.6 Incremental (delta) regeneration feature — design summary

Goal: **hours → minutes** for small changes (skip the rate-limited LLM work for unchanged functions).
"Incremental build for documents" (the make/ccache/Bazel principle).

- **Change detection — two layers:**
  - **`git diff --name-only`** for *which files* changed (fast, reliable — **not** its scattered hunk
    output).
  - **Entity hashing** for *which entities* changed: hash **four entity types — functions, globals,
    macros, types**. **Token-based** (libclang; ignores whitespace/indentation/CRLF, **includes
    comments**), **full SHA-256** (32 bytes, never truncated), one **uniform** hash per entity's source
    extent, **keyed by identity including the defining file/location** (so same-named macros/types in
    different files are distinct).
  - **One hash per entity** now; **per-artifact hashing is deferred**.
  - Classification: unchanged / changed / new / deleted; **move/rename = delete(old key) + add(new key)**.
  - *Why hash globals/macros/types separately:* changing a global/macro/type does **not** change a
    *using* function's tokens (a function still just writes `MAX` after `#define MAX` changes value), so
    those entities must be hashed on their own; impact analysis then refreshes the functions that use them.
- **Impact analysis (dependency-graph propagation):** changes flow **UP to callers/users**. Axes:
  **call graph (transitive callers), type usage, globals, macros, containment (file/component/project
  summaries), diagrams (call-edge changes), cross-group**. Hard cases: **indirect calls / virtual
  dispatch → over-approximate** (treat as edges to all overrides / any address-taken function);
  **move/rename → key change**. Algorithm: reverse-reachability BFS / recursive CTE / closure table over
  the stored edges.
- **Selective regeneration:** re-run the LLM only for the impact set; **reuse** stored outputs for the
  rest. **Reassemble** the document from pieces (re-run Phase 3 views + Phase 4 export; **not** in-place
  patching).
- **Chosen approach & baseline (updated — see `docs/production-redesign/03` §12, v1.2):** v1 uses
  **Approach 2** — **git-diff narrowed parse** (parse only changed files; reuse the baseline version's
  stored model + outputs for the rest) + **stored-graph impact** + **selective regen**. The product model
  is **a document version per code version, branch-agnostic** — each generation stores its own document +
  metadata; reuse is **content-addressed across all generated versions**. The diff baseline is the
  **nearest generated ancestor** (via `git merge-base`), with **Approach 1's full parse as the fallback**
  for first-generation / no-ancestor / diverged history.
- **Versioning:** a document version per generation; **full Git-style cross-version dedup is deferred**.
- **Tech additions (no new DB or system):** the **`git` CLI** in the worker image + **repo credentials**
  (SSH deploy key or HTTP access token, from a deployment-appropriate secrets store — K8s Secrets / Vault
  / env injection; the project owner supplies it at registration, stored encrypted). Operator-side recipe
  changes (LLM model/prompts/config) → a manual full-regen, separate from the user's code-diff path.

### 22.7 Storage estimation (DB structured data only; excludes images/docs)

- **~250 MB / branch** (20k functions + 3k entities), dominated by **embeddings (~120 MB) + Mermaid
  (~60 MB)**.
- **~2.5 GB / project** (×10 branches; v1 stores per-branch, no cross-branch dedup).
- Platform: ~25 GB (10 projects) → **~500 GB logical / ~1.5 TB physical at 200 projects** → a
  **single primary + replicas** comfortably suffices.
- Cross-branch dedup (deferred) would shrink ~2.5 GB → **~0.5 GB + small deltas**.

### 22.8 Explicitly deferred to later phases

- **Object storage** (images, documents at scale).
- **Per-artifact hashing** (finer-grained reuse — e.g. a comment-only change reusing the flowchart).
- **Image-render cache** (skip re-rendering unchanged flowcharts — tied to object storage).
- **Full version history** (Git-style dedup across versions/branches).
- **Non-Functional Requirements section** for the DB study.

### 22.9 What's next

- **Incremental implementation (in progress on `version4`)** — Approach 2 over the current JSON-file
  pipeline first, to migrate to Postgres later. Workstreams: git ingestion + project onboarding, per-project /
  per-version storage, entity hashing + dependency-edge persistence, the detect→impact→regenerate→reassemble
  engine wired into Phases 1–4, and the supporting APIs (onboard / projects / branches / commits / generate).
- **Detailed database schema design** — tables for entities, dependency edges, `{key → hash}` records,
  per-version baselines, RBAC, and the job queue (owned by the DB engineer).
- (Optional) the NFR section for the DB study; the object-storage study (future phase).

### 22.10 Cross-cutting lessons from this session

- **MinIO Community Edition is dead** (archived Feb 2026); **SeaweedFS** (Apache-2.0) is the maintained
  alternative *if/when* object storage is needed.
- **Watch licensing rug-pulls:** SSPL / CSL / BSL / RSAL are *source-available, not OSI*. PostgreSQL
  (PostgreSQL License) is the low-risk anchor; **Valkey** is the OSI-clean Redis fork.
- **Hashing for change detection** must be **token-based** (to ignore formatting/CRLF) and **full
  SHA-256** (collisions effectively impossible). A *token change is always a line change*, so git diff
  never *under*-detects — it only over-detects on formatting, which is the safe direction.
- **The whole incremental design biases to over-regenerate, never to stale** — every ambiguous case
  (indirect/virtual calls, formatting noise, non-ancestor commits) regenerates *more*, with a manual
  full-regen escape hatch.

---

## 23. version4 — Incremental Changes feature (this session, 2026-06-18)

> `version4` is the **active working branch**. This section is the orientation + **decisions + status**
> for the **incremental document regeneration** feature. Authoritative design lives in
> **[docs/production-redesign/04-incremental-changes-implementation.md](docs/production-redesign/04-incremental-changes-implementation.md)**
> (approach, v2.1) and **[docs/production-redesign/05-incremental-api-spec.md](docs/production-redesign/05-incremental-api-spec.md)**
> (UI HTTP API). Read those for depth; this is the map.

### 23.1 What `version4` is
- Created off `origin/main` (`f3946bd`). `main` is the live code line: **`layers`/`component` schema** (§4d —
  `modulesGroups`→`layers`, `module`→`component`, `modules.json`→`components.json`), plus
  `--data-dictionary`/`--macros`/`--include-path`/`--selected-layer`/`--selected-component` CLI, a Streamlit
  `ui/`, and the `SampleCppProject` fixture.
- Brought over from `version3`: `engine/` and `docs/production-redesign/01..03`. This `PROJECT_CONTEXT.md`
  = main's §1–§20 + §21 (backend) + §22 (production redesign) + this §23.

### 23.2 Done this session
1. **Backend adapted to layers/component** ([engine/main.py](engine/main.py), [engine/models.py](engine/models.py)):
   config source `modulesGroups`→`get_flat_groups(layers)`; component-keyed `fn_id`s + `functions_<group>.json`
   naming (`safe_filename` spaces→`-`); `_resolve_group_name` vs group names; `POST /config` splice generalized
   to the `layers` key; `UpdateConfigRequest.layers`. Verified (25 routes import + functional probe).
2. **Backend docs corrected** to layers/component ([engine/API_DOC.md](engine/API_DOC.md),
   [engine/PROJECT_CONTEXT.md](engine/PROJECT_CONTEXT.md)); `engine/repository_config.json` → `SampleCppProject`.
3. **`engine/git_service.py`** (M0 #1 — **DONE**): `clone_repo` (HTTPS user/token; token reset out of
   `.git/config`, never logged), `fetch`, `checkout`, `current_commit`, `list_branches`, `list_commits`, and the
   baseline primitives `is_ancestor` / `nearest_ancestor` / `merge_base` / `changed_files`. `shell=False`
   deliberately (credential/URL safety). Verified against the repo + a local clone.
4. **Design docs**: `04` (incremental approach, **v2.1**), `05` (UI API spec).

### 23.3 Incremental — key decisions (do NOT re-derive these)
- **Approach 2** (doc 03 §12): git-diff **narrowed parse** + stored-graph impact + selective regen; **full
  parse is the fallback** (first version / no ancestor / `mode:"full"`).
- **Version = one generation run** (`versionId`); records branch/commit/scope/dataDictId/baselineVersionId/
  counts. **All versions kept.** Same commit generated twice (different scope/data-dict) = two versions.
- **Baseline = auto nearest-ancestor** (`git merge-base --is-ancestor` over prior versions' commits; nearest by
  `rev-list --count`); **optional user override** (`baseVersionId`) with ancestor/nearest **warnings**; none →
  full gen. **Correctness is base-independent** — the base only affects *parse speed* (reuse is content-addressed).
- **`edges.json` is SLIM** — only **type/macro usage**. Calls/globals come from `functions.json`
  (`calledByIds`/`callsIds`, `reads`/`writesGlobalIds`); the **recursive/transitive closure is computed by
  reverse-BFS**, not stored. (Don't re-store the call graph — it already exists in `functions.json`.)
- **Reuse = `cache/index.json`**, a `{fingerprint → (versionId, entityKey)}` **POINTER index** — **NOT** a
  duplicate blob store. Output content lives **once** in each version's `model/output`; reuse = look up the
  fingerprint → copy from the pointed-to version. Plus **carry-forward** from the baseline version.
- **`fingerprint`** = `sha256(source_hash + sorted(dependency source-hashes))` — **content-only**; the LLM
  recipe is intentionally NOT folded in (recipe-fingerprint invalidation **dropped by decision** — an approved
  document is reused regardless of model/prompt changes).
- **Data dictionary** is per-version, replaceable; **uploaded by onboarding's separate API**; `generate` only
  references a `dataDictId`. A data-dict-only change → cheap reassembly (interface-table ranges), **no LLM**.
- **Onboarding is OUT of scope** (other engineer): registration, git credentials, the initial clone, the
  project's `layers`, the data-dict upload. Incremental **consumes** `projectId` + `repo/` + `layers` +
  data dict + `branch`+`commit`.
- **version-id assignment**: sequential per project (`v1, v2, …`), assigned at generation start. **Collision-
  free** because generations are **serialized per project** (single shared clone → one `git checkout` at a
  time; a 2nd concurrent `generate` → `409`). Global key = `(projectId, versionId)`. `projectId` uniqueness is
  onboarding's responsibility.
- **Engine flow** (doc 04 §5 — validated 8 steps): copy baseline → new version; `git diff` changed files;
  partial-parse + merge; classify changed/new/deleted; **impact BFS** (all axes; over-approx virtual/fn-ptr;
  move/rename); selective regen (index-check before LLM); reassemble (Phase 3 + 4); record version.
  **Impact analysis is the #1 correctness trap** — must regenerate dependents that live in *unchanged* files,
  else the document goes stale.
- **Regenerated dependents are cached too** (doc 04 §5 steps 6+8): every entity in
  `{changed ∪ new ∪ impacted}` that is LLM-regenerated gets a **new `cache/index.json` pointer entry** (→ the
  new version), so a future version / revert / cross-branch-identical run reuses it. Because the fingerprint
  includes `sorted(dependency source-hashes)`, an impacted dependent correctly **misses** on this version
  (its dep changed) and **hits** later when that dep state recurs. *Carried-forward* (unchanged & unimpacted)
  entities get **no** new entry — their fingerprint already points at the version that first produced them.
- **Storage interface (D9 — doc 04 §3):** all incremental-store access goes through a thin interface
  (`engine/incremental/stores.py`: `VersionStore`, `ReuseIndex`, `HashStore`, `EdgeStore`) — **JSON-file impl now,
  Postgres impl later behind the same methods**. The §5 engine + the APIs call *only* the interface (no
  scattered `open()`/`json.load`), so the §10 Postgres swap is one implementation, not a refactor. **Scope =
  the incremental *metadata* stores only** (versions/hashes/edges/reuse-index/jobs); the analyzer's per-version
  `model/`+`output/` stay file-based until the DB-native pipeline rewrite (§22.3). Git auth is **D8** (POC
  plaintext: token injected into the URL then `origin` reset credential-free; `engine/git_service.py`).

### 23.4 Storage (per project) — examples in doc 04 §4
```
workspaces/<projectId>/
  project.json                 [onboarding]  name, layers, repo ref, current dataDictId
  repo/                        [onboarding]  single clone; incremental does `checkout <commit>`
  datadict/<dataDictId>.csv    [onboarding / separate API]
  cache/index.json             [INCREMENTAL]  {fingerprint -> {versionId, entityKey}}  (pointer index)
  versions/index.json          [INCREMENTAL]
  versions/<versionId>/        manifest.json, hashes.json (full entity->source-hash snapshot),
                               edges.json (SLIM: type/macro only), config.json, model/ output/ documents/
```

### 23.5 Implementation plan + status
- **P0 `git_service` — ✅ done.**
- **P1 onboarding stub fixture — done, then removed** (with the Streamlit UI in #28). `engine/seed_workspace.py` seeded
  `workspaces/<projectId>/` with the **onboarding-owned** parts only (doc 04 §4): `project.json` (name, the
  project's `layers`, repo ref, `currentDataDictId`), `repo/` (a real **full** clone via
  `git_service.clone_repo`, public/no-creds), and `datadict/dd-001.csv` (seeded from
  `engine/config/data_dictionary.csv`). Leaves `cache/`+`versions/` to the incremental engine. Default fixture =
  `projectId=samplecpp`, repo `github.com/vishal9359/SampleCppProject` (branches `main` + `feature1/2/3`,
  topology purpose-built for nearest/far/divergent-ancestor tests — see the repo's `README.md`). `workspaces/`
  is gitignored (data). (Both this seed script and `engine/git_service.py` were later removed.)
- **M1 — version-producing FULL gen + substrate** — *in progress.*
  - **M1.1 `--config`/`ANALYZER_CONFIG` — ✅ done.** `run.py --config <path>` resolves+validates the path and
    exports `ANALYZER_CONFIG` **before** importing `utils` (which loads config at import time), so this process
    and every phase subprocess (env inherited) honor it. `core/config.py load_config()` reads `ANALYZER_CONFIG`
    first: if set it loads that file **as-is** (JSONC) — **no `config.local.json` merge**, for reproducibility —
    and **fails loud** (`FileNotFoundError`) on a set-but-missing path; unset → existing `config.defaults.json`+local
    behavior. Tests: `tests/unit/test_core_config.py::TestLoadConfigAnalyzerConfigOverride` (5).
  - **M1.2a entity hashing — ✅ done.** New `engine/incremental/hashing.py` (token-based full SHA-256;
    formatting-insensitive, comment-inclusive — folds in the preceding doc comment; visibility macros expand
    away and are intentionally excluded since the hash governs *output reuse*, and visibility is caught by the
    changed-file re-parse). `parser.py` stores `_sourceHash` on function/global entries (internal — does **not**
    leak into `functions.json`) and writes `model/hashes.json` `{entityKey→token-sha256}` for all four kinds:
    functions (model key), globals (model key), types (qn), macros (`name@relFile`, line-stable). `model_io`
    gains `HASHES`/`EDGES` (not in `ALL_MODEL_NAMES`). Verified on `SampleCppProject`: 353 entities, all 64-hex,
    **deterministic** across re-parse, and a one-function edit changed **exactly 1** hash while a whitespace-only
    reformat of a sibling changed **none**. Tests: `tests/unit/test_incremental_hashing.py` (12).
  - **M1.2b slim usage index — ✅ done.** `parser.py` adds a `visit_usage` pass (3rd walk on the same TU, no
    extra parse) that threads the enclosing function like `visit_calls`: **type usage** via AST
    (`_project_type_qn` resolves return/param/`TYPE_REF`/`VAR_DECL` types through pointer/ref/array layers to a
    project type's qn) and **macro usage** via per-function identifier-token capture. New pure
    `engine/incremental/edges.py::build_edges` (no libclang — unit-tested) inverts to
    `model/edges.json` `{typeUsers, macroUsers}` keyed by model fid, **filtered to types/macros that have a hash**
    so every key cross-references `hashes.json`; keys+values sorted for byte-stable output. Macro keys
    `name@relFile`, type keys qn — identical to `hashes.json`. Calls/globals are deliberately **not** here
    (functions.json has them). Verified on `SampleCppProject`: 14 types / 1 macro used, **0** key/fid mismatches
    vs `hashes.json`, `Point`/`Status`/`Mode` resolve to the right functions, deterministic. Tests:
    `tests/unit/test_incremental_edges.py` (8). *Known limits (M2/M3): typedef→underlying transitive type edges
    and synthetic-from-VAR_DECL functions are not tracked; macro detection over-approximates (token-name match).*
  - **M1.3a substrate — ✅ done.** **D9 store interface** `engine/incremental/stores.py`
    (`Workspace`/`VersionStore`/`HashStore`/`EdgeStore`/`ReuseIndex`, JSON-file impl, atomic writes) +
    **fingerprints** `engine/incremental/fingerprint.py` (`compute_fingerprints` =
    `sha256(source_hash + sorted(dep source_hashes))` — **content-only**, no recipe component (recipe-fingerprint
    invalidation dropped by decision) — over functions+globals; deps = callees/globals from functions.json +
    types/macros forward-inverted from edges) +
    the **version-producing full-gen orchestrator** `engine/incremental/generate.py` (CLI:
    `python engine/incremental/generate.py --project-id … --branch … --commit … --scope group:G --no-llm`): checkout
    → resolved config (global + project layers) → run `run.py --config` → capture `model/output/documents` +
    `hashes.json`/`edges.json` into `versions/<vN>/` → seed `cache/index.json` → write manifest + index. Verified
    e2e on `samplecpp` (scope group:Support, LLM off): `versions/v2` complete, 127 entities fingerprinted, docx
    captured, reuse index seeded; failed attempts recorded (status=failed) and still consume a versionId. Tests:
    `tests/unit/test_incremental_stores.py` (13) + `test_incremental_fingerprint.py` (7).
  - **M1.3b backend HTTP — ✅ done.** [engine/main.py](engine/main.py) gains `POST /api/v1/projects/{id}/generate`
    (FULL path only — spawns `engine/incremental/generate.py` as a job via `_spawn_generate`; pre-allocates the
    versionId, serializes per project with **409**, returns `{versionId, jobId, decision:"full", …}`),
    `GET …/versions`, `GET …/versions/{id}` (+ per-doc `downloadUrl`), `…/versions/{id}/download`
    (`.docx`, or `.zip` for multi-doc). generate.py: `--version-id` (pre-allocatable) + early **running** manifest
    (so the version is queryable immediately) + analyzer stdout/stderr **inherited** (so run.py phase markers land
    in the per-job log → existing `/jobs/{id}/status` tracks progress). Verified via TestClient on `samplecpp`:
    versions list/detail/download (real 47 KB docx) + validation (404/400/409). *POST happy-path not exercised
    live (TestClient blocks on the watcher; orchestrator is e2e-tested via the identical CLI path) — test live on a
    running server. `mode:"auto"`/baseline (incremental) is M2.*
- **M2 — incremental engine — ✅ done** (M2.1–M2.4 below; incremental generation works e2e + via the API).
  - **M2.1 baseline selection + preview — ✅ done.** `engine/incremental/git_ops.py` (engine-local git wrapper —
    checkout/current_commit/is_ancestor/merge_base/rev_list_count/changed_files/nearest_ancestor; decoupled from
    `engine/git_service.py`, consolidation deferred to M3) + `engine/incremental/baseline.py::select_baseline`
    (auto nearest-ancestor among *complete* versions → none = full; optional `baseVersionId` override with
    **divergent** [not-ancestor] / **not-nearest** warnings; base only narrows the parse, never staleness) +
    backend `GET …/generate/preview?commit=&baseVersionId=` (read-only, no checkout). `generate.py` now uses
    `git_ops`. Verified: tmp-repo unit tests (`test_incremental_git_ops.py` 12 + `test_incremental_baseline.py` 11)
    + TestClient preview on `samplecpp` (main→incremental/v2/nearest/0-changed, feature1→full, override-v2→divergent
    +warning, unknown→404).
  - **M2.2 classify + impact BFS — ✅ done.** `engine/incremental/impact.py` (pure): `classify(baseline_hashes,
    target_hashes)` → {changed/new/deleted/unchanged}; `impact_set(changed_keys, functions, edges,
    extra_seed_functions=)` → set of function fids to regenerate = changed/new functions + **everything
    transitively depending on any changed entity** (reverse-BFS: callers via `calledByIds`, global users via
    inverted reads/writes, type/macro users via `edges.json`; visited-set handles cycles; `extra_seed_functions`
    injects deleted entities' baseline callers). The #1 staleness trap — covered. Tests:
    `tests/unit/test_incremental_impact.py` (12).
  - **PARSE-STRATEGY DECISION (D10):** the M2 engine uses a **FULL parse** of the checked-out commit (correct
    call graph by construction), and the incremental win comes from **selective LLM regeneration** (classify →
    impact BFS → reuse). **Narrowed/partial parse (doc 03 D2 "Approach 2") is DEFERRED** to a later optimization
    (doc 04 §10's parse cache): correct narrowed parse needs cross-file call/reverse-edge reconciliation that is
    complex and easy to get subtly wrong → staleness, whereas the *primary* benefit (skip the rate-limited LLM for
    unchanged+unimpacted entities = hours→minutes) is parse-strategy-independent and a full parse is **never
    stale** (D7). Parse time becomes the bottleneck to optimize only after LLM time is removed.
  - **M2.3 incremental engine — ✅ done.** `engine/incremental/engine.py::generate_incremental`: baseline-pick →
    checkout → full parse (`run.py`) → `plan_incremental` (classify vs baseline `hashes.json` + impact BFS +
    deleted-caller seeding) → **carry forward** baseline outputs (description/behaviour names) for the reuse set
    (`carry_forward_descriptions`) → reassemble (`run.py --from-phase 4 --use-model`) → capture version + seed
    reuse index + manifest (decision/regenerated/reused/baselineVersionId/carriedForward). Falls back to
    `generate_full` when no baseline. Pure helpers `plan_incremental`/`carry_forward_descriptions` unit-tested
    (`test_incremental_engine.py` 8). **Verified e2e on `samplecpp`**: baseline v1@C3 (125 entities) → incremental
    v2@main-HEAD = decision=incremental, baseline=v1, **3 new** (multiply/clampPositive/coreReset) + impact **6**
    (incl. a deleted function's transitive callers App::main/calculate via MultiplyOperation::apply), **109
    reused/carried-forward**, 14.4s vs 31.7s full. (The `Cross::Dispatch::multiply` "deleted" is a pre-existing
    parser name-resolution fuzziness → safe over-regeneration, never stale.) *Descriptions reuse via the version3
    EntityCache on LLM-on runs; flowchart-level reuse (restrict the engine to the impact set) is M2.4.*
  - **M2.4a mode:auto dispatch — ✅ done.** `POST /api/v1/projects/{id}/generate` now resolves the target +
    runs `select_baseline` and **dispatches**: `mode:"auto"` (default) → incremental (spawn `engine.py`) when a
    baseline ancestor exists, else full (`generate.py`); `mode:"full"` forces full. Response carries the real
    `decision` + `baselineVersionId`/`baselineCommit` + `warnings`; `baseVersionId` override forwarded. `commit not
    in repo` → 409. Verified via TestClient (auto@main→incremental/engine.py/baseline=v2, full→generate.py,
    auto@feature1[no ancestor]→full, 400/409).
  - **M2.4b flowchart-level reuse — ✅ done (file-level; later narrowed by M3.5 and replaced by M3.6 function-level).** `views/flowcharts.py::_apply_incremental_plan`
    (gated on `model/incremental_plan.json`; absent → unchanged full behaviour) **carries forward** the baseline
    version's `output/<scope>/flowcharts/*.json` then **restricts** the flowchart engine's functions file to the
    impacted source files (engine overwrites only those). `engine.py` computes `impactedFiles` BEFORE the run
    from the **baseline model + `git diff`** (over-approx, safe — no Phase-split) and writes/cleans the plan.
    The `engine/flowchart/` engine is unchanged. Verified e2e on `samplecpp` (carried 3 / restricted 16 in 9 files;
    output complete, plan not leaked into the version). *(Superseded by M3.1: the impacted-file seeding is now
    precise/function-level, not file+git-diff.)*
- **M3 — hardening** — *in progress.*
  - **M3.1 precise function-level flowchart reuse — ✅ done.** Added **`run.py --to-phase N`** (stop after a phase;
    additive filter over `plan_runs`' output by script→phase, gated — `None` = unchanged). `generate_incremental`
    now **Phase-splits**: `--to-phase 2` (parse+derive) → compute the **precise** impact from the fresh target
    model (`plan_incremental`) → carry forward descriptions + write the impacted-files plan → `--from-phase 3
    --use-model` (views+export; flowcharts restricted to impacted files, rest carried). One impact computation
    drives both description + flowchart reuse. Verified e2e on `samplecpp`: impacted files 9→**4**, restricted
    16→**14** (exactly the 6 impacted functions' source files); v2 complete, output correct, no plan leak.
  - **M3.2 hierarchy-summary reuse — ✅ done (the real payoff fix).** Diagnosis: descriptions/behaviourNames are
    **off by default**, so M2.3's description carry-forward was a no-op; the dominant default LLM costs are
    **flowchart labeling** (fixed by M3.1) and **hierarchy summarization** (Phase 2) — and the `PkbCache` keys on
    the *whole* `functions.json` hash, so any change re-summarized **everything** (this is why an 8-line diff took
    full time). Fix: the engine now Phase-splits at **Phase 1** (`--to-phase 1` → impact → carry forward baseline
    `description`+`phases` for the reuse set → `--from-phase 2`). The summarizer only summarizes functions with no
    `description` (`project_scanner._summarize_functions`), so carrying it forward makes it **skip the reuse set**
    — function-level summarization (the big cost) is restricted to the impact set with **no `model_deriver`/
    summarizer change**. Verified e2e (C1→C3, scope Support): regenerated 9 / reused 104, flowcharts restricted to
    5 files, output correct. *File/module/project summaries still re-run (~minor, not function-gated) — a later
    refinement.*
  - **M3.3 full Phase-2 enrichment reuse + 4 fixes — ✅ done.** An LLM-on test (744s for an 8-line diff) exposed
    that M3.2 only covered function summaries, while the user's config has `descriptions:True`+`behaviourNames:True`
    and the dominant cost was **behaviour-names (417s) re-run for all 113 functions**, plus globals (46s),
    file/component summaries (117s), and PNG re-render (92s) — none reused; and the captured `documents` list had
    **stale/duplicate docx** from prior runs. Fixes:
    (1) **documents** — `engine`/`generate` clean `output/` before each run so a version captures only its own docs.
    (2) **`model_deriver` incremental mode** — reads `incremental_plan.json` (`impactFids`/`impactedGlobals`) and
    restricts behaviour-names + descriptions + global enrichment to the impact set (the engine carries forward the
    reuse set's `description`/behaviour-names/`phases` into `functions.json` and global descriptions into
    `globalVariables.json` before Phase 2). (3) **file/component summary gating** — `_run_hierarchy_summarizer`
    pre-populates `knowledge.file_summaries`/`component_summaries` from the baseline for unchanged files/components,
    and `project_scanner._summarize_files`/`_summarize_components` skip those already present. (4) **flowchart PNG
    reuse** — `views/flowcharts.py` carries forward baseline PNGs and re-renders only impacted units. Verified e2e
    (LLM-off flow): "enriching 9 functions + 3 globals; reusing the rest", documents=[just the scope's doc], PNGs
    carried. `tests/unit/test_incremental_engine.py` +2 (carry_forward_globals).
  - **M3.4 end-of-run report — ✅ done.** `engine/incremental/report.py` (`build_report` pure + `emit_report`): both
    `generate_incremental` and `generate_full` print a summary at the end — **logged** (to `logs/run_<date>.log` via
    `get_logger`) **and saved** to `versions/<id>/report.txt`. Sections: inputs (project/branch/commit/scope/
    **baseline + changed-file count**/dataDict/LLM recipe/status/**wall-clock**), **change classification** (changed/
    new/deleted/unchanged, broken down by kind), and **reuse accounting** (functions/globals/flowcharts:
    regenerated vs reused + %; summaries note). Tests: `tests/unit/test_incremental_report.py` (6). Example on
    C1→C3: `Functions regenerated 9/113 -> reused 104 (92%)`, `Globals 3/12 -> reused 9 (75%)`, `Flowcharts 5/18
    files -> carried 13 (72%)`.
  - **M3.5 flowchart impact-scoping fix — ✅ done (big speedup).** An LLM-on real-diff (C1→C3) took 1021s with the
    **flowchart engine alone = 497s**, even though only 3 functions changed. Cause: flowcharts were regenerated
    for the **full impact set** (changed + transitive callers), pulling in `App/Main.cpp`'s *large* functions
    because they call the changed `Math`. But **a function's flowchart is its own CFG + call-site labels — it does
    NOT change when a callee's *body* changes**. Fix: the plan now carries a separate **`flowchartFiles`** = files
    of only the *directly* changed/new/deleted functions (descriptions/summaries keep the full-impact
    `impactedFiles`, since those genuinely depend on callees, and are cheap); `views/flowcharts.py` restricts on
    `flowchartFiles`. (Also confirmed: the flowchart `PkbCache` caches the PKB *index* keyed by the whole
    functions.json hash — **not** LLM labels; there is no label cache — so unifying caches wouldn't help; reuse is
    handled by version-level carry-forward.) Verified e2e: C1→C3 flowcharts dropped from **12 functions / 5 files**
    to **3 functions / 1 file** (App no longer re-labeled); report shows `Flowcharts carried 15/18 (83%)`.
  - **M3.6 function-level flowchart granularity — ✅ done (supersedes M2.4b file-level).** Even after M3.5,
    flowcharts regenerated at **file** granularity: a changed file re-labeled *all* its functions (e.g. changing
    `Math::subtract` re-labeled `add`/`computeBoth` too). Now per-**function**: the plan carries **`flowchartFids`**
    (the directly changed/new fids); `views/flowcharts.py` restricts the engine to *only* those functions, carries
    forward all baseline flowchart JSONs+PNGs, then **splices** each fresh per-function flowchart into the baseline
    file JSON via `_merge_incremental_flowcharts` — **join key = entry `name` (== `functions.json` `qualifiedName`,
    verified exact)**. Merge rule: keep unchanged (baseline), replace changed (fresh), **drop deleted** (not in the
    target's current set — handles deletion-only files whose deleted entry still sits in the carried JSON), append
    new; baseline file order preserved. Only changed functions' PNGs re-render (the rest are carried). Unit set for
    the merge = `flowchartFiles` ∩ in-scope (so deletion-only files are rebuilt); engine restriction =
    `flowchartFids` ∩ scope. Safe fallback: if baseline flowcharts are missing → full flowchart regen. Report now
    counts flowcharts at **function** granularity (`flowcharts` stat: regenerated `len(direct_fns)` / total
    functions), split from file-level **summaries** (`files` stat). Other generation types were already
    function/entity-level (descriptions/behaviour-names/globals via skip-if-described + `only_fids`/`only_globals`);
    file/component summaries are per-file/per-component by nature. Verified e2e LLM-off (C1→C3, scope Support):
    flowchart engine restricted to **1 changed function** (was 3 file-level), `Utils.json` correctly retains all 3
    (`add`,`subtract`,`computeBoth`) with `subtract` fresh, **1 PNG** re-rendered; +6 merge unit tests (120 pass).
  - **M4.0 per-TU include-closure capture — ✅ done (foundation for narrowed parse; no behaviour change).**
    New `engine/incremental/parse_includes.py` (pure, libclang-free): `to_repo_relative` + `build_closure` —
    normalize libclang include paths to **repo-relative, forward-slash, case-preserved**, drop out-of-repo
    (system/third-party) headers, dedup/sort, exclude the TU's own source. `parser.py::_capture_tu_includes(tu, path)`
    reads `tu.get_includes()` in the first parse pass (best-effort — never breaks parsing) and `main()` writes
    **`model/tu_includes.json`** `{tuRelPath → [in-repo included rel paths]}` (new `model_io.TU_INCLUDES`, not in
    `ALL_MODEL_NAMES`; captured into each version automatically since `capture_artifacts` copytrees `model/`). This is
    the map the future **M4 narrowed parse** intersects with the `git diff` to find affected TUs — soundly covering
    header/macro/template fan-out (all propagate only through `#include`). Paths are case-**preserved** so they line up
    with `functions.json` `location.file` + `git diff`; case-insensitive *matching* is M4.1's job. Verified e2e LLM-off
    (`SampleCppProject`): 19 TUs / 42 in-repo edges, paths clean (no backslash/drive/`..`/leading `/`), no system
    headers leaked, `Utils.h` fans out into `Main.cpp`'s closure, form matches `functions.json` (18/19). +8 unit tests.
    **Full M4 design + corner-case audit + never-stale full-reparse triggers + `--verify-parse` self-check: doc 04 §11
    (v2.3, D10 + M4 milestone).** M4 plan is M4.0 done → M4.1 affected-TU computation (`affected.py`, pure) → M4.2
    fingerprint hardening (flags+libclang version) → M4.3 parse-merge + reverse-recompute → M4.4 engine wiring → M4.5
    self-check → M4.6 corner-case hardening. **M4 only worth building once Phase-1 parse is the *measured* bottleneck.**
  - **M3.8 branch/commit listing endpoints — ✅ done.** `GET /projects/{id}/branches` (doc 05 G1) +
    `GET /projects/{id}/branches/{branch:path}/commits?limit=&offset=` (G2) in `engine/main.py`, thin
    wrappers over the existing `git_service.list_branches`/`list_commits` on the project's clone (the UI's
    "pick a target commit" path). Verified on `samplecpp` (branches main/feature1/2/3; main 6 commits).
  - **M3.9 version-scoped reads — ✅ done.** `?projectId=&versionId=` on `/components`, `/components/{id}`,
    `/components/{id}/modules`, `/functions/{fn_id}` (GET+PATCH), `/flowcharts/{fn_id}` now serve that
    version's snapshot. Mechanism: a request-scoped **`_ReadRoots`** (contextvar `_roots()`, default = shared
    `model/`+`output/`); `_enter_version_scope(projectId, versionId)` at the top of each endpoint points the
    read helpers (`_load_functions`/`_load_groups`/`_project_base_path`/`_module_file_for_fn`/`_persist_description`/
    `_find_flowchart_entry`) at `versions/<vid>/{model,output}` + that version's `config.json` (reset in `finally`;
    per-task so concurrent requests don't collide). 404 on unknown version. Also hardened
    `_find_flowchart_entry`: walks **all** `flowcharts/` dirs under output (handles scoped `output/<scope>/flowcharts/`)
    and matches `functionKey` (real engine) **or** falls back to `name` == fn_id's qualifiedName (POC fake generator).
    `/config` (canonical *source* config) + `/project/structure` (working tree) left project-level — orthogonal to
    versions. Verified e2e (TestClient) + 10 unit tests (`tests/unit/test_backend_version_scope.py`); backend imported
    lazily there to avoid the `models` name clash with the flowchart tests at collection time.
  - **M3.7 cross-version reuse-index lookup — ✅ done (the D3 reuse payoff).** The engine now *reads*
    `cache/index.json` (it only seeded it before). New pure `engine.carry_forward_from_index(impact_keys,
    target_fps, target_entities, index, current_version_id, src_loader, fields)`: for each IMPACT-set entity
    whose **content fingerprint** already exists in the index (produced by a *prior* version — a revert, or
    code identical to another branch), it copies that version's stored output (`description`/behaviour-names
    for functions; `description` for globals) instead of regenerating. Reused entities drop out of the LLM
    regen sets (`regen_impact`/`regen_globals` → the plan's `impactFids`/`impactedGlobals`), so Phase 2 skips
    them. Fingerprints (content-only) are computed once and reused to seed the index at the end. Report adds an
    **X-version** line + `crossVersion` stat; manifest gets `crossVersionReused`. Verified e2e LLM-off: re-gen
    of C3 with baseline v1 → **functions regenerated 0/113 (100% reused), 9 reused cross-version from v2**
    (which already produced C3). +7 unit tests. **Follow-on (M3.7b):** flowchart cross-version reuse — a reused
    function's *flowchart* still regenerates (flowchartFids unchanged); reusing it needs the splice to pull
    per-fid from arbitrary versions.
  - **Move/rename orphan cleanup — ✅ done.** `views/flowcharts.py::_prune_orphan_flowcharts(out_dir, valid_stems)`
    runs right after the baseline carry-forward (both function- and file-level modes): drops carried flowchart
    JSON (`<stem>.json`) + PNG (`<stem>_<func>.png`) for source-file stems no longer in the current model (a
    deleted or **renamed** file), so a version's output carries no stale units. No-op when `valid_stems` is empty
    (guards against a load glitch nuking the carry-forward); prefix-collision safe (`Foo` won't drop `Foobar`).
    +4 unit tests; e2e confirms zero spurious pruning on the no-rename C1→C3 diff. **Note: also confirmed unit
    diagrams use NO LLM (pure structural) — incremental reuse there would only save PNG-render time; deprioritized.**
  - **git_ops/git_service consolidation — ✅ done (no behavior change).** `engine/incremental/git_ops.py` is now the
    **single** home for every local git primitive (checkout / current_commit / ancestry / diff / `list_branches` /
    `list_commits` — the last two moved over from git_service). `engine/git_service.py` keeps **only** the
    credentialed network ops (`clone_repo`, `fetch`, `_auth_url`, `_clean_url`) and **re-exports** the locals from
    git_ops, so existing `git_service.<fn>` callers and `except git_service.GitError` keep working — `GitError` is
    now one class (`git_service.GitError is git_ops.GitError`). The duplicated baseline primitives
    (`is_ancestor`/`merge_base`/`changed_files`/`nearest_ancestor`/`_run`/`_check`) are gone from git_service. Layer
    direction preserved (backend→src; git_ops has no backend dep). Verified: 20 git_ops+backend tests pass; M3.8
    endpoints flow through the re-export; identity + unified-GitError checks green.
  - **M3.7b flowchart cross-version reuse — ✅ done.** A directly-changed function reused from the index (a
    revert) has the SAME content → SAME flowchart as its source version, so it's no longer regenerated. Engine:
    `xver_flowcharts = {fid → sourceVersionDir}` (= `direct_fns ∩ index_reused`), excluded from `flowchartFids`,
    written to the plan as **`crossVersionFlowcharts`**. View (`views/flowcharts.py`): `_source_unit_flowchart`
    finds the unit's flowchart in the source version's output (walks scoped `output/<scope>/flowcharts/`); the
    splice gains a **third source** (`fresh > x-ver > baseline`) and copies the source PNG; if the source version
    has no flowchart for it, falls back to regenerating (adds the fid back to the engine's set). Report X-version
    line + `crossVersion.flowcharts` count. Verified e2e: re-gen of C3 with baseline v1 → flowcharts **restricted
    to 0 regenerated, 1 cross-version splice** (subtract from v2), `Utils.json` complete; **so a re-gen/revert is
    now 0 LLM end-to-end** (descriptions + behaviour + flowcharts all reused). +2 unit tests (three-source priority,
    x-ver new fn).
  - **Virtual-dispatch over-approximation (D7 audit) — ✅ done.** Audit found: a virtual call `base->m()`
    resolves (libclang) to the static method — or, when the base is pure-virtual, an *arbitrary* override by
    name — so sibling overrides got **no caller** (e.g. `MultiplyOperation::apply` showed `calledByIds: []`):
    changing an override wouldn't impact the dispatcher (**stale**) and the model was inaccurate. Fix: new pure
    `engine/incremental/virtual_dispatch.py::spread_virtual_families` — unions virtual *families* (override→base via
    `clang_getOverriddenCursors`, bound through the **C API by ctypes** since this Python binding lacks the wrapper;
    queried on `cursor.canonical` because out-of-line defs report no overrides) and links every caller of any member
    to **all** members. `parser.py` collects `_override_pairs` in `visit_definitions` and spreads in `build_metadata`
    (before calledByIds/callsIds are derived). Verified: `applyWithOperation.callsIds` now lists both overrides,
    `MultiplyOperation::apply.calledByIds = [applyWithOperation]`. Degrades safely (no spread) if the C API is
    absent. +6 unit tests. **Function-pointer dispatch = documented limitation** (target unknowable statically;
    dispatcher descriptions are generic → low staleness risk; use `mode:"full"` if guaranteed freshness needed).
    Details in doc 04 §5 checklist (Virtual dispatch / Function pointers rows).
  - **M3.10 unit-diagram incremental reuse — ✅ done.** `views/unit_diagrams.py` now gates on
    `incremental_plan.json`: carries forward the baseline version's unit diagrams (`.mmd`+`.png`), prunes orphans
    (renamed/deleted units), and regenerates only **affected units** = units of the impacted functions PLUS their
    1-hop cross-unit neighbours (`_affected_units` — a unit diagram shows the edges incident to the unit, so any
    change to a function in it OR a function it calls / is called by can alter it; over-approximates, never stale).
    No-LLM view, so the win is render time only. Verified e2e: C1→C3 regenerated **1 affected unit of 3**, other 2
    carried forward; +6 unit tests. (No incremental plan → original full wipe+regenerate.)
  - **All doc-05 incremental APIs implemented** ✅ — G1 `/branches`, G2 `/branches/{branch}/commits`, #1
    `/generate/preview`, #2 `/generate`, #3 `/versions`, #4 `/versions/{id}`, #5 `/download`, #6–#10 job
    status/logs/cancel/export (reused), #11–#13 `/components`·`/functions`·`/flowcharts` (version-scoped, M3.9),
    #14 `/config`, #15 `/project/structure`.
  - **M4 narrowed parse — ✅ COMPLETE (M4.0–M4.6)** (for big 10k+-function codebases; full design in doc 04 §11).
    Avoids the whole-project Phase-1 parse: parse only the affected TUs, reuse the baseline model for the rest, merge
    + recompute reverse edges. Opt-in (`--narrowed-parse`) + `--verify-parse` self-check; full parse stays the default
    until the self-check is clean across a diff matrix on a large repo. Validated byte-equal (set-level) on C1→C3.
    - **M4.1 affected-TU set — ✅ done.** `engine/incremental/affected.py` (pure): `affected_tus(changed, tu_includes)`
      = TUs whose closure ∩ git-diff ≠ ∅ (+ new `.cpp` not yet in the map; case-insensitive match on Windows);
      `full_reparse_reason(status_pairs, tu_includes)` = the §11.4 must-full-reparse triggers (no closure map; a
      **header added/deleted** → shadowing risk). `git_ops.changed_files_status` (`git diff --name-status`, renames
      split into D+A). +9 unit tests.
    - **M4.2 parse fingerprint — ✅ done.** `fingerprint.parse_fingerprint(clang_args, std, toolchain)` (order-
      preserving over `-I`/`-D`) — a mismatch vs the baseline version's value forces a full re-parse (flags/
      toolchain changed). +4 unit tests.
    - **M4.3 partial-parse + merge — ✅ done (the core).** `parser.py --only-files <listfile>` parses only the
      affected TUs → a *forward-only* partial model; verified (1 TU → 3 fns). Parser also emits
      **`model/entity_files.json`** `{entityKey → defining file}` (covers all hashed entities — types/hashes have no
      inline location; full parse: 353/353). `engine/incremental/parse_merge.py::merge_model(baseline, fresh, drop_files)`
      (pure): drop baseline entities whose file ∈ drop, overlay fresh, merge edges/dataDictionary/tu_includes by file,
      then **recompute calledByIds** (filter callsIds to merged fns → re-run virtual spread → invert). Verified on REAL
      data: full-parse a baseline, re-parse 1 TU as a partial, `merge_model(...)` == the full parse
      (functions/hashes/globals/edges all match). +7 merge unit tests. *(`override_pairs` emission for cross-affected
      virtual re-spread → done in M4.6; calledByIds **list order** byte-identity remains set-equal, the correctness bar.)*
    - **M4.4 engine wiring — ✅ done + validated (opt-in).** `generate_incremental(narrowed_parse=…)` /
      `engine.py --narrowed-parse`: when on AND the baseline has a parser-level snapshot + no full-reparse trigger,
      it computes `affected_tus`, runs `run.py --to-phase 1 --only-files <list>` (threaded through
      `group_planner`→`run.py`→`parser.py`), and `parse_merge.merge_model(baseline_parse, partial, drop)` → writes
      the merged blank skeleton to `model/`; else a full parse. Each version now snapshots its post-Phase-1 skeleton
      to `versions/<id>/parse/` (`generate_full` phase-split; `snapshot_parse_model`). **Two correctness fixes found
      via real-data validation:** (1) `drop = changed ∪ affected ∪ deleted` (NOT every file the partial transitively
      saw — those were only partially parsed; merge keeps fresh ONLY for dropped files); (2) **cross-TU call
      resolution** — a partial parse can't resolve a call whose callee is defined in an UN-parsed file (the parser
      links edges only to known function definitions), so the parser now emits `model/func_keys.json`
      `{mangled→fid}` and a narrowed parse loads the **baseline's** map (via env `ANALYZER_BASELINE_FUNCKEYS`) so
      `visit_calls` resolves cross-TU edges. **Verified: narrowed model == full-parse model** on C1→C3
      (functions/globals/hashes/dataDictionary/edges/entity_files all match, 0 callsIds/calledByIds diffs). Full
      parse path unchanged (`_baseline_func_keys` empty → no-ops). All these are no-ops unless `--narrowed-parse`.
    - **M4.5 `--verify-parse` self-check — ✅ done.** `parse_merge.diff_models(narrowed, full)` (pure, edge lists
      compared as SETS since order is cosmetic) + `engine.py --verify-parse`: runs the narrowed parse, then a FULL
      parse, diffs the two models, logs every mismatch loudly + records a manifest warning, and **uses the full
      parse as the source of truth** (a verify run is slow but always safe). This is the gate to make narrowed the
      default. **It immediately earned its keep:** on C1→C3 it flagged `hashes[UNIT]` — `typedef int UNIT;` is
      defined in **5 files**, all keyed by the bare name, so the parse-order-dependent winner differed between
      narrowed (an affected TU) and full (the baseline's stable winner). **Fix:** `merge_model` resolves a shared
      entity's file from the BASELINE (its canonical, stable location), so a multiply-defined entity sticks with the
      baseline winner — matching a full parse. Re-verified: **narrowed == full (set-equal), 0 mismatches.** +5 diff
      unit tests.
    - **M4.6 narrowed-parse hardening — ✅ done.** (1) **Virtual re-spread:** the parser emits fid-level
      `model/override_pairs.json` (from `get_overridden_cursors`); a narrowed parse loads the baseline's + the
      partial's and `merge_model._recompute_call_edges` re-runs `spread_virtual_families` (D7) so a re-parsed
      dispatcher links to ALL overrides incl. those in un-parsed files. (2) **Parse-fingerprint gate:** the parser
      writes `metadata.parseFingerprint = parse_fingerprint(CLANG_ARGS, std, libclang lib)`; `_try_narrowed_parse`
      compares the partial's value to the baseline's and falls back to a full parse on any clang-flag/std/toolchain
      change. (3) **Windows path-case:** `parse_merge._norm` case-folds repo paths on `nt` so git-diff paths and
      `entity_files` line up in the drop set. (Header add/delete was already covered by M4.1 `full_reparse_reason`.)
      Re-validated on C1→C3 after all three: **`--verify-parse` → narrowed == full (set-equal), 0 mismatches.**
      *Remaining polish (non-blocking): exact list-ORDER byte-identity (set-equal is the correctness bar — order
      doesn't affect any consumer) and a perf measurement on a large repo (the O(diff) win doesn't show on SampleCpp).*
    - **M4 COMPLETE (M4.0–M4.6).** Narrowed parse is opt-in (`--narrowed-parse`), validated byte-equal (set-level)
      to a full parse via `--verify-parse`. Flip to default once the self-check is clean across a diff matrix on a
      real (large) repo.
      **M4.4 KEY FINDING — narrowed parse must merge against a PARSER-LEVEL snapshot, not the baseline's FINAL
      model.** Reason: the baseline final model has LLM descriptions; if the merge keeps those for unaffected files,
      the impacted *dependents* (unaffected files that call a changed fn) would carry a description → Phase 2 skips
      them → **stale**. So the merge must produce a parser-level model (source-comment descriptions, no LLM fields),
      identical to a full-parse Phase-1 output, so the engine's EXISTING classify→impact→carry_forward→Phase-2 flow
      runs unchanged. **M4.4 steps:** (1) `engine/core/group_planner.py` + `run.py`: thread a new `--only-files <list>`
      through to `parser.py` (Phase-1 parses only those TUs); (2) a `_snapshot_parse_model(model_dir, version_dir)`
      helper that copies the 8 parser artifacts (functions/globalVariables/dataDictionary/hashes/edges/tu_includes/
      entity_files/metadata) to `versions/<id>/parse/` — captured after Phase 1 in BOTH paths (phase-split
      `generate_full` into `--to-phase 1` → snapshot → `--from-phase 2`); (3) `engine.generate_incremental(narrowed_parse=…)`:
      if opt-in AND baseline has `parse/` + `tu_includes.json` AND `affected.full_reparse_reason(...)` is None →
      compute `affected_tus` from the diff ∩ baseline `tu_includes`, run `--only-files`, `parse_merge.merge_model(
      baseline_parse, partial, drop_files=affected ∪ deleted ∪ fresh-entity-files)`, write merged → `model/`,
      snapshot it to `versions/<id>/parse/`; else full parse (today's path). Then the existing flow is untouched.
      Default = full parse (zero risk); flip only after the M4.5 self-check is byte-identical across a diff matrix.
  - *Remaining (after M4):* **M5** Postgres migration, **M6** object storage/dedup — deferred to the production phase.
    (Recipe-fingerprint invalidation **dropped by decision** — fingerprint is content-only; multi-doc zip shipped in M1.3b.)
  - **PERF M-A…M-D — ✅ DONE (Phase 3/4 + Phase 2 caching; full design in doc 04 §12).** LLM-on profiling showed a
    ~85s fixed floor that did NOT scale with change size (a 0-change incremental still cost ~88s): the floor lived
    in Phase 4 (DOCX) + Phase 2 (derive), neither incremental. Narrowed parse only touches Phase 1 (~10%). All caches
    content-addressed, persist across version runs.
    - **M-A content-addressed Mermaid→PNG cache.** `utils.render_mermaid_cached()` (key `sha256(mermaid+scale+puppeteer)`
      at `<root>/.mmdc_cache/`); routes docx component diagrams (Phase 4, the ~46s win) + the Phase-3 flowchart/unit
      renders through it. `mmdc` runs once per unique diagram; graceful fallback on any cache error. +3 tests.
    - **M-B export-time description cache.** `get_struct_description`/`get_unit_description` cached via `EntityCache`
      (`.flowchart_cache/aux_descriptions`, honours `cacheVersion`). With M-A, an unchanged component's Phase 4 =
      0 renders + 0 LLM calls — no baseline-`.docx` editing (re-assembly is cheap). +3 tests.
    - **M-C Phase-2 derive scoping.** (1) behaviour-name LLM calls (~23s, scoped but uncached) now cached (keyed by
      prompt); (2) `enrich_functions_rich` computes the work set FIRST and returns BEFORE building the O(model) RepoMap
      infra (~20s) when nothing needs a description. +2 tests.
    - **M-D true `--no-llm`.** `generate.apply_no_llm(cfg)` sets `llm.descriptions=False`+`behaviourNames=False`; DOCX
      unit summary gated on descriptions; `flowcharts.py` passes `--no-llm` → flowchart engine `_NullLlmClient` (empty
      response → fallback labels). Fully LLM-free deterministic run; verified e2e on a no-gateway host (0 LLM calls,
      full gen in ~14s). +2 tests. *(Keeps `--no-llm-summarize` as the granular knob.)*
    - **Net:** a re-run / unchanged-component / fully-cached incremental drops Phase 2 + Phase 4 from ~93s toward
      near-0; the first run of a NEW diff still pays the real cost for CHANGED entities only (correct). Caches at
      `<project_root>/.mmdc_cache` + `.flowchart_cache/aux_descriptions`.
- **Next concrete step:** **M4 + PERF M-A…M-D complete.** The incremental feature (engine, stores, cross-version
  reuse, narrowed parse + `--verify-parse`, and Phase 2/3/4 caching) is implemented. Remaining are *validation /
  graduation*, not new milestones: (1) **LLM-on timing validation on the office machine** — confirm Phase 2 + Phase 4
  collapse on a re-run (the M-A…M-D payoff) and that `--no-llm` gives 0 LLM calls; (2) run `--verify-parse` across a
  diff matrix on a real (large) repo, then flip narrowed parse opt-in → default; (3) a perf measurement on that repo.
  Optional: scope the RepoMap build to the impact neighbourhood (cut the ~20s even for a few changed); exact list-ORDER
  byte-identity (set-equal is the correctness bar today). After that: **M5** Postgres, **M6** object storage/dedup.
- **Testing convention:** `_probe_*.py` (run once, delete) + end-to-end on `SampleCppProject`; run **LLM off**
  to validate the logic (hashing / diff / impact / reuse counts), LLM on only for the time-savings payoff.

### 23.6 Analyzer changes M1/M2 will make
`run.py` (`--config`/`ANALYZER_CONFIG`, `--incremental`); `core/config.py` (honor `ANALYZER_CONFIG`);
`parser.py` (partial-parse; entity hashing; slim type/macro index); `model_deriver.py` (incremental mode;
extend `EntityCache`); `views/flowcharts.py` (restrict the engine's functions file to the impact set; the
`engine/flowchart/` engine itself is unchanged); new `engine/incremental/` — incl. `stores.py` (D9 interface:
`VersionStore`/`ReuseIndex`/`HashStore`/`EdgeStore`, JSON-file impl now, Postgres later) that all version /
hash / edge / reuse-index access goes through.

### 23.7 Key `version4` commits (this session)
`a2edee1` bring-over backend+docs · `3498153` PROJECT_CONTEXT merge · `1cf4eb5` backend→layers/component ·
`082ec8b` backend doc corrections · `a74a560` **git_service** · `4651fe9` + `d1ee2bd` + `98b2ce1` doc 04
(incremental approach → slim edges + pointer index) · `8ea45a2` doc 05 (UI API spec). Branch is pushed to
`origin/version4`.

---

## 24. Frontend — `frontend/designs/`

Branch: `feat/frontend-app`. HTML design mockups in `frontend/designs/` are the reference specs; the working React app lives in `frontend/app/` (Vite + React + TS + Tailwind v4) and ports each design 1:1. Full UI context in `frontend/UI_CONTEXT.md`.

> **On `feat/web-app-api-port` the app moved to `web-app/` and is wired to the live FastAPI API (§19), not mock data.** The detail below describes the earlier `frontend/app/` mock-data state. For the current app, read the web-app docs directly: the **`ui-dev` skill** (`.claude/skills/ui-dev/`, engineering rules — was `web-app/CONVENTIONS.md`), **`web-app/INTEGRATION_NOTES.md`** (API wiring, per-page gaps), **`web-app/TESTING.md`** (vitest unit + `npm run test:api` contract suite).

**Team-facing doc:** `frontend/app/README.md` — stack, run commands, folder structure, and the core conventions (tokens-not-hex, read data through `hooks/`, thin pages, commit style). `UI_CONTEXT.md` covers the product/design *what & why*; the README covers the engineering *how*.

### Design system

- Tailwind CSS + Material Symbols Outlined (self-hosted via the `material-symbols` npm package — `@import "material-symbols/outlined.css"` in `web-app/src/index.css`; no Google Fonts `<link>`, fully offline)
- Fonts: Inter (body/headlines), JetBrains Mono (labels/code)
- Color tokens: navy `#041627`, blue `#0058be`, green `#00a572`

### Page inventory

| # | File | Sidebar | Subbar | What it covers |
|---|------|---------|--------|----------------|
| 1 | `signin.html` | none | no | Two-panel auth: branding left, SSO + email/password form right |
| 2 | `projects.html` | 220px | yes | All-projects table; ADMIN/DEV badges, row kebab menu (Settings / Archive / Delete) |
| 3 | `projects-empty.html` | 220px | yes | Empty state + 5-step onboarding wizard; Request Project Access modal |
| 4 | `project-detail.html` | 220px | yes | Project overview: KPI cards, generation progress, documents table, team list, review queue, function-visibility slide-over, Run Analysis modal, Admin/Developer role switcher |
| 5 | `documents.html` | 56px collapsed | yes | Document list: process filter tabs, status/assignee filters, batch actions, edit-section modal, assign-reviewers slide panel |
| 6 | `compare.html` | 56px collapsed | yes | Split diff: reference left / current right; per-section Accept/Decline/Edit; review footer with progress dots |
| 7 | `versions.html` | 56px collapsed | yes | Tagged version cards (In Review / Approved); untagged commits timeline; filter tabs |
| 8 | `team.html` | 220px | yes | Team table: role dropdowns, pending invites, Invite Member modal, permission legend |
| 9 | `projects-portfolio.html` | none | no | Org-level (portfolio) variant of the main Projects screen for a new role **above** project admin: a portfolio roll-up above the unchanged projects table — 4-card KPI strip (projects · overall approval % · in-review backlog · needs-attention), then a 3-panel insight row (Projects-by-status donut, Needs-attention list → `project-detail.html`, Review-workload bars). Role surfaced via an `ORG ADMIN` header pill. Static design artifact only; roll-up numbers derived from the same 5 sample rows as `projects.html` so the strip matches the table |

### React app implementation (`frontend/app/`)

The Vite + React + TS app under `frontend/app/` ports every design HTML to a route. As of `98af777` all screens — **including the five inner pages** — are faithful 1:1 ports of their design HTML. (Earlier those five were simplified sketches missing 50–80% of the design DOM — panels, KPI strips, sub-bars, state variants, detail rows; rebuilt 2026-06-22.)

| Design HTML | React page (`src/pages/`) | Route |
|---|---|---|
| `signin.html` | `SignInPage.tsx` | `/signin` |
| `projects.html` | `ProjectsPage.tsx` | `/projects` |
| `projects-empty.html` | `ProjectsEmptyPage.tsx` | `/projects/new` |
| `project-detail.html` | `ProjectDetailPage.tsx` | `/projects/:projectId/overview` (index) |
| `documents.html` | `DocumentsPage.tsx` | `/projects/:projectId/documents` |
| `compare.html` | `ComparePage.tsx` | `/projects/:projectId/compare` |
| `versions.html` | `VersionsPage.tsx` | `/projects/:projectId/versions` |
| `team.html` | `TeamPage.tsx` | `/projects/:projectId/team` |

`/` and unmatched paths redirect to `/projects`; all non-auth routes are wrapped in `ProtectedRoute`.

- **Shared shell**: the four project-scoped routes render inside `ProjectLayout` → `Sidebar` + `Topbar` + `Subbar` + `<Outlet>`.
- **Data**: `@tanstack/react-query` hooks (`useProject` / `useDocuments` / `useTeam` / `useVersions` / `useCommits`) over mock data in `src/data/mock.ts` (5 projects, 15 documents, 9 team members incl. 1 pending, 3 versions, untagged commits).
- **State**: Zustand `ui` store holds `roleView` (Admin/Dev toggle in the Topbar — drives admin-vs-developer page content) + `sidebarCollapsed`; `auth` store (persisted) gates `ProtectedRoute`. Page state (never / running / in_review / complete / stale) is driven per-project by `project.pageState`, **not** a dev toolbar.
- **Tailwind v4** (`@import "tailwindcss"` + `@theme {}`, no config file). The design HTML uses the Tailwind **v3** CDN, so its named type-scale classes (e.g. `text-body-md`, `font-label-sm`) are not portable — ported with explicit inline styles / v4 utilities. Verify production builds with `npm run build` (`tsc -b` catches `Record<DocStatus,…>` exhaustiveness errors that `tsc --noEmit` misses).

### Shell rules

**Sidebar** — context-progressive:
- `signin.html` and `projects.html` have **no sidebar** — full-width, logo top-left.
- All project-scoped pages (4–8): **project sidebar** (220px expanded / 56px collapsed):
  - `← All Projects` → `projects.html`
  - Project name label (10px uppercase)
  - Overview → `project-detail.html` · Documents → `documents.html` · Compare → `compare.html` · Versions → `versions.html` · Team → `team.html`
  - Settings at bottom (below `border-t`)
- `documents.html`, `compare.html`, `versions.html` default to **collapsed (56px)**.

**Subbar** (all project-scoped pages):
```
[ 📁 VCU Engine Firmware ▾ ]  ·  [ v1.2.0 ▾ ]  ·  ⑂ main @ d9a0c55  ·  Jun 15    [CTA]
```
- CTAs: project-detail `[▶ RUN ANALYSIS]`, documents `[↓ Download All]`, compare `[✓ Accept All] [✗ Reject All]`, team `[+ Invite]`, versions — none

**Breadcrumbs** — always start with `[⬡]` home (→ `projects.html`):
`Overview` · `Documents` · `Documents / Compare` · `Versions` · `Team`

### Navigation flow

```
signin.html → projects.html (no sidebar)
  └─ click row → project-detail.html (220px sidebar)
       ├─ Documents → documents.html (56px) → Compare → compare.html (56px)
       ├─ Versions  → versions.html (56px)
       └─ Team      → team.html (220px)
```

---

_End of file._
