"""`--unit` narrows the RENDER, not which functions get a row.

Deciding whether a function needs a behaviour diagram is free: the selector returns
nothing for almost every function, measured at about 0.01s across 2817 of them. The cost
is mmdc, several seconds per PNG. So every function is evaluated and every row recorded;
only the image rendering is skipped for units the caller did not name, reusing whatever
PNG is already on disk.

Narrowing the FUNCTION LIST instead -- which is what this did first -- was wrong in a way
that hid itself three times over:

  * `_behaviour_pngs.json` is the only thing the exporter reads to place a behaviour
    subsection, so dropping a unit's rows dropped it from the document;
  * the .mmd and .png stayed on disk, so the directory looked complete and the failure
    read as an exporter bug;
  * it could not repair itself. No `--unit` run could restore rows a previous `--unit`
    run had dropped, because the run that would rebuild them was the one being narrowed.
    Only a full run recovered it.

With the render narrowed instead, the manifest is complete by construction, `--unit` still
skips the expensive work, and a narrowed run HEALS a manifest an earlier one emptied --
verified end to end at 0.14s against 5.6s for the full render.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_VIEW = os.path.join(_ROOT, "engine", "views", "behaviour_diagram.py")


def _src():
    with open(_VIEW, encoding="utf-8") as fh:
        return fh.read()


def test_the_function_list_is_not_narrowed_by_unit():
    """The regression that started it: `functions = [... in allowed_units]`."""
    src = _src()
    assert "allowed_units" in src, "the flag is still read"
    assert "functions = [fid for fid in functions" not in src.split("allowed_units", 1)[1][:400]


def test_the_render_is_narrowed_by_unit():
    """Where the time is actually spent."""
    src = _src()
    i = src.index("png = os.path.join(out_dir,")
    block = src[i:i + 900]
    assert "if allowed_units and _short not in allowed_units:" in block
    assert "run_cmd_base" in block


def test_an_existing_png_is_reused_rather_than_rerendered():
    src = _src()
    i = src.index("if allowed_units and _short not in allowed_units:")
    block = src[i:i + 400]
    assert "os.path.isfile(png)" in block
    assert "png_path = png" in block


def test_a_row_is_recorded_even_when_the_image_was_skipped():
    """The whole point: the document keeps its heading and description. The exporter
    already tolerates a row whose pngPath is missing."""
    src = _src()
    i = src.index("if allowed_units and _short not in allowed_units:")
    block = src[i:i + 400]
    assert "not_rendered.append" in block
    # and the append to docx_rows is NOT inside that branch
    assert "docx_rows.setdefault" not in block


def test_the_manifest_is_written_whole():
    """No merge: docx_rows is complete for the component now, and rebuilding it whole is
    what drops a stale row whose diagram has since gone."""
    src = _src()
    assert "merged" not in src and "prior" not in src
    assert 'json.dump({"_docxRows": docx_rows}, f, indent=2)' in src


def test_skipped_renders_are_reported():
    src = _src()
    assert "had no PNG to reuse" in src
    assert "Re-run without --unit to render them" in src


def test_orphans_are_keyed_on_recorded_rows_not_on_the_png():
    """A row whose image --unit skipped is still a row. Keying the orphan check on the
    PNG reported exactly those as missing from the document, which is the opposite of
    what had happened."""
    src = _src()
    i = src.index("    orphans = []")
    block = src[i:i + 500]
    assert "f not in rowed_mmd" in block
    assert "pngPath" not in block


def test_rowed_mmd_is_filled_where_the_row_is_made():
    """If these two ever drift apart the orphan report becomes noise."""
    src = _src()
    i = src.index("rowed_mmd.add(")
    assert "docx_rows.setdefault" in src[i:i + 200]
