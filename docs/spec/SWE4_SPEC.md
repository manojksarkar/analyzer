# SWE.4 Spec — Unit Test Specification

Update this document first when changing any SWE.4 logic, then update the code and tests to match.

Rules describe **what** must appear in the final output (DOCX + intermediate `test_specs.json`), not **how**.
The derivation rules (REQ-TC) say what the generated test cases must satisfy. Companion to the SWE.3
[Design Spec](SWE3_SPEC.md). Leadership summary: [docs/planning/SWE4_PLAN.md](../planning/SWE4_PLAN.md).

---

## Document Structure

**Output:** `output/software_unit_test_specification_<group>.docx`

---

### REQ-UT-01 — Document sections

The document contains, in order:
- Introduction (Purpose, Scope, Terms)
- Software Unit Test Specification — one section per component; within it, per unit, a test spec per
  function; a Dynamic Behaviour sub-section when the component has dynamic behaviour
- Code Metric, Coding Rule, Test Coverage
- Appendix (Reference)

**Verification:** Each section heading present, in order.

---

### REQ-UT-02 — Scope

A test spec is produced for **every public function** of each source-backed unit. Private items produce no
spec. (Mirrors SWE.3 unit scope; header-only units produce no section.)

**Verification:** Known public functions have a spec; known private functions do not.

---

### REQ-UT-03 — Two tables per function

Each function's spec has exactly **two tables**: **Table A** (horizontal — one header row + one data row)
carries the test **content**; **Table B** (vertical form) carries the **metadata**.

**Verification:** Each function spec has one horizontal Table A (1 data row) and one vertical Table B.

---

### REQ-UT-04 — Table A content

Table A columns: **Eval. Equipment Name · Precondition · Input · Test Steps · Expected Results · Test
Platform**.

**Verification:** All six columns present; one data row per function.

---

### REQ-UT-05 — Precondition

The Precondition cell lists: **mock functions** — the unit's callees, written as `name()`; **all
parameters**; **all consumed globals** (read or written), with the declared initial value where one exists.
Local variables are not listed.

**Verification:** Callees appear as `name()`; parameters and read/written globals appear; a global with a
declared initializer shows its value; locals absent.

---

### REQ-UT-06 — Input

The Input cell lists **one or more input sets**, each a concrete value or a range, chosen to cover the
function's branches (REQ-TC). A function with no parameters shows `VOID`. Each set aligns by index with an
entry in Expected Results. A **pointer/reference parameter that the function writes** is an **output** — it
belongs in Expected Results, not Input.

**Verification:** Input sets present and index-aligned with Expected; void functions show `VOID`;
written-through pointer/reference params do not appear as inputs.

---

### REQ-UT-07 — Test Steps

Test Steps are **descriptive and single-level**, following the function's control flow (flowchart), and
**name the variables** involved. They cover the code exercised by the input sets.

**Verification:** Steps reference the function's variables and follow its control flow; no nested levels.

---

### REQ-UT-08 — Expected Results

Expected Results gives, per input set, the **corresponding output**: the return value, **written
out-parameters** (pointer/reference), any updated globals (the function's written globals), and mock-call
expectations.

**Verification:** One expected output per input set; written globals and out-parameters asserted where the
function writes them.

---

### REQ-UT-09 — Table B metadata

Table B fields: **Test Case ID** (deterministic per function), **Test Case Generation Method**
(`function + branch coverage`), **Priority** (config default), and the requirement-linked fields
**Alias Test ID · Risk · Test Method · Test Environment · Linked Work Items**.

**Verification:** Test Case ID and Generation Method present. (Requirement-linked fields — see Open items.)

---

### REQ-UT-10 — Environment fields

**Eval. Equipment Name** and **Test Platform** are user-supplied, defaulting to `Emulator`. SWE.3 and SWE.4
consume the **same macros, per layer**.

**Verification:** Both fields default to `Emulator` and are overridable by config/run input.

---

## Test-Case Derivation

**Input consumed:** the re-materialized **CFG** (decision predicates + branch edges), **parameters**
(name/type/range), **globals** read/written, **callees**, and **return expressions/ranges**.

---

### REQ-TC-01 — Coverage target

Input sets are **branch-targeted**: they aim to exercise **every branch edge at least once** (branch
coverage) — **not** every path (path coverage explodes combinatorially). Callees are mocked; a public
callee's own branches are covered by its own spec. Coverage is *targeted*, **not verified** (see
Limitations).

