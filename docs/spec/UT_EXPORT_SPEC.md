# UT Export Spec — unit-test JSON

Update this doc first when changing UT-export logic, then code + tests.
Companion: [SWE4_WIKI](SWE4_WIKI.md) (what the specs mean) · Plan: [engine/PLAN.md](../../engine/PLAN.md)

**Current understanding** of the target format and how each field is derived from the ArtiFex model.
Items marked **?** are not settled yet; see Open items.

---

## 1. The two files

### 1.1 The hierarchy file

Maps the test tree onto the source tree.

```
<hierarchy file>
├── Macros
│   ├── HCoreMacros
│   ├── FCoreMacros
│   └── NCoreMacros
└── LayerMapping
    └── [Layer]                       e.g. "HIL"
        ├── searchdirectories: [dir1, dir2, ...]
        └── Sections
            └── [Section]
                ├── SectionID
                ├── SectionName
                └── Units
                    └── [Unit]
                        ├── unit_id
                        ├── Filename
                        ├── FilePath
                        ├── CoreType
                        ├── IsHeader
                        ├── Corresponding_cpp        (if IsHeader = true)
                        ├── Corresponding_cpp_path   (if IsHeader = true)
                        └── Testcases → [Testcase]   (see §2)
```

`Section` is our **component**, `Layer` our **layer**. The `Corresponding_cpp` pairing is the same
idea as our "a unit is a path, not a file" rule — `Foo.h` and `Foo.cpp` are one unit, see
[SWE4_WIKI § Precondition](SWE4_WIKI.md).

### 1.2 The test-spec file

```jsonc
{
  "format_version": "1.0",
  "environment": {
    "flags":      [ /* how to spell paths: namespace style, nullptr style, … */ ],
    "probepoint": [ /* custom code before/after a specific line of the original source */ ],
    "usercode":   [ /* code invoked just before the test, e.g. memory init, setup */ ]
  },
  "cases": [ /* one object per test case */ ]
}
```

Each case carries its sections **in this order**:

```
id → name → level → trace → review → target → preconditions → stubs → inputs → expected
```

| field | type | meaning |
|---|---|---|
| `id` | String | Unique test-case identifier, e.g. `"TC-ROUTER-001"` |
| `name` | String | Human-readable description of what the test validates |
| `level` | String | `"UT"` — one function in isolation |
| `trace` | String | Requirement ID(s) validated, e.g. `"REQ-ROUTER-010"` |
| `review` | Object | DO-178C compliance: author and reviewer information |
| `target` | Object | Which function/class is under test |
| `preconditions` | Object | State that exists before the test runs |
| `stubs` | Array | Dependencies replaced with stubs |
| `inputs` | Array | What is passed to the function |
| `expected` | Object | Return, globals, class members, stub params |

Testcase-level identity fields: `TestcaseID`, `ClassName`, `FunctionName`.

---

## 2. Derivation

### REQ-UE-01 — Everything SWE.4 emits is `level: "UT"`

Both SWE.4 spec kinds are unit-test specifications — the two sections of one
`Software Unit Test Specification` document:

| spec kind | `level` | source |
|---|---|---|
| per-function spec | `"UT"` | `test_specs.json` → `<unit>.functions[]` |
| dynamic-behaviour spec | `"UT"` | `test_specs.json` → `dynamicSpecs[]` |

**Verification:** every emitted case has `level: "UT"`.

### REQ-UE-02 — Field mapping

| field | source | status |
|---|---|---|
| `id` | `spec.testCaseId` (`TC_<interfaceId>`) | ready |
| `name` | `spec.name` / `spec.qualifiedName` | ready |
| `level` | REQ-UE-01 | ready |
| `trace` | — no requirements source (Polarion / SWE.1) | **gap** — emit empty |
| `review` | not derivable from code | **config** — author/reviewer keys |
| `target.ClassName` / `.FunctionName` | split `spec.qualifiedName` on `::` | ready |
| `preconditions` | `spec.precondition.globals` + each global's `value` (initial value, in the model) | ready |
| `stubs` | `spec.precondition.mockFunctions` | **needs enrichment** — REQ-UE-03 |
| `expected` | `spec.expected` — `returns[]`, `outParameters[]`, `globals[]` | ready; stub-param expectations need REQ-UE-03 |
| `inputs` | `spec.input.entries[]` — typed, with ranges | ranges only — REQ-UE-04 |

