# Fix plan — review issues

How each issue in [issue_list.csv](issue_list.csv) is fixed. The issue list stays as it is; this file changes
as work moves. Verdicts: [REVIEW_TRIAGE_SPEC](../spec/REVIEW_TRIAGE_SPEC.md).

**Effort**: days to find and fix one issue.

## Review SWE3_V4 (2026-11-11)

### Time — 11 to 13 days, then 4 to 5 for hide/show

| # | Work | Issues | Days |
|---|---|---|---|
| 1 | Setup and environment | Run at the review site (`.axf`); fix 17 and 12's headers; verify 08, 09 | 8–10 |
| 2 | Fixes | 10, 11, 12, 13, 16, 25 | 8–10 |
| 3 | Investigate and review tool | 12; rules for 16, 17, 25; categorize the rest of the review comments (done: SWE.3 100 of 232, SWE.4 350 of 500); the review tool | 8–10 |
| 4 | Hide/show | Function visibility and editable direction (19, 21); lower priority | 4–5 |

Optimistic days. 1–3 run side by side, one person each: 8–10 days, then the last run and check (3 d):
11–13 days.
4 comes after.

### Open

| Issue ID | Issue | Fix | Effort | Status |
|---|---|---|---|---|
| SWE3-V4-10 | Flowchart: text cluttered | Case labels overlap under the diamond.<br>1) Label in the middle of the arrow.<br>2) Constant only: `eVALUE`, not `case Type::eVALUE`.<br>3) Cases to the same box share one arrow | 1–2 d | open |
| SWE3-V4-11 | Flowchart: Return not joined to End | A `return` inside an extra `{ }` gets an arrow to the next step.<br>1) Look inside nested `{ }` for how a branch ends.<br>2) No arrow on after `return`, `break`, `continue`, `goto`.<br>3) A test case in the sample | 1–2 d | open |
| SWE3-V4-12 | Flowchart: one side of a branch missing | 1) Header not found: fixed by SWE3-V4-08; check at the review site.<br>2) Macro off: SWE3-V4-17.<br>3) Other causes: to find | 1–2 d | investigate |
| SWE3-V4-13 | Flowchart: wrong value on a branch | Branch labels from the code, not the LLM | 1–2 d | open |
| SWE3-V4-14 | Flowchart: both branches look the same | Fixed by SWE3-V4-13 | 0 d | open: after SWE3-V4-13 |
| SWE3-V4-15 | Flowchart: wording or label | Reviewers correct it in the app | 0 d | open: the reviewing team |
| SWE3-V4-16 | Gap: which files make a unit | Agree the rule, then build | 1–2 d | decide |
| SWE3-V4-17 | Gap: a macro that is off | Read each file's `-D` flags from `compile_commands.json` | 1–2 d | decide |
| SWE3-V4-25 | Direction Out for a function that changes state without writing a global | SWE3-UI-05 changes:<br>1) In words like `set`: Delete, Insert, Backup… (config).<br>2) Writing a field of its own class counts like a global write.<br>Editable direction: BACKLOG S3-20 | 1–2 d | decide |

### Fixed

**Verified**: checked in the newest documents, not by a test.

| Issue ID | Issue | Fixed by | Verified |
|---|---|---|---|
| SWE3-V4-01 | Class: writes to static members | Writes like `x++`, `this->s_x`, `obj.s_x` now count | Verified |
| SWE3-V4-02 | Class: access specifier | Access no longer decides public (SWE3-UI-01.3) | Verified |
| SWE3-V4-03 | Static diagram not sliced | The container diagram fits the page | Verified |
| SWE3-V4-04 | Orphan header's enum in every unit | Listed once, in one unit (SWE3-UH-04) | Verified |
| SWE3-V4-05 | Orphan header's function counted as another unit's | The header belongs to its own unit | Verified |
| SWE3-V4-06 | Globals not in the unit headers | Globals listed (SWE3-UH-01) | Verified |
| SWE3-V4-07 | Class: structs and classes missing | Struct, class and union listed | Verified |
| SWE3-V4-08 | Flowchart: a header not reached drops a branch | A `case` keeps its branch when its header is not found | To verify; then the review site run (SWE3-V4-12) |
| SWE3-V4-09 | Flowchart: steps in the JSON, not in the DOCX | Big pictures drawn whole; output kept if the engine crashes on exit | To verify |

### As per rule — nothing to fix

| Issue ID | Issue | What the rule gives | Planned |
|---|---|---|---|
| SWE3-V4-18 | Need proper data dictionary | Data Range comes from the data dictionary (SWE3-UI-04) | — |
| SWE3-V4-19 | Public inline functions appearing | Public = another unit calls it (SWE3-UI-01) | Function visibility: Hide makes it private. BACKLOG WA-1 |
| SWE3-V4-20 | Globals in both unit header and interface | Unit header: all symbols (SWE3-UH-01); interface: public ones (SWE3-UI-01) | — |
| SWE3-V4-21 | A function no other unit calls has no row or entry | Not public: no row (SWE3-UI-01); its flowchart is under its caller (SWE3-FD-01) | Function visibility: Show makes it public. BACKLOG WA-1 |
| SWE3-V4-22 | Orphan header's enum in the wrong single unit | Listed once, in the first unit by name (SWE3-UH-04) | — |
| SWE3-V4-23 | Enum appears in one component | Same rule (SWE3-UH-04) | — |
| SWE3-V4-24 | Input name missing or incomplete | First parameter; else a global; else `<Function> input` (SWE3-FD-03) | — |
