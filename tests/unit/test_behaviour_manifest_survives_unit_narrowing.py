"""A unit-narrowed run must not throw away the other units' behaviour rows.

`_behaviour_pngs.json` is the only thing the exporter reads to place behaviour diagrams
in a document. The view rewrote it unconditionally at the end of every run, which is
right for a FULL run -- it just regenerated everything the component has -- and wrong
under `--selected-unit`, where it only looked at the named units.

The damage lands on components that do not hold the named unit at all: the filter leaves
zero functions, so the rows come out empty, and the manifest from the earlier full run is
overwritten with `{}`. Every .mmd and .png stays on disk, so the directory looks healthy
and the document's Dynamic Behaviour section is silently empty.

    generate --scope "group:X"        -> {"_docxRows": {"Signal": {"SignalDriver": [...]}}}
    reexport --unit SomeOtherUnit     -> {"_docxRows": {}}          <- and 2 files still there

Reproduced end to end before fixing, which is how it was found: it is the shape reported
from a real project, where a `--unit` reexport left 8 diagram files and 0 rows.

unit_diagrams already skips its output-directory wipe under `--selected-unit`, for the
same reason and with the same comment. This is that rule applied to the manifest.
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_VIEW = os.path.join(_ROOT, "engine", "views", "behaviour_diagram.py")


def _write_block():
    with open(_VIEW, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index('out_path = os.path.join(out_dir, "_behaviour_pngs.json")')
    # end at the write itself, not a fixed window -- a window that overshoots into the
    # next statement makes "the dump is last" untestable
    end = src.index('json.dump({"_docxRows": docx_rows}, f, indent=2)', i)
    return src[i:end + len('json.dump({"_docxRows": docx_rows}, f, indent=2)')]


def test_a_narrowed_run_merges_instead_of_replacing():
    block = _write_block()
    assert "if allowed_units:" in block
    assert "prior" in block and "merged" in block


def test_a_full_run_still_replaces():
    """A full run regenerated everything, so stale rows must not survive it. The merge is
    inside `if allowed_units:` precisely so an unnarrowed run keeps replacing."""
    block = _write_block()
    before_merge = block.split("if allowed_units:", 1)[0]
    assert "json.dump" not in before_merge, "the write must come after the merge decision"
    assert block.rstrip().endswith('json.dump({"_docxRows": docx_rows}, f, indent=2)')


def test_the_selected_units_own_rows_are_replaced_not_appended():
    """The named units were fully recomputed. Keeping their old rows would leave a unit
    whose diagram has since gone with a row pointing at a file nobody writes any more."""
    block = _write_block()
    assert "u.lower() not in allowed_units" in block


def test_a_corrupt_manifest_does_not_abort_the_run():
    block = _write_block()
    assert "except (OSError, ValueError)" in block


def test_merge_semantics():
    """The behaviour itself, on the data shapes the view uses."""
    prior = {"Signal": {"SignalDriver": [{"x": 1}], "Signal": [{"y": 2}]},
             "Cross": {"Hub": [{"z": 3}]}}
    allowed_units = ["signal"]                       # narrowed to the unit "Signal"
    fresh = {}                                       # which produced no diagrams

    merged = {}
    for comp, umap in prior.items():
        kept = {u: rows for u, rows in umap.items() if u.lower() not in allowed_units}
        if kept:
            merged[comp] = kept
    for comp, umap in fresh.items():
        merged.setdefault(comp, {}).update(umap)

    # SignalDriver and Hub survive; the recomputed "Signal" unit is gone, as it should be
    assert merged == {"Signal": {"SignalDriver": [{"x": 1}]}, "Cross": {"Hub": [{"z": 3}]}}


def _orphan_block():
    with open(_VIEW, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("    orphans = []")
    return src[i:src.index("progress.done(", i)]


def test_diagram_files_with_no_row_are_reported():
    """The merge cannot restore rows an earlier run already destroyed, and a narrowed run
    regenerates only its own units -- so files can sit there covered by nothing. The
    exporter places a subsection only from the manifest, so the document gets an empty
    "Dynamic Behaviour" heading while the directory looks healthy. Silence there is what
    made this take three rounds to find."""
    block = _orphan_block()
    assert "no entry in _behaviour_pngs.json" in block
    assert "err=True" in block


def test_the_narrowed_case_says_how_to_recover():
    """Naming the fix matters: the rows are gone and only a full run rebuilds them."""
    block = _orphan_block()
    assert "if allowed_units:" in block
    assert "WITHOUT --unit" in block


def test_orphans_are_matched_by_the_rendered_png():
    """A row points at a .png; the file on disk is a .mmd. Comparing the wrong pair would
    report every diagram as an orphan on every healthy run."""
    block = _orphan_block()
    assert 'os.path.splitext(f)[0] + ".png"' in block
    assert "pngPath" in block


def test_orphan_detection_reads_the_merged_rows():
    """It must run AFTER the merge, or a narrowed run would flag the units it correctly
    carried forward."""
    with open(_VIEW, encoding="utf-8") as fh:
        src = fh.read()
    assert src.index("docx_rows = merged") < src.index("    orphans = []")
