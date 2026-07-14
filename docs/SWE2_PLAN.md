# SWE.2 Planning — Working Notes

> Working doc for **SWE.2 = one document: "Software Architecture Design Specification" (SAD)**.
> Captured verbally (no client template file). Started 2026-07-06.

## What SWE.2 is — decisions
- **One document**, the SAD (SWE.3 was the multiple *detailed design* docs; SWE.2 is architecture).
- **Template:** no client file — structure captured verbally.
- **Traceability:** kept in a **separate doc** for now.
- **Prior work to revive:** `feat/architecture-design` (see Prior work reference below).
- Note: the requirements-style list first mentioned in discussion was actually **SYS.2** (V2 scope) —
  moved to **`docs/SYS2_PLAN.md`**.

## Target document structure (TOC)

```
Software Architecture Design Specification (title)

1  Introduction
   1.1 Purpose
   1.2 Scope
   1.3 Terms, Abbreviations and Definitions

2  Software Architecture Design            ← software-level block
   2.1 Software Static Design
   2.2 Function Allocation
       2.2.1 Function Definition             (assume: provided as input)
       2.2.2 Function Allocation
   2.3 Layer Interface
       2.3.N  <LayerName>                    ← repeats per layer (N = layer index, same var as §3.N)
   2.4 Resource Management
   2.5 Dynamic Behaviour
   2.6 Configuration Data
       2.6.1 Dynamic Configurations
       2.6.2 Static Configurations           ← SFRs for HW elements: initial values + ranges
   2.7 Calibration Data
   2.8 Global Header

3  Layer Design                            ← layer/component detail
   3.N <LayerName>
       3.N.1 Static Design                  (layer diagram + Component Information table)
       3.N.2 Function Allocation            (mirrors §2.2 at layer scope)
       3.N.3 Component Design
             3.N.3.x <ComponentName>              (component static design diagram)
                     3.N.3.x.1 <ComponentName> interface   (interface table)
                     3.N.3.x.y  table: Requirement ID | Requirements | Capacity | Input Name |
                                        Output Name | Linked Work Items          (verify later)
       3.N.4 Resource Management
       3.N.5 Dynamic Behaviour
       3.N.6 Configuration Data
             3.N.6.1 Dynamic Configuration
             3.N.6.2 Static Configuration
       3.N.7 Calibration Data
       3.N.8 Layer Header                   (layer-scope counterpart of §2.8 Global Header)

4  Architecture Design Evaluation
   4.1 Evaluation Criteria
   4.2 Evaluation of Software Architecture

Appendix A
   Reference
```
Hierarchy: **Software (§2) → Layer (§3.N) → Component (§3.N.3.x)**.

**Structural insight:** §2 (software-wide) and §3.N (per-layer) are the SAME 8-part template at two scopes —
2.1↔3.N.1 Static Design, 2.2↔3.N.2 Function Allocation, 2.3↔3.N.3 Interface/Component, 2.4↔3.N.4 Resource Mgmt,
2.5↔3.N.5 Dynamic Behaviour, 2.6↔3.N.6 Configuration Data, 2.7↔3.N.7 Calibration Data, 2.8↔3.N.8 Header
(Global vs Layer). Build implication: one set of section-builders parameterised by scope, not two.

**Out of the SAD body (confirmed):** Traceability (separate doc) and Technical Review – Checklist (Polarion).

**Open placements — ASSUMPTIONS, kept OUT of the body (guess for now; re-check):**
- **Component Dynamic Behaviour** (P1) — no home yet (3.N.3.x.y is the requirements table, not this); confirm.
- **Data Dictionary** (P1) — no home yet (candidates: own top-level section, or an appendix).

## Master table — structure + priority + source

