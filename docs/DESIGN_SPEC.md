# Design Spec

Update this document first when changing any logic, then update the code and tests to match.

---

## Interface Tables

**Output:** `output/interface_tables.json`

---

### REQ-IT-01 — Unit inclusion

The view produces one table per `.cpp`-backed unit. Header-only units are excluded.
When the run is module-scoped, only units from those modules are included.

**Verification:** Unit keys in the output correspond to `.cpp` files only.

---

### REQ-IT-02 — Entry inclusion

Each unit table includes all `PUBLIC` and `PROTECTED` functions and global variables.
`PRIVATE` functions and globals are excluded.

**Verification:** Known private items do not appear. Known public/protected items do appear.

---

### REQ-IT-03 — Sort order

Entries within each unit are sorted by source line number in ascending order.

**Verification:** Line numbers of entries are non-decreasing within each unit.

---

### REQ-IT-04 — Columns

Each entry has the following columns:

| Column | Function | Global Variable |
|---|---|---|
| Interface ID | `IF_<PROJ>_<GROUP>_<UNIT>_<NN>` | same format |
| Interface Name | short function name | short variable name |
| Information | LLM description, or `-` | same |
| Data Type | semicolon-joined param types; `VOID` if no params | C++ variable type |
| Data Range | semicolon-joined param ranges from data dictionary; `NA` if none | range from data dictionary |
| Direction (In/Out) | `In` or `Out` — see REQ-IT-05 | always `In/Out` |
| Source/Destination | external caller/callee units; `-` if none | unit path |
| Interface Type | `Function` | `Global Variable` |

**Verification:** All columns are present on every entry. Values match the rules in the referenced requirements.

---

### REQ-IT-05 — Direction (functions)

Direction is determined from direct global variable access within the function's own AST.
Access through callees is not traced.

| Access pattern | Direction |
|---|---|
| Writes any global | `In` |
| Reads globals, writes none | `Out` |
| No global access | `Out` |

If a nested function or lambda writes a global, the enclosing function also gets `In`.
Global variables always get `In/Out` regardless of access pattern.

**Verification:** Known setter functions are `In`. Known getter and pure functions are `Out`. All globals are `In/Out`.

---

### REQ-IT-06 — Interface Name

Interface Name is the short (unqualified) name of the function or global variable.

**Verification:** Interface Name matches the last segment of the qualified name.

---

### REQ-IT-07 — Information

Information holds the LLM-generated description of the function or global variable.
When no description is available, the value is `-`.

**Verification:** When LLM descriptions are off, Information is `-` for all entries.

---

### REQ-IT-08 — Data Type

For functions, Data Type is the semicolon-joined list of parameter types. When a function has no parameters, the value is `VOID`.
For global variables, Data Type is the C++ variable type.

**Verification:** Functions with known parameter types show the correct types. Parameter-less functions show `VOID`. Globals show their declared type.

---

### REQ-IT-09 — Data Range

Data Range is looked up from the data dictionary using the type as the key.
For functions, ranges are semicolon-joined across all parameters. When no range is found, the value is `NA`.
For global variables, the range comes from the variable type lookup.

**Verification:** Types with a known data dictionary entry show the correct range. Types without an entry show `NA`.

---

### REQ-IT-10 — Interface Type

Interface Type identifies whether the entry is a function or a global variable.
The value is `Function` for functions and `Global Variable` for global variables.

**Verification:** All function entries have Interface Type `Function`. All global variable entries have Interface Type `Global Variable`.

---

### REQ-IT-11 — Interface ID

Format: `IF_<PROJ>_<GROUP>_<UNIT>_<NN>`

- Each named segment contains uppercase letters only (digits and underscores stripped).
- `<GROUP>` is omitted when no group resolves for the unit.
- `<NN>` is a zero-padded sequential index within the unit.

**Verification:** All interface IDs match the pattern `IF_<UPPER>..._<NN>`.

---

### REQ-IT-12 — Source/Destination

`callerUnits` and `calleesUnits` list all units that call or are called by this function, including same-module units.
`sourceDest` contains external units only (units from a different module).
When there are no external callers or callees, `sourceDest` is `"-"`.
Global variable entries always have empty `callerUnits` and `calleesUnits`.

**Verification:** Functions with known external callers show them in `sourceDest`. Functions with no external connections show `"-"`. Global entries have empty lists.

---
