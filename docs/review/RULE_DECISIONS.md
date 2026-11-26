# Rule decisions — Gap and Expected issues (reviews SWE3_V4, SWE3_V5)

To agree with the review team. Rules: [SWE3_WIKI](../spec/SWE3_WIKI.md). Issues: [issue list](issue_list.csv).
Built on branch `fix/review-rules`; the SWE3_WIKI text for it is not committed until agreed.

## Gap — no rule yet

| Issue | Problem (review comment) | Proposal | Decision |
|---|---|---|---|
| SWE3-016 | A unit is made only for a file with at least one function or global; a file with only types or macros gets none | (a) such a file is its own unit: its header's types then show there, not in another unit (SWE3-022, -023); or (b) as today, its types are listed in a unit that uses them. First check the file's code is not all under an `#if` that is off (SWE3-017) | On hold |
| SWE3-017 | Code under an `#if` whose macro is off in our run is missing | Each layer's macros start from its build's `-D` flags (`compile_commands.json` of that exact commit); a macros file wins on a name | Built, to agree |

## Expected — change the rule?

| Issue | Problem (review comment) | Rule today | Proposal | Decision |
|---|---|---|---|---|
| SWE3-025 | A function that changes state without writing a global (a setter on its class's field, Delete) shows Out. Same cause in SWE.4: Precondition, Input and Expected Results leave out the class's member variables | SWE3-UI-05: In only for `set` or a global write. SWE4_WIKI: globals only | No word list: a void function is In when it writes a member variable of its own object, or what a pointer or reference parameter points at (`pNode->length = …`) -- directly or through a local pointer (SWE3-UI-05 rows 3–4). SWE4_WIKI: a method's member variables in Precondition, Input and Expected Results, like globals | SWE.3 built, to agree. SWE.4 not done |
| SWE3-019 | Public inline functions appear in the interface table | SWE3-UI-01: public = another unit calls it | Later: Hide per function in the app | |
| SWE3-021 | A function no other unit calls has no interface row and no entry | SWE3-UI-01 | Later: Show per function in the app | |
| SWE3-029 | The interface table lists only functions called from another unit of the same component | SWE3-UI-01.2: called from any other unit, any component | Wording only: "another unit, of this component or another" | |
| SWE3-031 | A protected global, recorded private, gets no row in the unit header | SWE3-UH-01.2: a global is listed whatever its access | Need the example: a class's static member is in its class's row (expected); a plain global missing is a Defect | |

## Expected — no change

| Issue | Problem (review comment) | Rule |
|---|---|---|
| SWE3-018 | Need a proper data dictionary | SWE3-UI-04: Data Range comes from the project's data dictionary |
| SWE3-020 | Global variables are in both the unit header and the interface table | SWE3-UH-01 lists every symbol; SWE3-UI-01 lists the ones another unit uses |
| SWE3-022 | An orphan header's enum appears in the wrong single unit | SWE3-UH-04: listed once, in the first unit that uses it. Depends on SWE3-016 when the header has a source file |
| SWE3-023 | An enum appears in one component only | SWE3-UH-04. Depends on SWE3-016 when the header has a source file |
| SWE3-024 | An input name is missing or incomplete | SWE3-FD-03: first parameter; else a global; else `<Function> input` |
