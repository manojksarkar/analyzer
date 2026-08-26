"""testSpecs view (SWE.4): scope, mock rule, Input/Expected composition.

Rules under test come from docs/spec/SWE4_WIKI.md.
"""
import os
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from views.test_specs import (  # noqa: E402
    _build_test_specs, _spec_function_ids, _is_out_parameter, _test_case_id,
    GENERATION_METHOD,
)


def _fn(name, *, visibility="default", file="U.cpp", line=1, params=(),
        ret="int", calls=(), reads=(), writes=(), iid="", writes_params=()):
    f = {"qualifiedName": name, "visibility": visibility, "returnType": ret,
         "location": {"file": file, "line": line}, "parameters": list(params),
         "callsIds": list(calls), "interfaceId": iid}
    if reads:
        f["readsGlobalIds"] = list(reads)
    if writes:
        f["writesGlobalIds"] = list(writes)
    if writes_params:
        # Out-parameters are asserted only where the body is seen to write them.
        f["writesParams"] = list(writes_params)
    return f


@pytest.fixture
def model():
    functions = {
        "C|U|pub": _fn("pub", params=[{"name": "a", "type": "int"},
                                      {"name": "out", "type": "int*"}],
                       calls=["C|U|priv", "C|U|other", "C|O|far"],
                       reads=["C|U|gRead"], writes=["C|U|gWrite"], iid="IF_01",
                       writes_params=["out"]),
        "C|U|priv": _fn("priv", visibility="private", line=2),
        "C|U|other": _fn("other", line=3, ret="short"),
        "C|U|inlinepub": _fn("inlinepub", file="U.h", line=4),
        "C|U|voidcallee": _fn("voidcallee", line=5, ret="void"),
        "C|O|far": _fn("far", file="O.cpp", line=1, ret="long"),
    }
    units = {
        "C|U": {"name": "U", "fileName": "U.cpp",
                "functionIds": ["C|U|pub", "C|U|priv", "C|U|other",
                                "C|U|inlinepub", "C|U|voidcallee"]},
        "C|O": {"name": "O", "fileName": "O.cpp", "functionIds": ["C|O|far"]},
        "C|H": {"name": "H", "fileName": "H.h", "functionIds": []},
    }
    globals_ = {
        "C|U|gRead": {"qualifiedName": "gRead", "type": "int", "value": "7"},
        "C|U|gWrite": {"qualifiedName": "gWrite", "type": "char"},
    }
    return units, functions, globals_


def _specs(model):
    units, functions, globals_ = model
    r = _build_test_specs(units, functions, globals_, {})
    return {s["name"]: s for k, v in r.items() if k != "unitNames"
            for s in v["functions"]}


# --- scope -----------------------------------------------------------------

def test_private_function_gets_no_spec(model):
    assert "priv" not in _specs(model)


def test_inline_public_header_function_gets_no_spec(model):
    """The wiki's one exception: covered through its callers instead."""
    assert "inlinepub" not in _specs(model)


def test_public_cpp_functions_get_a_spec(model):
    names = _specs(model)
    assert {"pub", "other", "far"} <= set(names)


def test_header_only_unit_produces_no_section(model):
    units, functions, globals_ = model
    r = _build_test_specs(units, functions, globals_, {})
    assert "C|H" not in r


# --- mock rule -------------------------------------------------------------

def test_callee_with_its_own_spec_is_mocked(model):
    mocks = _specs(model)["pub"]["precondition"]["mockFunctions"]
    assert "other()" in mocks and "far()" in mocks


def test_same_unit_callee_without_a_spec_is_inlined_not_mocked(model):
    """A private helper of this unit has no spec, so it must run inline or its
    branches are covered nowhere."""
    assert "priv()" not in _specs(model)["pub"]["precondition"]["mockFunctions"]


def test_mock_rule_is_own_spec_or_different_unit(model):
    units, functions, globals_ = model
    spec_ids = _spec_function_ids(units, functions, None)
    unit_of = {fid: uk for uk, u in units.items() for fid in u["functionIds"]}
    mocks = set(_specs(model)["pub"]["precondition"]["mockFunctions"])
    for cid in functions["C|U|pub"]["callsIds"]:
        expected = f"{functions[cid]['qualifiedName']}()"
        stubbed = cid in spec_ids or unit_of.get(cid) != unit_of["C|U|pub"]
        assert (expected in mocks) is stubbed


