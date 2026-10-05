"""The SWE.3 document in the web app reads like the DOCX of the same version.

A page-vs-DOCX comparison of a real run (2026-09-29) found the web app's render
(api/services/doc_render.py) saying something else in six places. Each test pins the DOCX's
rule (engine/docx_exporter.py) the render now follows:

  * the Introduction came from `engine/config/config.json`, which no longer exists, so
    Purpose / Scope were placeholders - it now comes from the config the version ran with;
  * the component was headed `Layer1.Lib` where the DOCX says `Lib`;
  * a parameter was its type alone (`int; int`) where the DOCX says `int a; int b`;
  * the unit's description was guessed from its functions', where the DOCX shows its own
    (an LLM summary with AI on) - the exporter now writes it to unit_descriptions.json;
  * the appendix read "Appendix A Appendix A. Design Guideline";
  * a unit with no interface said "NA" where the DOCX prints the empty table, and a
    flowchart's Requirements line said "-" where the DOCX names the function.
"""
import datetime
import json
from types import SimpleNamespace

import pytest

from api.services import doc_render as dr

pytestmark = pytest.mark.unit

UNIT = "Layer1.Lib|Lib"
EMPTY_UNIT = "Layer1.Lib|Empty"
ENTRY = {"interfaceId": "IF_1", "interfaceName": "libAdd", "name": "libAdd", "type": "Function",
         "description": "", "parameters": [{"type": "int", "name": "a", "range": "R"},
                                           {"type": "int", "name": "", "range": "R"}],
         "returnType": "int", "returnRange": "R", "direction": "Out", "sourceDest": "Core/Core"}


def _render(tmp_path, *, version_config=None, unit_descriptions=None, flowchart=False):
    group = tmp_path / "Layer1.Lib"
    group.mkdir()
    (group / "interface_tables.json").write_text(json.dumps({
        "unitNames": {UNIT: "Lib", EMPTY_UNIT: "Empty"},
        UNIT: {"entries": [dict(ENTRY, description="Adds two numbers.") if unit_descriptions is None
                           else ENTRY]},
        EMPTY_UNIT: {"entries": []}}), encoding="utf-8")
    if unit_descriptions is not None:
        (group / "unit_descriptions.json").write_text(json.dumps(unit_descriptions), encoding="utf-8")
    if flowchart:
        (group / "flowcharts").mkdir()
        (group / "flowcharts" / "Layer1.Lib_Lib.json").write_text(
            json.dumps([{"name": "libAdd", "flowchart": "flowchart TD\n A-->B"}]), encoding="utf-8")
    now = datetime.datetime(2026, 9, 29, tzinfo=datetime.timezone.utc)
    doc = SimpleNamespace(id="d1", group="Layer1.Lib", layer="Layer1", subtitle=None, process="SWE.3",
                          updated_at=now, version_id="v1")
    project = SimpleNamespace(name="Brake ECU", compliance_standard="ISO_26262")
    version = SimpleNamespace(id="v1", tag="v1.0.0", resolved_config=version_config)
    out = dr.build_render(doc, project, version, group, "p1",
                          model_reader=SimpleNamespace(load=lambda name: {}), output_reader=None)
    return out


def _find(sections, pred):
    for s in sections:
        if pred(s):
            return s
        hit = _find(s.get("children") or [], pred)
        if hit:
            return hit
    return None


class TestTheIntroduction:
    def test_comes_from_the_config_the_version_ran_with(self, tmp_path):
        cfg = {"docx": {"introduction": {"purpose": "SDD for {project_name}.",
                                         "scopeIntro": "Covers {project_name}:"}}}
        intro = _render(tmp_path, version_config=cfg)["sections"][0]
        purpose, scope = intro["children"][0], intro["children"][1]
        assert purpose["content"] == "SDD for Brake ECU."
        assert scope["content"].startswith("Covers Brake ECU:\n• Lib")

    def test_without_one_the_engines_defaults_are_read_not_a_missing_file(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "repo" / "engine" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.defaults.json").write_text(
            '{"docx": {"introduction": {"purpose": "From the defaults."}}}', encoding="utf-8")
        monkeypatch.setattr(dr, "_REPO_ROOT", tmp_path / "repo")
        assert dr.render_config(SimpleNamespace(resolved_config=None))["docx"]["introduction"][
            "purpose"] == "From the defaults."

    def test_a_relative_abbreviations_file_is_found_where_the_engine_looks(self, tmp_path, monkeypatch):
        # The engine reads it from its project root, the repository root (core/paths.py) - so a
        # file under engine/ is not found by the DOCX, and must not be by the page either.
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "abbr.txt").write_text("ECU: Engine Control Unit\n", encoding="utf-8")
        (tmp_path / "engine" / "config").mkdir(parents=True)
        (tmp_path / "engine" / "config" / "only.txt").write_text("X: y\n", encoding="utf-8")
        monkeypatch.setattr(dr, "_REPO_ROOT", tmp_path)
        assert dr._load_abbreviations({"llm": {"abbreviationsPath": "config/abbr.txt"}}) == {
            "ECU": "Engine Control Unit"}
        assert dr._load_abbreviations({"llm": {"abbreviationsPath": "config/only.txt"}}) == {}