| § | Header or View | Section | Pri | Source | Notes |
|---|---|---|---|---|---|
| 1 | **Introduction** | | — | Manual | |
| 1.1 | Purpose | | — | Manual | |
| 1.2 | Scope | | — | Manual | |
| 1.3 | Terms, Abbreviations & Definitions | | — | ✅ Have it | |
| 2 | **Software Architecture Design** | | — | — | |
| 2.1 | Software Static Design | Software Static Design | P2 | 🟡 Partial | |
| 2.2 | **Function Allocation** | Software function allocation table | — | — | |
| 2.2.1 | Function Definition | | P2 | 🔴 New (ext) | Input |
| 2.2.2 | Function Allocation | | P2 | ✅ Have it | LLM: derive from 2.2.1 input + code base |
| 2.3 | Layer Interface (2.3.N per layer) | Layer Interface | P2 | 🟡 Partial | |
| 2.4 | Resource Management | Resource Management | P2 | 🔴 New (ext) | |
| 2.5 | Dynamic Behaviour | Dynamic Behaviour Level 1 | P1 | 🟡 Partial | needs behaviour list + call entry points |
| 2.6 | **Configuration Data** | Configuration Data — Dynamic/Static | — | — | |
| 2.6.1 | Dynamic Configuration | | P1 | 🔴 New (ext) | macros? |
| 2.6.2 | Static Configuration | | P1 | 🔴 New (ext) | init values + ranges; macros? |
| 2.7 | Calibration Data | | — | 🔴 New (ext) | no calibration data defined (N/A) |
| 2.8 | Global Header | Global Header | P1 | ✅ Have it | |
| 3 | **Layer Design** (3.N per layer) | | — | — | |
| 3.N.1 | Static Design | Layer Design — Static Design | P1 | ✅ Have it | |
| 3.N.2 | Function Allocation | Function Allocation | P1 | ✅ Have it | |
| 3.N.3 | **Component Design** | | — | — | |
| 3.N.3.x | `<ComponentName>` (diagram) | Component Design — Static Diagram | P1 | ✅ Have it | |
| 3.N.3.x.1 | interface | Interface Table | P1 | ✅ Have it | |
| 3.N.3.x.y | requirements table | | — | 🔴 New (ext) | what is y? |
| 3.N.4 | Resource Management | Resource Management | P2 | 🔴 New (ext) | |
| 3.N.5 | Dynamic Behaviour | | P1 | 🟡 Partial | subset of 2.5 (overall dynamic), but with more behaviours |
| 3.N.6 | **Configuration Data** | Configuration Data — Dynamic/Static | — | — | |
| 3.N.6.1 | Dynamic Configuration | | P1 | 🔴 New (ext) | |
| 3.N.6.2 | Static Configuration | | P1 | 🔴 New (ext) | |
| 3.N.7 | Calibration Data | | — | 🔴 New (ext) | no calibration data defined (N/A) |
| 3.N.8 | Layer Header | | P1 | ✅ Have it | |
| 4 | **Architecture Design Evaluation** | | — | 🔴 New | |
| 4.1 | Evaluation Criteria | | — | Manual | |
| 4.2 | Evaluation of Software Architecture | | — | 🔴 New / LLM | |
| App. A | Reference | | — | Manual | |
| — | Data Dictionary | Data Dictionary | P1 | ✅ Have it | placement TBD |
| — | Component Dynamic Behaviour | Component Dynamic Behaviour | P1 | 🟡 Partial | placement TBD |
| *(out)* | Traceability | Traceability | P0 | Separate doc | |
| *(out)* | Technical Review – Checklist | Technical Review — Review Checklist | P0 | Polarion | |

**Legend:** ✅ Have it (reuse existing model/views) · 🟡 Partial (building blocks exist, needs rework/scope) ·
🔴 New (ext) (external input, not from C++ today) · Manual.

## Section list (raw team input, with priority tags)

Priority = automation priority. P0 = highest doc priority but manual/Polarion; P1 = core; P2 = later.

