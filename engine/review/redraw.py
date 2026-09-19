"""Applying corrections to flowchart JSON, and rebuilding the DOT. No database, no rows.

Split from `rerender` so the `flowcharts` **view** can use it. A view must not drag in
`api.db.postgres.schema` and SQLAlchemy to paste a label onto a graph; keeping the pure part
separate is what lets the same code serve both callers:

    Phase 3 (a full or incremental run)   -> apply_to_output_dir, before the PNGs are drawn
    a save                               -> rerender.redraw_flowchart, no pipeline at all

Both produce the same corrected CFG and the same DOT, because it is the same function. Two
implementations of "apply a correction" is the arrangement this feature exists to remove.

## The DOT is regenerated, never patched

Labels are line-wrapped and escaped on the way into the DOT, so a corrected label of a different
length needs re-wrapping. Patching the DOT text would put those rules in a second place to drift
from the first. Editing the CFG also keeps the picture and the SWE.4 Test Steps in step, since the
Test Steps read the CFG and not the DOT.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, List, Mapping, NamedTuple, Sequence

from review import phase3_overrides as p3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RedrawError(Exception):
    """Stored flowchart output could not be read or redrawn."""


class Redrawn(NamedTuple):
    """One flowchart that changed."""
    flowchart_id: str
    function_name: str
    png_name: str
    dot: str


class Patched(NamedTuple):
    content: str                 #: the unit's flowchart JSON, ready to store
    redrawn: Sequence[Redrawn]


def patch_unit_flowcharts(content: str, unit_name: str,
                          by_flowchart: Mapping[str, Mapping[str, str]],
                          shapes: Mapping[str, str] = None) -> Patched:
    """Apply corrections to one unit's flowchart JSON and rebuild the DOT for what changed.

    Pure: text in, text out, no files and no database. That is what makes the rules below
    testable without a parsed project.

    A unit with no corrections comes back **unchanged**, not merely equivalent — re-serialising
    JSON that nobody edited would rewrite every row on every save and make "what changed" useless
    for anyone reading the table.
    """
    if not by_flowchart:
        return Patched(content, ())
    try:
        entries = json.loads(content or "[]")
    except (TypeError, ValueError):
        raise RedrawError("flowchart JSON for %s is not readable" % unit_name)
    if not isinstance(entries, list):
        raise RedrawError("flowchart JSON for %s is not a list of entries" % unit_name)

    changed_ids = p3.apply_to_flowchart_json(entries, by_flowchart, shapes)
    if not changed_ids:
        return Patched(content, ())

    redrawn: List[Redrawn] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("functionKey") not in changed_ids:
            continue
        func_name = (entry.get("name") or "").strip()
        dot = dot_for(entry.get("cfg") or {})
        # The stored DOT is what the PNG render reads, so it moves with the CFG or the picture
        # and the graph disagree -- the two-copies failure in miniature.
        entry["flowchart"] = dot
        redrawn.append(Redrawn(flowchart_id=entry["functionKey"], function_name=func_name,
                               png_name=png_name_for(unit_name, func_name), dot=dot))

    return Patched(json.dumps(entries, indent=2, ensure_ascii=False), redrawn)


def apply_to_output_dir(fc_dir: str, by_flowchart: Mapping[str, Mapping[str, str]],
                        shapes: Mapping[str, str] = None) -> List[str]:
    """Apply corrections across every unit JSON in a flowcharts output directory.

    Called from inside the `flowcharts` view, **after** the engine has written its JSON and
    **before** the PNGs are drawn, so the picture is right the first time and there is no
    re-render (`REQ-AP-05`). Returns the flowchart ids corrected.

    One unreadable unit file is logged by the caller and skipped, not raised: a generation that
    has already paid for the parse and the LLM must not be lost to one bad file.
    """
    done: List[str] = []
    if not (by_flowchart and fc_dir and os.path.isdir(fc_dir)):
        return done
    for fn in sorted(os.listdir(fc_dir)):
        if not fn.endswith(".json") or fn == "_summary.json":
            continue
        path = os.path.join(fc_dir, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            patched = patch_unit_flowcharts(content, fn[:-len(".json")], by_flowchart,
                                            shapes)
        except (OSError, RedrawError):
            continue
        if not patched.redrawn:
            continue
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(patched.content)
        except OSError:
            continue
        done.extend(r.flowchart_id for r in patched.redrawn)
    return done


def dot_for(cfg: Mapping[str, Any]) -> str:
    """The DOT for a CFG dict, through the same builder a full run uses."""
    _ensure_paths()
    from flowchart.dot_builder import build_dot
    from flowchart.models import cfg_for_rendering
    return build_dot(cfg_for_rendering(dict(cfg)))


def png_name_for(unit_name: str, function_name: str) -> str:
    """`<unit>_<function>.png`, spelled exactly as `flowcharts.py` spells it.

    Through `safe_filename`, the same helper the view uses. Two spellings of one filename is how a
    re-render writes a picture the document never looks at.
    """
    _ensure_paths()
    from utils import safe_filename
    return "%s_%s.png" % (unit_name, safe_filename(function_name))


def _ensure_paths() -> None:
    """`engine/` and `engine/flowchart/` on `sys.path`, at call time not import time.

    The flowchart package imports its own submodules flat, so it needs its own directory on the
    path. The API imports this module to validate a request long before anything is drawn, and a
    module should not rearrange the import path merely by being loaded.
    """
    for p in (os.path.join(_REPO_ROOT, "engine"),
              os.path.join(_REPO_ROOT, "engine", "flowchart")):
        if p not in sys.path:
            sys.path.insert(0, p)
