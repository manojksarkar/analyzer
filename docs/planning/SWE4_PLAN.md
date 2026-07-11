# SWE.4 Plan — Software Unit Verification (Unit Test Specification)

> **SWE.4 = unit test *specifications*** (derived content — no execution, no runnable test code, no ingesting
> external results). No client template — structure was captured verbally (started 2026-07-06). Reuse is
> **assessed against main's SWE.3 machinery** (the 2026-07-08 audit inventory); refer to the section table when building.

## What it is
- **Unit test *specifications*, several documents** (one per **GROUP**, mirroring the SWE.3 detailed-design DOCX).
  Per-component/unit granularity is **deferred** — revisit later; model on the SWE.3 shape for now.
- **Starting point: bare C++ + our SWE.3 detailed design.** The client has no existing unit tests/framework to
  build on, so everything derives from parsed code + SWE.3 outputs.
- **Out of the spec body:** Test Plan Review, Spec Review, Test Report + Summary (separate work products / review
  gates), and Traceability (separate, mirrors the SWE.2 decision).
- **Parked:** coverage tooling (gcov etc.) and code metrics — clear the document first.
- **Priority convention** (same as SWE.2, one twist): **P0 = manual** (or Polarion) — for SWE.4 P0 does **not**
  mean highest priority, only "manual, may or may not automate — unknown". **P1 = core content to automate first.** P2 = later.

## How we build it
- **V-model position.** SWE.4 is the **right-leg partner of SWE.3** (unit level): SWE.3 ↔ SWE.4 (unit),
  SWE.2 ↔ SWE.5 (integration). SWE.4 verifies exactly what SWE.3 designed, so it consumes SWE.3's outputs
  directly. We have **SWE.3 today** — the input side is already built.
- **Transform, don't roll up.** Unlike SWE.2 (which aggregates component detail *up* to layer/software), SWE.4
  stays at **the same unit scope as SWE.3** and *transforms* design content → test-spec content. That makes SWE.4
  the **higher-reuse, lower-risk** doc: no aggregation layer to invent. The real work is the **design→test-case
  transform** (the two-table spec + case enumeration — the critical path below), not view revival.
- **One model, one bar: logical correctness.** All docs come from one shared model, so they're consistent by
  construction. A coherent, traceable draft is acceptable even if wording deviates from the client's — which makes
  the **code-derived floor a shippable first draft**.

**Floor (build now, no external input):** per-function Table A (Input from interface IN types/ranges, Expected
Results from OUT/return ranges, Test Steps from the flowchart) + Table B (Test Case ID + Generation Method); the
Dynamic-Behaviour specs (Views 3–4); the per-component/unit scaffolding (§2, §2.N, §2.N.X); Terms (§1.3) from the
data dictionary; boilerplate §1.1, §1.2, App A, Reference.

**Gaps (need input — stub or omit for now):** requirement-linked fields — Alias Test ID, Linked Work Items
(SWE.1 not built → Polarion); §3 Code Metric / Coding Rule / Test Coverage (not extracted; coverage parked);
environment fields — Eval. Equipment Name, Test Platform, Test Environment.

**Optional inputs sharpen but never block:** a metrics/coverage export fills §3; a Polarion feed fills Linked Work
Items + traceability; an environment/config seed fills the equipment/platform fields; a **test-case policy**
(target count per function, boundary conventions) sharpens the case enumeration; a few client sample specs raise confidence.

## SWE.4 process steps (from team, with automation-priority tags)

| # | Step | Pri | Derivability (initial read — TBD, confirm in walkthrough) |
|---|---|---|---|
| 1 | UT Test Plan (including Static) | P0 (manual) | manual for now → feeds §3 metrics/coverage |
| 2 | Test Plan Review | P0 (manual) | review gate — not a heading in the spec doc |
| 3 | Generate Spec based on detailed-design interfaces + requirements | **P1** | interfaces EXIST (SWE.3 interface tables, View 1); **requirements source unknown** (SWE.1 not built) |
| 4 | Generate Spec based on Dynamic Behaviour | **P1** | behaviour diagram + flowcharts EXIST (Views 3–4) |
| 5 | Spec Review | P0 (manual) | review gate — not a heading |
| 6 | Traceability | P0 (manual) | manual / separate for now (mirrors SWE.2) |
| 7 | Generate Input/Output files | P0 (manual) | NEW — what artifact? (test data / vectors?) TBD |
| 8 | Test report generation + test summary | P0 (manual) | review gate — not a heading |

**The tool's core SWE.4 contribution (P1) = steps 3 + 4:** generate the unit test spec from detailed-design
interfaces (+ requirements) and from dynamic behaviour. Everything else is manual/fixed for now (may automate later).

