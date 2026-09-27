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
    with pytest.raises(subprocess.TimeoutExpired):
        run_capture([sys.executable, str(script)], timeout=3, shell=SHELL)
    assert time.monotonic() - t0 < 40, "waited for the grandchild instead of stopping it"

    psutil = pytest.importorskip("psutil")
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    assert not alive, "the grandchild outlived the timeout"
