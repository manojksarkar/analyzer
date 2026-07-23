# SWE.2 Plan — Software Architecture Design (SAD)

> One document: the **Software Architecture Design Specification**. Structure was captured verbally
> (no client template yet). For the shared generation approach — how we derive, what's buildable now
> vs. needs input, where human judgement is needed — see [DOC_GENERATION_PLAYBOOK.md](DOC_GENERATION_PLAYBOOK.md).

## What it is

- **SWE.2 = architecture** (the level above SWE.3 detailed design). It is a **single SAD document**.
- Built **bottom-up from the code + SWE.3**: derive the component/unit sections first, then **roll them up**
  to layer and software level. This roll-up is the main new work.
- Out of the document body: Traceability and the Technical Review checklist (handled separately).

## Document structure

```
1  Introduction
2  Software Architecture Design            (software-level view)
   2.1 Software Static Design
   2.2 Function Allocation                 (2.2.1 Function Definition = the feature list)
   2.3 Layer Interface (per layer)
   2.4 Resource Management
   2.5 Dynamic Behaviour
   2.6 Configuration Data
   2.7 Calibration Data
   2.8 Global Header
3  Layer Design                            (same 8-part template, per layer / component)
4  Architecture Design Evaluation
Appendix A  Reference
```

Sections 2 and 3 are the **same template at two scopes** (software, then layer/component), so we build one
set of scope-parameterised section-builders rather than two.

## Decisions

None yet — pending client discussion.

## Section readiness

| Group | Status |
|---|---|
| Introduction, Global Header, Terms | Ready — reuse / re-scope existing SWE.3 output |
| Static Design, Function Allocation, Dynamic Behaviour, Layer/Component detail | Mostly derivable from the code + call graph; needs the feature list to sharpen |
| Resource Management, Configuration & Calibration Data | **Needs client input** — stub or omit for now |
| Requirements table, Traceability | **Blocked** on a requirements source (Polarion / SWE.1) — shared dependency |
| Architecture Evaluation | New — derived from the assembled architecture |

## Crux — the feature list (§2.2.1)

The crux is collapsing the codebase (thousands of functions) into the product's **feature list**
(Reset/Power, UFS boot, Patrol Read, Data Refresh, …). This is an abstraction problem, not a fixed lookup,
so we **draft then confirm** (see the playbook). We combine several signals — the config structure, entry
points, call-graph clustering, LLM summaries, and naming — and switch to simply *classifying* functions
if the client provides a feature list to seed from.

## Open items

- [ ] Discovery spike: settle the driving inputs (feature list, hardware-interface config) and data sources.
- [ ] Prototype the feature-list derivation; confirm a sample with the client.
- [ ] Confirm the requirements-table columns and the interface-combine strategy with the client.
- [ ] Check for existing product docs (specs / feature list) to seed the draft.
