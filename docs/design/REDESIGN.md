# Analyzer v2 — Redesign from Scratch

## Table of Contents

1. [Current Architecture Analysis](#1-current-architecture-analysis)
2. [Advantages of the Current System](#2-advantages-of-the-current-system)
3. [Disadvantages and Pain Points](#3-disadvantages-and-pain-points)
4. [Design Goals for v2](#4-design-goals-for-v2)
5. [High-Level Architecture](#5-high-level-architecture)
6. [Core Data Model](#6-core-data-model)
7. [The Artifact Store (Content-Addressable Cache)](#7-the-artifact-store-content-addressable-cache)
8. [Phase Redesign](#8-phase-redesign)
9. [LLM Subsystem Redesign](#9-llm-subsystem-redesign)
10. [Concurrency Model](#10-concurrency-model)
11. [View / Export Plugin System](#11-view--export-plugin-system)
12. [Configuration Redesign](#12-configuration-redesign)
13. [CLI and UX](#13-cli-and-ux)
14. [Directory and Module Layout](#14-directory-and-module-layout)
15. [Migration Path](#15-migration-path)
16. [Risk Assessment](#16-risk-assessment)

---

## 1. Current Architecture Analysis

The current system is a 4-phase pipeline invoked via `run.py`:

```
                     subprocess          subprocess          subprocess          subprocess
  run.py ──────────> parser.py ────────> model_deriver.py ──> run_views.py ──────> docx_exporter.py
                     (Phase 1)           (Phase 2)           (Phase 3)            (Phase 4)
                        │                    │                    │
                        │                    │               views/__init__.py
                        │                    │                 ├── interface_tables.py
                        v                    v                 ├── unit_diagrams.py
                  model/functions.json   model/knowledge_base  ├── behaviour_diagram.py
                  model/metadata.json    model/units.json      └── flowcharts.py
                  model/data.json        model/modules.json          │
                  model/globalVars.json  model/summaries.json        │  subprocess
                                                                     v
                                                          flowchart_engine.py
                                                           ├── ast_engine/
                                                           ├── pkb/
                                                           ├── llm/
                                                           ├── enrichment/
                                                           └── mermaid/
```

Each phase runs as a **separate subprocess**, communicating exclusively through JSON files on disk.

---

## 2. Advantages of the Current System

| # | Advantage | Why it Matters |
|---|-----------|---------------|
| 1 | **libclang-based parsing** | Uses the real compiler frontend — structurally correct AST, handles macros, templates, includes |
| 2 | **CFG built purely from AST** | No heuristics or regex; structurally faithful control flow |
| 3 | **ASSERT macro pre-scan** | O(1) set lookup per cursor; correctly filters assert macros that expand to IF_STMT |
| 4 | **PKB disk cache** | Avoids rebuilding PKB when functions.json hasn't changed |
| 5 | **Rich node enrichment** | Enums, macros, typedefs, struct members resolved and injected into LLM prompts |
| 6 | **LLM batch labeling with auto-halve** | Handles token limit failures gracefully by splitting batches |
| 7 | **Coherence pass** | Second LLM call normalizes terminology/voice across all labels |
| 8 | **Phase resumption** (`--from-phase N`) | Can skip expensive early phases during iteration |
| 9 | **Header file filtering** | Avoids crashes on unparseable standalone headers |
| 10 | **Configurable with local overrides** | `config.local.json` overrides without touching committed config |
| 11 | **View registry pattern** | New views auto-register, clean separation |
| 12 | **4-level hierarchy summaries** | Function → File → Module → Project summaries provide semantic context |

---

## 3. Disadvantages and Pain Points

### 3.1 Duplicate Parsing (Critical)

```
Phase 1 (parser.py):    libclang parse → functions.json    (AST traversal #1)
Phase 2 (model_deriver): imports project_scanner.py        (AST traversal #2 for summaries)
Phase 3 (flowchart_engine): libclang parse AGAIN           (AST traversal #3 for CFG)
```

The **same C++ files are parsed by libclang up to 3 times** per run. Each parse
creates a full TranslationUnit which includes preprocessing, macro expansion, and
type resolution. For a project with 50 files, this triples the total parse time.

### 3.2 Duplicate LLM Calls (Critical)

```
Phase 2 calls LLM for:
  - Function descriptions (_enrich_from_llm)
  - Behaviour names (_enrich_behaviour_names_llm)
  - 4-level hierarchy summaries (_run_hierarchy_summarizer)

Phase 3 calls LLM for:
  - CFG node labels (LabelGenerator)
  - Coherence pass (per-function)
```

There is **no shared LLM call cache** between phases. If you run the pipeline
twice on the same input, every LLM call is repeated. Even within a single run,
Phase 2's LLM descriptions and Phase 3's LLM labels are generated independently
with no knowledge of each other.

### 3.3 No Incremental Processing (Critical)

If you change **1 function** in a 200-function project:
- Phase 1 re-parses **all** files
- Phase 2 re-derives **all** units, re-enriches **everything**
- Phase 3 re-generates **all** flowcharts (no per-function cache)
- Phase 4 re-exports the **entire** DOCX

**No artifact is reused.** The only cache is PKB (keyed by full functions.json hash),
which invalidates on any single-function change.

### 3.4 Subprocess Boundary Waste

```
run.py → subprocess → parser.py        (loads libclang, parses, writes JSON, exits)
       → subprocess → model_deriver.py  (reads JSON, loads libclang AGAIN, writes JSON, exits)
       → subprocess → run_views.py      (reads JSON, launches ANOTHER subprocess:)
                          → subprocess → flowchart_engine.py  (loads libclang AGAIN)
       → subprocess → docx_exporter.py  (reads JSON)
```

**4 subprocess launches + 1 nested subprocess.** Each:
- Reloads Python interpreter
- Re-imports all modules
- Re-reads all JSON from disk
- Re-initializes libclang
- Loses all in-memory state from prior phase

### 3.5 Two Incompatible Data Models

| Aspect | functions.json | knowledge_base.json |
|--------|---------------|---------------------|
| Keys | Internal IDs (`module\|unit\|qualifiedName\|params`) | qualifiedNames |
| Callees | `callsIds` (internal IDs) | `calls` (qualifiedNames) |
| Description | Split: `comment` + `description` | Merged: single `comment` |
| Extra | `calledByIds`, `direction`, `interfaceId` | `signature`, hierarchy summaries |

`_generate_knowledge_base()` (model_deriver.py:495) is a ~100-line translation
layer. The flowchart engine then builds **another** in-memory index (PKB) from
knowledge_base.json. This is 3 representations of the same data.

### 3.6 Other Issues

| # | Issue | Impact |
|---|-------|--------|
| 1 | **No parallel function processing** | Sequential within files; CPU-bound CFG + I/O-bound LLM could overlap |
| 2 | **Retry loop bug** (generator.py:272) | `range(1, self._max_retries)` = 1 attempt, 0 retries with default=2 |
| 3 | **No API key support** in LLM client | Can't use cloud APIs (OpenAI, Anthropic, private endpoints) |
| 4 | **No `response_format: json_object`** | Cloud APIs return markdown-wrapped JSON, causing parse failures |
| 5 | **Hardcoded `MAX_PROMPT_CHARS=6000`** | Wastes 95% of context window on 128k-token cloud models |
| 6 | **`sleep(3)` rate limiter** | Should be configurable; 3s is 10x too slow for most endpoints |
| 7 | **No crash recovery** | Pipeline failure at function N means functions 1..N-1 work is lost |
| 8 | **No output diffing** | Can't tell what changed between runs |
| 9 | **No quality gate** | Labels with "Process data" or "Handle input" pass silently |

---

## 4. Design Goals for v2

| Priority | Goal | Rationale |
|----------|------|-----------|
| P0 | **Never re-parse unchanged source** | Biggest time sink; libclang parse is ~0.5-2s per file |
| P0 | **Never re-call LLM for same input** | LLM calls are ~2-10s each; 200 functions = 30+ minutes |
| P0 | **Single parse, single data model** | Eliminate 3x parsing and 3 representations of same data |
| P1 | **Incremental at function granularity** | Change 1 function → only that function reprocesses |
| P1 | **In-process pipeline** | No subprocess boundaries; share memory between phases |
| P1 | **Parallel function processing** | CFG build + LLM calls are embarrassingly parallel |
| P2 | **Pluggable LLM backend** | Support local (Ollama), cloud (OpenAI/Anthropic), and no-LLM mode |
| P2 | **Crash-resumable** | Persist per-function progress; resume from last success |
| P2 | **Observable** | Progress bars, quality metrics, timing breakdown |
| P3 | **Pluggable export formats** | DOCX, HTML, PDF, Markdown — registry pattern |

---

## 5. High-Level Architecture

### 5.1 Pipeline Overview

```
                          ┌─────────────────────────────────────────────────────────┐
                          │                   ARTIFACT STORE                        │
                          │  Content-addressable cache: hash(input) → artifact      │
                          │  Stores: AST, CFG, labels, Mermaid, descriptions, etc.  │
                          └──────────────────────┬──────────────────────────────────┘
                                                 │
                                                 │ read/write
                                                 │
  ┌──────────┐    ┌──────────────┐    ┌──────────┴──────────┐    ┌──────────────┐
  │  Source   │───>│   PARSER     │───>│   PROCESSOR POOL    │───>│   VIEWS /    │
  │  Files    │    │  (once)      │    │   (per-function)    │    │   EXPORTS    │
  │  (C++)   │    │              │    │                     │    │              │
  └──────────┘    │ libclang TU  │    │ ┌─ CFG Builder ───┐ │    │ ┌─ Mermaid  │
                  │ AST extract  │    │ │  Enricher       │ │    │ │  DOCX     │
  ┌──────────┐    │ Call graph   │    │ │  LLM Labeler    │ │    │ │  HTML     │
  │  Config  │───>│ Type info    │    │ │  Mermaid Gen    │ │    │ │  Iface    │
  │          │    │ Macro scan   │    │ └─────────────────┘ │    │ │  UnitDiag │
  └──────────┘    └──────────────┘    └─────────────────────┘    │ └──────────│
                                                                 └─────────────┘
                         ▲                       ▲                       │
                         │                       │                       │
                    ┌────┴────┐            ┌─────┴────┐           ┌──────┴──────┐
                    │ Change  │            │ Parallel │           │   Output    │
                    │Detector │            │Scheduler │           │   Writer    │
                    └─────────┘            └──────────┘           └─────────────┘
```

### 5.2 Key Architectural Decisions

**Decision 1: In-process, single pipeline**
- No subprocess launches. One Python process runs everything.
- Phases become function calls, not script invocations.
- libclang initialized once, TUs shared across all consumers.

**Decision 2: Content-addressable artifact store**
- Every intermediate artifact is stored keyed by hash of its inputs.
- If the hash matches, the artifact is reused without recomputation.
- Granularity: per-function (not per-file, not per-project).

**Decision 3: Unified data model**
- One `FunctionRecord` dataclass used from parse to export.
- No translation layers. No internal ID vs qualifiedName split.
- Keys are always `qualifiedName` (human-readable, stable across renames within file).

**Decision 4: Parse once, extract everything**
- Single libclang pass per file extracts: AST, types, call graph, macros, comments, AND function bodies.
- The CFG builder receives the already-parsed cursor directly — no re-parse.

**Decision 5: LLM calls are content-addressed**
- `hash(system_prompt + user_prompt)` → cached response.
- Same prompt = same response. Zero LLM calls on unchanged input.
- Cache persists across runs (disk-backed).

---

## 6. Core Data Model

### 6.1 Unified FunctionRecord

```
┌──────────────────────────────────────────────────────────────────────┐
│                          FunctionRecord                              │
├──────────────────────────────────────────────────────────────────────┤
│  qualified_name: str          # "Namespace::Class::Method"           │
│  signature: str               # "RetType Method(ParamType p1, ...)"  │
│  file: str                    # Relative path from base_path         │
│  line: int                    # Start line (1-indexed)               │
│  end_line: int                # End line                             │
│  parameters: List[Param]      # [{name, type}]                       │
│  return_type: str                                                    │
│  comment: str                 # Source doc comment (preferred)        │
│  description: str             # LLM-generated description            │
│  calls: List[str]             # qualifiedNames of callees            │
│  called_by: List[str]         # qualifiedNames of callers            │
│  reads_globals: List[str]     # Global variable qualifiedNames       │
│  writes_globals: List[str]    # Global variable qualifiedNames       │
│  phases: List[Phase]          # [{start_line, end_line, description}]│
│  interface_id: str            # "IF_PROJ_UNIT_03"                    │
│  direction: str               # "In" | "Out"                         │
│  behaviour_input: str         # Input behaviour name                 │
│  behaviour_output: str        # Output behaviour name                │
│  module: str                  # Module name                          │
│  unit: str                    # Unit name (file stem)                │
│                                                                      │
│  # Derived (populated lazily, cached)                                │
│  cfg: ControlFlowGraph        # Built from AST cursor                │
│  mermaid: str                 # Generated Mermaid script             │
│  source_hash: str             # SHA256 of function source text       │
│  labels_hash: str             # Hash of all inputs to LLM labeling   │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 Unified ProjectModel

```
┌──────────────────────────────────────────────────────────────────────┐
│                          ProjectModel                                │
├──────────────────────────────────────────────────────────────────────┤
│  project_name: str                                                   │
│  base_path: str                                                      │
│  functions: Dict[str, FunctionRecord]    # key = qualifiedName       │
│  globals: Dict[str, GlobalRecord]                                    │
│  enums: Dict[str, EnumRecord]                                        │
│  macros: Dict[str, MacroRecord]                                      │
│  typedefs: Dict[str, TypedefRecord]                                  │
│  structs: Dict[str, StructRecord]                                    │
│  units: Dict[str, UnitRecord]                                        │
│  modules: Dict[str, ModuleRecord]                                    │
│                                                                      │
│  # Summaries (populated by LLM pass)                                 │
│  project_summary: str                                                │
│  module_summaries: Dict[str, str]                                    │
│  file_summaries: Dict[str, str]                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**No separate `functions.json`, `knowledge_base.json`, `units.json`, `modules.json`.** One model serialized to one file: `model/project.json`. Views read this directly.

---

## 7. The Artifact Store (Content-Addressable Cache)

This is the **core innovation** that eliminates all redundant work.

### 7.1 Concept

```
                                        ┌──────────────────┐
  hash(inputs) ────────────────────────>│  Artifact Store  │
                                        │  .analyzer_cache/ │
                                        │                  │
                                        │  ab/cd1234.json  │──> cached CFG
                                        │  ef/gh5678.json  │──> cached labels
                                        │  ij/kl9012.json  │──> cached mermaid
                                        │  mn/op3456.json  │──> cached LLM response
                                        └──────────────────┘
```

### 7.2 What Gets Cached (with Cache Keys)

| Artifact | Cache Key (hash of) | Stored Value |
|----------|---------------------|--------------|
| **Parsed AST metadata** | `sha256(file_content + clang_args)` | Function signatures, call graph, types, comments |
| **CFG** | `sha256(function_source + max_stmts + max_lines)` | Serialized ControlFlowGraph |
| **Enriched nodes** | `sha256(cfg_hash + pkb_context_hash)` | Enriched node contexts |
| **LLM label response** | `sha256(system_prompt + user_prompt)` | Raw LLM response text |
| **Parsed labels** | `sha256(llm_response)` | Dict of node_id → label |
| **Coherence pass** | `sha256(all_labels_before + coherence_prompt)` | Revised labels |
| **Mermaid script** | `sha256(cfg_hash + final_labels_hash)` | Mermaid string |
| **LLM description** | `sha256(description_prompt)` | Description text |
| **LLM behaviour names** | `sha256(behaviour_prompt)` | Input/output names |
| **Hierarchy summary** | `sha256(summary_prompt)` | Summary text |

### 7.3 Cache Invalidation

```
Source file changes
    └──> AST metadata cache miss  (file_content changed)
           └──> Function source changed?
                  ├── YES ──> CFG cache miss ──> enrichment miss ──> LLM miss ──> Mermaid miss
                  └── NO  ──> CFG cache HIT ──> everything downstream is HIT
```

**Cascade rule:** If an artifact cache hits, ALL downstream artifacts also hit (their inputs haven't changed). This means changing a comment in one function doesn't invalidate the CFG or labels of another function in the same file.

### 7.4 Storage Format

```
.analyzer_cache/
├── manifest.json              # {version, created, stats}
├── artifacts/
│   ├── ab/
│   │   └── cd1234ef5678.json  # one artifact per hash
│   ├── ef/
│   │   └── ...
│   └── ...
└── index.json                 # Maps qualifiedName → latest artifact hashes (for quick lookup)
```

Artifacts are stored in hash-sharded directories (first 2 chars of hash) to avoid filesystem slowdown from too many files in one directory.

### 7.5 Cache Size Management

- **TTL:** Artifacts not accessed in 30 days are eligible for eviction.
- **Max size:** Configurable (default 500MB). LRU eviction.
- `analyzer cache stats` — shows size, hit rate, artifact counts.
- `analyzer cache clear` — wipes all cached artifacts.

---

## 8. Phase Redesign

### 8.1 Current vs. New

```
CURRENT (4 phases, 5 subprocesses, 3 libclang parses, 0 function-level caching):

  Phase 1 ──> Phase 2 ──> Phase 3 ──> Phase 4
  (parse)     (derive)     (views)     (export)
  [subprocess] [subprocess] [subprocess+subprocess] [subprocess]

NEW (3 stages, 1 process, 1 libclang parse, full function-level caching):

  ┌─────────────────────────────────────────────────────────────────┐
  │                     Single Python Process                       │
  │                                                                 │
  │  Stage 1: PARSE + MODEL                                        │
  │  ┌─────────────────────────────────────────────────────────┐   │
  │  │ For each source file (parallel):                        │   │
  │  │   - Parse with libclang (1 TU per file)                 │   │
  │  │   - Extract: functions, types, globals, call graph      │   │
  │  │   - Cache AST metadata per file                         │   │
  │  │ Then:                                                   │   │
  │  │   - Build units, modules, interface IDs                 │   │
  │  │   - Propagate global access                             │   │
  │  │   - Build unified ProjectModel                          │   │
  │  └─────────────────────────────────────────────────────────┘   │
  │                              │                                  │
  │                              v                                  │
  │  Stage 2: ENRICH + FLOWCHART (per-function, parallel)          │
  │  ┌─────────────────────────────────────────────────────────┐   │
  │  │ For each function (parallel via ThreadPool):            │   │
  │  │   a. Check artifact cache → skip if all cached          │   │
  │  │   b. Build CFG from already-parsed TU cursor            │   │
  │  │   c. Enrich nodes with project context                  │   │
  │  │   d. LLM: descriptions (if needed)                      │   │
  │  │   e. LLM: node labels (batch)                           │   │
  │  │   f. LLM: coherence pass                                │   │
  │  │   g. LLM: behaviour names (if needed)                   │   │
  │  │   h. Build Mermaid script                               │   │
  │  │   i. Cache all artifacts                                │   │
  │  └─────────────────────────────────────────────────────────┘   │
  │                              │                                  │
  │                              v                                  │
  │  Stage 3: SUMMARIZE + EXPORT (sequential)                      │
  │  ┌─────────────────────────────────────────────────────────┐   │
  │  │ - LLM hierarchy summaries (file → module → project)     │   │
  │  │ - Generate all views (interface tables, unit diagrams,   │   │
  │  │   flowcharts JSON, behaviour diagrams)                   │   │
  │  │ - Export DOCX                                            │   │
  │  └─────────────────────────────────────────────────────────┘   │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘
```

### 8.2 Stage 1: Parse + Model (Detail)

```
┌──────────────────────────────────────────────────────────────────┐
│ Stage 1: Parse + Model                                           │
│                                                                  │
│  Input:  C++ project directory + config                          │
│  Output: ProjectModel (in-memory) + cached AST metadata          │
│                                                                  │
│  ┌──────────────┐                                                │
│  │ Change       │ Compare file hashes against cached hashes.     │
│  │ Detector     │ Only re-parse files that changed.              │
│  └──────┬───────┘                                                │
│         │                                                        │
│         v                                                        │
│  ┌──────────────┐   For changed files only:                      │
│  │ File Parser  │   - Create TranslationUnit (libclang)          │
│  │ (parallel)   │   - Walk AST → extract functions, types, etc.  │
│  └──────┬───────┘   - Also retain TU in memory for Stage 2       │
│         │                                                        │
│         v                                                        │
│  ┌──────────────┐                                                │
│  │ Model Builder│   - Merge all file extractions                 │
│  │              │   - Resolve cross-file call graph              │
│  │              │   - Build units/modules/interface IDs           │
│  │              │   - Compute global access propagation           │
│  └──────────────┘                                                │
│                                                                  │
│  Key difference from v1:                                         │
│  - TUs stay in memory (not discarded after Phase 1)              │
│  - Function cursors are resolved HERE, not re-resolved later     │
│  - Each function stores a reference to its body cursor           │
└──────────────────────────────────────────────────────────────────┘
```

### 8.3 Stage 2: Enrich + Flowchart (Detail)

```
┌──────────────────────────────────────────────────────────────────┐
│ Stage 2: Enrich + Flowchart  (per function, parallelizable)      │
│                                                                  │
│  For each FunctionRecord:                                        │
│                                                                  │
│  ┌─────────────┐   hash(source_text + config) → cache lookup     │
│  │ Cache Check  │   If ALL artifacts cached → skip entirely      │
│  └──────┬──────┘                                                 │
│         │ (cache miss)                                           │
│         v                                                        │
│  ┌─────────────┐   Build CFG from in-memory TU cursor            │
│  │ CFG Builder  │   - ASSERT pre-scan + suppression              │
│  │             │   - Statement segmentation                      │
│  │             │   - Same algorithm as v1 (proven correct)       │
│  └──────┬──────┘                                                 │
│         v                                                        │
│  ┌─────────────┐   Annotate nodes with project vocabulary        │
│  │ Enricher    │   - Callee resolution, enum/macro context       │
│  │             │   - Inline comments, struct members             │
│  └──────┬──────┘                                                 │
│         v                                                        │
│  ┌─────────────┐   Build context packet + prompts                │
│  │ LLM Labeler │   Check LLM cache before calling                │
│  │             │   - Batch labeling with auto-halve              │
│  │             │   - Coherence pass                              │
│  │             │   - Cache every LLM response                    │
│  └──────┬──────┘                                                 │
│         v                                                        │
│  ┌─────────────┐   Generate Mermaid from labeled CFG             │
│  │ Mermaid Gen │   Validate CFG and Mermaid                      │
│  └──────┬──────┘                                                 │
│         v                                                        │
│  ┌─────────────┐   Store all artifacts to disk cache             │
│  │ Cache Write │   (CFG, labels, Mermaid, description, etc.)     │
│  └─────────────┘                                                 │
└──────────────────────────────────────────────────────────────────┘
```

### 8.4 Stage 3: Summarize + Export (Detail)

```
┌──────────────────────────────────────────────────────────────────┐
│ Stage 3: Summarize + Export                                      │
│                                                                  │
│  ┌──────────────────┐   LLM hierarchy summaries                  │
│  │ Summarizer       │   - Function → File → Module → Project     │
│  │ (with LLM cache) │   - Only summarize if inputs changed       │
│  └───────┬──────────┘                                            │
│          v                                                       │
│  ┌──────────────────┐   Registered views generate output         │
│  │ View Engine      │   - Interface tables                       │
│  │                  │   - Unit diagrams                          │
│  │                  │   - Flowchart JSON + PNG                   │
│  │                  │   - Behaviour diagrams                     │
│  │                  │   - Module static diagrams                 │
│  └───────┬──────────┘                                            │
│          v                                                       │
│  ┌──────────────────┐   Generate final document                  │
│  │ Exporter         │   - DOCX (default)                         │
│  │                  │   - HTML, Markdown (pluggable)             │
│  └──────────────────┘                                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 9. LLM Subsystem Redesign

### 9.1 Problems in v1

1. No prompt-level caching (same prompt = repeated LLM call)
2. No API key support (Ollama only; cloud APIs rejected)
3. No `response_format: json_object` (unreliable JSON from cloud)
4. Hardcoded `MAX_PROMPT_CHARS=6000` (wastes large context windows)
5. Broken retry loop (`range(1, max_retries)` = 1 attempt)
6. `sleep(3)` hardcoded rate limiter
7. Two independent LLM usage sites (Phase 2 + Phase 3) with different clients

### 9.2 New Design

```
┌──────────────────────────────────────────────────────────────────┐
│                        LLM Gateway                               │
│                                                                  │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │ Prompt      │   │ Response     │   │ Provider Adapters    │  │
│  │ Cache       │   │ Cache        │   │                      │  │
│  │             │   │              │   │ ┌─ OllamaAdapter    │  │
│  │ hash(prompt)│   │ hash(prompt) │   │ ├─ OpenAIAdapter    │  │
│  │  → response │   │  → parsed    │   │ ├─ AnthropicAdapter │  │
│  │             │   │    result    │   │ └─ NoopAdapter      │  │
│  └──────┬──────┘   └──────────────┘   │    (fallback labels)│  │
│         │                              └──────────┬───────────┘  │
│         │                                         │              │
│         v                                         v              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                     Rate Limiter                         │    │
│  │  Token-bucket: configurable req/sec (default: 5)         │    │
│  │  Per-provider, per-model limits                          │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                     Retry Engine                         │    │
│  │  - Configurable max_retries (default: 3)                 │    │
│  │  - Exponential backoff: 1s, 2s, 4s                       │    │
│  │  - Separate handling: no_response vs bad_response        │    │
│  │  - Auto-halve batch on repeated no_response              │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Config:                                                         │
│  │  provider: "ollama" | "openai" | "anthropic" | "none"         │
│  │  base_url: str                                                │
│  │  api_key: str (from env var or config)                        │
│  │  model: str                                                   │
│  │  max_context_tokens: int (auto-scales prompt budget)          │
│  │  max_output_tokens: int                                       │
│  │  temperature: float                                           │
│  │  rate_limit_rps: float                                        │
│  │  response_format: "json" | "text"                             │
│  │  timeout_seconds: int                                         │
│  │  max_retries: int                                             │
└──────────────────────────────────────────────────────────────────┘
```

### 9.3 Key Improvements

**Prompt cache:** `sha256(system_prompt + user_prompt)` → stored response. Same
function with same context = zero LLM calls. This alone eliminates ~90% of LLM
calls on re-runs.

**Provider adapters:** Each adapter handles the HTTP format, auth headers,
`response_format`, and response parsing for its provider. Adding a new provider
is one class.

**Auto-scaling prompt budget:** Instead of `MAX_PROMPT_CHARS=6000`, the gateway
reads `max_context_tokens` from config and auto-scales the prompt to fill 70%
of the window (leaving 30% for output). This means:
- Ollama 2k model: ~4200 chars
- Ollama 8k model: ~16800 chars
- Cloud 128k model: ~268000 chars

**Unified client:** One `LlmGateway` instance used everywhere — descriptions,
labels, summaries, behaviour names. No more separate clients in Phase 2 vs Phase 3.

---

## 10. Concurrency Model

### 10.1 What Can Run in Parallel

```
  Stage 1 (Parse):
  ┌─────────────────────────────────────┐
  │  File A  ─┐                         │
  │  File B  ─┼─ ThreadPool (libclang)  │   Libclang is thread-safe for
  │  File C  ─┤  max_workers = CPU/2    │   independent TranslationUnits
  │  File D  ─┘                         │
  └─────────────────────────────────────┘

  Stage 2 (Enrich + Flowchart):
  ┌──────────────────────────────────────────────────┐
  │  Func 1 ──┐                                      │
  │  Func 2 ──┼─ ThreadPool (CFG = CPU, LLM = I/O)  │   CFG build is CPU-bound
  │  Func 3 ──┤  max_workers = configurable          │   LLM calls are I/O-bound
  │  Func 4 ──┘  default = min(8, CPU_count)         │   Thread pool handles both
  └──────────────────────────────────────────────────┘

  Stage 3 (Export):
  Sequential (DOCX writing is not parallelizable)
```

### 10.2 Thread Safety

- **libclang TUs:** Thread-safe when each thread works on a different TU.
  Functions within the same file share a TU — schedule them sequentially per-file
  but parallel across files.
- **Artifact Store:** Thread-safe via file-level locking (each artifact has unique path).
- **LLM Gateway:** Thread-safe. Rate limiter uses a token bucket with a lock.
- **ProjectModel:** Read-only during Stage 2. Stage 1 writes, Stages 2-3 read.

### 10.3 Estimated Speedup

For a 200-function project:

| | v1 (sequential) | v2 (parallel, no cache) | v2 (cached, 1 func changed) |
|---|---|---|---|
| Parse | 60s (3x parse) | 20s (1x parse, parallel) | ~1s (1 file re-parsed) |
| CFG + Enrich | 30s | 8s (4 workers) | ~0.2s (1 function) |
| LLM labels | 600s (200 × 3s) | 150s (4 workers) | ~3s (1 function) |
| LLM summaries | 60s | 60s (sequential) | ~0s (cached) |
| Export | 10s | 10s | 10s |
| **Total** | **~760s (~13 min)** | **~248s (~4 min)** | **~14s** |

---

## 11. View / Export Plugin System

### 11.1 View Interface

```python
class View(Protocol):
    """Every view implements this interface."""

    name: str                    # "flowcharts", "interfaceTables", etc.

    def generate(self,
                 model: ProjectModel,
                 output_dir: Path,
                 config: ViewConfig) -> None:
        """Generate output files from the model."""
        ...
```

### 11.2 Built-in Views

| View | Input | Output |
|------|-------|--------|
| `InterfaceTablesView` | ProjectModel | `output/interface_tables.json` |
| `FlowchartView` | ProjectModel (with Mermaid scripts) | `output/flowcharts/*.json` + optional PNG |
| `UnitDiagramView` | ProjectModel | `output/unit_diagrams/*.mmd` + optional PNG |
| `BehaviourDiagramView` | ProjectModel | `output/behaviour_diagrams/*.mmd` + optional PNG |
| `ModuleStaticDiagramView` | ProjectModel | `output/module_static_diagrams/*.mmd` + optional PNG |

### 11.3 Built-in Exporters

| Exporter | Input | Output |
|----------|-------|--------|
| `DocxExporter` | All view outputs + ProjectModel | `output/software_detailed_design.docx` |
| `HtmlExporter` (new) | Same | `output/report/index.html` (interactive) |
| `MarkdownExporter` (new) | Same | `output/report.md` |

### 11.4 Registration

```python
# In each view module:
@register_view("flowcharts")
class FlowchartView:
    ...

# In each exporter module:
@register_exporter("docx")
class DocxExporter:
    ...
```

Views and exporters are discovered by the engine at startup. Config controls which are enabled.

---

## 12. Configuration Redesign

### 12.1 New Config Structure

```jsonc
{
  // Project parsing
  "project": {
    "name": "MyProject",           // Optional: auto-detected from directory
    "std": "c++14",
    "clangArgs": ["-I/path/to/includes"],
    "excludeDirs": ["build", "test", ".git"],
    "modules": {                   // Optional module grouping
      "core": ["app", "math"],
      "support": "outer/inner"
    }
  },

  // Clang / libclang
  "clang": {
    "llvmLibPath": "C:\\Program Files\\LLVM\\bin\\libclang.dll",
    "clangIncludePath": "C:\\Program Files\\LLVM\\lib\\clang\\17\\include"
  },

  // LLM provider (unified)
  "llm": {
    "provider": "ollama",          // "ollama" | "openai" | "anthropic" | "none"
    "baseUrl": "http://localhost:11434",
    "model": "qwen2.5-coder:14b",
    "apiKey": "${LLM_API_KEY}",    // Env var interpolation
    "maxContextTokens": 8192,      // Auto-scales prompt budget
    "maxOutputTokens": 4096,
    "temperature": 0.1,
    "rateLimitRps": 5.0,           // Requests per second
    "timeoutSeconds": 120,
    "maxRetries": 3,
    "responseFormat": "json"       // Hint to provider if supported
  },

  // Feature flags
  "features": {
    "descriptions": true,          // LLM function descriptions
    "behaviourNames": true,        // LLM behaviour names
    "hierarchySummaries": true,    // 4-level LLM summaries
    "flowcharts": true,            // CFG + Mermaid generation
    "coherencePass": true          // Label coherence normalization
  },

  // Views
  "views": {
    "interfaceTables": true,
    "unitDiagrams": { "renderPng": true },
    "flowcharts": { "renderPng": true },
    "behaviourDiagram": { "renderPng": true },
    "moduleStaticDiagram": { "enabled": true, "renderPng": true }
  },

  // Export
  "export": {
    "format": "docx",             // "docx" | "html" | "markdown"
    "outputPath": "output/software_detailed_design.docx",
    "fontSize": 8
  },

  // Cache
  "cache": {
    "enabled": true,
    "dir": ".analyzer_cache",
    "maxSizeMb": 500,
    "ttlDays": 30
  },

  // Performance
  "performance": {
    "maxWorkers": 8,               // Thread pool size
    "parseBatchSize": 10           // Files per parse batch
  }
}
```

### 12.2 Key Improvements Over v1

- **Environment variable interpolation** (`${LLM_API_KEY}`) — secrets stay out of config files
- **Single LLM config** — no more separate configs in Phase 2 and Phase 3
- **Feature flags** — granular control over what runs
- **Cache config** — tunable cache behavior
- **Performance tuning** — explicit worker count

---

## 13. CLI and UX

### 13.1 Commands

```bash
# Full run
analyzer run <project_path>

# Full run with options
analyzer run <project_path> --clean --no-llm --workers 4

# Incremental run (default behavior — only reprocesses changed functions)
analyzer run <project_path>

# Single function
analyzer run <project_path> --function "Namespace::MyClass::MyMethod"

# Stage control
analyzer run <project_path> --from-stage 2    # Skip parsing
analyzer run <project_path> --only-stage 1    # Parse only

# Cache management
analyzer cache stats                          # Show hit rate, size
analyzer cache clear                          # Wipe cache
analyzer cache clear --function "Foo::Bar"    # Clear one function

# Inspect intermediate artifacts
analyzer inspect <project_path> --function "Foo::Bar" --show cfg
analyzer inspect <project_path> --function "Foo::Bar" --show mermaid
analyzer inspect <project_path> --function "Foo::Bar" --show labels
```

### 13.2 Progress Output

```
[12:34:56] Stage 1: Parse + Model
  Scanning files... 48 C++ files found
  Changed: 3 files (45 cached)
  Parsing: ████████████████████ 48/48 [0:00:12]
  Model: 187 functions, 23 globals, 12 units, 4 modules

[12:35:08] Stage 2: Enrich + Flowchart
  Functions to process: 14 (173 cached)
  Processing: ██████████████░░░░░░ 14/14 [0:00:45]
    Cache: 173 hit, 14 miss
    LLM calls: 42 (38 label batches + 4 coherence)
    LLM cache: 28 hit, 14 miss

[12:35:53] Stage 3: Summarize + Export
  Hierarchy summaries: 4 LLM calls (all cached)
  Views: interfaceTables ✓ unitDiagrams ✓ flowcharts ✓ behaviourDiagram ✓
  Export: output/software_detailed_design.docx ✓

[12:36:01] Done in 65s (vs ~760s without cache)
  Artifacts: 187 functions, 14 regenerated, 173 from cache
  LLM calls: 14 actual, 201 avoided via cache
```

---

## 14. Directory and Module Layout

```
analyzer/
├── analyzer.py                    # CLI entry point
├── config/
│   ├── config.json                # Default config
│   └── config.local.json          # Local overrides (gitignored)
│
├── src/
│   ├── __init__.py
│   ├── pipeline.py                # Orchestrates Stage 1 → 2 → 3
│   │
│   ├── parse/                     # Stage 1: Parse + Model
│   │   ├── __init__.py
│   │   ├── file_parser.py         # libclang per-file parsing
│   │   ├── model_builder.py       # Builds ProjectModel from parse results
│   │   ├── change_detector.py     # File-level change detection
│   │   └── type_extractor.py      # Enums, macros, typedefs, structs
│   │
│   ├── cfg/                       # CFG construction
│   │   ├── __init__.py
│   │   ├── builder.py             # CFGBuilder (same algorithm as v1)
│   │   ├── enricher.py            # NodeEnricher
│   │   └── assert_filter.py       # ASSERT pre-scan + filter
│   │
│   ├── llm/                       # LLM Gateway (unified)
│   │   ├── __init__.py
│   │   ├── gateway.py             # LLM Gateway: cache + rate limit + retry
│   │   ├── cache.py               # Prompt-level response cache
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # Provider protocol
│   │   │   ├── ollama.py          # Ollama adapter
│   │   │   ├── openai.py          # OpenAI-compatible adapter
│   │   │   ├── anthropic.py       # Anthropic adapter
│   │   │   └── noop.py            # No-LLM fallback labels
│   │   ├── labeler.py             # CFG label generator (batch + coherence)
│   │   ├── describer.py           # Function/global description generator
│   │   ├── summarizer.py          # Hierarchy summarizer
│   │   └── prompts.py             # All prompt templates
│   │
│   ├── model/                     # Unified data model
│   │   ├── __init__.py
│   │   ├── records.py             # FunctionRecord, GlobalRecord, etc.
│   │   ├── project.py             # ProjectModel
│   │   └── serialization.py       # JSON read/write
│   │
│   ├── mermaid/                   # Mermaid generation + validation
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   └── validator.py
│   │
│   ├── views/                     # View generators
│   │   ├── __init__.py
│   │   ├── registry.py            # View + Exporter registration
│   │   ├── interface_tables.py
│   │   ├── flowcharts.py
│   │   ├── unit_diagrams.py
│   │   ├── behaviour_diagrams.py
│   │   └── module_static_diagrams.py
│   │
│   ├── export/                    # Exporters
│   │   ├── __init__.py
│   │   ├── docx_exporter.py
│   │   ├── html_exporter.py
│   │   └── markdown_exporter.py
│   │
│   ├── cache/                     # Artifact store
│   │   ├── __init__.py
│   │   ├── store.py               # Content-addressable artifact store
│   │   └── hasher.py              # Input hashing utilities
│   │
│   └── utils/                     # Shared utilities
│       ├── __init__.py
│       ├── config.py              # Config loader with env var interpolation
│       ├── logging.py             # Unified logging
│       └── naming.py              # Module/unit naming, safe filenames
│
├── model/                         # Generated model (single file)
│   └── project.json               # Unified ProjectModel serialized
│
├── output/                        # Generated outputs
│   ├── flowcharts/
│   ├── unit_diagrams/
│   ├── behaviour_diagrams/
│   ├── interface_tables.json
│   └── software_detailed_design.docx
│
└── .analyzer_cache/               # Artifact store (gitignored)
    ├── manifest.json
    ├── index.json
    └── artifacts/
```

### Comparison with v1

| Aspect | v1 | v2 |
|--------|----|----|
| Entry points | `run.py` + 4 subprocess scripts | Single `analyzer.py` |
| Modules | Flat + nested flowchart/ subpackage | Clean package hierarchy |
| Data model files | 7 JSON files (functions, globalVars, units, modules, metadata, data, knowledge_base) | 1 file: `project.json` |
| LLM code | `llm_client.py` (Phase 2) + `llm/client.py` (Phase 3) | Single `llm/gateway.py` |
| Config | Scattered across files | Single `utils/config.py` |

---

## 15. Migration Path

### Phase A: Foundation (no behavior change)

1. Create new package structure alongside existing code
2. Build `ArtifactStore` and `LlmGateway` as standalone modules
3. Build unified `ProjectModel` and `FunctionRecord` with serialization
4. Write adapter that produces `ProjectModel` from existing `functions.json` + `knowledge_base.json`

### Phase B: In-process pipeline

1. Convert `parser.py` → `parse/file_parser.py` (keep libclang logic, add caching)
2. Convert `model_deriver.py` → `parse/model_builder.py` (eliminate subprocess boundary)
3. Wire Stage 1 through `pipeline.py`
4. Test: output must match v1 for the same input

### Phase C: Unified flowchart processing

1. Move `cfg_builder.py` → `cfg/builder.py` (minimal changes)
2. Move `enricher.py` → `cfg/enricher.py`
3. Integrate with in-process TU (eliminate re-parse)
4. Wire Stage 2 through `pipeline.py` with artifact caching
5. Test: Mermaid output must match v1

### Phase D: LLM unification

1. Build provider adapters (Ollama, OpenAI, Anthropic)
2. Replace both `llm_client.py` and `llm/client.py` with `LlmGateway`
3. Add prompt-level caching
4. Fix retry loop, add `response_format`, add API key support
5. Test: labels and descriptions match v1 quality

### Phase E: Parallelism + polish

1. Add ThreadPoolExecutor for Stage 1 (file parsing) and Stage 2 (function processing)
2. Add progress bars
3. Add `analyzer cache` CLI commands
4. Add incremental change detection
5. Performance benchmarks

### Phase F: Cleanup

1. Remove old subprocess scripts
2. Remove `knowledge_base.json` generation (no longer needed)
3. Remove duplicate code paths
4. Update FLOW.md documentation

---

## 16. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| libclang TU thread safety issues | Medium | High | Serialize per-file; only parallelize across files |
| Artifact cache hash collisions | Very Low | Medium | Use SHA-256 (collision probability negligible) |
| Cache invalidation bugs (stale results) | Medium | High | Always include ALL inputs in hash key; option to `--no-cache` |
| LLM provider differences (different output for same prompt) | High | Medium | Cache is per-provider-and-model; changing model invalidates cache |
| Migration regression (different output than v1) | Medium | High | Phase B-D: output comparison tests against v1 baseline |
| Windows path handling | Medium | Medium | Normalize all paths at ingestion; use `pathlib.Path` throughout |
| Large project memory usage (all TUs in memory) | Low | Medium | Optional: release TU after function cursors extracted |
| Config migration from v1 | Low | Low | Accept v1 config format with deprecation warnings |

---

## Summary: What Changes, What Stays

### Stays (proven correct, keep algorithm)
- CFGBuilder algorithm (AST-only, no heuristics)
- ASSERT pre-scan approach (O(1) lookup)
- Mermaid builder + validator
- Node enrichment (callee, enum, macro, struct context)
- LLM prompt design (system + user prompt structure)
- Batch labeling with auto-halve
- Coherence pass
- Header file filtering
- Interface table generation
- DOCX export layout

### Changes (architecture, not algorithms)
- Single process instead of 5 subprocesses
- Single libclang parse instead of 3
- Unified data model instead of 3 JSON formats
- Content-addressable artifact cache (per-function granularity)
- LLM prompt-level response cache
- Parallel function processing
- Pluggable LLM provider (Ollama, OpenAI, Anthropic, none)
- API key support, `response_format: json`, auto-scaling prompt budget
- Fixed retry loop
- Incremental change detection
- Clean module hierarchy
