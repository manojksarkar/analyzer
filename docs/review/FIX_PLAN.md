# Fix plan — review issues

How each issue in [issue_list.csv](issue_list.csv) is fixed. The issue list stays as it is; this file changes
as work moves. Verdicts: [REVIEW_TRIAGE_SPEC](../spec/REVIEW_TRIAGE_SPEC.md).

- **Verdict**: Defect — the document breaks its rule · Gap — no rule covers it · As per rule — the document
  follows its rule.
- **Status**: verified (checked in the newest documents) · to verify · done (fixed on a branch, not merged) ·
  open · investigate · decide.
- **Effort**: days to find and fix one issue.

## Review SWE3_V4 (2026-11-11)

### Summary

| Verdict | Fixed | Open | Planned | Nothing to do | Total |
|---|---|---|---|---|---|
| Defect — flowchart | 1 | 7 | — | — | 8 |
| Defect — other | 7 | — | — | — | 7 |
| Gap | — | 2 | — | — | 2 |
| As per rule | — | — | 3 | 5 | 8 |
| **Total** | **8** | **9** | **3** | **5** | **25** |

### Time — 11 to 13 days, then 4 to 5 for hide/show

| # | Work | Issues | Days |
|---|---|---|---|
| 1 | Setup and environment | Run at the review site (`.axf`); fix 17 and the headers not reached (08, 12); verify 09 | 8–10 |
| 2 | Fixes | 10, 11, 12, 13, 14, 16, 25 | 8–10 |
| 3 | Investigate and review tool | 12; rules for 16, 17, 25; categorize the rest of the review comments (done: SWE.3 100 of 232, SWE.4 350 of 500); the review tool | 8–10 |
| 4 | Hide/show | Function visibility and editable direction (19, 21); lower priority | 4–5 |

Optimistic days. 1–3 run side by side, one person each: 8–10 days, then the last run and check (3 d):
11–13 days. 4 comes after.

### Defects — flowchart

| Issue ID | Issue | Fix | Effort | Status |
|---|---|---|---|---|
| SWE3-V4-08 | A header not reached drops a branch | 1) A `case` keeps its branch when its header is not found: fixed, to verify.<br>2) An `if` whose condition uses a value from a header not reached: to find.<br>3) Check in the review-site run (12) | 1–2 d | open |
| SWE3-V4-09 | Steps in the JSON, not in the DOCX | Very big charts were drawn only in part (the bottom blank); now drawn whole | — | to verify |
| SWE3-V4-10 | Text cluttered | Case labels piled up under the diamond.<br>1) Label in the middle of the arrow.<br>2) Constant only: `eVALUE`, not `case Type::eVALUE`.<br>3) Cases to the same box share one arrow | 1–2 d | done (branch) |
| SWE3-V4-11 | Return not joined to End | A `return` inside an extra `{ }` had an arrow to the next step.<br>1) Look inside nested `{ }` for how a branch ends.<br>2) No arrow on after `return`, `break`, `continue`, `goto`.<br>Also fixed: a `case X: { …; break; }` in braces fell into the next case; a `continue` in a `switch` case had no arrow back to its loop | 1–2 d | done (branch) |
| SWE3-V4-12 | One side of a branch missing | 1) Header not found: fixed by 08; check at the review site.<br>2) Macro off: 17.<br>3) An empty branch (an `#if` whose macro is off empties `{ }`) had no arrow: done (branch).<br>4) Other causes: to find | 1–2 d | investigate |
| SWE3-V4-13 | Wrong value on a branch | Branch labels from the code, not the LLM | 1–2 d | open |
| SWE3-V4-14 | Both branches look the same | Two boxes with different code never share a label: the pass that evens out the labels sees no code | 1 d | open |
| SWE3-V4-15 | Wording or label should change | Reviewers correct it in the app | 0 d | open: the reviewing team |

### Defects — other

| Issue ID | Issue | Fix | Effort | Status |
|---|---|---|---|---|
| SWE3-V4-01 | Class: writes to static members | Writes like `x++`, `this->s_x`, `obj.s_x` now count | — | verified |
| SWE3-V4-02 | Class: access specifier | Access no longer decides public (SWE3-UI-01.3) | — | verified |
| SWE3-V4-03 | Static diagram not sliced | The container diagram fits the page | — | verified |
| SWE3-V4-04 | Orphan header's enum in every unit | Listed once, in one unit (SWE3-UH-04) | — | verified |
| SWE3-V4-05 | Orphan header's function counted as another unit's | The header belongs to its own unit | — | verified |
| SWE3-V4-06 | Globals not in the unit headers | Globals listed (SWE3-UH-01) | — | verified |
| SWE3-V4-07 | Class: structs and classes missing | Struct, class and union listed | — | verified |

### Gaps

| Issue ID | Issue | Fix | Effort | Status |
|---|---|---|---|---|
| SWE3-V4-16 | Which files make a unit | Agree the rule, then build | 1–2 d | decide |
| SWE3-V4-17 | A macro that is off | Read each file's `-D` flags from `compile_commands.json` | 1–2 d | decide |

### As per rule

| Issue ID | Issue | What the rule gives | Planned | Status |
|---|---|---|---|---|
| SWE3-V4-18 | Need proper data dictionary | Data Range comes from the data dictionary (SWE3-UI-04) | — | — |
| SWE3-V4-19 | Public inline functions appearing | Public = another unit calls it (SWE3-UI-01) | Function visibility: Hide makes it private. BACKLOG WA-1 | lower priority |
| SWE3-V4-20 | Globals in both unit header and interface | Unit header: all symbols (SWE3-UH-01); interface: public ones (SWE3-UI-01) | — | — |
| SWE3-V4-21 | A function no other unit calls has no row or entry | Not public: no row (SWE3-UI-01); its flowchart is under its caller (SWE3-FD-01) | Function visibility: Show makes it public. BACKLOG WA-1 | lower priority |
| SWE3-V4-22 | Orphan header's enum in the wrong single unit | Listed once, in the first unit by name (SWE3-UH-04) | — | — |
| SWE3-V4-23 | Enum appears in one component | Same rule (SWE3-UH-04) | — | — |
| SWE3-V4-24 | Input name missing or incomplete | First parameter; else a global; else `<Function> input` (SWE3-FD-03) | — | — |
| SWE3-V4-25 | Direction Out for a function that changes state without writing a global | Only a global write makes a function In (SWE3-UI-05) | SWE3-UI-05 changes, 1–2 d:<br>1) In words like `set`: Delete, Insert, Backup… (config).<br>2) Writing a field of its own class counts like a global write.<br>Editable direction: BACKLOG S3-20 | decide |
