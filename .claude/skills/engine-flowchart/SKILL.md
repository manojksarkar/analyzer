---
name: engine-flowchart
description: >-
  The flowchart/CFG + incremental-engine developer role (one engineer's domain). Load this BEFORE editing
  engine/flowchart/ (libclang CFG extraction, Graphviz DOT rendering, PKB, local-LLM node labels) or
  engine/incremental/ (git-diff narrowed parse, stored-graph impact, selective regeneration). Carries the
  deterministic-CFG-vs-LLM-label split, the flowchart engine's standalone subprocess + its own LlmClient,
  the knowledge_base.json bridge, and the version4 incremental engine (hashing, impact BFS, reuse). NOT the
  main pipeline/doc-gen (→ engine-dev) or behaviour diagrams (→ engine-behaviour).
---

# Role: flowchart / CFG + incremental engine

You own two `engine/` subsystems (same engineer):
- **`engine/flowchart/`** — C++ → Graphviz DOT flowcharts (libclang CFG + local-LLM labels).
- **`engine/incremental/`** — version4 git-diff narrowed-parse + stored-graph impact + selective regen.

> TL;DR: **the CFG is deterministic; the LLM only writes node *labels*** · the flowchart engine runs as a
> **standalone subprocess with its own `LlmClient` + `EngineConfig`** (not `engine/llm_enrichment.py`) ·
> **persisted: the DOT string + a lossy serialized CFG** — the full `ControlFlowGraph` is rebuilt on
> demand · node labels are **reviewer-correctable** · incremental = **full parse, selective *work***
> (reuse unchanged descriptions/outputs; carry reviewer corrections).

Start context (read as needed, don't duplicate here):
- **Flowchart deep dive** → [engine/flowchart/README.md](engine/flowchart/README.md) + the end-to-end trace
  [engine/flowchart/FLOW.md](engine/flowchart/FLOW.md).
- **Incremental design** → [docs/production-redesign/04-incremental-changes-implementation.md](docs/production-redesign/04-incremental-changes-implementation.md).
- **How these plug into the pipeline / everything else** → root [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (the
  index; the flowchart engine is §13 in [VIEWS_AND_EXPORT.md](project-context/VIEWS_AND_EXPORT.md), incremental
  is §23 in [INCREMENTAL.md](project-context/INCREMENTAL.md)), and `engine-dev`.

## 1. Flowchart engine (`engine/flowchart/`)

- Runs as a **child subprocess** launched by [views/flowcharts.py](engine/views/flowcharts.py) (Phase 3):
  `config.views.flowcharts.scriptPath` → [flowchart_engine.py](engine/flowchart/flowchart_engine.py). Reads
  `model/functions.json` + `model/knowledge_base.json`; writes `output/<group>/flowcharts/<stem>.json`.
- **Structure:** `ast_engine/` (`CFGBuilder`, `TranslationUnitParser`, resolver's 3-strategy
  `find_function_cursor`) · `enrichment/` (`NodeEnricher`) · `llm/` (`LabelGenerator` batching/retry/
  coherence, `LlmClient`) · `dot_builder.py` (`build_dot` — CFG → Graphviz DOT) · `mermaid/`
  (**now partly legacy** after the DOT switch: `validate_cfg` + `normalize_edge_label` still used by
  `dot_builder`; `validate_mermaid`/`builder.py` are dead) · `pkb/` (`ProjectKnowledgeBase` + MD5-keyed
  `PkbCache`) · `output/writer.py`. Types in [models.py](engine/flowchart/models.py): `CfgNode`, `CfgEdge`,
  `ControlFlowGraph`, `NodeType` (START/END/ACTION/DECISION/LOOP_HEAD/SWITCH_HEAD/RETURN/CASE/
  BREAK/CONTINUE/TRY_HEAD/CATCH).
- **The CFG is deterministic; the LLM only labels nodes.** Structure comes from
  `CFGBuilder.build(func_cursor, func_entry)`; the LLM turns raw code into readable labels, with
  deterministic **fallback labels** when it fails. Never let the LLM decide structure.
- **Rendering is Graphviz DOT, not Mermaid** (switched 2026-07-27). `build_dot(cfg)` emits the DOT;
  `engine.utils.render_dot_cached` renders it (viz-js DOT→SVG → puppeteer PNG, content-addressed
  `.dot_cache`). `dot_builder` is **label-only + layout** — it never changes CFG structure: it
  **word-wraps long node labels** (`_wrap_label`, breaks at spaces only, `_LABEL_WRAP_WIDTH`, never splits
  identifiers) so wide nodes grow down not out, uses **default curved splines** (no `splines=ortho`), and
  anchors Return/End at the bottom via `constraint=false` back-edges + invisible push-down edges. `goto` is
  a real node with a deferred edge to its target label (not a jump to exit).
- **Persisted: the DOT string and a serialized CFG** (`[{functionKey, name, flowchart, cfg}]`; the
  `FlowchartResult` field is still named `mermaid_script` for schema compat but holds DOT). `cfg` is
  `serialize_cfg(cfg)` (since 3355930) — what SWE.4's Test Steps read and what review redraws from. It
  is **lossy** (`label or raw_code` collapse into one field; no line numbers, no qualified name), so
  **re-materialize via `CFGBuilder`** when you need the full graph (what SWE.4's deferred pass and
  `tools/swe4-derivation-spike/` do).
- **Own LLM stack:** a standalone `LlmClient` (Ollama + OpenAI formats) + `EngineConfig` dataclass, fed the
  `config.llm` settings via CLI flags. Don't reach into `engine/llm_enrichment.py` or the main `config.json`
  from here.
- **Determinism is tested without the LLM** — CFG + topological-sort invariants and CFG-node-type-count ==
  DOT-shape-count checks (see the README **Testing** section). Debug prompts with `FLOWCHART_TRACE=1`.
- ASSERT macros are pre-scanned so they don't become DECISION nodes.
- **Node labels are reviewer-correctable** (`nodeLabel` slots: flowchart id + node id; engine-dev §8).
  Phase 3 puts corrections back before rendering (`views/flowcharts._apply_text_overrides`). A correction
  made later is redrawn from the stored `cfg` through `models.cfg_for_rendering` → `build_dot`
  (`engine/review/redraw.py`), so `cfg_for_rendering` must keep restoring every field `build_dot` reads.
  A node id is a *position*: a builder change that renumbers nodes makes `slot_shape` (a hash of the
  node-id list) disagree, and the correction is dropped (Phase 3) or orphaned (carry-forward) instead of
  landing on the wrong box — REQ-ID-02, HANDOVER §4.13.
- **Labels are written from descriptions too.** The context packet — purpose, callers, the callee
  hierarchy, globals — reads the knowledge base Phase 2 wrote; `_with_current_descriptions` lays the
  model's descriptions over it before the first chart the LLM labels (`pkb.knowledge.overlay_descriptions`).
  An update rewriting the charts a description correction reached runs the engine with
  `--rewrite-labels <request> --only-rewrite` (`_label_chart`): those charts skip the label cache —
  keyed by the source, which a correction does not move — and `_replace_labels` replaces the entry; a
  chart with a fallback label keeps its earlier labels and is not reported. The view splices them into
  the stored charts (`views/flowcharts._splice_rewritten`). The label cache buffers its writes:
  `_flush_labels` at the end of `run()` lands them (HANDOVER §4.37, §4.39).
- **A Word picture only for a printed chart.** The view draws PNGs for the charts the directory's
  SWE.3 document prints — public functions' flowcharts and their private callees' — by the exporter's
  own rule, `docx_common.printed_flowcharts` (`_pictures_to_draw`). Change which flowcharts the exporter
  prints only through `docx_common.flowchart_section` / `private_callee_flowcharts`, or a printed chart
  ends up with no picture.

## 2. Incremental engine (`engine/incremental/`)

- **"Approach 2" (version4)** — [engine.py](engine/incremental/engine.py) `generate_incremental()`:
  baseline-pick → checkout → parse → classify vs baseline hashes → **impact BFS** → carry the reuse set's
  outputs forward → regenerate only the impact set → reassemble via the main Phase 3/4 → record version.
- **Full parse, selective *work*.** The call graph is always complete, so impact analysis can't go stale;
  the win is skipping unchanged **LLM work** — the `EntityCache` under `<repo>/.flowchart_cache` (composite
  source+callee hash) reuses unchanged descriptions, and this engine carries per-version output snapshots
  forward (`_CARRY_FIELDS`: description, inputName, outputName, comment, phases).
- **Its own model files** (constants in [core/model_io.py](engine/core/model_io.py), deliberately **not** in
  `ALL_MODEL_NAMES`): `HASHES`, `EDGES`, `TU_INCLUDES`, `ENTITY_FILES`, `FUNC_KEYS`, `OVERRIDE_PAIRS` —
  produced by Phase 1 for change detection/impact. The main pipeline ignores them.
- **Planning helpers are pure** (`plan_incremental`, `classify`, `impact_set`) — unit-test them directly;
  `generate_incremental` does the I/O. Modules include `git_ops`, `hashing`, `fingerprint`, `affected`
  (affected TUs), `parse_merge` (narrowed-parse merge + cross-TU edge re-resolve from baseline `FUNC_KEYS`),
  `baseline`, `stores` (workspace / version / hash / edge stores + `ReuseIndex`), `report`.
- **Reviewer corrections travel with the version.** Once the baseline is chosen,
  `_carry_review_overrides(base_vid, version_id)` copies its `text_overrides` onto the new version
  (`engine/review/carry_forward.py`) and orphans any whose entity changed. Keep that call — dropping it
  in a merge fails only `test_review_pipeline_wiring.py` (HANDOVER §4.4). The same call copies the
  regeneration queue's still-owed entries (`carry_queue`) — names and chart labels included, which no
  generation rewrites; every queued kind needs its rule in `_queue_entry_applies` (HANDOVER §4.31).

## 3. Boundaries

- **`knowledge_base.json` is the bridge** into the flowchart engine — **built by `engine-dev`'s
  `model_deriver._generate_knowledge_base()`** (Phase 2), consumed here. Changing its shape → coordinate
  with `engine-dev`.
- **Consumers of your output:** the DOCX exporter embeds the DOT-rendered PNGs; **SWE.4's deferred
  boundary/equivalence pass** borrows `CFGBuilder`. Behaviour diagrams are a *separate* view (→ `engine-behaviour`).
  The **web reader shows server-drawn SVGs** — `views/flowcharts.write_flowchart_svgs`, every run, one Node
  process (`engine/config/render_svg.mjs`); name / box count / 500-box limit / content key live in
  `engine/core/flowchart_svg.py`, shared with `api/services/doc_render.py`. The DOT never reaches the browser.
  Backfill old runs: `tools/render_flowchart_pngs.py --project ID | --all`.

## Before you finish
- Structure change? The **CFG stays deterministic** — the LLM only labels; the CFG/topo + shape-count checks still pass (no LLM needed).
- Changed what `serialize_cfg` writes or what `build_dot` reads? `cfg_for_rendering` must still rebuild the
  same picture (`tests/unit/test_cfg_for_rendering.py` compares the two DOT strings).
- Incremental change? Pure planners unit-tested; reuse/impact accounted; the version4 model files stay consistent.
- CFG builder change that renumbers nodes? Label corrections on those flowcharts orphan by design — say so
  in PROJECT_CONTEXT, and run `pytest tests/unit/test_review_*.py`.
- Meaningful change? Update the project context (`project-context/`: topic file + dated history entry) + the
  flowchart README/FLOW.md — pair with `docs-maintainer`.
- Touching the model schema, doc-gen, or the main LLM/config? That's `engine-dev`.
