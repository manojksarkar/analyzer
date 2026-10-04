"""A git command that does not finish is stopped, and answers as a failure.

`subprocess.run` with no timeout: a slow or unreachable repository -- or Git Credential Manager
waiting for a login nobody can type -- held the request (commit sync, Test Connection, the wizard's
tree) or the run behind it for ever. `tests/api/test_smoke.py::test_list_commits` waited an hour on
a clone of a URL that does not exist (2026-10-04). Both runners -- the API's (`git_cli`) and the
engine's, through which every clone goes (`git_ops`) -- now stop the whole process tree at a limit.
"""
import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.services import git_cli                 # noqa: E402
from incremental import git_ops                  # noqa: E402

pytestmark = pytest.mark.unit

RUNNERS = [git_cli, git_ops]


def _hang(tmp_path):
    """A stand-in for git that never answers -- and starts a child that holds its pipes, as git's
    helpers do -- written as a Python script the runner will start instead of git."""
    script = tmp_path / "hang.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "time.sleep(120)\n", encoding="utf-8")
    return str(script)


@pytest.mark.parametrize("mod", RUNNERS, ids=["api", "engine"])
class TestAHungGitIsStopped:
    def test_it_answers_as_a_failure_within_its_limit(self, mod, tmp_path, monkeypatch):
        script = _hang(tmp_path)
        monkeypatch.setattr(mod, "_git_exe", lambda: sys.executable)
        monkeypatch.setattr(mod, "TIMEOUTS", {"fetch": 3})
        t0 = time.monotonic()
        proc = mod._run([script, "fetch", "https://user:SECRET@example.invalid/r.git"])
        assert time.monotonic() - t0 < 60, "waited for the child holding the pipes"
        assert proc.returncode == mod.TIMED_OUT
        assert "did not finish within 3 s" in proc.stderr
        assert "SECRET" not in proc.stderr, "the arguments (a URL with a token) are never echoed"

    def test_a_command_that_answers_is_untouched(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_git_exe", lambda: sys.executable)
        proc = mod._run(["-c", "print('ok')"])
        assert proc.returncode == 0 and proc.stdout.strip() == "ok"


@pytest.mark.parametrize("mod", RUNNERS, ids=["api", "engine"])
class TestTheLimits:
    def test_each_network_command_has_its_own_and_the_rest_the_local_one(self, mod, monkeypatch):
        monkeypatch.delenv("ANALYZER_GIT_TIMEOUT", raising=False)
        assert mod._timeout(["clone", "--depth", "1", "u", "d"]) == mod.TIMEOUTS["clone"]
        assert mod._timeout(["-C", "d", "-c", "x=y", "fetch", "origin"]) == mod.TIMEOUTS["fetch"]
        assert mod._timeout(["ls-remote", "u"]) == mod.TIMEOUTS["ls-remote"] < 300
        assert mod._timeout(["-C", "d", "log"]) == mod.LOCAL_TIMEOUT

    def test_the_network_limit_can_be_set(self, mod, monkeypatch):
        monkeypatch.setenv("ANALYZER_GIT_TIMEOUT", "45")
        assert mod._timeout(["clone", "u", "d"]) == 45
        monkeypatch.setenv("ANALYZER_GIT_TIMEOUT", "soon")
        assert mod._timeout(["clone", "u", "d"]) == mod.TIMEOUTS["clone"]


def test_git_never_asks(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    env = git_cli.quiet_env()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
