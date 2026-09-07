# SWE.3 Software Detailed Design — how it is generated (V1)

This document explains how every part of the generated design document is produced, so the rules can be
agreed before anyone judges the output. Its partner is [SWE4_WIKI.md](SWE4_WIKI.md) (unit test
specifications, built from this design). [SWE3_SPEC.md](SWE3_SPEC.md) is the short internal requirement
list; this document is the reasoning behind it.

## Contents

- [What is produced](#what-is-produced)
- [What lands in one document](#what-lands-in-one-document) — [the four levels of identity](#the-four-levels-of-identity) · [which units get a section](#which-units-get-a-section)
- [Cross-cutting rules](#cross-cutting-rules) — [public vs. private](#public-vs-private) · [names](#names) · [interface ID](#interface-id) · [data range](#data-range) · [descriptions](#descriptions-the-only-llm-written-content) · [hidden functions](#hidden-functions)
- [1 Introduction](#1-introduction)
- [N.1 Static Design](#n1-static-design)
  - [N.1.1 Component diagrams](#n11--component-diagrams)
  - [N.1.2 Component/Unit table](#n12--componentunit-table)
  - [N.1.3 Unit architecture diagram](#n13--unit-architecture-diagram) — [which edges](#which-edges-are-drawn) · [arrow direction](#arrow-direction) · [layout](#layout)
  - [N.1.4 Unit header table](#n14--unit-header-table) — [column 1 declaration](#column-1--declaration) · [column 2 information](#column-2--information) · [orphan-header symbols](#orphan-header-symbols) · [cleanup](#cleanup-and-de-duplication) · [exclusions](#exclusions)
  - [N.1.5 Unit interface table](#n15--unit-interface-table) — [which rows, in what order](#which-rows-and-in-what-order) · [1 Interface ID](#column-1--interface-id) · [2 Interface Name](#column-2--interface-name) · [3 Information](#column-3--information) · [4 Data Type](#column-4--data-type) · [5 Data Range](#column-5--data-range) · [6 Direction](#column-6--directioninout) · [7 Source/Destination](#column-7--sourcedestination) · [8 Interface Type](#column-8--interface-type)
  - [N.1.6 Per-function flowchart entry](#n16--per-function-flowchart-entry) — [which flowcharts](#which-flowcharts-appear-under-the-entry) · [how one is built](#how-a-flowchart-is-built) · [Input/Output Name](#input-name--output-name)
- [N.2 Dynamic Behaviour](#n2-dynamic-behaviour) — [which interactions qualify](#which-interactions-get-an-entry) · [the diagram](#the-diagram) · [the description table](#the-description-table)
- [Code Metrics and Appendix](#code-metrics-and-appendix)
- [Fixed and placeholder values](#fixed-and-placeholder-values)
- [Worked example](#worked-example)
- [Open items](#open-items)

---

## What is produced

One `Software Detailed Design` document per **group**. It is built from the C++ source code and the
project settings. Nothing else is needed — no requirement database, and no design notes written by hand.

```
1  Introduction
   1.1  Purpose
   1.2  Scope
   1.3  Terms, Abbreviations and Definitions
2  <Component>                              ← one top-level section per component, in A-Z order
   2.1  Static Design
        · component container diagram
        · file dependency diagram
        · Component / Unit / Description / Note table
        2.1.1  <Unit>                       ← one per unit that has a source file
               · unit architecture diagram
               2.1.1.1  unit header         ← globals / typedef / enum / define table
               2.1.1.2  unit interface      ← Interface ID / Name / Information / Data Type /
                                              Data Range / Direction / Source-Destination / Type
               2.1.1.3  <Unit>-<Function>   ← one per public function: flowchart + table
               2.1.1.4  <Unit>-<Function>
   2.2  Dynamic Behaviour
        2.2.1  <Unit> - <Function> (<CallerUnit> - <CallerFunction>)
               · description table + sequence diagram
3  <Component>  …
N  Code Metrics, Coding Rule, Test Coverage
Appendix A  Design Guideline
```

The numbers follow the position in the document. Components start at `2`. Code Metrics is always the
section after the last component.

---

## What lands in one document

### The four levels of identity

| Level | What it is | Where it comes from |
|---|---|---|
| **Layer** | Top folder of the delivery (for example `FTL`, `HIL`, `FIL`) | `layers` in the settings |
| **Group** | What one document covers — **one document per group** | `layers.<layer>.groups` |
| **Component** | A named set of folders inside a group. Each one becomes a top-level section | the group's `{name: path}` map |
| **Unit** | One source file plus its header of the same name | worked out from the file path: `<component>\|<file stem>` |

A **unit** is `Foo.cpp` **plus** `Foo.h` treated as one thing. The file extension is dropped, so both
halves share one identity and their interfaces are numbered in a single list.

If two files in different folders of the same component share a file name, they end up with the same
identity and are merged into one unit. The run prints a warning when this happens. It is not repaired
automatically, because that identity is used everywhere in the stored data, and changing it would break
everything that refers to it. **⚠ To confirm:** whether this happens at all in the client's code.

### Which units get a section

- Only units that **have a source file**. A unit that is only a header gets no section, no interface table
  and no diagram. Its content shows up inside the units that *use* it instead — see the
  [unit header table](#n14--unit-header-table).
- Only components of the selected group. Code outside the group can still appear as a *name* on a diagram
  or in the Source/Destination column, but it gets no section of its own.

---

## Cross-cutting rules

These rules decide what appears anywhere in the document, so they are worth agreeing first.

### Public vs. private

Everything the document publishes is *public*. A function counts as **private**, and is left out of the
interface table, the unit diagram and the headings, based on the first rule below that applies:

1. The source marks it `PRIVATE` → private. The marking always wins.
2. The source marks it `PUBLIC` → public. This marking is trusted too. It is what keeps an interrupt
   handler or a registered callback in the document even though nothing calls it by name.
3. Its address is put in a table at file level (`static const fp_t table[] = { fn, … };`) → public. It can
   be reached through that table, even though no call names it.
4. Otherwise: **public if a function in another file calls it**, private if not.

The `PRIVATE` and `PUBLIC` markings are macros that expand to nothing, so the compiler never sees them.
They are found by reading back up to 5 lines above the declaration in the source file.

A global variable is private only if it is marked `PRIVATE`.

Private functions are not lost. When a public function calls a private one, the private function's
flowchart is added under that public function (see [flowcharts](#n16--per-function-flowchart-entry)). It is
labelled with its **signature**, never with an id.

**⚠ To confirm:** rule 4 — "called from another file, so it is public" — is a guess for code with no
markings. In code that uses the markings, rules 1 and 2 answer everything and rule 4 never runs.

### Names

| Where | Form | Why |
|---|---|---|
| Interface Name, headings | short name with the class in front — `MapCache::insert`, `FtlLookup` | the namespace is dropped because it only makes the cell longer. The class is kept because it is what tells two same-named methods apart |
| Diagram boxes | `Component/Unit` | the layer prefix is dropped. The box is there to be read, not looked up |
| Internal keys and file names | layer included (`Ftl.Map\|FtlMap`) | two layers are allowed to have a component with the same name |

### Interface ID

```
IF_<LAYER>_<GROUP>_<UNIT>_<NN>          public   — printed in the document
PIF_<LAYER>_<GROUP>_<UNIT>_<NN>         private  — internal only, NEVER printed
```

> **The `PIF_` form never appears anywhere in the document.** Private items get no table row, no diagram
> arrow and no heading of their own, and the private flowcharts that *are* shown are labelled with the
> function signature. The id exists only inside the tool: in the stored data and the logs, where it keeps
> private items addressable and keeps their numbering apart from the published ones. It is written here
> only so the client team knows what it is if it shows up in a log file.

- Each part of the id is the name in capitals with everything that is not a letter removed. `Sample Core`
  becomes `SAMPLECORE`, `Ftl_Map` becomes `FTLMAP`. The **layer** part keeps digits too (`Layer1` becomes
  `LAYER1`); the group and unit parts do not.
- The `<GROUP>` part is left out when the component belongs to no group.
- `<NN>` is a two-digit number counted **within the unit**. Functions are numbered first, then globals.
  Each set is ordered by file name, then line number, which puts `.cpp` before `.h`. So adding public
  functions in the header adds numbers at the end instead of renumbering what is already there.
- Public and private ids are counted in **separate** lists inside the tool, so `IF_…_01` and `PIF_…_01` can
  both exist and the published numbering never has a gap.

**⚠ To confirm:** the way names are shortened. It is repeatable but it loses information — `Map` and `Map2`
both give `MAP`. If the client wants fixed-width codes, or a list of agreed component codes, this is the
one place to decide it.

### Data Range

A range is never made up for one call. It is looked up **by type name** in a single data dictionary that
is built while the code is parsed. The lookup happens in two steps.

**Step 1 — who is allowed to answer.** Only entries from the layer being documented, plus the shared
entries (built-in types, the primitive table, a project-wide CSV). A type with the same name in a
different layer is never used.

**Step 2 — the order among those entries.** The first one that has an answer wins:

1. a CSV supplied from outside (`--data-dictionary`) — this beats everything else;
2. what libclang measured for the build target — `long` is 4 bytes on Windows and 8 on Linux, which a
   fixed table cannot express;
3. the built-in table of primitives (`uint8_t` → `0-0xFF`, `bool` → `0-1`, and so on);
4. a lookup by name, for types that came from a CSV or were never parsed;
5. `NA`.

A typedef with no range of its own is followed to the type it stands for, up to 10 steps, so
`Lba_t → uint32_t` gives `0-0xFFFFFFFF`. Structs, unions, pointers and floats are `NA` on purpose.
The match is **case-sensitive**, because C++ is: `Size_t` (a struct) is not `size_t`.

Every run prints how much it managed to fill in — `data ranges: 64/65 resolved, 1 NA (int[6] x1)`. That
line is the quickest way to see what a client-supplied CSV would still need to cover.

### Descriptions (the only LLM-written content)

| Field | Without the LLM | With the LLM |
|---|---|---|
| Interface **Information** | `-` | one line describing the function or global |
| Component/Unit **Description** | the unit's own descriptions joined together, cut at 120 characters | one line summarising the unit |
| Unit header **information** for a `typedef struct` | a phrase built from the type name | one line built from the type name **and** its fields |
| Flowchart node labels | the node's own source text | a short label per node |
| Behaviour bullets | `A calls B` | `A calls B to …` (20 words at most) |
| **Input/Output Name** | worked out from the code (see [below](#n16--per-function-flowchart-entry)) | asked for only when the worked-out name was a placeholder |

Everything else in the document — ids, directions, ranges, arrows, table rows and the *shape* of every
flowchart — comes from the code alone. The same code always produces the same result. LLM answers are
cached, and the model is told what the project's domain is so the wording stays in that domain.

### Hidden functions

A function marked `hidden` is removed from the interface table, from the flowchart sub-sections and from
Dynamic Behaviour. Hiding works on the exact function, not on its name, so hiding one of two same-named
methods leaves the other one in place.

---

## 1 Introduction

| Sub-section | What it contains | Where it comes from |
|---|---|---|
| 1.1 Purpose | a paragraph from the settings, with `{project_name}` filled in | `docx.introduction.purpose` |
| 1.2 Scope | a paragraph from the settings, then **one bullet per component** in this document, then optional extra text and bullets | `docx.introduction.scopeIntro` / `scopeBody` / `scopeItems`, plus the component list |
| 1.3 Terms | a `Term \| Description` table of every abbreviation in the settings, in A-Z order | the project's abbreviations file |

Only the component bullets come from the code. The rest is standard text the client supplies.
**⚠ To confirm:** the wording of Purpose and Scope, and the abbreviation list.

---

## N.1 Static Design

### N.1.1 — Component diagrams

Every component section opens with two pictures.

**Container diagram** — the component as a yellow box with one blue box per unit inside it, and no arrows.
It answers "what is in this component". The units are listed in sorted order, so the same code always
gives the same picture on any machine.

**File dependency diagram** — drawn bottom to top: a blue box per `.cpp`, a dark box per header, and an
arrow `source → header` for every header the source includes.
- Only headers **belonging to this component** are drawn. An include of another component's header, or of
  a system header, is ignored.
- Includes are read from the file text, and `#ifdef` / `#ifndef` / `#if` / `#elif` / `#else` blocks are
  taken into account. Only the branch that is active for this build contributes arrows. If a condition
  cannot be worked out, it is treated as active, so an include is never quietly lost.
- The header with the same name as the source is always included, even if the source does not say
  `#include` for it.

### N.1.2 — Component/Unit table

One row per unit of the component that has a source file. Four columns:

| Column | What it shows | If there is nothing |
|---|---|---|
| **Component** | the component name for reading: layer prefix removed, hyphens turned back into spaces (`Layer1.Sample-Core` → `Sample Core`). Written once, in the first row, then merged down the whole column | `N/A` |
| **Unit** | the unit name (the file name without its extension) | `N/A` |
| **Description** | one line describing the unit, built from the descriptions of its **own functions and globals**, never from raw source | see below |
| **Note** | always `N/A` | — |

**How Description is filled, in order:**
1. The LLM summarises the unit from the names and descriptions of its functions and its globals. Functions
   and globals are kept as two separate lists, so a unit that is mostly data reads differently from one
   that is mostly logic. Empty descriptions and duplicates are removed first.
2. If the LLM is off, unreachable, or fails: the same descriptions joined together with duplicates removed,
   cut at 120 characters.
3. If none of the unit's items have a description: `N/A`.

**⚠ To confirm:** what should go in **Note**. It is always `N/A` today.

### N.1.3 — Unit architecture diagram

One diagram per unit, drawn left to right. **Boxes are units. Arrows are interfaces**, labelled with
interface IDs.

#### Which edges are drawn

Only the unit's **own** interfaces: for every public function of the unit, one arrow per unit that calls
it. Arrows for functions this unit *calls* are not drawn here. They are drawn in the diagram of the unit
that owns them.

This is the rule to agree on: **every relationship between two units appears exactly once in the
document, in the diagram of the unit that provides the function.**

Private functions are left out here, just as they are in the interface table, so an arrow can never carry
an id that the reader cannot find in a table.

#### Arrow direction

The direction comes from the **owner's** In/Out. The owner is the unit of the function being called. The
caller's own direction does not matter:

| Owner's Direction | Arrow |
|---|---|
| `Out` | owner → partner (data leaves the owner) |
| `In` | partner → owner (data comes into the owner) |

Because the direction is fixed by the owner and not by "this unit", the same interface is drawn as the
**same** arrow in both units' diagrams.

#### Layout

- The unit's own component is a yellow box in the middle. The current unit sits inside it with a thick
  border. Units from the same component sit beside it in a lighter style.
- Units with an arrow pointing **into** this unit are placed on the **left**.
- Units with an arrow pointing **out of** this unit are placed on the **right**.
- A unit with arrows in **both** directions is drawn **twice**, once on each side. Each box carries only
  the interface IDs of the arrow on that side.
- Several interfaces between the same two units, in the same direction, share one arrow. The label lists
  all their ids, with blank space above and below so two labels never run together.
- A unit never draws an arrow to itself.
- If a function is published only through a table of function pointers, its arrow goes to the unit that
  registers it.

When the document covers a whole group, every unit in that group counts as internal. Anything outside the
group is external.

### N.1.4 — Unit header table

Two columns. What gets listed, by kind:

| Kind | Listed when | Column 2 (`information`) |
|---|---|---|
| Global variable | declared in the unit's own files and not marked `PRIVATE` | the starting value: everything to the right of the first `=`. Brackets are counted, so a value spread over several lines is captured in full. `N/A` if there is none |
| `#define` | defined in the unit's own files | the macro value; `N/A` if it has none |
| `enum` | defined in the unit's own files | `NAME=value, NAME=value, …` |
| `typedef` | defined in the unit's own files | the enum values when it stands for an enum; a one-line description when it stands for a struct; `N/A` otherwise |

"The unit's own files" means **both** halves of the unit: its source file **and** its header.

#### Column 1 — declaration

The declaration **exactly as it is written in the source**, not rebuilt from the parsed data.

- The text is read back from the file at the recorded line. Brackets are counted, so a declaration that
  runs over several lines (a long array, a `typedef struct { … } Name;`) is captured to its end instead of
  being cut off at the first line.
- For a `#define`, the macro text the parser captured is used, including lines joined with `\`.
- If nothing readable comes back, the cell falls back to the symbol's name, so a row is never blank.
- Some declarations name more than one alias, like `} one_s, *one_s_2;`. The extra alias line is dropped,
  because the full declaration is already shown by the row that sits on the real `typedef` line.

#### Column 2 — information

The **value**, by kind, as in the table above. Two points worth agreeing:

- For a global, the value is taken from the same multi-line text as the declaration, not from a single
  line. That is what makes an array show `{ … }` instead of a stray fragment. The single-line value is
  used only as a fallback.
- For a `typedef struct`, the column holds a **one-line description** of the type instead. A struct has no
  value to print, so the cell carries meaning instead. The description is built from the type name and its
  fields, or from the name alone when the LLM is off.

#### Orphan-header symbols

An **orphan header** is a header with no source file of the same name — a header that only holds
definitions. It is not a unit, so on its own it would never appear in the document.

Its symbols are therefore listed **in the units that use them**, and only there. Each unit shows exactly
the symbols it uses, never the whole header. A header that *does* have a source file of the same name is
never pulled into another unit this way.

"Uses" is decided from two sources, and a symbol counts if **either** says so. Being slightly generous is
deliberate — better to show a symbol twice than to lose it:
1. the usage index built during parsing, which knows which functions of this unit mention the macro or
   type; and
2. a text search of the unit's own source, with comments and text in quotes removed first. This catches
   uses the index cannot see, such as a macro used as an array size, in a global's starting value, or
   inside another macro. Removing comments stops a symbol that is only *mentioned* in a comment from
   counting. An enum that is used only through its values is found by matching those value names.

#### Cleanup and de-duplication

Applied to **both** columns, in this order:

1. **Comments removed** — `//` and `/* */`, including ones spanning several lines. Text inside quotes is
   kept. A comment is never part of a declaration or of a value. Comments in other languages are removed
   the same way, not translated.
2. **Duplicates removed**, matched on the declaration text. The same declaration can arrive twice: once as
   an `enum` and once as the `typedef` that names it. The row with the more useful `name=value` information
   is kept.
3. **Sorted** by declaration text, ignoring upper/lower case.

Comments are removed before duplicates are matched, so two rows that differ only by a trailing comment
collapse into one.

#### Exclusions

Never listed: include guards (a `#define FILE_H` with no value), private globals, local variables, and
plain structs or classes. A struct reaches the table only through a `typedef`.

**Defines inside `#if` blocks:** a macro defined once in each branch is listed **once**. libclang keeps
only the branch that is active for this build, and the text search is limited to the lines it kept. If
libclang has no answer, every branch is kept, so the macro is never lost.

**Known gap:** a macro value is shown as written (`(1<<6)`), not worked out (`64`).

### N.1.5 — Unit interface table

Eight columns. Here they are at a glance; each one is then explained in full below.

| # | Column | Function row | Global variable row |
|---|---|---|---|
| 1 | **Interface ID** | `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` | same |
| 2 | **Interface Name** | short name with the class in front | short name |
| 3 | **Information** | description, or `-` | description, or `-` |
| 4 | **Data Type** | the parameter types, plus a `return:` line | the declared type |
| 5 | **Data Range** | one range per parameter, plus a `return:` line | the type's range |
| 6 | **Direction(In/Out)** | `In` or `Out` | always `In/Out` |
| 7 | **Source/Destination** | the units that **call** this function | the unit's own path |
| 8 | **Interface Type** | `Function` | `Global Variable` |

#### Which rows, and in what order

**Which rows exist**
- One row per **public function** and one per **public global** of the unit, across **both** halves of the
  unit. A public inline function in `Foo.h` sits in the same table as the functions in `Foo.cpp`.
- Private items get **no row at all**. They carry a `PIF_…` id inside the tool, but it is never printed:
  not here, not on a diagram, not in a heading (see [Interface ID](#interface-id)).
- Functions marked **hidden** are removed when the document is written. This works on the exact function,
  so hiding one of two same-named methods leaves the other one in place.
- A unit with no source file gets no table at all.

**Order**
1. Rows are collected functions first (by line number), then globals (by line number).
2. The table is then sorted by the **number at the end of the interface ID**, compared as a number, so
   `_99` comes before `_100`. Sorting by line number would go wrong as soon as a unit spans `.cpp` and
   `.h`, because the two files have their own line numbers.
3. Because ids are given out functions first and globals second, that grouping survives the sort: all
   functions, then all globals, each in id order. A row with no readable number sorts last.

The result: the ID column always reads `01, 02, 03…` with no gaps, and the order of the table is the
numbering itself.

#### Column 1 — Interface ID

```
IF_<LAYER>_<GROUP>_<UNIT>_<NN>          public   — this column
PIF_<LAYER>_<GROUP>_<UNIT>_<NN>         private  — internal only, never printed anywhere
```

- **The parts.** Each name is put in capitals and everything that is not a letter is removed:
  `Sample Core` becomes `SAMPLECORE`, `Ftl_Map` becomes `FTLMAP`. The **layer** part keeps digits as well
  (`Layer1` becomes `LAYER1`); the group and unit parts do not.
- **If there is no layer.** A component that belongs to no layer uses the **project name** in that slot.
- **If there is no group.** The group part is left out completely, giving `IF_<LAYER>_<UNIT>_<NN>`.
- **The unit part** is the file name without its extension, not the folder path.
- **`<NN>`** is a two-digit number counted **per unit**, not per file. That is what keeps `Foo.h` and
  `Foo.cpp` on one list instead of both starting again at `01` and clashing.
- **The order numbers are given out in**, inside a unit: functions first (by file name, then line, which
  puts `.cpp` before `.h`), then globals the same way. So adding public functions in the header adds
  numbers at the end instead of renumbering the ones already in use.
- **Public and private are counted separately** inside the tool, so `IF_…_01` and `PIF_…_01` can both
  exist, and the published `01, 02, 03…` never skips a number where a private function sits in the source.

**⚠ To confirm:** the shortening rule. It is repeatable but it loses information: `Map` and `Map2` both
give `MAP`, and `Sample Core` gives `SAMPLECORE`. If the client wants fixed-width codes, or an agreed list
of component codes, this is the one place to decide it.

#### Column 2 — Interface Name

- **Function:** the short name with its class in front — `MapCache::insert` for a method, `FtlLookup` for
  a plain function. The namespace is **dropped**. The class is kept because it is the only thing that
  tells two same-named methods in one unit apart.
- The class comes from what the parser recorded, not from splitting the full name. A full name cannot be
  split back into "namespace" and "class" reliably.
- If no class was recorded, the cell shows the plain short name.
- **Global:** the short name, everything after the last `::`.

Inside the tool a separate short name is kept for lookups (flowchart file names, behaviour rows). Only the
displayed cell carries the class prefix, so changing what this column shows does not break those lookups.

#### Column 3 — Information

- One line describing the function or global, or `-` when there is none.
- These descriptions come from the LLM only. With descriptions turned off, **every** Information cell is
  `-`, and the rest of the document is unaffected. No other column depends on this one.
- A description is written from the item's own source, the descriptions of what it calls, and a map of the
  repository. It can be improved by a second pass that adds the callers' context, and by a review pass for
  longer functions. Answers are cached, so a function that has not changed is not asked about again.
- Globals get their descriptions separately, from the declaration and the code around it.

**⚠ To confirm:** whether the text in this column is part of what the client checks, or whether `-` is
acceptable for V1.

#### Column 4 — Data Type

**Function rows** — two lines:

```
<type> <name>; <type> <name>; …
return: <type>
```

- One entry per parameter, **in the order they are declared**, separated by `; `. Each entry is
  `type name`. If the parameter has no recorded name, only the type is shown.
- `const`, `volatile`, `*` and `&` are kept exactly as written in the source.
- **No parameters → the cell reads `VOID`**, not an empty cell.
- The `return:` line is added **only when a return type was recorded**. A `void` return is shown as
  `VOID`, to match the no-parameter case.

**Global rows:** the declared type, as written.

#### Column 5 — Data Range

Lines up with Column 4 line for line, so the *n*-th range belongs to the *n*-th type:

```
<range>; <range>; …
return: <range>
```

- One range per parameter, in the same order, separated by `; `. **No parameters → the whole cell is
  `NA`.**
- The `return:` line holds the return type's range, or `NA` for `void` and for anything that could not be
  worked out.
- **Global rows:** the range of the declared type.
- Ranges are looked up **by type name** in the shared data dictionary, using the rules in
  [Data Range](#data-range). They are never worked out per call, and never fixed onto the parameter while
  parsing — that is what lets a client-supplied CSV override them later.
- A typedef is followed to the type it stands for, up to 10 steps, so `Lba_t → uint32_t` gives
  `0-0xFFFFFFFF`. Structs, unions, pointers and floats are `NA` on purpose, not by failure.
- Every run prints its coverage — `data ranges: 64/65 resolved, 1 NA (int[6] x1)` — naming the types that
  came back `NA`. That is exactly the list a client-supplied CSV would need to cover.

#### Column 6 — Direction(In/Out)

**Function rows** — the first rule that matches wins:

| # | Rule | Result | Notes |
|---|---|---|---|
| 1 | the name contains the whole word `set` | **In** | checked before `get`: writing wins |
| 1 | the name contains the whole word `get` | **Out** | |
| 2 | it has a return type that is not `void` | **Out** | `void *` counts as a value |
| 3 | it writes a global, itself **or** through a function it calls | **In** | |
| 3 | it reads a global and writes none | **Out** | |
| 3 | it touches no global | **Out** | a pure function |

- **Whole words, not letters.** The name is split into words across `camelCase` and `snake_case`. So
  `SetX`, `setX`, `Module_SetX`, `SET_X` and `coreSetResult` all match, while `Setup`, `Settings`,
  `Setter`, `Reset`, `offset` and `target` do not.
- **Rule 3 follows the call chain.** Before direction is decided, every function's global reads and writes
  are extended with everything the functions it calls read and write, all the way down. So a function that
  changes state only through a helper is `In`, not `Out`.
- **Each decision is recorded in words**, for example `In: function name 'FtlSetEntry' contains 'Set'
  (writes/updates state).`, `Out: returns a value (int).`, `In: writes global(s) gErrCount directly.`, or
  `In: writes global(s) gState (via cacheFlush).` Any row can be checked without reading the code. This
  text is not printed in the document today.

**Global rows:** always `In/Out`. A global can be read and written, so it is both.

**⚠ To confirm:** rule 1 also matches names like `isSet` or `hasGet`. A list of exceptions is easy to add
if the client wants one.

#### Column 7 — Source/Destination

**Function rows** list **the callers only**:

- Every **other** unit that calls this function, written `Component/Unit`, in A-Z order, separated by
  `, `.
- The function's **own unit is left out**. Units in the same component and the same group **are** included,
  so this cell matches the [unit diagram](#n13--unit-architecture-diagram).
- If a function is published through a table of function pointers, no function calls it by name, so the
  **unit that registers it** is named instead. Otherwise the cell would read `-` for a real relationship.
- **`-`** when nothing qualifies.
- The list of units this function *calls* is worked out and kept in the intermediate data, but it is **not
  printed**. Each relationship between two units is written down once, on the side that provides the
  function, and this function's calls appear in those other units' rows.

**Global rows:** the unit's own path, `Component/Unit`.

**⚠ Two things to confirm here:**
1. **Callers only.** This is the "write each relationship down once, on the provider's side" reading, and
   it is the biggest interpretation choice in this table.
2. **How the component name is written.** The layer prefix is removed, so the cell reads
   `Sample-Core/Core`, not `Layer1.Sample-Core/Core`. The layer is stated once at the front of the
   document, so repeating it in every cell only adds noise. One small difference remains: this cell keeps
   the hyphens (`Sample-Core`), while section headings turn them back into spaces (`Sample Core`).

#### Column 8 — Interface Type

One of exactly two values: `Function` or `Global Variable`. It comes from what the row *is*, so the table
can be filtered on it.

### N.1.6 — Per-function flowchart entry

One heading, `N.1.u.k <Unit>-<Function>`, per public function of the unit. Globals get no entry. Each
heading holds a table of five rows:

| Row | What it holds |
|---|---|
| **Requirements** | the function's description (or its name, if it has none), then the flowchart picture(s), each with the signature it belongs to above it |
| **Risk** | `Medium` — fixed |
| **Capacity(Density)** | `Common` — fixed |
| **Input Name** | worked out, see below |
| **Output Name** | worked out, see below |

#### Which flowcharts appear under the entry

The function's own flowchart first, then one for each **private** function it calls directly. A private
function has no heading of its own, so this is where its logic is published. Each private function is
drawn at most once per unit, under the first public function that calls it. Hidden ones are skipped. Every
picture has its signature above it, so a stack of flowcharts in one cell stays readable.

#### How a flowchart is built

The shape comes from the code; only the wording comes from the LLM.

1. libclang reads the function and builds its control-flow graph. The node kinds are `START`, `END`,
   `ACTION`, `DECISION`, `LOOP_HEAD`, `SWITCH_HEAD`, `CASE`, `DEFAULT_CASE`, `RETURN`, `BREAK`,
   `CONTINUE`, `TRY_HEAD` and `CATCH`. Arrows carry Yes/No labels.
2. Each node is given extra context: the calls it makes, the comments in it, and what the enums, macros
   and typedefs it uses actually mean.
3. A local LLM writes a short label for each node, with context about callers and callees. A second pass
   makes the wording consistent across the whole function. After that, a fixed step **puts the call names
   back**: every call in a node is written as `Name()`, and any call the label dropped is added as
   `Calls: X()`. A call can never be lost to rewording.
4. The labelled graph is drawn with Graphviz: an oval for Start and End, a diamond for a decision, a box
   for everything else. A separate step finds the loops and (a) pushes `Return` and `End` **below** the
   loop body and (b) routes the loop's back-arrow and its exit in separate lanes. That is what keeps
   **Return/End at the bottom and stops lines crossing** — both asked for by the client.
5. The picture is placed 4 inches wide. A flowchart too tall for one Word page is **split across pages**
   at blank rows, rather than shrunk until it cannot be read.

#### Input Name / Output Name

Worked out from the code first. The LLM is asked only when the result was a placeholder.

**Input Name** — the first of these that gives a name:
1. the first parameter's name;
2. the name of the first global it **writes**;
3. the name of the first global it **reads**;
4. `<Function> input` (the placeholder).

**Output Name** — the first of these that gives a name:
1. a plain name taken from the `return` line (the first word, once brackets and operators are stripped off,
   and only if it starts like a name);
2. the return **type**, if it is not one of `void`, `int`, `bool`, `float`, `double`, `char`, `short`,
   `long`;
3. the name of the first global it **writes**;
4. the name of the first global it **reads**;
5. `<Function> result` (the placeholder).

If the function returns `TRUE` or `FALSE`, the name becomes `TRUE/FALSE`, so it does not report whichever
branch happened to be read first.

**Tidying up**, applied to whatever came out: a leading `g_`, `s_` or `t_` is removed, underscores become
spaces, and the first letter is capitalised. A name of 2 characters or fewer (`i`, `x`) is thrown away as
meaningless, and the next step in the list is used instead.

The global lists used above include everything reached through the functions it calls, so state the
function touches only through a helper can still name the label. The LLM is asked for a better name **only**
when the result was a placeholder, and it is given the source, the parameters, the globals read and
written, the return type and the return line.

**⚠ To confirm:** Risk and Capacity(Density) are fixed values today — see
[Fixed and placeholder values](#fixed-and-placeholder-values).

---

## N.2 Dynamic Behaviour

One entry per **interaction**: a call coming into this component from outside, and what that call does
across the component's units.

### Which interactions get an entry

All five conditions must be true. This is the rule most worth agreeing, because it is why this section is
short on purpose:

1. The function is **public**.
2. Following its calls **inside its own component** reaches **more than one unit**. A function that only
   calls into its own unit is not an interaction.
3. It is called by at least one function in a **different component**. Exactly **one** entry is produced
   per function, using the **first** such caller.
4. The traced calls contain at least one arrow **between two units of the component**. A picture that is
   just `outside → function → return` is dropped.
5. The function is not hidden.

### The diagram

A sequence diagram with one participant per unit, grouped and coloured by component.

- The outside caller enters the target function.
- Calls are followed forward from the target, but only **within the target's own component**. Calls that
  leave the component, including calls back into the caller's component, are not drawn.
- **Calls within a single unit are skipped.** The chain is joined up across the skip, so a later
  cross-unit call is attached to the nearest function that is actually on the picture. No arrow ever
  starts from a function the reader cannot see.
- Returns are drawn back along the same chain.

### The description table

The same five rows as a flowchart entry:

| Row | What it holds |
|---|---|
| **Requirements** | `Behavior Description`, then one bullet per arrow, in the order of the diagram |
| **Risk** | `Medium` — fixed |
| **Capacity** | `Common` — fixed |
| **Input Name** | the function's Input Name |
| **Output Name** | the function's Output Name |

A call bullet reads `A calls B to <reason>` with the LLM on, and `A calls B` with it off. A return bullet
is always `B returns to A`. The heading is `<Unit> - <Function> (<CallerUnit> - <CallerFunction>)`.

---

## Code Metrics and Appendix

`N Code Metrics, Coding Rule, Test Coverage` and `Appendix A. Design Guideline` are written as headings
with placeholder text. Neither is worked out from the code today.

**⚠ To confirm:** whether metrics such as complexity, lines of code and coverage should be produced here,
or come from the client's own tools. The control-flow graphs behind the flowcharts already hold what a
complexity metric needs.

---

## Fixed and placeholder values

Everything the document states without working it out from the code, in one place. This is the agreement
list.

| Field | Value today | Why | What is needed |
|---|---|---|---|
| Risk | `Medium` | there is no risk information to read | a rule from the client, or a source |
| Capacity / Capacity(Density) | `Common` | the same | what the scale is meant to mean |
| Note (component/unit table) | `N/A` | the column's purpose is not defined | what belongs there |
| Requirements row | the description, or the behaviour bullets | there is no requirements source (SWE.1 / Polarion) yet | requirement ids to link to |
| Introduction text | from the settings | client boilerplate | the final wording |
| Code Metrics, Appendix A | placeholder text | not produced from the code | a source, or a decision to drop them |
| Information / Description cells | `-` or `N/A` when the LLM is off | the LLM is optional | whether this text is part of the acceptance check |

---

## Worked example

A component with two units, in a flash-storage layer. `FtlMap` is the unit being documented. `FtlCache` is
another unit of the same component. `HilQueue` is in a different component.

```c
// ---- layer Ftl · group Map · component FtlCore · unit FtlMap.h ----
#define MAP_ENTRY_MAX  (1024)            // used by FtlMap.cpp outside any function
typedef uint32_t Lba_t;

// ---- unit FtlMap.cpp ----
uint16_t        gEntryCount = 64;        // public global
PRIVATE uint8_t gErrCount   = 0;         // private -> not published

PRIVATE bool isValidLba(Lba_t lba);      // private -> no table row; flowchart shown under its caller
PUBLIC  int  FtlSetEntry(Lba_t lba, uint32_t ppn);   // calls FtlCacheInsert in unit FtlCache
PUBLIC  int  FtlGetPpn(Lba_t lba, uint32_t* ppnOut);
```

`HilQueue::hilFlush` calls `FtlSetEntry`, and `FtlSetEntry` calls `FtlCacheInsert` in unit `FtlCache`.

### 2.1.1.1 unit header (FtlMap)

| global variables / typedef / enum / define | information |
|---|---|
| `#define MAP_ENTRY_MAX (1024)` | `(1024)` |
| `typedef uint32_t Lba_t;` | `N/A` |
| `uint16_t gEntryCount = 64;` | `64` |

`gErrCount` is missing because it is private. `MAP_ENTRY_MAX` and `Lba_t` come from the unit's own header.
If they had been in a shared definitions header with no source file, they would appear here only because
this unit uses them, and in no other unit's table.

### 2.1.1.2 unit interface (FtlMap)

| Interface ID | Interface Name | Information | Data Type | Data Range | Direction(In/Out) | Source/Destination | Interface Type |
|---|---|---|---|---|---|---|---|
| `IF_FTL_MAP_FTLMAP_01` | `FtlSetEntry` | Stores a mapping entry for a logical block. | `Lba_t lba; uint32_t ppn`<br>`return: int` | `0-0xFFFFFFFF; 0-0xFFFFFFFF`<br>`return: -0x80000000-0x7FFFFFFF` | `In` | `HilCore/HilQueue` | Function |
| `IF_FTL_MAP_FTLMAP_02` | `FtlGetPpn` | Returns the physical page for a logical block. | `Lba_t lba; uint32_t* ppnOut`<br>`return: int` | `0-0xFFFFFFFF; NA`<br>`return: -0x80000000-0x7FFFFFFF` | `Out` | `-` | Function |
| `IF_FTL_MAP_FTLMAP_03` | `gEntryCount` | Number of populated map entries. | `uint16_t` | `0-0xFFFF` | `In/Out` | `FtlCore/FtlMap` | Global Variable |

Reading the rules off the rows:
- `FtlSetEntry` is `In` because of **rule 1** (the whole word `Set`), even though it returns `int`. The
  name is checked before the return value.
- `FtlGetPpn` is `Out` because of **rule 1** (`Get`). Rule 2 would have given the same answer.
- `Lba_t` gives `0-0xFFFFFFFF` by following the typedef. `uint32_t*` is a pointer, so `NA`.
- `FtlGetPpn` shows `-` because no *other* unit calls it. This column lists callers only.
- Source/Destination drops the layer, so it reads `HilCore/HilQueue` and not `Hil.HilCore/HilQueue` —
  see [column 7](#column-7--sourcedestination).
- `isValidLba` has no row. Its flowchart appears under whichever public function calls it, labelled
  `bool isValidLba(Lba_t lba)`. Its internal id is never printed.

### 2.1.1.3 FtlMap-FtlSetEntry

| | |
|---|---|
| Requirements | Stores a mapping entry for a logical block.<br>`int FtlSetEntry(Lba_t lba, uint32_t ppn)` + flowchart<br>`bool isValidLba(Lba_t lba)` + flowchart *(private function it calls)* |
| Risk | Medium |
| Capacity(Density) | Common |
| Input Name | `Lba` |
| Output Name | `Entry count` |

`Input Name` is the first parameter, tidied up. `Output Name` falls through to the first global the
function writes, because the return line is not a plain name.

### 2.2.1 FtlMap - FtlSetEntry (HilQueue - hilFlush)

It qualifies: public ✓, its calls reach `FtlMap` and `FtlCache` ✓, a caller in `HilCore` ✓, and there is a
cross-unit arrow inside `FtlCore` ✓.

| | |
|---|---|
| Requirements | **Behavior Description**<br>• hilFlush calls FtlSetEntry to store a flushed mapping<br>• FtlSetEntry calls FtlCacheInsert to cache the new entry<br>• FtlCacheInsert returns to FtlSetEntry<br>• FtlSetEntry returns to hilFlush |
| Risk | Medium |
| Capacity | Common |
| Input Name | `Lba` |
| Output Name | `Entry count` |

The call to `isValidLba` is not shown. It is inside the same unit, so it is skipped and the chain is
joined straight to the `FtlCache` arrow.

---

## Open items

- [ ] The way names are shortened for interface ids (capital letters only) — confirm or replace.
- [ ] Direction rule 1 also matches names like `isSet` — accept it, or agree a list of exceptions.
- [ ] Component names still differ slightly: Source/Destination keeps hyphens (`Sample-Core/Core`) while
      headings show spaces (`Sample Core`). Confirm this is acceptable.
- [ ] Source/Destination lists callers only — confirm this is the intended reading.
- [ ] Risk, Capacity and Note — real values, or agreed constants.
- [ ] Requirements traceability: there is nothing to link to until SWE.1 / Polarion is available.
- [ ] Code Metrics section — produce it here, or take it from the client's tools.
- [ ] Macro values are shown as written, not worked out (`(1<<6)`, not `64`) — confirm this is acceptable.
- [ ] Two source files with the same name in one component merge into one unit — confirm this does not
      happen in the client's code.
