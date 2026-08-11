# Flowchart Engine

Generates Graphviz **DOT** flowcharts from C++ source code using libclang for static analysis and a local LLM (Ollama) for human-readable labels.

> See also [FLOW.md](FLOW.md) — the complete end-to-end analyzer pipeline flow reference (`run.py` → phases → DOCX).

Given a C++ function, it produces a DOT flowchart like this:

```
int classify(int x) {        digraph G {
    if (x > 0)                   N0 [shape=ellipse, label="Start: classify"];
        return 1;                N1 [shape=diamond, label="Is x positive?"];
    else                         N2 [shape=box, label="Return positive result"];
        return -1;               N3 [shape=box, label="Return negative result"];
}                                N4 [shape=ellipse, label="End"];
                                 N0 -> N1;
                                 N1 -> N2 [taillabel="Yes"];
                                 N1 -> N3 [taillabel="No"];
                                 N2 -> N4;  N3 -> N4;
                                 }
```

---

## How It Works

```
functions.json          metadata.json         project_knowledge.json
      |                      |                        |  (optional)
      v                      v                        v
 ┌─────────────────────────────────────────────────────────────┐
 │                    flowchart_engine.py                       │
 │                                                             │
 │  1. PKB Build                                               │
 │     Load all function entries (qualified name, file, line)  │
 │     Build caller/callee index for context injection         │
 │                          |                                  │
 │  2. CFG Extraction   (ast_engine/)                          │
 │     libclang parses the .cpp file                           │
 │     CFGBuilder walks the AST and creates:                   │
 │       Nodes: START, END, ACTION, DECISION,                  │
 │              LOOP_HEAD, SWITCH_HEAD, RETURN,                │
 │              CASE, BREAK, CONTINUE, TRY_HEAD, CATCH         │
 │       Edges: control-flow arrows with Yes/No labels         │
 │                          |                                  │
 │  3. Enrichment       (enrichment/)                          │
 │     Each node is enriched with extra context:               │
 │       - call_names: EVERY call in the node (cpp_tokens.py)  │
 │       - Function calls within the node (PKB descriptions)   │
 │       - Inline source comments                              │
 │       - Enum / macro / typedef / struct member info         │
 │                          |                                  │
 │  4. LLM Labeling     (llm/)                                 │
 │     Nodes are sorted topologically and split into batches   │
 │     Each batch is sent to the LLM with a context packet:    │
 │       - File and function purpose                           │
 │       - Caller context (who calls this function)            │
 │       - Callee context (what this function calls)           │
 │       - Phase hints (if project_scanner was run)            │
 │       - Neighbor node code (preceding / following)          │
 │       - Data-flow shared variables across the batch         │
 │     A coherence pass normalises labels across all batches   │
 │                          |                                  │
 │  4b. Call-name enforcement  (llm/generator.py)              │
 │     Deterministic, no LLM, runs AFTER coherence:            │
 │       - normalise every mention to Name() (args stripped)   │
 │       - append missing names as "<br/>Calls: X()"           │
 │                          |                                  │
 │  5. DOT Build        (dot_builder.py)                       │
 │     Labeled CFG → Graphviz DOT script                       │
 │     Node shapes: ellipse=START/END  diamond=DECISION        │
 │                  box=everything else                        │
 │     Long labels word-wrapped; curved edges (no ortho)       │
 │                          |                                  │
 │  6. Output           (output/)                              │
 │     One JSON file per source file written to --out-dir      │
 └─────────────────────────────────────────────────────────────┘
                            |
                     output/myfile.json
```

---

## Project Structure

