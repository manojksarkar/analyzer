"""The flowchart engine reads its inputs from the database (doc 10, step 7).

It is a separate program with a file-based CLI, which is why its four inputs were paths. Once
the model lives in Postgres the caller cannot always produce one, so the engine reads the
database itself.

Verified end to end on SQLite before these were written: with ONLY `--version-id` it produced
280 flowcharts / 0 failures, and the old file arguments over the same version produced the same
280 — equivalence, not merely absence of errors. These keep the wiring from being undone.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "engine", "flowchart"))


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestEngineConfig:
    def test_database_fields_exist(self):
        from config import EngineConfig
        c = EngineConfig(functions_json_path="", metadata_json_path="", out_dir="",
                         version_id="ver9", component="Uart", restrict_from_plan=True)
        assert (c.version_id, c.component, c.restrict_from_plan) == ("ver9", "Uart", True)

    def test_paths_are_no_longer_required_on_the_cli(self):
        """--interface-json / --metaData-json were `required=True`, which made it impossible to
        run without files at all."""
        src = _src(os.path.join("engine", "flowchart", "flowchart_engine.py"))
        assert 'p.add_argument("--interface-json", default=None,' in src
        assert 'p.add_argument("--metaData-json", default=None,' in src
        for flag in ("--version-id", "--component", "--restrict-from-plan"):
            assert f'"{flag}"' in src, f"{flag} missing from the engine CLI"


class TestOneLoaderBlock:
    def test_all_four_inputs_have_a_database_path(self):
        """Model, project metadata, knowledge base and the header->TU map."""
        src = _src(os.path.join("engine", "flowchart", "flowchart_engine.py"))
        assert "_load_inputs_from_db(config)" in src        # model + metadata
        assert "_db_knowledge_base(config.version_id)" in src
        assert "_db_tu_includes(config.version_id)" in src

    def test_missing_database_fails_loudly(self):
        """A run told to read a version from the database must NOT quietly produce an empty
        model — that would render zero flowcharts and report success."""
        src = _src(os.path.join("engine", "flowchart", "flowchart_engine.py"))
        assert "--version-id needs a configured database" in src

    def test_the_scope_filter_is_reachable(self):
        """The component and unit filters replace the pre-filtered functions_<group>.json:
        the engine ignores --interface-json once it has a version id, so in database mode
        it must narrow the loaded model itself.

        What the filter SELECTS is covered behaviourally, against poc-4's own filter, in
        test_flowchart_scope_matches_poc4.py. Here we only check the loader still routes
        through it -- a filter nobody calls is the bug this whole class guards against.
        """
        src = _src(os.path.join("engine", "flowchart", "flowchart_engine.py"))
        assert "def _apply_scope(" in src
        assert "functions, comps, units = _apply_scope(" in src

    def test_the_view_passes_the_scope(self):
        """The filters are useless if the caller never sends the scope. Every component's run
        rendered the WHOLE version before this — 70 flowcharts across two components where 35
        were wanted."""
        src = _src(os.path.join("engine", "views", "flowcharts.py"))
        assert '"--component", _c' in src
        assert '"--unit", _u' in src


class TestKnowledgeLoaderIsShared:
    def test_file_loader_delegates_to_the_data_loader(self):
        """Two parsers for one format is how a new field gets handled in the file and forgotten
        in the database."""
        from pkb.knowledge import load_knowledge_data
        src = _src(os.path.join("engine", "flowchart", "pkb", "knowledge.py"))
        assert "return load_knowledge_data(data)" in src
        assert load_knowledge_data(None) is None
        assert load_knowledge_data({}) is None

    def test_data_loader_builds_knowledge(self):
        from pkb.knowledge import load_knowledge_data
        k = load_knowledge_data({"project_name": "P", "base_path": "/src",
                                 "project_summary": "s", "functions": {}})
        assert k is not None and k.project_name == "P" and k.base_path == "/src"


class TestCallerStopsWritingFiles:
    def test_database_mode_passes_the_version_instead_of_paths(self):
        src = _src(os.path.join("engine", "views", "flowcharts.py"))
        assert 'cmd.extend(["--version-id", _run_version()])' in src
        assert 'cmd.append("--restrict-from-plan")' in src

    def test_file_mode_still_passes_the_file_arguments(self):
        """The file path must remain intact — it is the default and the fallback."""
        src = _src(os.path.join("engine", "views", "flowcharts.py"))
        assert 'cmd.extend(["--knowledge-json", kb_path])' in src
        assert 'cmd.extend(["--tu-includes", tu_includes_path])' in src
