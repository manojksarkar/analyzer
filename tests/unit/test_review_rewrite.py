"""An update rewrites the texts written from a corrected one (FAST_WORD_FILE_UPDATES P5, D1, D3).

The save queues the candidates (`cascade.dependents_of`); the update of their component
(`review.rewrite`) keeps those whose prompt holds the corrected text and rewrites them -- with the
generator that wrote them, from the model as it is now -- and leaves the rest:

    in another component         waits for that component's update (D3)
    a reviewer's own text        never rewritten (REQ-CS-03)
    in an approved document      waits until it is reopened
    its prompt did not move      retired, unchanged
    no answer from the LLM       keeps its words and its entry
    a chart                      handed to Phase 3, retired once that run is stored

The LLM is a stub throughout: every generator the step calls is replaced, and the cache has no
project, so nothing here reaches a database or a network.
"""
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s                     # noqa: E402
from core import model_store as ms                          # noqa: E402
from review import cascade, rewrite, slot                   # noqa: E402

PID, VID = "p", "v1"
CALLER = "Comp|UnitA|ns::caller|void"
CALLEE = "Comp|UnitA|ns::callee|void"
ALONE = "Comp|UnitB|ns::alone|void"
FAR = "Other|UnitC|ns::far|void"
USE_X = "Comp|UnitA|ns::useX|void"
GX = "Comp|UnitA|g_x"
F = "Comp|UnitA|ns::f|void"
G = "Comp|UnitB|ns::g|void"
EXT = "Ext|UnitX|ns::c|void"

LLM = {"provider": "ollama", "baseUrl": "http://localhost:11434", "defaultModel": "m",
       "timeoutSeconds": 5, "numCtx": 8192, "retries": 0, "descriptions": True,
       "behaviourNames": True}
CONFIG = {"llm": LLM}
NOW = datetime.datetime(2026, 10, 7, tzinfo=datetime.timezone.utc)

SOURCE = {"a.cpp": "void caller() {\n  callee();\n}\nint x;\nvoid callee() {\n  x++;\n}\n"
                   "void useX() {\n  return;\n}\nvoid f() {\n  g();\n}\n",
          "b.cpp": "void alone() {\n}\nvoid g() {\n}\n",
          "c.cpp": "void far() {\n}\nvoid c() {\n  f();\n}\n"}


def _fn(qn, path, line, end, desc, **more):
    return {"qualifiedName": qn, "location": {"file": path, "line": line, "endLine": end},
            "description": desc, **more}


@pytest.fixture
def src(tmp_path):
    for name, text in SOURCE.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return str(tmp_path)


@pytest.fixture
def eng():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    s.metadata.create_all(engine)
    with engine.begin() as cx:
        cx.execute(sa.insert(s.projects).values(id=PID, name=PID, created_at=NOW))
        cx.execute(sa.insert(s.versions).values(id=VID, project_id=PID, version="v1",
                                                created_at=NOW))
        ms.persist_functions(cx, PID, VID, {
            CALLER: _fn("ns::caller", "a.cpp", 1, 3, "LLM caller", callsIds=[CALLEE]),
            CALLEE: _fn("ns::callee", "a.cpp", 5, 7, "CORRECTED callee"),
            ALONE: _fn("ns::alone", "b.cpp", 1, 2, "LLM alone"),
            FAR: _fn("ns::far", "c.cpp", 1, 2, "LLM far"),
            USE_X: _fn("ns::useX", "a.cpp", 8, 10, "LLM useX", readsGlobalIds=[GX],
                       readsGlobalIdsTransitive=[GX], inputName="LLM in", outputName="LLM out"),
            F: _fn("ns::f", "a.cpp", 11, 13, "LLM f", callsIds=[G]),
            G: _fn("ns::g", "b.cpp", 3, 4, "CORRECTED g"),
            EXT: _fn("ns::c", "c.cpp", 3, 5, "LLM c", callsIds=[F]),
        })
        ms.persist_globals(cx, PID, VID, {
            GX: {"qualifiedName": "g_x", "location": {"file": "a.cpp", "line": 4},
                 "type": "int", "description": "CORRECTED x"}})
        ms.persist_units(cx, VID, {u: {"name": u.split("|")[1], "description": "LLM unit"}
                                   for u in ("Comp|UnitA", "Comp|UnitB", "Other|UnitC",
                                             "Ext|UnitX")})
        ms.persist_components(cx, VID, {c: {} for c in ("Comp", "Other", "Ext")})
        for key, llm in ((CALLEE, "LLM callee"), (G, "LLM g"), (GX, "LLM x")):
            _correct(cx, slot.DESCRIPTION, key, llm, "CORRECTED " + llm.split()[-1])
    return engine