**Verification:** Every branch edge has ≥1 input set intended to exercise it; case count is ~O(branches).

---

### REQ-TC-02 — Per-condition covering values (parameter-driven)

For a decision that depends on a parameter:
- comparison vs. a literal → the **boundary pair** (e.g. `p < K` → true=`K-1`, false=`K`; `p == K` →
  `K` / `K+1`)
- `switch(param)` → one input per `case` label plus a non-matching `default` value
- loop bound (counter vs. parameter, e.g. `i < n`) → **not-taken** (`n=0`) and **taken** (`n≥1`)
- parameter-vs-parameter or parameter-derived (e.g. `x == y`, `i < n/3`) → consistent values that hit and
  miss the branch

**Verification:** Generated inputs for these forms match the boundary/partition rules above.

---

### REQ-TC-03 — Branch selection

For each target branch edge, the conditions along a path reaching it are **conjoined** into one input set;
a **minimal** set of inputs covering all branch edges is chosen (paths are **not** all enumerated);
**infeasible** (contradictory) constraints are dropped; boundary values are preferred.

**Verification:** Every branch edge is covered by some input set; no infeasible path emits a set; the input
count is ~O(branches), not O(2^branches).

---

### REQ-TC-04 — Loop-internal conditions

A condition on a **loop counter** (a local, not a parameter — e.g. `i % 2 == 0`) is covered by choosing an
**iteration count** that exercises both outcomes, not by a distinct input set.

**Verification:** Loop-internal conditions do not spawn separate top-level input sets; the chosen bound
drives enough iterations.

---

### REQ-TC-05 — Non-deterministic conditions

A condition on a **global, struct field, mocked-callee return, or a compound `&&`/`||`** predicate is
covered by setting the required state in the **Precondition** and/or an **LLM-proposed** input, and the case
is **marked draft** (review needed).

**Verification:** Such cases carry a draft/review marker and a Precondition state (or mock return) that
justifies the branch.

---

### REQ-TC-06 — Expected derivation

For a branch returning a **literal or a parameter / mock-return expression**, Expected is **exact**
(derived symbolically). For a **computed / logic-dependent** output the tool does **not fabricate a
value** — it emits the expected **relation / description** or a **tester-fill placeholder**, marked
*review*. It never guesses a concrete number.

**Verification:** Literal/expression returns are exact; computed outputs carry a relation or placeholder +
review marker — never an invented value.

---

### REQ-TC-07 — Determinism

Re-running generation on **unchanged input** yields **identical** test cases (IDs, input sets, expected).

**Verification:** Two runs over the same model produce byte-identical `test_specs.json`.

---

## Limitations

- **No execution** → 100% coverage cannot be *verified* or *guaranteed* (coverage tooling is parked, §3).
  The tool produces coverage-*targeted* inputs; proving coverage needs a run.
- Conditions on **globals / struct fields / mocked-callee returns / compound predicates** are not
  deterministically solvable — they need Precondition state setup or LLM, and cannot be guaranteed.
- **Many independent parameters** → combinatorial path blow-up; capped by policy.
- **Expected for computed outputs** is left as a relation/placeholder for the tester (never a fabricated
  value) — the tool does not execute code.
- The AST-derived CFG may **differ** from the (possibly LLM-rendered) SWE.3 flowchart.

---

## Open items (client)

- How **100% coverage** is demonstrated given no coverage tool.
- The **mock-return value** convention (drives both branch-taking and Expected).
- **Table B** requirement-linked fields — Alias Test ID · Risk · Test Method · Test Environment · Linked
  Work Items (blocked on a requirements source: Polarion / SWE.1).
- **Scope** — only **public** functions, or **also private** helpers? Where branching logic lives in
  private functions, public-only + mocking covers little of the actual code.

---

## Evidence

Derivation logic validated by a spike over **24 sample functions** (0 `UNSOLVED`; only loop-counter parity
needed the iteration heuristic). Reference implementation: `tools/swe4-derivation-spike/`.
