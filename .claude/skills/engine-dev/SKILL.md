---
name: engine-dev
description: >-
  The engine/ developer role — the Python pipeline that turns parsed C++ into ASPICE documents (SWE.3/SWE.4).
  Load this BEFORE writing or editing any engine/ code: the parse→derive→views→export pipeline, the model
  schema, views + DOCX exporters, LLM enrichment, config, orchestration, or engine tests. Carries the
  pipeline / registry / model-IO / determinism / testing conventions and points into PROJECT_CONTEXT.md for
  depth. Excludes the flowchart/CFG + incremental engine (→ engine-flowchart) and behaviour diagrams
  (→ engine-behaviour).
---

# Role: engine developer (`engine/`)

You own the **analysis + document-generation pipeline** in `engine/` — parsing C++, deriving the model,
building views, exporting DOCX — **except** two carved-out areas:
- **flowchart / CFG + the incremental (narrowed-parse) engine** → `engine-flowchart`
- **behaviour diagrams** → `engine-behaviour`

> TL;DR: **4 phases, run as subprocesses** (parse → derive → views → export) · **one shared model → every
> doc** · **views read the model + logic, never another view's output** · **doc type is a *dimension*, not a
> phase** · **LLM is cached + grounded → deterministic** · test with the `Sample` fixture + `pytest --skip-pipeline`.

