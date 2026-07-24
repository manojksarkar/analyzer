---
name: engine-behaviour
description: >-
  The behaviour-diagram developer role (one engineer's domain) — Mermaid SEQUENCE diagrams showing how
  external units/components call into a unit. Load this BEFORE editing engine/behaviour_diagram/
  (SequenceDiagramGenerator, CallChainTracer, MermaidBuilder, the CallDescriptionGenerator LLM path, the
  diagram selector) or its Phase-3 view engine/views/behaviour_diagram.py. Distinct from the behaviour-NAME
  derivation (behaviourInputName/OutputName, in model_deriver → engine-dev) and the flowchart/CFG engine
  (→ engine-flowchart).
---

# Role: behaviour diagrams (`engine/behaviour_diagram/`)

You own the **behaviour (sequence) diagrams** — generated **when a unit is called by external
units/components** (one diagram per external caller), plus the LLM call-description that annotates them.

> TL;DR: **sequence diagrams of *external caller → current unit*** · a **standalone package** with its own
> CLI + LLM description path · runs **in-process as a Phase-3 view** (`@register("behaviourDiagram")`), then
> renders PNG via `mmdc` · **not** the behaviour-*name* derivation (that's `engine-dev`).

Start context (read as needed, don't duplicate here):
- **Deep detail / how it plugs into the pipeline** → root [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md), and `engine-dev`.
- The package is self-describing — start at [generator.py](engine/behaviour_diagram/generator.py) and the
  view [views/behaviour_diagram.py](engine/views/behaviour_diagram.py).

## 1. The package (`engine/behaviour_diagram/`)

- **`generator.py` — `SequenceDiagramGenerator`** (orchestrator): loads `components.json` / `units.json` /
  `functions.json`, builds function→unit→component maps, and per function emits one Mermaid **sequence
  diagram per external caller** — participants = caller unit + current unit; messages = the inbound call,
  then forward calls one hop. `generate_all_diagrams(fid, out_dir)` → `(mmd_paths, behaviour_descriptions)`.
- Supporting modules: **`tracer.py`** (`CallChainTracer` — walks the call graph) · **`mermaid_builder.py`**
  (`MermaidBuilder` — sequence-diagram source + component colours) · **`llm_call_description.py`**
  (`CallDescriptionGenerator` — the LLM path that writes each diagram's behaviour description) ·
  **`selector.py`** (`create_diagram_selector` — which diagrams to emit; default
  `single_per_external_component`) · `utils.py` · `cli.py` (standalone entry).
- **Own LLM path:** descriptions come from `CallDescriptionGenerator`, not `engine/llm_enrichment.py`.

## 2. The view & output (`engine/views/behaviour_diagram.py`)

- **`@register("behaviourDiagram")`** — note the exact key (**singular**). Runs **in-process** in Phase 3 (it
  imports the generator directly — unlike the flowchart engine, which is a subprocess). Off unless
  `config.views.behaviourDiagram` is enabled.
- Per non-private function with **external callers** (external = different component, or outside the selected
  group), it generates the `.mmd`(s), renders each to **PNG via `mmdc`** (`--scale 2`,
  `engine/config/puppeteer-config.json`), and writes `output/<group>/behaviour_diagrams/_behaviour_pngs.json`
  → `_docxRows` (component → unit → `[{currentFunctionName, externalUnitFunction, pngPath, behaviorDescription}]`).
- **Consumers:** `docx_exporter` embeds the PNGs + descriptions in the §2.N **Dynamic Behaviour** section;
  **SWE.4** reads the same rows for its Dynamic Behaviour specs.

## 3. Boundaries

- **Behaviour *diagrams* (here) ≠ behaviour *names*.** `behaviourInputName` / `behaviourOutputName` (and
  direction) are derived in `model_deriver` → **`engine-dev`**; this package doesn't use them.
- **Not the flowchart/CFG** control-flow diagrams (→ `engine-flowchart`). Both render Mermaid + PNG, but
  these are *sequence* diagrams of cross-unit calls, not intra-function control flow.
- Reads the model (`components` / `units` / `functions.json`) — if those shapes change, coordinate with `engine-dev`.

## Before you finish
- New behaviour-diagram logic? Still **one diagram per external caller**, private functions skipped, PNG via `mmdc`.
- Description change? It flows through `CallDescriptionGenerator` (this package's LLM path), not the main enrichment.
- Meaningful change? Update PROJECT_CONTEXT.md — pair with `docs-maintainer`.
- Touching behaviour-*name* derivation, the model schema, or the DOCX exporter? That's `engine-dev`.
