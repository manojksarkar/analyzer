# Logic for SWE.4 Unit Test Specification (V1)

**Contents:** [What is produced](#what-is-produced) · [Who gets a spec](#who-gets-a-spec) ·
[Table A](#table-a--the-test-content) · [Table B](#table-b--the-metadata) ·
[Worked example](#worked-example) · [Dynamic Behaviour test specs](#dynamic-behaviour-test-specs)

---

## What is produced

One `Software Unit Test Specification` document per group, generated from the parsed source code and the
SWE.3 detailed design. Specifications only — no runnable test code, nothing is executed.

```
1  Introduction
2  Software Unit Test Specification
   2.N  <Component>
        2.N.X  <Unit>
               <one spec per function: Table A + Table B>
        Dynamic Behaviour test specs  (only when the component has dynamic behaviour)
3  Code Metric, Coding Rule, Test Coverage
Appendix A  Reference
```

---

## Who gets a spec

- Every function that appears in the SWE.3 detailed design gets a spec.
- **Except inline public functions** — those defined in a header. They get no spec of their own; they are
  covered through the functions **of their own unit** that call them. A caller in another unit mocks them
  instead (see Precondition), so an inline function with no caller in its own unit is covered nowhere. Known
  gap — closing it means giving inline functions a spec, which this section rules out.

---

## Table A — the test content

One header row and **one data row per function**, six columns.

**Numbering.** Precondition, Input, Test Steps and Expected Results are all numbered lists — `1)`, `2)`,
`3)`. Only **Test Steps** nests, because it follows the control flow: `2.1)`, `2.1.3)`, `2.1.3.4)`. The other
three stay flat — where an entry has several values, they are separated by commas on the same line.

### Eval. Equipment Name

- Can be taken as input from the user; default `Emulator`.

### Precondition

- A callee is **mocked** when either holds: it **has a spec of its own**, or it belongs to a **different unit**
  than the function under test. This is a *unit* test spec, not an integration test spec — nothing outside the
  unit under test may execute, whether or not a spec covers it elsewhere.
- Only a callee that is **this unit's own and has no spec** runs inline — a same-unit private helper, or a
  same-unit inline public function. It must execute, or its branches are exercised nowhere and coverage could
  never reach 100%.
- A unit is a **path, not a file**: `Foo.h` and `Foo.cpp` are one unit, and a header with no `.cpp` beside it is
  a unit of its own. So an inline public function counts as this unit's code only when it sits in this unit's
  own header; from any other header it is mocked, however many units include it.
- A stub does not execute, so nothing it calls is mocked either — a callee reached **only** through a mock is
  not this spec's concern. Only callees reached through the code that really runs are listed.
- Library calls that cannot be named are left out.
- Every parameter is listed, with its type.
- Every global the function reads or writes is listed — including through inlined private helpers — as
  `type variable` only. No direction, no range, no value.
- Local variables never appear.
- Three entries: `1)` mock functions, `2)` parameters, `3)` globals — each a comma-separated list.
- Nothing to list → `None`.

### Input

- **Input is the Precondition, plus more.** Every Precondition item the function reads appears here with its
  range — parameters, globals that are read, and mocks that return a value. Precondition names them; Input
  gives them their ranges.
- **Plus anything else a decision depends on** that Precondition does not name — a value a mock writes back
  through a pointer, a struct field. Written the same way, one entry each.
- **Excluded:** out-parameters, write-only globals, and `void` mocks. They have no value to set — they are
  outputs, and belong in Expected Results.
- Each entry is written `type variable[start value-end value]`, a mock as `type name()[start value-end value]`.
- A type with no meaningful range, such as a pointer or a struct, is written without brackets.
- **No descriptions.** The entry is the typed input and its range, nothing else.
- Nothing read → `VOID`.

### Test Steps

- A numbered transcription of the function's flowchart — one step per node, in flow order.
- A decision sub-numbers its two legs: `2.1) True: …` / `2.2) False: …`, nesting deeper for nested decisions.
- Plain English, naming the variables involved. A mocked callee reads *"expect mock function `name`"*.
- **Every function name appears** — the function under test, every mock, and every inlined helper. A helper
  is named where it is called, not described in the abstract.
- Every `return` in the function is its own step, so Expected Results can point at it.
- Ends where the function exits. There is no closing "verify the result" step — checking the outcome is what
  Expected Results is for.

### Expected Results

- Each entry is an assertion, written `Successfully …`, and **names the step it comes from** —
  `Successfully returned <value> in step 2`.
- `1)` is always the mocks: `Successfully called mock functions <names>`.
- **Every return in the function gets its own entry** — one per exit, not one range covering them all.
- Then one entry per out-parameter written and per global written, with its range in brackets,
  `[lower-upper]`, the same way Input writes them.
- Nothing changes → say so explicitly.

### Test Platform

- Can be taken as input from the user; default `VectorCAST` for now.

---

## Table B — the metadata

One Table B per function, in a vertical form layout.

- **Test Case ID** — derived from the function's interface ID (`TC_<interfaceId>`), falling back to the
  qualified function name when it has no interface entry. One ID per function.
- **Priority** — from configuration; default `Medium`.
- **Test Environment** — from configuration; default `Emulator`.
- **Test Case Generation Method** — fixed at `Analysis of Requirements`: cases are derived from the unit's
  specified behaviour (signature, SWE.3 design, return and out-parameters). Not configurable.
- **Alias Test ID · Risk · Test Method · Linked Work Items** — left as `-`. These link to requirements, and
  there is no requirements source available yet (Polarion / SWE.1).

Eval. Equipment Name, Test Platform and Test Environment are three independent fields, each set separately.

---

## Worked example

One function chosen to exercise almost every rule at once — an inlined private helper, two mocked cross-unit
callees, globals of all three directions, a loop, a switch with a default, an out-parameter, and five return
paths.

```c
// ---- unit FtlMap.cpp ----
static uint16_t gEntryCount = 64;             // read
static uint32_t gLastLba    = 0;              // written
static uint8_t  gErrCount   = 0;              // read/write

static bool isValidLba(uint32_t lba);         // same-unit private -> inlined, never mocked
int  FilReadPage(uint16_t idx, MapEntry* e);  // cross-unit -> mocked
void HilNotify(uint8_t code);                 // cross-unit -> mocked

int FtlLookup(uint32_t lba, uint8_t mode, uint32_t* ppnOut)
{
    if (!isValidLba(lba)) {
        gErrCount++;
        HilNotify(ERR_RANGE);
        return -1;
    }
    MapEntry e;
    for (uint16_t i = 0; i < gEntryCount; i++) {
        if (FilReadPage(i, &e) != 0) {
            gErrCount++;
            return -2;
        }
        if (e.lba == lba) {
            switch (mode) {
                case MODE_READ: *ppnOut = e.ppn;       break;
                case MODE_TRIM: *ppnOut = PPN_INVALID; break;
                default:        return -3;
            }
            gLastLba = lba;
            return 0;
        }
    }
    return -4;
}
```

### Table A

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | 1) Mock functions: `FilReadPage()`, `HilNotify()`<br>2) Parameters: `uint32_t lba`, `uint8_t mode`, `uint32_t* ppnOut`<br>3) Globals: `uint16_t gEntryCount`, `uint32_t gLastLba`, `uint8_t gErrCount` | 1) `uint32_t lba[0-4294967295]`<br>2) `uint8_t mode[0-255]`<br>3) `uint16_t gEntryCount[0-65535]`<br>4) `uint8_t gErrCount[0-255]`<br>5) `int FilReadPage()[-2147483648-2147483647]`<br>6) `uint32_t e.lba[0-4294967295]`<br>7) `uint32_t e.ppn[0-4294967295]` | 1) Issue function `FtlLookup` with inputs `lba`, `mode` and output buffer `ppnOut`.<br>2) Call `isValidLba` with `lba` and check whether it returns true.<br>&nbsp;&nbsp;2.1) True: continue to step 3.<br>&nbsp;&nbsp;2.2) False: increase `gErrCount` by one; expect mock function `HilNotify` with the range-error code; return -1.<br>3) Repeat for each index `i` from 0 while `i` is less than `gEntryCount`.<br>&nbsp;&nbsp;3.1) Expect mock function `FilReadPage` with input `i` and entry buffer `e`.<br>&nbsp;&nbsp;3.2) Check whether `FilReadPage` returned zero.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.2.1) True: continue to step 3.3.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.2.2) False: increase `gErrCount` by one; return -2.<br>&nbsp;&nbsp;3.3) Check whether the entry's `lba` is equal to `lba`.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.3.1) True: select on `mode`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.1) `MODE_READ`: set `ppnOut` to the entry's `ppn`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.2) `MODE_TRIM`: set `ppnOut` to `PPN_INVALID`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.3) Any other mode: return -3.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.4) Set `gLastLba` to `lba`; return 0.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.3.2) False: continue with the next index.<br>4) Return -4.<br>5) Exit. | 1) Successfully called mock functions `FilReadPage()`, `HilNotify()`<br>2) Successfully returned `-1` in step 2.2<br>3) Successfully returned `-2` in step 3.2.2<br>4) Successfully returned `-3` in step 3.3.1.3<br>5) Successfully returned `0` in step 3.3.1.4<br>6) Successfully returned `-4` in step 4<br>7) Successfully updated `uint32_t* ppnOut` in range `[0-4294967295]` in steps 3.3.1.1, 3.3.1.2<br>8) Successfully updated `uint32_t gLastLba` in range `[0-4294967295]` in step 3.3.1.4<br>9) Successfully updated `uint8_t gErrCount` in range `[0-255]` in steps 2.2, 3.2.2 | VectorCAST |