## Target structure (TOC, per-group document)

```
1  Introduction
   1.1 Purpose
   1.2 Scope
   1.3 Terms, Abbreviations & Definitions
2  Software Unit Test Specification
   2.N  <Component N>
        2.N.X  <Unit X>                         (unit vs function granularity — TBD)
               2.N.X.Y  <test spec Y>            (heading = function name — confirm)
                        Table A (form/vertical): Eval. Equipment Name | Precondition | Input |
                                                 Test Steps | Expected Results | Test Platform
                        Table B (horizontal):    Test Case ID | Alias Test ID | Priority | Risk |
                                                 Test Method | Test Environment |
                                                 Test Case Generation Method | Linked Work Items
        2.N.<Last>  Dynamic Behaviour            (ONLY if the component has dynamic behaviours)
                    2.N.<Last>.Z  <test spec>    (same two-table format as above)
3  Code Metric, Coding Rule, Test Coverage
Appendix A  Reference
```

**Mapping to the two P1 generation sources:** step 3 (interfaces + requirements) → the per-unit specs `2.N.X.Y`;
step 4 (dynamic behaviour) → the per-component `Dynamic Behaviour` subsection (conditional).

## Section status (vs main's SWE.3 machinery)

**Status:** `reuse` = main's SWE.3 renderer already emits this at unit scope, consume ~as-is · `transform` = data
exists in the SWE.3 model but design→test-spec needs a **new renderer** (the two-table spec + case enumeration —
the critical path) · `input` = external input / not extracted today · `fixed` = boilerplate or manual constant.

| Heading No. | Heading | Step | Pri | Status | Depends on | How we build it |
|---|---|---|---|---|---|---|
| 1.1 | Purpose | — | — | fixed | — | boilerplate |
| 1.2 | Scope | — | — | fixed | — | boilerplate |
| 1.3 | Terms, Abbreviations & Definitions | — | — | reuse | data dictionary | reuse the SWE.3 terms table |
| **2** | **Software Unit Test Specification** | 3 + 4 | — | — | — | container — core of the document |
| 2.N | \<Component N\> | 3 + 4 | — | reuse | component model (SWE.3) | per-component grouping, straight from the model |
| 2.N.X | \<Unit X\> | 3 | — | reuse | unit model (SWE.3) | per-unit grouping; **Unit-vs-function granularity TBD** |
| 2.N.X.Y | Table A — Precondition · Input · Test Steps · Expected Results | 3 | **P1** | transform | interface tables (View 1) + flowchart | Input←interface IN type/range · Expected←OUT/return range · Test Steps←flowchart · Precondition←LLM + global access; **enumerate cases → see crux** |
| 2.N.X.Y | Table A — Eval. Equipment Name · Test Platform | 3 | P0 | input | env config | fixed per-project constant or per-run config — TBD |
| 2.N.X.Y | Table B — Test Case ID · Test Case Generation Method | 3 | **P1** | transform | ID scheme | ID generated from unit + case index; Generation Method = fixed label (values TBD) |
| 2.N.X.Y | Table B — Alias Test ID · Priority · Risk · Test Method · Test Environment · Linked Work Items | 6 | P0 | input | Polarion / manual | Linked Work Items←traceability/Polarion; others manual/default — **per-field decision (Q3)**; "Alias Test ID" meaning TBD |
| 2.N.\<Last\> | Dynamic Behaviour test specs (only if component has dynamic behaviour) | 4 | **P1** | transform | behaviour diagram + flowcharts (Views 3–4) | same two-table format, sourced from behaviour/flowchart; conditional |
| 3 | Code Metric, Coding Rule, Test Coverage | 1 | P0 | input | metrics / coverage tool | not extracted today; coverage parked — manual/import for now |
| A | Appendix A | — | P0 | fixed | — | manual; content TBD |
| — | Reference | — | P0 | fixed | — | manual list |

**Automation footprint:** only the **P1** rows are the tool's job — the per-unit Table A content + Test Case
ID/Generation Method, and the Dynamic-Behaviour specs. Everything else is manual/fixed/input for now.

## Reuse reality

SWE.4's reuse story is **more favourable than SWE.2's**: it stays at unit scope, so there is **no aggregation
layer to build** — the SWE.3 renderers that main already ships (per-unit interface tables `views/interface_tables.py`,
flowcharts, behaviour diagram, terms table) feed SWE.4 almost directly. The genuinely new engineering is the
**design→test-case transform**: a renderer that emits the **two-table spec format** and, inside Table A,
**enumerates and populates test cases** (Input / Expected / Test Steps) from interface ranges + the flowchart —
**this is the critical path**, not view revival.