def _correct(cx, kind, key, llm, human):
    cx.execute(sa.insert(s.text_overrides).values(
        version_id=VID, slot_kind=kind, slot_key=key, llm_text=llm, human_text=human,
        is_orphaned=False, updated_at=NOW))


def _queue(eng, *items):
    with eng.begin() as cx:
        cascade.enqueue(cx, VID, [cascade.Dependent(k, key, "test") for k, key in items], now=NOW)


def _pending(eng):
    with eng.connect() as cx:
        return {(r.slot_kind, r.slot_key) for r in cascade.pending(cx, VID)}


def _description(eng, key):
    with eng.connect() as cx:
        fns = ms.load_functions(cx, VID)
        return (fns.get(key) or ms.load_globals(cx, VID).get(key) or {}).get("description")


@pytest.fixture
def llm(monkeypatch):
    """The generators the step calls, stubbed; records what each was asked."""
    import llm_enrichment as le
    from llm_core.cache import EntityCache
    from behaviour_diagram.llm_call_description import CallDescriptionGenerator
    asked = {"functions": [], "globals": [], "units": [], "names": [], "calls": []}
    answers = {"fail": False}

    def functions(funcs, base_path, config, knowledge=None, regenerate=None, only=None):
        asked["functions"].append(sorted(only or ()))
        assert set(regenerate or ()) == set(only or ())        # past the cache, every one
        return {} if answers["fail"] else {k: {"description": "NEW " + k} for k in only}

    def globals_(globals_data, functions_data, base_path, config, knowledge=None):
        asked["globals"].append(sorted(globals_data))
        return {le._make_canonical_key(g): {"description": "NEW global"}
                for g in globals_data.values()}

    def unit(name, fn_items, gv_items, config, abbreviations=None):
        asked["units"].append((name, fn_items, gv_items))
        return "" if answers["fail"] else "NEW unit " + name

    def names(source, params, globals_read, globals_written, *a, **k):
        asked["names"].append([g.get("description") for g in globals_read])
        return {} if answers["fail"] else {"inputName": "NEW in", "outputName": "NEW out"}

    def query(self, context):
        asked["calls"].append(context)
        return "" if answers["fail"] else "NEW call"

    monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)
    monkeypatch.setattr(le, "enrich_functions_rich", functions)
    monkeypatch.setattr(le, "enrich_globals_rich", globals_)
    monkeypatch.setattr(le, "get_unit_description", unit)
    monkeypatch.setattr(le, "get_behaviour_names", names)
    monkeypatch.setattr(le, "_AUX_DESC_CACHE", EntityCache("", "aux_descriptions", 1))
    monkeypatch.setattr(CallDescriptionGenerator, "_is_llm_available", lambda self: True)
    monkeypatch.setattr(CallDescriptionGenerator, "_query_llm_for_description", query)
    return asked, answers


def _run(eng, src, components=None, config=CONFIG):
    return rewrite.rewrite_queued(eng, VID, components, config=config, base_path=src,
                                  log=lambda _m: None)