```
flowchart_engine.py     Main entry point and orchestration
models.py               Data models: CfgNode, CfgEdge, FunctionEntry, etc.
config.py               EngineConfig dataclass
cpp_tokens.py           One definition of "a function call", shared by the
                        enricher, the prompt, and the enforcement pass:
                        CPP_KEYWORDS, extract_call_names, render_call

ast_engine/
  cfg_builder.py        Builds ControlFlowGraph from a libclang AST cursor
  parser.py             SourceExtractor and TranslationUnitParser (libclang)
  resolver.py           Finds the libclang cursor for a given function

enrichment/
  enricher.py           Enriches CFG nodes with PKB/project-knowledge context

llm/
  generator.py          Batch LLM label generation + coherence pass +
                        enforce_call_names() (deterministic, runs last)
  prompts.py            System and user prompt templates
  client.py             Ollama HTTP client with auto-retry and auto-split

dot_builder.py          Converts a labeled CFG to a Graphviz DOT script
                        (build_dot); word-wraps long labels, curved edges,
                        loop-anchor push-down for Return/End at the bottom.
                        Rendered to PNG by engine.utils.render_dot_cached.

mermaid/                LEGACY after the DOT switch (2026-07-27):
  validator.py          validate_cfg() still used; validate_mermaid() is dead
  normalizer.py         normalize_edge_label() still used by dot_builder
  builder.py            build_mermaid() — dead code (superseded by dot_builder)

pkb/
  builder.py            ProjectKnowledgeBase — caller/callee index + context packets
  knowledge.py          FunctionKnowledge dataclass and JSON serialisation
  cache.py              Disk cache for the PKB

output/
  writer.py             Writes per-source-file JSON to --out-dir

project_scanner.py      Standalone tool — builds project_knowledge.json
                        (file summaries, function purposes, phase breakdowns)

tests/
  test_cfg_topo.py      Layer-1 & Layer-2 test runner (see Testing section)
```

---

## Label Policy

**A label is descriptive prose that names every function the node calls, each
written `Name()` with the arguments stripped.**

What stays constant is the content — every call present, in the uniform
`Name()` form. What varies is the phrasing: the name goes where the code puts
it. `via X()` is wrong wherever the callee doesn't perform the action; in
`functionX()->timeSlot = False` the function only returns the object being
written, so the verb belongs to the assignment.

| C++ shape | What the call does | Label |
|---|---|---|
| `sz = functionJ();` | supplies a value | Get somethingZ by calling `functionJ()` |
| `functionX()->timeSlot = False;` | supplies the object written | Set the time slot in `functionX()` to False |
| `sa = &functionA()->sa;` | supplies the object read | Update sa with the address of sa in `functionA()` |
| `ServerReplicate(part, id);` | **is** the action | Replicate partition state with `ServerReplicate()` |
| `doc.AddMember("initiator", id);` | **is** the action | Add the initiator ID to the JSON body using `doc.AddMember()` |

Three places implement this and must agree, all keyed off `cpp_tokens.py`:
the enricher declares `call_names`, the prompt requires every one of them, and
`generator.enforce_call_names()` verifies and repairs afterwards — so a label
is correct even when the LLM drifts or the batch falls back to a rule-based
label.

**Not named** (each already has its own prompt rule, and naming them would
contradict it): logging macros, assertions, casts, and constructors.
Constructors can't be separated from calls textually — `Point(1, 2)` and
`process(1, 2)` are the same shape — so the enricher passes known struct/enum/
typedef names to `extract_call_names(exclude=…)`.

A high append count in the logs (`appended missing call names on N node(s)`)
means the prompt isn't landing. Fix the prompt; the enforcement pass is the
safety net, not the mechanism.

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.9+    |
| libclang    | 16+     |
| Ollama      | any     |
| A code-capable LLM model | e.g. `qwen2.5-coder:7b` |

```bash
pip install -r requirements.txt
```

Ollama must be running locally:
```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

---

## Input Files

### functions.json
Generated by your C++ analyser. Each key is a unique function identifier.

```json
{
  "src|myfile|MyClass::myMethod|int,bool": {
    "qualifiedName": "MyClass::myMethod",
    "location": {
      "file": "src/myfile.cpp",
      "line": 42,
      "endLine": 85
    },
    "parameters": [
      { "type": "int",  "name": "x" },
      { "type": "bool", "name": "flag" }
    ],
    "callsIds":    ["src|util|helper|void"],
    "calledByIds": ["src|main|main|int"],
    "description": "Processes x with the given flag."
  }
}
```

### metadata.json
```json
{
  "basePath":    "/absolute/path/to/cpp/project",
  "projectName": "MyProject"
}
```

### project_knowledge.json (optional)
Built by `project_scanner.py`. Provides richer semantic context for LLM labels.

---

## Usage

### Basic — generate flowcharts

```bash
python flowchart_engine.py \
    --interface-json functions.json \
    --metaData-json  metadata.json  \
    --out-dir        output/        \
    --llm-url        http://localhost:11434 \
    --llm-model      qwen2.5-coder:7b
