"""Demo branch: the LLM describes only the components whose documents are asked for
(`llm.onlyRequestedComponents`). Parse and the code-based part of Phase 2 still cover whole
layers; only which entities get LLM text is limited. These pin the rules:

* the requested components are the version's `version_components` rows, matched to a key's
  component the way the pipeline compares names (spaces as '-', any case);
* off, or a version that names none, means no limit -- exactly today's behaviour;
* the function loop keeps the full run's bottom-up order and drops the others;
* unit and struct descriptions skip what belongs to a component nobody asked for;
* an export chains its "describe first" step after the layer-add step.
"""
import os
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import model_deriver as md  # noqa: E402


ON = {"llm": {"onlyRequestedComponents": True}}


class TestTheScope:
    def test_off_means_no_limit(self, monkeypatch):
        monkeypatch.setattr("core.version_run.requested_components", lambda vid: ["Layer1.Lib"])
        assert md._llm_scope({"llm": {}}) == (None, [])
        assert md._llm_scope({"llm": {"onlyRequestedComponents": False}}) == (None, [])

    def test_a_version_that_names_none_means_no_limit(self, monkeypatch):
        monkeypatch.setattr("core.version_run.requested_components", lambda vid: None)
        assert md._llm_scope(ON) == (None, [])

    def test_keys_of_the_requested_components_only(self, monkeypatch):
        monkeypatch.setattr("core.version_run.requested_components",
                            lambda vid: ["Layer1.Sample-Core", "Layer2.Gpio"])
        in_scope, names = md._llm_scope(ON)
        assert names == ["Layer1.Sample-Core", "Layer2.Gpio"]
        # A key carries the component id with its space; the rows carry the folder name.
        assert in_scope("Layer1.Sample Core|Core|ns::run|int")
        assert in_scope("layer2.gpio|Gpio|gpioInit|")
        assert not in_scope("Layer1.Lib|Lib|libAdd|int,int")
        assert not in_scope("Layer2.Sample Core|Core|ns::run|int"), "same name, other layer"
        assert not in_scope("")

    def test_a_database_that_cannot_answer_means_no_limit(self, monkeypatch):
        def boom(vid):
            raise RuntimeError("no database")
        monkeypatch.setattr("core.version_run.requested_components", boom)
        assert md._llm_scope(ON) == (None, [])


class TestRequestedComponents:
    def test_no_version_or_no_database_answers_none(self, monkeypatch):
        from core import version_run as vr
        assert vr.requested_components(None) is None
        monkeypatch.setattr(vr, "_engine", lambda: None)
        assert vr.requested_components("p.v1") is None


class TestUnitAndStructDescriptions:
    """Units and records of a component nobody asked for are left without text."""

    def _run(self, monkeypatch, in_scope):
        import llm_enrichment as le
        asked = {"units": [], "structs": []}
        monkeypatch.setattr(le, "llm_provider_reachable", lambda cfg: True)
        monkeypatch.setattr(le, "get_unit_description",
                            lambda name, fn, gv, cfg, ab: asked["units"].append(name) or f"{name} text")
        monkeypatch.setattr(le, "get_struct_description",
                            lambda name, fields, cfg, ab: asked["structs"].append(name) or f"{name} text")
        monkeypatch.setattr(md, "_iface_items_for_unit", lambda *a: ([("f", "Does f.")], []))
        units = {"Layer1.Lib|Lib": {"name": "Lib"}, "Layer1.Util|Util": {"name": "Util"}}
        dd = {"LibState": {"kind": "struct", "name": "LibState", "location": {"file": "Layer1/Lib/Lib.h"}},
              "UtilState": {"kind": "struct", "name": "UtilState", "location": {"file": "Layer1/Util/Util.h"}}}
        monkeypatch.setattr(md, "_unit_of", lambda entry, base: (
            "Layer1.Lib|Lib" if "Lib" in entry["location"]["file"] else "Layer1.Util|Util"))
        n = md._enrich_unit_and_struct_descriptions(units, {}, {}, dd, {"llm": {"descriptions": True}},
                                                    in_scope=in_scope, base_path="/src")
        return n, asked, units, dd

    def test_only_the_requested_ones(self, monkeypatch):
        n, asked, units, dd = self._run(monkeypatch, lambda key: key.startswith("Layer1.Lib|"))
        assert n == (1, 1)
        assert asked == {"units": ["Lib"], "structs": ["LibState"]}
        assert not units["Layer1.Util|Util"].get("description")
        assert not dd["UtilState"].get("description")

    def test_without_a_scope_every_one_as_before(self, monkeypatch):
        n, asked, _u, _d = self._run(monkeypatch, None)
        assert n == (2, 2)


class TestTheFunctionLoopKeepsItsOrder:
    def test_only_filters_the_bottom_up_order(self, monkeypatch):
        """`only` drops functions from the full run's order; it never reorders what is left."""
        import llm_enrichment as le
        seen = []
        monkeypatch.setattr(le, "llm_provider_reachable", lambda cfg: True)
        # Stop right after the order is decided: the first thing done with it is the LLM setup.
        def stop(*a, **k):
            raise _Stop()
        monkeypatch.setattr(le, "load_llm_config", stop)

        class _Stop(Exception):
            pass

        funcs = {"c": {"callsIds": []}, "b": {"callsIds": ["c"]}, "a": {"callsIds": ["b"]},
                 "x": {"callsIds": []}}
        # Read the order through the filter: patch the list the loop builds by wrapping `only`.
        class Spy(set):
            def __contains__(self, k):
                seen.append(k)
                return set.__contains__(self, k)
        with pytest.raises(_Stop):
            le.enrich_functions_rich(funcs, "/src", {"llm": {}}, only=Spy({"a", "c"}))
        assert [k for k in seen if k in ("a", "b", "c")] == ["c", "b", "a"], "bottom-up, as a full run"
        assert le.enrich_functions_rich(funcs, "/src", {"llm": {}}, only=set()) == {}


class TestExportDescribesFirst:
    def test_hooks_run_in_order_and_the_first_failure_stops(self):
        import analyzer
        calls = []
        ok = lambda *a: calls.append("adder") or 0          # noqa: E731
        bad = lambda *a: calls.append("adder") or 4         # noqa: E731
        describe = lambda *a: calls.append("describe") or 0  # noqa: E731
        assert analyzer._chain_before(None, describe) is describe
        assert analyzer._chain_before(ok, describe)("c", False, "/src", "swe3") == 0
        assert calls == ["adder", "describe"]
        calls.clear()
        assert analyzer._chain_before(bad, describe)("c", False, "/src", "swe3") == 4
        assert calls == ["adder"], "a layer add that failed is not followed by a describe"

    def test_the_switch_is_on_on_this_branch(self):
        import json
        cfg = json.load(open(os.path.join(PROJECT_ROOT, "engine", "config", "config.defaults.json"),
                             encoding="utf-8"))
        assert cfg["llm"]["onlyRequestedComponents"] is True