# ---------------------------------------------------------------------------
# descriptions
# ---------------------------------------------------------------------------
class TestDescriptions:
    def test_one_whose_prompt_holds_the_corrected_text_is_rewritten(self, eng, src, llm):
        """CALLER's prompt lists its callee's description, which a reviewer corrected."""
        asked, _ = llm
        _queue(eng, (slot.DESCRIPTION, CALLER))
        result = _run(eng, src)
        assert asked["functions"] == [[CALLER]]
        assert _description(eng, CALLER) == "NEW " + CALLER
        assert result.rewritten == {slot.DESCRIPTION: 1}
        assert _pending(eng) == set()

    def test_one_whose_prompt_does_not_hold_it_is_retired_unchanged(self, eng, src, llm):
        asked, _ = llm
        _queue(eng, (slot.DESCRIPTION, ALONE))
        result = _run(eng, src)
        assert asked["functions"] == []
        assert _description(eng, ALONE) == "LLM alone"
        assert (result.unchanged, _pending(eng)) == (1, set())

    def test_a_global_whose_writers_and_readers_hold_it(self, eng, src, llm, monkeypatch):
        """A global's prompt lists its readers and writers from the knowledge base -- brought up
        to date with the model's corrections first."""
        asked, _ = llm
        gy = "Comp|UnitA|g_y"
        with eng.begin() as cx:
            ms.persist_globals(cx, PID, VID, {
                gy: {"qualifiedName": "g_y", "location": {"file": "a.cpp", "line": 4},
                     "type": "int", "description": "LLM y"}})
            ms.persist_knowledge_base(cx, VID, {
                "functions": {"ns::callee": {"qualifiedName": "ns::callee",
                                             "description": "LLM callee"}},
                "globals": {"g_y": {"qualifiedName": "g_y", "type": "int",
                                    "readBy": ["ns::callee"], "writtenBy": []}}})
        _queue(eng, (slot.DESCRIPTION, gy))
        _run(eng, src)
        assert asked["globals"] == [[gy]]
        assert _description(eng, gy) == "NEW global"

    def test_a_reviewer_s_own_text_is_never_rewritten(self, eng, src, llm):
        """REQ-CS-03, checked again when it is stored."""
        asked, _ = llm
        with eng.begin() as cx:
            _correct(cx, slot.DESCRIPTION, CALLER, "LLM caller", "HUMAN caller")
            ms.set_entity_field(cx, VID, CALLER, "description", "HUMAN caller", ("function",))
        _queue(eng, (slot.DESCRIPTION, CALLER))
        _run(eng, src)
        assert asked["functions"] == []
        assert _description(eng, CALLER) == "HUMAN caller"
        assert _pending(eng) == set()

    def test_a_failed_rewrite_keeps_the_words_and_the_entry(self, eng, src, llm):
        _asked, answers = llm
        answers["fail"] = True
        _queue(eng, (slot.DESCRIPTION, CALLER))
        result = _run(eng, src)
        assert _description(eng, CALLER) == "LLM caller"
        assert _pending(eng) == {(slot.DESCRIPTION, CALLER)}
        assert result.waiting == 1 and result.failed


# ---------------------------------------------------------------------------
# which entries an update takes
# ---------------------------------------------------------------------------
class TestWhichEntries:
    def test_another_component_waits_for_its_own_update(self, eng, src, llm):
        """D3: an update rewrites inside its own components."""
        _queue(eng, (slot.DESCRIPTION, CALLER), (slot.DESCRIPTION, FAR))
        _run(eng, src, components=["Comp"])
        assert _pending(eng) == {(slot.DESCRIPTION, FAR)}

    def test_an_approved_document_holds_its_texts(self, eng, src, llm):
        asked, _ = llm
        with eng.begin() as cx:
            cx.execute(sa.insert(s.documents).values(id="d1", project_id=PID, version_id=VID,
                                                     process="SWE.3", component="Comp",
                                                     status="approved"))
        _queue(eng, (slot.DESCRIPTION, CALLER))
        result = _run(eng, src)
        assert asked["functions"] == []
        assert (result.waiting, _pending(eng)) == (1, {(slot.DESCRIPTION, CALLER)})

    def test_a_version_made_without_the_llm_rewrites_nothing(self, eng, src, llm):
        asked, _ = llm
        _queue(eng, (slot.DESCRIPTION, CALLER))
        result = _run(eng, src, config={"llm": {**LLM, "descriptions": False}})
        assert asked["functions"] == [] and result.waiting == 1
        assert _pending(eng) == {(slot.DESCRIPTION, CALLER)}

    def test_nothing_queued_reads_nothing(self, eng, src, llm):
        assert _run(eng, src) == rewrite.NOTHING


