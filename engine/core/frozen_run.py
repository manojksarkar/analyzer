"""Start a long run in the background, on a frozen copy of the code (`--detach`).

Two things kill or corrupt a run that lasts days, and neither is about the run itself:

* **Its parent.** A run started from the web app is a child of the API process, reading its
  output through a pipe; stopping the API (`tools/start_app.py` kills the tree) stops the run, and
  the next start marks it failed. A run started in a terminal dies with the terminal.
* **The code under it.** The four phases are separate processes, and each loads the code from
  disk when it STARTS. Phase 3 starts days after Phase 1 -- with whatever the working tree holds
  by then: an engine fix made on day 2, a branch switched for an unrelated change.

So `--detach` copies the code a run needs (`analyzer.py`, `engine/`, `api/`, `tools/`) into
`<data root>/runs/<version>/<time>/code`, starts the same command from that copy as a process of
its own, with its output in `run.log` next to it, and returns. The copy works on the SAME data:
`ANALYZER_DATA_ROOT` (engine) and `ANALYZER_WORKSPACES_DIR` (API services) point it at this
installation's workspaces, model and output, so the version it writes is the one everything else
reads. Node packages resolve through this installation's `node_modules` (linked into the copy).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional

# What a run imports. analyzer.py imports api/ (registration, accounts) and tools/ (doctor,
# grant_access); the engine imports api.db.postgres.schema.
COPIED = ("analyzer.py", "engine", "api", "tools")
_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", "logs",
                                  ".flowchart_cache", ".dot_cache", ".mmdc_cache", ".pytest_cache",
                                  "*.db", "*.sqlite", "*.sqlite3")   # data, never code


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text or "run").strip("._") or "run"


def strip_detach(argv: List[str]) -> List[str]:
    """The command line the background process runs: the same one, without `--detach`."""
    return [x for x in argv if x != "--detach"]


def run_dir(data_root: str, version_key: str, now: Optional[datetime.datetime] = None) -> str:
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return os.path.join(data_root, "runs", safe_name(version_key), stamp)


def _claim_run_dir(data_root: str, version_key: str) -> str:
    """A run folder of its own: `run_dir`, or `<stamp>-2`, `-3`, ... when a run of the same
    version started in the same second. Two runs shared one folder -- their code copies, their
    run.json and their log -- and on Windows one copy failed on the other's open files."""
    base = run_dir(data_root, version_key)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    for n in range(1, 100):
        dest = base if n == 1 else f"{base}-{n}"
        try:
            os.mkdir(dest)
            return dest
        except FileExistsError:
            continue
    raise RuntimeError(f"no free run folder beside {base}")


#: Waits (seconds) before each new try of a file Windows says another process holds.
COPY_RETRIES = (0.2, 0.5, 1, 2, 4)


def _copy_retrying(src: str, dst: str) -> str:
    """`shutil.copy2`, tried again while the file is held by another process (WinError 32/33):
    an antivirus scanner opens every file just written, and a web export failed to start on
    dozens of them at once ("The run could not be started", 2026-10-03)."""
    for wait in COPY_RETRIES + (None,):
        try:
            return shutil.copy2(src, dst)
        except OSError as exc:
            if wait is None or getattr(exc, "winerror", None) not in (32, 33):
                raise
            time.sleep(wait)


def freeze(code_root: str, dest: str) -> str:
    """Copy the code a run needs into `dest/code`; return that directory."""
    code = os.path.join(dest, "code")
    os.makedirs(code, exist_ok=True)
    for name in COPIED:
        src = os.path.join(code_root, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(code, name), ignore=_IGNORED, dirs_exist_ok=True,
                            copy_function=_copy_retrying)
        elif os.path.isfile(src):
            _copy_retrying(src, os.path.join(code, name))
    _link_node_modules(code_root, code)
    return code