Note what is **not** in the Precondition: `isValidLba`. It is a private helper of the same unit, so it runs
inline and its branch shows up in the test steps as an ordinary decision rather than as a mock.

### Table B

| | |
|---|---|
| Test Case ID | `TC_FTL_MAP_02` |
| Alias Test ID | `-` |
| Priority | Medium |
| Risk | `-` |
| Test Method | `-` |
| Test Environment | Emulator |
| Test Case Generation Method | Analysis of Requirements |
| Linked Work Items | `-` |

---

## Dynamic Behaviour test specs

A second kind of spec — one per **interaction**, not per function. It sits under its component, after that
component's units, and exists **only when the component has dynamic behaviour**.

The set is not decided here: **a dynamic-behaviour spec exists exactly where SWE.3 draws a behaviour
diagram.** The two pair one-to-one, and the diagram is the spec's scope statement.

### Which functions get one

All four conditions hold — they are the behaviour-diagram selection rules:

- The function is **public**. Private functions are dropped before selection.
- It has an **external caller** — a caller in a different component, or, when one group is generated, any
  caller outside that group.
- Its forward call chain, followed **within its own component**, touches **more than one unit**. A function
  that only calls into its own unit has no interaction to specify.
- **One spec per function**, from its first external caller. A function called from several places gets one
  spec, not one per caller.

