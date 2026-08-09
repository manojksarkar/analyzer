"""Unit tests for build_config.preprocessor_definitions -> a macro file on disk.

Covers _materialize_macros in api.services.pipeline_runner, which closes the gap
where wizard-entered defines never reached Clang at all: the manual list is
written next to the per-project config, an upload resolves to its stored file,
and the result is what _write_project_config points clang.macrosFile at.

Mark: unit (writes only into tmp_path)
"""
import json

import pytest

from api.services.pipeline_runner import _materialize_macros

pytestmark = pytest.mark.unit


class TestManualMode:
    def test_defines_are_written_as_a_json_list(self, tmp_path):
        out = _materialize_macros(
            {"mode": "manual", "defines": ["FEATURE_A=1", "PLATFORM_EMBEDDED", "ENABLE_DIAG"]},
            tmp_path,
        )
        assert out == tmp_path / "macros.json"
        assert json.loads(out.read_text(encoding="utf-8")) == [
            "FEATURE_A=1", "PLATFORM_EMBEDDED", "ENABLE_DIAG"]

    def test_mode_defaults_to_manual(self, tmp_path):
        out = _materialize_macros({"defines": ["A=1"]}, tmp_path)
        assert out and json.loads(out.read_text(encoding="utf-8")) == ["A=1"]

    def test_blank_entries_are_dropped(self, tmp_path):
        out = _materialize_macros({"mode": "manual", "defines": ["A=1", "  ", ""]}, tmp_path)
        assert json.loads(out.read_text(encoding="utf-8")) == ["A=1"]

    def test_no_defines_writes_nothing(self, tmp_path):
        assert _materialize_macros({"mode": "manual", "defines": []}, tmp_path) is None
        assert not (tmp_path / "macros.json").exists()

    @pytest.mark.parametrize("value", [None, "", [], "manual"])
    def test_non_dict_input_is_ignored(self, value, tmp_path):
        assert _materialize_macros(value, tmp_path) is None


class TestUploadMode:
    def test_upload_resolves_to_the_stored_file(self, tmp_path, monkeypatch):
        stored = tmp_path / "fcore_macros.json"
        stored.write_text('{"A": "1"}', encoding="utf-8")
        monkeypatch.setattr(
            "api.routes.repositories.resolve_upload",
            lambda upload_id: stored if upload_id == "up_abc" else None,
        )
        assert _materialize_macros(
            {"mode": "upload", "file_id": "up_abc", "file_name": "fcore_macros.json"},
            tmp_path,
        ) == stored

    def test_unknown_upload_id_yields_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.routes.repositories.resolve_upload", lambda _id: None)
        assert _materialize_macros({"mode": "upload", "file_id": "gone"}, tmp_path) is None


class TestEngineContract:
    def test_the_written_file_is_readable_by_the_engine_reader(self, tmp_path):
        """The wizard's list shape must be one macro_input understands end to end."""
        import os
        import sys

        engine_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "engine",
        )
        sys.path.insert(0, engine_dir)
        from core.macro_input import GLOBAL_SCOPE, load_macro_defs, to_clang_args

        out = _materialize_macros(
            {"mode": "manual", "defines": ["FEATURE_A=1", "ENABLE_DIAG"]}, tmp_path)
        defs, report = load_macro_defs(str(out))
        assert report.kind == "list"
        assert to_clang_args(defs[GLOBAL_SCOPE]) == ["-DFEATURE_A=1", "-DENABLE_DIAG"]