def _link_node_modules(code_root: str, code: str) -> None:
    """`node_modules` is not copied (hundreds of MB): link it. The renderers find their packages
    without it -- Node looks upward, and the copy sits inside this installation -- but the
    mermaid CLI is looked up at `<code root>/node_modules/.bin/mmdc`."""
    src, dst = os.path.join(code_root, "node_modules"), os.path.join(code, "node_modules")
    if not os.path.isdir(src) or os.path.exists(dst):
        return
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(src, dst)      # a junction needs no administrator rights
        else:
            os.symlink(src, dst, target_is_directory=True)
    except Exception as exc:                      # noqa: BLE001 - the renderers still work
        print(f"note: could not link node_modules into the frozen copy ({exc}); the mermaid "
              f"CLI will be looked for on the PATH", file=sys.stderr)


def child_env(*, data_root: str, workspaces_dir: str, log_path: str, code_dir: str,
              base: Optional[Dict[str, str]] = None,
              database_url: Optional[str] = None,
              exit_path: Optional[str] = None) -> Dict[str, str]:
    env = dict(os.environ if base is None else base)
    if database_url:
        # The database THIS process resolved. The copy would resolve its own: a relative SQLite
        # path against the copy, or a config.local.json edited after the run started.
        env["DATABASE_URL"] = database_url
    env.update({
        "ANALYZER_DATA_ROOT": os.path.abspath(data_root),
        "ANALYZER_WORKSPACES_DIR": os.path.abspath(workspaces_dir),
        "ANALYZER_RUN_LOG": os.path.abspath(log_path),
        "ANALYZER_RUN_CODE": os.path.abspath(code_dir),
        "PYTHONUNBUFFERED": "1",                  # the log is followed while the run goes
        "PYTHONIOENCODING": "utf-8",
    })
    if exit_path:
        # Where the run writes its exit code (`record_exit`): nobody waits for the process.
        env[EXIT_ENV] = os.path.abspath(exit_path)
    return env


