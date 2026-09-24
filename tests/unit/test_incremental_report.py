"""Unit tests for src/incremental/report.py — end-of-run report (M3.4)."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental import report as R
from incremental.report import build_report, build_run_summary


def _incremental_stats():
    return {
        "versionId": "v2", "decision": "incremental", "status": "complete",
        "projectId": "samplecpp", "branch": "main", "commit": "3433fd6d6911",
        "scope": "group:Support", "baselineVersionId": "v1", "baselineCommit": "08d2f565cd03",
        "changedFiles": 3, "dataDictId": "dd-001",
        "llmModel": "openai/gpt-oss-120b", "elapsedSeconds": 123.4,
        "classification": {"changed": {"function": 3}, "new": {}, "deleted": {},
                           "unchanged": {"function": 110, "global": 12, "type": 14, "macro": 9}},
        "functions": {"total": 113, "regenerated": 9, "reused": 104},
        "globals": {"total": 12, "regenerated": 3, "reused": 9},
        "files": {"total": 18, "regenerated": 5, "carried": 13},
        "documents": ["software_detailed_design_Support.docx"], "warnings": [],
    }


class TestBuildReport:
    def test_incremental_has_key_sections_and_numbers(self):
        text = "\n".join(build_report(_incremental_stats()))
        assert "GENERATION REPORT" in text and "incremental" in text
        assert "Baseline" in text and "v1 @ 08d2f565cd" in text and "3 changed file" in text
        assert "regenerated 9" in text and "reused 104 (92%)" in text          # functions
        assert "regenerated 3" in text and "reused 9 (75%)" in text            # globals
        assert "carried 13 (72%)" in text                                       # flowcharts
        assert "software_detailed_design_Support.docx" in text
        assert "123.4s" in text

    def test_classification_rendered(self):
        text = "\n".join(build_report(_incremental_stats()))
        assert "changed   : 3" in text
        assert "unchanged : 145" in text  # 110+12+14+9

    def test_warnings_listed(self):
        s = _incremental_stats(); s["warnings"] = ["base v9 is not an ancestor - close to full"]
        text = "\n".join(build_report(s))
        assert "Warnings:" in text and "not an ancestor" in text

    def test_full_report_notes_no_baseline(self):
        s = _incremental_stats()
        s.update(decision="full", classification=None,
                 functions={"total": 113, "regenerated": 113, "reused": 0})
        text = "\n".join(build_report(s))
        assert "full" in text and "full generation" in text
        assert "reused 0 (0%)" in text
        assert "CHANGE CLASSIFICATION" not in text   # only shown for incremental

    def test_pct_safe_on_zero_total(self):
        s = _incremental_stats(); s["globals"] = {"total": 0, "regenerated": 0, "reused": 0}
        text = "\n".join(build_report(s))   # must not raise ZeroDivisionError
        assert "reused 0 (0%)" in text



class TestEndReportNamesItsInputs:
    def test_doc_type_and_every_dictionary_are_listed(self):
        st = dict(_incremental_stats(), docType="all", dataDictId=None,
                  dataDictionaries={"Layer1": "dd1.csv", "Layer2": "dd2.csv"})
        text = "\n".join(build_report(st))
        assert "SWE.3 Software Detailed Design, SWE.4 Software Unit Test Specification" in text
        assert "Layer1 <- dd1.csv" in text and "Layer2 <- dd2.csv" in text
        assert "project-wide: none" in text
        assert "Data dict       : None" not in text


def _summary(**over):
    s = {"projectId": "project1", "versionId": "project1.v1", "versionName": "v1",
         "branch": "main", "commit": "15bcf6d3a2c0c022", "scope": "group:Layer1.My Sample",
         "docType": "swe3", "viewsOn": ["interfaceTables", "flowcharts"],
         "viewsOff": ["behaviourDiagram"],
         "dataDictionaries": [("Layer1", "dd1.csv", "Core1", True), ("Layer2", None, None, False)],
         "projectDataDict": None, "macros": [("Layer1", "m1.json", "Core1", True)],
         "llm": "OFF (--no-llm)", "baseline": "none - full generation", "config": "cfg.json",
         "warnings": [], "errors": []}
    s.update(over)
    return "\n".join(build_run_summary(s))


class TestRunSummary:
    """Printed before the parse, so a wrong input is seen while stopping is still cheap."""

    def test_the_title_carries_the_name_and_the_id(self):
        assert "GENERATE  project1 / v1   (id project1.v1)" in _summary()

    def test_scope_documents_and_views(self):
        text = _summary()
        assert "Scope           : group:Layer1.My Sample" in text
        assert "SWE.3 Software Detailed Design   (--doc-type swe3)" in text
        assert "interfaceTables, flowcharts" in text and "behaviourDiagram" in text

    def test_every_layer_says_where_its_dictionary_comes_from_or_none(self):
        text = _summary()
        assert "Layer1 <- dd1.csv  (Core1)" in text
        assert "Layer2: none" in text
        assert "project-wide: none   (--data-dict)" in text

    def test_a_missing_file_is_flagged_on_its_line(self):
        text = _summary(dataDictionaries=[("Layer1", "gone.csv", "Core1", False)],
                        projectDataDict=("dd7", "/w/dd7.csv", False))
        assert "Layer1 <- gone.csv  (Core1)  NOT FOUND" in text
        assert "project-wide: dd7 <- /w/dd7.csv  NOT FOUND" in text

    def test_warnings_and_stop_reasons_get_their_own_sections(self):
        clean = _summary()
        assert "WARNINGS" not in clean and "STOPPING" not in clean
        text = _summary(warnings=["cores.Core1.datadictionary ..."], errors=["Layer1: gone"])
        assert "WARNINGS\n    - cores.Core1.datadictionary ..." in text
        assert "STOPPING BEFORE THE PARSE - fix these first:\n    - Layer1: gone" in text

    def test_all_names_both_documents(self):
        text = _summary(docType="all")
        assert "SWE.4 Software Unit Test Specification" in text


class TestEmitRunSummary:
    """The wiring: resolved config in, the right lines out, and what must stop the run."""

    def _run(self, monkeypatch, tmp_path, cfg, **kw):
        lines = []
        monkeypatch.setattr(R, "_version_name", lambda vid: "v1")      # no database here
        monkeypatch.setattr(R, "emit_report", lambda ls, **_: lines.extend(ls))
        args = dict(project_id="project1", version_id="project1.v1", branch="main",
                    commit="15bcf6d3a2", scope={"type": "group", "names": ["Layer1.My Sample"]},
                    doc_type="swe3", cfg=cfg, no_llm=True, data_dict_id=None,
                    data_dict_path=None, baseline="none - full generation",
                    config_path="cfg.json", project_root=str(tmp_path))
        args.update(kw)
        return R.emit_run_summary(**args), "\n".join(lines)

    def test_a_missing_dictionary_stops_the_run_and_says_why(self, monkeypatch, tmp_path):
        cfg = {"cores": {"Core1": {"dataDictionary": "gone.csv"}},
               "layers": {"Layer1": {"cores": ["Core1"]}}}
        stop, text = self._run(monkeypatch, tmp_path, cfg)
        assert stop == ["Layer1: dataDictionary file not found: gone.csv "
                        "(from cores.Core1.dataDictionary)"]
        assert "STOPPING BEFORE THE PARSE" in text

    def test_a_misspelled_key_warns_but_does_not_stop(self, monkeypatch, tmp_path):
        cfg = {"cores": {"Core1": {"datadictionary": "dd.csv"}},
               "layers": {"Layer1": {"cores": ["Core1"]}}}
        stop, text = self._run(monkeypatch, tmp_path, cfg)
        assert stop == []
        assert "Layer1: none" in text and "did you mean 'dataDictionary'" in text

    def test_views_follow_the_pipeline_rule(self, monkeypatch, tmp_path):
        """No key: off, except interfaceTables and unitHeaders. Any value but False: on."""
        cfg = {"layers": {}, "views": {"flowcharts": False, "unitDiagrams": True,
                                       "utExport": {"review": {}}}}
        _, text = self._run(monkeypatch, tmp_path, cfg)
        on = next(l for l in text.splitlines() if "Views on" in l)
        off = next(l for l in text.splitlines() if "Views off" in l)
        assert "interfaceTables" in on and "unitHeaders" in on and "utExport" in text
        assert "flowcharts" in off

    def test_a_project_wide_id_with_no_file_warns(self, monkeypatch, tmp_path):
        _, text = self._run(monkeypatch, tmp_path, {"layers": {}}, data_dict_id="dd7",
                            data_dict_path=str(tmp_path / "dd7.csv"))
        assert "--data-dict dd7: no file at" in text and "WITHOUT" in text


class TestSummaryViewsMatchThePipeline:
    """config_views copies run_views' rule so the orchestrator need not import every view.
    This holds the copy to the original: the summary must name exactly what will run."""

    @pytest.mark.parametrize("views", [
        {},
        {"flowcharts": True},
        {"flowcharts": False, "unitHeaders": False},
        {"interfaceTables": False, "utExport": {"review": {}}, "behaviourDiagram": True},
    ])
    def test_the_summary_says_what_run_views_runs(self, monkeypatch, views):
        import views as V
        ran = []
        for name in list(V.VIEW_REGISTRY):
            monkeypatch.setitem(V.VIEW_REGISTRY, name, lambda *a, _n=name: ran.append(_n))
        V.run_views({}, "out", "model", {"views": views})
        on, _ = R.config_views({"views": views})
        assert set(ran) == set(on) & set(V.VIEW_REGISTRY)
