# doccheck — compare generated documents by what they say

Reads a `.docx` into the things it describes — units, interface rows, test steps —
and compares them level by level. A reordered table or a reworded sentence does not
flood the output, and a wrong `Direction` does not hide in it.

Paths in, a report out. No repository, database or pipeline run, so it works on a
client's document, on the machine the document is on.

## Use

```bash
# two documents of one type (SWE.3 + SWE.3, or SWE.4 + SWE.4)
python tools/doccheck/__main__.py reference.docx compared.docx

# a SWE.3 design against its SWE.4 spec: chosen automatically, or with --pair
python tools/doccheck/__main__.py design.docx spec.docx

# one document against its own rules
python tools/doccheck/__main__.py a_document.docx --self

# the long form, JSON, a gate for a pipeline, and a depth limit
python tools/doccheck/__main__.py a.docx b.docx --markdown r.md --json r.json --gate P1 --level 3
```

| Flag | |
|---|---|
| `--markdown PATH` / `--json PATH` | write the long-form / machine report — every check type |
| `--level 1..5` | stop after that level (default 5) |
| `--gate P1..P4` | exit 1 when a counted finding at that priority or worse exists (`high`/`medium`/… still accepted) |
| `--full` | terminal: list P3/P4 and follow-up findings too, and every changed line |
| `--aliases FILE` | `ours = theirs` name pairs, one per line, for names no algorithm can settle |
| `--profile swe3\|swe4` | force the document type instead of detecting it |
| `--color auto\|always\|never` | colour only on a terminal; a pipe gets plain ASCII (`NO_COLOR` honoured) |

## Levels — where a difference is

Each level checks only what the level above matched, so a missing unit is one
finding, not forty missing rows. Names are compared, not only counts: five function
headings against five is still ✗ when two names differ.

| Level | SWE.3 / SWE.3 | SWE.4 / SWE.4 | SWE.3 / SWE.4 |
|---|---|---|---|
| **L1** headings | every heading kind present | same | each SWE.3 kind has its SWE.4 counterpart |
| **L2** inventory | components, units, dynamic behaviours | components, units, interaction specs | units; behaviour diagrams ↔ interaction specs |
| **L3** sections | per unit: function headings, unit header / interface sections | per unit: test case headings | per unit: function headings ↔ test cases |
| **L4** views | per table and diagram: rows, rows by kind, columns, images | per spec: Table A/B present, item counts | per unit: interface Function rows ↔ test cases; per interaction: call arrows ↔ cross-unit calls |
| **L5** content | the cells of matched rows, declarations, arrows | what Table A and B say | Test Case ID = `TC_` + Interface ID; which arrow has no step (or step no arrow); headings printed alike |

One fact is counted once, at the first level that sees it. A function heading only
one side has is an L3 finding; its interface row at L4 is shown, marked *follows*,
and not counted again.

SWE.3 is the input to SWE.4, so the pair check reads the design twice for the tests
it owes: its function headings (L3) and its interface table's Function rows (L4). A
function that lost only its flowchart entry is still owed a spec by its row. Each
behaviour diagram's call arrows (`A calls B`) must reappear as the spec's cross-unit
calls (`Successfully called <Unit>.B`); mocks leave the component and are not compared.

Headings are checked twice in a pair: their kinds at L1 (each SWE.3 kind has its SWE.4
counterpart) and their text at L5, gathered in one **headings** view per unit — component,
unit, `<Unit>-<Function>` and interaction headings. Case or spacing alone is P4; other
wording is P2; a heading that names another function or entry point no longer pairs, and
is found at L2/L3 instead. A heading spaced `Unit - function` is still that function.

The pair reads one way, because SWE.3 is the input: what only the design has is a
coverage gap (P2 — a header-defined function gets no spec); what only the spec has
was invented by the spec (P1). The spec takes the design's Interface IDs, so a gap
in its Test Case IDs left by a design function with no spec is explained (P3).

An inline (header-defined) public function is in the design because another unit calls
it, and gets no spec of its own: its callers mock it or run it inline. When the spec
shows that — the function named as a mock, or inside its own unit's specs — its missing
spec is explained (P3). With no such evidence it stays P2 and names its callers, since
the documents cannot tell a header function from a forgotten spec.

Both documents are held to the same heading rules on their own: a `<Unit>-<Function>`
heading starts with its own unit, and an interaction heading reads
`<Unit> - <Function> (<CallerUnit> - <CallerFunction>)`; SWE.3 also checks that the unit
and function it names are in its component.

## Priorities — how bad it is

| | |
|---|---|
| **P1** blocker | breaks a documented rule: a missing unit, a wrong Direction or Data Type, broken IDs, a design and spec that do not pair |
| **P2** review | a real difference a person has to judge |
| **P3** explained | a documented rule produces it; listed with the rule, never counted as a defect |
| **P4** cosmetic | order and wording only |

A rule comes in three strengths: *explained* (P3), *possible reason* (a lead, the
priority stays) and *the rule* (the one a pairing finding breaks).

## Reading the reports

- **Markdown**: a summary table per level is always shown; the details sit in
  collapsed `<details>` blocks — L4 per unit, L5 per unit then per view. Open it in
  a Markdown preview (VS Code: Ctrl+Shift+V).
- **Terminal**: the ladder (`L1 ok  L2 1 …`), then per level the rows that disagree
  and the P1/P2 findings. `−` marks the first document, `+` the second; `≡` folds
  the same change in several places into one.
- **JSON** (`schema: doccheck/2`): levels, summary rows (`checks`), findings, and
  each document's own checks.

Not compared across two documents: Interface / Test Case IDs (each document numbers
its own; checked inside one document instead) and image pixels (images are counted).

## Adding a document type

A profile (`swe3.py`, `swe4.py`) turns the block stream into an entity tree and
declares its `HEADING_TYPES`, `KINDS` (which entity sits at which level),
`POLICIES` (how each field is compared, at which level, in which view),
`FOLLOWS` / `FIELD_REQUIRES`, and `SELF_CHECKS`. Matching, the levels and the
reports are generic.

## Layout

| | |
|---|---|
| `blocks.py` | a `.docx` as a block stream, structure kept |
| `cells.py` | the cell grammars the exporters write |
| `model.py` | the entity tree, field policies, levels and priorities |
| `swe3.py` / `swe4.py` | one profile per document type |
| `match.py` | which entity on the left is which on the right |
| `compare.py` | the five levels: summary rows and findings |
| `rules.py` | a difference attributed to a documented rule, per document type |
| `pairing.py` | SWE.3 against SWE.4 |
| `report.py` | terminal, markdown and JSON |

Tests: `pytest tests/unit -k doccheck --skip-pipeline`. `test_doccheck_scenarios.py`
changes one thing in a real generated document per scenario and asserts the level
and priority it lands at; `python tests/unit/doccheck_scenarios.py OUT_DIR` writes
the demo reports from all of them at once.