def spawn(code_dir: str, argv: List[str], log_path: str, env: Dict[str, str],
          cwd: Optional[str] = None) -> int:
    """Start `python <code_dir>/analyzer.py <argv>` detached from this process and its terminal,
    in `cwd` (the caller's folder, so relative paths on its command line mean what they meant);
    return its pid."""
    kw = {}
    if os.name == "nt":
        # A console of its own, never shown, in a process group of its own: closing the terminal
        # or a Ctrl+C there does not reach it. NOT `DETACHED_PROCESS` -- with no console at all,
        # every phase it starts gets a NEW console, and the phases' output never reaches run.log.
        kw["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                               | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kw["start_new_session"] = True
    with open(log_path, "ab") as log:
        proc = subprocess.Popen([sys.executable, os.path.join(code_dir, "analyzer.py"), *argv],
                                cwd=cwd or os.getcwd(), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, env=env, close_fds=True, **kw)
    return proc.pid


def detach(argv: List[str], *, code_root: str, data_root: str, workspaces_dir: str,
           version_key: str, existing_code: Optional[str] = None,
           database_url: Optional[str] = None) -> Dict[str, object]:
    """Freeze the code (or reuse `existing_code`, a run's earlier copy), start `argv` in the
    background, write run.json beside the log; return what was started."""
    dest = _claim_run_dir(data_root, version_key)
    code = existing_code if existing_code and os.path.isdir(existing_code) else freeze(code_root, dest)
    log_path = os.path.join(dest, "run.log")
    argv = strip_detach(argv)
    env = child_env(data_root=data_root, workspaces_dir=workspaces_dir, log_path=log_path,
                    code_dir=code, database_url=database_url,
                    exit_path=os.path.join(dest, EXIT_FILE))
    pid = spawn(code, argv, log_path, env)
    info = {"pid": pid, "create_time": _create_time(pid),
            "argv": argv, "code_dir": code, "log_path": log_path, "run_dir": dest,
            "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            # The web job that started it, when one did: how an API that restarted finds the
            # run it was following (`find_job_run`).
            "job_id": os.environ.get("ANALYZER_JOB_ID") or None}
    with open(os.path.join(dest, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
    return info


# ---------------------------------------------------------------------------
# Following a background run: its exit code, whether it lives, stopping it
# ---------------------------------------------------------------------------

EXIT_FILE = "exit.json"
EXIT_ENV = "ANALYZER_EXIT_FILE"


def record_exit(code: int, path: Optional[str]) -> None:
    """Write a background run's exit code beside its log, as it exits (analyzer.py's entry
    point). Nobody waits for a detached process, so without this its outcome is a guess. A run
    that is killed writes nothing: no exit code and no process means it died."""
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"exit_code": int(code), "pid": os.getpid(),
                       "finished_at": datetime.datetime.now().isoformat(timespec="seconds")}, fh)
    except Exception:                             # noqa: BLE001 - never fail the exit
        pass


def read_exit(run_dir_: str) -> Optional[int]:
    """The exit code a background run recorded, or None while it has not exited (or if it died)."""
    try:
        with open(os.path.join(run_dir_, EXIT_FILE), encoding="utf-8") as fh:
            return int(json.load(fh)["exit_code"])
    except Exception:                             # noqa: BLE001 - absent or half written
        return None


def find_job_run(data_root: str, version_key: str, job_id: str) -> Optional[Dict[str, object]]:
    """The newest background run of `version_key` that web job `job_id` started (its run.json,
    with `run_dir`), or None."""
    base = os.path.join(data_root, "runs", safe_name(version_key))
    try:
        stamps = sorted(os.listdir(base), reverse=True)
    except OSError:
        return None
    for stamp in stamps:
        try:
            with open(os.path.join(base, stamp, "run.json"), encoding="utf-8") as fh:
                info = json.load(fh)
        except Exception:                         # noqa: BLE001 - not a run folder
            continue
        if info.get("job_id") == job_id:
            info["run_dir"] = os.path.join(base, stamp)
            return info
    return None


def _create_time(pid: Optional[int]) -> Optional[float]:
    """When process `pid` started (seconds since the epoch), or None when this cannot be told."""
    try:
        import psutil
        return psutil.Process(int(pid)).create_time()
    except Exception:                             # noqa: BLE001 - no psutil, or it is gone
        return None


def process_alive(pid: Optional[int], create_time: Optional[float] = None) -> Optional[bool]:
    """True while `pid` is the run's process, False when it is not, None when this cannot be told
    (no psutil, or no access to it -- then the version's lock decides). The process must have
    started when the run did (`create_time`, from run.json) and run analyzer.py: after a reboot
    the system gives its id to other programs, another run's among them."""
    if not pid:
        return False
    try:
        import psutil
    except ImportError:
        return None
    try:
        p = psutil.Process(int(pid))
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
        if create_time is not None and abs(p.create_time() - float(create_time)) > 2.0:
            return False
        try:
            return any("analyzer.py" in part for part in p.cmdline())
        except psutil.AccessDenied:
            return None
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return None


def stop(pid: Optional[int], create_time: Optional[float] = None) -> None:
    """Stop a background run and every process it started (its phases) -- only a process known to
    be the run: `process_alive` says so, or it cannot read the command line (no access) but the
    start time matches. After a reboot the run's id may belong to anything; killing that tree is
    worse than leaving a run to finish."""
    alive = process_alive(pid, create_time)
    if not (alive is True or (alive is None and create_time is not None
                              and _create_time(pid) is not None)):
        return
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            root = psutil.Process(int(pid))
            family = root.children(recursive=True) + [root]
        except psutil.Error:
            return
        for p in family:
            try:
                p.terminate()
            except psutil.Error:
                pass
        _, left = psutil.wait_procs(family, timeout=10)
        for p in left:
            try:
                p.kill()
            except psutil.Error:
                pass
    elif os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(int(pid), signal.SIGTERM)   # its own session: the group is the run's
        except OSError:
            pass