| # | Section (as given) | Pri | Maps to |
|---|---|---|---|
| 1 | Software Static Design | P2 | §2.1 |
| 2 | Software function allocation table | P2 | §2.2 |
| 3 | Layer Interface | P2 | §2.3 |
| 4 | Resource Management | P2 | §2.4 / §3.N.4 |
| 5 | Dynamic Behaviour Level 1 | P1 | §2.5 |
| 6 | Configuration Data — Dynamic/Static | P1 | §2.6 / §3.N.6 |
| 7 | Global Header | P1 | §2.8 |
| 8 | Layer Design — Static Design | P1 | §3.N.1 |
| 9 | Function Allocation | P1 | §3.N.2 |
| 10 | Component Design — Static Diagram | P1 | §3.N.3.x |
| 11 | Interface Table | P1 | §3.N.3.x.1 |
| 12 | Data Dictionary | P1 | unplaced (TBD) |
| 13 | Component Dynamic Behaviour | P1 | unplaced (TBD) |
| 14 | Traceability | P0 | out of body (separate doc) |
| 15 | Technical Review — Review Checklist | P0 | out of body (Polarion) |

## Prior work reference — `feat/architecture-design`
Dropped early-stage attempt ("ADD" = Architecture Design Document). Revival candidate.
- `src/architecture_docx_exporter.py` — `export_architecture_docx()`, DOCX titled "Software Architecture
  Design Specification". Currently emits only 1 Introduction (placeholders) + 3 Layer Design (3.N.1 Static
  Design + Component Information table; 3.N.3 Component Design + interface tables). Section 2 and most of §3 absent.
- `src/sad_views/` — the view generators: `layer_static_diagram.py` (→ §3.N.1), `component_design_diagram.py`
  (→ §3.N.3 + interface table).
- `docs/images/architecture.drawio` / `architecture.png`.
- Data sources: `output/add/layer_static_diagrams/_layer_static_data.json` (+ `_component_design_data.json`).
- Branch note: no `feat/architecture-diagram` branch exists; `feat/component-design` has the same exporter.
  `feat/architecture-design` is the fuller branch.

## FINAL — Approach & Estimate

**Approach: extend the existing engine, don't rebuild.** SWE.2 rides the same pipeline as SWE.3
(parse → derive → views → DOCX).
1. Revive `feat/architecture-design` (`sad_views/` + exporter) as the base.
2. Reuse foundation: ~100% of parse+derive (functions, components, layers, interfaces, call graph, data
   dictionary, headers) + existing views (layer static, component design, interface tables).
3. Build the SWE.2 delta: (a) aggregation to software/layer scope; (b) input adapters for external data
   (Resource Mgmt, Config/SFRs, Calibration, Polarion requirements linkage); (c) Evaluation section.
4. One new doc type; scope-parameterised section-builders (§2 ↔ §3.N mirror = one builder set, two scopes).
5. Parallel **correctness workstream** (the completeness→correctness shift): a prompt evaluator
   (offline golden-set + LLM-judge scorer, built on existing few_shot / self_review / structured_output)
   + feedback loop from reviewer corrections. Cross-cutting — benefits SWE.3 and all future doc types.

**Reuse split:** ~60% of SWE.2 derives from existing building blocks (structure/interfaces/allocation/
diagrams); ~40% is new — and that 40% is mostly *ingesting external inputs*, not new C++ parsing.

**Estimate (person-days):**
- Discovery spike (lock data sources, revive & run branch, one filled example per section) — do first: **2–3**
- SWE.2 build if red-bucket data is **client-provided input**: **20–35**
- SWE.2 build if it must be **extracted from C++** (new parsers): **28–48**
- Correctness workstream (evaluator + feedback), separate/shared: **5–10**

**Swing factor** = the red-bucket data source (Resource/Config/Calibration): ±8–15 days → the spike goes first.
**Calendar** (3 people, after hard V1 on 2026-07-15): SWE.2 ≈ 2–4 weeks; evaluator ≈ 1 week, overlapping.

## Next steps / open items
- [ ] Discovery spike: lock red-bucket data sources (client-provided vs code-extracted); revive & run the branch.
- [ ] Place the two unplaced sections: Data Dictionary, Component Dynamic Behaviour.
- [ ] Verify the `3.N.3.x.y` requirements table columns/meaning with client.
- [ ] Confirm SFR = Special Function Registers; decide §3.N.2 Function Allocation sub-items (mirror §2.2?).
