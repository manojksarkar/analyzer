"""Functions that share a name inside one unit are told apart wherever the document names them.

Reported in review: two functions took the same section heading. `Class::name` is one
string for overloads (`scale(int)`, `scale(float)`) and for functions of one name in different
namespaces, so two sections read the same -- and a flowchart was keyed by the qualified name
inside its unit, so overloads shared one file and one picture as well.

An override was never the problem: the class in front tells `Base::run` from `Derived::run`.

ONE rule (engine/core/function_names.py), asked by every place that prints a name or names a
flowchart. The fixture is SampleCppProject/Layer1/Poly/Overloads.*; it is outside the e2e run's
scope (group "Layer1.My Sample"), so these are the checks.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(_ROOT, "engine"), os.path.join(_ROOT, "engine", "flowchart"),
           os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.function_names import (chart_names, display_names, overload_signatures,  # noqa: E402
                                 signature, stored_chart, without_signature)

U = "Layer1.Cross|Overloads"


def _fn(qualified, params=(), cls="", line=1, unit=U, visibility="public", **more):
    types = ",".join(t for t, _ in params)
    key = f"{unit}|{qualified}|{types}"
    return key, dict({"qualifiedName": qualified, "className": cls, "visibility": visibility,
                      "parameters": [{"type": t, "name": n} for t, n in params],
                      "returnType": "int", "interfaceId": f"IF_X_{line:02d}",
                      "location": {"file": "Layer1/Poly/Overloads.cpp", "line": line},
                      "calledByIds": [], "callsIds": []}, **more)


FUNCTIONS = dict([
    _fn("ovlScale", [("int", "value")], line=5),
    _fn("ovlScale", [("int", "value"), ("int", "factor")], line=12),
    _fn("ovlScale", [("float", "value")], line=19),
    _fn("fastpath::ovlInit", [("int", "seed")], line=24),
    _fn("slowpath::ovlInit", [("int", "seed")], line=30),
    _fn("OvlShape::area", [("int", "side")], cls="OvlShape", line=38),
    _fn("OvlSquare::area", [("int", "side")], cls="OvlSquare", line=55),
    _fn("OvlShape::resize", [("int", "side")], cls="OvlShape", line=42),
    _fn("OvlShape::resize", [("int", "width"), ("int", "height")], cls="OvlShape", line=46),
    _fn("ovlAlone", [("int", "value")], line=59),
    # the same name in ANOTHER unit shares nothing with these
    _fn("ovlScale", [("int", "value")], unit="Layer1.Cross|Other", line=3),
])
KEY = {(f["qualifiedName"], signature(f["parameters"])): k for k, f in FUNCTIONS.items() if k.startswith(U)}


class TestTheRule:
    def test_overloads_carry_their_parameter_types(self):
        names = display_names(FUNCTIONS)
        assert names[KEY[("ovlScale", "(int)")]] == "ovlScale(int)"
        assert names[KEY[("ovlScale", "(int, int)")]] == "ovlScale(int, int)"
        assert names[KEY[("ovlScale", "(float)")]] == "ovlScale(float)"
        assert names[KEY[("OvlShape::resize", "(int)")]] == "OvlShape::resize(int)"
        assert names[KEY[("OvlShape::resize", "(int, int)")]] == "OvlShape::resize(int, int)"

    def test_one_name_in_two_namespaces_carries_its_scope(self):
        names = display_names(FUNCTIONS)
        assert names[KEY[("fastpath::ovlInit", "(int)")]] == "fastpath::ovlInit"
        assert names[KEY[("slowpath::ovlInit", "(int)")]] == "slowpath::ovlInit"

    def test_an_override_is_told_apart_by_its_class_as_before(self):
        names = display_names(FUNCTIONS)
        assert names[KEY[("OvlShape::area", "(int)")]] == "OvlShape::area"
        assert names[KEY[("OvlSquare::area", "(int)")]] == "OvlSquare::area"

    def test_a_name_nobody_shares_is_printed_as_before(self):
        names = display_names(FUNCTIONS)
        assert names[KEY[("ovlAlone", "(int)")]] == "ovlAlone"
        assert names["Layer1.Cross|Other|ovlScale|int"] == "ovlScale", "another unit's twin is no twin"

    def test_no_two_functions_of_a_unit_print_alike(self):
        names = display_names(FUNCTIONS)
        in_unit = [names[k] for k in FUNCTIONS if k.startswith(U + "|")]
        assert len(in_unit) == len(set(in_unit))

    def test_it_does_not_depend_on_who_is_published(self):
        """A sibling losing its caller must not rename the one that keeps it."""
        hidden = {k: dict(f, visibility="private") for k, f in FUNCTIONS.items()}
        assert display_names(hidden) == display_names(FUNCTIONS)

    def test_mixed_overloads_and_scopes(self):
        fns = dict([_fn("a::go", [("int", "x")]), _fn("a::go", [("const char *", "s")]), _fn("b::go")])
        assert sorted(display_names(fns).values()) == ["a::go(const char *)", "a::go(int)", "b::go"]

    def test_only_overloads_have_a_signature_to_add(self):
        sigs = overload_signatures(FUNCTIONS)
        assert set(sigs.values()) == {"(int)", "(int, int)", "(float)"}
        assert len(sigs) == 5 and KEY[("fastpath::ovlInit", "(int)")] not in sigs

    def test_a_signature_line_writes_the_parameters_once(self):
        sigs = overload_signatures(FUNCTIONS)
        key = KEY[("ovlScale", "(int, int)")]
        assert without_signature("ovlScale(int, int)", key, sigs) == "ovlScale"
        assert without_signature("ovlAlone", KEY[("ovlAlone", "(int)")], sigs) == "ovlAlone"
        # `operator()` of a function that is NOT overloaded ends in "()" and must keep it
        assert without_signature("Functor::operator()", "C|U|Functor::operator()|", sigs) == "Functor::operator()"


class TestFlowchartNames:
    """A chart is keyed by its name inside its unit's file, and by it on disk."""

    def test_overloads_get_a_chart_of_their_own(self):
        charts = chart_names(FUNCTIONS)
        assert charts[KEY[("ovlScale", "(int)")]] == "ovlScale(int)"
        assert charts[KEY[("ovlScale", "(int, int)")]] == "ovlScale(int,int)"
        assert charts[KEY[("OvlShape::resize", "(int, int)")]] == "OvlShape::resize(int,int)"

    def test_every_other_chart_keeps_the_qualified_name(self):
        """...so no picture, no web SVG and no stored chart of a function that shares its name
        with nobody is renamed by this."""
        charts = chart_names(FUNCTIONS)
        overloaded = set(overload_signatures(FUNCTIONS))
        for key, f in FUNCTIONS.items():
            if key not in overloaded:
                assert charts[key] == f["qualifiedName"]

    def test_no_two_charts_of_a_unit_share_a_name(self):
        charts = chart_names(FUNCTIONS)
        in_unit = [charts[k] for k in FUNCTIONS if k.startswith(U + "|")]
        assert len(in_unit) == len(set(in_unit))

    def test_no_two_charts_of_a_unit_share_a_file(self):
        """A picture is `<unit>_<name>` with `*`, `&`, `<`, `,` ... replaced by `_`: overloads
        apart only by a pointer and a reference were two charts with one picture."""
        from utils import safe_filename
        fns = dict([_fn("put", [("const Frame *", "f")]), _fn("put", [("const Frame &", "f")]),
                    _fn("put", [("Frame &&", "f")]), _fn("put", [("Frame **", "f")]),
                    _fn("put", [("std::pair<int,int>", "p")]), _fn("put", [("std::pair<int;int>", "p")]),
                    _fn("Run"), _fn("run"), _fn("alone", [("char *", "s")])])
        charts = chart_names(fns)
        files = [safe_filename(name).casefold() for name in charts.values()]
        assert len(files) == len(set(files)) == 9
        by_types = {k.split("|", 3)[3]: v for k, v in charts.items() if "|put|" in k}
        assert by_types["const Frame *"] == "put(const Frame ptr)"
        assert by_types["const Frame &"] == "put(const Frame ref)"
        assert by_types["Frame &&"] == "put(Frame rref)"
        # a name nobody shares keeps its own, pointer or not
        assert charts[next(k for k in fns if "|alone|" in k)] == "alone"
        # what is still one file is numbered, in key order: stable from run to run
        assert sorted(v for k, v in charts.items() if k.split("|")[2].lower() == "run") == ["Run", "run-2"]
        assert chart_names(dict(reversed(list(fns.items())))) == charts

    def test_the_writer_gives_an_overload_drawn_alone_its_own_name(self):
        """An incremental run draws only the function that changed. Its chart must carry the
        name it has beside its sibling, or the splice into the baseline file puts it under a
        new name and leaves the old picture in place."""
        from models import FileResult, FlowchartResult
        from output.writer import _serialize_file_result
        key = KEY[("ovlScale", "(int, int)")]
        alone = FileResult(source_file="Layer1/Poly/Overloads.cpp", flowcharts=[
            FlowchartResult(function_key=key, qualified_name="ovlScale", mermaid_script="digraph {}")])
        [entry] = _serialize_file_result(alone, chart_names(FUNCTIONS))
        assert (entry["functionKey"], entry["name"]) == (key, "ovlScale(int,int)")
        [plain] = _serialize_file_result(alone)                    # no names given: as before
        assert plain["name"] == "ovlScale"


