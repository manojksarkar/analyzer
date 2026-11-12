# Fix plan — review issues

How each issue in [issue_list.csv](issue_list.csv) is fixed. The issue list stays as it is; this file changes
as work moves. Verdicts: [REVIEW_TRIAGE_SPEC](../spec/REVIEW_TRIAGE_SPEC.md).

**Effort**: days to find and fix. A run and check at the review site takes 3 d; a fix that fails needs
another run.

## Review SWE3_V4 (2026-11-11)

### Time — 12 to 26 days

Fixes go in batches, one review-site run each. The next batch is fixed while a run goes on; a fix that
fails goes into the next run.

| Step | Fix | Days | Review site meanwhile |
|---|---|---|---|
| 1 | 10, 11, 13, 15; 12 once found | 5–10 | run today's code: verify 08, 09; investigate 12, 17 |
| 2 | 17, 18, 19, 27; re-fixes from step 1 | 4–9 | run step 1 |
| 3 | re-fixes from step 2 | 0–1 | run step 2 (3 d); one more run if needed (3 d) |

Best: 5 + 4 + 3 = 12 d. Worst: 10 + 9 + 3 + 1 + 3 = 26 d. With function visibility and editable direction
(BACKLOG WA-1, S3-20, 13 d to build): 25 to 40 d.

### Open

| Issue ID | Issue | Fix | Effort | Status |
|---|---|---|---|---|
| SWE3-V4-10 | Flowchart: text cluttered | Case labels overlap under the diamond.<br>1) Label in the middle of the arrow.<br>2) Constant only: `eVALUE`, not `case Type::eVALUE`.<br>3) Cases to the same box share one arrow | 1–2 d | open |
| SWE3-V4-11 | Flowchart: Return not joined to End | A `return` inside an extra `{ }` gets an arrow to the next step.<br>1) Look inside nested `{ }` for how a branch ends.<br>2) No arrow on after `return`, `break`, `continue`, `goto`.<br>3) A test case in the sample | 1–2 d | open |
| SWE3-V4-12 | Flowchart: one side of a branch missing | 1) Header not found: fixed by SWE3-V4-08; check at the review site.<br>2) Macro off: SWE3-V4-19.<br>3) Other causes: to find | 1–2 d | investigate |
| SWE3-V4-13 | Flowchart: wrong value on a branch | Branch labels from the code, not the LLM | 1–2 d | open |
| SWE3-V4-14 | Flowchart: both branches look the same | Fixed by SWE3-V4-13 | 0 d | open: after SWE3-V4-13 |
| SWE3-V4-15 | Flowchart: a value, parameter or call wrong | Boxes keep the code's values and parameters | 1–2 d | open |
| SWE3-V4-16 | Flowchart: wording or label | Reviewers correct it in the app | 0 d | open: the reviewing team |
| SWE3-V4-17 | Return type not updated | To find, then fix | 1–2 d | investigate |
| SWE3-V4-18 | Gap: which files make a unit | Agree the rule, then build | 1–2 d | decide |
| SWE3-V4-19 | Gap: a macro that is off | Read each file's `-D` flags from `compile_commands.json` | 1–2 d | decide |
| SWE3-V4-27 | Direction Out for a function that changes state without writing a global | SWE3-UI-05 changes:<br>1) In words like `set`: Delete, Insert, Backup… (config).<br>2) Writing a field of its own class counts like a global write.<br>Editable direction: BACKLOG S3-20 | 1–2 d | decide |

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
| SWE3-V4-20 | Need proper data dictionary | Data Range comes from the data dictionary (SWE3-UI-04) | — |
| SWE3-V4-21 | Public inline functions appearing | Public = another unit calls it (SWE3-UI-01) | Function visibility: Hide makes it private. BACKLOG WA-1 |
| SWE3-V4-22 | Globals in both unit header and interface | Unit header: all symbols (SWE3-UH-01); interface: public ones (SWE3-UI-01) | — |
| SWE3-V4-23 | A function no other unit calls has no row or entry | Not public: no row (SWE3-UI-01); its flowchart is under its caller (SWE3-FD-01) | Function visibility: Show makes it public. BACKLOG WA-1 |
| SWE3-V4-24 | Orphan header's enum in the wrong single unit | Listed once, in the first unit by name (SWE3-UH-04) | — |
| SWE3-V4-25 | Enum appears in one component | Same rule (SWE3-UH-04) | — |
| SWE3-V4-26 | Input name missing or incomplete | First parameter; else a global; else `<Function> input` (SWE3-FD-03) | — |
