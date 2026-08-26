"""Root conftest — pipeline lifecycle only.

CLI options and the pipeline subprocess are declared here (must be in root).
All other fixtures (snapshots, JSON loaders) live in integration/conftest.py.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.e2e_paths import (                                    # noqa: E402
    PROJECT_ROOT, SAMPLE_PROJECT, E2E_PID, E2E_VID, MODEL_DIR,
)

# Stores pipeline failure message if it failed; None means success or skipped.
_pipeline_failure = None


def _rmtree_force(path):
    """rmtree that clears read-only bits (git pack files on Windows)."""
    if not os.path.isdir(path):
        return

    def _retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    kw = {"onexc": _retry} if sys.version_info >= (3, 12) else {"onerror": _retry}
    shutil.rmtree(path, **kw)


def _scratch_repo():
    """SampleCppProject as a git repo of its own, returning (path, sha, branch).

    A version is identified by a commit, so the sample needs one of its own rather than
    borrowing the analyzer repo's HEAD -- which would change on every commit here and
    make the e2e run's identity depend on unrelated work.
    """
    repo = os.path.join(tempfile.gettempdir(), "analyzer-e2e-sample")
    # ignore_errors would leave the tree behind: git's pack files are read-only on
    # Windows, so the delete fails silently and the copy below then hits FileExists.
    _rmtree_force(repo)
    shutil.copytree(SAMPLE_PROJECT, repo)
    quiet = dict(check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", repo, "init", "-q"], **quiet)
    subprocess.run(["git", "-C", repo, "symbolic-ref", "HEAD", "refs/heads/main"], **quiet)
    subprocess.run(["git", "-C", repo, "add", "-A"], **quiet)
    subprocess.run(["git", "-C", repo, "-c", "user.email=e2e@test", "-c", "user.name=e2e",
                    "commit", "-q", "-m", "e2e sample"], **quiet)
    sha = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    return repo, sha, "main"


def _analyzer(*args, env=None):
    """One analyzer CLI call, raising with its own output if it fails."""
    r = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "analyzer.py"), *args],
                       cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError("analyzer %s failed (exit %d):\n%s\n%s"
                           % (args[0], r.returncode, r.stdout, r.stderr))
    return r


def _dump_model(out):
    """Materialise the version's model as model/*.json for the model-shape tests.

    Phases 1 and 2 write to the database; there is no model directory any more. The
    model is still sourced from the database -- these files are a hand-off, the same
    one the flowchart engine used before it read the database directly.
    """
    try:
        for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        from core.db import get_engine
        from core import model_store
        with get_engine().connect() as cx:
            model_store.dump_model_to_dir(cx, E2E_VID, MODEL_DIR)
    except Exception as exc:                    # not fatal: only the model tests need it
        out.write("\n  (model dump unavailable: %s)\n" % exc)


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
    group = "My Sample"
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

    # The analyzer CLI, not run.py directly: a phase needs a version row to write into,
    # and onboarding is what creates one. tests/e2e_paths.py has the full why.
    repo, sha, branch = _scratch_repo()
    _analyzer("onboard", "--project-id", E2E_PID, "--source", repo, "--use-defaults",
              "--branch", branch, "--version-id", E2E_VID, "--commit", sha,
              "--force-config", env=pipeline_env)
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "analyzer.py"), "generate",
           "--project-id", E2E_PID, "--version-id", E2E_VID, "--branch", branch,
           "--commit", sha, "--scope", "group:" + group, "--no-llm"]

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
        _dump_model(out)
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
