"""A saved correction re-derives the component's SWE.4 specs from the stored rows (REQ-CS-04).

A SWE.4 spec carries corrected text two ways: its function's description, copied, and every node
label of the flowchart it transcribes -- "Check whether <label>", "Successfully returned <label>",
and in a Dynamic Behaviour spec another unit's steps spliced in place. So a label corrected in unit
Proc changes unit Drv's document. The save rebuilds both from what is stored, through the views'
own code, and the result must be the file a whole-document Phase-3 build would write, byte for byte.

The model is hand-built: component Sig (units Drv and Proc) entered from component Ext, one
document covering both. `drive` calls `refine` in the other unit of its component, so its Dynamic
Behaviour spec splices `refine`'s steps.
"""
import copy
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s  # noqa: E402
from review import export_guard as g, slot, swe4_rederive as rd  # noqa: E402
from views import ut_export  # noqa: E402
from views.test_specs import build as build_specs  # noqa: E402
from views.test_steps import cfgs_from_entries  # noqa: E402

T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
T1 = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

DRIVE, REFINE, ENTRY = "Sig|Drv|drive|int", "Sig|Proc|refine|int", "Ext|Caller|entry|"


def _fn(name, file, *, calls=(), called_by=(), params=(), iid="", description=""):
    f = {"qualifiedName": name, "visibility": "public", "returnType": "int",
         "location": {"file": file, "line": 1}, "parameters": list(params),
         "callsIds": list(calls), "calledByIds": list(called_by), "interfaceId": iid}
    if description:
        f["description"] = description
    return f


MODEL = {
    "functions": {
        ENTRY: _fn("entry", "Caller.cpp", calls=[DRIVE], iid="IF_EXT_01"),
        DRIVE: _fn("drive", "Drv.cpp", calls=[REFINE], called_by=[ENTRY], iid="IF_DRV_01",
                   params=[{"name": "raw", "type": "int"}], description="Drives the signal."),
        REFINE: _fn("refine", "Proc.cpp", called_by=[DRIVE], iid="IF_PRC_01",
                    params=[{"name": "x", "type": "int"}], description="Refines a value."),
    },
    "globalVariables": {},
    "units": {
        "Ext|Caller": {"name": "Caller", "fileName": "Caller.cpp", "functionIds": [ENTRY]},
        "Sig|Drv": {"name": "Drv", "fileName": "Drv.cpp", "functionIds": [DRIVE]},
        "Sig|Proc": {"name": "Proc", "fileName": "Proc.cpp", "functionIds": [REFINE]},
    },
    "components": {"Ext": {"units": ["Ext|Caller"]}, "Sig": {"units": ["Sig|Drv", "Sig|Proc"]}},
    "dataDictionary": {},
}

CONTEXT = {"allowedComponents": ["Ext", "Sig"], "layerComponents": None,
           "views": {"functionTestSpecs": True, "dynamicBehaviourSpecs": True,
                     "utExport": {"review": {"author": "A", "reviewer": "R"}}},
           "layers": {"Layer1": {"groups": {"G": {"Ext": {}, "Sig": {}}}}}}


def _entry(fid, nodes, edges):
    return {"functionKey": fid, "name": fid.split("|")[2],
            "cfg": {"entry": "N1", "exits": ["NE"],
                    "nodes": [{"id": i, "type": t, "label": lab, "rawCode": raw or lab,
                               "line": n + 1, "endLine": n + 1}
                              for n, (i, t, lab, raw) in enumerate(nodes)],
                    "edges": [{"source": a, "target": b, "label": e} for a, b, e in edges]},
            "flowchart": "digraph {}"}


FLOWCHARTS = {
    "G/flowcharts/Caller.json": [_entry(ENTRY, [
        ("N1", "START", "Start: entry", ""), ("N2", "ACTION", "Drive the signal", "drive(1);"),
        ("N3", "RETURN", "Return 0", "return 0;"), ("NE", "END", "End", "")],
        [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])],
    "G/flowcharts/Drv.json": [_entry(DRIVE, [
        ("N1", "START", "Start: drive", ""), ("N2", "ACTION", "Refine the raw value",
                                              "refine(raw);"),
        ("N3", "RETURN", "Return 0", "return 0;"), ("NE", "END", "End", "")],
        [("N1", "N2", None), ("N2", "N3", None), ("N3", "NE", None)])],
    "G/flowcharts/Proc.json": [_entry(REFINE, [
        ("N1", "START", "Start: refine", ""), ("N2", "DECISION", "Check: x < 0?", "if (x < 0)"),
        ("N3", "RETURN", "Return -1", "return -1;"), ("N4", "RETURN", "Return 1", "return 1;"),
        ("NE", "END", "End", "")],
        [("N1", "N2", None), ("N2", "N3", "Yes"), ("N2", "N4", "No"),
         ("N3", "NE", None), ("N4", "NE", None)])],
}


