# SWE.2 Plan — Software Architecture Design (SAD)

> **SWE.2 = one document:** the "Software Architecture Design Specification" (SAD). No client template —
> structure was captured verbally (started 2026-07-06). The section table is **verified against `main`
> (2026-07-08)**; refer to it when building.

## What it is
- **One SAD document.** SWE.2 = architecture; SWE.3 = detailed design.
- **Out of the SAD body:** Traceability (separate doc) and Technical Review checklist (Polarion).
- The earlier requirements-style list was actually **SYS.2** → `docs/planning/SYS2_PLAN.md`.
- **Two driving inputs, both still in discussion:** the function/feature list (§2.2.1, see below) and the
  hardware-interface-layer config (§2.1).
- **Not yet placed in the TOC:** Data Dictionary, Component Dynamic Behaviour.

## How we build it
- **V-model position.** Design flows down SYS.1 → SYS.2 → SWE.1 → **SWE.2** → SWE.3 (design + code). Tests pair
  across: SWE.3 ↔ SWE.4 (unit), SWE.2 ↔ SWE.5 (integration). We have **SWE.3 today**.
- **Bottom-up from code.** SWE.2 normally derives from SYS/SWE.1, which we lack. So build from what we have —
  code + SWE.3 + per-part descriptions — deriving component/unit sections first, then **rolling up §3.N → §2**
  (this roll-up is the critical path).
- **One model, one bar: logical correctness.** All docs come from one shared model, so they're consistent by
  construction. A coherent, traceable draft is acceptable even if wording deviates from the client's — which makes
  the **code-only floor a shippable first draft**.

**Floor (build now, no feature list needed):** code-derived §1.3, §2.1, §2.2, §2.3, §2.5, §2.8, all of §3.N, §4.2;
boilerplate §1.1, §1.2, §4.1, App A.