# ---------------------------------------------------------------------------
# a unit's description, the input and output names
# ---------------------------------------------------------------------------
class TestUnitsAndNames:
    def test_a_unit_description_is_written_from_its_functions_as_they_are_now(self, eng, src,
                                                                               llm):
        asked, _ = llm
        _queue(eng, (slot.UNIT_DESCRIPTION, slot.for_unit("Comp|UnitA")))
        _run(eng, src)
        (name, fn_items, _gv), = asked["units"]
        assert ("callee", "CORRECTED callee") in fn_items
        with eng.connect() as cx:
            assert ms.load_units(cx, VID)["Comp|UnitA"]["description"] == "NEW unit UnitA"

    def test_names_written_from_a_corrected_global(self, eng, src, llm):
        """useX's static names are poor (its global's name is too short to read), so Phase 2
        asked the LLM -- with the global's description, which a reviewer corrected."""
        asked, _ = llm
        _queue(eng, (slot.INPUT_NAME, USE_X))
        _run(eng, src)
        assert asked["names"] == [["CORRECTED x"]]
        with eng.connect() as cx:
            f = ms.load_functions(cx, VID)[USE_X]
        assert (f["inputName"], f["outputName"]) == ("NEW in", "NEW out")

    def test_no_answer_keeps_the_llm_s_earlier_names(self, eng, src, llm):
        """Its silence leaves the poor static names, which must not replace the LLM's."""
        _asked, answers = llm
        answers["fail"] = True
        _queue(eng, (slot.INPUT_NAME, USE_X))
        _run(eng, src)
        with eng.connect() as cx:
            f = ms.load_functions(cx, VID)[USE_X]
        assert (f["inputName"], f["outputName"]) == ("LLM in", "LLM out")
        assert _pending(eng) == {(slot.INPUT_NAME, USE_X)}

    def test_a_corrected_name_is_kept(self, eng, src, llm):
        with eng.begin() as cx:
            _correct(cx, slot.INPUT_NAME, USE_X, "LLM in", "HUMAN in")
            ms.set_entity_field(cx, VID, USE_X, "inputName", "HUMAN in", ("function",))
        _queue(eng, (slot.INPUT_NAME, USE_X))
        _run(eng, src)
        with eng.connect() as cx:
            f = ms.load_functions(cx, VID)[USE_X]
        assert (f["inputName"], f["outputName"]) == ("HUMAN in", "NEW out")


# ---------------------------------------------------------------------------
# a behaviour row, call by call
# ---------------------------------------------------------------------------
ROW_PATH = "Comp/behaviour_diagrams/_behaviour_pngs.json"


def _store_row(eng, bullets):
    with eng.begin() as cx:
        cx.execute(sa.insert(s.version_output_files).values(
            version_id=VID, rel_path=ROW_PATH, group_name="Comp",
            content=json.dumps({"_docxRows": {"Comp": {"UnitA": [
                {"currentFunctionId": F, "externalCallerId": EXT,
                 "behaviorDescription": bullets}]}}})))


def _stored_row(eng):
    with eng.connect() as cx:
        content = cx.execute(sa.select(s.version_output_files.c.content).where(
            s.version_output_files.c.rel_path == ROW_PATH)).scalar()
    return json.loads(content)["_docxRows"]["Comp"]["UnitA"][0]["behaviorDescription"]


class TestBehaviourRows:
    """f (UnitA) calls g (UnitB), and c in another component calls f: the row's bullets are the
    incoming call c -> f and f -> g, each from both ends' descriptions, then the two returns."""
    STORED = ["c calls f, stored", "f calls g, stored", "ns::g returns to ns::f",
              "ns::f returns to ns::c"]

    def test_only_the_call_whose_prompt_moved_is_asked_again(self, eng, src, llm):
        """g's description was corrected: f -> g is asked again; c -> f keeps its words."""
        asked, _ = llm
        _store_row(eng, self.STORED)
        _queue(eng, (slot.BEHAVIOUR_DESCRIPTION, slot.for_behaviour_row(F, EXT)))
        result = _run(eng, src)
        assert len(asked["calls"]) == 1 and "CORRECTED g" in asked["calls"][0]
        assert _stored_row(eng) == ["c calls f, stored", "NEW call", "ns::g returns to ns::f",
                                    "ns::f returns to ns::c"]
        assert result.rewritten == {slot.BEHAVIOUR_DESCRIPTION: 1}
        assert _pending(eng) == set()

    def test_a_row_whose_calls_did_not_move_is_retired_as_it_is(self, eng, src, llm):
        asked, _ = llm
        with eng.begin() as cx:
            cx.execute(sa.delete(s.text_overrides).where(s.text_overrides.c.slot_key == G))
        _store_row(eng, self.STORED)
        _queue(eng, (slot.BEHAVIOUR_DESCRIPTION, slot.for_behaviour_row(F, EXT)))
        _run(eng, src)
        assert asked["calls"] == [] and _stored_row(eng) == self.STORED
        assert _pending(eng) == set()

    def test_no_answer_keeps_the_row(self, eng, src, llm):
        _asked, answers = llm
        answers["fail"] = True
        _store_row(eng, self.STORED)
        _queue(eng, (slot.BEHAVIOUR_DESCRIPTION, slot.for_behaviour_row(F, EXT)))
        _run(eng, src)
        assert _stored_row(eng) == self.STORED
        assert len(_pending(eng)) == 1


