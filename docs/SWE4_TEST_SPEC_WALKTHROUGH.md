# SWE.4 Unit Test Spec — Walkthrough (team / client discussion aid)

> **Purpose:** a plain-language explainer of how the SWE.4 unit test specification is built and how it
> is meant to reach ~100% (branch) coverage — for discussions with teammates and the client.
> **Authority:** the normative rules live in [spec/SWE4_SPEC.md](spec/SWE4_SPEC.md) and
> [planning/SWE4_PLAN.md](planning/SWE4_PLAN.md); this doc teaches and links to them, it does not
> restate them as a contract. Keep it current when SWE.4 behaviour changes.

---

## 1. What "100%" means here

Branch coverage of the unit — every branch edge (each true/false leg of every decision) exercised at
least once. **Not** path coverage (every combination), which explodes combinatorially. Every design
choice below aims at "hit every edge with the fewest input sets."

Honest caveat: coverage is **targeted, not verified** — there is no execution/coverage tool yet, so the
tool produces coverage-*targeted* inputs; proving 100% needs a run.

---

## 2. The two tables

- **Table A** (horizontal, one header + one data row) = test **content**.
  Columns: **Eval. Equipment Name · Precondition · Input · Test Steps · Expected Results · Test Platform**.
- **Table B** (vertical form) = **metadata** (Test Case ID, Generation Method, Priority, …).
  One Test Case ID per function even when Table A holds multiple input sets.

---

## 3. Precondition = the controllable environment

The setup state established **before** the call. Three parts:

1. **Mock functions** — callees to stub, written as `name()`.
2. **Parameters** — all of them (the knobs Input then binds).
3. **Consumed globals** — every global read/written (transitively through inlined helpers), with
   direction (read / write / read-write), type, range, and declared initial value if any.

Locals excluded.

**Mock rule (the crux for coverage):** inline a callee iff it is **same-unit AND hidden** (a helper with
no spec of its own — it must run inline or its branches are covered nowhere). Everything else is
**mocked**: cross-unit callees, and same-unit callees that carry their own spec. Mock returns double as
branch drivers. (See [SWE4_SPEC REQ-UT-05](spec/SWE4_SPEC.md).)

---

## 4. Input = the ranges you vary

One or more **input sets**, each expressed as a **range or constraint** — *not* a sampled concrete value.
The aim is **covering every branch**, not verifying one particular value, so a set states the condition that
reaches its branch (`a > 0`, `idx ≥ gTableSize`) and leaves the tester free to pick any member. A range
collapses to a point only when the predicate itself does (`b == 5` → `b = 5`).

Why ranges rather than values: a concrete `a = 1` implies the tool chose that number for a reason. It did
not — any positive `a` covers the same edge. Stating the range says exactly what is known, and nothing more
([SWE4_SPEC REQ-TC-06](spec/SWE4_SPEC.md) — never invent a value).

`VOID` when parameterless. Each set is index-aligned with one Expected entry. A pointer/ref parameter the
function **writes** is an **output** → it belongs in Expected, not Input.

Branch-hitting rules (the deferred Equivalence/Boundary pass):
- comparison vs literal → the two partitions either side of it (`p < K` → `p < K` / `p ≥ K`)
- `switch(param)` → one set per case label + a non-matching default
- loop bound → not-taken (`n = 0`) and taken (`n ≥ 1`)

**Boundary Value Analysis narrows these ranges to their edges** (`p < K` → `K-1` / `K`) when that pass
lands — the range is the general form, the boundary pair is a sharpening of it, not a different answer.

**Input sets are "ragged":** set count varies per function (branch-driven), set width varies per function
(input surface), and even across sets of the *same* function the width can differ — a set lists only the
inputs on the path to its target branch; the rest are don't-care.

---

## 5. Precondition vs Input — why both exist

Conceptually all of {parameters, read-globals, struct fields, mock returns} are **inputs**, each carrying
a value/range. The columns are split because:

1. It mirrors a real test's **arrange (precondition) vs act (call with params)** phases.
2. The **mock list** is structural setup ("which callees to stub"), not a value — it can't live in Input.
3. Globals show **initial** state in Precondition and **final** state in Expected (before/after symmetry).
4. The client's ASPICE template mandates the split.