# --- mock rule: the unit boundary ------------------------------------------
# A unit test spec is not an integration test spec: nothing outside the unit under
# test may execute, whether or not it has a spec of its own. An inline function is
# defined in a header, gets no spec anywhere, and is included by many units -- so
# "no spec" alone used to inline another unit's code into this one.

@pytest.fixture
def boundary():
    """`pub` calls one of every kind of callee across the unit boundary."""
    functions = {
        "C|U|pub": _fn("pub", calls=["C|U|inl", "C|U|priv", "C|X|xinl",
                                     "C|O|opriv", "loose", "unresolvable"]),
        # this unit's own -> run inline
        "C|U|inl": _fn("inl", file="U.h", line=2, reads=["g_inl"]),
        "C|U|priv": _fn("priv", visibility="private", line=3, reads=["g_priv"]),
        # outside the unit -> stubbed
        "C|X|xinl": _fn("xinl", file="X.h", line=1, reads=["g_x"]),
        "C|O|opriv": _fn("opriv", visibility="private", file="O.cpp", line=1),
        "loose": _fn("loose", file="Vendor.h", line=1),   # parsed, but in no unit
    }
    units = {
        "C|U": {"name": "U", "fileName": "U.cpp",
                "functionIds": ["C|U|pub", "C|U|inl", "C|U|priv"]},
        # a header with no .cpp beside it is still a unit of its own
        "C|X": {"name": "X", "fileName": "X.h", "functionIds": ["C|X|xinl"]},
        "C|O": {"name": "O", "fileName": "O.cpp", "functionIds": ["C|O|opriv"]},
    }
    globals_ = {g: {"qualifiedName": g, "type": "int"}
                for g in ("g_inl", "g_priv", "g_x")}
    return units, functions, globals_


def _boundary_spec(boundary):
    return _specs(boundary)["pub"]


def test_inline_function_of_another_unit_is_mocked(boundary):
    """`X.h` has no `.cpp`, so `xinl` gets no spec anywhere -- but it is another
    unit's code and must not run inside this unit's test."""
    assert "xinl()" in _boundary_spec(boundary)["precondition"]["mockFunctions"]


def test_inline_function_of_the_same_unit_is_not_mocked(boundary):
    """`U.h` and `U.cpp` are one unit, so `inl` is this unit's own code."""
    assert "inl()" not in _boundary_spec(boundary)["precondition"]["mockFunctions"]


def test_private_function_of_another_unit_is_mocked(boundary):
    assert "opriv()" in _boundary_spec(boundary)["precondition"]["mockFunctions"]


def test_callee_belonging_to_no_unit_is_mocked(boundary):
    """Its file was never parsed, so it cannot be this unit's own code. Inlining it
    is the failure the boundary exists to prevent."""
    assert "loose()" in _boundary_spec(boundary)["precondition"]["mockFunctions"]


def test_unresolvable_callee_is_left_out(boundary):
    """The wiki: a library call that cannot be named does not reach the document."""
    mocks = _boundary_spec(boundary)["precondition"]["mockFunctions"]
    assert not any("unresolvable" in m for m in mocks)


def test_globals_stop_at_the_unit_boundary(boundary):
    """A stub never executes, so its globals are not preconditions of this spec --
    while an inlined same-unit helper's globals are."""
    names = {g["name"] for g in _boundary_spec(boundary)["precondition"]["globals"]}
    assert names == {"g_inl", "g_priv"}


# --- precondition ----------------------------------------------------------

def test_precondition_globals_carry_no_value_or_range(model):
    texts = [g["text"] for g in _specs(model)["pub"]["precondition"]["globals"]]
    assert texts == ["int gRead", "char gWrite"]
    assert not any("[" in t or "=" in t for t in texts)


def test_precondition_lists_every_parameter(model):
    texts = [p["text"] for p in _specs(model)["pub"]["precondition"]["parameters"]]
    assert texts == ["int a", "int* out"]


# --- input -----------------------------------------------------------------

