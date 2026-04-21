"""Unit tests for src/core/model_io.py — path helpers, read, write, load."""
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from core.model_io import (
    ALL_MODEL_NAMES, FUNCTIONS, DATA_DICTIONARY, ModelFileMissing,
    model_file_path, model_files_present, read_model_file, load_model, write_model_file,
)


def _fake_paths(tmp_path):
    model_dir = str(tmp_path / "model")
    os.makedirs(model_dir, exist_ok=True)
    return SimpleNamespace(model_dir=model_dir)


def _write(tmp_path, name, data):
    path = str(tmp_path / "model" / f"{name}.json")
    (tmp_path / "model").mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class TestPathHelpers:
    def test_model_file_path_has_json_extension_under_model_dir(self, tmp_path):
        fake = _fake_paths(tmp_path)
        with patch("core.model_io.paths", return_value=fake):
            p = model_file_path(FUNCTIONS)
        assert p.startswith(fake.model_dir) and p.endswith(".json")

    def test_model_files_present_returns_missing_names(self, tmp_path):
        _write(tmp_path, FUNCTIONS, {})
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            missing = model_files_present(FUNCTIONS, DATA_DICTIONARY)
        assert FUNCTIONS not in missing and DATA_DICTIONARY in missing


class TestReadModelFile:
    def test_reads_json(self, tmp_path):
        _write(tmp_path, FUNCTIONS, {"f1": "v"})
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            assert read_model_file(FUNCTIONS)["f1"] == "v"

    def test_missing_required_raises_model_file_missing(self, tmp_path):
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            with pytest.raises(ModelFileMissing):
                read_model_file(FUNCTIONS)

    def test_missing_optional_returns_custom_default(self, tmp_path):
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            assert read_model_file(FUNCTIONS, required=False, default={}) == {}

    def test_model_file_missing_is_file_not_found_error(self):
        assert issubclass(ModelFileMissing, FileNotFoundError)


class TestLoadModel:
    def test_required_and_optional_together(self, tmp_path):
        _write(tmp_path, FUNCTIONS, {"f": 1})
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            r = load_model(FUNCTIONS, optional=[DATA_DICTIONARY])
        assert r[FUNCTIONS] == {"f": 1}
        assert r[DATA_DICTIONARY] == {}

    def test_missing_required_raises(self, tmp_path):
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            with pytest.raises(ModelFileMissing):
                load_model(FUNCTIONS)


class TestWriteModelFile:
    def test_in_place_round_trip(self, tmp_path):
        data = {"key": 42}
        with patch("core.model_io.paths", return_value=_fake_paths(tmp_path)):
            write_model_file(FUNCTIONS, data)
            assert read_model_file(FUNCTIONS) == data

    def test_atomic_round_trip_leaves_no_tmp(self, tmp_path):
        fake = _fake_paths(tmp_path)
        with patch("core.model_io.paths", return_value=fake):
            write_model_file(FUNCTIONS, {"a": 1}, atomic=True)
            assert read_model_file(FUNCTIONS) == {"a": 1}
        assert not any(f.endswith(".tmp") for f in os.listdir(fake.model_dir))
