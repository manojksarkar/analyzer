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

The Precondition cell lists: **mock functions** — the callees to stub, written as `name()`; **all
parameters**; **all consumed globals** (read or written), with the declared initial value where one exists.
Local variables are not listed.

**Mock scope (coverage rule).** A callee is mocked only when it lies *outside the unit under test* — a
different unit (any visibility), or a same-unit **public/protected** callee (which carries its own spec, so
its branches are covered there). A **same-unit private helper is NOT mocked**: it has no spec of its own, so
it runs inline under the caller's test — otherwise its branches are exercised nowhere and unit coverage can
never reach 100%. External/library callees we cannot name are omitted.

**Verification:** a same-unit private callee is **absent** from the `name()` list; a cross-unit callee is
**present**; parameters and read/written globals appear; a global with a declared initializer shows its
value; locals absent.

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

Each public function has **one** Table B carrying a **single Test Case ID** (deterministic per function),
even when its Table A holds **multiple input sets**. Fields: **Test Case ID**, **Test Case Generation
Method** (the method(s) of REQ-TC-08 that produced the function's cases — **`Analysis of Requirements`** in
the first implementation), **Priority** (config default), and the requirement-linked fields **Alias Test
ID · Risk · Test Method · Test Environment · Linked Work Items**.

**Verification:** One Test Case ID per function; Generation Method names a REQ-TC-08 method (first
implementation: `Analysis of Requirements`). (Requirement-linked fields — see Open items.)

---

### REQ-UT-10 — Environment fields

**Eval. Equipment Name** and **Test Platform** are user-supplied, defaulting to `Emulator`. SWE.3 and SWE.4
consume the **same macros, per layer**.

**Verification:** Both fields default to `Emulator` and are overridable by config/run input.

---

## Test-Case Derivation

**Input consumed:** the re-materialized **CFG** (decision predicates + branch edges), **parameters**
(name/type/range), **globals** read/written, **callees**, and **return expressions/ranges**.

> **Scope of the first implementation:** only the **Analysis of Requirements** method (REQ-TC-08) is
> emitted. The coverage-targeted, input-partitioning rules below (REQ-TC-01…05) belong to the **Equivalence
> Class** and **Boundary Value** methods and are **deferred** — retained here as the agreed target for the
> follow-on pass. REQ-TC-06/07 are method-agnostic and apply now.

---

### REQ-TC-08 — Generation methods

Test cases are produced by one of three client-stated methods, recorded in Table B (REQ-UT-09):

- **Analysis of Requirements** — cases derived from the unit's **specified behaviour**: the function
  signature, the SWE.3 detailed design/description, and return/OUT parameters — functional cases with their
  expected results. **This is the first implementation's sole method.**
- **Equivalence Class Analysis** — cases from partitioning the unit's **inputs and outputs** into
  equivalence classes, one representative per class (the partition/switch/default rules of REQ-TC-02).
  **Deferred.**
- **Boundary Value Analysis** — cases from the **boundary values** of the inputs (the boundary-pair rules
  of REQ-TC-02, `get_range`/`get_range_for_type`). **Deferred.**

Every input set is attributed to ≥1 method; Table B lists the distinct set applied to the function.

**Verification:** Each input set carries a method attribution; Table B's Generation Method is that distinct
set. In the first implementation every case is `Analysis of Requirements` and no partition/boundary-only
cases are emitted.

---

### REQ-TC-01 — Coverage target

Input sets are **branch-targeted**: they aim to exercise **every branch edge at least once** (branch
coverage) — **not** every path (path coverage explodes combinatorially). Cross-unit and same-unit public
callees are mocked (a public callee's own branches are covered by its own spec); a same-unit private helper
is inlined, so its branches are covered here (REQ-UT-05). Coverage is *targeted*, **not verified** (see
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

- **First implementation = Analysis of Requirements only.** Equivalence Class and Boundary Value analysis
  (REQ-TC-01…05) are deferred to a follow-on pass; until then coverage is requirement-driven, not
  branch-systematic.
- **No execution** → 100% coverage cannot be *verified* or *guaranteed* (coverage tooling is parked, §3).
  The tool produces coverage-*targeted* inputs; proving coverage needs a run.
- Conditions on **globals / struct fields / mocked-callee returns / compound predicates** are not
  deterministically solvable — they need Precondition state setup or LLM, and cannot be guaranteed.
- **Many independent parameters** → combinatorial path blow-up; capped by policy.
- **Expected for computed outputs** is left as a relation/placeholder for the tester (never a fabricated
  value) — the tool does not execute code.
- The AST-derived CFG may **differ** from the (possibly LLM-rendered) SWE.3 flowchart.

---

## Open items (client / meeting)

Mock scope is **partially decided in code** — same-unit private helpers are inlined, not mocked (REQ-UT-05),
which is what lets their branches reach coverage. The rest are pending a review meeting; all bear on 100%.

- **Mock boundary** — confirm *same-unit + private* (current) vs *any same-unit* callee left un-mocked.
- **Protected functions** — the view specs protected today (only `private` is excluded from scope); if
  protected keep their own spec they stay mocked, otherwise they inline. Settle protected's scope.
- **Unreachable private helpers** — a private not called by any public function is neither specced nor
  inlined ⇒ uncoverable. Emit a direct spec for it, accept <100% with a flag, or other?
- **Transitive mocks** — an inlined same-unit private helper's *own* cross-unit callees are not hoisted into
  the caller's Precondition (mocks are direct-callee only). Walk transitively?
- **Mock-return convention** — to drive a branch gated on a mocked callee's return, the mock must return a
  chosen value (also drives Expected).
- **Non-drivable conditions** — branches gated on globals / struct fields / compound `&&`/`||` predicates
  carry draft/review markers; accept manual review, or extend the derivation?
- **Demonstrating 100%** — no coverage tool / no execution (§3 parked): coverage is *targeted*, not
  *verified*. Stand up a coverage/execution step, or accept targeted for the deliverable?
- **Table B** requirement-linked fields — Alias Test ID · Risk · Test Method · Test Environment · Linked
  Work Items (blocked on a requirements source: Polarion / SWE.1).

---

## Evidence

The boundary/equivalence derivation logic — i.e. the **deferred** Equivalence/Boundary pass, not the first
implementation — was validated by a spike over **24 sample functions** (0 `UNSOLVED`; only loop-counter
parity needed the iteration heuristic). Reference implementation: `tools/swe4-derivation-spike/`.
