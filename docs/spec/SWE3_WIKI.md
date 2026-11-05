# SWE.3 Software Detailed Design — the rules (V1)

Every part of the generated design document follows a numbered rule. Agree the rules first, then judge
the output against them: a review comment names the rule it is about. The partner document is
[SWE4_WIKI.md](SWE4_WIKI.md) (unit test specifications, built from this design). Which test checks
which rule: [TEST_INVENTORY.md](TEST_INVENTORY.md).

## How to use the rule ids

A rule id is `SWE3-`, the section's code and a two-digit number: `SWE3-UI-14` is rule 14 of the
unit interface. `SWE3` names the document, so a review sheet that mixes documents stays clear; SWE.4
rules would be `SWE4-…`. One rule table per section, in document order, named as the review scores
them:

| Code | Review section | What it covers |
|---|---|---|
| DOC | — | [the document as a whole](#doc--the-document-as-a-whole): what is in it, units, files, LLM text |
| INT | — | [1 Introduction](#int--introduction) |
| SD | **Static diagram** | [N.1 Static Design](#sd--static-diagram): the component's two diagrams, the Component/Unit table, each unit's architecture diagram |
| UH | **Unit header** | [the unit header table](#uh--unit-header) |
| UI | **Unit interface** | [the unit interface table](#ui--unit-interface) |
| FD | **Flow diagram** | [each public function's entry](#fd--flow-diagram): its table and flowchart(s) |
| DB | **Dynamic behaviour** | [N.2 Dynamic Behaviour](#db--dynamic-behaviour) |
| FX | — | [fixed values, Code Metrics, Appendix](#fx--fixed-values-code-metrics-appendix) |

A review scores the five named sections. A comment is counted in the section where it was made, even
when the rule it names is a DOC, INT or FX one: "functions of `x.c` are missing" in the unit interface
is a Unit interface comment on [SWE3-DOC-09](#doc--the-document-as-a-whole).

Each rule has its **ID**, the **Rule**, an **Example**, and **Looks wrong, but is expected**: what a
reader may take for a defect although the rule asks for it. ⚠ marks a rule, or a case, not agreed yet;
all of them are listed again in [Open questions](#open-questions). The short notes under some tables say
why a rule is the way it is. **An id never changes:** a new rule takes the next number of its section,
and a rule that goes stays in its table, struck through, so its number is never used again.

A review comment is one of five things:

| The comment says | It is | What happens |
|---|---|---|
| the output breaks a rule | a **defect** | the tool is fixed |
| the output follows a rule, but the reader expected something else | **as per rule** | the answer names the rule |
| the rule should be different | a **change request** | the rule is agreed again, then the tool changes |
| no rule covers the case | a **gap** | a rule is written |
| an LLM-written text is badly worded | a **wording** fix | the reviewer corrects the text in the app ([SWE3-DOC-15](#doc--the-document-as-a-whole)) |

Further down: [Worked example](#worked-example) · [Open questions](#open-questions).

---

## The document outline

```
1  Introduction
   1.1  Purpose
   1.2  Scope
   1.3  Terms, Abbreviations and Definitions
2  <Component>                              ← one per component in the document, A-Z
   2.1  Static Design
        · component container diagram
        · file dependency diagram
        · Component / Unit / Description / Note table
        2.1.1  <Unit>                       ← one per unit that has a source file
               · unit architecture diagram
               2.1.1.1  unit header         ← globals / typedef / enum / define / records
               2.1.1.2  unit interface      ← Interface ID / Name / Information / Data Type /
                                              Data Range / Direction / Source-Destination / Type
               2.1.1.3  <Unit>-<Function>   ← one per public function: table + flowchart(s)
               2.1.1.4  <Unit>-<Function>
   2.2  Dynamic Behaviour
        2.2.1  <Unit> - <Function> (<CallerUnit> - <CallerFunction>)
               · description table + sequence diagram
3  <Component>  …
N  Code Metrics, Coding Rule, Test Coverage
Appendix A  Design Guideline
```

---

## DOC — the document as a whole

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-DOC-01 | One document per component. A run that names several components together (`component:A,B`) makes one combined document for them | `software_detailed_design_<component>.docx` | — |
| SWE3-DOC-02 | The document is built from the C++ source and the project settings only: no requirement database, no hand-written design notes | — | — |
| SWE3-DOC-03 | Top-level sections in this order: 1 Introduction; one section per component, A-Z; Code Metrics; Appendix A | — | — |
| SWE3-DOC-04 | Section numbers follow the position in the document: components start at `2`, Code Metrics is the section after the last component | — | — |
| SWE3-DOC-05 | A component section holds N.1 Static Design (the component diagrams, the Component/Unit table, then one sub-section per unit) and N.2 Dynamic Behaviour | — | — |
| SWE3-DOC-06 | A unit sub-section holds, in order: the unit architecture diagram, the unit header table, the unit interface table, one entry per public function | — | — |
| SWE3-DOC-07 | A unit is a source file and the header of the same name, as one thing: `Foo.cpp` + `Foo.h` is unit `Foo` | — | a function defined in `Foo.h` sits in the same tables as those of `Foo.cpp` |
| SWE3-DOC-08 | Only a unit with a source file (`.cpp`, `.cc`, `.cxx`) gets a sub-section. A header with no source file of its own gets none; its content is listed inside one unit that uses it ([SWE3-UH-18](#uh--unit-header)) | — | "header `Types.h` has no section" |
| SWE3-DOC-09 | Files read: `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.hxx` under the component's folders. A `.c` file is not read. A file whose name contains `emul` is skipped, unless the project's settings list other name patterns to skip | — | "functions of `x.c` are missing"; "the emulator files are missing" |
| SWE3-DOC-10 | A file that two components list belongs to the first one in the settings | — | — |
| SWE3-DOC-11 | ⚠ Two source files with the same name in one component become one unit; the run prints a warning | — | — |
| SWE3-DOC-12 | Code outside the document's components appears only as a name — a box on a diagram, a unit in Source/Destination — never with a section of its own | — | — |
| SWE3-DOC-13 | The LLM writes only wording ([table below](#descriptions-the-only-llm-written-content)). Ids, rows, directions, ranges, arrows and the shape of every flowchart come from the code alone | — | two similar functions described in different words |
| SWE3-DOC-14 | The same code gives the same document: LLM answers are cached, and the LLM is told the project's domain so the wording stays in it | — | — |
| SWE3-DOC-15 | A text a reviewer corrected in the app is printed instead of the LLM's. It stays in later versions while the code it describes is unchanged | — | a text that is not what the tool first wrote |
| SWE3-DOC-16 | A function marked hidden is removed from the interface table, the function entries and Dynamic Behaviour. Hiding works on the exact function, so one of two same-named methods can be hidden alone | — | — |

**The four levels of identity**

| Level | What it is | Where it comes from |
|---|---|---|
| Layer | top folder of the delivery (for example `FTL`, `HIL`, `FIL`) | `layers` in the settings |
| Group | a named set of components inside a layer; part of every interface id | `layers.<layer>.groups` |
| Component | a named set of folders inside a group; one top-level section each | the group's `{name: path}` map |
| Unit | one source file plus its header of the same name | the file path: component and file name |

### Descriptions (the only LLM-written content)

| Text | Without the LLM | With the LLM |
|---|---|---|
| Interface **Information** ([SWE3-UI-18](#column-3--information)) | `-` | one line describing the function or global |
| Component/Unit **Description** ([SWE3-SD-09](#sd--static-diagram)) | its interface rows' descriptions joined, cut at 120 characters | one line summarising the unit |
| Unit header **information** of a struct typedef ([SWE3-UH-07](#uh--unit-header)) | a phrase built from the type name | one line from the type name **and** its fields |
| Flowchart box labels ([SWE3-FD-07](#fd--flow-diagram)) | the box's own source text | a short label per box |
| Behaviour bullets ([SWE3-DB-08](#db--dynamic-behaviour)) | `A calls B` | `A calls B to …` (20 words at most) |
| Input / Output Name ([SWE3-FD-12](#fd--flow-diagram)) | worked out from the code | asked for only when the worked-out name is a placeholder |

---

## INT — Introduction

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-INT-01 | 1.1 Purpose: a paragraph from the settings (`docx.introduction.purpose`), with the project name filled in | — | — |
| SWE3-INT-02 | 1.2 Scope: the settings' paragraph (`scopeIntro`), then one bullet per component in this document, then the settings' extra text and bullets (`scopeBody`, `scopeItems`) | — | — |
| SWE3-INT-03 | 1.3 Terms: a `Term` \| `Description` table of every abbreviation in the project's abbreviations file, A-Z | — | — |
| SWE3-INT-04 | ⚠ Only the component bullets come from the code; the rest is standard text from the settings, its wording still to be agreed | — | — |

---

## SD — Static diagram

The pictures and the table of N.1 Static Design: at the top of every component, its two diagrams and
the Component/Unit table; in every unit, its architecture diagram.

### Component diagrams

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-SD-01 | Container diagram: the component as a yellow box, one blue box per unit inside it, no arrows. Units are in sorted order, so the same code gives the same picture on any machine | — | — |
| SWE3-SD-02 | File dependency diagram, drawn bottom to top: a blue box per source file, a dark box per header, an arrow source → header for every header the source includes | — | — |
| SWE3-SD-03 | Only headers of this component are drawn. An include of another component's header, or of a system header, is not | — | "the include of `Hil.h` is missing" |
| SWE3-SD-04 | An include inside `#if` / `#ifdef` / `#ifndef` / `#elif` / `#else` counts only when its branch is active for this build. A condition that cannot be worked out counts as active, so an include is never lost quietly | — | — |
| SWE3-SD-05 | A source file's own header (same name) is always drawn as included, even with no `#include` line | — | — |

### Component/Unit table

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-SD-06 | The Component/Unit table has one row per unit with a source file, in four columns: Component, Unit, Description, Note | — | — |
| SWE3-SD-07 | Component: the name for reading — layer prefix removed, hyphens back to spaces (`Layer1.Sample-Core` → `Sample Core`) — written once, in the first row, and merged down the column | — | — |
| SWE3-SD-08 | Unit: the file name without its extension | `FtlMap` | — |
| SWE3-SD-09 | Description: one line from the LLM, summarising the descriptions of the unit's **public** functions and globals — its interface rows — kept as two lists, duplicates and blanks removed; never the raw source. LLM off or failing: those descriptions joined with `; `, cut at 120 characters. No description at all: `N/A` | — | a sentence cut short when the LLM is off; `N/A` for a unit with no public item |
| SWE3-SD-10 | ⚠ Note: always `N/A` ([SWE3-FX-03](#fx--fixed-values-code-metrics-appendix)) | — | — |

### Unit architecture diagram

One diagram per unit. **Boxes are units, arrows are interfaces.**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-SD-11 | One diagram per unit with a source file, drawn left to right. Each arrow is labelled with its interface id(s) | — | — |
| SWE3-SD-12 | Only the unit's **own** interfaces are drawn: for each public function of the unit, an arrow to each unit that calls it | `HilQueue` calls `FtlSetEntry` → an arrow in `FtlMap`'s diagram | "the call from `FtlMap` to `FtlCache` is missing" — it is in `FtlCache`'s diagram |
| SWE3-SD-13 | So each relationship between two units appears once in the document: in the diagram of the unit that provides the function | — | — |
| SWE3-SD-14 | A private function has no arrow, so an arrow never carries an id the reader cannot find in a table | — | — |
| SWE3-SD-15 | The arrow's direction is the providing function's Direction ([SWE3-UI-27…SWE3-UI-29](#column-6--directioninout)): `Out` points from the provider to the caller, `In` from the caller to the provider. The caller's own direction does not matter | `FtlSetEntry` is `In`: `HilQueue` → `FtlMap` | an arrow that points against the call |
| SWE3-SD-16 | Interfaces between the same two units in the same direction share one arrow; its label lists all their ids, spaced so labels never run together | — | — |
| SWE3-SD-17 | A function published only through a table of function pointers draws its arrow to the unit that registers it | — | — |
| SWE3-SD-18 | A unit never draws an arrow to itself | — | — |
| SWE3-SD-19 | Layout: a yellow component box in the middle holds this unit (thick border) and the units of the document's components that share an arrow with it (lighter style). Units of other components are drawn outside the box. A unit with no arrow to this one is not drawn | — | "unit `FtlLog` of the same component is missing" — it shares no interface |
| SWE3-SD-20 | Inside the box and outside it alike, a unit whose arrow points **into** this unit comes before it (left); one whose arrow points **out of** it comes after it (right). A unit with arrows both ways is drawn twice, each box with the ids of its own arrow | — | "a unit is drawn twice" |
| SWE3-SD-21 | The unit's own **published** globals (those with an interface row) are boxes with **no arrows** — a global is always `In/Out` — stacked above the unit in interface-id order, labelled with the name (`Owner::s_count` for a class static member) | — | "the global has no arrow" |
| SWE3-SD-22 | Other units' globals, private globals and `extern` declarations are not drawn | — | "the global this unit reads is missing" |
| SWE3-SD-23 | Box labels are `Component/Unit`, the layer dropped. A character that would break the picture is replaced | — | — |

---

## UH — Unit header

Section N.1.4: two columns, `declaration` and `information`. The table says what the unit **declares**,
not what it publishes.

**What is listed**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UH-01 | One row per symbol declared in the unit's own files (source **and** header): globals (`extern` declarations too), `#define`s, enums, typedefs, `using` aliases, structs, classes, unions. Functions are not listed here — they are in the interface table | — | an `extern int g_x;` row: the unit uses a global another unit owns |
| SWE3-UH-02 | Access and markings change nothing: a class with private members, a `PRIVATE` global, a file-scope `static` global — all are listed | `PRIVATE uint8_t gErrCount = 0;` listed | "a private item is listed" |
| SWE3-UH-03 | ⚠ A symbol of the unit's own files is listed whether or not the unit uses it. The use test applies to orphan headers only ([SWE3-UH-20](#uh--unit-header)) | — | "an unused define is listed" |

**Column 2 — information**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UH-04 | Global: its starting value, everything right of the first `=` (brackets counted); `N/A` if it has none | `int g_cnt = 0;` → `0` | `N/A` for a global with no initialiser |
| SWE3-UH-05 | `#define`: the value as written; `N/A` if it has none | `#define N (1<<6)` → `(1<<6)` | ⚠ not worked out to `64` |
| SWE3-UH-06 | enum, and typedef of an enum: `NAME=value, NAME=value, …` | `IDLE=0, BUSY=1` | — |
| SWE3-UH-07 | typedef of a struct: one line describing it, from its name and its fields (from the name alone when the LLM is off) | — | — |
| SWE3-UH-08 | struct, class, union: one line — `Structure for …`, `Class for …`, `Union for …` | — | — |
| SWE3-UH-09 | `using T = …;` is treated as a typedef. Any other typedef: `N/A` | `typedef uint32_t Lba_t;` → `N/A` | — |

**Column 1 — declaration**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UH-10 | The declaration exactly as written in the source, markings and keywords included — never rebuilt from parsed data | `PUBLIC int g_res = 0;` | "`PUBLIC` should be removed" |
| SWE3-UH-11 | A declaration over several lines is read to its closing bracket (a bracket in a comment or string does not count). One still open after 2000 lines is cut there, with a warning in the run log | a long array or `typedef struct {…} S;` in full | — |
| SWE3-UH-12 | `#define`: the macro text, lines joined with `\` included | — | — |
| SWE3-UH-13 | Nothing readable at the recorded line: the symbol's name, so a row is never blank | — | a row showing a bare name |
| SWE3-UH-14 | In `} one_s, *one_s_2;` the extra alias is dropped; the `typedef` row already shows the full declaration | — | "alias `one_s_2` is missing" |

**Records — struct, class, union**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UH-15 | The row holds the declaration as written: data members (static or not), access labels, base classes, and methods as **declarations** — an inline body is cut to its declaration | `int status() { return 1; }` → `int status();` | "the method body is missing" — it is in the flowchart |
| SWE3-UH-16 | A type declared inside a record (enum, typedef, struct, union, using) has no row of its own: the record's row declares it | — | "the nested enum is missing" |
| SWE3-UH-17 | A static member's definition in the `.cpp` (`int Foo::s_count = 0;`) is not listed: the class row declares the member. Its starting value is therefore not shown | — | "the initial value of `s_count` is missing" |

**Orphan headers** — a header with no source file of the same name

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UH-18 | Its symbols are listed in **one** unit only, the header's owner: the first unit by name, in the header's own component, that uses anything of it; if none there, the first using unit anywhere | `SharedDefs.h` is listed in `Core` only | "the enum is missing in unit B" — it is in unit A |
| SWE3-UH-19 | The owner lists every symbol of the header that **any** unit uses, including ones only other units use. A symbol no unit uses is listed nowhere | — | "a define of the header is missing" — nobody uses it |
| SWE3-UH-20 | Used means: the parse saw it used by one of the unit's functions, or its name appears in the unit's own source outside comments and quotes. An enum also counts through its value names. A global counts only when a function of the unit reads or writes it — including the header is not enough | — | — |
| SWE3-UH-21 | The owner is chosen over the whole project, so the header is listed in the same unit in every document — maybe in another component's document | — | "the shared enum is not in this document" |

**Cleanup and exclusions**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UH-22 | Comments (`//`, `/* */`, over several lines too) are removed from both columns; text inside quotes is kept | — | "the comment is missing" |
| SWE3-UH-23 | A declaration that arrives twice (as an enum and as the typedef naming it) is listed once, with the more useful `name=value` information. One variable declared in two files (`extern int g_x;`, `int g_x = 0;`) is listed once, as the one with the value. Two same-named statics without a value stay separate | — | — |
| SWE3-UH-24 | Rows are sorted by declaration text, ignoring case | `#define …` before `typedef …` | "rows are not in code order" |
| SWE3-UH-25 | Never listed: include guards (`#define FILE_H` with no value), local variables, anonymous records (the typedef that names one carries it) | — | "`FTL_H` is missing" |
| SWE3-UH-26 | A macro defined once in each branch of an `#if` is listed once, from the branch active for this build. If libclang has no answer, every branch is kept, so the macro is never lost | — | — |

Why the declaration is shown as written (SWE3-UH-10): a reviewer holds the code next to the document. The
project markings (`PUBLIC`, `PRIVATE`) expand to nothing, but they state intent, so they stay (decided
in review, 2026-09-23). `extern`, `static`, `const`, `volatile` and `inline` change what a declaration
means. None of this reaches the interface table, which shows a name and a type only.

---

## UI — Unit interface

Section N.1.5. One row per interface of the unit:

| # | Column | Function row | Global variable row |
|---|---|---|---|
| 1 | **Interface ID** | `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` | same |
| 2 | **Interface Name** | short name with the class in front | short name |
| 3 | **Information** | description, or `-` | description, or `-` |
| 4 | **Data Type** | the parameters, plus a `return:` line | the declared type |
| 5 | **Data Range** | one range per parameter, plus a `return:` line | the type's range |
| 6 | **Direction(In/Out)** | `In` or `Out` | always `In/Out` |
| 7 | **Source/Destination** | the units that **call** it | the unit's own `Component/Unit` |
| 8 | **Interface Type** | `Function` | `Global Variable` |

### Which rows — public and private

**One rule decides what is public: something in another unit uses it.**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-01 | One table per unit with a source file, the eight columns above on every row. A unit with no source file has no table | — | — |
| SWE3-UI-02 | One row per **public** function and **public** global of the unit, from both halves (`.cpp` and `.h`) | — | — |
| SWE3-UI-03 | A function is public when a function in **another unit** calls it, or its address sits in a file-level table (`static const fp_t table[] = { fn, … };`). A call from the unit's own header is a call from the same unit | — | "`PUBLIC` function `main` is missing" — no other unit calls it |
| SWE3-UI-04 | A global is public when a function in **another unit** reads or writes it. A use through an `extern` declaration counts for the global it declares; so does a class static member used through an object (`obj.s_x`, `p->s_x`). Calling a function that touches the global does not count | `Lib` reads `g_sharedTick` through `SharedDefs.h` → `Core`'s global has a row | "global `g_result` is missing" — only its own unit uses it |
| SWE3-UI-05 | **No marking decides.** `PUBLIC`, `PRIVATE`, `PROTECTED` and the C++ `public:`, `protected:`, `private:` are ignored | `coreGetCount` is `PROTECTED`, called by `App/Main` → it has a row | "a private function is in the table" |
| SWE3-UI-06 | A file-scope `static` variable never has a row: nothing outside its file can name it. An `extern` declaration has none either: the defining unit's row stands for it (the unit header lists the `extern` line) | — | "the global this unit declares `extern` has no row here" |
| SWE3-UI-07 | A private item has no row, no arrow and no heading. Its internal id `PIF_…` is never printed; it exists only in the tool's data and logs | — | — |
| SWE3-UI-08 | ⚠ The answer depends on what was parsed: an entry point nothing calls by name (an ISR, a registered callback) is private unless a table holds its address, and a run of one layer cannot see the layer above calling in | — | "the ISR is missing" |
| SWE3-UI-09 | Types and macros are never rows: they are in the unit header table | — | — |

### Order

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-10 | Functions first, then globals, each in interface-id order (by the number at the end, so `_99` before `_100`). The id column reads `01, 02, 03…` with no gap | — | "rows are not in source order" — `.h` and `.cpp` have their own line numbers |

### Column 1 — Interface ID

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-11 | `IF_<LAYER>_<GROUP>_<UNIT>_<NN>`. Each part is the name in capitals with every character that is not a letter removed; the layer part keeps its digits | `Sample Core` → `SAMPLECORE`, `Ftl_Map` → `FTLMAP`, `Layer1` → `LAYER1` | ⚠ `Map` and `Map2` both give `MAP` |
| SWE3-UI-12 | No layer: the project name takes its place, letters only. No group: the group part is left out (`IF_<LAYER>_<UNIT>_<NN>`). The unit part is the file name, not the folder path | — | — |
| SWE3-UI-13 | `<NN>` is two digits counted **per unit**, `.h` and `.cpp` on one list: functions first, ordered by file name then line (`.cpp` before `.h`), then globals the same way. Private items are counted apart, so the printed numbers never skip | — | — |
| SWE3-UI-14 | ⚠ Units whose ids would read the same (`Map`, `Map2`) share one count, so no id is printed twice: `Map` takes `_01`, `_02`, `Map2` goes on at `_03` | — | `Map2` starting at `_03` |
| SWE3-UI-15 | An id is a position: when a function becomes public, each later id of its unit grows by one | — | "ids changed between versions" |

### Column 2 — Interface Name

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-16 | Function: the short name with its class in front; the namespace is dropped. Global: the name after the last `::`. Headings use the same name | `MapCache::insert`, `FtlLookup` | "the namespace is missing" |
| SWE3-UI-17 | Two functions of one unit never print alike: overloads add their parameter types, one name in two namespaces adds its scope. Every other name prints plainly | `FtlRead(Lba_t)`, `FtlRead(Lba_t, uint32_t)`; `fast::init` | a name with brackets |

### Column 3 — Information

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-18 | One line describing the function or global, written by the LLM from its source, what it calls and its callers; `-` when there is none. With the LLM off every cell is `-`, and no other column changes | — | ⚠ `-` |

### Column 4 — Data Type

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-19 | Function: the parameters as `type name; type name; …` in declared order (the type alone when a parameter has no name), then a line `return: <type>`. `const`, `volatile`, `*` and `&` are kept as written | `Lba_t lba; uint32_t ppn` / `return: int` | — |
| SWE3-UI-20 | No parameters: `VOID`. A `void` return: `return: VOID`. The `return:` line appears only when a return type was recorded | — | — |
| SWE3-UI-21 | Global: the declared type as written | `uint16_t` | — |

### Column 5 — Data Range

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-22 | One range per Data Type line, in the same order: `range; range; …`, then `return: range` (`NA` for `void`). No parameters: `NA` | `0-0xFFFFFFFF; 0-0xFFFFFFFF` / `return: -0x80000000-0x7FFFFFFF` | — |
| SWE3-UI-23 | A range is looked up **by type name** in one data dictionary, never made up per function. Only this layer's entries and the shared ones answer; a type of the same name in another layer is never used | — | — |
| SWE3-UI-24 | The first that answers wins: a supplied CSV; what libclang measured for the build target; the built-in table of primitives; a lookup by name; `NA` | `uint8_t` → `0-0xFF`, `bool` → `0-1` | "`long` has a different range on another machine" — 4 bytes on Windows, 8 on Linux |
| SWE3-UI-25 | A typedef with no range of its own follows the type it stands for, up to 10 steps. The match is case-sensitive, as C++ is | `Lba_t` → `uint32_t` → `0-0xFFFFFFFF`; `Size_t` is not `size_t` | — |
| SWE3-UI-26 | Structs, unions, pointers and floats are `NA` on purpose | `uint32_t*` → `NA` | "the range is missing" |

Every run prints how many ranges it filled in — `data ranges: 64/65 resolved, 1 NA (int[6] x1)` — which
names the types a supplied CSV would still need to cover.

### Column 6 — Direction(In/Out)

A function's Direction is decided by the first of SWE3-UI-27, SWE3-UI-28, SWE3-UI-29 that matches.

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-27 | The name contains the whole word `set` → `In`; otherwise the whole word `get` → `Out`. The name is split into words across camelCase and snake_case | `SetX`, `setX`, `Module_SetX`, `SET_X`, `coreSetResult` match; `Setup`, `Settings`, `Reset`, `offset` do not | `FtlSetEntry` is `In` though it returns `int`; ⚠ `isSet` matches too |
| SWE3-UI-28 | Otherwise, a return type that is not `void` → `Out` (`void *` counts as a value) | `int bump() { s_count++; return s_count; }` → `Out` | ⚠ "it writes a global, so it should be `In`" |
| SWE3-UI-29 | Otherwise: writes a global, itself or through any function it calls → `In`; only reads, or touches none → `Out`. A class static member is a global however it is reached (`Foo::s_x`, `s_x`, `this->s_x`, `obj.s_x`), whatever its access | a `void` function that changes state only through a helper → `In` | — |
| SWE3-UI-30 | Global rows: always `In/Out` | — | — |

Each decision is kept in words in the tool's data — `In: function name 'FtlSetEntry' contains 'Set'`,
`Out: returns a value (int).`, `In: writes global(s) gState (via cacheFlush).` — so any row can be checked
without reading the code. It is not printed in the document.

### Column 7 — Source/Destination

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-31 | Function: every **other** unit that calls it, as `Component/Unit`, A-Z, separated by `, `. Units of the same component count; the function's own unit is left out. It matches the unit diagram (SWE3-SD-12) | `HilCore/HilQueue` | ⚠ "a unit it calls is missing" — callers only |
| SWE3-UI-32 | Published only through a pointer table: the unit that registers it. Nothing qualifies: `-` | — | — |
| SWE3-UI-33 | ⚠ The layer prefix is dropped and hyphens are kept | `Sample-Core/Core` | the heading says `Sample Core` |
| SWE3-UI-34 | Global: the unit's own `Component/Unit` | `FtlCore/FtlMap` | — |

Why callers only (SWE3-UI-31): each relationship between two units is written down once, on the side that
provides the function. A function's calls appear in the rows of the units it calls.

### Column 8 — Interface Type

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-UI-35 | `Function` or `Global Variable`, from what the row is | — | — |

---

## FD — Flow diagram

Section N.1.6: one heading per public function, with a table and its flowchart(s).

**The entry**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-FD-01 | One heading `N.1.u.k <Unit>-<Function>` per public function ([SWE3-UI-03](#which-rows--public-and-private)), named as in the interface table; each overload has its own. Globals get none | `FtlMap-FtlSetEntry` | "private function `isValidLba` has no heading" |
| SWE3-FD-02 | Under it, a table of five rows: Requirements, Risk, Capacity(Density), Input Name, Output Name | — | — |
| SWE3-FD-03 | Requirements: the function's description (its name if it has none), then its flowchart picture(s), each with its signature above it | — | — |
| SWE3-FD-04 | After the function's own flowchart comes one for each **private** function it calls directly. Each private function is drawn once per unit, under the first public function that calls it; hidden ones are skipped | `bool isValidLba(Lba_t lba)` + flowchart under `FtlSetEntry` | "`isValidLba`'s flowchart sits under another function"; ⚠ a private function called only by another private function has no flowchart |
| SWE3-FD-05 | Risk `Medium`, Capacity(Density) `Common`: fixed values ([SWE3-FX-01](#fx--fixed-values-code-metrics-appendix)) | — | ⚠ the same value on every function |

**The flowchart**

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-FD-06 | The shape comes from the code: libclang reads the function and builds its control flow. An oval for Start and End, a diamond for a decision, a box for everything else; Yes/No on a decision's arrows | — | — |
| SWE3-FD-07 | The LLM writes only the box labels, with the box's calls, comments and the meaning of the enums, macros and typedefs it uses as context; a second pass keeps the wording consistent across the function. Without the LLM, a box shows its own source text | — | — |
| SWE3-FD-08 | Every call in a box is written `Name()`, and a call the label dropped is added as `Calls: X()`, so no call is lost to rewording | — | a `Calls: X()` line |
| SWE3-FD-09 | `Return` and `End` are drawn at the bottom; a loop's back arrow and its exit run in separate lanes, so lines do not cross | — | — |
| SWE3-FD-10 | A header that cannot be found removes no branch: a statement that uses its names stays as written, and a `case X:` whose `X` comes from it is read from the source text. Still lost: a `#if` branch on a macro of the missing header. The run log names every header not found | — | — |
| SWE3-FD-11 | The picture is 4 inches wide. One too tall for a page is split across pages at blank rows, not shrunk | — | a flowchart over two pages |

**Input Name and Output Name** — worked out from the code; the LLM is asked only for a placeholder

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-FD-12 | Input Name: the first parameter's name. A function with no named parameter: the first global it writes, else the first global it reads. Nothing found: `<Function> input` | `lba` → `Lba` | — |
| SWE3-FD-13 | Output Name, the first that gives a name: a plain name from the `return` line; the return type, unless `void`, `int`, `bool`, `float`, `double`, `char`, `short` or `long`; the first global it writes; the first global it reads; `<Function> result`. A function returning `TRUE` or `FALSE` gets `TRUE/FALSE` | — | — |
| SWE3-FD-14 | Tidying: a leading `g_`, `s_` or `t_` is removed, underscores become spaces, the first letter is a capital. A name of 2 characters or fewer is dropped: the Input Name becomes the placeholder, the Output Name goes on to the globals. The globals include those reached through the functions it calls | `g_entry_count` → `Entry count` | `Scale input` for `scale(int x)`, with the LLM off |
| SWE3-FD-15 | Only a placeholder (`<Function> input`, `<Function> result`) is sent to the LLM for a better name, with the source, parameters, globals, return type and return line | — | — |

---

## DB — Dynamic behaviour

Section N.2: one entry per **interaction** — a call coming into the component from outside, and what it
does across the component's units.

| ID | Rule | Example | Looks wrong, but is expected |
|---|---|---|---|
| SWE3-DB-01 | A function gets an entry only when all five hold: it is public; its calls inside its own component reach more than one unit; a function in a **different component** calls it; the traced calls hold at least one arrow between two units of the component; it is not hidden | — | "public function `FtlGetPpn` has no entry" — no other component calls it |
| SWE3-DB-02 | One entry per function, for its first caller from another component | — | "the second caller has no entry" |
| SWE3-DB-03 | Heading: `<Unit> - <Function> (<CallerUnit> - <CallerFunction>)` | `FtlMap - FtlSetEntry (HilQueue - hilFlush)` | — |
| SWE3-DB-04 | A sequence diagram: one participant per unit, grouped and coloured by component; the outside caller enters the function | — | — |
| SWE3-DB-05 | Calls are followed only inside the function's component. Calls that leave it, back into the caller's component too, are not drawn | — | "the call into `HilCore` is missing" |
| SWE3-DB-06 | Calls within one unit are skipped, and the chain is joined across them, so no arrow starts from a function not on the picture. Returns go back along the same chain | — | "the call to `isValidLba` is missing" |
| SWE3-DB-07 | The table: Requirements (`Behavior Description`, then one bullet per arrow in diagram order), Risk `Medium`, Capacity `Common`, Input Name and Output Name (the function's, SWE3-FD-12, SWE3-FD-13) | — | — |
| SWE3-DB-08 | A call bullet reads `A calls B to <reason>` with the LLM (20 words at most), `A calls B` without. A return bullet is always `B returns to A` | — | — |

---

## FX — Fixed values, Code Metrics, Appendix

Everything the document states without working it out from the code, in one place: the agreement list.

| ID | Field | Value today | What is needed |
|---|---|---|---|
| SWE3-FX-01 | ⚠ Risk (function and behaviour tables) | `Medium` | a rule, or a source of risk information |
| SWE3-FX-02 | ⚠ Capacity, Capacity(Density) | `Common` | what the scale means |
| SWE3-FX-03 | ⚠ Note (Component/Unit table) | `N/A` | what belongs there |
| SWE3-FX-04 | ⚠ Requirements row | the description, or the behaviour bullets | requirement ids to link to (SWE.1 / Polarion) |
| SWE3-FX-05 | ⚠ Introduction text | from the settings | the final wording (SWE3-INT-04) |
| SWE3-FX-06 | ⚠ `N Code Metrics, Coding Rule, Test Coverage` | a heading with placeholder text | made here — the control-flow graphs already hold what a complexity metric needs — or taken from the project's own tools |
| SWE3-FX-07 | ⚠ `Appendix A Design Guideline` | a heading with placeholder text | a source, or a decision to drop it |
| SWE3-FX-08 | ⚠ LLM-written cells with the LLM off | `-` or `N/A` | whether this text is part of the acceptance check |

---

## Worked example

A component `FtlCore` with two units, in layer `Ftl`, group `Map`. `FtlMap` is the unit documented;
`FtlCache` is another unit of the component; `HilQueue` is in another component, `HilCore`.

```c
// ---- unit FtlMap.h ----
#define MAP_ENTRY_MAX  (1024)            // used by FtlMap.cpp outside any function
typedef uint32_t Lba_t;

// ---- unit FtlMap.cpp ----
uint16_t        gEntryCount = 64;        // read by FtlCache -> public
PRIVATE uint8_t gErrCount   = 0;         // used only in this unit -> not public

PRIVATE bool isValidLba(Lba_t lba);      // called only in this unit -> no row; flowchart under its caller
PUBLIC  int  FtlSetEntry(Lba_t lba, uint32_t ppn);   // called by HilQueue; calls isValidLba, FtlCacheInsert
PUBLIC  int  FtlGetPpn(Lba_t lba, uint32_t* ppnOut); // called by FtlCache
```

### 2.1.1.1 unit header (FtlMap)

| declaration | information |
|---|---|
| `#define MAP_ENTRY_MAX (1024)` | `(1024)` |
| `PRIVATE uint8_t gErrCount = 0;` | `0` |
| `typedef uint32_t Lba_t;` | `N/A` |
| `uint16_t gEntryCount = 64;` | `64` |

- `gErrCount` is listed though it is private, with its marking (SWE3-UH-02, SWE3-UH-10).
- Comments are gone (SWE3-UH-22); rows are sorted by their text (SWE3-UH-24).
- The functions are not here; they are in the interface table (SWE3-UH-01).

### 2.1.1.2 unit interface (FtlMap)

| Interface ID | Interface Name | Information | Data Type | Data Range | Direction(In/Out) | Source/Destination | Interface Type |
|---|---|---|---|---|---|---|---|
| `IF_FTL_MAP_FTLMAP_01` | `FtlSetEntry` | Stores a mapping entry for a logical block. | `Lba_t lba; uint32_t ppn`<br>`return: int` | `0-0xFFFFFFFF; 0-0xFFFFFFFF`<br>`return: -0x80000000-0x7FFFFFFF` | `In` | `HilCore/HilQueue` | Function |
| `IF_FTL_MAP_FTLMAP_02` | `FtlGetPpn` | Returns the physical page for a logical block. | `Lba_t lba; uint32_t* ppnOut`<br>`return: int` | `0-0xFFFFFFFF; NA`<br>`return: -0x80000000-0x7FFFFFFF` | `Out` | `FtlCore/FtlCache` | Function |
| `IF_FTL_MAP_FTLMAP_03` | `gEntryCount` | Number of populated map entries. | `uint16_t` | `0-0xFFFF` | `In/Out` | `FtlCore/FtlMap` | Global Variable |

- `FtlSetEntry` and `FtlGetPpn` have rows because another unit calls them; `PUBLIC` did not decide it
  (SWE3-UI-03, SWE3-UI-05). `isValidLba` and `gErrCount` have none (SWE3-UI-07).
- `FtlSetEntry` is `In` by SWE3-UI-27 (the word `Set`), though it returns `int`: the name is checked first.
  `FtlGetPpn` is `Out` by SWE3-UI-27 (`Get`).
- Functions take `_01`, `_02`, the global `_03` (SWE3-UI-13).
- `Lba_t` gives `0-0xFFFFFFFF` through the typedef (SWE3-UI-25); `uint32_t*` is a pointer, so `NA` (SWE3-UI-26).
- Source/Destination names the callers, without the layer (SWE3-UI-31, SWE3-UI-33).

### 2.1.1.3 FtlMap-FtlSetEntry

| | |
|---|---|
| Requirements | Stores a mapping entry for a logical block.<br>`int FtlSetEntry(Lba_t lba, uint32_t ppn)` + flowchart<br>`bool isValidLba(Lba_t lba)` + flowchart *(the private function it calls, SWE3-FD-04)* |
| Risk | Medium |
| Capacity(Density) | Common |
| Input Name | `Lba` |
| Output Name | `Entry count` |

Input Name is the first parameter, tidied (SWE3-FD-12, SWE3-FD-14). Output Name falls through to the first global
the function writes, `gEntryCount`, because the return line is not a plain name and `int` is skipped (SWE3-FD-13).

### 2.2.1 FtlMap - FtlSetEntry (HilQueue - hilFlush)

It qualifies (SWE3-DB-01): public ✓, its calls reach `FtlMap` and `FtlCache` ✓, a caller in `HilCore` ✓, a
cross-unit arrow inside `FtlCore` ✓. `FtlGetPpn` does not: its only caller is in its own component.

| | |
|---|---|
| Requirements | **Behavior Description**<br>• hilFlush calls FtlSetEntry to store a flushed mapping<br>• FtlSetEntry calls FtlCacheInsert to cache the new entry<br>• FtlCacheInsert returns to FtlSetEntry<br>• FtlSetEntry returns to hilFlush |
| Risk | Medium |
| Capacity | Common |
| Input Name | `Lba` |
| Output Name | `Entry count` |

The call to `isValidLba` is not drawn: it stays inside `FtlMap`, so it is skipped and the chain joins
straight to the `FtlCache` arrow (SWE3-DB-06).

---

## Open questions

Each ⚠ above, by rule:

| Rule | Open question |
|---|---|
| SWE3-DOC-11 | Two source files with the same name in one component merge into one unit — does that happen in the code under review? |
| SWE3-INT-04, SWE3-FX-05 | The wording of Purpose and Scope, and the abbreviation list |
| SWE3-SD-10, SWE3-FX-03 | What goes in Note |
| SWE3-UH-03 | List a unit's own symbol only when the unit uses it? The review asked for "of the unit **and** used by the unit" |
| SWE3-UH-05 | A macro value is shown as written (`(1<<6)`), not worked out (`64`) — acceptable? |
| SWE3-UI-08 | Entry points nothing calls by name (ISRs, callbacks) are private unless a table holds their address |
| SWE3-UI-11, SWE3-UI-14 | The way names are shortened for ids — repeatable, but `Map` and `Map2` both give `MAP`. Fixed-width codes, or an agreed list of component codes? |
| SWE3-UI-18, SWE3-FX-08 | Is the LLM-written text part of the acceptance check, or is `-` acceptable for V1? |
| SWE3-UI-27 | Rule 1 also matches `isSet`, `hasGet` — accept, or agree a list of exceptions |
| SWE3-UI-28 | A function that returns a value **and** writes a global is `Out` — keep, or let the write decide first (every status-returning writer would become `In`)? |
| SWE3-UI-31 | Source/Destination lists callers only — is that the intended reading? |
| SWE3-UI-33 | Source/Destination keeps hyphens (`Sample-Core/Core`) while headings show spaces (`Sample Core`) |
| SWE3-FD-04 | A private function reached only through another private function gets no flowchart anywhere — print it under its caller's caller too? |
| SWE3-FD-05, SWE3-FX-01, SWE3-FX-02 | Risk and Capacity — real values, or agreed constants? |
| SWE3-FX-04 | Requirements traceability: nothing to link to until SWE.1 / Polarion is available |
| SWE3-FX-06, SWE3-FX-07 | Code Metrics and Appendix — produce them here, or take them from the project's own tools? |
