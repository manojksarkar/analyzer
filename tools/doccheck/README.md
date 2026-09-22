# doccheck — compare two generated documents

Reads a `.docx` into the things it describes — units, interface rows, test steps —
and compares two of them by content. Unlike `tools/dump_docx.py` + `diff`, a
reordered table or a reworded sentence does not flood the output, and a wrong
`Direction` does not hide in it.

Two paths in, a report out. No repository, database or pipeline run — so it works
on a client's document, on the machine the client's document is on.

## Use

```bash
# ours against theirs
python tools/doccheck/__main__.py reference.docx compared.docx

# one document, against its own rules
python tools/doccheck/__main__.py a_document.docx --self

# a SWE.3 design against its SWE.4 specification (V-model)
python tools/doccheck/__main__.py --pair design.docx spec.docx

# reports, and an exit code for a pipeline
python tools/doccheck/__main__.py a.docx b.docx --markdown r.md --json r.json --gate high
```

SWE.3 and SWE.4 are detected from the document; `--profile` forces it.

`--aliases names.txt` settles what no algorithm can — one `ours = theirs` per line,
`#` comments. Use it when two documents name the same unit differently on purpose.

## What it reports

Each rung runs only on what the rung above matched, so one missing unit does not
report its forty rows as forty missing rows:

| | |
|---|---|
| **L0** | sections present, and in order |
| **L1** | components and units — which exist, then in what order |
| **L2** | per unit — interface rows, header definitions, functions, test cases |
| **L3** | the fields of a matched row, each by its own rule |
| **L4** | dynamic behaviour — the set of interactions |

Severity is `high` / `medium` / `low` / `info`, and a finding carries the
documented rule that would explain it where one does.

## Three things worth knowing

**The ID is ours.** `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` and `TC_<interfaceId>` are
derived here, so another author's document will not share them. Rows are matched
on **name**; the id is checked for internal consistency instead — well-formed,
gapless, functions before globals.

**Fields are not compared with `==`.** `Direction` is an enum (`OUT` and `Out`
agree), `Source/Destination` is a set (order is not a difference), parameters are
a sequence (order *is*), and `Information` is advisory — a rewording is never a
defect. See `model.py` for the policy table.

**A single document can fail on its own.** A unit appears in the Component/Unit
table *and* as a heading; a function appears as a flowchart heading *and* as an
interface row. `--self` checks those against each other, with no second document.

## Adding a document type

A profile (`swe3.py`, `swe4.py`) turns the block stream into an entity tree and
declares a `POLICIES` table. Everything below that — matching, the ladder, the
report — is generic.

## Layout

| | |
|---|---|
| `blocks.py` | a `.docx` as a block stream, structure kept |
| `cells.py` | the cell grammars the exporters write |
| `model.py` | the entity tree and the field policies |
| `swe3.py` / `swe4.py` | one profile per document type |
| `match.py` | which entity on the left is which on the right |
| `compare.py` | the level ladder |
| `rules.py` | attributing a difference to a documented rule |
| `pairing.py` | SWE.3 against SWE.4 |
| `report.py` | terminal, markdown and JSON output |

Tests: `tests/unit/test_doccheck_*.py` (`pytest tests/unit -k doccheck --skip-pipeline`).
They validate the extractor against `interface_tables.json` and `test_specs.json` —
the pipeline's own data, sitting next to every generated document.