class TestTheCallerARowWasDrawnFor:
    """The view pairs the selector's i-th caller with the i-th direct caller from another
    component, and the selector also takes callers of callers."""

    class Gen:
        function_to_unit = {"C|U|f|": "C|U"}
        functions = {"C|U|f|": {"calledByIds": ["C|V|own|", "X|W|direct|"]}}

    class Sel:
        def __init__(self, picked):
            self.picked = picked

        def select_diagrams_to_generate(self, fid):
            return self.picked

    def test_the_selector_s_caller_at_the_row_s_place(self):
        sel = self.Sel([("Y|Z|callers_caller|", "Y")])
        assert rewrite._drawn_for(self.Gen, sel, "C|U|f|", "X|W|direct|") == "Y|Z|callers_caller|"

    def test_a_caller_the_view_did_not_pair_is_none(self):
        assert rewrite._drawn_for(self.Gen, self.Sel([]), "C|U|f|", "X|W|direct|") is None
        assert rewrite._drawn_for(self.Gen, self.Sel([("a", "b")]), "C|U|f|", "C|V|own|") is None


# ---------------------------------------------------------------------------
# a chart: Phase 3's part
# ---------------------------------------------------------------------------
def _store_chart(eng, key, name):
    with eng.begin() as cx:
        cx.execute(sa.insert(s.version_output_files).values(
            version_id=VID, rel_path="Comp/flowcharts/a.json", group_name="Comp",
            content=json.dumps([{"functionKey": key, "name": name, "flowchart": "digraph{}"}])))


class TestCharts:
    def test_a_stored_chart_whose_prompt_moved_goes_to_phase_3(self, eng, src, llm):
        """CALLER's label prompts name its callee's description."""
        _store_chart(eng, CALLER, "ns::caller")
        _queue(eng, (cascade.FLOWCHART_LABELS, CALLER))
        result = _run(eng, src)
        assert result.charts == [CALLER]
        assert _pending(eng) == {(cascade.FLOWCHART_LABELS, CALLER)}     # until Phase 3's run

    def test_a_chart_printed_nowhere_is_retired(self, eng, src, llm):
        _queue(eng, (cascade.FLOWCHART_LABELS, CALLER))
        result = _run(eng, src)
        assert result.charts == [] and _pending(eng) == set()

    def test_the_request_and_its_report_retire_what_was_rewritten(self, eng, tmp_path):
        _queue(eng, (cascade.FLOWCHART_LABELS, CALLER), (cascade.FLOWCHART_LABELS, ALONE))
        req = str(tmp_path / "req.json")
        assert rewrite.write_labels_request(req, [CALLER, ALONE]) == req
        assert rewrite.read_labels_request(req) == {"keys": sorted([CALLER, ALONE]),
                                                    "report": req + ".done"}
        with open(req + ".done", "w", encoding="utf-8") as fh:
            fh.write(CALLER + "\n")                   # the engine's report: CALLER alone
        assert rewrite.labels_done(eng, VID, req) == 1
        assert _pending(eng) == {(cascade.FLOWCHART_LABELS, ALONE)}

    def test_no_chart_leaves_no_request(self, tmp_path):
        req = tmp_path / "req.json"
        req.write_text("{}", encoding="utf-8")
        (tmp_path / "req.json.done").write_text("old\n", encoding="utf-8")
        assert rewrite.write_labels_request(str(req), []) is None
        assert not req.exists() and not (tmp_path / "req.json.done").exists()