class TestAVersionFromBeforeTheNames:
    """A version generated before 2026-10-13 holds a function's overloads under ONE name. A
    re-export, or the web page, of such a version must show what it showed, not lose the chart."""

    UNITS = ("Layer1.Cross_Overloads", "Overloads")
    NEW = {"Overloads": {"OvlShape::resize(int)": "ONE", "OvlShape::resize(int,int)": "TWO",
                         "ovlAlone": "ALONE"}}
    OLD = {"Overloads": {"OvlShape::resize": "SHARED", "ovlAlone": "ALONE"}}

    def test_an_overload_is_found_under_its_own_name(self):
        chart, names = stored_chart(self.NEW, self.UNITS, "OvlShape::resize(int,int)",
                                    "OvlShape::resize", "resize")
        assert (chart, names) == ("TWO", ["OvlShape::resize(int,int)"])

    def test_an_older_version_has_it_under_the_qualified_name(self):
        chart, names = stored_chart(self.OLD, self.UNITS, "OvlShape::resize(int,int)",
                                    "OvlShape::resize", "resize")
        assert (chart, names) == ("SHARED", ["OvlShape::resize", "resize"])

    def test_its_own_chart_never_takes_the_shared_picture(self):
        """Carried from an older baseline, the shared picture may still be on disk, and it may
        be the sibling's: an overload found under its own name names no other picture."""
        both = {"Overloads": dict(self.NEW["Overloads"], **self.OLD["Overloads"])}
        _chart, names = stored_chart(both, self.UNITS, "OvlShape::resize(int)",
                                     "OvlShape::resize", "resize")
        assert names == ["OvlShape::resize(int)"]

    def test_every_other_function_is_looked_up_as_before(self):
        assert stored_chart(self.NEW, self.UNITS, "ovlAlone", "ovlAlone", "ovlAlone") == \
            ("ALONE", ["ovlAlone"])
        # the short name behind the qualified one, in either spelling of the unit
        by_short = {"Layer1.Cross_Overloads": {"area": "SHORT"}}
        assert stored_chart(by_short, self.UNITS, "OvlShape::area", "OvlShape::area", "area") == \
            ("SHORT", ["OvlShape::area", "area"])
        assert stored_chart({}, self.UNITS, "OvlShape::area", "OvlShape::area", "area") == \
            (None, ["OvlShape::area", "area"])


