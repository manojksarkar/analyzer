# SWE.4 Planning — Working Notes

> Started 2026-07-06 from team discussion. WORKING DRAFT — filled by verbal discovery, one question
> at a time (same method as `SWE2_PLAN.md`). SWE.4 = **Software Unit Verification**.
> No client template file available; captured verbally.

## Locked so far (from team)
- **Deliverable class:** generate unit **test SPECIFICATIONS** — derived content, no execution, no runnable
  test code, no ingesting external test results.
- **Starting point:** **bare C++** — derive everything from parsed code + our existing SWE.3 detailed design.
  Client has no existing unit tests/framework we build on.
- **Coverage/tooling (gcov etc.):** parked — not now. Clear the document first.

## SWE.4 step list (from team, with automation-priority tags)

Priority convention (same as SWE.2): **P0 = manual** (or Polarion) — note: for SWE.4 P0 does **not**
necessarily mean highest priority, just "manual, may or may not automate — unknown". **P1 = core content
to automate first.** P2 = later.

| # | Step | Pri | Derivability (initial read — TBD, confirm in walkthrough) |
|---|---|---|---|
| 1 | UT Test Plan (including Static) | P0 (manual) | manual for now |
| 2 | Test Plan Review | P0 (manual) | manual review step |
| 3 | Generate Spec based on detailed design interfaces + requirements | **P1** | interfaces EXIST (SWE.3 interface tables, View 1); **requirements source unknown** (SWE.1 not built) |
| 4 | Generate Spec based on Dynamic Behaviour | **P1** | behaviour diagram + flowcharts EXIST (Views 3–4) |
| 5 | Spec Review | P0 (manual) | manual review step |
| 6 | Traceability | P0 (manual) | manual / separate for now (mirrors SWE.2 decision) |
| 7 | Generate Input/Output files | P0 (manual) | NEW — what artifact? (test data / vectors?) TBD |
| 8 | Test report generation + test summary preparation | P0 (manual) | manual for now |

**Tool's core SWE.4 contribution (P1) = generate the unit test spec from (3) detailed-design interfaces
+ requirements and (4) dynamic behaviour.** Everything else is manual for now (may automate later, unknown).

## SWE.4 document section master table (per-group document)

Section list of the actual document (mirrors SWE.2's master table). Columns: **Heading No.** = numbering
as it appears in the doc; **Heading** = its title; **Section (step)** = the matching step from the 8-step
step list above (cross-ref); **Pri** — **P0 = manual** (or fixed/Polarion), **P1 = automate first**, P2 = later;
**Source** = derivability class, one of **Existing** (derive from existing metadata/model) · **Partial**
(some inputs exist, some missing) · **New** (not in metadata today — new extraction or manual authoring);
**Understanding / Doubts** = initial read + open questions.

Note: step-list items **2 Test Plan Review, 5 Spec Review, 8 Test Report+Summary** are separate
work products / review gates, not headings inside this spec document — so they don't appear as rows below.

| Heading No. | Heading | Section (step) | Pri | Source | Understanding / Doubts |
|---|---|---|---|---|---|
| 1 | Introduction — Purpose / Scope / Terms, Abbreviations & Definitions | — (doc boilerplate) | P0 | New (manual boilerplate) | Doubt: any fixed house-standard wording to reuse? |
| 2 | **Software Unit Test Specification** | 3 + 4 Generate Spec | — | Existing (component/unit model) | Container — core of the document. |
| 2.N | \<Component N\> | 3 + 4 Generate Spec | — | Existing (component model, SWE.3) | Reused from SWE.3. |
| 2.N.X | \<Unit X\> | 3 Generate Spec (design interfaces + reqs) | — | Existing (unit model, SWE.3) | **Doubt: what is a "Unit" vs the function-named test spec (2.N.X.Y)?** |
| 2.N.X.Y | \<test spec\> — Table A: Precondition · Input · Test Steps · Expected Results | 3 Generate Spec (design interfaces + reqs) | **P1** | Partial (interface tables + flowchart exist; **requirements input missing — SWE.1 not built**) | Doubt: #cases per function (nominal/boundary/error); concrete vs abstract input values. |
| 2.N.X.Y | \<test spec\> — Table A: Eval. Equipment Name · Test Platform | 3 Generate Spec (env fields) | P0 | New (fixed constant / config) | Doubt: fixed per project, or per-run config? |
| 2.N.X.Y | \<test spec\> — Table B: Test Case ID · Test Case Generation Method | 3 Generate Spec | **P1** | Partial (ID generated; method = fixed label) | Doubt: what values does "Generation Method" take? |
| 2.N.X.Y | \<test spec\> — Table B: Alias Test ID · Priority · Risk · Test Method · Test Environment · Linked Work Items | 6 Traceability (Linked Work Items) + manual | P0 | New (manual / default / Polarion) | **Doubt (Q3): blank vs fixed default vs LLM-guess, per field? What is "Alias Test ID"?** |
| 2.N.\<Last\> | Dynamic Behaviour test specs (**only if component has dynamic behaviour**) | 4 Generate Spec (Dynamic Behaviour) | **P1** | Existing (behaviour diagram + flowcharts, Views 3–4) | Same two-table format as above. |
| 3 | Code Metric, Coding Rule, Test Coverage | 1 UT Test Plan (incl. Static) | P0 | New (not extracted today) | Coverage parked. Doubt: source of metrics / coding-rule / coverage; manual now? |
| A | Appendix A | — | P0 | New (manual) | Doubt: what content goes here? |
| — | Reference | — | P0 | New (manual) | Manual list of references. |

**Automation footprint:** only the **P1** rows are the tool's job — the per-unit test-spec content (Table A
content fields + Test Case ID/Generation Method) and the Dynamic-Behaviour specs. Everything else is
manual/fixed for now.

