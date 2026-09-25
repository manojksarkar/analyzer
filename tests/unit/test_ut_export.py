"""utExport view: test_specs.json -> the unit-test automation JSON.

Rules under test come from docs/spec/UT_EXPORT_SPEC.md.
"""
import os
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from views.ut_export import (  # noqa: E402
    _cases_for, _environment, _iter_specs, _review, _split_qualified, LEVEL_UT,
)


def _spec(**over):
    spec = {
        "testCaseId": "TC_IF_01",
        "name": "f",
        "qualifiedName": "f",
        "precondition": {"mocks": [{"name": "dep", "returnType": "int",
                                    "parameters": [], "declaredIn": "D.h"}],
                         "globals": []},
        "input": {"entries": [{"kind": "parameter", "name": "a", "type": "int"}]},
        "expected": {"returns": [{"step": "2.1", "expression": "0"},
                                 {"step": "2.2", "expression": "a"}]},
    }
    spec.update(over)
    return spec


def _cases(**over):
    return _cases_for(_spec(**over), {}, {"author": "", "reviewer": ""})


# --- one case per path (REQ-UE-04) -----------------------------------------

def test_each_return_becomes_its_own_case():
    """A spec covers every exit in one row because that is what the document
    renders; the export is per test case, so the paths split back out."""
    cases = _cases()
    assert [c["id"] for c in cases] == ["TC_IF_01_01", "TC_IF_01_02"]


def test_each_case_expects_the_return_of_its_own_path():
    cases = _cases()
    assert [(c["expected"]["return"], c["expected"]["atStep"]) for c in cases] == [
        ("0", "2.1"), ("a", "2.2")]


def test_a_spec_with_no_return_still_yields_one_case():
    """A void function has nothing to assert a return against, but skipping it
    would leave the function untested rather than trivially tested."""
    cases = _cases(expected={"returns": []})
    assert len(cases) == 1
    assert cases[0]["expected"]["return"] is None


def test_every_case_id_carries_a_path_suffix():
    """Interface ids already end in `_NN`, so a bare id on a no-return spec is
    indistinguishable from a path index: `TC_IF_LAYER1_CORE_02` could be spec 02
    with one path, or spec CORE path 02. Suffixing uniformly removes the guess."""
    assert _cases(expected={"returns": []})[0]["id"] == "TC_IF_01_01"
    assert [c["id"] for c in _cases()] == ["TC_IF_01_01", "TC_IF_01_02"]


def test_expected_asserts_no_called_mocks():
    """The mock list is the union over every path, so on any one path most of it
    did not run. Asserting it would fail on every path but one."""
    for case in _cases():
        assert "calls" not in case["expected"]


# --- case content ----------------------------------------------------------

def test_every_case_is_a_unit_test():
    assert {c["level"] for c in _cases()} == {LEVEL_UT}


def test_trace_is_present_but_empty():
    """No requirements source exists yet. Emitted empty rather than omitted, so a
    missing field is never read as 'traced, link unknown'."""
    assert all(c["trace"] == "" for c in _cases())


def test_free_function_has_no_class_name():
    assert _split_qualified("coreNestedBranch") == ("", "coreNestedBranch")


def test_member_function_splits_into_class_and_method():
    assert _split_qualified("SignalProcessor::normalize") == (
        "SignalProcessor", "normalize")


def test_stubs_carry_the_signature():
    stub = _cases()[0]["stubs"][0]
    assert stub["returnType"] == "int" and stub["declaredIn"] == "D.h"


def test_inputs_carry_a_range_and_an_unsolved_value():
    """Without a solution (no CFG for the function) the value stays missing rather
    than guessed. With one, see the run() tests below (REQ-UE-06)."""
    entry = _cases()[0]["inputs"][0]
    assert entry["value"] is None
    assert entry["range"] == "-0x80000000-0x7FFFFFFF"


def test_global_initial_value_reaches_preconditions():
    spec = _spec(precondition={"mocks": [], "globals": [
        {"name": "gFlag", "type": "int", "value": "7"}]})
    pre = _cases_for(spec, {}, {"author": "", "reviewer": ""})[0]["preconditions"]
    assert pre["globals"] == [{"name": "gFlag", "type": "int", "initialValue": "7"}]


