"""Audit every generated ut_export.json against docs/spec/UT_EXPORT_SPEC.md.

Companion to swe4_audit.py, which audits the specs themselves. This checks the
export, and the strongest checks are CROSS-FILE: ut_export.json is derived from
test_specs.json in the same directory, so the two must agree about how many cases
a function has, which step each one exits from, and what it returns there. A rule
broken inside one file alone is usually a typo; a disagreement between them means
the derivation drifted.

Reads only from output/ -- never model/*.json, which does not survive the move to
a database backing.

    python tools/ut_export_audit.py            # all groups under output/
    python tools/ut_export_audit.py output/My-Sample
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CASE_FIELDS = ("id", "name", "level", "trace", "review", "target",
               "preconditions", "stubs", "inputs", "expected")
RESERVED = ("unitNames", "dynamicSpecs")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def specs_by_test_case_id(test_specs):
    """`testCaseId -> spec`, over both spec kinds."""
    out = {}
    for key, unit in test_specs.items():
        if key in RESERVED or not isinstance(unit, dict):
            continue
        for spec in unit.get("functions") or ():
            out[spec.get("testCaseId", "")] = spec
    dynamic = test_specs.get("dynamicSpecs")
    for spec in (sum(dynamic.values(), []) if isinstance(dynamic, dict)
                 else (dynamic or [])):
        out[spec.get("testCaseId", "")] = spec
    return out


def check_envelope(payload, findings, group):
    if not payload.get("format_version"):
        findings.append((group, "no format_version"))
    env = payload.get("environment")
    if not isinstance(env, dict):
        findings.append((group, "environment missing or not an object"))
    else:
        for key in ("flags", "probepoint", "usercode"):
            if not isinstance(env.get(key), list):
                findings.append((group, f"environment.{key} is not a list"))
    if not isinstance(payload.get("cases"), list):
        findings.append((group, "cases missing or not a list"))


def check_case(case, spec, findings, where):
    # R: every field the format names, in the order it names them.
    missing = [f for f in CASE_FIELDS if f not in case]
    if missing:
        findings.append((where, f"missing field(s): {', '.join(missing)}"))
    present = [k for k in case if k in CASE_FIELDS]
    if present != [f for f in CASE_FIELDS if f in case]:
        findings.append((where, f"fields out of order: {', '.join(present)}"))

    # R: everything SWE.4 emits is a unit test (REQ-UE-01).
    if case.get("level") != "UT":
        findings.append((where, f"level is {case.get('level')!r}, expected 'UT'"))

    # R: trace is present but empty -- no requirements source exists yet.
    if case.get("trace"):
        findings.append((where, "trace is set, but no requirements source exists"))

    # R: a free function has no ClassName; a member function has both.
    target = case.get("target") or {}
    if not target.get("FunctionName"):
        findings.append((where, "target.FunctionName is empty"))

    if spec is None:
        findings.append((where, "no spec in test_specs.json for this id"))
        return

    # R (cross-file): the step this case exits from must exist in the spec's steps.
    step = (case.get("expected") or {}).get("atStep")
    numbers = {s.get("number") for s in spec.get("testSteps") or ()}
    if step and numbers and step not in numbers:
        findings.append((where, f"expected.atStep {step!r} is not a step of the spec"))

    # R (cross-file): and it must return what the spec says it returns there.
    if step:
        ret = next((r for r in (spec.get("expected") or {}).get("returns") or ()
                    if r.get("step") == step), None)
        if ret is None:
            findings.append((where, f"no return at step {step!r} in the spec"))
        elif (case.get("expected") or {}).get("return") != ret.get("expression"):
            findings.append((where, f"return at step {step} disagrees with the spec"))

    # R: a stub must be writable -- a name alone cannot be turned into one.
    spec_mocks = {m.get("name") for m in (spec.get("precondition") or {}).get("mocks") or ()}
    for stub in case.get("stubs") or ():
        name = stub.get("name")
        if not name:
            findings.append((where, "stub with no name"))
            continue
        if name not in spec_mocks:
            findings.append((where, f"stub {name} is not a mock of the spec"))
        if not stub.get("returnType"):
            findings.append((where, f"stub {name} has no returnType"))
        if "parameters" not in stub:
            findings.append((where, f"stub {name} has no parameter list"))

    # R: expected must not assert mocks -- the list is the union over all paths.
    if "calls" in (case.get("expected") or {}):
        findings.append((where, "expected.calls asserts mocks not reached on this path"))


def audit_group(out_dir, findings, totals):
    export_path = os.path.join(out_dir, "ut_export.json")
    specs_path = os.path.join(out_dir, "test_specs.json")
    if not os.path.isfile(export_path):
        return
    group = os.path.basename(out_dir)
    totals["groups"] += 1
    payload = load(export_path)
    check_envelope(payload, findings, group)

    specs = specs_by_test_case_id(load(specs_path)) if os.path.isfile(specs_path) else {}
    if not specs:
        findings.append((group, "no test_specs.json beside the export - cross-checks skipped"))

    seen = set()
    per_spec = {}
    for case in payload.get("cases") or ():
        cid = case.get("id", "?")
        totals["cases"] += 1
        where = f"{group}/{cid}"
        # R: an id identifies one case.
        if cid in seen:
            findings.append((where, "duplicate case id"))
        seen.add(cid)
        # Every case id is `<specId>_<path>` -- uniformly, so that stripping one
        # suffix always yields the spec. Interface ids end in `_NN` themselves, so
        # a conditional strip cannot tell the two numbers apart.
        base = cid.rsplit("_", 1)[0] if "_" in cid else cid
        per_spec.setdefault(base, []).append(case)
        check_case(case, specs.get(base), findings, where)
        if any(i.get("value") is None for i in case.get("inputs") or ()):
            totals["unsolved"] += 1

    # R (cross-file): one case per return, or exactly one when there is no return.
    for base, cases in per_spec.items():
        spec = specs.get(base)
        if spec is None:
            continue
        expected = len((spec.get("expected") or {}).get("returns") or ()) or 1
        if len(cases) != expected:
            findings.append((f"{group}/{base}",
                             f"{len(cases)} case(s) for {expected} return path(s)"))


def main():
    targets = sys.argv[1:] or sorted(
        d for d in glob.glob(os.path.join(ROOT, "output", "*")) if os.path.isdir(d))
    findings = []
    totals = {"groups": 0, "cases": 0, "unsolved": 0}
    for target in targets:
        audit_group(target, findings, totals)

    print(f"groups={totals['groups']}  cases={totals['cases']}  "
          f"cases with unsolved inputs={totals['unsolved']}")
    if not findings:
        print("\nNo rule violations found.")
        return 0
    print(f"\n{len(findings)} finding(s):")
    for where, msg in findings:
        print(f"  {where}: {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
