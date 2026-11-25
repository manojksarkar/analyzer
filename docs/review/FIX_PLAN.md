# Fix plan — reviews SWE3_V4 and SWE3_V5

Issues: [issue_list.csv](issue_list.csv). Verdicts: [REVIEW_TRIAGE_SPEC](../spec/REVIEW_TRIAGE_SPEC.md).
Rules to agree: [RULE_DECISIONS](RULE_DECISIONS.md).

## Status (2026-11-25)

| Status | Count | Issues (SWE3-…) |
|---|---|---|
| Verified at the review site | 13 | 001–007, 009–011, 013, 014, 030 |
| To verify | 7 | 008, 012, 017, 025, 026, 027, 028 |
| Open | 5 | 015, 016, 019, 021, 031 |
| Nothing to do (as per rule) | 6 | 018, 020, 022, 023, 024, 029 |
| **Total** | **31** | |

## To verify

One run checks all seven: branch `fix/review-rules` (develop is in it), generated with `--full`
(Fresh run in the app). An incremental run keeps the old parse for the files it does not re-read.

| Issue | Branch | What to check on the run |
|---|---|---|
| SWE3-008 | `fix/review-rules` | A `case` or `if` on a name from a header that is not found keeps both arrows |
| SWE3-012 | `fix/review-rules` | The log lists each branch drawn without its arrow (`branch missing: file:line function`): read the list |
| SWE3-017 | `fix/review-rules` | Code under an `#if` that the build's `-D` flags turn on is there. Needs that commit's `compile_commands.json` |
| SWE3-025 | `fix/review-rules` | `DeleteSomething`, and methods that write their own members, are In. If `VOID` is a typedef they stay `Out: returns a value (VOID)`: a separate fix |
| SWE3-028 | `fix/review-rules` | A virtual call reaches the overrides below it; the function is in the right unit's interface table |
| SWE3-026 | develop | Calls through `->` appear in dynamic behaviour; the log lists every call not linked |
| SWE3-027 | develop | A call through a function pointer reaches the functions stored in it |

## All issues

| Issue | Verdict | Problem | Fix or rule | Status |
|---|---|---|---|---|
| SWE3-001 | Defect | Class: writes to static members | `x++`, `this->s_x`, `obj.s_x` count as writes | verified |
| SWE3-002 | Defect | Class: access specifier | Access no longer decides public (SWE3-UI-01.3) | verified |
| SWE3-003 | Defect | Static diagram not sliced | Fitted to the page | verified |
| SWE3-004 | Defect | Orphan header's enum in every unit | Listed once, in one unit | verified |
| SWE3-005 | Defect | Orphan header's function counted as another unit's | The header belongs to its own unit | verified |
| SWE3-006 | Defect | Globals not in the unit headers | Listed | verified |
| SWE3-007 | Defect | Class: structs and classes missing | Struct, class and union listed | verified |
| SWE3-008 | Defect | Flowchart: a header not reached drops a branch | A `case` keeps its branch; an `if` on a name from that header keeps both arrows | to verify |
| SWE3-009 | Defect | Flowchart: steps in the JSON, not in the DOCX | Big charts drawn whole | verified |
| SWE3-010 | Defect | Flowchart: text cluttered | One label in the middle of the arrow, the constant only | verified |
| SWE3-011 | Defect | Flowchart: Return not joined to End | A `return` inside `{ }` ends its branch | verified |
| SWE3-012 | Defect | Flowchart: one side of a branch missing | 008 and an empty side fixed; the log lists any branch still drawn without its arrow | to verify |
| SWE3-013 | Defect | Flowchart: wrong value on a branch | Labels keep the code's numbers and constants | verified |
| SWE3-014 | Defect | Flowchart: both branches look the same | Different code, different labels | verified |
| SWE3-015 | Defect | Flowchart: wording should change | Reviewers correct it in the app | open: the reviewers |
| SWE3-016 | Gap | A file with only types or macros gets no unit | Agree the rule, then build (on hold) | open: decide |
| SWE3-017 | Gap | Code under an `#if` that is off is missing | Each layer's macros start from the build's `-D` flags; a macros file wins on a name | to verify |
| SWE3-018 | As per rule | Need a proper data dictionary | Data Range comes from the project's data dictionary (SWE3-UI-04) | — |
| SWE3-019 | As per rule | Public inline functions shown | Public = another unit calls it (SWE3-UI-01). Planned: Hide per function (BACKLOG WA-1) | open: later |
| SWE3-020 | As per rule | Globals in both unit header and interface | Unit header lists all; interface the used ones | — |
| SWE3-021 | As per rule | A function no other unit calls is not shown | Not public (SWE3-UI-01). Planned: Show per function (BACKLOG WA-1) | open: later |
| SWE3-022 | As per rule | Orphan header's enum in the wrong unit | Listed once, in the first unit that uses it (SWE3-UH-04) | — |
| SWE3-023 | As per rule | Enum in one component only | Same rule (SWE3-UH-04) | — |
| SWE3-024 | As per rule | Input name missing or incomplete | First parameter, else a global, else `<Function> input` (SWE3-FD-03) | — |
| SWE3-025 | As per rule | Direction Out without a global write | Rule changed, to agree (SWE3-UI-05): writing its own member, or through a pointer or reference parameter, makes it In. SWE.4's half not done | to verify |
| SWE3-026 | Defect | Dynamic behaviour missing: calls through `->` | Pointer-field calls linked; every call not linked is logged | to verify |
| SWE3-027 | Defect | Indirect dispatch call not found | A call through a function pointer reaches what is stored in it (rule SWE3-UI-01.6, to agree) | to verify |
| SWE3-028 | To check | A function in the interface table of the unit that calls it; overrides | A virtual call reaches the method it names and the overrides below it | to verify |
| SWE3-029 | As per rule | Interface lists only callers from the same component | Any other unit, of any component, gives a row (SWE3-UI-01) | — |
| SWE3-030 | Defect | Dynamic behaviour: descriptions not by the LLM | Tried again, a second round, logged | verified |
| SWE3-031 | As per rule | Protected global has no unit header row | Listed whatever its access (SWE3-UH-01.2) | open: need the example |