def _config(allowed):
    return {"views": CONTEXT["views"], "layers": CONTEXT["layers"],
            "_analyzerAllowedComponents": list(allowed)}


def _whole(model, flowcharts, labels=None):
    """What a whole-document Phase-3 build writes: (test_specs.json, ut_export.json)."""
    files = copy.deepcopy([flowcharts[p] for p in sorted(flowcharts)])
    for entries in files:
        for e in entries:
            for node in e["cfg"]["nodes"]:
                text = (labels or {}).get((e["functionKey"], node["id"]))
                if text:
                    node["label"] = text
    specs = build_specs(model, _config(["Ext", "Sig"]), cfgs_from_entries(files), verbose=False)
    return (json.dumps(specs, indent=2),
            json.dumps(ut_export.build(specs, {}, _config(["Ext", "Sig"])), indent=2))


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        specs, ut = _whole(MODEL, FLOWCHARTS)
        rows = {p: json.dumps(v, indent=2) for p, v in FLOWCHARTS.items()}
        rows.update({"G/flowcharts/_summary.json": "{}", "G/test_specs.json": specs,
                     "G/ut_export.json": ut,
                     "G/_derivations.json": g.record_text({"views": {
                         view: {"at": T0.isoformat(), "components": ["ext", "sig"],
                                "context": CONTEXT}
                         for view in ("testSpecs", "utExport")}})})
        for path, content in rows.items():
            cx.execute(sa.insert(s.version_output_files).values(
                version_id="v1", rel_path=path, content=content, group_name="G"))
        yield cx


def _row(conn, path):
    return conn.execute(sa.select(s.version_output_files.c.content)
                        .where(s.version_output_files.c.rel_path == path)).scalar()


def _correct(conn, fid, node, text):
    conn.execute(sa.insert(s.text_overrides).values(
        version_id="v1", slot_kind=slot.NODE_LABEL, slot_key=slot.for_node(fid, node),
        llm_text="llm", human_text=text, is_orphaned=False, updated_at=T1))


def _spec(conn, name, dynamic=False):
    doc = json.loads(_row(conn, "G/test_specs.json"))
    if dynamic:
        return next(sp for specs in doc["dynamicSpecs"].values() for sp in specs
                    if sp["name"] == name)
    return next(sp for k, u in doc.items() if k not in ("unitNames", "dynamicSpecs")
                for sp in u["functions"] if sp["name"] == name)


def _texts(spec):
    return [st["text"] for st in spec["testSteps"]]


class TestTheFixture:
    def test_it_has_what_the_rule_is_about(self, conn):
        """A decision step from `refine`'s own flowchart, and `drive`'s Dynamic Behaviour spec
        splicing it -- or the tests below would pass for nothing."""
        assert "Check whether x < 0." in _texts(_spec(conn, "refine"))
        assert any("x < 0" in t for t in _texts(_spec(conn, "drive", dynamic=True)))


class TestNothingChanged:
    def test_the_rows_are_left_byte_for_byte(self, conn):
        """The component re-derived alone and merged is the file a whole-document build
        wrote. If this fails, the merge -- or the claim that a spec does not depend on the
        document's other components -- is wrong."""
        before = {p: _row(conn, p) for p in ("G/test_specs.json", "G/ut_export.json")}
        assert rd.rederive(conn, "v1", "Sig", MODEL) == ["testSpecs", "utExport"]
        assert {p: _row(conn, p) for p in before} == before


