"""PhaseRunner's post-phase hook — the seam C11 hangs on (doc 09, C11a).

The hook is how the model reaches Postgres at every phase boundary instead of only at the end
of a run. Three properties have to hold, and none of them need a database to prove:

  * it fires after each phase that SUCCEEDS — otherwise nothing is persisted;
  * it does NOT fire for a phase that FAILED — persisting a half-written model would put a
    corrupt copy in the database, which is precisely what C11 must never do;
  * a hook that itself raises does not fail the run — during the dual-write the files are
    still authoritative, so a persistence problem must not destroy an otherwise good run.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.orchestration import Phase, PhaseRunner       # noqa: E402


class _Runner(PhaseRunner):
    """PhaseRunner with the subprocess replaced by a scripted list of exit codes."""

    def __init__(self, codes):
        super().__init__(project_root=PROJECT_ROOT)
        self._codes = list(codes)
        self.started = []

    def _fake(self, cmd, **kw):
        self.started.append(cmd)
        return (self._codes.pop(0), ["some stderr line"], 12.5)


def _phases():
    return [Phase("Phase 1: Parse C++ source", "parser.py"),
            Phase("Phase 2: Derive model", "model_deriver.py")]


def _patched(monkeypatch, runner):
    monkeypatch.setattr("core.orchestration.run_streaming", runner._fake)
    # keep the test off the metrics file and off the database
    monkeypatch.setattr("core.orchestration.run_metrics.record_phase", lambda *a, **k: None)
    monkeypatch.setattr("core.orchestration.set_pipeline_status", lambda *a, **k: None)


def test_hook_fires_once_per_successful_phase(monkeypatch):
    r = _Runner([0, 0])
    _patched(monkeypatch, r)
    seen = []
    r.run(_phases(), on_phase_done=lambda p: seen.append(p.script))
    assert seen == ["parser.py", "model_deriver.py"]


def test_hook_does_not_fire_for_a_failed_phase(monkeypatch):
    """A phase that failed left a partial model — persisting it would corrupt the DB copy."""
    r = _Runner([1])
    _patched(monkeypatch, r)
    seen = []
    with pytest.raises(SystemExit):
        r.run(_phases(), on_phase_done=lambda p: seen.append(p.script))
    assert seen == [], "the hook must not run for a phase that failed"


def test_a_raising_hook_does_not_fail_the_run(monkeypatch):
    """Dual-write stage: files are still authoritative, so a persistence error is logged and
    the run continues. Once reads move to the DB (C11b) this should be revisited."""
    r = _Runner([0, 0])
    _patched(monkeypatch, r)

    def _boom(_phase):
        raise RuntimeError("database went away")

    total = r.run(_phases(), on_phase_done=_boom)      # must not raise
    assert total > 0
    assert len(r.started) == 2                          # both phases still ran


def test_no_hook_is_the_unchanged_path(monkeypatch):
    """Every existing caller passes no hook; behaviour must be exactly as before."""
    r = _Runner([0, 0])
    _patched(monkeypatch, r)
    assert r.run(_phases()) > 0
    assert len(r.started) == 2


def test_skipped_phases_do_not_fire_the_hook(monkeypatch):
    """--from-phase skips earlier phases; a skipped phase produced nothing to persist."""
    r = _Runner([0])
    _patched(monkeypatch, r)
    seen = []
    r.run(_phases(), from_phase=2, on_phase_done=lambda p: seen.append(p.script))
    assert seen == ["model_deriver.py"]