Input vector  = params(read) ∪ read-globals ∪ read-fields ∪ mock-return values.
Output vector = return ∪ written out-params ∪ written globals ∪ mock-call expectations.
A read/write global appears on **both** sides.

---

## 6. VOID functions still have branches — cover them via Precondition

A `VOID` function's branches depend on globals / struct fields / mock-callee returns, not parameters. So
"varying the input" becomes "varying the **Precondition state**". Input stays `VOID`; each case is
distinguished by its global values + mock returns. These are non-deterministic conditions
([SWE4_SPEC REQ-TC-05](spec/SWE4_SPEC.md)) → set the state in the Precondition (and/or an LLM-proposed
value) and **mark the case draft/review**. A branch gated on something nothing can set (e.g. a hardware
register) is **uncoverable by construction** → flag it, never fake a value.

---

## 7. The three generation methods

Complementary strategies for *where cases come from*, recorded in Table B
([SWE4_SPEC REQ-TC-08](spec/SWE4_SPEC.md)):

- **Analysis of Requirements** — cases from the specified behaviour (signature + SWE.3 design +
  return/OUT). Requirement-complete, but not branch-systematic. **This is the only method implemented today.**
- **Equivalence Class Analysis** *(deferred)* — partition the input/output domain into classes, one
  representative per class; collapses an infinite domain to a finite covering set.
- **Boundary Value Analysis** *(deferred)* — test the values right at/adjacent to each class edge; this is
  what forces both legs of every comparison → the engine of branch coverage.

AoR = "does it meet the spec?"; Equivalence = "minimum distinct cases"; Boundary = "exact edge values that
trip each branch". Equivalence + Boundary together drive branch coverage toward 100%. Ship AoR first
(correct, reviewable), defer Equivalence + Boundary.

---

## 8. Worked examples — Table A only

Shown in the real Table A layout — one header row + one data row (wide; scroll horizontally). Environment
fields are user-supplied (default **Emulator**); the examples show `Eval. Equipment Name = Emulator` with
`Test Platform = Target Board` to make clear the two are independent. Empty precondition parts (no mocks /
no globals) are simply omitted. Multiple input sets are stacked within the single Input/Expected cells,
index-aligned.

**Test Steps are generic** — a **plain-English** numbered transcription of the function's flowchart, written
**once per function** and independent of the input sets. Every step is **imperative** — *issue · check ·
expect · set · return* — never "the function returns …". Steps avoid code syntax: a condition reads *"check
whether `a` is greater than 0"*, not `a > 0`. A mocked callee reads *"expect mock function `loadEntry`"* at
the point the function reaches it. Decisions nest (`2.` → `2.1` **True case** / `2.2` **False case**, deeper for
nested decisions), so the step list reads as the control-flow graph. Steps **end at the function's exit** —
there is no trailing "verify the result" step, because checking the outcome is exactly what the Expected
Results column is for. Which set drives which leg is *not* recorded here either; that is what the
index-aligned Input / Expected Results pair carries.

### 1 — pure parameter, ragged sets

```c
// no callees, no globals
int f(int a, int b) {
    if (a > 0) {
        if (b == 5) {
            return 1;
        }
        return 2;
    }
    return 3;
}
```

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | **Parameters:** `a (int)`, `b (int)` | **Set 1:** `a > 0`, `b = 5`<br>**Set 2:** `a > 0`, `b ≠ 5`<br>**Set 3:** `a ≤ 0` | 1. Issue function `f` with input `a`, `b`.<br>2. Check whether `a` is greater than 0.<br>&nbsp;&nbsp;2.1 True case: check whether `b` is equal to 5.<br>&nbsp;&nbsp;&nbsp;&nbsp;2.1.1 True case: return 1.<br>&nbsp;&nbsp;&nbsp;&nbsp;2.1.2 False case: return 2.<br>&nbsp;&nbsp;2.2 False case: return 3. | **Set 1:** `1`<br>**Set 2:** `2`<br>**Set 3:** `3` | Target Board |

*Set widths 2, 2, 1 — `b` drops out on the `a ≤ 0` path.*

### 2 — parameter + read global (range partitions)