class TestTheComponent:
    def test_is_headed_by_its_own_name_not_its_layer(self, tmp_path):
        r = _render(tmp_path)
        comp = r["sections"][1]
        assert comp["title"] == "Lib"
        table = _find(r["sections"], lambda s: s.get("title") == "Component/Unit Table")["table"]
        assert [row[0] for row in table["rows"]] == ["Lib", "Lib"]

    def test_a_unit_says_what_the_docx_says_of_it(self, tmp_path):
        r = _render(tmp_path, unit_descriptions={UNIT: "Arithmetic helpers.", EMPTY_UNIT: "N/A"})
        table = _find(r["sections"], lambda s: s.get("title") == "Component/Unit Table")["table"]
        assert table["rows"][1][2] == "Arithmetic helpers."        # rows sorted: Empty, Lib

    def test_without_the_exporters_file_its_functions_describe_it_as_the_docx_falls_back(self, tmp_path):
        r = _render(tmp_path)
        table = _find(r["sections"], lambda s: s.get("title") == "Component/Unit Table")["table"]
        assert table["rows"][1][2] == "Adds two numbers."


class TestTheUnitInterface:
    def test_a_parameter_is_its_type_and_name(self, tmp_path):
        r = _render(tmp_path)
        iface = _find(r["sections"], lambda s: s.get("id") == f"{UNIT}-iface")["table"]
        assert iface["rows"][0][3] == "int a; int\nreturn: int"

    def test_a_unit_with_none_shows_the_empty_table(self, tmp_path):
        r = _render(tmp_path)
        iface = _find(r["sections"], lambda s: s.get("id") == f"{EMPTY_UNIT}-iface")
        assert iface["type"] == "table" and iface["table"]["rows"] == []
        assert iface["table"]["headers"][0] == "Interface ID"


def test_a_flowcharts_requirements_line_names_the_function_when_it_has_no_description(tmp_path):
    r = _render(tmp_path, unit_descriptions={}, flowchart=True)
    fc = _find(r["sections"], lambda s: s.get("type") == "flowchart_table")
    assert fc["flowchart_table"]["description"] == "libAdd"


def test_the_appendix_reads_as_the_docx_heading(tmp_path):
    appendix = _render(tmp_path)["sections"][-1]
    assert f"{appendix['number']} {appendix['title']}" == "Appendix A. Design Guideline"


class TestTheCounts:
    def test_globals_are_counted_as_the_view_writes_them(self, tmp_path):
        """The interface-tables view types a global "Global Variable" (views/interface_tables.py);
        the page's count looked only for other spellings, so every document said "0 Globals"."""
        group = tmp_path / "Layer1.Lib"
        group.mkdir()
        glob = {"interfaceId": "IF_2", "globalId": "g1", "type": "Global Variable",
                "interfaceName": "g_count", "name": "g_count", "qualifiedName": "g_count",
                "unitKey": UNIT, "unitName": "Lib", "location": {}, "variableType": "int",
                "range": "R", "direction": "In/Out", "reason": "", "sourceDest": "Core/Core",
                "callerUnits": [], "calleesUnits": []}
        (group / "interface_tables.json").write_text(json.dumps({
            "unitNames": {UNIT: "Lib"}, UNIT: {"entries": [ENTRY, glob]}}), encoding="utf-8")
        now = datetime.datetime(2026, 10, 4, tzinfo=datetime.timezone.utc)
        doc = SimpleNamespace(id="d1", group="Layer1.Lib", layer="Layer1", subtitle=None,
                              process="SWE.3", updated_at=now, version_id="v1")
        project = SimpleNamespace(name="Brake ECU", compliance_standard="ISO_26262")
        version = SimpleNamespace(id="v1", tag="v1.0.0", resolved_config=None)
        meta = dr.build_render(doc, project, version, group, "p1",
                               model_reader=SimpleNamespace(load=lambda name: {}),
                               output_reader=None)["meta"]
        assert (meta["functions_total"], meta["globals_total"]) == (1, 1)
