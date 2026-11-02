"""A function's own lines of code, from its version's checkout (BACKLOG NW-7).

The reader shows them beside the function's flowchart, so a reviewer can check the chart against
the code. Read from the checkout the version was generated from -- never cloned here: a clone can
take minutes, too long for a page. A version whose code is not on this machine says so
(`SourceNotHere`); a run or a re-export of it puts the code back.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

#: The most lines one answer carries: a function longer than this is cut, and says so.
MAX_LINES = 400


class SourceNotHere(Exception):
    """The version's code is not on this machine."""


def _location(engine: Any, version_id: str, function_id: str):
    """(file relative to the project, first line, last line) of the function in this version."""
    from sqlalchemy import select
    from ..db.postgres import schema as s
    ev, e = s.entity_versions, s.entities
    with engine.connect() as cx:
        return cx.execute(
            select(ev.c.file, ev.c.line, ev.c.end_line)
            .select_from(ev.join(e, e.c.entity_id == ev.c.entity_id))
            .where(ev.c.version_id == version_id, e.c.entity_key == function_id,
                   e.c.kind == "function")).first()


def function_source(db: Any, project_id: str, version_id: str, function_id: str) -> dict:
    """{function_id, file, start_line, end_line, lines, truncated}. LookupError when the version
    has no such function; SourceNotHere when its code is not on this machine."""
    engine = getattr(db, "_engine", None)
    row = _location(engine, version_id, function_id) if engine is not None else None
    if row is None or not row.file or not row.line:
        raise LookupError(function_id)
    from ..db.session import _engine_on_path
    _engine_on_path()
    from incremental.source_checkout import SourceUnavailable, locate_or_restore
    from .settings import get_settings
    try:
        checkout = locate_or_restore(project_id, version_id, restore=False,
                                     workspaces_root=str(get_settings().workspaces))
    except SourceUnavailable as exc:
        raise SourceNotHere(str(exc)) from exc
    root = Path(checkout.path).resolve()
    path = (root / row.file).resolve()
    if root not in path.parents or not path.is_file():   # never outside the checkout
        raise SourceNotHere(f"{row.file} is not in the version's checkout")
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(row.line))
    end = max(start, int(row.end_line or start))
    if end == start:
        # A version made before the parser stored where a function ends has its end line equal
        # to its first: found here, from the code, so the body is shown and not the signature only.
        end = _body_end(text, start)
    stop = min(end, start - 1 + MAX_LINES)
    return {"function_id": function_id, "file": row.file, "start_line": start, "end_line": end,
            "lines": text[start - 1:stop], "truncated": end > stop}


def _body_end(lines: list, start: int) -> int:
    """The line of the `}` that closes the function whose signature is on line `start` (1-based):
    its braces counted in code only -- not in comments or string and char literals
    (`views.unit_headers._code_only`). `start` when no body opens (a declaration, `= default;`)
    or none closes within `MAX_LINES`."""
    from views.unit_headers import _code_only
    depth, opened, in_block = 0, False, False
    for i in range(start - 1, min(len(lines), start - 1 + MAX_LINES)):
        code, in_block = _code_only(lines[i], in_block)
        if not opened and ";" in code and "{" not in code:
            return start                                    # a declaration: no body
        for ch in code:
            if ch == "{":
                depth, opened = depth + 1, True
            elif ch == "}" and opened:
                depth -= 1
                if depth == 0:
                    return i + 1
    return start