```c
static uint16_t gMaxSpeed = 120;              // read global

bool overLimit(uint16_t speed) {
    return speed > gMaxSpeed;
}
```

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | **Parameters:** `speed (uint16_t)`<br>**Globals:** `gMaxSpeed (read, = 120)` | **Set 1:** `speed ≤ gMaxSpeed`<br>**Set 2:** `speed > gMaxSpeed` | 1. Issue function `overLimit` with input `speed`.<br>2. Check whether `speed` is greater than `gMaxSpeed`.<br>&nbsp;&nbsp;2.1 True case: return true.<br>&nbsp;&nbsp;2.2 False case: return false. | **Set 1:** `false`<br>**Set 2:** `true` | Target Board |

### 3 — VOID function, driven by global + mock return (draft cases)

```c
#define THRESHOLD 50
static Mode    gMode  = INACTIVE;             // read global
static uint8_t gAlarm = 0;                    // written global
int readSensor(void);                         // cross-unit callee (mocked)

void updateAlarm(void) {
    if (gMode == ACTIVE) {
        if (readSensor() > THRESHOLD) {
            gAlarm = 1;
        } else {
            gAlarm = 0;
        }
    }
}
```

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | **Mocks:** `readSensor()`<br>**Parameters:** *VOID*<br>**Globals:** `gMode (read)`, `gAlarm (write, = 0)` | *VOID* on params — sets vary the driving state:<br>**Set 1:** `gMode = ACTIVE`, mock `readSensor` returns `> THRESHOLD`<br>**Set 2:** `gMode = ACTIVE`, mock `readSensor` returns `≤ THRESHOLD`<br>**Set 3:** `gMode ≠ ACTIVE` | 1. Issue function `updateAlarm` with input *VOID*.<br>2. Check whether `gMode` is ACTIVE.<br>&nbsp;&nbsp;2.1 True case: expect mock function `readSensor` and check whether its returned value is greater than THRESHOLD.<br>&nbsp;&nbsp;&nbsp;&nbsp;2.1.1 True case: set `gAlarm` to 1.<br>&nbsp;&nbsp;&nbsp;&nbsp;2.1.2 False case: set `gAlarm` to 0.<br>&nbsp;&nbsp;2.2 False case: leave `gAlarm` unchanged. | **Set 1:** `gAlarm = 1`; mock function `readSensor` called *(draft — review)*<br>**Set 2:** `gAlarm = 0`; mock function `readSensor` called *(draft)*<br>**Set 3:** `gAlarm` unchanged (= 0); mock function `readSensor` not called | Target Board |

*Branches driven entirely from the Precondition; non-deterministic → marked draft.*

### 4 — out-parameter + mock callee + read global

```c
static uint8_t gTableSize = 8;                // read global
Entry loadEntry(uint8_t idx);                 // cross-unit callee (mocked)

int readEntry(uint8_t idx, Entry* out) {
    if (idx < gTableSize) {
        *out = loadEntry(idx);
        return 0;
    }
    return -1;
}
```

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | **Mocks:** `loadEntry()`<br>**Parameters:** `idx (uint8_t)`, `out (Entry*)`<br>**Globals:** `gTableSize (read, = 8)` | **Set 1:** `idx < gTableSize`, mock `loadEntry` returns any valid `Entry`<br>**Set 2:** `idx ≥ gTableSize` *(out of range)*<br>*`out` is written, so it is not an input* | 1. Issue function `readEntry` with input `idx` and output buffer `out`.<br>2. Check whether `idx` is less than `gTableSize`.<br>&nbsp;&nbsp;2.1 True case:<br>&nbsp;&nbsp;&nbsp;&nbsp;2.1.1 Expect mock function `loadEntry` with input `idx`; store its returned value in `out`.<br>&nbsp;&nbsp;&nbsp;&nbsp;2.1.2 Return 0.<br>&nbsp;&nbsp;2.2 False case: return -1. | **Set 1:** returns `0`; `*out` = the `Entry` returned by the mock; mock function `loadEntry` called<br>**Set 2:** returns `-1`; `*out` untouched; mock function `loadEntry` not called | Target Board |

*`out` is a written pointer → appears in Expected Results, never in Input.*

---

Across the four: set counts vary (3 / 2 / 3 / 2), set widths vary, some are param-driven, some
state-driven, and out-params / mock-calls land in Expected — the shapes Table A has to carry.

> **Target, not current output.** The engine does **not** emit this yet: the `testSpecs` view produces flat
> single-level steps and LLM-chosen concrete values. §8 is the agreed shape;
> [SWE4_SPEC.md](spec/SWE4_SPEC.md) and the view still have to be moved to it.