def test_input_entries_carry_a_range(model):
    entry = next(e for e in _specs(model)["pub"]["input"]["entries"]
                 if e["name"] == "a")
    assert entry["text"].startswith("int a[") and entry["text"].endswith("]")


def test_out_parameter_is_excluded_from_input(model):
    spec = _specs(model)["pub"]
    assert "out" not in {e["name"] for e in spec["input"]["entries"]}
    assert "out" in {o["name"] for o in spec["expected"]["outParameters"]}


def test_write_only_global_is_excluded_from_input(model):
    spec = _specs(model)["pub"]
    names = {e["name"] for e in spec["input"]["entries"]}
    assert "gRead" in names and "gWrite" not in names


def test_void_mock_is_named_in_precondition_but_not_in_input(model):
    units, functions, globals_ = model
    functions["C|U|pub"]["callsIds"].append("C|U|voidcallee")
    spec = _specs((units, functions, globals_))["pub"]
    assert "voidcallee()" in spec["precondition"]["mockFunctions"]
    assert "voidcallee()" not in {e["name"] for e in spec["input"]["entries"]}


def test_value_returning_mock_appears_in_input(model):
    entry = next(e for e in _specs(model)["pub"]["input"]["entries"]
                 if e["name"] == "far()")
    assert entry["kind"] == "mockReturn" and entry["text"].startswith("long far()")


def test_input_is_void_when_nothing_is_read():
    functions = {"C|U|f": _fn("f", ret="void")}
    units = {"C|U": {"name": "U", "fileName": "U.cpp", "functionIds": ["C|U|f"]}}
    r = _build_test_specs(units, functions, {}, {})
    assert r["C|U"]["functions"][0]["input"]["isVoid"] is True


# --- expected --------------------------------------------------------------

def test_written_global_is_an_expected_output(model):
    assert [g["name"] for g in _specs(model)["pub"]["expected"]["globals"]] == ["gWrite"]


def test_returns_are_left_for_the_cfg_pass(model):
    assert _specs(model)["pub"]["expected"]["returns"] == []


# --- out-parameter heuristic ----------------------------------------------

@pytest.mark.parametrize("type_str,is_out", [
    ("int", False), ("int*", True), ("const int*", False),
    ("int&", True), ("const int&", False),
    ("int (*)(int, int)", False),      # callback: an input despite the '*'
    ("void (*)(void)", False),
])
def test_out_parameter_detection(type_str, is_out):
    assert _is_out_parameter({"type": type_str}) is is_out


# --- misc ------------------------------------------------------------------

def test_test_case_id_prefers_interface_id(model):
    assert _specs(model)["pub"]["testCaseId"] == "TC_IF_01"


def test_test_case_id_falls_back_to_a_sanitized_name():
    assert _test_case_id({"qualifiedName": "ns::fn"}) == "TC_ns__fn"


def test_generation_method_is_fixed(model):
    assert _specs(model)["pub"]["generationMethod"] == GENERATION_METHOD == \
        "Analysis of Requirements"


def test_build_is_deterministic(model):
    units, functions, globals_ = model
    import json
    a = json.dumps(_build_test_specs(units, functions, globals_, {}), indent=2)
    b = json.dumps(_build_test_specs(units, functions, globals_, {}), indent=2)
    assert a == b


# --- the mock boundary: what runs, what is stubbed -------------------------
#
# Wiki: a callee with no spec of its own is never mocked -- it runs inline. So the
# spec'd functions IT calls really get called, and a global only a MOCK reads is
# never reached. Both follow from "follow the real execution path, stop at each stub".