```

### With project knowledge (better labels)

```bash
# Step 1: build project knowledge (run once, or when code changes significantly)
python project_scanner.py \
    --interface-json functions.json \
    --metaData-json  metadata.json  \
    --llm-url        http://localhost:11434 \
    --llm-model      qwen2.5-coder:7b \
    --llm-summarize \
    --out             project_knowledge.json

# Step 2: generate flowcharts using that knowledge
python flowchart_engine.py \
    --interface-json  functions.json \
    --metaData-json   metadata.json  \
    --knowledge-json  project_knowledge.json \
    --out-dir         output/        \
    --llm-url         http://localhost:11434 \
    --llm-model       qwen2.5-coder:7b
```

### Single function only

```bash
python flowchart_engine.py \
    --interface-json functions.json \
    --metaData-json  metadata.json  \
    --out-dir        output/        \
    --function-key   "src|myfile|MyClass::myMethod|int,bool"
```

### With missing headers

If your project has headers in non-standard locations, pass them to libclang:

```bash
python flowchart_engine.py \
    --interface-json functions.json \
    --metaData-json  metadata.json  \
    --out-dir        output/        \
    --clang-arg      -I/path/to/include \
    --clang-arg      -I/another/include
```

---

## Output Format

Each source file produces one JSON file in `--out-dir`:

```
output/
  myfile.json
  another_module.json
  _summary.json
```

Each JSON file is an array:

```json
[
  {
    "functionKey":   "src|myfile|MyClass::myMethod|int,bool",
    "name":          "MyClass::myMethod",
    "flowchart":     "digraph G {\n  N0 [shape=ellipse, label=\"Start: myMethod\"];\n  ...\n}"
  },
  {
    "functionKey":   "src|myfile|MyClass::otherMethod|void",
    "name":          "MyClass::otherMethod",
    "flowchart":     "digraph G {\n  ...\n}",
    "error":         null
  }
]
```

The `flowchart` field holds a **Graphviz DOT** script (the `FlowchartResult`/schema field is still named
`mermaid_script` for back-compat, but its content is DOT). Render it with the project renderer
(`engine.utils.render_dot_cached`) or paste it into any Graphviz viewer (e.g. [dreampuf.github.io/GraphvizOnline](https://dreampuf.github.io/GraphvizOnline)).

---

## Example Walkthrough

### C++ function

```cpp
// src/classifier.cpp
int classify(int x) {
    if (x > 0) {
        return 1;
    } else if (x < 0) {
        return -1;
    } else {
        return 0;
    }
}
```

### What the engine does step-by-step

**Step 1 — CFG Extraction**

libclang parses `classify` and produces:

```
Nodes:
  N0  START     ""
  N1  DECISION  "x > 0"
  N2  RETURN    "return 1"
  N3  DECISION  "x < 0"
  N4  RETURN    "return -1"
  N5  RETURN    "return 0"
  N6  END       ""

Edges:
  N0 → N1         (entry)
  N1 → N2  [Yes]  (x > 0 true branch)
  N1 → N3  [No]   (x > 0 false branch)
  N3 → N4  [Yes]  (x < 0 true branch)
  N3 → N5  [No]   (else branch)
  N2 → N6         (return to end)
  N4 → N6
  N5 → N6
