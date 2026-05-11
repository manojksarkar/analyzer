"""Root conftest — pipeline lifecycle only.

CLI options and the pipeline subprocess are declared here (must be in root).
All other fixtures (snapshots, JSON loaders) live in integration/conftest.py.
"""
import os
import subprocess
import sys
import threading
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def pytest_collection_finish(session):
    """Run the pipeline after collection, before any test executes.

    Skipped entirely when only unit tests are collected — no e2e
    items means no pipeline output is needed.
    """
    global _pipeline_failure

    # Only run the pipeline when e2e tests are collected.
    needs_pipeline = any(
        "e2e" in str(item.fspath).replace("\\", "/")
        for item in session.items
    )
    if not needs_pipeline:
        return

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

    # Forward COVERAGE_PROCESS_START so subprocess coverage data is captured.
    # Also ensure PROJECT_ROOT is on PYTHONPATH so sitecustomize.py is found
    # reliably on Linux (where '' may not be in sys.path for subprocesses).
    pipeline_env = os.environ.copy()
    coveragerc = os.path.join(PROJECT_ROOT, ".coveragerc")
    if os.path.isfile(coveragerc):
        pipeline_env.setdefault("COVERAGE_PROCESS_START", coveragerc)
        existing_pypath = pipeline_env.get("PYTHONPATH", "")
        pipeline_env["PYTHONPATH"] = (
            PROJECT_ROOT + os.pathsep + existing_pypath if existing_pypath else PROJECT_ROOT
        )

    cmd = [sys.executable, "run.py", SAMPLE_PROJECT, "--clean", "--selected-group", group]

    out.write(f"  Command: {' '.join(cmd)}\n")
    out.flush()

    if show_output:
        out.write(f"  Pipeline: {label}\n\n")
        out.flush()
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=pipeline_env)
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
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=pipeline_env,
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


@pytest.fixture(scope="session")
def run_pipeline(request):
    """Fail all tests if the pipeline failed during collection.

    Not autouse — integration and e2e tests request this explicitly (or via
    their conftest fixtures). Unit tests never request it.
    """
    if _pipeline_failure:
        pytest.fail(_pipeline_failure)