Nothing selected → the component has no Dynamic Behaviour sub-section at all.

### Scope — the diagram is the boundary

- The **entry point** is the external caller, named `<CallerUnit> - <callerFunction>`. The spec starts there,
  not at the function under test.
- **Every unit the diagram shows executes.** This is the one place the unit boundary widens: an in-component
  callee that a function spec would mock runs for real here, because the interaction between those units is
  exactly what is being verified.
- **Everything the diagram does not show is mocked** — every call leaving the component, including calls back
  into the caller's own component. Those edges are dropped from the trace, so they never execute.
- **A same-unit hop is not an arrow, but it is still a step.** The diagram skips it and bridges to the next
  cross-unit call; the code runs all the same, so it is transcribed like any other executing branch.

### The tables

Table A and Table B keep their columns. What changes:

- **Precondition** — mocks are the **cross-component** callees, not the cross-unit ones. Parameters and globals
  are those of the entry-point call.
- **Test Steps** — transcribe the interaction the way a function spec transcribes a flowchart: in flow order,
  nesting on decisions, every mock and every return its own step. The difference is **attribution** — a
  cross-unit call is written `<Unit> calls <Unit>.<function>`, so every step says which unit is acting.
  Arrows alone are not enough: a mock, or an assignment between two arrows, would have no step to sit in and
  Expected Results could not name its step. The diagram's LLM-written call description is presentation only
  and **never enters the spec** — these tables stay deterministic.
- **Expected Results** — `1)` the mocks, then one entry per **cross-unit call** that must be observed — the
  interaction is what this spec exists to verify — then the returns and the writes, ordered exactly as a
  function spec orders them.
- **Test Case ID** — **open.** It has to stay distinct from the `TC_<interfaceId>` of the same function's own
  spec, and no scheme is agreed yet.

### Worked example — an interaction

One component, `FTL`, whose unit `FtlMap` is entered from `HIL` and fans out to a second `FTL` unit,
`FtlCache`, while its `FIL` callee is mocked — the smallest shape that qualifies.

```c
// ---- component HIL, unit HilCore.cpp ----
int HilRead(uint32_t lba, uint8_t* buf);        // external caller -> the entry point

// ---- component FTL, unit FtlCache.cpp ----
static uint32_t gCacheHits = 0;                 // written here, still in scope
bool FtlCacheGet(uint32_t lba, uint32_t* ppnOut);
void FtlCacheStore(uint32_t lba, uint32_t ppn); // increments gCacheHits

// ---- component FIL, unit FilNand.cpp ----
int  FilReadPage(uint16_t idx, MapEntry* e);    // different component -> mocked

// ---- component FTL, unit FtlMap.cpp — the unit under test ----
static uint16_t gEntryCount = 64;               // read
static bool isValidLba(uint32_t lba);           // same unit -> no arrow, still a step

int FtlResolve(uint32_t lba, uint32_t* ppnOut)
{
    if (!isValidLba(lba))         return -1;
    if (FtlCacheGet(lba, ppnOut)) return 0;

    MapEntry e;
    for (uint16_t i = 0; i < gEntryCount; i++) {
        if (FilReadPage(i, &e) != 0) return -2;
        if (e.lba == lba) {
            *ppnOut = e.ppn;
            FtlCacheStore(lba, e.ppn);
            return 0;
        }
    }
    return -3;
}
```