```

**Step 2 — Topological Sort**

Nodes sorted in execution order: `N0 → N1 → N2 → N3 → N4 → N5 → N6`
No back-edges (no loops in this function).

**Step 3 — Batching**

Split at branch points:
```
Batch 1: [N1]       ← first DECISION — flush immediately
Batch 2: [N2, N3]   ← return + second DECISION
Batch 3: [N4, N5]   ← two return branches
```

**Step 4 — LLM Labeling**

LLM receives each batch with context and responds:
```
N1 → "Is x greater than zero?"
N2 → "Return positive (1)"
N3 → "Is x less than zero?"
N4 → "Return negative (-1)"
N5 → "Return zero"
```

**Step 5 — DOT Output**

```
digraph G {
  rankdir=TB; nodesep=1.5; ranksep=0.9;
  N0 [shape=ellipse, label="Start: classify"];
  N1 [shape=diamond, label="Is x greater than zero?"];
  N2 [shape=box,     label="Return positive 1"];
  N3 [shape=diamond, label="Is x less than zero?"];
  N4 [shape=box,     label="Return negative -1"];
  N5 [shape=box,     label="Return zero"];
  N6 [shape=ellipse, label="End"];

  N0 -> N1;
  N1 -> N2 [taillabel="Yes"];
  N1 -> N3 [taillabel="No"];
  N3 -> N4 [taillabel="Yes"];
  N3 -> N5 [taillabel="No"];
  N2 -> N6;  N4 -> N6;  N5 -> N6;
}
```

---

## Debugging

### See exactly what the LLM receives

```bash
FLOWCHART_TRACE=1 python flowchart_engine.py ...
```

Prints the full system prompt and user prompt for every batch to stdout.

### LLM context overflow

If labels are falling back to raw code, the LLM context window may be too small. Increase it:

```bash
python flowchart_engine.py ... --llm-num-ctx 16384
```

---

## Testing

The test runner validates the deterministic parts of the pipeline (no LLM required).

### Layer 1 — CFG and Topological Sort invariants

```bash
python tests/test_cfg_topo.py \
    --interface-json functions.json \
    --metadata-json  metadata.json
```

What it checks for each function:

```
CFG invariants:
  - At least one node exists
  - Entry node is set and points to a real node
  - Every edge's source/target is a valid node ID
  - Exactly one START node
  - At least one END node

Topological sort invariants:
  - Every CFG node appears in the output exactly once
  - Entry node is first
  - For every forward edge A→B: A appears before B in the order
  - Every back-edge (loop) points from a later node to an earlier one
```

### Layer 2 — CFG node-type counts vs rendered shape counts (⚠ STALE — dormant)

Cross-checks that the number of each CFG node-type equals the number of matching shapes in the persisted
diagram (opt-in via `--out-dir`). **This layer is currently stale:** `_count_mermaid_shapes` still parses
**Mermaid** syntax (`([`, `{`, `[[`, `[`), but the persisted `flowchart` field is now **Graphviz DOT**
(`shape=diamond`/`ellipse`/`box`). Because it only runs when `--out-dir` is passed, it is dormant in normal
CI and was not caught by the 2026-07-27 DOT switch. **TODO:** port `_count_mermaid_shapes` to count DOT
`shape=` attributes (tracked in `docs/BACKLOG.md`). Until then, rely on Layer 1 (CFG + topo invariants),
which is format-independent and always runs.

### Test a single function

```bash
python tests/test_cfg_topo.py \
    --interface-json functions.json \
    --metadata-json  metadata.json  \
    --function-key   "src|myfile|MyClass::myMethod|int,bool"
```

### With extra include paths

```bash
python tests/test_cfg_topo.py \
    --interface-json functions.json \
    --metadata-json  metadata.json  \
    --clang-arg      -I/path/to/headers
```

### Sample output

```
Testing 42 function(s) from functions.json
base_path=/home/user/myproject  std=c++14
============================================================

[PASS] MyClass::processRequest
       key: src|myfile|MyClass::processRequest|int
     OK  cfg.cursor_resolved
     OK  cfg.nodes_not_empty: 12 node(s)
     OK  cfg.entry_node_exists: entry_node_id='N0'
     OK  cfg.edges_reference_valid_nodes: 14 edge(s) all valid
     OK  cfg.exactly_one_start_node: START count=1
     OK  cfg.has_end_node: END count=1
     OK  topo.all_nodes_present_no_duplicates: 12 node(s) in order
     OK  topo.entry_node_is_first: first='N0' entry='N0'
     OK  topo.forward_edges_respect_order: all forward edges ordered correctly
     OK  topo.back_edges_are_backward: 0 back-edge(s) all valid

============================================================
PASSED  42/42 functions
```

(Layer-1 only; the Layer-2 shape cross-check is dormant — see above.)