Hierarchy file:

| field | source | status |
|---|---|---|
| `Layer` | run layer | ready |
| `SectionID` / `SectionName` | component | ready |
| `unit_id` / `Filename` / `FilePath` | `spec.unitKey`, `unit.fileName`, `spec.location.file` | ready |
| `IsHeader` | `views/test_specs.py::_is_header` | ready |
| `Corresponding_cpp[_path]` | the unit's `.cpp` sibling — units are already path-keyed | ready |
| `searchdirectories` | layer/component paths from config | ready |
| `CoreType` | H/F/N core concept, matching `Macros` | **?** — needs definition |
| `Macros` (H/F/NCoreMacros) | our per-layer macros config | **?** — confirm the split |

### REQ-UE-03 — Stubs need full signatures

`views/test_specs.py::_mock_functions` returns bare strings (`"FilReadPage()"`). A `stubs` entry
replaces a dependency, and `expected` asserts on stub params — neither is possible without the
callee's return type, parameter types and declaring header. All three are on the callee's model
entry; the view simply does not project them.

**Verification:** every `stubs[]` entry carries a return type and a typed parameter list.

### REQ-UE-04 — One `cases[]` object per test case, not per function

**This is the crux.** `cases` is one object per *test case*; SWE.4 v1 emits one spec per *function*,
covering every exit in a single row. A generator handed one case per function has to invent the
split itself.

The bridge already exists in the model: `spec.expected.returns[].step` names which numbered step
each return exits from, so the paths are already distinguished — they are simply collapsed into one
spec for the document. Splitting them yields one case per path, each with its own `inputs` and
`expected`.

What each case then needs beyond the split:

- **`inputs` with values, not only ranges.** V1 gives `type name[low-high]` per input. A case needs
  an assignment that reaches its path.
- **Path conditions.** The predicate for each branch currently exists only as English inside
  `testSteps[].text` (*"Check whether sample < 0."*). The CFG has the structure; the view flattens
  it. Without it neither side can solve for values.

Interim: one case per spec, ids unsuffixed. Target: one case per path.

**Verification:** case count equals the number of distinct paths, and every case's `expected.return`
matches the return at its path's exit step.

### REQ-UE-05 — `environment` is configuration, not derivation

`flags`, `probepoint` and `usercode` describe the test harness, not our source. Carry them from
config verbatim; never synthesise them.

**Verification:** the emitted `environment` block equals the configured one byte for byte.

---

## 3. Worked example

