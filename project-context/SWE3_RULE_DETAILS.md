# SWE3_WIKI rule details — what the rule book leaves out

> **Project context — topic file.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md), the index.
> `docs/spec/SWE3_WIKI.md` is the rule book three teams agree on, cut to what a reviewer judges
> (2026-11-05). The details of the same output it leaves out are kept here, by its section, so none was
> lost: when a review comment touches one, the answer starts here. A rule that grows a detail a reviewer
> must judge moves it back into the wiki.

## DOC — General

- A unit key is `component|<file name without extension>`, no folder: two same-named files in one
  component's folders merge into one unit, with the path of whichever came first; the run log warns
  (`model_deriver`, "unit key … is claimed by N files"). Reported, not repaired: the key is in every id.
  It does not happen in the code under review (answered 2026-11-05), so the wiki has no rule for it.
- Introduction: 1.1 Purpose is `docx.introduction.purpose` with the project name; 1.2 Scope is
  `scopeIntro`, one bullet per component, then `scopeBody` and `scopeItems`; 1.3 Terms is a
  `Term | Description` table from the abbreviations file.
- LLM answers are cached by content and `llm.cacheVersion`; the description prompts carry the domain context.
- A reviewer's correction is carried into the next version and orphaned when the code it describes changed;
  hiding names the exact function, so one of two same-named methods can be hidden alone.

## SD — Static diagram

- Units are drawn in name order, so a picture is the same on any machine.
- File dependency diagram: a header is drawn only when a source file includes it; an `#if` condition that
  cannot be worked out counts as active; a source file's own header (same name) always counts as included,
  even with no `#include` line. `#include "…"` is looked up only from the including file's folder, not
  through the include paths -- a defect (BACKLOG S3-14).
- Unit diagram: drawn left to right; a private function has no arrow; a function published only through a
  table of function pointers draws its arrow to the unit that registers it; no arrow from a unit to itself;
  the caller's own Direction does not matter; a shared arrow's label lists all its ids, spaced apart; this
  unit has a thick border, the other units a lighter style; box labels are `Component/Unit` without the
  layer, with characters that would break the picture replaced; published globals are stacked in
  interface-id order, a class static member labelled `Owner::s_count`; `extern` declarations are not drawn.

## UH — Unit header

- A declaration is read until its brackets close (one in a comment or a string does not count); still open
  after 2000 lines, it is cut there with a warning in the run log. A `#define` keeps its `\`-joined lines.
  Nothing readable at the recorded line: the row shows the symbol's name, so no row is blank.
- `using T = …;` is a typedef. A record with no name is shown by the typedef that names it; the extra name
  in `} one_s, *one_s_2;` is dropped (the typedef row shows the line). Two same-named statics with no value
  stay two rows. A macro defined in each `#if` branch is listed once, from the active branch; when libclang
  cannot tell, every branch is kept.
- Shared (orphan) header, "used" by a unit: one of its functions uses the symbol, or the name appears in the
  unit's own source outside comments and quotes; an enum also through its value names; a global only when
  a function reads or writes it -- including the header is not enough. The owner is chosen over the whole
  project: the first using unit by name in the header's own component, else the first anywhere.
- Why declarations are shown as written: a reviewer holds the code next to the document; `PUBLIC` /
  `PRIVATE` expand to nothing but state intent, so they stay (review decision, 2026-09-23); `extern`,
  `static`, `const`, `volatile`, `inline` change what a declaration means.

## UI — Unit interface

- Which rows: a private item has no row, no arrow and no heading; its internal id `PIF_…` is never
  printed. A use through an `extern` declaration counts for the global it declares; a class static member
  used through an object (`obj.s_x`, `p->s_x`) counts; calling a function that touches a global does not
  publish the global. A call from the unit's own header is a call from the same unit.
- IDs: no layer → the project name, letters only; no group → `IF_<LAYER>_<UNIT>_<NN>`; the unit part is
  the file name, not the folder. Rows sort by the number at the end (`_99` before `_100`); at one file
  name, `.cpp` before `.h`. Headings use the interface table's name.
- Information is written from the function's source, what it calls and its callers.
- Data Type keeps `const`, `volatile`, `*` and `&` as written; an unnamed parameter shows its type alone;
  the `return:` line appears only when a return type was recorded.
- Data Range: only this layer's entries and the shared ones answer. The first that answers wins: a
  supplied CSV; what libclang measured for the build target; the built-in primitives; a lookup by name;
  `NA`. A typedef chain is followed up to 10 steps, case-sensitively (`Size_t` is not `size_t`). Every run
  prints the coverage, `data ranges: 64/65 resolved, 1 NA (int[6] x1)`.
- Direction: `SetX`, `setX`, `Module_SetX`, `SET_X`, `coreSetResult` match `set`; `Setup`, `Settings`,
  `Reset`, `offset` do not. `void *` counts as a value. A class static member is a global however it is
  reached (`Foo::s_x`, `s_x`, `this->s_x`, `obj.s_x`), whatever its access. Each decision is kept in words
  in the tool's data (`In: function name 'FtlSetEntry' contains 'Set'`), not printed.
- Source/Destination is separated by `, `; units of the same component count, the function's own unit is
  left out. Callers only, because each relationship between two units is written once, on the side that
  provides the function.

## FD — Flow diagram

- The heading is `N.1.u.k <Unit>-<Function>`. Requirements falls back to the function's name when it has
  no description. A hidden private function gets no flowchart.
- Labels: the LLM gets the box's calls, comments and the meaning of the enums, macros and typedefs it uses;
  a second pass keeps the wording consistent across the function. `Return` and `End` are drawn at the
  bottom; a loop's back arrow and its exit run in separate lanes. The picture is 4 inches wide and is split
  at blank rows.
- A header that cannot be found: a statement that uses its names stays as written; a `case X:` whose `X`
  comes from it is read from the source text; an `#if` on one of its macros is still lost.
- Names: the basic return types skipped for Output Name are `void`, `int`, `bool`, `float`, `double`,
  `char`, `short`, `long`. A name of 2 characters or fewer is dropped (Input Name → the placeholder; Output
  Name goes on to the globals). The globals include those reached through the functions it calls. The LLM
  gets the source, parameters, globals, return type and return line.

## DB — Dynamic behaviour

- The traced calls must draw at least one arrow between two units of the component. Calls back into the
  caller's component are not drawn either. Returns go back along the same chain.