class TestALabel:
    def test_a_decision_label_reaches_the_function_spec(self, conn):
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        rd.rederive(conn, "v1", "Sig", MODEL)
        assert "Check whether the input is negative." in _texts(_spec(conn, "refine"))

    def test_a_label_in_one_unit_changes_another_units_dynamic_spec(self, conn):
        """REQ-CS-04's verification: `drive` (unit Drv) was not edited."""
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        rd.rederive(conn, "v1", "Sig", MODEL)
        assert any("the input is negative" in t
                   for t in _texts(_spec(conn, "drive", dynamic=True)))

    def test_a_return_label_reaches_the_ut_export(self, conn):
        """A return step's label is its case's expected return."""
        _correct(conn, REFINE, "N3", "Return ERR_NEGATIVE")
        rd.rederive(conn, "v1", "Sig", MODEL)
        cases = json.loads(_row(conn, "G/ut_export.json"))["cases"]
        assert "ERR_NEGATIVE" in {c["expected"]["return"] for c in cases}

    def test_the_result_is_what_phase_3_would_write(self, conn):
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        rd.rederive(conn, "v1", "Sig", MODEL)
        specs, ut = _whole(MODEL, FLOWCHARTS,
                           {(REFINE, "N2"): "Check: the input is negative?"})
        assert _row(conn, "G/test_specs.json") == specs
        assert _row(conn, "G/ut_export.json") == ut

    def test_the_stored_flowchart_row_need_not_carry_it(self, conn):
        """A save patches ONE stored copy of its flowchart; a directory holding another copy
        still gets the corrected steps -- every correction is applied the way Phase 3 applies
        them. The fixture's rows were never patched."""
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        assert "negative" not in _row(conn, "G/flowcharts/Proc.json")
        rd.rederive(conn, "v1", "Sig", MODEL)
        assert "Check whether the input is negative." in _texts(_spec(conn, "refine"))

    def test_another_components_entries_are_untouched(self, conn):
        before = json.loads(_row(conn, "G/test_specs.json"))["Ext|Caller"]
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        rd.rederive(conn, "v1", "Sig", MODEL)
        assert json.loads(_row(conn, "G/test_specs.json"))["Ext|Caller"] == before


class TestADescription:
    def test_the_spec_copies_the_corrected_text(self, conn):
        """The save hands over the model it wrote through: the write is not committed, and a
        fresh read would re-derive the words just replaced."""
        model = copy.deepcopy(MODEL)
        model["functions"][REFINE]["description"] = "Clamps a value to the valid range."
        rd.rederive(conn, "v1", "Sig", model)
        assert _spec(conn, "refine")["description"] == "Clamps a value to the valid range."


class TestWhereItDoesNothing:
    @staticmethod
    def _never():
        raise AssertionError("the model was read with nothing to re-derive")

    def test_a_version_without_swe4_output(self, conn):
        """Every version the web app generates. One query of paths, no model read."""
        conn.execute(sa.delete(s.version_output_files)
                     .where(s.version_output_files.c.rel_path == "G/test_specs.json"))
        assert rd.rederive(conn, "v1", "Sig", self._never) == []

    def test_a_component_no_swe4_document_carries(self, conn):
        assert rd.rederive(conn, "v1", "Oth", self._never) == []

    def test_a_directory_built_before_the_settings_were_kept(self, conn):
        """Its specs cannot be rebuilt as they were built, so nothing is written, and nothing
        returned to be stamped: the guard keeps calling SWE.4 stale, which is the truth."""
        conn.execute(sa.update(s.version_output_files)
                     .where(s.version_output_files.c.rel_path == "G/_derivations.json")
                     .values(content=g.record_text({"views": {"testSpecs": {
                         "at": T0.isoformat(), "components": ["ext", "sig"]}}})))
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        before = _row(conn, "G/test_specs.json")
        assert rd.rederive(conn, "v1", "Sig", self._never) == []
        assert _row(conn, "G/test_specs.json") == before

    def test_an_export_that_cannot_be_rebuilt_is_not_claimed(self, conn):
        """A UT export recorded for the component with no row to rebuild."""
        conn.execute(sa.delete(s.version_output_files)
                     .where(s.version_output_files.c.rel_path == "G/ut_export.json"))
        assert rd.rederive(conn, "v1", "Sig", MODEL) == ["testSpecs"]


