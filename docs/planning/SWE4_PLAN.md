# SWE.4 Plan — Software Unit Verification (Unit Test Specification)

> Unit test **specifications** — derived content only, no test execution or runnable code. Structure was
> captured verbally (no client template yet). For the shared generation approach — how we derive, what's
> buildable now vs. needs input, where human judgement is needed — see
> [DOC_GENERATION_PLAYBOOK.md](DOC_GENERATION_PLAYBOOK.md).

## What it is

- **Unit test specifications**, one document per **group** (mirroring the SWE.3 detailed-design document).
- Built directly from the **parsed code + our SWE.3 detailed design** — the client has no existing tests to
  start from. SWE.4 verifies exactly what SWE.3 designed, so it **transforms** SWE.3 content at the same
  unit scope (no roll-up).
- Out of the document body: test plan/spec reviews, test reports, and Traceability (handled separately).

## Document structure

```
1  Introduction
2  Software Unit Test Specification
   2.N  <Component>
        2.N.X  <Unit>
               <test spec per function>
                 Table A (horizontal, 1 header + 1 row): Precondition · Input · Test Steps · Expected Results · Eval. Equipment Name · Test Platform
                 Table B (vertical form): Test Case ID · Alias Test ID · Priority · Risk · Test Method · Test Environment · Generation Method · Linked Work Items
        Dynamic Behaviour test specs (only when the component has dynamic behaviour)
3  Code Metric, Coding Rule, Test Coverage
Appendix A  Reference
```

## Confirmed with client (2026-07-22)

- **Scope:** a spec for **every public function**.
- **Precondition** = mock callees written as `name()` + all parameters + all consumed globals.
- **Input** = multiple sets (a value or a range) sized for **100% function + branch coverage**; **Expected
  Results** gives the matching output per set.
- **Test Steps** = descriptive, following the flowchart and naming the variables (single level).
- **Eval. Equipment Name / Test Platform** = user input (default **Emulator**); **Generation Method** =
  "function + branch coverage".
- **Macros:** SWE.3 & SWE.4 share the same macros, **per layer**.

**Readiness**

| Group | Status |
|---|---|
| Introduction, Terms, per-component/unit scaffolding | Ready — reuse existing SWE.3 output |
| Table A (Precondition, Input, Expected Results, Test Steps) + Dynamic-Behaviour specs | Derivable — the core new work (coverage-driven cases + descriptive flowchart steps) |
| Table B metadata (Alias Test ID, Risk, Test Method, Test Environment, Linked Work Items) | **Open** — not yet discussed; Alias Test ID / Linked Work Items also **blocked** on a requirements source (Polarion / SWE.1) |
| §3 Code Metric / Coding Rule / Test Coverage | **Needs input** — not extracted today; coverage tooling parked |

## Test-case sizing — resolved by coverage

The client set the target: **enough input sets to reach 100% function + branch coverage** (not a fixed
per-function count). Boundary/equivalence partitioning + flowchart paths produce the input sets, the LLM
adds error/precondition cases, and Expected is the matching output per set. Residual judgement: choosing
concrete input values that hit each branch, and logic-dependent Expected values.

## Open items

- [ ] Table B metadata fields — Alias Test ID · Risk · Test Method · Test Environment · Linked Work Items (only Table A was confirmed).
- [ ] Requirements/Linked Work Items source, given SWE.1 isn't built yet (shared with SWE.2).
- [ ] §3 metrics/coverage source (coverage tooling parked).
