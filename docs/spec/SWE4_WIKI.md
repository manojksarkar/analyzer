# Logic for SWE.4 Unit Test Specification (V1)

**Contents:** [What is produced](#what-is-produced) · [Who gets a spec](#who-gets-a-spec) ·
[Table A](#table-a--the-test-content) · [Table B](#table-b--the-metadata) ·
[Worked example](#worked-example)

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
3  Code Metric, Coding Rule, Test Coverage
Appendix A  Reference
```

---

## Who gets a spec

- Every function that appears in the SWE.3 detailed design gets a spec.
- **Except inline public functions** — those defined in a header. They get no spec of their own; they are
  covered through the functions that call them.

---

## Table A — the test content

One header row and **one data row per function**, six columns.

**Numbering.** Precondition, Input, Test Steps and Expected Results are all numbered lists — `1)`, `2)`,
`3)`. Only **Test Steps** nests, because it follows the control flow: `2.1)`, `2.1.3)`, `2.1.3.4)`. The other
three stay flat — where an entry has several values, they are separated by commas on the same line.

### Eval. Equipment Name

- Can be taken as input from the user; default `Emulator`.

### Precondition

- A callee is **mocked** only when it has a spec of its own — a function in a different unit, or a same-unit
  function that appears in SWE.3. Its branches are covered by its own spec, so there is no need to run it here.
- A callee with **no spec of its own is never mocked** — a same-unit private helper, or an inline public
  function. It runs inline as part of the function under test; otherwise its branches would be exercised
  nowhere and coverage could never reach 100%.
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

- Each entry is an assertion, written `Successfully …`, and **names the step it comes from**.
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
| Emulator | 1) Mock functions: `FilReadPage()`, `HilNotify()`<br>2) Parameters: `uint32_t lba`, `uint8_t mode`, `uint32_t* ppnOut`<br>3) Globals: `uint16_t gEntryCount`, `uint32_t gLastLba`, `uint8_t gErrCount` | 1) `uint32_t lba[0-4294967295]`<br>2) `uint8_t mode[0-255]`<br>3) `uint16_t gEntryCount[0-65535]`<br>4) `uint8_t gErrCount[0-255]`<br>5) `int FilReadPage()[-2147483648-2147483647]`<br>6) `uint32_t e.lba[0-4294967295]`<br>7) `uint32_t e.ppn[0-4294967295]` | 1) Issue function `FtlLookup` with inputs `lba`, `mode` and output buffer `ppnOut`.<br>2) Call `isValidLba` with `lba` and check whether it returns true.<br>&nbsp;&nbsp;2.1) True: continue to step 3.<br>&nbsp;&nbsp;2.2) False: increase `gErrCount` by one; expect mock function `HilNotify` with the range-error code; return -1.<br>3) Repeat for each index `i` from 0 while `i` is less than `gEntryCount`.<br>&nbsp;&nbsp;3.1) Expect mock function `FilReadPage` with input `i` and entry buffer `e`.<br>&nbsp;&nbsp;3.2) Check whether `FilReadPage` returned zero.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.2.1) True: continue to step 3.3.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.2.2) False: increase `gErrCount` by one; return -2.<br>&nbsp;&nbsp;3.3) Check whether the entry's `lba` is equal to `lba`.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.3.1) True: select on `mode`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.1) `MODE_READ`: set `ppnOut` to the entry's `ppn`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.2) `MODE_TRIM`: set `ppnOut` to `PPN_INVALID`.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.3) Any other mode: return -3.<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3.3.1.4) Set `gLastLba` to `lba`; return 0.<br>&nbsp;&nbsp;&nbsp;&nbsp;3.3.2) False: continue with the next index.<br>4) Return -4.<br>5) Exit. | 1) Successfully called mock functions `FilReadPage()`, `HilNotify()`<br>2) Successfully returned `-1` (step 2.2)<br>3) Successfully returned `-2` (step 3.2.2)<br>4) Successfully returned `-3` (step 3.3.1.3)<br>5) Successfully returned `0` (step 3.3.1.4)<br>6) Successfully returned `-4` (step 4)<br>7) Successfully updated `uint32_t* ppnOut` in range `[0-4294967295]` (steps 3.3.1.1, 3.3.1.2)<br>8) Successfully updated `uint32_t gLastLba` in range `[0-4294967295]` (step 3.3.1.4)<br>9) Successfully updated `uint8_t gErrCount` in range `[0-255]` (steps 2.2, 3.2.2) | VectorCAST |

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