Start context (read as needed, don't duplicate here):
- **Everything — pipeline, schema, flags, views, DOCX, LLM, risks, decisions** → root
  [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (agent-facing source of truth; read it first, per CLAUDE.md).
- **Doc contracts** → [docs/spec/SWE3_SPEC.md](docs/spec/SWE3_SPEC.md), [docs/spec/SWE4_SPEC.md](docs/spec/SWE4_SPEC.md).
- **Carved-out areas** → `engine-flowchart` (flowchart/CFG + incremental), `engine-behaviour`.

## 1. Pipeline & orchestration

Four phases. **Each is a separate Python subprocess**; they communicate through `model/*.json` and
`output/` on disk, not in-process calls.

| Phase | Script | Produces |
|---|---|---|
| 1 Parse | `parser.py` | `model/*.json` (libclang AST → schema) |
| 2 Derive | `model_deriver.py` | units, components, call-graph, global-access, LLM descriptions |
| 3 Views | `run_views.py` | `output/<group>/*.json` (+ flowchart assets) |
| 4 Export | `docx_exporter.py` | `output/<group>/software_detailed_design_<group>.docx` |

- Orchestration: [core/group_planner.py](engine/core/group_planner.py) (`plan_runs` → `RunPlan`s) +
  [core/orchestration.py](engine/core/orchestration.py) (`Phase`, `PhaseRunner`). The model (Phases 1–2) is
  built **once**; Phases 3–4 run **per group**.
- **Dev-speed flags** ([run.py](engine/run.py)): `--use-model` (skip Phase 1/2, reuse `model/`),
  `--from-phase N` / `--to-phase N`, `--no-llm-summarize`. Build the model once, then iterate views/export
  with `--use-model` — no re-parse, no LLM cost.

## 2. Model & schema

- **All model IO goes through [core/model_io.py](engine/core/model_io.py)** — canonical name constants
  (`FUNCTIONS`, `GLOBALS="globalVariables"`, `UNITS`, `COMPONENTS`, `DATA_DICTIONARY`, `KNOWLEDGE_BASE`, …),
  `load_model(*required, optional=…)`, `read/write_model_file`. Never inline `json.load` against `model/*.json`.
- **Provenance:** Phase 1 (parser) → raw facts (parameters, types, return, visibility, location, globals +
  their initializer `value`). Phase 2 (deriver) → units/components, call-graph (`callsIds`/`calledByIds`),
  global-access (`reads/writesGlobalIdsTransitive`). **Descriptions are the only LLM-derived model fields.**
- **Two facts that bite** (verified): **locals are not in the model** (the parser records only local decl
  *types*); a **global carries a `value` only when its declaration initializes one**.
- The incremental-engine model files (`HASHES`, `EDGES`, `TU_INCLUDES`, `ENTITY_FILES`, …) belong to
  `engine-flowchart` — don't touch them here.

## 3. Views & doc generation

- **Views self-register** in [views/registry.py](engine/views/registry.py) via `@register("name")` →
  `VIEW_REGISTRY`; [views/__init__.py](engine/views/__init__.py) `run_views` runs each **enabled** one
  (`config.views.<name>`; only `interfaceTables` defaults on). A view is `run(model, output_dir, model_dir, config)`.
- **A view reads the in-memory `model` + shared logic (e.g. `get_range` in [utils.py](engine/utils.py)) and
  writes its own `output/<group>/<name>.json`. It must NOT read another view's output** — see
  [views/interface_tables.py](engine/views/interface_tables.py) as the template.
- **Doc type is a *dimension*, not a phase.** Exporters (`docx_exporter.py`; the planned `EXPORTER_REGISTRY`
  mirrors `VIEW_REGISTRY`) diverge per doc type; Phases 1–3 stay doc-type-agnostic. Adding a doc type
  (SWE.4/SWE.2) = register a view + an exporter, **no new phase**.
- **DOCX** is built with **python-docx** in `docx_exporter.py`. Shared table/heading helpers are being
  factored into `docx_common.py` as more exporters land — reuse them, don't copy (keeps `docx_exporter.py`
  and `api/services/doc_render.py` from drifting).

## 4. LLM enrichment

- **Single entry:** `_call_llm(prompt, config, *, system="", kind="default")` in
  [llm_enrichment.py](engine/llm_enrichment.py). `kind` tags the call site (`description`, `behaviour_names`, …).
- **Cached + deterministic:** calls are content-addressed and honour `llm.cacheVersion` — same input → same
  output on rerun. Bump `cacheVersion` to invalidate.
- **Grounded, not free-associating:** description prompts append the project **domain context**
  (`llm.domainContextPath`) so the model uses real vocabulary (Task 3.14); few-shot via `FewShotPool`
  (`llm_core.few_shot`).
- **Philosophy:** deterministic facts stay deterministic; the LLM only **synthesises** (descriptions, names,
  test cases) *grounded* in those facts — it never invents structure. New LLM work follows the same
  cache + grounding shape.

## 5. Config

- Base `config.defaults.json` ([config/config.defaults.json](engine/config/config.defaults.json)): `clang`, `views` (per-view enables),
  `layers.<Layer>.groups.<Group>.<Component>`, `llm`, `docx.*`. Read via `app_config()` in
  [core/config.py](engine/core/config.py); `ANALYZER_CONFIG=<path>` overrides the file.
- `DEFAULT_VISIBILITY_MACROS` (`PUBLIC`/`PRIVATE`/`PROTECTED`/`__OVLYINIT`) are always injected as `-D…=`
  so libclang parses visibility-tagged code — distinct from the user `--macros` CSV.

## 6. Testing

- Fixture **`SampleCppProject`**, group **`Sample`**; the pipeline runs once in [tests/conftest.py](tests/conftest.py)
  for e2e. **`pytest --skip-pipeline`** reuses existing `output/` — use it for unit/planner tests; don't
  trigger a full pipeline.
- **e2e = structural, not golden-binary** ([tests/e2e/test_docx.py](tests/e2e/test_docx.py)): open the
  `.docx`, assert headings/tables/values. **Snapshots** (`tests/snapshots/Sample/*.json`, regenerate with
  `--update-snapshots`) guard view-JSON determinism.
- Determinism is a contract: a rerun on unchanged input reproduces byte-identical output.

## 7. Commits

Short, prefixed (`feat:`, `fix:`, `refactor:`, `docs:`). **No "Claude" mentions, no co-author trailer.**

## Definition of done — every output-rule change

The list the user should not have to retype. A rule change is not done until all six:

1. **Fix** the code.
2. **Fixture** — add the scenario to `SampleCppProject`, one file or class per behaviour. A rule with
   no fixture is a rule nobody can check. Mind the placement gotcha: a file outside a mapped component
   dir is silently excluded from the parse.
3. **Tests** — extend the existing test module, don't start a new one. Assert the new row **and** the
   case that must stay excluded.
4. **Before/after** — run the pipeline both ways and show the actual cells that changed. Turn
   `llm.descriptions` + `llm.behaviourNames` off (`--no-llm`), or it is minutes of LLM for nothing.
   Documents come out per **group** (`--scope "group:L.G"`) or per component — a `layer:` scope writes
   the model and **no documents**. Reading a `.docx` back: `tools/dump_docx.py`, but it flattens cell
   line breaks to ` // `, so check a real cell with `python-docx` before believing a cell is ugly.
5. **Docs** — output-visible rule → `docs/spec/SWE3_WIKI.md` (client-facing; tables, prose only where
   rationale needs it; an undecided rule goes in as a `⚠ To confirm`, never as a rule). Mechanism, gaps
   and the matrix → `PROJECT_CONTEXT.md` + its `> Updated:` log.
6. **Every consumer** — an output rule has more than one implementation:
   - `engine/docx_exporter.py` — the DOCX, and the only one that reads the C++ source
   - `api/services/doc_render.py` — the web view, model JSON only, no source access
   - `tools/doccheck/` — the comparison must be able to SEE the difference, or a client review reports
     your change as a defect
   - `tests/snapshots/Sample/*.json` — regenerate with `--update-snapshots` if view JSON moved

## Before you finish
- Touched a phase? It still runs **standalone as a subprocess** — the phase boundary is files on disk.
- New view? Registered + config-gated + reads model/logic only (no sibling-view output).
- LLM call? Cached, `kind`-tagged, grounded — rerun is deterministic.
- Meaningful change? Update **PROJECT_CONTEXT.md** (+ its `> Updated:` log) — pair with `docs-maintainer`.
- In a carved-out area (flowchart/CFG, incremental, behaviour diagrams)? Use that spoke skill instead.