# --- configuration, not derivation (REQ-UE-05) -----------------------------

def test_environment_is_carried_from_config_verbatim():
    cfg = {"views": {"utExport": {"environment": {
        "flags": ["-std=c++14"], "probepoint": ["p"], "usercode": ["init();"]}}}}
    assert _environment(cfg) == {"flags": ["-std=c++14"], "probepoint": ["p"],
                                 "usercode": ["init();"]}


def test_environment_is_empty_when_unconfigured():
    """Nothing here is derivable from source; an absent config means empty, never
    a synthesised value."""
    assert _environment({}) == {"flags": [], "probepoint": [], "usercode": []}


def test_review_comes_from_config():
    cfg = {"views": {"utExport": {"review": {"author": "A", "reviewer": "B"}}}}
    assert _review(cfg) == {"author": "A", "reviewer": "B"}


# --- both spec kinds are unit tests (REQ-UE-01) ----------------------------

def test_dynamic_behaviour_specs_are_exported_too():
    """Both SWE.4 spec kinds are unit-test specifications, so both become cases."""
    test_specs = {
        "unitNames": {"C|U": "U"},
        "C|U": {"name": "U", "functions": [_spec()]},
        "dynamicSpecs": {"C": [_spec(testCaseId="TC_DYN_01")]},
    }
    assert [s["testCaseId"] for s in _iter_specs(test_specs)] == ["TC_IF_01", "TC_DYN_01"]


# --- the whole view: solved values + the target format (REQ-UE-06..10) -----

import json  # noqa: E402

from views import ut_export  # noqa: E402

