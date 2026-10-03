"""A render's timeout is the timeout -- it stops the whole process tree.

The diagram renderers go through the shell on Windows (mmdc is a .cmd) and start Node and
Chromium beneath it. `subprocess.run` answers a timeout by killing only the process it started,
then reads its pipes to the end -- and the grandchildren hold them open, so the read waits for
THEM. A unit diagram whose render hung, with a 60-second timeout, held its phase for an hour
(layer-scoped run of the sample, Layer1.Diag|ArmIntrinsics). `core.subprocess_util.run_capture`
stops the tree first.
"""
import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from core.subprocess_util import run_capture  # noqa: E402

SHELL = os.name == "nt"          # the renderers' own setting: through the shell on Windows


def test_output_and_exit_code_come_back_as_from_subprocess_run(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("import sys\nprint('drawn')\nsys.exit(3)\n", encoding="utf-8")
    r = run_capture([sys.executable, str(script)], timeout=60, shell=SHELL)
    assert r.returncode == 3 and r.stdout.strip() == "drawn"


def test_a_timeout_does_not_wait_for_a_grandchild_holding_the_pipes(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    script = tmp_path / "hang.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(%r, 'w').write(str(g.pid))\n"
        "time.sleep(120)\n" % str(pidfile), encoding="utf-8")
    t0 = time.monotonic()
    # 15 s, not 3: on a loaded machine the child had not yet started its grandchild (and written
    # its pid) when 3 s ran out. Still far below the grandchild's 120 s.
    with pytest.raises(subprocess.TimeoutExpired):
        run_capture([sys.executable, str(script)], timeout=15, shell=SHELL)
    assert time.monotonic() - t0 < 60, "waited for the grandchild instead of stopping it"

    psutil = pytest.importorskip("psutil")
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    assert not alive, "the grandchild outlived the timeout"


# --- the behaviour view's own mmdc call (views/behaviour_diagram._render_png) ---------------------

def _behaviour_view():
    from views import behaviour_diagram
    return behaviour_diagram


def test_the_behaviour_view_renders_through_run_capture(monkeypatch):
    """Its mmdc call went through `subprocess.run`, which on a timeout left Chromium running."""
    import core.subprocess_util as su
    calls = []
    monkeypatch.setattr(su, "run_capture", lambda cmd, *, timeout, shell=False: (
        calls.append(timeout) or subprocess.CompletedProcess(cmd, 0, "", "")))
    assert _behaviour_view()._render_png(["mmdc", "-i", "a.mmd"]).returncode == 0
    assert calls == [60]


def test_a_timed_out_diagram_is_tried_again_longer(monkeypatch):
    """Under load the first try timed out on a diagram that drew fine, and the row shipped with
    no picture (2026-09-30)."""
    import core.subprocess_util as su
    calls = []

    def first_times_out(cmd, *, timeout, shell=False):
        calls.append(timeout)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(su, "run_capture", first_times_out)
    assert _behaviour_view()._render_png(["mmdc"]).returncode == 0
    assert calls == [60, 180]


def test_a_diagram_that_never_draws_still_raises(monkeypatch):
    """The caller logs "mmdc timed out" and ships the row without a picture, as before."""
    import core.subprocess_util as su

    def always(cmd, *, timeout, shell=False):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(su, "run_capture", always)
    with pytest.raises(subprocess.TimeoutExpired):
        _behaviour_view()._render_png(["mmdc"])
