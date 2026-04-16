"""E2E conftest — pipeline output fixtures and snapshot helpers."""
import json
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "snapshots")


@pytest.fixture(scope="session")
def update_snapshots(request):
    return request.config.getoption("--update-snapshots")


@pytest.fixture(scope="session")
def interface_tables(run_pipeline):
    path = os.path.join(OUTPUT_DIR, "interface_tables.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def core_entries(interface_tables):
    return interface_tables.get("Core|Core", {}).get("entries", [])


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
