# Status boards of 2026-07-20 and 2026-08-14 — historical

> **Project context — old status boards.** Start at [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md),
> whose **Current state** section replaces these. They headed the single-file context until
> 2026-09-28 and are kept here unchanged except link paths. **Not current:** the database-native
> pipeline (doc 10) they call "planned, not started" has landed; treat their other open items
> as unverified.

> **⭐ WORK STATUS — 2026-08-14 · branch `db-with-increment-changes` (READ THIS FIRST in a new chat).**
> - **The PostgreSQL migration is COMPLETE and validated on the office box.** Postgres holds the model,
>   view outputs, reuse index, run metadata, resolved config and all app data. `JsonDatabase` is deleted;
>   the API is Postgres-only. The commit dir now holds ONLY the git checkout + `manifest.json` + `report.txt`
>   + `parse/`. Full detail: the dated entry below (2026-08-13) and §6.
> - **NEXT WORK IS PLANNED, NOT STARTED → [docs/production-redesign/10-db-native-pipeline.md](../../docs/production-redesign/10-db-native-pipeline.md)**
>   (2026-08-17). Removes `model/*.json` from the pipeline itself: all four phases **and** the
>   flowchart engine read/write their model from the database; SQLite becomes a supported backend so
>   the gates run on a machine with no Postgres; no environment variable remains a source of our
>   configuration. That doc is the source of truth for what to do next — 10 steps, gates after each,
>   with a **sign-off stop at step 8** before anything is deleted.
> - Doc 09 is **largely done** — see [09-post-migration-consolidation-plan.md](../../docs/production-redesign/09-post-migration-consolidation-plan.md)
>   for the remainder (concurrency raise pending its RSS measurement; C4/C7 context service; IN-4/IN-5).
> - **B0 DONE (2026-08-14):** the `job_max_concurrency` **default is now 1**
>   ([settings.py:47](../../api/services/settings.py#L47)). `<repo>/output` is gone too — runs render into
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
>   view is NOT yet ported to DOT** (open follow-up — **done 2026-09-30b**: server-drawn SVGs, see that
>   dated note). Verified e2e via the engine CLI on `SampleCppProject`
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

