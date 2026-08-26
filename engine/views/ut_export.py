"""UT export view (SWE.4): test_specs.json -> output/<group>/ut_export.json.

The unit-test automation format, per docs/spec/UT_EXPORT_SPEC.md. Reads the specs
the testSpecs view just wrote rather than re-deriving them, so the document and the
export can never disagree about what a unit's tests are -- the same objects feed
both. (Same arrangement as testSpecs reading the flowchart engine's CFG.)

One case per PATH, not per function (REQ-UE-04). A spec covers every exit in one
row because that is what the document renders; `expected.returns[].step` names which
numbered step each return leaves by, so the paths are already distinguished and only
need splitting out.

Input VALUES are not solved yet -- each input carries its declared range and a null
value. Solving needs the branch predicates, which today survive only as English
inside `testSteps[].text`. Until then this emits the shape with the values missing,
which is honest, rather than a guess a generator would trust.
"""
import json
import os

from .registry import register
from utils import get_range, log

FORMAT_VERSION = "1.0"
LEVEL_UT = "UT"

# Top-level keys in test_specs.json that are not unit entries.
_RESERVED = ("unitNames", "dynamicSpecs")


def _split_qualified(qualified_name):
    """`Class::method` -> ("Class", "method"); a free function -> ("", name).

    Most of the target firmware is C-style, so the empty ClassName is the common
    case, not the edge one.
    """
    qn = qualified_name or ""
    if "::" not in qn:
        return "", qn
    owner, _, method = qn.rpartition("::")
    return owner, method


def _inputs(spec, dd):
    """One entry per readable input, with its range and an unsolved value.

    The spec's Input already excludes what has no value to set -- out-parameters,
    write-only globals, void mocks. Ranges come from the data dictionary rather
    than from parsing them back out of the display text.
    """
    out = []
    for entry in (spec.get("input") or {}).get("entries") or ():
        rng = get_range(entry.get("type") or "", dd)
        item = {"name": entry.get("name", ""),
                "type": entry.get("type", ""),
                "kind": entry.get("kind", ""),
                "value": None}
        if rng and rng not in ("NA", "VOID"):
            item["range"] = rng
        out.append(item)
    return out


def _preconditions(spec):
    """Globals the case must set up, with the initial value the model recorded."""
    globals_ = []
    for g in (spec.get("precondition") or {}).get("globals") or ():
        entry = {"name": g.get("name", ""), "type": g.get("type", "")}
        if g.get("value") not in (None, ""):
            entry["initialValue"] = g["value"]
        globals_.append(entry)
    return {"globals": globals_}


def _stubs(spec):
    """Every stubbed callee, with what a generator needs to write it.

    Emitted per case rather than per function, even though the list is currently
    the function's whole set: narrowing it to the callees a given path actually
    reaches needs a mock-to-step mapping the transcription does not yet carry.

    Over-listing a stub is harmless -- an unused stub is registered and never
    called. Over-*asserting* one is not, which is why `expected` carries no
    called-mocks list; see `_cases_for`.
    """
    return [dict(m) for m in (spec.get("precondition") or {}).get("mocks") or ()]


def _case_name(func_name, ret, step):
    """A sentence a reviewer can check against the code."""
    if ret is None:
        return f"{func_name} completes"
    expr = ret.get("expression") or ret.get("source") or ""
    where = f" at step {step}" if step else ""
    return f"{func_name} returns {expr}{where}".replace("  ", " ")


def _cases_for(spec, dd, review):
    """One case per return path; one case overall when the spec names no return.

    A void function, or one whose control flow was never transcribed, still needs
    a case -- it just has nothing to assert a return value against.

    `expected` names no called mocks. The spec's mock list is the union over every
    path, so on any one path most of it did not run: asserting it would fail three
    times out of four on a four-way branch. Which mock a path reaches is knowable
    -- the transcription writes "expect mock function X" into a step -- but only as
    prose, so it waits on the same structural work as the branch predicates.
    """
    base_id = spec.get("testCaseId") or ""
    class_name, function_name = _split_qualified(spec.get("qualifiedName", ""))
    shared = {
        "level": LEVEL_UT,
        # No requirements source exists yet (Polarion / SWE.1); emitted empty
        # rather than omitted, so the field's absence is never mistaken for a
        # traced-but-unlinked case.
        "trace": "",
        "review": dict(review),
        "target": {"ClassName": class_name, "FunctionName": function_name},
        "preconditions": _preconditions(spec),
        "stubs": _stubs(spec),
        "inputs": _inputs(spec, dd),
    }
    returns = (spec.get("expected") or {}).get("returns") or []
    if not returns:
        case = {"id": base_id, "name": _case_name(spec.get("name", ""), None, "")}
        case.update(shared)
        case["expected"] = {"return": None}
        return [case]

    cases = []
    for index, ret in enumerate(returns, start=1):
        step = ret.get("step", "")
        # The suffix scheme is provisional -- see UT_EXPORT_SPEC.md Open items.
        case = {"id": f"{base_id}_{index:02d}",
                "name": _case_name(spec.get("name", ""), ret, step)}
        case.update(shared)
        case["expected"] = {
            # `expression` is the source expression, so a return of `libAdd()` or
            # `sample` stays symbolic. Resolving it to a literal is the same step
            # as choosing the inputs, and neither is solved yet.
            "return": ret.get("expression", ""),
            "atStep": step,
        }
        cases.append(case)
    return cases


def _environment(config):
    """Harness settings, carried from config verbatim (REQ-UE-05).

    These describe the test environment, not our source -- there is nothing here
    to derive, and synthesising a value would be inventing one.
    """
    cfg = ((config.get("views", {}) or {}).get("utExport", {}) or {})
    env = cfg.get("environment") or {}
    return {"flags": list(env.get("flags") or []),
            "probepoint": list(env.get("probepoint") or []),
            "usercode": list(env.get("usercode") or [])}


def _review(config):
    """DO-178C author/reviewer. Not derivable from code -- configuration only."""
    cfg = ((config.get("views", {}) or {}).get("utExport", {}) or {})
    review = cfg.get("review") or {}
    return {"author": review.get("author", ""), "reviewer": review.get("reviewer", "")}


def _iter_specs(test_specs):
    """Every spec that becomes cases, function specs then dynamic ones.

    Both kinds are unit-test specifications (REQ-UE-01) and share Table A's shape,
    so one loop covers them.
    """
    for key, unit in test_specs.items():
        if key in _RESERVED or not isinstance(unit, dict):
            continue
        for spec in unit.get("functions") or ():
            yield spec
    dynamic = test_specs.get("dynamicSpecs")
    if isinstance(dynamic, dict):
        for specs in dynamic.values():
            for spec in specs or ():
                yield spec
    elif isinstance(dynamic, list):
        for spec in dynamic:
            yield spec


@register("utExport")
def run(model, output_dir, model_dir, config):
    specs_path = os.path.join(output_dir, "test_specs.json")
    if not os.path.isfile(specs_path):
        log("no test_specs.json under %s - nothing to export" % output_dir,
            component="utExport")
        return
    with open(specs_path, encoding="utf-8") as f:
        test_specs = json.load(f)

    dd = model.get("dataDictionary", {}) or {}
    review = _review(config)
    cases = []
    for spec in _iter_specs(test_specs):
        cases.extend(_cases_for(spec, dd, review))

    payload = {"format_version": FORMAT_VERSION,
               "environment": _environment(config),
               "cases": cases}

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "ut_export.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    log("%s (%d case(s) from %d spec(s))"
        % (out_path, len(cases), sum(1 for _ in _iter_specs(test_specs))),
        component="utExport")