TOOLS = os.path.join(os.path.dirname(ENGINE), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import check_ut_json  # noqa: E402

_UNIT = "Layer1.Sample-Core|Core"
_FID = f"{_UNIT}|coreNestedBranch|int,int"


def _view_spec():
    """coreNestedBranch from the Sample: two nested `> 0` checks, two stubs."""
    mocks = [{"functionId": f"Layer1.Lib|Lib|{n}|int,int", "name": n, "qualifiedName": n,
              "returnType": "int", "parameters": [{"name": "a", "type": "int"},
                                                  {"name": "b", "type": "int"}],
              "declaredIn": "Layer1/Sample/Lib/Lib.h"} for n in ("libAdd", "utilCompute")]
    steps = [("2", "N3"), ("2.a.1", "N4"), ("2.a.1.a", "N5"), ("2.a.1.b", "N6"),
             ("2.b.1", "N7"), ("2.b.1.a", "N8"), ("2.b.1.b", "N9")]
    return {
        "functionId": _FID, "testCaseId": "TC_IF_CORE_06", "name": "coreNestedBranch",
        "qualifiedName": "coreNestedBranch", "unitKey": _UNIT, "unitName": "Core",
        "returnType": "int", "location": {"file": "Layer1/Sample/Core/Core.cpp", "line": 112},
        "precondition": {"mockFunctions": ["libAdd()", "utilCompute()"], "mocks": mocks,
                         "parameters": [{"name": "a", "type": "int"},
                                        {"name": "b", "type": "int"}],
                         "globals": []},
        "input": {"entries": [{"kind": "parameter", "name": "a", "type": "int"},
                              {"kind": "parameter", "name": "b", "type": "int"},
                              {"kind": "mockReturn", "name": "libAdd()", "type": "int"},
                              {"kind": "mockReturn", "name": "utilCompute()", "type": "int"}]},
        "expected": {"returns": [{"step": "2.a.1.a", "expression": "libAdd()"},
                                 {"step": "2.a.1.b", "expression": "utilCompute()"},
                                 {"step": "2.b.1.a", "expression": "7"},
                                 {"step": "2.b.1.b", "expression": "0"}],
                     "outParameters": [], "globals": []},
        "testSteps": [{"number": n, "nodeId": i} for n, i in steps],
    }


def _view_cfg():
    nodes = [("N1", "START", "coreNestedBranch(int a, int b)"), ("N2", "END", "End"),
             ("N3", "DECISION", "a > 0"), ("N4", "DECISION", "b > 0"),
             ("N5", "RETURN", "return libAdd(a, b)"),
             ("N6", "RETURN", "return utilCompute(a, -b)"),
             ("N7", "DECISION", "b > 0"), ("N8", "RETURN", "return 7"),
             ("N9", "RETURN", "return 0")]
    edges = [("N1", "N3", None), ("N3", "N4", "Yes"), ("N3", "N7", "No"),
             ("N4", "N5", "Yes"), ("N4", "N6", "No"), ("N7", "N8", "Yes"),
             ("N7", "N9", "No")] + [(r, "N2", None) for r in ("N5", "N6", "N8", "N9")]
    return {"entry": "N1", "exits": ["N2"],
            "nodes": [{"id": i, "type": t, "rawCode": r, "label": r} for i, t, r in nodes],
            "edges": [{"source": s, "target": d, "label": lab} for s, d, lab in edges]}


def _lib_spec():
    """The same shape in a second component, so two group runs share one `ut/`."""
    spec = _view_spec()
    spec.update({"functionId": "Layer1.Lib|Lib|libNested|int,int", "testCaseId": "TC_IF_LIB_01",
                 "name": "libNested", "qualifiedName": "libNested",
                 "unitKey": "Layer1.Lib|Lib", "unitName": "Lib",
                 "location": {"file": "Layer1/Sample/Lib/Lib.cpp", "line": 10}})
    return spec


def _groups_config(*components):
    """A config naming `components` (bare names) as groups of Layer1."""
    return {"views": {"utExport": {"review": {"author": "A", "reviewer": "B"}}},
            "cores": {"Core1": {}},
            "layers": {"Layer1": {"cores": ["Core1"],
                                  "groups": {c: {c: f"Sample/{c}"} for c in components}}}}


def _run_view(tmp_path, monkeypatch, config=None, with_cfg=True, group="Layer1.Sample-Core",
              spec=None, specs=True):
    """One group run of the view, laid out as the pipeline lays it out:
    <tmp>/output/<group>/ for the group, <tmp>/output/ut/ for the target format.
    Returns the group folder."""
    out, model_dir = tmp_path / "output" / group, tmp_path / "model"
    (out / "flowcharts").mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(exist_ok=True)
    spec = spec or _view_spec()
    uk = spec["unitKey"]
    payload = ({"unitNames": {uk: spec["unitName"]},
                uk: {"name": spec["unitName"], "functions": [spec]}, "dynamicSpecs": {}}
               if specs else {"unitNames": {}, "dynamicSpecs": {}})
    (out / "test_specs.json").write_text(json.dumps(payload), encoding="utf-8")
    if with_cfg:
        (out / "flowcharts" / f"{spec['unitName']}.json").write_text(json.dumps(
            [{"functionKey": spec["functionId"], "name": spec["name"], "cfg": _view_cfg()}]),
            encoding="utf-8")
    (model_dir / "clang_macros.json").write_text(
        json.dumps({"Layer1": ["-DMAX_LUN=8"]}), encoding="utf-8")
    (model_dir / "clang_include_paths.json").write_text(
        json.dumps({"Layer1": ["C:/w/p/Layer1/Sample/Core", "C:/w/p/Layer1/Sample/Lib"]}),
        encoding="utf-8")
    monkeypatch.setattr(ut_export, "_base_path", lambda: "")
    cfg = config or {"views": {"utExport": {"review": {"author": "A", "reviewer": "B"}}},
                     "cores": {"Core1": {}}, "layers": {"Layer1": {"cores": ["Core1"]}}}
    ut_export.run({"functions": {}, "dataDictionary": {}}, str(out), str(model_dir), cfg)
    return out


def _ut(group_dir):
    return group_dir.parent / "ut"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sections(ut):
    return _load(ut / "hierarchy.json")["LayerMapping"]["Layer1"]["Sections"]


def test_our_format_gets_the_solved_values(tmp_path, monkeypatch):
    cases = _load(_run_view(tmp_path, monkeypatch) / "ut_export.json")["cases"]
    got = [({i["name"]: i["value"] for i in c["inputs"]}, c["expected"]["value"])
           for c in cases]
    assert got == [({"a": "1", "b": "1", "libAdd()": "1", "utilCompute()": "1"}, "1"),
                   ({"a": "1", "b": "0", "libAdd()": "1", "utilCompute()": "1"}, "1"),
                   ({"a": "0", "b": "1", "libAdd()": "1", "utilCompute()": "1"}, "7"),
                   ({"a": "0", "b": "0", "libAdd()": "1", "utilCompute()": "1"}, "0")]
    assert {c["solve"]["status"] for c in cases} == {"solved"}
    # Our shape is otherwise untouched: the source expression stays next to the value.
    assert cases[0]["expected"]["return"] == "libAdd()"
    assert cases[0]["target"] == {"ClassName": "", "FunctionName": "coreNestedBranch"}


def test_target_format_files_are_written_and_valid(tmp_path, monkeypatch):
    ut = _ut(_run_view(tmp_path, monkeypatch))
    assert sorted(p.name for p in ut.iterdir()) == ["Layer1_Sample_Core_Core_TS.json",
                                                    "hierarchy.json"]
    for name, template in (("Layer1_Sample_Core_Core_TS.json", "testcase"),
                           ("hierarchy.json", "hierarchy")):
        payload = _load(ut / name)
        found = check_ut_json.run(
            payload, check_ut_json.load(check_ut_json.template_path(template)))
        assert found.count("ERROR") == 0 and found.count("WARN") == 0, (
            check_ut_json.render(found, name, template))
    first = _load(ut / "Layer1_Sample_Core_Core_TS.json")["cases"][0]
    assert first["target"] == {"unit": "Core", "function": "coreNestedBranch"}
    assert first["inputs"] == [{"param": "a", "value": "1"}, {"param": "b", "value": "1"}]
    assert first["expected"]["stub_params"] == [
        {"unit": "Lib", "function": "libAdd",
         "params": {"a": {"value": "1"}, "b": {"value": "1"}}}]
    h = _load(ut / "hierarchy.json")
    env = h["LayerMapping"]["Layer1"]["Sections"]["Core"]["TestEnvironments"][
        "Layer1_Sample_Core_Core_TS"]
    assert env["CoreType"] == "Core1"
    assert env["Testcase"] == "Layer1_Sample_Core_Core_TS.json"
    assert h["Macros"] == {"Core1Macros": ["MAX_LUN=8"]}
    # No metadata basePath here: the root is recovered from the include dirs.
    assert h["LayerMapping"]["Layer1"]["searchdirectories"] == ["Layer1/Sample/Core",
                                                                "Layer1/Sample/Lib"]


def test_a_rerun_writes_identical_files(tmp_path, monkeypatch):
    first = _run_view(tmp_path / "a", monkeypatch)
    second = _run_view(tmp_path / "b", monkeypatch)
    assert (first / "ut_export.json").read_bytes() == (second / "ut_export.json").read_bytes()
    for name in ("Layer1_Sample_Core_Core_TS.json", "hierarchy.json"):
        assert (_ut(first) / name).read_bytes() == (_ut(second) / name).read_bytes(), name


def test_target_format_can_be_switched_off(tmp_path, monkeypatch):
    out = _run_view(tmp_path, monkeypatch,
                    config={"views": {"utExport": {"targetFormat": False}}})
    assert (out / "ut_export.json").is_file()
    assert not _ut(out).exists() and not (out / "ut").exists()


# --- one project-level ut/ folder, one hierarchy (REQ-UE-09) -----------------

def test_every_group_writes_into_one_folder_with_one_hierarchy(tmp_path, monkeypatch):
    cfg = _groups_config("Sample-Core", "Lib")
    core = _run_view(tmp_path, monkeypatch, config=cfg)
    lib = _run_view(tmp_path, monkeypatch, config=cfg, group="Layer1.Lib", spec=_lib_spec())
    ut = _ut(core)
    assert _ut(lib) == ut
    assert sorted(p.name for p in ut.iterdir()) == [
        "Layer1_Lib_Lib_TS.json", "Layer1_Sample_Core_Core_TS.json", "hierarchy.json"]
    assert not (core / "ut").exists() and not (lib / "ut").exists()
    sections = _sections(ut)
    assert sorted(sections) == ["Core", "Lib"]
    assert sections["Lib"]["TestEnvironments"]["Layer1_Lib_Lib_TS"]["FilePath"] == \
        "Layer1/Sample/Lib/Lib.cpp"
    found = check_ut_json.run(_load(ut / "hierarchy.json"),
                              check_ut_json.load(check_ut_json.template_path("hierarchy")))
    assert found.count("ERROR") == 0 and found.count("WARN") == 0


def test_generating_a_group_again_does_not_duplicate_it(tmp_path, monkeypatch):
    cfg = _groups_config("Sample-Core", "Lib")
    core = _run_view(tmp_path, monkeypatch, config=cfg)
    _run_view(tmp_path, monkeypatch, config=cfg, group="Layer1.Lib", spec=_lib_spec())
    before = (_ut(core) / "hierarchy.json").read_bytes()
    _run_view(tmp_path, monkeypatch, config=cfg)
    assert (_ut(core) / "hierarchy.json").read_bytes() == before


def test_a_component_removed_from_the_config_leaves_no_trace(tmp_path, monkeypatch):
    """Its old group folder may linger on disk; its test-case file and its
    hierarchy entry must not."""
    core = _run_view(tmp_path, monkeypatch, config=_groups_config("Sample-Core", "Lib"))
    lib = _run_view(tmp_path, monkeypatch, config=_groups_config("Sample-Core", "Lib"),
                    group="Layer1.Lib", spec=_lib_spec())
    _run_view(tmp_path, monkeypatch, config=_groups_config("Sample-Core"))
    assert (lib / "test_specs.json").is_file()            # the stale folder is still there
    assert sorted(p.name for p in _ut(core).iterdir()) == [
        "Layer1_Sample_Core_Core_TS.json", "hierarchy.json"]
    assert sorted(_sections(_ut(core))) == ["Core"]


def test_a_unit_with_no_specs_any_more_is_dropped(tmp_path, monkeypatch):
    cfg = _groups_config("Sample-Core", "Lib")
    core = _run_view(tmp_path, monkeypatch, config=cfg)
    _run_view(tmp_path, monkeypatch, config=cfg, group="Layer1.Lib", spec=_lib_spec())
    _run_view(tmp_path, monkeypatch, config=cfg, group="Layer1.Lib", spec=_lib_spec(),
              specs=False)
    assert not (_ut(core) / "Layer1_Lib_Lib_TS.json").exists()
    assert sorted(_sections(_ut(core))) == ["Core"]


def test_only_test_case_files_are_ever_deleted(tmp_path, monkeypatch):
    """Pruning touches `*_TS.json` only -- anything else in the folder is not ours to remove."""
    core = _run_view(tmp_path, monkeypatch)
    keep = _ut(core) / "notes.txt"
    keep.write_text("mine", encoding="utf-8")
    _run_view(tmp_path, monkeypatch)
    assert keep.read_text(encoding="utf-8") == "mine"


def test_the_ut_folder_sits_beside_the_group_folders(tmp_path, monkeypatch):
    import importlib
    core_paths = importlib.import_module("core.paths")    # `core.paths` the name is the function
    root = tmp_path / "output"
    assert ut_export.output_root(str(root / "Layer1.Lib")) == str(root)
    # A run with no layers writes into the output root itself.
    monkeypatch.setattr(core_paths, "paths",
                        lambda: type("P", (), {"output_dir": str(root)})())
    assert ut_export.output_root(str(root)) == str(root)


def test_without_a_cfg_values_stay_null_and_say_why(tmp_path, monkeypatch):
    cases = _load(_run_view(tmp_path, monkeypatch, with_cfg=False) / "ut_export.json")["cases"]
    assert all(i["value"] is None for c in cases for i in c["inputs"])
    assert {c["solve"]["status"] for c in cases} == {"unsolved"}
    assert "control-flow graph" in cases[0]["solve"]["notes"][0]


def test_no_solutions_means_the_old_shape():
    """Called without solutions (as before), a case has no `solve` block and no
    `expected.value` -- consumers of the old shape see exactly the old shape."""
    case = _cases()[0]
    assert "solve" not in case and "value" not in case["expected"]


def test_infer_base_path_from_include_dirs():
    inc = {"L": ["C:/w/p/Layer1/Sample/Core", "C:/w/p/Layer1/Lib", "D:/sdk/inc"]}
    files = ["Layer1/Sample/Core/Core.cpp", "Layer1/Lib/Lib.cpp"]
    assert ut_export.infer_base_path(inc, files) == "C:/w/p"
    assert ut_export.infer_base_path({}, ["a/b.cpp"]) == ""
