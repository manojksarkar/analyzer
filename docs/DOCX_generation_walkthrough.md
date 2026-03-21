# Software Detailed Design DOCX — Section Guide

This guide explains **what each part of the generated DOCX is for** and **how sections are ordered**, at document / design level — not domain rules, not routine-level implementation detail.

The generated **Software Detailed Design** presents modules, units, and interfaces from overview down to table rows. Where useful, subsections note **what to cover** and **expected depth** for readers — without naming individual routines in the narrative body.

**Reading order:** start with the outline below, then Section 1, then each module chapter in numeric order (static design for each unit before dynamic behaviour for that module).

---

## Outline and numbering

| Order | Section | Role |
|-------|---------|------|
| Title | Software Detailed Design | Pipeline output |
| **1** | Introduction | Purpose, scope, terms |
| **2 … N** | One chapter per **module** | Logical slice of the tree (config / top-level area) |
| **N+1** | Code Metrics, Coding Rule, Test Coverage | Placeholder |
| **Appendix A** | Design Guideline | Placeholder |

**Inside each module:** **Static Design** (structure, units, interfaces, declarations) then **Dynamic Behaviour** (interactions across units).

**Numbers:**

- `1` = Introduction only.
- First module = `2`, second = `3`, and so on.
- Under a module: `N.1` = Static Design, `N.2` = Dynamic Behaviour.
- Units: `N.1.1`, `N.1.2`, … (third number = unit index).
- Under unit `N.1.x`: `N.1.x.1` = unit header, `N.1.x.2` = unit interface table, `N.1.x.3`, `N.1.x.4`, … = one subsection per interface row (same order as the table).

**Terms:** *Module* = configured top-level group; *Unit* = typically one compilation unit (file name); *Interface* = one row in the unit interface table (function or global variable).

---

## Section 1 — Introduction

**1.1 Purpose** — why this document exists. **1.2 Scope** — what is in scope (and when filled, what is out of scope). **1.3 Terms** — acronyms and terms used later in the DOCX.

**When fully written:**

- **1.1** — Audience, objective of the document, how it sits next to other artifacts (architecture, tests, etc.).
- **1.2** — Product or subsystem boundary, baseline or version if relevant, external systems only at a high level.
- **1.3** — One line per acronym or special term; expand on first use in the body if needed.

**Today:** headings with short placeholder paragraphs (replace for a real project).

---

## Sections 2 … N — Per module

**Module chapter expectations:**

- Section title uses the **module name** from the analysis configuration.
- **Static Design** (`N.1`) appears before **Dynamic Behaviour** (`N.2`) so structure is read before interaction.

### N.1 Static Design

| Block | Role | Notes |
|-------|------|--------|
| Module → units diagram | Module name + unit names from model | One node for the module, one per unit; labels match headings and tables; unit order matches index table when possible |
| Index table (Component \| Unit \| Description \| Note) | Inventory + short unit summary | Description from aggregated interface text; Note column shows `N/A` until filled |
| Unit title + path | Locate sources | Human-readable name + path without extension |
| Unit diagram | Unit-level diagram | Placed above the unit header when the asset is produced |
| **N.1.x.1** Unit header | Globals + typedef/enum/define | Left: declaration/macro; right: value / enumerators / note; avoid duplicate rows when the pipeline merges entries |
| **N.1.x.2** Unit interface | Main interface table | See column table below |
| **N.1.x.3+** Per interface | One subsection per table row | Heading: unit display name — interface id; body: flowchart PNG if available, else description text; subsection order matches table row order |

**Interface table columns**

| Column | Meaning |
|--------|---------|
| Interface ID | Stable id for cross-references |
| Interface Name | Name of the interface |
| Information | Short description of role or behaviour |
| Data Type / Data Range | For **functions**, **inputs** via parameter types/ranges; **no parameters** → **VOID** / **NA**. For **globals**, variable type and range |
| Direction (In/Out) | How flow is classified for that row |
| Source/Destination | Related unit or area |
| Interface Type | Kind of row (e.g. Function vs Global Variable) |

**Table quality:** Do not leave type/range empty — use VOID/NA for functions with no parameters; keep Direction and Source/Destination consistent with the analysis; keep Information readable (one sentence or short paragraph per row when a description exists).

### N.2 Dynamic Behaviour

**Content per subsection (one per behaviour row):**

- **Title line** — unit name, active logic, and another callee in parentheses when the row describes a cross-unit call.
- **Behaviour description table** — bullet list of behaviour points when provided; Risk and Capacity lines use defaults unless overridden elsewhere.
- **Input name / Output name** — short labels from the enriched model when present; otherwise readable generated labels.
- **Behaviour** — diagram image under the bold “Behaviour” label when the file exists on disk.

**Ordering:** Subsections are sorted in a stable way (e.g. by unit name, then order in behaviour metadata) so two exports stay comparable.

---

## Code Metrics / Appendix A

**Code Metrics, Coding Rule, Test Coverage (last numbered section):**

- Placeholder today.
- When filled: quantitative metrics (size, complexity, or org-specific counts), pointers to coding standards or checklists, test coverage summary or link to a report.

**Appendix A — Design Guideline:**

- Placeholder today.
- When filled: naming conventions for modules/units, error-handling or logging expectations at design level, constraints (real-time, memory, safety) if they shape the structure in the main body.

---

## Data sources (reference)

| Need | Location |
|------|----------|
| Interface tables + text | `output/interface_tables.json` |
| Unit header | `model/units.json`, `model/globalVariables.json`, `model/dataDictionary.json`, sources under project base from metadata |
| Behaviour labels and rows | `model/functions.json`, `output/behaviour_diagrams/_behaviour_pngs.json` |
| Diagrams | `output/flowcharts/`, `output/unit_diagrams/`, `output/module_static_diagrams/` |
| DOCX output | `output/software_detailed_design_all.docx` (exact filename from export settings) |

**Config (affects DOCX):** `config/config.json` — e.g. `views.moduleStaticDiagram` (diagram size and rendering), `views.flowcharts`, `export.docxPath` and `export.docxFontSize`.

**Refresh:** Regenerate model and views, then run the project **DOCX export** step from the repo root (see README).

---

## Diagrams

These are **fixed places** in the DOCX layout. Each type is generated from the pipeline outputs below.

| Diagram | Where it appears | Source |
|---------|------------------|--------|
| Module → units | Start of each module’s Static Design | Module + unit names in the model |
| Unit | Under each unit heading, before unit header | `output/unit_diagrams/` |
| Per-interface flowchart | Under each interface subsection | `output/flowcharts/` |
| Behaviour | Under each Dynamic Behaviour subsection | Behaviour view + PNG path in metadata |
