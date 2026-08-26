"""E2E conftest — pipeline output fixtures and snapshot helpers."""
import json
import os
import sys

import pytest

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tests.e2e_paths import (                             # noqa: E402
    PROJECT_ROOT, OUTPUT_DIR, COMPONENTS, output_for,
)
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "snapshots")


def _load_cfg():
    """Load config.defaults.json via the project's own utility (strips comments/trailing commas)."""
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
    from utils import load_config
    return load_config(os.path.join(PROJECT_ROOT, "engine"))


@pytest.fixture(scope="session")
def llm_behaviour_names_off():
    """Skip the requesting test when llm.behaviourNames is enabled.

    Static-heuristic assertions are not valid when the LLM overwrites the values.
    """
    if _load_cfg().get("llm", {}).get("behaviourNames", False):
        pytest.skip("llm.behaviourNames is on — static heuristic assertions not valid")


@pytest.fixture(scope="session")
def llm_descriptions_off():
    """Skip the requesting test when llm.descriptions is enabled.

    Tests asserting the description field is absent/empty are not valid when LLM adds it.
    """
    if _load_cfg().get("llm", {}).get("descriptions", False):
        pytest.skip("llm.descriptions is on — description field assertions not valid")


@pytest.fixture(scope="session")
def behaviour_diagram_on():
    """Skip the requesting test when the behaviourDiagram view is disabled.

    The DOCX Dynamic Behaviour section (sub-headings + description tables) is
    generated only when views.behaviourDiagram is on; with it off the section
    is empty and behaviour-content assertions are not valid.
    """
    if not _load_cfg().get("views", {}).get("behaviourDiagram", False):
        pytest.skip("views.behaviourDiagram is off — Dynamic Behaviour section is empty")


@pytest.fixture(scope="session")
def llm_summarize_off():
    """Skip the requesting test when llm.summarize is enabled.

    Snapshots generated with LLM off will not match LLM-enriched output.
    """
    if _load_cfg().get("llm", {}).get("summarize", False):
        pytest.skip("llm.summarize is on — snapshot content may differ")


@pytest.fixture(scope="session")
def update_snapshots(request):
    return request.config.getoption("--update-snapshots")


@pytest.fixture(scope="session")
def interface_tables(run_pipeline):
    """Every component's interface tables, merged into the one dict tests expect.

    A group-scoped run writes output/<Component>/interface_tables.json once per
    component; the keys inside are already component-qualified ("Lib|Lib"), so the
    merge cannot collide and the result is what the single group-level file used
    to hold.
    """
    merged = {}
    for c in COMPONENTS:
        path = os.path.join(output_for(c), "interface_tables.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                part = json.load(f) or {}
            # "unitNames" is a map keyed by unit, present in EVERY file -- a plain
            # update() would keep only the last component's names.
            merged.setdefault("unitNames", {}).update(part.pop("unitNames", None) or {})
            merged.update(part)
    if not merged:
        raise AssertionError("no interface_tables.json under " + OUTPUT_DIR)
    return merged


@pytest.fixture(scope="session")
def core_entries(interface_tables):
    return interface_tables.get("Sample-Core|Core", {}).get("entries", [])


@pytest.fixture(scope="session")
def lib_entries(interface_tables):
    return interface_tables.get("Lib|Lib", {}).get("entries", [])


@pytest.fixture(scope="session")
def util_entries(interface_tables):
    return interface_tables.get("Util|Util", {}).get("entries", [])


@pytest.fixture(scope="session")
def all_entries(core_entries, lib_entries, util_entries):
    return core_entries + lib_entries + util_entries


@pytest.fixture
def assert_snapshot(update_snapshots):
    """Compare actual dict/list against a committed golden JSON file.

    Run with --update-snapshots to regenerate golden files.
    After updating, review with: git diff tests/snapshots/
    """
    def _assert(actual, snapshot_rel_path):
        full_path = os.path.normpath(os.path.join(SNAPSHOTS_DIR, snapshot_rel_path))
        if update_snapshots:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                json.dump(actual, f, indent=2, sort_keys=True)
            pytest.skip(f"Snapshot updated: {snapshot_rel_path}")
            return
        if not os.path.isfile(full_path):
            pytest.fail(
                f"Snapshot missing: {snapshot_rel_path}\n"
                f"Run with --update-snapshots to generate it."
            )
        with open(full_path, encoding="utf-8") as f:
            expected = json.load(f)
        assert actual == expected, _diff_summary(actual, expected, snapshot_rel_path)

    return _assert


def _diff_summary(actual, expected, path):
    if isinstance(expected, dict) and isinstance(actual, dict):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(expected) & set(actual) if expected[k] != actual[k])
        lines = [f"Snapshot mismatch: {path}"]
        if missing:
            lines.append(f"  Keys removed: {missing}")
        if extra:
            lines.append(f"  Keys added:   {extra}")
        if changed:
            lines.append(f"  Keys changed ({len(changed)}): {changed[:10]}")
        return "\n".join(lines)
    return f"Snapshot mismatch: {path}"
