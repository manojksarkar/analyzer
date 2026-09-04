"""The flowchart engine must regenerate exactly what the view decided.

Both halves restrict independently and they have to agree, because the engine reads
`flowchartFids` from the STORED plan while the view computes its own `sel`. They diverge
in one specific place, and the result is silent and wrong.

    plan.flowchartFids = direct_fns - crossVersionFlowcharts

so a CHANGED function whose content fingerprint was already seen in an earlier version is
excluded, on the assumption its flowchart can be spliced from there. The view then checks
that assumption -- and when the source version turns out to have no flowchart for it, adds
the fid back to `sel` to be regenerated.

Nothing carried that correction to the engine. It read the unchanged plan, saw an empty
list, rendered nothing, and the splice fell through fresh -> x-ver -> BASELINE. The
document kept the PREVIOUS version's diagram for code that had changed, with no error.

Reproduced end to end: a for-loop added to Math|Utils::add, incremental. The first run
renders it (nothing in the index yet). A later run off the same baseline finds the
fingerprint, finds no flowchart at the source, and silently keeps the old picture --
byte-identical PNG, 442-char DOT against the correct 734.

So the view republishes the corrected set before the engine starts. One source of truth.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_VIEW = os.path.join(_ROOT, "engine", "views", "flowcharts.py")
_ENGINE = os.path.join(_ROOT, "engine", "flowchart", "flowchart_engine.py")


def _src(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def test_the_view_republishes_its_corrected_selection():
    src = _src(_VIEW)
    i = src.index("if set(sel) != set(fids):")
    block = src[i:i + 600]
    assert "write_model_file(INCREMENTAL_PLAN" in block
    assert '"flowchartFids": sorted(set(sel))' in block


def test_it_republishes_only_when_the_sets_differ():
    """An unconditional write would rewrite the plan on every run for no reason, and would
    hide whether the fallback ever fires."""
    assert "if set(sel) != set(fids):" in _src(_VIEW)


def test_a_republish_failure_does_not_kill_the_run():
    """Losing a flowchart refresh is bad; losing the whole document is worse. It says so
    loudly instead."""
    src = _src(_VIEW)
    i = src.index("if set(sel) != set(fids):")
    block = src[i:i + 900]
    assert "except Exception" in block
    assert "err=True" in block


def test_the_fallback_that_makes_this_necessary_still_exists():
    """`sel.append(fid)` when the cross-version source has no flowchart. If that ever goes
    away the republish is pointless -- and if it stays without the republish, the bug is
    back."""
    src = _src(_VIEW)
    i = src.index("if entry is None:")
    assert "sel.append(fid)" in src[i:i + 120]


def test_unit_narrowing_cannot_drop_a_changed_function():
    """The second half of the same guarantee. Once the plan has restricted to the changed
    functions, --unit must not narrow further: the view has already carried the baseline's
    PNGs forward, so dropping a changed function here does not skip work, it leaves the
    previous version's picture on disk for edited code."""
    src = _src(_ENGINE)
    assert "_units = () if _plan_applied else config.units" in src
    i = src.index("_plan_applied = True")
    assert "_plan_applied" in src[i:i + 400]