`coreNestedBranch` — four paths and three stubbed callees, the smallest function that exercises both
REQ-UE-03 and REQ-UE-04. Source at [Core.cpp:112](../../SampleCppProject/Layer1/Sample/Core/Core.cpp#L112):

```c
PUBLIC int coreNestedBranch(int a, int b) {
    if (a > 0) {
        if (b > 0) return libAdd(a, b);            // step 2.1.1.1
        else       return utilCompute(a, -b);      // step 2.1.1.2
    } else {
        if (b > 0) return libNormalize(b, a < -100 ? 100 : -a);   // step 2.2.1.1
        else       return 0;                       // step 2.2.1.2
    }
}
```

### What SWE.4 emits today — one spec, four returns

```jsonc
{
  "testCaseId": "TC_IF_LAYER1_CORE_06",
  "qualifiedName": "coreNestedBranch",
  "precondition": { "mockFunctions": ["libAdd()", "libNormalize()", "utilCompute()"],
                    "parameters": [ { "name": "a", "type": "int" },
                                    { "name": "b", "type": "int" } ] },
  "input": { "entries": [ { "kind": "parameter",  "name": "a", "text": "int a[-0x80000000-0x7FFFFFFF]" },
                          { "kind": "parameter",  "name": "b", "text": "int b[-0x80000000-0x7FFFFFFF]" },
                          { "kind": "mockReturn", "name": "libAdd()",       "type": "int" },
                          { "kind": "mockReturn", "name": "libNormalize()", "type": "int" },
                          { "kind": "mockReturn", "name": "utilCompute()",  "type": "int" } ] },
  "expected": { "returns": [ { "step": "2.1.1.1", "expression": "libAdd()",       "source": "libAdd(a, b)" },
                             { "step": "2.1.1.2", "expression": "utilCompute()",  "source": "utilCompute(a, -b)" },
                             { "step": "2.2.1.1", "expression": "libNormalize()", "source": "libNormalize(b, …)" },
                             { "step": "2.2.1.2", "expression": "0",              "source": "0" } ] },
  "testSteps": [ { "number": "2",     "type": "DECISION", "text": "Check whether a > 0." },
                 { "number": "2.1.1", "type": "DECISION", "text": "Check whether b > 0." },
                 { "number": "2.2.1", "type": "DECISION", "text": "Check whether b > 0." } ]
}
```

### The four paths

| case | path conditions | inputs | stub reached | expected return |
|---|---|---|---|---|
| `…_01` | `a > 0`, `b > 0` | `a=1, b=1` | `libAdd` | the stub's value |
| `…_02` | `a > 0`, `b ≤ 0` | `a=1, b=0` | `utilCompute` | the stub's value |
| `…_03` | `a ≤ 0`, `b > 0` | `a=0, b=1` | `libNormalize` | the stub's value |
| `…_04` | `a ≤ 0`, `b ≤ 0` | `a=0, b=0` | none | `0` |

**Only one stub is reached per path.** The spec's `mockFunctions` is the union across all paths;
a per-path case narrows `stubs` to the callee actually executed — a refinement the split enables.

### The hierarchy file for this group

Layer `Layer1`, group `My Sample` — three components, one unit each:

```jsonc
{
  "Macros": {
    "HCoreMacros": [ /* … */ ],
    "FCoreMacros": [ /* … */ ],
    "NCoreMacros": [ /* … */ ]
  },
  "LayerMapping": {
    "Layer1": {
      "searchdirectories": [ "Layer1/Sample/Core", "Layer1/Sample/Lib", "Layer1/Sample/Util" ],
      "Sections": [
        {
          "SectionID": "Sample-Core",
          "SectionName": "Sample Core",
          "Units": [
            {
              "unit_id": "Sample-Core|Core",
              "Filename": "Core.cpp",
              "FilePath": "Layer1/Sample/Core/Core.cpp",
              "CoreType": "",
              "IsHeader": false,
              "Testcases": [ "TC_IF_LAYER1_CORE_06_01", "TC_IF_LAYER1_CORE_06_02",
                             "TC_IF_LAYER1_CORE_06_03", "TC_IF_LAYER1_CORE_06_04" ]
            },
            {
              "unit_id": "Sample-Core|Core.h",
              "Filename": "Core.h",
              "FilePath": "Layer1/Sample/Core/Core.h",
              "CoreType": "",
              "IsHeader": true,
              "Corresponding_cpp": "Core.cpp",
              "Corresponding_cpp_path": "Layer1/Sample/Core/Core.cpp",
              "Testcases": []
            }
          ]
        },
        { "SectionID": "Lib",  "SectionName": "Lib",  "Units": [ /* Lib.cpp,  Lib.h  */ ] },
        { "SectionID": "Util", "SectionName": "Util", "Units": [ /* Util.cpp, Util.h */ ] }
      ]
    }
  }
}
```

Every value above except `Macros` and `CoreType` comes straight from the model — `searchdirectories`
from the group's configured component paths, `SectionID`/`SectionName` from the component,
`unit_id`/`Filename`/`FilePath` from the unit, and the `Corresponding_cpp` pair from the unit's path
(`Foo.h` and `Foo.cpp` are one unit, so the sibling is already known).

> **One file or two — unresolved.** The hierarchy ends `Testcases → [Testcase] → "refer section 4"`,
> which reads as full case objects nested under each Unit. But §4.1 describes a spec file whose
> `cases` is a flat top-level array. Above, `Testcases` holds **ids** referencing the separate spec
> file; the alternative is to inline the case objects there and drop the separate file. This is the
> first Open item to settle — it decides whether the export writes one artifact or two.

### What the export produces

First and last case in full; the middle two follow the same shape.

```jsonc
{
  "format_version": "1.0",
  "environment": { "flags": [], "probepoint": [], "usercode": [] },
  "cases": [
    {
      "id": "TC_IF_LAYER1_CORE_06_01",
      "name": "coreNestedBranch returns libAdd(a, b) when a and b are both positive",
      "level": "UT",
      "trace": "",
      "review": { "author": "", "reviewer": "" },
      "target": { "ClassName": "", "FunctionName": "coreNestedBranch" },
      "preconditions": {},
      "stubs": [
        { "name": "libAdd", "returnType": "int",
          "parameters": [ { "name": "x", "type": "int" }, { "name": "y", "type": "int" } ],
          "declaredIn": "Layer1/Sample/Lib/Lib.h",
          "returns": 7 }
      ],
      "inputs":   [ { "name": "a", "type": "int", "value": 1 },
                    { "name": "b", "type": "int", "value": 1 } ],
      "expected": { "return": 7, "calls": [ "libAdd" ] }
    },
    {
      "id": "TC_IF_LAYER1_CORE_06_04",
      "name": "coreNestedBranch returns 0 when neither a nor b is positive",
      "level": "UT",
      "trace": "",
      "review": { "author": "", "reviewer": "" },
      "target": { "ClassName": "", "FunctionName": "coreNestedBranch" },
      "preconditions": {},
      "stubs": [],
      "inputs":   [ { "name": "a", "type": "int", "value": 0 },
                    { "name": "b", "type": "int", "value": 0 } ],
      "expected": { "return": 0, "calls": [] }
    }
  ]
}
```

Three things this makes concrete:

- **`ClassName` is empty** for a free function. Only a `Class::method` qualified name fills it.
- **The expected return is the stub's own value** on three of the four paths — `expression` is
  `libAdd()`, not a literal. Choosing the stub's return value and stating the expected result are
  therefore the same decision, not two.
- **Inputs are solved, not guessed.** `a=1, b=1` comes from intersecting the path conditions
  (`a > 0`, `b > 0`) with the declared range — which is why REQ-UE-04 needs those predicates
  structurally rather than as English in `testSteps[].text`.

> The **inner** shapes of `target`, `preconditions`, `stubs`, `inputs` and `expected` above are
> assumed, and the `_NN` id suffix is provisional. Both are Open items.

---

## Limitations

- **`trace` is empty.** No requirements source exists yet (Polarion / SWE.1), the same gap that
  leaves SWE.4 Table B's *Alias Test ID · Risk · Test Method · Linked Work Items* as `-`.
- **`review`** (DO-178C author/reviewer) has no code-derived source — configuration only.
- **Inline public functions get no case**, because they get no SWE.4 spec — they are covered through
  their own unit's callers. An inline function with no caller in its own unit is covered nowhere;
  known gap, see [SWE4_WIKI § Who gets a spec](SWE4_WIKI.md).

## Open items

- [ ] Confirm the full field descriptions for each case section.
- [ ] `CoreType` — what H/F/N core mean, and how a unit is classified.
- [ ] Whether `Macros` (HCore/FCore/NCoreMacros) maps onto our per-layer macros config.
- [ ] `format_version` to target — the guide is `v0.1`, the sample says `"1.0"`.
- [ ] **One file or two** — does `Units[].Testcases` hold full case objects, or ids referencing a
      separate spec file? The hierarchy implies nesting, §4.1 implies a flat `cases` array. Settle
      this first; it decides how many artifacts the export writes. See §3.
- [ ] `id` scheme vs our `TC_<interfaceId>` — the sample reads `"TC-ROUTER-001"`. Per-path cases
      (REQ-UE-04) also need a suffix scheme, and dynamic-behaviour cases need ids distinct from the
      same function's own spec — still unsettled in SWE.4 itself.
- [ ] Where a dynamic-behaviour spec's step transcription goes — its content is a multi-unit call
      sequence, and the per-case shape has no field that carries one.
