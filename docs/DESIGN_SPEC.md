# Design Spec

Update this document first when changing any logic, then update the code and tests to match.

Rules describe what must appear in the final output (DOCX and intermediate artifacts read by the exporter).
They are independent of implementation — they say **what**, not **how**.

---

## Document Structure

**Output:** `output/software_detailed_design_<group>.docx`

---

### REQ-DS-01 — Document sections

The document contains the following top-level sections in order:
- Introduction (with sub-sections: Purpose, Scope, Terms)
- One section per module in the selected group
- Code Metrics
- Appendix

**Verification:** Each section heading is present. Sections appear in the correct order.

---

### REQ-DS-02 — Module sections

Each module has a Heading 1 section. Within it, each unit has its own sub-section containing:
- A unit architecture diagram
- A unit header table (global variables, typedefs, enums, defines)
- An interface table

**Verification:** All module names appear as Heading 1. All unit names appear as Heading 3 within their module.

---

### REQ-DS-03 — Static Design sub-section

Each module section includes a Static Design sub-section. It contains:
- A component/unit overview table
- A flowchart entry for every function in each unit
- A module architecture diagram

**Verification:** "Static" heading present. Component/unit table present. Flowchart tables present. Module diagram present.

---

### REQ-DS-04 — Dynamic Behaviour sub-section

Each module section includes a Dynamic Behaviour sub-section. It contains one scenario entry for every external-caller interaction within that module.

**Verification:** "Dynamic Behaviour" heading present. Scenario sub-headings present for units with external callers.

---

## Interface Tables

**Output:** One table per unit, embedded in the DOCX unit section.

---

### REQ-IT-01 — Scope

Every unit that has a source implementation file produces one interface table in the document. Units with only a header file produce no table.

**Verification:** Unit keys in the output correspond to source-backed units only.

---

### REQ-IT-02 — Entry inclusion

The table lists all public and protected functions and global variables of the unit. Private items do not appear.

**Verification:** Known private items absent. Known public and protected items present.

---

### REQ-IT-03 — Row order

Rows appear in the same order the items are declared in the source file, top to bottom.

**Verification:** Line numbers of successive rows are non-decreasing within each unit.

---

### REQ-IT-04 — Columns

Every row contains all eight columns:

| Column | Function entry | Global Variable entry |
|---|---|---|
| Interface ID | Unique structured ID | Same format |
| Interface Name | Short, unqualified name | Short, unqualified name |
| Information | Description, or `-` | Description, or `-` |
| Data Type | Input parameter types | Declared variable type |
| Data Range | Valid value ranges | Valid value range |
| Direction | `In` or `Out` | `In/Out` |
| Source/Destination | External units interacting with this interface | Unit path |
| Interface Type | `Function` | `Global Variable` |

**Verification:** All columns present on every row. Values match the rules below.

---

### REQ-IT-05 — Direction

A function that modifies shared state has direction **In**.
A function that only reads shared state, or has no side effects at all, has direction **Out**.
Global variables always have direction **In/Out**.

**Verification:** Known modifier functions are `In`. Known read-only and pure functions are `Out`. All global variable rows are `In/Out`.

---

### REQ-IT-06 — Interface Name

The interface name is the short, unqualified name of the function or variable — no namespace prefix, no class prefix.

**Verification:** Interface Name matches the last part of the fully qualified name.

---

### REQ-IT-07 — Information

Shows a human-readable description of what the function or variable does.
When no description is available, shows `-`.

**Verification:** When LLM descriptions are off, every Information cell is `-`.

---

### REQ-IT-08 — Data Type

For functions: the parameter types, separated by semicolons. When the function takes no parameters, shows `VOID`.
For global variables: the declared C++ type.

**Verification:** Functions with known parameters show correct types. Parameter-less functions show `VOID`. Globals show their declared type.

---

### REQ-IT-09 — Data Range

The valid value range for each data type, looked up from the data dictionary.
For functions with multiple parameters, ranges are semicolon-joined in parameter order.
Shows `NA` when no range is defined for a type.

**Verification:** Types with a data dictionary entry show the correct range. Types without an entry show `NA`.

---

### REQ-IT-10 — Interface Type

Identifies whether the row is a function or a global variable.
Value is exactly `Function` or `Global Variable`.

**Verification:** All function rows show `Function`. All global variable rows show `Global Variable`.

---

### REQ-IT-11 — Interface ID

Every interface has a unique structured identifier in the format `IF_<PROJECT>_<GROUP>_<UNIT>_<NN>`.
Each named segment uses uppercase letters only.
`<GROUP>` is omitted when no group applies.
`<NN>` is a zero-padded sequential number within the unit.

**Verification:** All IDs start with `IF_`. Segments are uppercase. IDs are unique across the group.

---

### REQ-IT-12 — Source/Destination

For functions: lists the external units (from outside the current module) that call or are called by this function.
Shows `-` when there are no external connections.
Global variable rows have no caller or callee lists.

**Verification:** Functions with known external callers show them. Functions with no external connections show `-`. Global variable rows have empty caller/callee fields.

---

## Unit Architecture Diagrams