class TestTheViewSplicesTheRewrittenCharts:
    """The update's Phase 3 charts the named functions alone. The engine writes unit files
    holding those alone, and a summary of them; the view puts each chart the engine reported
    into the stored file, and everything else back as it was."""

    def _write(self, d, name, data):
        (d / name).write_text(json.dumps(data), encoding="utf-8")

    def _read(self, d, name):
        return json.loads((d / name).read_text(encoding="utf-8"))

    def test_rewritten_charts_go_in_and_the_rest_stays(self, tmp_path):
        from views import flowcharts as fv
        self._write(tmp_path, "a.json", [{"functionKey": "K1", "name": "n1", "flowchart": "o1"},
                                         {"functionKey": "K2", "name": "n2", "flowchart": "o2"}])
        self._write(tmp_path, "b.json", [{"name": "n3", "flowchart": "o3"}])     # before keys
        self._write(tmp_path, "_summary.json", {"totalFunctions": 3})
        stored = fv._stored_unit_files(str(tmp_path))
        # what the engine wrote, charting K1..K4
        self._write(tmp_path, "a.json", [{"functionKey": "K1", "name": "n1", "flowchart": "N1"},
                                         {"functionKey": "K2", "name": "n2", "flowchart": "",
                                          "error": "boom"}])
        self._write(tmp_path, "b.json", [{"functionKey": "K3", "name": "n3", "flowchart": "N3"}])
        self._write(tmp_path, "c.json", [{"functionKey": "K4", "name": "n4", "flowchart": "N4"}])
        self._write(tmp_path, "_summary.json", {"totalFunctions": 3, "of": "the rewrite"})
        spliced = fv._splice_rewritten(str(tmp_path), stored, ["K1", "K2", "K3", "K4"])
        assert spliced == ["K1", "K3"]
        assert [e["flowchart"] for e in self._read(tmp_path, "a.json")] == ["N1", "o2"]
        assert self._read(tmp_path, "b.json")[0]["flowchart"] == "N3"
        assert self._read(tmp_path, "_summary.json") == {"totalFunctions": 3}
        assert not (tmp_path / "c.json").exists()        # not stored here: not printed here

    def test_a_chart_not_reported_keeps_its_stored_entry(self, tmp_path):
        from views import flowcharts as fv
        self._write(tmp_path, "a.json", [{"functionKey": "K1", "name": "n1", "flowchart": "o1"}])
        stored = fv._stored_unit_files(str(tmp_path))
        self._write(tmp_path, "a.json", [{"functionKey": "K1", "name": "n1", "flowchart": "N1"}])
        assert fv._splice_rewritten(str(tmp_path), stored, []) == []
        assert self._read(tmp_path, "a.json")[0]["flowchart"] == "o1"

    def test_a_failed_engine_puts_the_stored_charts_back(self, tmp_path):
        from views import flowcharts as fv
        self._write(tmp_path, "a.json", [{"functionKey": "K1", "flowchart": "o1"}])
        stored = fv._stored_unit_files(str(tmp_path))
        self._write(tmp_path, "a.json", [])
        work = tmp_path / "work"
        work.mkdir()
        fv._end_rewrite(str(work), str(tmp_path), stored)
        assert self._read(tmp_path, "a.json") == [{"functionKey": "K1", "flowchart": "o1"}]
        assert not work.exists()

    def test_the_request_reaches_the_view(self):
        from views import flowcharts as fv
        assert fv._rewrite_request({}) == {}
        assert fv._rewrite_request({"_analyzerRewriteLabels": {"keys": []}}) == {}
        req = {"keys": ["K"], "report": "R", "only": True}
        assert fv._rewrite_request({"_analyzerRewriteLabels": req}) == req


class TestTheUpdatesPhase3:
    def test_only_the_named_views_run(self, monkeypatch, tmp_path):
        import views
        from views.registry import VIEW_REGISTRY
        ran = []
        for name in list(VIEW_REGISTRY):
            monkeypatch.setitem(VIEW_REGISTRY, name, lambda *a, _n=name: ran.append(_n))
        cfg = {"views": {"flowcharts": True, "behaviourDiagram": True}}
        out = views.run_views({}, str(tmp_path), str(tmp_path), cfg, doc_type="all",
                              only=["flowcharts", "testSpecs", "utExport"])
        assert out == ran and set(ran) == {"flowcharts", "testSpecs", "utExport"}

    def test_run_views_reads_the_request(self, tmp_path):
        import run_views
        req = tmp_path / "req.json"
        rewrite.write_labels_request(str(req), ["K"])
        assert run_views._rewrite_request(str(req), only=True) == {
            "keys": ["K"], "report": str(req) + ".done", "only": True}
        with pytest.raises(SystemExit):
            run_views._rewrite_request(str(tmp_path / "missing.json"), only=False)

    def test_run_py_hands_both_to_phase_3_alone(self):
        src = open(os.path.join(PROJECT_ROOT, "engine", "run.py"), encoding="utf-8").read()
        block = src[src.index("if views_arg or rewrite_labels_arg:"):]
        block = block[:block.index("\n\n")]
        assert 'os.path.basename(_ph.script) == "run_views.py"' in block
        assert '_ph.args.extend(["--views", views_arg])' in block
        assert '_ph.args.extend(["--rewrite-labels", rewrite_labels_arg])' in block