## Decisions so far
- **Template:** no client file; capture verbally (same as SWE.2).
- **Mirror SWE.2 method:** one document-discovery question at a time; this file is the running log.
- **Build approach:** deferred — understand the document fully first.

## Prior work reference
- None known yet (SWE.4 was previously out of scope in ROADMAP.md). To verify no dropped branch exists.

## Q&A log (discovery — one question at a time)

**Q1 — One document or several? → RESOLVED: several.**
- SWE.4 is **several documents**, not one combined artifact.
- **Granularity (per component / per unit / other) is DEFERRED** — revisit later.
- **Working approach for now:** model it like the **SWE.3 detailed-design DOCX** (same per-component/group
  structure and machinery) because that makes development easy. Granularity to be revisited.

**Q2 — Document structure & spec entry? → RESOLVED (structure captured below).**
- **One document per GROUP** (mirrors SWE.3).
- Full target TOC and the two per-test-spec tables captured in "Target document structure" below.

**Q3 — pending:** Field-level derivability of the two spec tables (auto vs manual). (see Next steps)

## Target document structure (per-group document)

```
1  Introduction
   1.1 Purpose
   1.2 Scope
   1.3 Terms, Abbreviations & Definitions
2  Software Unit Test Specification
   2.N  <Component N>
        2.N.X  <Unit X>                         (unit vs function granularity — TBD, Q?)
               2.N.X.Y  <test spec Y>            (heading appears to be the function name — confirm)
                        Table A (form/vertical): Eval. Equipment Name | Precondition | Input |
                                                 Test Steps | Expected Results | Test Platform
                        Table B (horizontal):    Test Case ID | Alias Test ID | Priority | Risk |
                                                 Test Method | Test Environment |
                                                 Test Case Generation Method | Linked Work Items
        2.N.<Last>  Dynamic Behaviour            (ONLY if the component has dynamic behaviours)
                    2.N.<Last>.Z  <test spec>    (same two-table format as above)
3  Code Metric, Coding Rule, Test Coverage
Appendix A
Reference
```

**Mapping to the two P1 generation sources:**
- Step 3 (spec from detailed-design interfaces + requirements) → the per-unit test specs `2.N.X.Y`.
- Step 4 (spec from dynamic behaviour) → the per-component `Dynamic Behaviour` subsection (conditional).

**Initial derivability read of the two tables (to confirm in Q3):**
- Table A — Precondition (LLM + global-access), Input (interface Data Type/Range, IN), Test Steps
  (LLM from flowchart/behaviour), Expected Results (interface Data Range, OUT/return); Eval. Equipment
  Name + Test Platform look like **environment/manual** fields.
- Table B — Test Case ID (generated); Test Case Generation Method (auto/manual tag); Linked Work Items
  (traceability / Polarion); Alias Test ID, Priority, Risk, Test Method, Test Environment — **unclear /
  likely manual or fixed defaults** — confirm each.

## Next steps
- [x] Q1: one doc vs several → several; granularity deferred; reuse SWE.3 detailed-design DOCX shape for now.
- [x] Q2: document structure → per-group doc; TOC + two-table spec format captured above.
- [ ] Q3: field-level derivability of Table A / Table B (auto vs manual vs fixed default).
- [ ] Q?: what is a "Unit" (2.N.X) vs the function-named test spec (2.N.X.Y)?
- [ ] Q?: how many test cases per function (nominal / boundary / error) + concrete vs abstract input values?
- [ ] Q?: Section 3 (Code Metric, Coding Rule, Test Coverage) — source? (coverage was parked → likely manual now).
- [ ] Q?: where do "requirements" in step 3 come from, given SWE.1 isn't built?
- [ ] Then decide build approach (reuse SWE.3 interface/behaviour views vs. new generator).