**Output:** One diagram per unit, embedded in the DOCX unit section.

---

### REQ-UD-01 — Scope

Every source-backed unit has a diagram. Header-only units have no diagram.
When generating for a specific group, only units in that group are included.

**Verification:** A diagram is present for every source-backed unit. Header-only units produce no diagram.

---

### REQ-UD-02 — Node representation

Each unit appears as a distinct node. Node identifiers are unambiguous and contain no characters that would corrupt the diagram.

**Verification:** Every unit in the call graph appears as a node. No node ID contains invalid characters.

---

### REQ-UD-03 — Label readability

Node labels are human-readable. Characters that would break diagram rendering are replaced with safe equivalents (e.g. quotes, newlines, pipes).

**Verification:** Labels containing special characters render correctly without breaking the diagram.

---

### REQ-UD-04 — Diagram orientation

The diagram flows left-to-right. The current unit's module is visually grouped as a labelled subgraph. The subgraph label matches the module name.

**Verification:** Diagram direction is left-to-right. Subgraph is present and labelled with the module name.

---

### REQ-UD-05 — Call edges

An arrow connects two units for every cross-unit call relationship. The arrow is labelled with the interface identifier of the called function. When a unit makes multiple calls to another unit, all interface identifiers appear on the same arrow. A unit does not draw an arrow to itself.

**Verification:** Known cross-unit calls produce labelled arrows with `IF_` identifiers. Same-unit calls produce no arrow. Multiple calls share one arrow with all identifiers.

---

### REQ-UD-06 — Node placement

External units that call into the current module appear to the left of the module subgraph.
External units that the current module calls appear to the right.
The current unit and its same-module peers occupy the subgraph in the centre.

**Verification:** External caller nodes appear before the subgraph declaration. External callee nodes appear after the subgraph close.

---

### REQ-UD-07 — Visual styling

The current unit is visually distinct from other nodes (thick border).
Same-module peer units have a secondary visual style.
External units have the default style.

**Verification:** Current unit has `mainUnit` style. Peer units have `internal` style. No peer is styled as `mainUnit`.

---

### REQ-UD-08 — Group boundary

When the document is generated for a specific group of modules, all units within that group are treated as internal (shown inside or alongside the subgraph). Units from outside the group are external.

**Verification:** Units from the selected group are styled as internal. Units from outside are styled as external.

---

## Dynamic Behaviour

**Output:** Scenario entries in the Dynamic Behaviour sub-section of each module.

---

### REQ-BD-01 — Scenario scope

A scenario entry exists for every function in the unit that is called by at least one unit outside the selected module group. Functions only called by same-module units have no entry.

**Verification:** Functions with known external callers have scenario entries. Functions only called internally have no entry.

---

### REQ-BD-02 — Scenario heading

Each scenario has a heading that identifies both the current function and the external unit that calls it.

**Verification:** Scenario headings contain the function name and the caller unit name.

---

### REQ-BD-03 — Sequence diagram

Each scenario includes a diagram showing the interaction between the external caller and the current function.

**Verification:** A diagram is present in every scenario entry. The diagram is a valid Mermaid diagram.

---

### REQ-BD-04 — Description table

Each scenario has a description table with the following rows:
Requirements, Risk, Capacity, Input Name, Output Name.

**Verification:** All five row labels are present in every scenario description table.

---

### REQ-BD-05 — Input and Output Names

Input Name describes what data the function receives.
Output Name describes what the function produces or affects.
Both are human-readable labels derived from the function's parameters, return value, or shared state it accesses.

**Verification:** Input Name and Output Name are non-empty strings. They are not raw identifiers or generic placeholders when a meaningful name can be derived.

---

## Static Design / Flowcharts

**Output:** Flowchart entries in the Static Design sub-section of each unit.

---

### REQ-FC-01 — Scope

The Static Design section contains a flowchart entry for every function in the unit.

**Verification:** Every expected public function has a flowchart entry in the document.

---

### REQ-FC-02 — Function label

Each flowchart entry is labelled with the short, unqualified function name.

**Verification:** Entry labels match the short function names, not fully qualified names.

---

### REQ-FC-03 — Flowchart content

The flowchart shows the control flow of the function as a valid diagram. It is non-empty.

**Verification:** Every flowchart entry contains a non-empty, valid Mermaid diagram.

---

### REQ-FC-04 — Metadata table

Each flowchart entry has an accompanying metadata table. The table includes a Capacity (Density) row describing the complexity.

**Verification:** `Capacity(Density)` row label present in flowchart metadata tables.

---

## Component Overview

**Output:** Component/unit table in the Static Design sub-section.

---

### REQ-CO-01 — Table presence

A component/unit overview table is present in the Static Design section, listing all modules and their units.

**Verification:** Table with `Component`, `Unit`, `Description`, `Note` column headers is present.

---

### REQ-CO-02 — Table content

The table includes a row for each module in the selected group. The module names appear in the Component column.

**Verification:** All module names appear in the component/unit table.

---

### REQ-CO-03 — Module architecture diagram

The Static Design section includes a diagram showing the architecture of the selected module group.

**Verification:** An image or Mermaid diagram is present in the Static Design section.

---
