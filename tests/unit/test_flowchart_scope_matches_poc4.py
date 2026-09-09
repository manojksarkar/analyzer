"""The database scope filter selects exactly what poc-4's file filter selected.

poc-4 narrowed the model in the view: it filtered functions.json down to the
run's components and units, wrote the smaller file, and passed it to the
flowchart engine as --interface-json. Database mode has no such file -- the
engine loads the model from the version and narrows it itself.

Same selection, different place. This pins that: _in_scope below is copied
verbatim from origin/poc-4 engine/views/flowcharts.py, and every case is run
through both. If the database filter ever drifts, these fail.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "engine" / "flowchart"))
sys.path.insert(0, str(_ROOT / "engine"))

from flowchart_engine import _apply_scope  # noqa: E402

KEY_SEP = "|"


def _poc4(all_funcs, allowed_components, allowed_units):
    """origin/poc-4 engine/views/flowcharts.py, unchanged.

    The view only filtered when a scope was set; otherwise it handed the whole
    functions.json over untouched.
    """
    if not (allowed_components or allowed_units):
        return dict(all_funcs)

    def _in_scope(fid):
        if not isinstance(fid, str) or KEY_SEP not in fid:
            return False
        parts = fid.split(KEY_SEP)
        if allowed_components and parts[0].lower() not in allowed_components:
            return False
        if allowed_units:
            unit = parts[1].lower() if len(parts) > 1 else ""
            if unit not in allowed_units:
                return False
        return True

    return {fid: info for fid, info in all_funcs.items() if _in_scope(fid)}


# Ordinary keys, plus the ones that decide the edges: a component spelled in a
# different case, a signature carrying extra separators, a key with no
# separator at all, and empty halves.
KEYS = [
    "App|Main|run",
    "App|Utils|helper",
    "Math|Utils|add",
    "Math|Main|calc",
    "APP|MAIN|shout",
    "App|Main|a|b",
    "Orphan",
    "App|",
    "|Utils|x",
]

SCOPES = [
    ([], []),                    # whole version
    (["app"], []),               # one component
    (["app", "math"], []),       # a group covering several
    ([], ["utils"]),             # --unit on its own
    (["app"], ["utils"]),        # both
    (["math"], ["main"]),
    (["APP"], ["UTILS"]),        # caller typed it in caps
    (["nope"], []),              # matches nothing
    ([], ["nope"]),
]


@pytest.mark.parametrize("components,units", SCOPES)
def test_selects_what_poc4_selected(components, units):
    funcs = {k: {"name": k} for k in KEYS}
    expected = _poc4(funcs, [c.lower() for c in components],
                     [u.lower() for u in units])
    got, _, _ = _apply_scope(dict(funcs), components, "", units)
    assert sorted(got) == sorted(expected)


def test_no_scope_keeps_the_whole_version():
    funcs = {k: {} for k in KEYS}
    got, comps, picked = _apply_scope(dict(funcs), [], "", [])
    assert sorted(got) == sorted(funcs)
    assert comps == set() and picked == set()


def test_singular_component_still_works():
    """run_views passes one component per call; the CLI can repeat --component."""
    funcs = {k: {} for k in KEYS}
    one, _, _ = _apply_scope(dict(funcs), (), "App", ())
    many, _, _ = _apply_scope(dict(funcs), ["app"], "", ())
    assert sorted(one) == sorted(many)


def test_plural_wins_over_singular():
    funcs = {k: {} for k in KEYS}
    got, comps, _ = _apply_scope(dict(funcs), ["math"], "App", ())
    assert comps == {"math"}
    assert all(k.lower().startswith("math|") for k in got)
