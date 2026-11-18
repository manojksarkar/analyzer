# Fix plan — review issues

How each issue in [issue_list.csv](issue_list.csv) is fixed. The issue list stays as it is; this file changes
as work moves. Verdicts: [REVIEW_TRIAGE_SPEC](../spec/REVIEW_TRIAGE_SPEC.md).

- **Verdict**: Defect — the document breaks its rule · Gap — no rule covers it · As per rule — the document
  follows its rule.
- **Status**: verified (checked in the newest documents) · to verify · done (fixed on a branch, not merged) ·
  open · investigate · decide.
- **Effort**: days to find and fix one issue.

## Review SWE3_V4 (2026-11-11) and SWE3_V5 (2026-11-18)

### Summary

| Verdict | Fixed | Open | Planned | Nothing to do | Total |
|---|---|---|---|---|---|
| Defect — flowchart | 3 | 5 | — | — | 8 |
| Defect — other | 7 | 3 | — | — | 10 |
| Gap | — | 2 | — | — | 2 |
| As per rule | — | — | 3 | 7 | 10 |
| To check | — | 1 | — | — | 1 |
| **Total** | **10** | **11** | **3** | **7** | **31** |

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
| SWE3-V4-09 | Steps in the JSON, not in the DOCX | Very big charts were drawn only in part (the bottom blank); now drawn whole (no review comment found for it) | — | verified |
| SWE3-V4-10 | Text cluttered | Case labels piled up under the diamond.<br>1) Label in the middle of the arrow.<br>2) Constant only: `eVALUE`, not `case Type::eVALUE`.<br>3) Cases to the same box share one arrow | 1–2 d | verified |
| SWE3-V4-11 | Return not joined to End | A `return` inside an extra `{ }` had an arrow to the next step.<br>1) Look inside nested `{ }` for how a branch ends.<br>2) No arrow on after `return`, `break`, `continue`, `goto`.<br>Also fixed: a `case X: { …; break; }` in braces fell into the next case; a `continue` in a `switch` case had no arrow back to its loop | 1–2 d | verified |
| SWE3-V4-12 | One side of a branch missing | 1) Header not found: fixed by 08; check at the review site.<br>2) Macro off: 17.<br>3) An empty branch (an `#if` whose macro is off empties `{ }`) had no arrow: done.<br>4) Other causes: to find | 1–2 d | investigate |
| SWE3-V4-13 | Wrong value on a branch | A branch's label keeps its code's numbers and constant names; else it reads the code: `Check: retry > 3?`. Cached labels too | 1–2 d | done (branch) |
| SWE3-V4-14 | Both branches look the same | Two boxes with different code never share a label: the pass that evens out the labels now sees the code, and a clash goes back to the first-pass label or the code | 1 d | done (branch) |
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
| SWE3-V5-01 | Dynamic behaviour missing: calls through `->` | A `->` call to a method is found when its class is visible. Not found: a class only declared (its header not reached), or a function-pointer field `p->fn()` (that is V5-02).<br>1) Find which with one example.<br>2) Header not reached: the include paths, as for 08.<br>3) Log each call that is not found, with file and line: done (branch) | 0.5 d + 1 d | investigate |
| SWE3-V5-02 | Indirect dispatch call not found | A call through a function pointer (a struct field, a variable, a table) links to nothing; worse, a field named like a function links to the first function of that name.<br>1) Rule: does such a call count, and to which functions? No rule says so today, so it may be a Gap; its Rule ID is empty until then.<br>2) Link it to the functions stored in that field or table; else to the functions of the same type whose address is taken.<br>3) Never link by name when the call names a field or a variable.<br>Done (branch), 1)–3); the rule is SWE3-UI-01.6, to agree | 2–3 d | done (branch) |
| SWE3-V5-05 | Dynamic behaviour: descriptions not written by the LLM | `A calls B` without `to …` is the text without the LLM (SWE3-DB-03), used silently when: the LLM is off; one server check fails, for the whole run; neither function has a description; a call fails.<br>1) Find which: `analyzer.py llm-stats`, stage `behaviour.call_description`.<br>2) Log each fallback and its reason; check the server again, not once per run: done (branch), with 3 tries, a second round at the end of the step, and the code when neither function is described | 0.5 d + 1 d | done (branch) |

### To check

| Issue ID | Issue | Fix | Effort | Status |
|---|---|---|---|---|
| SWE3-V5-03 | A function in the interface table of a unit that calls it directly; overrides | A call to a virtual method is linked to every method of its family, the base and every override, so an override nobody calls gets callers and a row (SWE3-UI-01).<br>1) Check with one example; then its verdict.<br>2) Documents: link a call to the method it names and the overrides below it; `Base::f()` and a call on an object to that one only. Incremental runs keep the wide link | 0.5 d + 1–2 d | investigate |

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
| SWE3-V5-04 | Interface table lists only functions called from another unit of the same component | A caller in any other unit gives a row, another component's too; a caller outside the run is not seen (SWE3-UI-01) | — | — |
| SWE3-V5-06 | A protected global, recorded private, gets no row in the unit header | The unit header lists a global whatever its access (SWE3-UH-01.2); a class's static member is in the class row (SWE3-UH-01.5); a shared header's global no unit uses has none (SWE3-UH-04.2) | — | to check: which table; a plain global missing from the unit header is a Defect |
