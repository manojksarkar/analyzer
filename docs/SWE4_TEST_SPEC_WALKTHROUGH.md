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

## 4. Input = the values you vary

One or more **input sets**, each a concrete value or a range, chosen so every branch edge gets ≥1 set
(~O(branches), not O(2^branches)). `VOID` when parameterless. Each set is index-aligned with one Expected
entry. A pointer/ref parameter the function **writes** is an **output** → it belongs in Expected, not Input.

Branch-hitting rules (the deferred Equivalence/Boundary pass):
- comparison vs literal → boundary pair (`p < K` → `K-1` / `K`)
- `switch(param)` → one input per case + a non-matching default
- loop bound → not-taken (`n=0`) and taken (`n≥1`)

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
| Emulator | **Parameters:** `a (int)`, `b (int)` | **Set 1:** `a=1, b=5`<br>**Set 2:** `a=1, b=4`<br>**Set 3:** `a=-1` | 1. Call `f(a, b)` with the input set.<br>2. Branch on `a > 0`; when taken, branch on `b == 5`.<br>3. Verify the return value. | **Set 1:** `1`<br>**Set 2:** `2`<br>**Set 3:** `3` | Target Board |

*Set widths 2, 2, 1 — `b` drops out on the `a<=0` path.*

### 2 — parameter + read global (boundary)

```c
static uint16_t gMaxSpeed = 120;              // read global

bool overLimit(uint16_t speed) {
    return speed > gMaxSpeed;
}
```

| Eval. Equipment Name | Precondition | Input | Test Steps | Expected Results | Test Platform |
|---|---|---|---|---|---|
| Emulator | **Parameters:** `speed (uint16_t)`<br>**Globals:** `gMaxSpeed (read, = 120)` | **Set 1:** `speed = 120`<br>**Set 2:** `speed = 121` | 1. Set `gMaxSpeed = 120`.<br>2. Call `overLimit(speed)`.<br>3. Evaluate `speed > gMaxSpeed`.<br>4. Verify the return value. | **Set 1:** `false`<br>**Set 2:** `true` | Target Board |

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
| Emulator | **Mocks:** `readSensor()`<br>**Parameters:** *VOID*<br>**Globals:** `gMode (read)`, `gAlarm (write, = 0)` | *VOID* on params — sets vary the driving state:<br>**Set 1:** `gMode=ACTIVE`, `readSensor()→90`<br>**Set 2:** `gMode=ACTIVE`, `readSensor()→10`<br>**Set 3:** `gMode=INACTIVE` | 1. Set `gMode` and stub `readSensor()` per the set.<br>2. Call `updateAlarm()`.<br>3. Branch on `gMode == ACTIVE`, then on `readSensor() > THRESHOLD`.<br>4. Verify `gAlarm`. | **Set 1:** `gAlarm = 1`; `readSensor()` called *(draft — review)*<br>**Set 2:** `gAlarm = 0`; `readSensor()` called *(draft)*<br>**Set 3:** `gAlarm` unchanged (= 0); `readSensor()` not called | Target Board |

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
| Emulator | **Mocks:** `loadEntry()`<br>**Parameters:** `idx (uint8_t)`, `out (Entry*)`<br>**Globals:** `gTableSize (read, = 8)` | **Set 1:** `idx = 0`, `loadEntry()→{id:0,val:7}`<br>**Set 2:** `idx = 8` *(boundary = gTableSize, out of range)*<br>*`out` is written, so it is not an input* | 1. Set `gTableSize = 8`, stub `loadEntry()`.<br>2. Call `readEntry(idx, out)`.<br>3. Branch on `idx < gTableSize`; when valid, copy loaded entry into `*out`.<br>4. Verify the return value and `*out`. | **Set 1:** returns `0`; `*out = {id:0,val:7}`; `loadEntry()` called<br>**Set 2:** returns `-1`; `*out` untouched; `loadEntry()` not called | Target Board |

*`out` is a written pointer → appears in Expected Results, never in Input.*

---

Across the four: set counts vary (3 / 2 / 3 / 2), set widths vary, some are param-driven, some
state-driven, and out-params / mock-calls land in Expected — the shapes the SWE.4 engine produces, in the
actual Table A layout.