Two gaps are real and one is **shared with SWE.2**: (1) the **requirements linkage** — Alias Test ID and Linked
Work Items have no source until SWE.1/Polarion exists (same blocker SWE.2 hits on its requirements table and
traceability); (2) **§3 metrics/coverage**, not extracted today and parked. Environment fields (Equipment /
Platform / Test Environment) are minor — fixed constants or a small config.

## The test-case derivation problem — the crux

The crux mirrors SWE.2's §2.2.1: an open-ended derivation, not a deterministic lookup. From a unit's **interface**
(data types + ranges) and its **flowchart/behaviour**, produce a *right-sized* set of test cases — nominal /
boundary / error — each with concrete-enough **Input** and **Expected Results**. It has a granularity knob (how
many cases per function) exactly like §2.2.1's feature-vs-sub-feature knob → **draft-then-confirm**. Approaches,
meant to be combined:

| # | Approach | Input | How | Trade-off |
|---|---|---|---|---|
| A | Boundary-value / equivalence partitioning | interface Data Type + Range ✓ | per IN param, generate nominal + min/max/just-outside + invalid partitions | deterministic + traceable, but ranges are often missing/loose; no coupling between params; combinatorial blow-up on multi-param |
| B | Flowchart path coverage | CFG flowchart ✓ | one case per independent path / branch / decision in the CFG (branch/path coverage) | ties cases to real control flow (a genuine coverage story), but input conditions per path must be solved; loops / complex predicates are hard |
| C | LLM from behaviour + interface | KB summaries + behaviour ✓ | LLM reads the unit summary/behaviour + interface, proposes nominal/boundary/error cases with values + expected | strong semantic cases (error/precondition-aware), but non-deterministic + can invent ranges; needs review |
| D | Expected-result derivation | interface OUT/return ✓ | derive each case's Expected from OUT/return type+range (+ LLM for behaviour-dependent outputs) | closes Table A's Expected column, but logic-dependent outputs stay LLM-guess unless behaviour is explicit |
| E | Seed-and-populate (policy) | client test-case policy ✗ | given a policy (e.g. "1 nominal + 2 boundary + 1 error per function") + naming, only fill values | matches client convention + bounds the count, but needs a seed policy |

**Default plan:** A + B for the case skeleton, C to label/enrich and add error cases, D for Expected; then
human-confirm on a sample and check coverage. Switch to **E**'s bounded count the moment a client policy/target
appears. Judge a draft by coverage (branches/params exercised), right-sizing (cases per function within target),
stability (re-runs agree), and client acceptance on a sample.

**Open questions for the team:** target granularity (cases per function — need a number + client examples) ·
concrete vs abstract input values (real values or symbolic partitions?) · how is "Expected Results" validated for
logic-dependent outputs? · must test cases trace to requirements (Table B Linked Work Items)? — the **shared
blocker with SWE.2**.

## Q&A log (discovery — resolved decisions)

- **Q1 — One document or several? → several.** Granularity (per component / per unit) **deferred**; for now model
  on the **SWE.3 detailed-design DOCX** shape (same per-group machinery) because it makes development easy.
- **Q2 — Document structure & spec entry? → resolved.** One document per **GROUP**; full TOC + the two per-spec
  tables captured under "Target structure" above.
- **Q3 — pending:** field-level derivability of Table A / Table B (auto vs manual vs fixed default) — see Open items.

## Open items
- [ ] Q3 — field-level derivability of Table A / Table B (auto vs manual vs fixed default), per field.
- [ ] Granularity — what is a "Unit" (2.N.X) vs the function-named test spec (2.N.X.Y)?
- [ ] Test-case count per function (nominal / boundary / error) + concrete vs abstract input values (crux).
- [ ] "Alias Test ID" — meaning + source; "Test Case Generation Method" — what values it takes.
- [ ] §3 Code Metric / Coding Rule / Test Coverage — source (coverage parked → likely manual now).
- [ ] Requirements in step 3 / Table B Linked Work Items — source, given SWE.1 isn't built (**shared with SWE.2**).
- [ ] Eval. Equipment Name / Test Platform / Test Environment — fixed constant vs per-run config.
- [ ] Step 7 "Generate Input/Output files" — what artifact (test data / vectors)?
- [ ] Prior work — none known (SWE.4 was previously out of ROADMAP scope); verify no dropped branch exists.
- [ ] Then settle the build approach: reuse SWE.3 interface/behaviour renderers vs a new generator.