class TestTheDeriver:
    """`make_save_deriver`, the `derive=` the API hands every save."""

    def test_a_kind_swe4_does_not_print_re_derives_nothing(self, conn):
        derive = rd.make_save_deriver(conn, TestWhereItDoesNothing._never)
        for kind in (slot.UNIT_DESCRIPTION, slot.INPUT_NAME,
                     slot.OUTPUT_NAME, slot.STRUCT_DESCRIPTION,
                     slot.BEHAVIOUR_DESCRIPTION):
            assert derive(version_id="v1", slot_kind=kind, location=None) == [], kind

    def test_a_label_re_derives_its_flowcharts_component(self, conn):
        _correct(conn, REFINE, "N2", "Check: the input is negative?")
        derive = rd.make_save_deriver(conn, MODEL)
        assert derive(version_id="v1", slot_kind=slot.NODE_LABEL,
                      flowchart_id=REFINE) == ["testSpecs", "utExport"]
        assert "Check whether the input is negative." in _texts(_spec(conn, "refine"))

    def test_a_description_re_derives_its_entitys_component(self, conn):
        from review.resolver import Location
        model = copy.deepcopy(MODEL)
        model["functions"][DRIVE]["description"] = "Corrected."
        derive = rd.make_save_deriver(conn, model)
        assert derive(version_id="v1", slot_kind=slot.DESCRIPTION,
                      location=Location("functions", DRIVE, "description")) \
            == ["testSpecs", "utExport"]
        assert _spec(conn, "drive")["description"] == "Corrected."

    def test_a_spec_that_cannot_be_built_does_not_lose_the_correction(self, conn,
                                                                      monkeypatch):
        """Nothing is claimed, so the guard keeps SWE.4 stale -- and the save goes through."""
        import views.test_specs

        def _broken(*a, **k):
            raise RuntimeError("a view bug")

        monkeypatch.setattr(views.test_specs, "build", _broken)
        derive = rd.make_save_deriver(conn, MODEL)
        assert derive(version_id="v1", slot_kind=slot.NODE_LABEL, flowchart_id=REFINE) == []

    def test_the_model_is_read_through_the_saves_connection(self, conn):
        """Never through the repository: a second connection inside the save's transaction
        waits on its lock (SQLite) or, sharing a single-connection pool, rolls it back."""
        from review import override_service as svc

        class _Refuses:
            def read(self, *a, **k):
                raise AssertionError("read through the repository's own connection")

        models = svc.ModelAccess(repo=_Refuses(), version_id="v1", project_id="p")
        model = rd.model_of(models, conn, "v1")
        assert set(model) == {"functions", "globalVariables", "units", "components",
                              "dataDictionary"}

    def test_what_the_save_holds_is_used_as_held(self, conn):
        """A description save corrected its artifact in memory; that copy is the one to use."""
        from review import override_service as svc
        models = svc.ModelAccess(artifacts=copy.deepcopy(MODEL))
        models.artifact("functions")[REFINE]["description"] = "Held."
        assert rd.model_of(models, conn, "v1")["functions"][REFINE]["description"] == "Held."


class TestTheSave:
    """Through `override_service`, as the API calls it: the rows, the stamp and the record."""

    def test_a_label_save_leaves_swe4_exportable(self, conn):
        from review import override_service as svc
        g.stamp_view_derivations(conn, "v1", [(v, c) for v in ("testSpecs", "utExport")
                                              for c in ("Ext", "Sig")], T0)
        out = svc.apply_flowchart_overrides(
            conn, "v1", REFINE, {"N2": "Check: the input is negative?"}, now=T1,
            derive=rd.make_save_deriver(conn, MODEL))
        assert list(out.views_derived) == ["testSpecs", "utExport"]
        assert "Check whether the input is negative." in _texts(_spec(conn, "refine"))
        assert not g.staleness(conn, "v1", "swe4").is_stale
        rec = json.loads(_row(conn, "G/_derivations.json"))
        assert rec["views"]["testSpecs"]["saved"] == {"sig": T1.isoformat()}

    def test_without_the_deriver_swe4_stays_stale(self, conn):
        """The other half: the guard is what stops an export-only run shipping the old step."""
        from review import override_service as svc
        g.stamp_view_derivations(conn, "v1", [(v, c) for v in ("testSpecs", "utExport")
                                              for c in ("Ext", "Sig")], T0)
        svc.apply_flowchart_overrides(conn, "v1", REFINE, {"N2": "Check: negative?"}, now=T1)
        assert g.staleness(conn, "v1", "swe4").is_stale


class TestTheParts:
    def test_the_model_is_narrowed_as_phase_3_narrows_it(self):
        """`narrow` restates `run_views._filter_model_to_components`, which cannot be imported
        into a server: importing `run_views` resets the process's run context."""
        import run_views
        model = copy.deepcopy(MODEL)
        model["units"]["Sample Core|X"] = {"name": "X", "functionIds": []}
        model["components"]["Sample-Core"] = {"units": ["Sample Core|X"]}
        for comps in ({"Sig"}, {"sig", "Sample Core"}, {"EXT"}):
            assert rd.narrow(model, comps) == run_views._filter_model_to_components(model, comps)

    def test_the_merge_keeps_the_views_layout(self):
        stored = {"unitNames": {"A|U": "U", "B|V": "V"}, "A|U": {"name": "U", "functions": [1]},
                  "B|V": {"name": "V", "functions": [2]},
                  "dynamicSpecs": {"A": [1], "B": [2]}}
        fresh = {"unitNames": {"B|W": "W"}, "B|W": {"name": "W", "functions": [3]},
                 "dynamicSpecs": {"B": [3]}}
        merged = rd.merge(stored, fresh, "b")
        assert list(merged) == ["unitNames", "A|U", "B|W", "dynamicSpecs"]
        assert merged["unitNames"] == {"A|U": "U", "B|W": "W"}
        assert merged["dynamicSpecs"] == {"A": [1], "B": [3]}