**Gaps (need input — stub or omit for now):** Resource Management (§2.4 / §3.N.4); Config-data *semantics* (§2.6 /
§3.N.6 — macro values derive, ranges/meaning don't); requirements table (§3.N.3.x.y, Polarion). Calibration = N/A.

**Optional inputs sharpen but never block:** a feature list flips §2.2.1 from *discover* → *classify*; a
HW-interface config sharpens §2.1 / §2.3; resource/config specs fill §2.4 / §2.6; Polarion fills the requirements
table + traceability.

## Target structure (TOC)

```
Software Architecture Design Specification (title)

1  Introduction
   1.1 Purpose
   1.2 Scope
   1.3 Terms, Abbreviations and Definitions

2  Software Architecture Design            ← software-level block
   2.1 Software Static Design
   2.2 Function Allocation
       2.2.1 Function Definition             (provided as input)
       2.2.2 Function Allocation
   2.3 Layer Interface
       2.3.N  <LayerName>                    ← repeats per layer
   2.4 Resource Management
   2.5 Dynamic Behaviour
   2.6 Configuration Data
       2.6.1 Dynamic Configurations
       2.6.2 Static Configurations           ← initial values + ranges
   2.7 Calibration Data
   2.8 Global Header

3  Layer Design                            ← layer/component detail
   3.N <LayerName>
       3.N.1 Static Design                  (layer diagram + Component Information table)
       3.N.2 Function Allocation            (mirrors §2.2 at layer scope)
       3.N.3 Component Design
             3.N.3.x <ComponentName>              (component design diagram)
                     3.N.3.x.1 <ComponentName> interface   (interface table)
                     3.N.3.x.y  table: Requirement ID | Requirements | Capacity |
                                       Input Name | Output Name | Linked Work Items   (verify later)
       3.N.4 Resource Management
       3.N.5 Dynamic Behaviour
       3.N.6 Configuration Data
             3.N.6.1 Dynamic Configuration
             3.N.6.2 Static Configuration
       3.N.7 Calibration Data
       3.N.8 Layer Header                   (layer-scope counterpart of §2.8)

4  Architecture Design Evaluation
   4.1 Evaluation Criteria
   4.2 Evaluation of Software Architecture

Appendix A  Reference
```

**Hierarchy:** Software (§2) → Layer (§3.N) → Component (§3.N.3.x). §2 and §3.N are the **same 8-part template at
two scopes**, so build **one set of scope-parameterised section-builders**, not two.

## Section status (vs `main`, 2026-07-08)

**Status:** `live` = main renders it, reuse ~as-is · `re-scope` = main has it at component/unit scope, aggregate up
(*light* = mostly re-scope an existing renderer) · `data` = data exists, no renderer yet · `input` = external
input / brand-new · `fixed` = boilerplate or keep existing assets.

| § | Section | Pri | Status | Depends on | How we build it |
|---|---|---|---|---|---|
| 1.1 | Purpose | — | fixed | — | boilerplate |
| 1.2 | Scope | — | fixed | — | boilerplate |
| 1.3 | Terms & Abbreviations | — | live | data dictionary | list terms + abbreviations from the data dictionary |
| **2** | **Software Architecture Design** | | | | |
| 2.1 | Software Static Design | P2 | re-scope + input | HW-interface config (new) | roll component static diagrams up to software-wide; parse the new HW-interface-layer config |
| 2.2.1 | Function Definition | P2 | data + LLM | KB summaries, call graph, config/naming | the feature list (not C++ functions); derive a draft, client confirms — see §2.2.1 below |
| 2.2.2 | Function Allocation | P2 | data | §2.2.1 + code | functions→unit→component derived, layer from config; build the allocation table from §2.2.1 |
| 2.3 | Layer Interface (per layer) | P2 | re-scope + input | §2.1 + code | HW↔FW interface (tricky); build on the §2.1 input, then derive from code |
| 2.4 | Resource Management | P2 | input | external | new config / input |
| 2.5 | Dynamic Behaviour | P1 | re-scope | §2.2.1 + code | behaviour list covering every component; derive from §2.2.1 + call graph |
| 2.6.1 | Dynamic Configuration | P1 | input | config (macros) | new |
| 2.6.2 | Static Configuration | P1 | input | config | init values + ranges; new |
| 2.7 | Calibration Data | — | input | — | none defined (N/A) |
| 2.8 | Global Header | P1 | re-scope *(light)* | data dictionary | SWE.3 unit-header table re-scoped to the global header file(s); renderer exists |
| **3** | **Layer Design** (3.N per layer) | | | | |
| 3.N.1 | Static Design | P1 | re-scope | layer config + KB | layer diagram (from layer config) + Component Information table (Group from config, description from KB; Development Type = new field) |
| 3.N.2 | Function Allocation | P1 | data | §2.2.1 + code | §2.2.2 at layer scope |
| 3.N.3.x | Component Design diagram | P1 | re-scope *(light)* | call graph + layer config | *Component Design* diagram (not main's static-structure one): this component's units flanked by same-layer callers (left) / callees (right); data in model, build the renderer (branch reference) |
| 3.N.3.x.1 | Interface table | P1 | re-scope | per-unit interface tables | combine the units' tables; may fold similar functions → **decision needed** |
| 3.N.3.x.y | Requirements table | — | input | Polarion | req-ID linkage; new |
| 3.N.4 | Resource Management | P2 | input | §2.4 | layer scope of §2.4 |
| 3.N.5 | Dynamic Behaviour | P1 | re-scope | §2.5 | layer subset of §2.5 |
| 3.N.6 | Configuration Data | P1 | input | config | layer scope of §2.6 |
| 3.N.7 | Calibration Data | — | input | — | N/A |
| 3.N.8 | Layer Header | P1 | re-scope *(light)* | data dictionary | SWE.3 unit-header table re-scoped to the layer header |
| **4** | **Architecture Design Evaluation** | | | | |
| 4.1 | Evaluation Criteria | — | fixed | — | boilerplate |
| 4.2 | Evaluation of Software Architecture | — | input | §2 + §3 (+ LLM) | evaluate the derived architecture |
| App A | Reference | — | fixed | — | boilerplate |

**Reuse reality.** No SAD code is in `main` — the revival branches (`feat/architecture-design`, `feat/header-diagram`,
`feat/data-dictionary`) all predate the incremental engine, so **re-port, don't `git merge`**; only the **Component
Design diagram (§3.N.3.x)** is worth reviving. Main's live output is all component/unit scope, so SAD mostly
**aggregates / re-scopes it up** to layer/software, keying every §3.N roll-up off the config `layers` block (not the
model). The genuinely new work is the **`input` sections** — Resource Mgmt (§2.4), Config Data (§2.6), Calibration
(§2.7), requirements table (§3.N.3.x.y) — plus **Evaluation (§4.2)**.

## The §2.2.1 problem — deriving the feature list

The crux: collapse the codebase (1000s of functions) into the product's **feature list** (Reset/Power, UFS boot,
Patrol Read, Data Refresh…; count not fixed). It's an abstraction/clustering problem → **draft-then-confirm**, not
deterministic. Approaches, meant to be combined:

| # | Approach | Input | How | Trade-off |
|---|---|---|---|---|
| A | Structure-first | config tree ✓ | config tree as the feature skeleton; roll up component summaries | deterministic + traceable, but code structure ≠ features |
| B | Entry-point / API | call graph ✓ | start from entry points (opcode handlers, ISRs, exported APIs, task loops, state dispatch), walk down | maps to "what the SW does", but background features have no entry point; N:M |
| C | Call-graph clustering | call graph ✓ | community detection (Louvain) → clusters = subsystems; LLM labels | catches cross-structure features, but granularity knob + hubs blur clusters; non-deterministic |
| D | LLM roll-up | KB summaries ✓ | function→file→component summaries (in KB) → LLM map-reduce into features | reuses summaries + strong semantic grouping, but token budget + can merge inconsistently |
| E | Naming / lexical | names ✓ | cluster by shared prefixes/tokens (`ufs_boot_*`, `patrol_*`) | cheap + deterministic, but relies on naming discipline |
| F | Seed-and-classify | client feature list ✗ | given feature names, only allocate functions→features | sidesteps discovery + higher-confidence, but needs a client seed |

**Default plan:** A + E + B → D (+ C), then human-confirm and check coverage (every component maps to ≥1 feature,
as §2.5 needs). Switch to **F** the moment a seed list appears. Judge a draft by coverage (% assigned), stability
(re-runs agree), and client acceptance on a sample.

**Open questions for the team:** granularity (feature vs sub-feature — need a target level + client examples) ·
do features map to entry points or are they cross-cutting? (B vs C) · is there an existing feature list to seed F? ·
one-to-one or many-to-many mapping? (drives §2.2.2) · validation by client sample or known-good subset?

## Open items
- [ ] Discovery spike: settle the driving inputs + external data sources; revive & run the branch.
- [ ] Check for product docs (specs / feature / design) to feed the LLM and seed the feature list (approach F).
- [ ] §2.2.1 — prototype deriving the feature list; confirm the draft with the client.
- [ ] §2.1 — settle the hardware-interface-layer config.
- [ ] Place the two unplaced sections (Data Dictionary, Component Dynamic Behaviour).
- [ ] §3.N.3.x.1 — decide the interface combine strategy (direct merge vs fold similar functions).
- [ ] §3.N.1 — source for the Development Type column.
- [ ] §3.N.3.x.y — verify the requirements-table columns/meaning with the client.
- [ ] §3.N.2 — decide Function Allocation sub-items (mirror §2.2?).
