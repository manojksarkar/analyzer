"""ut_target: our specs -> the target-format files (UT_EXPORT_SPEC REQ-UE-07..09).

The builders are pure: specs + solved values in, dicts out. The last tests run
`tools/check_ut_json.py` over what they build, so a mapping that drifts from the
templates in docs/spec/ut_templates/ fails here, not in a review.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "engine"), os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_ut_json  # noqa: E402
from views.ut_paths import NONNULL, Context  # noqa: E402
from views.ut_target import (  # noqa: E402
    PROTOTYPE_UNIT, _target, build_case, build_hierarchy, build_testcase_file,
    environment_name, ident, owner_of, rel_dir, split_unit_key,
)

REVIEW = {"author": "A", "reviewer": "B"}


def _spec(qn="coreAdd", fid="Layer1.Sample-Core|Core|coreAdd|int,int", mocks=(), entries=(),
          globals_=(), written=()):
    return {"name": qn.rpartition("::")[2], "qualifiedName": qn, "functionId": fid,
            "unitKey": fid.rsplit("|", 2)[0],
            "precondition": {"mocks": list(mocks), "globals": list(globals_),
                             "parameters": [{"name": e["name"], "type": e["type"]}
                                            for e in entries if e["kind"] == "parameter"]},
            "input": {"entries": list(entries)},
            "expected": {"returns": [], "globals": list(written)}}


LIB_ADD = {"functionId": "Layer1.Lib|Lib|libAdd|int,int", "name": "libAdd",
           "qualifiedName": "libAdd", "returnType": "int",
           "parameters": [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}]}
FIL_READ = {"functionId": "Layer1.Fil|FilNand|Fil::Nand::ReadPage|x", "name": "ReadPage",
            "qualifiedName": "Fil::Nand::ReadPage", "returnType": "int",
            "parameters": [{"name": "idx", "type": "uint16_t"}, {"name": "e", "type": "MapEntry *"}]}
NOTIFY = {"functionId": "Layer1.Hil|Hil|HilNotify|x", "name": "HilNotify",
          "qualifiedName": "HilNotify", "returnType": "void",
          "parameters": [{"name": "code", "type": "int"}]}


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

def test_unit_key_splits_into_layer_component_unit():
    assert split_unit_key("Layer1.Sample-Core|Core") == ("Layer1", "Sample-Core", "Core")
    assert split_unit_key("Comp|Unit") == ("", "Comp", "Unit")


def test_environment_name_is_layer_component_unit_ts():
    assert environment_name("Layer1.Sample-Core|Core") == "Layer1_Sample_Core_Core_TS"
    assert environment_name("Comp|Unit") == "Comp_Unit_TS"
    assert ident("My Sample--Core") == "My_Sample_Core"


def test_owner_is_the_class_for_a_member_and_the_unit_otherwise():
    assert owner_of("L.C|FtlMap|Ftl::Map::Lookup|x", "Ftl::Map::Lookup") == "Ftl::Map"
    assert owner_of("Layer1.Lib|Lib|libAdd|int,int", "libAdd") == "Lib"
    assert owner_of("Layer1.Sample-Core|Core|g_result", "g_result") == "Core"


@pytest.mark.parametrize("qn, target", [
    ("coreAdd", {"unit": "Core", "function": "coreAdd"}),
    ("Ftl::Map::Lookup", {"unit": "Ftl::Map", "function": "Lookup"}),
    ("Ftl::Map::Map", {"unit": "Ftl::Map", "class": "Ftl::Map", "function": "Ftl::Map",
                       "constructor": True}),
    ("Ftl::Map::~Map", {"unit": "Ftl::Map", "class": "Ftl::Map", "function": "~Ftl::Map",
                        "destructor": True}),
])
def test_target_for_free_function_method_constructor_destructor(qn, target):
    assert _target(_spec(qn=qn, fid=f"Layer1.Sample-Core|Core|{qn}|")) == target


def test_rel_dir_is_project_relative_or_unchanged():
    assert rel_dir("C:/w/p/Layer1/Core", "C:/w/p") == "Layer1/Core"
    assert rel_dir("C:\\w\\p\\Layer1", "C:/w/p") == "Layer1"
    assert rel_dir("D:/sdk/include", "C:/w/p") == "D:/sdk/include"


# ---------------------------------------------------------------------------
# one case
# ---------------------------------------------------------------------------

def _case(spec, values=None, ret=None, globals_after=None, stub_calls=(), writebacks=()):
    ctx = Context(spec, {"MapEntry": {"kind": "struct", "fields": []}})
    solution = {"status": "solved", "inputs": "solved", "expected": "known",
                "values": values or {}, "return": ret, "globals": globals_after or {},
                "stubCalls": list(stub_calls), "notes": []}
    return build_case("TC_01_01", "coreAdd returns 3", spec, solution, ctx, list(writebacks), REVIEW)


def test_a_case_carries_every_section_in_order():
    case = _case(_spec(entries=[{"kind": "parameter", "name": "a", "type": "int"}]),
                 values={"a": (2, None)}, ret="3")
    assert list(case) == ["id", "name", "level", "trace", "review", "target",
                          "preconditions", "stubs", "inputs", "expected"]
    assert case["inputs"] == [{"param": "a", "value": "2"}]
    assert case["expected"]["return"] == {"value": "3", "derived_from": ""}


def test_stub_mode_faked_without_write_back():
    case = _case(_spec(mocks=[LIB_ADD], entries=[
        {"kind": "mockReturn", "name": "libAdd()", "type": "int"}]),
        values={"libAdd()": (5, None)})
    assert case["stubs"] == [{"unit": "Lib", "function": "libAdd", "mode": "faked",
                              "returns": {"value": "5"}}]


def test_stub_mode_prototype_when_the_stub_writes_back():
    spec = _spec(mocks=[FIL_READ], entries=[
        {"kind": "mockReturn", "name": "ReadPage()", "type": "int"},
        {"kind": "mockWriteback", "name": "e.lba", "type": "uint32_t"}])
    wb = [{"label": "e.lba", "type": "uint32_t", "mock": FIL_READ["functionId"],
           "param": "e", "field": "lba"}]
    case = _case(spec, values={"ReadPage()": (0, None), "e.lba": (7, None)}, writebacks=wb)
    assert case["stubs"] == [{"unit": PROTOTYPE_UNIT, "function": "Fil::Nand::ReadPage",
                              "mode": "prototype", "returns": {"value": "0"},
                              "prototype_values": {"e.lba": "7"}}]


def test_a_void_stub_keeps_returns_with_an_empty_value():
    """Every stub in the format has `returns`; a void one says "nothing" with an
    empty value rather than dropping the key (the format is not changed)."""
    case = _case(_spec(mocks=[NOTIFY]))
    assert case["stubs"][0]["returns"] == {"value": ""}
    payload = build_testcase_file("E_TS", [case], {"flags": [], "probepoint": [], "usercode": []})
    assert _errors(payload, "testcase") == []


def test_globals_read_are_preconditions_and_written_ones_are_expected():
    spec = _spec(entries=[{"kind": "global", "name": "gErr", "type": "int",
                           "globalId": "Layer1.Sample-Core|Core|gErr"}],
                 globals_=[{"globalId": "Layer1.Sample-Core|Core|gErr", "name": "gErr"}],
                 written=[{"globalId": "Layer1.Sample-Core|Core|gErr", "name": "gErr"},
                          {"globalId": "Layer1.Sample-Core|Core|gLast", "name": "gLast"}])
    case = _case(spec, values={"gErr": (0, None)}, globals_after={"gErr": "1", "gLast": None})
    assert case["preconditions"]["globals"] == [{"unit": "Core", "name": "gErr", "value": "0"}]
    # gLast's value on this path is unknown: not asserted (the case's notes say why).
    assert case["expected"]["globals"] == [{"unit": "Core", "name": "gErr", "value": "1",
                                            "derived_from": ""}]


def test_stub_params_from_the_calls_on_the_path():
    case = _case(_spec(mocks=[LIB_ADD]), stub_calls=[("libAdd", {"a": "1", "b": "2"}),
                                                     ("libAdd", {})])
    assert case["expected"]["stub_params"] == [
        {"unit": "Lib", "function": "libAdd",
         "params": {"a": {"value": "1"}, "b": {"value": "2"}}}]


def test_struct_parameter_value_is_a_type_and_fields_object():
    spec = _spec(entries=[{"kind": "parameter", "name": "cfg", "type": "const Cfg *"}])
    ctx = Context(spec, {"Cfg": {"kind": "struct", "fields": [{"name": "mode", "type": "uint8_t"}]}})
    ctx.struct_field("cfg.mode")
    solution = {"values": {"cfg.mode": (3, None)}, "globals": {}, "stubCalls": []}
    case = build_case("TC", "n", spec, solution, ctx, [], REVIEW)
    assert case["inputs"] == [{"param": "cfg", "value": {"type": "Cfg", "fields": {"mode": "3"}}}]


def test_an_unset_pointer_input_is_null():
    spec = _spec(entries=[{"kind": "parameter", "name": "p", "type": "Foo *"}])
    case = _case(spec, values={"p": (NONNULL, None)})
    assert case["inputs"] == [{"param": "p", "value": None}]


# ---------------------------------------------------------------------------
# hierarchy
# ---------------------------------------------------------------------------

def _hierarchy(**over):
    kw = dict(macros_by_layer={"Layer1": ["-DMAX_LUN=8", "-DENABLE_DIAG"], "Layer2": ["-DX=1"]},
              includes_by_layer={"Layer1": ["C:/w/p/Layer1/Sample/Core", "D:/sdk/inc"]},
              cores_by_layer={"Layer1": ["Core1"], "Layer2": []},
              library_dirs={"Layer1": ["C:/w/p/lib"]},
              env_overrides={"Layer1_Sample_Core_Core_TS": {
                  "hierarchy": {"usercode": ["#include \"x.h\""]},
                  "testcase": {"usercode": [{"description": "d", "code": "c;"}]}}},
              base_path="C:/w/p")
    kw.update(over)
    units = [{"unitKey": "Layer1.Sample-Core|Core", "file": "Layer1/Sample/Core/Core.cpp"},
             {"unitKey": "Layer1.Lib|Core", "file": "Layer1/Lib/Core.h"},
             {"unitKey": "Layer2.Plat|Gpio", "file": "Layer2/Plat/Gpio.cpp"}]
    return build_hierarchy(units, **kw)


def test_macros_are_keyed_by_core_and_by_layer_without_one():
    h = _hierarchy()
    assert h["Macros"] == {"Core1Macros": ["MAX_LUN=8", "ENABLE_DIAG"], "Layer2Macros": ["X=1"]}


def test_one_section_and_one_environment_per_unit():
    layer1 = _hierarchy()["LayerMapping"]["Layer1"]
    assert layer1["searchdirectories"] == ["Layer1/Sample/Core", "D:/sdk/inc"]
    assert layer1["Librarydirectories"] == ["C:/w/p/lib"]
    # Two units named Core in one layer: the second is qualified by its component.
    assert sorted(layer1["Sections"]) == ["Core", "Sample-Core.Core"]
    env = layer1["Sections"]["Sample-Core.Core"]["TestEnvironments"]["Layer1_Sample_Core_Core_TS"]
    assert env["CoreType"] == "Core1"
    assert env["Filename"] == "Core.cpp" and env["IsHeader"] is False
    assert env["usercode"] == ["#include \"x.h\""]
    assert env["Testcase"] == "Layer1_Sample_Core_Core_TS.json"
    header_env = layer1["Sections"]["Core"]["TestEnvironments"]["Layer1_Lib_Core_TS"]
    assert header_env["IsHeader"] is True


# ---------------------------------------------------------------------------
# the validator agrees
# ---------------------------------------------------------------------------

def _errors(payload, template):
    out = check_ut_json.run(payload, check_ut_json.load(check_ut_json.template_path(template)))
    return [r for r in out.rows() if r[0] in ("ERROR", "WARN")]


def test_built_testcase_file_matches_the_template():
    spec = _spec(mocks=[LIB_ADD, FIL_READ],
                 entries=[{"kind": "parameter", "name": "a", "type": "int"},
                          {"kind": "global", "name": "gErr", "type": "int"},
                          {"kind": "mockReturn", "name": "libAdd()", "type": "int"},
                          {"kind": "mockReturn", "name": "ReadPage()", "type": "int"},
                          {"kind": "mockWriteback", "name": "e.lba", "type": "uint32_t"}],
                 written=[{"globalId": "Layer1.Sample-Core|Core|gErr", "name": "gErr"}])
    wb = [{"label": "e.lba", "type": "uint32_t", "mock": FIL_READ["functionId"],
           "param": "e", "field": "lba"}]
    case = _case(spec, values={"a": (1, None), "gErr": (0, None), "libAdd()": (1, None),
                               "ReadPage()": (0, None), "e.lba": (4, None)},
                 ret="1", globals_after={"gErr": "1"}, stub_calls=[("libAdd", {"a": "1"})],
                 writebacks=wb)
    payload = build_testcase_file("Layer1_Sample_Core_Core_TS", [case],
                                  {"flags": [], "probepoint": [], "usercode": []})
    assert _errors(payload, "testcase") == []


def test_built_hierarchy_file_matches_the_template():
    assert _errors(_hierarchy(), "hierarchy") == []