Headings, where the component has `U` units: `2.N.<U+1> Dynamic Behaviour`, then
`2.N.<U+1>.1 FtlMap - FtlResolve (HilCore - HilRead)`.

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | 1) Mock functions: `FilReadPage()`<br>2) Parameters: `uint32_t lba`, `uint32_t* ppnOut`<br>3) Globals: `uint16_t gEntryCount`, `uint32_t gCacheHits` | 1) `uint32_t lba[0-4294967295]`<br>2) `uint16_t gEntryCount[0-65535]`<br>3) `int FilReadPage()[-2147483648-2147483647]`<br>4) `uint32_t e.lba[0-4294967295]`<br>5) `uint32_t e.ppn[0-4294967295]` | 1) `HilCore` calls `FtlMap.FtlResolve` with `lba` and output buffer `ppnOut`.<br>2) Call `isValidLba` with `lba` and check whether it returns true.<br>&nbsp;&nbsp;2.1) True: continue to step 3.<br>&nbsp;&nbsp;2.2) False: `FtlMap` returns -1 to `HilCore`.<br>3) `FtlMap` calls `FtlCache.FtlCacheGet` with `lba` and `ppnOut`, and checks whether it returns true.<br>&nbsp;&nbsp;3.1) True: `FtlCache` has written the cached `ppn` into `ppnOut`; `FtlMap` returns 0 to `HilCore`.<br>&nbsp;&nbsp;3.2) False: continue to step 4.<br>4) Repeat for each index `i` from 0 while `i` is less than `gEntryCount`.<br>&nbsp;&nbsp;4.1) Expect mock function `FilReadPage` with input `i` and entry buffer `e`.<br>&nbsp;&nbsp;4.2) Check whether `FilReadPage` returned zero.<br>&nbsp;&nbsp;&nbsp;&nbsp;4.2.1) True: continue to step 4.3.<br>&nbsp;&nbsp;&nbsp;&nbsp;4.2.2) False: `FtlMap` returns -2 to `HilCore`.<br>&nbsp;&nbsp;4.3) Check whether the entry's `lba` is equal to `lba`.<br>&nbsp;&nbsp;&nbsp;&nbsp;4.3.1) True: set `ppnOut` to the entry's `ppn`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;4.3.1.1) `FtlMap` calls `FtlCache.FtlCacheStore` with `lba` and the entry's `ppn`; `gCacheHits` increases by one.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;4.3.1.2) `FtlMap` returns 0 to `HilCore`.<br>&nbsp;&nbsp;&nbsp;&nbsp;4.3.2) False: continue with the next index.<br>5) `FtlMap` returns -3 to `HilCore`.<br>6) Exit. | 1) Successfully called mock functions `FilReadPage()`<br>2) Successfully called `FtlCache.FtlCacheGet` in step 3<br>3) Successfully called `FtlCache.FtlCacheStore` in step 4.3.1.1<br>4) Successfully returned `-1` in step 2.2<br>5) Successfully returned `0` in step 3.1<br>6) Successfully returned `-2` in step 4.2.2<br>7) Successfully returned `0` in step 4.3.1.2<br>8) Successfully returned `-3` in step 5<br>9) Successfully updated `uint32_t* ppnOut` in range `[0-4294967295]` in steps 3.1, 4.3.1<br>10) Successfully updated `uint32_t gCacheHits` in range `[0-4294967295]` in step 4.3.1.1 | VectorCAST |

Two things a function spec could not have produced. `FtlCacheGet` and `FtlCacheStore` are **not** in the
Precondition — they are `FTL`'s own, in another unit, and here they run. And `gCacheHits` belongs to
`FtlCache`, a unit that is not itself under test; it is in scope only because that unit executes.

Table B is the function spec's, with the Test Case ID left open.

### Status

**Implemented.** `engine/views/dynamic_specs.py` derives the specs, `views/test_steps.py::attach_dynamic`
splices the callee flow, and the SWE.4 exporter writes the sub-section. Selection is delegated to the
behaviour-diagram selector, so a spec exists exactly where SWE.3 draws a diagram.

Two limits worth knowing:

- **A branch head is attributed but not descended into.** `if (FtlCacheGet(...))` names the call and the
  units, but the callee's own flow is not spliced under it — a decision numbers its legs off the same
  prefix the spliced steps would use. Only plain steps splice today.
- **Callees are matched by short name.** Two executing callees sharing one short name are both left
  un-spliced rather than risk splicing the wrong body.

The client's own wiki page carries a longer version of this section still to be reconciled with the rules
above. The Test Case ID suffix (`_DYN`) is provisional, pending the scheme decision.
