"""The SWE.4 page says what the SWE.4 DOCX says.

`api/services/swe4_render.py` builds the web page of a Unit Test Specification from the same
test_specs.json `engine/swe4_exporter.py` turns into the DOCX. These tests export a DOCX from a
small spec file with the engine's own exporter and hold the page to it: the same headings in the
same order, and every Table A / Table B cell with the same text.
"""
import datetime
import json
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

from api.services import swe4_render  # noqa: E402


def _fn(name, line, *, steps, returns=(), mocks=(), params=(), globals_=(), rt="int", desc=None,
        qualified=None, cross=()):
    return {
        "name": name, "qualifiedName": qualified or name, "testCaseId": f"TC_{name.upper()}",
        "generationMethod": "Analysis of Requirements", "returnType": rt,
        "location": {"file": "L/U.cpp", "line": line},
        **({"description": desc} if desc else {}),
        "precondition": {"mockFunctions": list(mocks),
                         "parameters": [{"text": p} for p in params],
                         "globals": [{"text": g} for g in globals_]},
        "input": {"entries": [{"text": p + "[-0x80000000-0x7FFFFFFF]"} for p in params]},
        "expected": {"mockFunctions": list(mocks), "crossUnitCalls": list(cross),
                     "returns": list(returns), "outParameters": [], "globals": []},
        "testSteps": [{"number": n, "text": t} for n, t in steps],
    }


SPECS = {
    "unitNames": {"Layer1.Signal|Signal": "Signal", "Layer1.Signal|Driver": "Driver"},
    "Layer1.Signal|Signal": {"name": "Signal", "functions": [
        _fn("normalize", 20, params=["int sample"], qualified="Proc::normalize",
            desc="Clamps a sample.",
            steps=[("1", "Issue function normalize with inputs sample."),
                   ("2", "Check whether sample < 0."), ("2.a", "True: Return 0."),
                   ("2.b", "False: Return sample.")],
            returns=[{"step": "2.a", "text": "Successfully returned 0"},
                     {"steps": ["2.b"], "text": "Successfully returned sample"}]),
        _fn("reset", 10, rt="void", steps=[("1", "Issue function reset with input VOID.")]),
        _fn("broken", 30, rt="int", steps=[]),
    ]},
    "Layer1.Signal|Driver": {"name": "Driver", "functions": [
        _fn("acquire", 5, params=["int raw"], mocks=["normalize()"], globals_=["int g_level"],
            steps=[("1", "Issue function acquire with inputs raw."), ("2", "Return normalize().")],
            returns=[{"step": "2", "text": "Successfully returned normalize()"}]),
    ]},
    "dynamicSpecs": {"Layer1.Signal": [
        dict(_fn("acquire", 5, params=["int raw"], steps=[("1", "Issue acquire."),
                                                          ("2", "Driver calls Signal.normalize.")],
                 cross=[{"text": "Signal.Proc::normalize", "step": "2"}]),
             unitName="Driver", entryPoint="Hub - hubCompute"),
    ]},
}


@pytest.fixture
def exported(tmp_path, monkeypatch):
    """The DOCX the engine writes for SPECS, read back as (headings, tables)."""
    docx = pytest.importorskip("docx")
    import swe4_exporter
    monkeypatch.setattr(swe4_exporter, "load_model_json", lambda name: {})
    js = tmp_path / "test_specs.json"
    js.write_text(json.dumps(SPECS), encoding="utf-8")
    out = tmp_path / "swe4.docx"
    ok, _ = swe4_exporter.export_test_specs(str(js), str(out), selected_components=["Layer1.Signal"])
    assert ok
    d = docx.Document(str(out))
    heads = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    tables = [[[c.text for c in r.cells] for r in t.rows] for t in d.tables]
    return heads, tables


