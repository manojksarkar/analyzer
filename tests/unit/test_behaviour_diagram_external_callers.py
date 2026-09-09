"""The view and the generator must agree on what "external" means.

The generator decides WHICH behaviour diagrams to write, and it defines an external
caller as one in a DIFFERENT COMPONENT (selector.get_external_callers_with_component
compares caller_component != current_component). The view then pairs the returned
.mmd files with callers positionally:

    for idx, mmd_path in enumerate(mmd_paths):
        if idx >= len(external_callers):
            break

so if the view computes a SHORTER list than the generator used, the loop breaks and
those diagrams are silently dropped -- after the .mmd (and often the .png) have already
been written to disk.

That is exactly what happened. The view used to say "external = outside the selected
components" whenever a scope was set, which disagrees with the generator the moment one
document spans several components -- `--scope "component:Alpha,Beta"`, or any group-level
document. A caller in a sibling component was external to the generator and internal to
the view, so external_callers came out empty and nothing was recorded.

The symptom is distinctive and worth recognising: a behaviour_diagrams/ directory full of
.mmd and .png files sitting beside a _behaviour_pngs.json that reads {"_docxRows": {}},
and a document whose Dynamic Behaviour section is empty. Reproduced on a two-component
fixture, and poc-4 has the identical defect -- it is not something the database migration
introduced.
"""

import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_VIEW = os.path.join(_ROOT, "engine", "views", "behaviour_diagram.py")


def _view_src():
    with open(_VIEW, encoding="utf-8") as fh:
        return fh.read()


def _external_caller_stmt():
    """The one statement that decides which callers the view will pair up.

    Bracket-aware rather than a lazy regex: the comprehension contains [0] and a lazy
    match stops there, which quietly reduces this whole file to testing a fragment.
    """
    src = _view_src()
    i = src.index("external_callers = [")
    depth, j = 0, src.index("[", i)
    for j in range(j, len(src)):
        if src[j] == "[":
            depth += 1
        elif src[j] == "]":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError("unbalanced brackets in external_callers")


def test_external_means_a_different_component():
    """The generator's rule, verbatim: caller component != this component."""
    stmt = _external_caller_stmt()
    assert 'c.split("|")[0] != component_name' in stmt


def test_external_is_not_defined_as_outside_the_selected_scope():
    """The rule that broke it. `allowed_components` legitimately narrows WHICH functions
    get diagrams (further up), but it must not redefine who counts as an external caller
    -- the generator already made that call when it wrote the files."""
    stmt = _external_caller_stmt()
    assert "allowed_components" not in stmt


def test_only_one_rule_exists():
    """It used to be an if/else over allowed_components. Two rules is how they drifted."""
    assert len(re.findall(r"external_callers = \[", _view_src())) == 1


def test_the_generator_still_uses_the_component_rule():
    """If the generator's definition ever changes, the view has to change with it -- this
    is the other half of the invariant, and it is the half that decides what gets written."""
    sel = os.path.join(_ROOT, "engine", "behaviour_diagram", "selector.py")
    with open(sel, encoding="utf-8") as fh:
        src = fh.read()
    assert "caller_component != current_component" in src


def test_rows_are_recorded_for_every_diagram_the_generator_wrote():
    """The pairing is positional, so the view's list must not be shorter than the
    generator's. Same model, same rule -> same length."""
    from behaviour_diagram.selector import DiagramSelectorBase

    functions = {
        "Beta|Target|betaCompute|int": {"calledByIds": ["Alpha|Caller|alphaRun|int"]},
        "Alpha|Caller|alphaRun|int": {"calledByIds": []},
    }
    fid_to_unit = {"Beta|Target|betaCompute|int": "Beta|Target",
                   "Alpha|Caller|alphaRun|int": "Alpha|Caller"}
    unit_to_comp = {"Beta|Target": "Beta", "Alpha|Caller": "Alpha"}
    sel = DiagramSelectorBase(fid_to_unit, unit_to_comp, functions)
    target = "Beta|Target|betaCompute|int"
    generator_view = sel.get_external_callers_with_component(target)
    generator_count = sum(len(v) for v in generator_view.values())

    # what the view now computes, with Alpha and Beta BOTH in scope
    component_name = "Beta"
    called_by = functions[target]["calledByIds"]
    view_callers = [c for c in called_by if c and "|" in c and c.split("|")[0] != component_name]

    assert generator_count == 1
    assert len(view_callers) == generator_count, (
        "the view would drop a diagram the generator wrote")