class TestTheAnalyzerChangesItsPhase3:
    """An export-only update with charts to write again makes Phase 3 for the flowcharts and the
    SWE.4 views alone -- or all of them, when a correction made meanwhile put another behind."""

    def _with(self, monkeypatch, behind):
        import analyzer as A
        asked = []
        monkeypatch.setattr(A, "_refuse_stale_export",
                            lambda *a, **k: asked.append(k) or (2 if behind else 0))
        return A, asked

    def test_export_only_becomes_the_label_views(self, monkeypatch):
        A, asked = self._with(monkeypatch, behind=False)
        out = A._with_label_rewrite(["--from-phase", "4", "--use-model", "src"], "req", "v1",
                                    "swe3", ["Comp"])
        assert out[out.index("--from-phase") + 1] == "3"
        assert out[out.index("--views") + 1] == "flowcharts,testSpecs,utExport"
        assert out[out.index("--rewrite-labels") + 1] == "req"
        assert asked == [{"quiet": True, "components": ["Comp"], "pictures": False}]

    def test_another_view_behind_makes_them_all(self, monkeypatch):
        A, _asked = self._with(monkeypatch, behind=True)
        out = A._with_label_rewrite(["--from-phase", "4", "--use-model", "src"], "req", "v1",
                                    "swe3", None)
        assert out[out.index("--from-phase") + 1] == "3" and "--views" not in out

    def test_a_run_with_phase_3_just_carries_the_charts(self, monkeypatch):
        A, asked = self._with(monkeypatch, behind=False)
        out = A._with_label_rewrite(["--from-phase", "2", "src"], "req", "v1", "swe3", None)
        assert out == ["--from-phase", "2", "src", "--rewrite-labels", "req"] and asked == []


# ---------------------------------------------------------------------------
# the update's components (D3)
# ---------------------------------------------------------------------------
class TestScopeComponents:
    CFG = {"layers": {"Layer1": {"groups": {"Support": {"Sample Core": "core", "Lib": "lib"},
                                            "App": {"Main": "main"}}},
                      "Layer2": {"groups": {"Drivers": {"Uart": "uart"}}}}}

    def test_each_scope(self):
        sc = rewrite.scope_components
        assert sc(self.CFG, {"type": "component", "names": ["Layer1.Lib"]}) == ["Layer1.Lib"]
        assert sorted(sc(self.CFG, {"type": "group", "names": ["Layer1.Support"]})) == [
            "Layer1.Lib", "Layer1.Sample Core"]
        assert sc(self.CFG, {"type": "group", "names": ["App"]}) == ["Layer1.Main"]
        assert sorted(sc(self.CFG, {"type": "layer", "names": ["Layer1"]})) == [
            "Layer1.Lib", "Layer1.Main", "Layer1.Sample Core"]
        assert sc(self.CFG, {"type": "project"}) is None
        assert sc(self.CFG, None) is None


# ---------------------------------------------------------------------------
# the knowledge base's copies of the descriptions
# ---------------------------------------------------------------------------
class TestKnowledgeOverlay:
    def test_the_model_s_descriptions_over_the_copies_an_overload_aside(self):
        from flowchart.pkb.knowledge import load_knowledge_data, overlay_descriptions
        kb = load_knowledge_data({
            "functions": {"a": {"description": "old a"}, "dup": {"description": "old dup"}},
            "globals": {"g": {"description": "old g"}}})
        n = overlay_descriptions(
            kb, {"k1": {"qualifiedName": "a", "description": "new a"},
                 "k2": {"qualifiedName": "dup", "description": "one"},
                 "k3": {"qualifiedName": "dup", "description": "two"}},
            {"kg": {"qualifiedName": "g", "description": "new g"}})
        assert n == 2
        assert kb.functions["a"].description == "new a"
        assert kb.functions["dup"].description == "old dup"
        assert kb.globals["g"].description == "new g"
        assert overlay_descriptions(None, {}, {}) == 0