@pytest.fixture
def page(tmp_path, monkeypatch):
    group_dir = tmp_path / "Layer1.Signal"
    group_dir.mkdir()
    (group_dir / "test_specs.json").write_text(json.dumps(SPECS), encoding="utf-8")
    from api.services import doc_render
    import swe4_exporter
    from core.config import app_config
    # The page reads the config its version ran with; give it the one the exporter used.
    monkeypatch.setattr(swe4_render, "render_config", lambda version: app_config())
    monkeypatch.setattr(swe4_render, "_load_abbreviations",
                        lambda cfg: swe4_exporter.load_abbreviations(swe4_exporter.PROJECT_ROOT, cfg))
    now = datetime.datetime.now(datetime.timezone.utc)
    doc = SimpleNamespace(group="Layer1.Signal", layer="Layer1", process="SWE.4", version_id="v",
                          updated_at=now)
    project = SimpleNamespace(name="Software Project", compliance_standard="ASPICE")
    return swe4_render.build_swe4_render(doc, project, None, group_dir)


def _flat(sections):
    for s in sections:
        yield s
        yield from _flat(s["children"])


class TestTheHeadings:
    def test_the_page_has_the_docx_headings_in_order(self, exported, page):
        heads, _ = exported
        mine = [f"{t['number']} {t['title']}" for t in page["toc"]]
        assert mine == heads

    def test_a_unit_and_its_functions_are_numbered_as_the_docx(self, page):
        titles = [f"{t['number']} {t['title']}" for t in page["toc"]]
        # Units by name (Driver before Signal), functions by source line (reset at 10 first).
        assert titles.index("2.1.1 Driver") < titles.index("2.1.2 Signal")
        assert "2.1.2.1 Signal-reset" in titles and "2.1.2.2 Signal-Proc::normalize" in titles
        assert "2.1.3.1 Driver - acquire (Hub - hubCompute)" in titles


class TestTheTables:
    def test_every_cell_is_the_docx_text(self, exported, page):
        _, tables = exported
        # The DOCX: Terms (maybe), then per spec Table A (header row + data row) and Table B.
        spec_tables = [t for t in tables if t and t[0][0] == "Eval. Equipment Name"]
        b_tables = [t for t in tables if t and t[0][0] == "Test Case ID"]
        specs = [s for s in _flat(page["sections"]) if s["type"] == "test_spec"]
        assert len(specs) == len(spec_tables) == len(b_tables) == 5
        for s, a, b in zip(specs, spec_tables, b_tables):
            rows = dict(s["table"]["rows"])
            assert [rows[h] for h in a[0]] == a[1]
            assert [rows[k] for k, _ in b] == [v for _, v in b]


class TestTheStructuredSpec:
    def test_steps_nest_and_results_name_their_step(self, page):
        spec = next(s for s in _flat(page["sections"]) if s["title"] == "Signal-Proc::normalize")
        ts = spec["test_spec"]
        assert [st["number"] for st in ts["steps"]] == ["1", "2", "2.a", "2.b"]
        assert ts["expected"] == [{"text": "Successfully returned 0", "steps": ["2.a"]},
                                  {"text": "Successfully returned sample", "steps": ["2.b"]}]
        assert spec["content"] == "Clamps a sample."

    def test_nothing_to_assert_says_why(self, page):
        by_title = {s["title"]: s["test_spec"] for s in _flat(page["sections"]) if s["type"] == "test_spec"}
        assert by_title["Signal-reset"]["expected_note"] == "No return value; no global side effects"
        assert "no control-flow graph" in by_title["Signal-broken"]["expected_note"]
        assert by_title["Signal-broken"]["steps"] == []

    def test_the_summary_counts_the_document(self, page):
        s = page["test_summary"]
        assert (s["units"], s["function_specs"], s["dynamic_specs"], s["mocks"]) == (2, 4, 1, 1)

    def test_the_chapters_carry_the_review_section_keys(self, page):
        assert [s["id"] for s in page["sections"]][:3] == ["intro", "test_spec", "metrics"]


def test_no_output_still_renders_the_chapters(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    doc = SimpleNamespace(group="Layer1.Gone", layer="Layer1", process="SWE.4", version_id="v",
                          updated_at=now)
    project = SimpleNamespace(name="P", compliance_standard="ASPICE")
    r = swe4_render.build_swe4_render(doc, project, None, None)
    assert [s["id"] for s in r["sections"]] == ["intro", "test_spec", "metrics", "appendix-a"]
    assert r["test_summary"]["function_specs"] == 0
