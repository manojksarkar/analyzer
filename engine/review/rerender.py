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


#: The stored output files the review code reads, by what their path ends with or contains.
FLOWCHARTS = "flowcharts"
INTERFACE_TABLES = "interface_tables.json"
BEHAVIOUR_MANIFEST = "_behaviour_pngs.json"


def output_rows(conn, version_id: str, which: str, *, mentioning: Optional[str] = None):
    """`(rel_path, content)` of one kind of stored output file in a version: `FLOWCHARTS` (each
    unit's flowchart JSON, not `_summary.json`), `INTERFACE_TABLES` or `BEHAVIOUR_MANIFEST`.

    Chosen by the DATABASE, by path. A version stores every output file of every group -- the
    flowchart JSON alone is megabytes -- and fetching all of it to keep one kind, as each caller
    here used to, moved the whole output tree across the wire for every save and every listing.
    `mentioning` narrows further to the rows whose text contains that string, for a caller
    looking for one entity's row.
    """
    vof = s.version_output_files
    q = select(vof.c.rel_path, vof.c.content).where(vof.c.version_id == version_id)
    if which == FLOWCHARTS:
        q = q.where(vof.c.rel_path.contains("/flowcharts/", autoescape=True),
                    vof.c.rel_path.endswith(".json", autoescape=True))
    else:
        q = q.where(vof.c.rel_path.endswith(which, autoescape=True))
    if mentioning:
        q = q.where(vof.c.content.contains(mentioning, autoescape=True))
    rows = conn.execute(q.order_by(vof.c.rel_path)).fetchall()
    if which == FLOWCHARTS:
        rows = [r for r in rows if r.rel_path.rsplit("/", 1)[-1] != "_summary.json"]
    return rows


def _flowchart_row_in(rows, flowchart_id: str):
    for r in rows:
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


def find_flowchart_row(conn, version_id: str, flowchart_id: str):
    """`(rel_path, unit_name, content)` for the unit file holding `flowchart_id`, or None.

    Searched rather than computed: the row's path carries a group directory and a unit stem that
    the flowchart id does not contain, and guessing either would fail silently on any project
    whose naming does not match the guess.

    Asked first for the files whose text contains the id as JSON writes it -- one or two rows,
    not the version's every flowchart. A writer that spelled it differently (non-ASCII escaped
    one way or the other) finds nothing there, so the whole set is searched before answering
    "no such flowchart".
    """
    spelled = json.dumps(flowchart_id)[1:-1]
    found = _flowchart_row_in(
        output_rows(conn, version_id, FLOWCHARTS, mentioning=spelled), flowchart_id)
    return found or _flowchart_row_in(output_rows(conn, version_id, FLOWCHARTS), flowchart_id)


# ---------------------------------------------------------------------------
# interface tables
# ---------------------------------------------------------------------------
def patch_interface_tables(conn, version_id: str, entity_key: str, description: str) -> int:
    """Update the copy of one entity's description in every stored `interface_tables.json`.

    The document does not read a function's description from the model -- the interface-tables
    view writes a **copy** into its own output, and both the DOCX exporter and the HTML view read
    that copy. So updating the model alone leaves the page showing the LLM's old words, which is
    the two-copies failure this feature exists to remove, arriving from the other direction.

    Re-deriving the view instead was rejected for the reason the render and the cascade were: it
    needs an output tree, a model and a config, and the host saving a correction may have none of
    them. Patching the row reaches the same place from anywhere.

    This is not a new writer. It goes through `write_output_row`, which the design already names as
    the one non-view writer of a `version_output_files` row.

    A function appears in exactly one unit but can appear in SEVERAL groups' files when scopes
    overlap, so every match is patched, not the first. Returns how many entries changed.
    """
    patched = 0
    for r in output_rows(conn, version_id, INTERFACE_TABLES):
        try:
            tables = json.loads(r.content or "{}")
        except ValueError:
            continue           # one unreadable group must not stop the others
        if not isinstance(tables, dict):
            continue
        changed = 0
        for unit_key, unit in tables.items():
            if unit_key == "unitNames" or not isinstance(unit, dict):
                continue
            for entry in unit.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                if entity_key in (entry.get("functionId"), entry.get("globalId")):
                    entry["description"] = description
                    changed += 1
        if changed:
            write_output_row(conn, version_id, r.rel_path,
                             json.dumps(tables, indent=2, ensure_ascii=False))
            patched += changed
    return patched


# ---------------------------------------------------------------------------
# behaviour rows
# ---------------------------------------------------------------------------
def find_behaviour_row(conn, version_id: str, function_id: str, external_caller_id: str):
    """`(rel_path, content, row)` for one behaviour row, or None.

    Matched on the two entity keys, never on the `externalUnitFunction` display label: that label
    drops the component, the class and the parameter types, so two callers can share one and a
    correction would land on whichever row was found first.

    A row written before `externalCallerId` existed simply does not match, which is the right
    outcome — it cannot be addressed unambiguously, so it is not addressed at all.
    """
    from review import phase3_overrides as p3

    for r in output_rows(conn, version_id, BEHAVIOUR_MANIFEST):
        try:
            payload = json.loads(r.content or "{}")
        except ValueError:
            continue
        for _c, _u, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
            if (row.get("currentFunctionId") == function_id
                    and row.get("externalCallerId") == external_caller_id):
                return r.rel_path, r.content, row
    return None


def write_behaviour_row(conn, version_id: str, rel_path: str, content: str,
                        slot_key: str, text: str) -> bool:
    """Put one corrected description into `_behaviour_pngs.json` and store the row.

    Goes through the same `apply_to_docx_rows` the `behaviourDiagram` view uses during a run, so a
    save and a regeneration cannot produce different output for one correction.
    """
    from review import phase3_overrides as p3

    try:
        payload = json.loads(content or "{}")
    except ValueError:
        raise RedrawError("behaviour output for version %s is not readable" % version_id)

    if not p3.apply_to_docx_rows((payload or {}).get("_docxRows"), {slot_key: text}):
        return False
    write_output_row(conn, version_id, rel_path,
                     json.dumps(payload, indent=2, ensure_ascii=False))
    return True


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


def draw_web_svgs(conn, version_id: str, flowchart_id: str, output_dir: str,
                  project_root: str) -> dict:
    """The web page's picture of one corrected flowchart -- drawn now, not by the next run.

    The web reader shows a flowchart only when its SVG was drawn from the stored DOT
    (`api/services/doc_render.py`, `_flowchart_entry`). A save rebuilds the DOT, so the page read
    "not drawn for this run" after every label correction until a re-export. The Word picture
    keeps its own path (`render_png`, the render queue).

    Writes the stored unit JSON back to the version's output tree, then runs the pass Phase 3
    runs on that directory (`views.flowcharts.write_flowchart_svgs`): it reads the JSON from disk
    and draws only the charts whose SVG no longer matches -- the corrected one. A disk copy left
    behind would also let the backfill tool (`tools/render_flowchart_pngs.py`), which reads disk,
    redraw the old labels.

    `{}` when the flowchart is not stored or the version has no output tree on this host; else
    the pass's counts (`drawn`, `current`, `failed`, ...).
    """
    found = find_flowchart_row(conn, version_id, flowchart_id)
    if not found:
        return {}
    rel_path, _unit_name, content = found
    path = os.path.join(output_dir, rel_path.replace("/", os.sep))
    if not os.path.isdir(os.path.dirname(path)):
        return {}
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    eng = os.path.join(_REPO_ROOT, "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    from views.flowcharts import write_flowchart_svgs
    return write_flowchart_svgs(project_root, os.path.dirname(path))