class TestWhereANameIsPrinted:
    @pytest.fixture
    def tables(self):
        from views.interface_tables import _build_interface_tables
        units = {U: {"name": "Overloads", "fileName": "Overloads.cpp",
                     "functionIds": [k for k in FUNCTIONS if k.startswith(U + "|")],
                     "globalVariableIds": []}}
        return _build_interface_tables(units, FUNCTIONS, {})[U]["entries"]

    def test_the_interface_table_has_one_name_per_function(self, tables):
        names = [e["interfaceName"] for e in tables]
        assert len(names) == len(set(names)) == 10
        assert {"ovlScale(int)", "ovlScale(int, int)", "ovlScale(float)", "fastpath::ovlInit",
                "slowpath::ovlInit", "OvlShape::resize(int)", "OvlShape::resize(int, int)",
                "OvlShape::area", "OvlSquare::area", "ovlAlone"} == set(names)

    def test_the_short_name_stays_a_lookup_key(self, tables):
        assert {e["name"] for e in tables} == {"ovlScale", "ovlInit", "area", "resize", "ovlAlone"}

    def test_swe4_gives_an_overload_a_heading_of_its_own(self):
        from views.test_specs import _build_test_specs
        from swe4_exporter import _spec_name
        units = {U: {"name": "Overloads", "fileName": "Overloads.cpp",
                     "functionIds": [k for k in FUNCTIONS if k.startswith(U + "|")],
                     "globalVariableIds": []}}
        specs = _build_test_specs(units, FUNCTIONS, {})[U]["functions"]
        headings = [_spec_name(s) for s in specs]
        assert len(headings) == len(set(headings)) == 10
        assert "ovlScale(int, int)" in headings and "OvlShape::resize(int)" in headings
        # nothing is added to a spec that needs nothing
        plain = next(s for s in specs if s["qualifiedName"] == "ovlAlone")
        assert "headingName" not in plain and _spec_name(plain) == "ovlAlone"
        assert "headingName" not in next(s for s in specs if s["qualifiedName"] == "fastpath::ovlInit")

    def test_the_comparison_tool_reads_an_overload_out_of_a_heading(self):
        from doccheck import cells
        from doccheck.model import normalise_key
        assert cells.function_of("Overloads-ovlScale(int, int)", "Overloads") == "ovlScale(int, int)"
        assert cells.function_of("Overloads-OvlShape::resize(int)", "Overloads") == "OvlShape::resize(int)"
        assert cells.function_of("Dispatch-AddOperation::apply", "Dispatch") == "AddOperation::apply"
        assert normalise_key("ovlScale(int)") != normalise_key("ovlScale(float)")
        assert normalise_key("utilAbs()") == normalise_key("utilAbs")       # a call form, as before


def test_the_fixture_holds_every_case():
    """The names above are the fixture's: a renamed function would leave them testing nothing."""
    with open(os.path.join(_ROOT, "SampleCppProject", "Layer1", "Poly", "Overloads.cpp"),
              encoding="utf-8") as fh:
        source = fh.read()
    for needle in ("int ovlScale(int value) {", "int ovlScale(int value, int factor) {",
                   "float ovlScale(float value) {", "namespace fastpath {", "namespace slowpath {",
                   "int OvlShape::resize(int side) {", "int OvlShape::resize(int width, int height) {",
                   "int OvlSquare::area(int side) {", "int ovlAlone(int value) {"):
        assert needle in source, needle