def _boundary_model():
    """`chain` calls `helper` (no spec -> inlined); `helper` calls `deep` (has a
    spec -> stubbed) and `deep` is the only reader of gDeep. `helper` itself reads
    gInline. Mirrors utilChain -> utilNorm -> utilCompute in the sample."""
    functions = {
        "C|U|chain": _fn("chain", line=1, calls=["C|U|helper"], iid="IF_01"),
        # no external caller in this model -> no spec -> runs inline
        "C|U|helper": _fn("helper", visibility="private", line=2,
                          calls=["C|O|deep"], reads=["C|U|gInline"]),
        "C|O|deep": _fn("deep", file="O.cpp", line=1, ret="int",
                        reads=["C|U|gDeep"]),
    }
    units = {
        "C|U": {"name": "U", "fileName": "U.cpp",
                "functionIds": ["C|U|chain", "C|U|helper"]},
        "C|O": {"name": "O", "fileName": "O.cpp", "functionIds": ["C|O|deep"]},
    }
    globals_ = {
        "C|U|gInline": {"qualifiedName": "gInline", "type": "int"},
        "C|U|gDeep": {"qualifiedName": "gDeep", "type": "int"},
    }
    out = _build_test_specs(units, functions, globals_, {})
    return out["C|U"]["functions"][0]


def test_mock_reached_through_an_inlined_callee_is_stubbed():
    """`chain` never names `deep`, but `helper` runs inline and really calls it."""
    assert _boundary_model()["precondition"]["mockFunctions"] == ["deep()"]


def test_global_read_only_by_a_mock_is_not_a_precondition():
    """gDeep is read only inside `deep`, which this spec stubs -- so the test can
    never reach it and setting it up would change nothing."""
    names = {g["name"] for g in _boundary_model()["precondition"]["globals"]}
    assert "gDeep" not in names


def test_global_read_by_an_inlined_callee_is_a_precondition():
    """gInline is read by `helper`, which really executes."""
    names = {g["name"] for g in _boundary_model()["precondition"]["globals"]}
    assert "gInline" in names


# --- mock write-backs (Input) ----------------------------------------------
#
# Wiki, Input: "Plus anything else a decision depends on that Precondition does not
# name -- a value a mock writes back through a pointer, a struct field."
# Its worked example lists `e.lba` and `e.ppn` because FtlLookup reads them; a field
# it never reads is a dead input and must not appear.

def _writeback_model(reads_fields=None):
    """The wiki's worked example, reduced: FtlLookup mocks
    FilReadPage(uint16_t, MapEntry*) and reads two of MapEntry's three fields."""
    lookup = _fn("FtlLookup", file="FtlMap.cpp", line=1,
                 params=[{"name": "lba", "type": "uint32_t"}],
                 calls=["F|Fil|FilReadPage"], iid="FTL_MAP_02")
    if reads_fields is None:
        reads_fields = [
            {"var": "e", "structType": "MapEntry", "field": "lba"},
            {"var": "e", "structType": "MapEntry", "field": "ppn"},
        ]
    if reads_fields:
        lookup["readsFields"] = reads_fields
    functions = {
        "F|Map|FtlLookup": lookup,
        "F|Fil|FilReadPage": _fn("FilReadPage", file="Fil.cpp", line=1,
                                 params=[{"name": "idx", "type": "uint16_t"},
                                         {"name": "e", "type": "MapEntry *"}],
                                 iid="FIL_01"),
    }
    units = {
        "F|Map": {"name": "Map", "fileName": "FtlMap.cpp",
                  "functionIds": ["F|Map|FtlLookup"]},
        "F|Fil": {"name": "Fil", "fileName": "Fil.cpp",
                  "functionIds": ["F|Fil|FilReadPage"]},
    }
    dd = {"MapEntry": {"kind": "struct", "range": "NA", "fields": [
        {"name": "lba", "type": "uint32_t", "range": "0-4294967295"},
        {"name": "ppn", "type": "uint32_t", "range": "0-4294967295"},
        {"name": "unused", "type": "uint8_t", "range": "0-255"},
    ]}}
    out = _build_test_specs(units, functions, {}, dd)
    return out["F|Map"]["functions"][0]["input"]["entries"]


def test_mock_writeback_lists_the_fields_the_function_reads():
    wb = [e for e in _writeback_model() if e["kind"] == "mockWriteback"]
    assert [(e["name"], e["type"]) for e in wb] == [
        ("e.lba", "uint32_t"), ("e.ppn", "uint32_t")]
    # Written like any other input: `type variable[range]`.
    assert all(e["text"].startswith(f"{e['type']} {e['name']}[") for e in wb)


def test_mock_writeback_omits_a_field_the_function_never_reads():
    """`unused` is a MapEntry field the stub could write, but FtlLookup never reads
    it -- setting it cannot change any outcome, so it is not an input."""
    assert "e.unused" not in {e.get("name") for e in _writeback_model()}


