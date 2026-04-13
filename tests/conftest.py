"""Shared fixtures for the analyzer test suite.

Strategy: run the full pipeline once per session against the Sample group,
then all test functions read from output/ and assert. No isolation needed
because the pipeline is deterministic and tests are read-only after the run.
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
SAMPLE_PROJECT = os.path.join(PROJECT_ROOT, "SampleCppProject")

# Stores pipeline failure message if it failed; None means success or skipped.
_pipeline_failure = None


def pytest_addoption(parser):
    grp = parser.getgroup(
        "analyzer",
        "Analyzer suite  |  examples: pytest --skip-pipeline · pytest -P · pytest --update-snapshots",
    )
    grp.addoption(
        "--skip-pipeline",
        action="store_true",
        default=False,
        help="Skip running the pipeline and test against existing output/.",
    )
    grp.addoption(
        "-P", "--show-pipeline-output",
        action="store_true",
        default=False,
        help="Print captured pipeline stdout/stderr after the run (always shown on failure).",
    )
    grp.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate golden snapshot files instead of comparing against them.",
    )


@pytest.fixture(scope="session")
def update_snapshots(request):
    return request.config.getoption("--update-snapshots")


def pytest_collection_finish(session):
    """Run the pipeline after collection, before any test executes."""
    global _pipeline_failure

    out = sys.__stdout__
    sep = "-" * 60
    if session.config.getoption("--skip-pipeline", default=False):
        out.write(f"\n{sep}\n  Pipeline: SKIPPED (using existing output/)\n{sep}\n\n")
        out.flush()
        return

    project_name = os.path.basename(SAMPLE_PROJECT)
    group = "Sample"
    label = f"{project_name} [{group}]"

    show_output = session.config.getoption("--show-pipeline-output", default=False)

    out.write(f"\n{sep}\n")
    out.flush()

    start = time.monotonic()

    if show_output:
        out.write(f"  Pipeline: {label}\n\n")
        out.flush()
        result = subprocess.run(
            [sys.executable, "run.py", SAMPLE_PROJECT, "--clean", "--selected-group", group, "--no-llm-summarize"],
            cwd=PROJECT_ROOT,
        )
    else:
        done_event = threading.Event()

        def _progress():
            while not done_event.wait(1):
                elapsed = int(time.monotonic() - start)
                out.write(f"\r  Pipeline: {label} ... {elapsed}s  ")
                out.flush()

        t = threading.Thread(target=_progress, daemon=True)
        t.start()

        result = subprocess.run(
            [sys.executable, "run.py", SAMPLE_PROJECT, "--clean", "--selected-group", group, "--no-llm-summarize"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        done_event.set()

    elapsed = int(time.monotonic() - start)

    if result.returncode != 0:
        captured = "" if show_output else f"{getattr(result, 'stderr', '')}\n{getattr(result, 'stdout', '')}"
        _pipeline_failure = (
            f"Pipeline failed in {elapsed}s (exit {result.returncode})"
            + (f":\n{captured}" if captured.strip() else " (output streamed above)")
        )
        out.write(f"\n  Pipeline: {label} ... FAILED ({elapsed}s)\n")
    else:
        out.write(f"\n  Pipeline: {label} ... OK ({elapsed}s)\n")

    out.write(f"{sep}\n\n")
    out.flush()


@pytest.fixture(scope="session", autouse=True)
def run_pipeline(request):
    """Fail all tests if the pipeline failed during collection."""
    if _pipeline_failure:
        pytest.fail(_pipeline_failure)


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
        full_path = os.path.join(SNAPSHOTS_DIR, snapshot_rel_path)
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
