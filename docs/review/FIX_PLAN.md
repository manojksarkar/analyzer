# Fix plan — review issues

How each issue in [issue_list.csv](issue_list.csv) is fixed. Verdicts: [REVIEW_TRIAGE_SPEC](../spec/REVIEW_TRIAGE_SPEC.md);
the rules to agree: [RULE_DECISIONS](RULE_DECISIONS.md).

Status: **verified** (checked at the review site) · **to verify** · **open** · **decide** (a rule to agree) ·
**later** (a planned feature) · — nothing to do.

## Summary — reviews SWE3_V4 and SWE3_V5

| Verdict | Fixed | To verify | Open | Nothing to do | Total |
|---|---|---|---|---|---|
| Defect | 13 | 4 | 1 | — | 18 |
| Gap | — | 1 | 1 | — | 2 |
| To check | — | 1 | — | — | 1 |
| As per rule | — | 1 | 3 | 6 | 10 |
| **Total** | **13** | **7** | **5** | **6** | **31** |

"To verify": changed in the tool, to check on a review run. 008, 012, 017, 025 and 028 are on
branch `fix/review-rules`, not in develop yet.

## Defects

| Issue ID | Issue | Fix | Status |
|---|---|---|---|
| SWE3-001 | Class: writes to static members | `x++`, `this->s_x`, `obj.s_x` count as writes | verified |
| SWE3-002 | Class: access specifier | Access no longer decides public (SWE3-UI-01.3) | verified |
| SWE3-003 | Static diagram not sliced | Fitted to the page | verified |
| SWE3-004 | Orphan header's enum in every unit | Listed once, in one unit | verified |
| SWE3-005 | Orphan header's function counted as another unit's | The header belongs to its own unit | verified |
| SWE3-006 | Globals not in the unit headers | Listed | verified |
| SWE3-007 | Class: structs and classes missing | Struct, class and union listed | verified |
| SWE3-008 | Flowchart: a header not reached drops a branch | A `case` keeps its branch; an `if` on any name from that header keeps both arrows (8 forms tested). Only an `#if` drops one: SWE3-017 | to verify |
| SWE3-009 | Flowchart: steps in the JSON, not in the DOCX | Big charts drawn whole | verified |
| SWE3-010 | Flowchart: text cluttered | One label in the middle of the arrow, the constant only | verified |
| SWE3-011 | Flowchart: Return not joined to End | A `return` inside `{ }` ends its branch | verified |
| SWE3-012 | Flowchart: one side of a branch missing | Header not reached (008) and empty branch fixed; the run lists each branch drawn without its arrow, with file and line (none in the sample). Left: read that list on a review run | to verify |
| SWE3-013 | Flowchart: wrong value on a branch | Labels keep the code's numbers and constants | verified |
| SWE3-014 | Flowchart: both branches look the same | Different code, different labels | verified |
| SWE3-015 | Flowchart: wording should change | Reviewers correct it in the app | open: the reviewers |
| SWE3-026 | Dynamic behaviour missing: calls through `->` | Pointer-field calls linked (027); every call not linked is logged. Left: read the log at the review site | to verify |
| SWE3-027 | Indirect dispatch call not found | A call through a function pointer reaches the functions stored in it. Rule SWE3-UI-01.6 to agree | to verify |
| SWE3-030 | Dynamic behaviour: descriptions not by the LLM | Tried again, a second round, logged | verified |

## To check

| Issue ID | Issue | Fix | Status |
|---|---|---|---|
| SWE3-028 | A function in the interface table of the unit that calls it; overrides | A virtual call reaches the method it names and the overrides below it; `Base::f()` reaches that one only | to verify |

## Gaps

| Issue ID | Issue | Fix | Status |
|---|---|---|---|
| SWE3-016 | A file with only types or macros gets no unit | On hold (2026-11-24): agree the rule, then build (1–2 d) | decide |
| SWE3-017 | Code under an `#if` that is off is missing | Each layer's macros start from the build's `-D` flags in `compile_commands.json`; a macros file wins on a name. Needs that commit's `compile_commands.json` | to verify |

## As per rule

| Issue ID | Issue | The rule | Status |
|---|---|---|---|
| SWE3-018 | Need a proper data dictionary | Data Range comes from the project's data dictionary (SWE3-UI-04) | — |
| SWE3-019 | Public inline functions shown | Public = another unit calls it (SWE3-UI-01). Planned: Hide per function (BACKLOG WA-1) | later |
| SWE3-020 | Globals in both unit header and interface | Unit header lists all; interface the used ones | — |
| SWE3-021 | A function no other unit calls is not shown | Not public (SWE3-UI-01). Planned: Show per function (BACKLOG WA-1) | later |
| SWE3-022 | Orphan header's enum in the wrong unit | Listed once, in the first unit that uses it (SWE3-UH-04) | — |
| SWE3-023 | Enum in one component only | Same rule (SWE3-UH-04) | — |
| SWE3-024 | Input name missing or incomplete | First parameter, else a global, else `<Function> input` (SWE3-FD-03) | — |
| SWE3-025 | Direction Out without a global write | Rule changed (SWE3-UI-05 rows 3–4, to agree): a method that writes a member variable of its own object -- itself, through its own methods, or through a local pointer or reference -- is In; a global written through a local pointer too. 2026-11-25: also a write through a pointer or reference parameter (`pNode->length = …`, the review's DeleteSomething), a typedef pointer included. SWE.4's half (member variables in Precondition, Input, Expected Results) not done | to verify |
| SWE3-029 | Interface lists only callers from the same component | Any other unit, of any component, gives a row (SWE3-UI-01) | — |
| SWE3-031 | Protected global has no unit header row | Listed whatever its access (SWE3-UH-01.2). Need the example | to check |
