"""Redrawing one flowchart after a correction, without running the pipeline.

`REQ-AP-06`. A save must be instant, so it re-parses nothing. The CFG is already stored, so:

    read the unit's flowchart JSON          version_output_files
    set cfg.nodes[n].label per correction   review.redraw
    rebuild the DOT from the corrected CFG  pure function
    write the JSON back
    re-render that one PNG                  Graphviz, then re-slice

No libclang, no LLM, no flowchart subprocess, and **no C++ source** — which is what lets a
correction be saved from a machine that does not have the tree checked out.

The patching itself lives in `review.redraw`, which has no database imports, because the
`flowcharts` view applies the same corrections during a full run (`REQ-AP-05`). One
implementation, two callers.

## The second writer

`REQ-AP-01` says view output is derived, and the design said only a `VIEW_REGISTRY` call writes a
`version_output_files` row. This module breaks that, deliberately and in exactly one place,
because it cannot run the view instead: `persist_output_files` deletes every row for a version and
rebuilds from a full `output_dir` walk — there is no single-row form, and a save has no output dir.

So the invariant is restated rather than left quietly false:

    a version_output_files row is written by `model_store.persist_output_files`
    or by `review.rerender.write_output_row`, and by nothing else.

`tests/unit/test_output_row_writers.py` fails if a third appears. An invariant nobody checks is a
comment, and this codebase has already been bitten by a guard that silently stopped running.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Mapping, Optional, Sequence

from sqlalchemy import insert, select, update

from review.redraw import (Patched, Redrawn, RedrawError, patch_unit_flowcharts,  # noqa: F401
                           png_name_for)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

#: Kept as an alias so callers have one exception to catch across both modules.
RerenderError = RedrawError


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
def read_output_row(conn, version_id: str, rel_path: str) -> Optional[str]:
    """One `version_output_files` row's content, or None."""
    row = conn.execute(
        select(s.version_output_files.c.content)
        .where(s.version_output_files.c.version_id == version_id,
               s.version_output_files.c.rel_path == rel_path)).first()
    return row.content if row else None


def write_output_row(conn, version_id: str, rel_path: str, content: str) -> None:
    """Replace one `version_output_files` row. **The only single-row writer** — see the module
    docstring for why this exists rather than re-running the view."""
    touched = conn.execute(
        update(s.version_output_files)
        .where(s.version_output_files.c.version_id == version_id,
               s.version_output_files.c.rel_path == rel_path)
        .values(content=content)).rowcount
    if not touched:
        conn.execute(insert(s.version_output_files).values(
            version_id=version_id, rel_path=rel_path, content=content,
            group_name=rel_path.split("/", 1)[0] if "/" in rel_path else None))


def find_flowchart_row(conn, version_id: str, flowchart_id: str):
    """`(rel_path, unit_name, content)` for the unit file holding `flowchart_id`, or None.

    Searched rather than computed: the row's path carries a group directory and a unit stem that
    the flowchart id does not contain, and guessing either would fail silently on any project
    whose naming does not match the guess.
    """
    rows = conn.execute(
        select(s.version_output_files.c.rel_path, s.version_output_files.c.content)
        .where(s.version_output_files.c.version_id == version_id)).fetchall()
    for r in rows:
        if "/flowcharts/" not in r.rel_path or not r.rel_path.endswith(".json"):
            continue
        if r.rel_path.rsplit("/", 1)[-1] == "_summary.json":
            continue
        try:
            entries = json.loads(r.content or "[]")
        except ValueError:
            continue
        if not isinstance(entries, list):
            continue
        if any(isinstance(e, dict) and e.get("functionKey") == flowchart_id for e in entries):
            unit_name = r.rel_path.rsplit("/", 1)[-1][:-len(".json")]
            return r.rel_path, unit_name, r.content
    return None


# ---------------------------------------------------------------------------
# the whole save-time redraw
# ---------------------------------------------------------------------------
def redraw_flowchart(conn, version_id: str, flowchart_id: str,
                     labels: Mapping[str, str], *,
                     output_dir: Optional[str] = None,
                     project_root: Optional[str] = None) -> Sequence[Redrawn]:
    """Apply `{node_id: text}` to one flowchart, store the JSON, re-render the picture.

    `output_dir` and `project_root` are optional: without them the JSON is updated and **no image
    is produced**. That is the right behaviour for an API host with no output tree — the text is
    corrected everywhere it is read from the database, and the picture is regenerated by the next
    run. It is not silent: the caller gets the `Redrawn` list either way and can queue a render.
    """
    found = find_flowchart_row(conn, version_id, flowchart_id)
    if not found:
        raise RedrawError("no stored flowchart for %s in version %s"
                          % (flowchart_id, version_id))
    rel_path, unit_name, content = found

    patched = patch_unit_flowcharts(content, unit_name, {flowchart_id: dict(labels)})
    if not patched.redrawn:
        return ()

    write_output_row(conn, version_id, rel_path, patched.content)

    if output_dir and project_root:
        fc_dir = os.path.join(output_dir, os.path.dirname(rel_path).replace("/", os.sep))
        for item in patched.redrawn:
            render_png(project_root, fc_dir, item)
    return patched.redrawn


def render_png(project_root: str, fc_dir: str, item: Redrawn) -> bool:
    """Render one flowchart's PNG and re-slice it. True if the image exists afterwards.

    Re-slicing is not optional. A corrected label can change the picture's height, so a graph
    written as `_part_1_of_3` may become `_part_1_of_2` and the orphan `_part_3_of_3.png` would be
    left for the document to find — a defect this codebase has had once already.
    `_maybe_slice_tall_png` clears the old parts before re-slicing, so calling it is the whole fix.
    """
    eng = os.path.join(_REPO_ROOT, "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    from utils import render_dot_cached
    from views.flowcharts import _maybe_slice_tall_png

    png_path = os.path.abspath(os.path.join(fc_dir, item.png_name))
    if not render_dot_cached(project_root, item.dot, png_path, scale=2, timeout=180):
        return False
    if os.path.isfile(png_path):
        _maybe_slice_tall_png(png_path)
    return True
