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
> **only the DOT string is persisted** — the structured `ControlFlowGraph` is rebuilt on demand ·
> incremental = **full parse, selective *work*** (reuse unchanged descriptions/outputs).

Start context (read as needed, don't duplicate here):
- **Flowchart deep dive** → [engine/flowchart/README.md](engine/flowchart/README.md) + the end-to-end trace
  [engine/flowchart/FLOW.md](engine/flowchart/FLOW.md).
- **Incremental design** → [docs/production-redesign/04-incremental-changes-implementation.md](docs/production-redesign/04-incremental-changes-implementation.md).
- **How these plug into the pipeline / everything else** → root [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md), and `engine-dev`.

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
- **Only the DOT string is persisted** (`[{functionKey, name, flowchart}]`; the `FlowchartResult`
  field is still named `mermaid_script` for schema compat but now holds DOT) — the structured
  `ControlFlowGraph` is discarded. **Re-materialize it via `CFGBuilder`** when you need branch structure
  (what SWE.4's deferred pass and `tools/swe4-derivation-spike/` do).
- **Own LLM stack:** a standalone `LlmClient` (Ollama + OpenAI formats) + `EngineConfig` dataclass, fed the
  `config.llm` settings via CLI flags. Don't reach into `engine/llm_enrichment.py` or the main `config.json`
  from here.
- **Determinism is tested without the LLM** — CFG + topological-sort invariants and CFG-node-type-count ==
  DOT-shape-count checks (see the README **Testing** section). Debug prompts with `FLOWCHART_TRACE=1`.
- ASSERT macros are pre-scanned so they don't become DECISION nodes.

## 2. Incremental engine (`engine/incremental/`)

- **"Approach 2" (version4)** — [engine.py](engine/incremental/engine.py) `generate_incremental()`:
  baseline-pick → checkout → parse → classify vs baseline hashes → **impact BFS** → carry the reuse set's
  outputs forward → regenerate only the impact set → reassemble via the main Phase 3/4 → record version.
- **Full parse, selective *work*.** The call graph is always complete, so impact analysis can't go stale;
  the win is skipping unchanged **LLM work** — the `EntityCache` under `<repo>/.flowchart_cache` (composite
  source+callee hash) reuses unchanged descriptions, and this engine carries per-version output snapshots
  forward (`_CARRY_FIELDS`: description, behaviourInputName, behaviourOutputName, comment, phases).
- **Its own model files** (constants in [core/model_io.py](engine/core/model_io.py), deliberately **not** in
  `ALL_MODEL_NAMES`): `HASHES`, `EDGES`, `TU_INCLUDES`, `ENTITY_FILES`, `FUNC_KEYS`, `OVERRIDE_PAIRS` —
  produced by Phase 1 for change detection/impact. The main pipeline ignores them.
- **Planning helpers are pure** (`plan_incremental`, `classify`, `impact_set`) — unit-test them directly;
  `generate_incremental` does the I/O. Modules include `git_ops`, `hashing`, `fingerprint`, `affected`
  (affected TUs), `parse_merge` (narrowed-parse merge + cross-TU edge re-resolve from baseline `FUNC_KEYS`),
  `baseline`, `stores` (workspace / version / hash / edge stores + `ReuseIndex`), `report`.

## 3. Boundaries

- **`knowledge_base.json` is the bridge** into the flowchart engine — **built by `engine-dev`'s
  `model_deriver._generate_knowledge_base()`** (Phase 2), consumed here. Changing its shape → coordinate
  with `engine-dev`.
- **Consumers of your output:** the DOCX exporter embeds the DOT-rendered PNGs; **SWE.4's deferred
  boundary/equivalence pass** borrows `CFGBuilder`. Behaviour diagrams are a *separate* view (→ `engine-behaviour`).
  **Note:** the web-app still renders the persisted string client-side **as Mermaid**, so its in-app flowchart
  view is NOT yet ported to DOT (open follow-up) — the DOCX/PNG path is DOT.

## Before you finish
- Structure change? The **CFG stays deterministic** — the LLM only labels; the CFG/topo + shape-count checks still pass (no LLM needed).
- Persisted only the DOT string? (the structured CFG is rebuilt on demand, never stored.)
- Incremental change? Pure planners unit-tested; reuse/impact accounted; the version4 model files stay consistent.
- Meaningful change? Update PROJECT_CONTEXT.md + the flowchart README/FLOW.md — pair with `docs-maintainer`.
- Touching the model schema, doc-gen, or the main LLM/config? That's `engine-dev`.
