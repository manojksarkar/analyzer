"""Audit every generated test_specs.json against docs/spec/SWE4_WIKI.md.

Throwaway review aid, not wired into the engine. Checks the rules that are
mechanically checkable, so a human review can concentrate on wording and content.

    python tools/swe4_audit.py            # all groups under output/
"""
import glob
import json
import os
import sys

MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model")


def load(name):
    with open(os.path.join(MODEL, name), encoding="utf-8") as f:
        return json.load(f)


def check_spec(spec, funcs, findings, group, unit):
    name = spec.get("name", "?")
    where = f"{group}/{unit}/{name}"
    pre = spec.get("precondition", {})
    inp = spec.get("input", {})
    exp = spec.get("expected", {})
    entries = inp.get("entries") or []
    kinds = {}
    for e in entries:
        kinds.setdefault(e.get("kind"), []).append(e)

    # R: Precondition mocks and Expected mocks must be the same set.
    if sorted(pre.get("mockFunctions") or []) != sorted(exp.get("mockFunctions") or []):
        findings.append((where, "mock list differs between Precondition and Expected"))

    # R: every value-returning mock appears in Input; void mocks do not.
    for m in pre.get("mockFunctions") or []:
        short = m[:-2]
        callee = next((f for f in funcs.values()
                       if (f.get("qualifiedName") or "").split("::")[-1] == short), None)
        if callee is None:
            continue
        ret = (callee.get("returnType") or "").strip().lower()
        in_input = any(e.get("name") == m for e in kinds.get("mockReturn", []))
        if ret and ret != "void" and not in_input:
            findings.append((where, f"mock {m} returns {ret} but is not an Input"))
        if ret == "void" and in_input:
            findings.append((where, f"void mock {m} must not be an Input"))

    # R: out-parameters and write-only globals are excluded from Input.
    in_names = {e.get("name") for e in entries}
    for o in exp.get("outParameters") or []:
        if o.get("name") in in_names:
            findings.append((where, f"out-parameter {o.get('name')} is also an Input"))

    # R: Input is VOID only when there is nothing to read.
    if inp.get("isVoid") and entries:
        findings.append((where, "isVoid set but Input has entries"))
    if not inp.get("isVoid") and not entries:
        findings.append((where, "Input empty but isVoid not set"))

    # R: every return entry names the step it came from.
    for r in exp.get("returns") or []:
        if not (r.get("step") or r.get("steps")):
            findings.append((where, f"return {r.get('text','')[:40]!r} names no step"))

    # R: Test Steps numbering is well formed and starts at 1.
    steps = spec.get("testSteps") or []
    if steps:
        if steps[0].get("number") != "1":
            findings.append((where, f"Test Steps start at {steps[0].get('number')}, not 1"))
        for s in steps:
            if not s.get("text"):
                findings.append((where, f"step {s.get('number')} has no text"))

    # R: a spec with a CFG should assert at least one return unless void.
    rt = (spec.get("returnType") or "").strip().lower()
    if steps and rt and rt != "void" and not (exp.get("returns") or []):
        findings.append((where, f"returns {rt} but Expected asserts no return"))

    # R: Table B fields present.
    if not spec.get("testCaseId"):
        findings.append((where, "no Test Case ID"))
    if spec.get("generationMethod") != "Analysis of Requirements":
        findings.append((where, f"generation method is {spec.get('generationMethod')!r}"))


def main():
    funcs = load("functions.json")
    findings = []
    totals = {"groups": 0, "specs": 0, "withSteps": 0}
    for path in sorted(glob.glob(os.path.join("output", "*", "test_specs.json"))):
        group = os.path.basename(os.path.dirname(path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        totals["groups"] += 1
        for unit_key, unit in data.items():
            if unit_key == "unitNames":
                continue
            for spec in unit.get("functions") or []:
                totals["specs"] += 1
                if spec.get("testSteps"):
                    totals["withSteps"] += 1
                check_spec(spec, funcs, findings, group, unit_key)

    print(f"groups={totals['groups']}  specs={totals['specs']}  "
          f"with Test Steps={totals['withSteps']}")
    if not findings:
        print("\nNo rule violations found.")
        return 0
    print(f"\n{len(findings)} finding(s):")
    for where, msg in findings:
        print(f"  {where}: {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