def test_mock_writeback_absent_when_the_function_reads_no_fields():
    entries = _writeback_model(reads_fields=[])
    assert [e for e in entries if e["kind"] == "mockWriteback"] == []


def test_mock_writeback_ignores_a_same_named_field_of_another_struct():
    """The base's declared type disambiguates: reading `other.lba` says nothing
    about the MapEntry that FilReadPage writes back."""
    entries = _writeback_model(reads_fields=[
        {"var": "other", "structType": "Other", "field": "lba"}])
    assert [e for e in entries if e["kind"] == "mockWriteback"] == []


# --- Expected Results: only out-parameters the body actually writes ---------
#
# Wiki: "one entry per out-parameter written". The signature only says a parameter
# COULD be written; asserting on that alone produced "Successfully updated
# Operation * op" for a function that merely calls through it.

def _outparam_entries(writes_params=None):
    fn = _fn("f", file="U.cpp", params=[{"name": "w", "type": "Widget_t *"}],
             ret="void", iid="IF_01",
             writes_params=writes_params or ())
    units = {"C|U": {"name": "U", "fileName": "U.cpp", "functionIds": ["C|U|f"]}}
    out = _build_test_specs(units, {"C|U|f": fn}, {}, {})
    return out["C|U"]["functions"][0]["expected"]["outParameters"]


def test_out_parameter_never_written_is_not_asserted():
    """`applyWithOperation(Operation* op)` only calls `op->apply()`. Asserting
    'Successfully updated op' gives the tester a check that can never pass."""
    assert _outparam_entries() == []


def test_written_out_parameter_is_asserted_as_a_whole():
    """`writesParams` covers both `*w = x` and `w->id = x`; the wiki asserts the
    parameter, not its fields, so one entry is emitted either way."""
    entries = _outparam_entries(["w"])
    assert [e["name"] for e in entries] == ["w"]
    assert entries[0]["kind"] == "outParameter"
    assert entries[0]["text"].startswith("Widget_t * w")


# --- mock signatures (UT_EXPORT_SPEC REQ-UE-03) -----------------------------

def test_mocks_mirror_mock_functions(model):
    """Both lists come from the same `mocked_ids`, so they must never disagree
    about which callees are stubbed -- only about how much detail they carry."""
    pre = _specs(model)["pub"]["precondition"]
    assert [m["name"] + "()" for m in pre["mocks"]] == pre["mockFunctions"]


def test_mock_carries_the_signature_needed_to_write_a_stub(model):
    """`other()` alone cannot be stubbed: a generator needs the return type to
    declare and the parameter types to match."""
    mocks = {m["name"]: m for m in _specs(model)["pub"]["precondition"]["mocks"]}
    assert mocks["other"]["returnType"] == "short"
    assert mocks["far"]["returnType"] == "long"


def test_mock_parameters_are_typed(model):
    units, functions, globals_ = model
    functions["C|U|other"]["parameters"] = [{"name": "n", "type": "size_t"}]
    mocks = {m["name"]: m for m in _specs((units, functions, globals_))
             ["pub"]["precondition"]["mocks"]}
    assert mocks["other"]["parameters"] == [{"name": "n", "type": "size_t"}]


def test_declaring_header_comes_from_the_component(model):
    """A stub must be includable. The unit is a path, so its header is the `.cpp`
    sibling -- but the extension comes from the component, not a guess."""
    units, functions, globals_ = model
    units["C|O"]["path"] = "src/C/O"
    components = {"C": {"headerFiles": ["src/C/O.hpp"]}}
    r = _build_test_specs(units, functions, globals_, {}, components_data=components)
    mocks = {m["name"]: m for m in
             r["C|U"]["functions"][0]["precondition"]["mocks"]}
    assert mocks["far"]["declaredIn"] == "src/C/O.hpp"


def test_declaring_header_is_empty_when_the_component_declares_none(model):
    """Better an empty string than a guessed path a generator would fail to open."""
    mocks = {m["name"]: m for m in _specs(model)["pub"]["precondition"]["mocks"]}
    assert mocks["far"]["declaredIn"] == ""
