#!/usr/bin/env python3
"""start_app.py - start the API and the web app from THIS folder, cleanly.

    python tools/start_app.py            # check, stop old servers, start both, show their logs
    python tools/start_app.py --status   # what runs now: folder, commit, database, API URL
    python tools/start_app.py --stop     # stop them
    python tools/start_app.py --check    # the checks only; starts and stops nothing
    start-app.cmd [options]              # Windows: the same, from the repo root

"I have the new code but the old UI (or the old API) shows" has many causes, and in the browser
they all look alike. Everything below is checked BEFORE anything starts; what is safe to fix is
fixed, the rest stops the start with the fix spelled out:

  code     not the branch/commit you think; behind origin; an old file left beside the folder
           it moved into (pages/NewProjectPage.tsx next to pages/NewProjectPage/index.tsx -
           Vite loads the FILE, so the old page shows); files that are not in git
  servers  an old server still on the port, on ANY address (Vite binds ::1 only, so an old one
           on 127.0.0.1 can share the port number); an API started before the code changed (it
           does not reload); a server from another copy of the repo; a port Windows reserves
           (Hyper-V / WSL / Docker) or HTTP.sys holds
  web app  VITE_API_URL from the shell or a .env file pointing at another API; node_modules
           older than package-lock.json; Node too old for Vite; Vite's cache; a stale dist/
  API      no database configured (the in-memory TEST backend: seed data, nothing saved); the
           database unreachable or older than the code; bcrypt 5 (sign-in fails); `api`
           imported from another folder; analysis jobs a restart would stop, or that an earlier
           stop left marked running
  after    both answer; each port belongs to the server just started; the web app points at
           the API just started

Logs go to logs/start-app/ (api.log, web.log); state.json there is what --status/--stop read.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import errno
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import psutil
except ImportError:                      # reported by check_tools; nothing below runs without it
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web-app"
RUN_DIR = ROOT / "logs" / "start-app"
STATE_FILE = RUN_DIR / "state.json"
IS_WIN = os.name == "nt"

DEFAULT_API_PORT = 8000
DEFAULT_WEB_PORT = 5173
DEFAULT_NODE_RANGE = "^20.19.0 || >=22.12.0"      # Vite 8's engines.node, if it can't be read
ACTIVE_JOB_STATES = ("queued", "running")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # office proxies


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class Report:
    """Prints each check as it runs and remembers the failures."""

    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []

    @staticmethod
    def _out(tag: str, what: str, detail: str = "", fix: str = "") -> None:
        print(f"  [{tag}] {what}", flush=True)
        for line in (detail or "").splitlines():
            print(f"         {line}")
        for i, line in enumerate((fix or "").splitlines()):
            print(f"         {'fix: ' if i == 0 else '     '}{line}")

    def section(self, title: str) -> None:
        print(f"\n{title}", flush=True)

    def ok(self, what: str, detail: str = "") -> None:
        self._out(" ok ", what, detail)

    def info(self, what: str, detail: str = "") -> None:
        self._out("info", what, detail)

    def warn(self, what: str, detail: str = "", fix: str = "") -> None:
        self.warns.append(what)
        self._out("warn", what, detail, fix)

    def fail(self, what: str, detail: str = "", fix: str = "") -> None:
        self.fails.append(what)
        self._out("FAIL", what, detail, fix)


def _few(items: list, n: int = 8) -> str:
    items = [str(i) for i in items]
    more = f"\n... and {len(items) - n} more" if len(items) > n else ""
    return "\n".join(items[:n]) + more


def _ago(ts: float | None) -> str:
    if not ts:
        return "?"
    s = max(0, int(time.time() - ts))
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def _rel(p: Path | str) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, cwd: Path = ROOT, timeout: int = 60, env: dict | None = None):
    """(returncode, stdout, stderr); (127, '', error) when it cannot run at all."""
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def git(*args: str, timeout: int = 60):
    if not shutil.which("git"):
        return 127, "", "git is not on PATH"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}       # never hang on a password prompt
    return _run(["git", "-C", str(ROOT), *args], timeout=timeout, env=env)


def git_tracked(path: Path) -> bool:
    rc, out, _ = git("ls-files", "--", str(path))
    return rc == 0 and bool(out)


def http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    """(status, body); status 0 when nothing answered. Never goes through a proxy."""
    try:
        with _NO_PROXY.open(url, timeout=timeout) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:                                   # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _url_host(host: str) -> str:
    """A listening address as a host to connect to ('::' -> '::1', '0.0.0.0' -> 127.0.0.1)."""
    if host in ("", "0.0.0.0"):
        return "127.0.0.1"
    if host == "::":
        return "[::1]"
    return f"[{host}]" if ":" in host else host


def lan_ip() -> str:
    """The address other machines reach this one on (the interface of the default route)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.254.254.254", 1))                       # no packet is sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def _version_tuple(v: str) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple((nums + [0, 0, 0])[:3])                       # type: ignore[return-value]


def node_satisfies(version: str, rng: str) -> bool:
    """Does a Node version ('v24.13.1') satisfy an engines range ('^20.19.0 || >=22.12.0')?
    Handles the forms engines fields use: ^ ~ >= > <= < = and bare versions, joined by ||."""
    have = _version_tuple(version)
    for alt in rng.split("||"):
        ok = True
        for tok in alt.split():
            m = re.match(r"(\^|~|>=|<=|>|<|=)?v?(\d+(?:\.\d+){0,2})", tok)
            if not m:
                continue
            op, want = m.group(1) or "=", _version_tuple(m.group(2))
            if op == "^":
                upper = (want[0] + 1, 0, 0) if want[0] else (0, want[1] + 1, 0)
                ok &= want <= have < upper
            elif op == "~":
                ok &= want <= have < (want[0], want[1] + 1, 0)
            elif op == ">=":
                ok &= have >= want
            elif op == ">":
                ok &= have > want
            elif op == "<=":
                ok &= have <= want
            elif op == "<":
                ok &= have < want
            else:
                ok &= have[:len(m.group(2).split("."))] == want[:len(m.group(2).split("."))]
        if ok:
            return True
    return False


def read_env_value(path: Path, key: str) -> str | None:
    """The value a dotenv file gives `key`, or None. Understands comments, quotes, `export`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    value = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, sep, v = line.partition("=")
        if not sep or k.strip() != key:
            continue
        v = v.strip()
        if v[:1] in ("'", '"') and v[-1:] == v[:1] and len(v) >= 2:
            v = v[1:-1]
        else:
            v = v.split(" #", 1)[0].strip()
        value = v                                              # the last one wins, as in Vite
    return value


def find_web_shadows(src: Path) -> list[tuple[Path, Path]]:
    """(file, folder) pairs where `X.tsx` sits beside a folder `X/` that has an index file.
    An import of './X' loads the FILE (Vite and TypeScript try extensions before a folder's
    index), so an old file left behind after its code moved into the folder hides the new code."""
    exts = (".tsx", ".ts", ".jsx", ".js", ".mjs", ".mts")
    out: list[tuple[Path, Path]] = []
    if not src.is_dir():
        return out
    for d in sorted(p for p in src.rglob("*") if p.is_dir()):
        if "node_modules" in d.parts or not any((d / f"index{e}").is_file() for e in exts):
            continue
        for e in exts:
            f = d.with_name(d.name + e)
            if f.is_file():
                out.append((f, d))
    return out


def find_py_shadows(roots: list[Path]) -> list[tuple[Path, Path]]:
    """(package folder, module file) pairs where `X/__init__.py` sits beside `X.py`. Python
    imports the PACKAGE, so an old package folder left behind after it became one file hides
    the file."""
    skip = {"__pycache__", "node_modules", ".git", "workspaces"}
    out: list[tuple[Path, Path]] = []
    for r in roots:
        if not r.is_dir():
            continue
        for init in r.rglob("__init__.py"):
            pkg = init.parent
            if skip & set(pkg.parts):
                continue
            mod = pkg.with_name(pkg.name + ".py")
            if mod.is_file():
                out.append((pkg, mod))
    return out


def stale_node_modules(pkg_dir: Path) -> list[str]:
    """What `npm install` would change in pkg_dir, judged from package-lock.json: packages that
    are missing or at another version. Empty = node_modules matches the lock."""
    nm = pkg_dir / "node_modules"
    if not nm.is_dir():
        return ["node_modules is missing"]
    lock = pkg_dir / "package-lock.json"
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    bad: list[str] = []
    for key, meta in (data.get("packages") or {}).items():
        if not key.startswith("node_modules/"):
            continue
        name = key[len("node_modules/"):]
        if "/node_modules/" in name or meta.get("link") or meta.get("inBundle"):
            continue                    # nested copies, links: not a signal
        if meta.get("optional") and not _for_this_platform(meta):
            continue                    # another platform's binary (or a truly optional one)
        want = meta.get("version")
        pj = pkg_dir / key / "package.json"
        if not pj.is_file():
            bad.append(f"{name}: missing")
            continue
        try:
            have = json.loads(pj.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            have = None
        if want and have != want:
            bad.append(f"{name}: {have} installed, lock wants {want}")
    return bad


def _for_this_platform(meta: dict) -> bool:
    """Is a lock entry a platform binary meant for THIS machine (os/cpu/libc all match)?
    Those are 'optional' in the lock, yet Vite, Tailwind and lightningcss can't start without
    theirs - the usual break when node_modules was copied from another machine."""
    if "os" not in meta and "cpu" not in meta:
        return False
    import platform
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64",
            "x86": "ia32", "i386": "ia32", "i686": "ia32"}.get(platform.machine().lower(), "")
    libc = ""
    if sys.platform.startswith("linux"):
        libc = "glibc" if platform.libc_ver()[0] == "glibc" else "musl"

    def match(field, value) -> bool:
        if not field:
            return True
        neg = [f[1:] for f in field if f.startswith("!")]
        pos = [f for f in field if not f.startswith("!")]
        return value not in neg and (value in pos if pos else True)

    return (match(meta.get("os"), "linux" if sys.platform.startswith("linux") else sys.platform)
            and match(meta.get("cpu"), arch)
            and (not meta.get("libc") or match(meta.get("libc"), libc)))


def newest_mtime(roots: list[Path], suffixes: tuple[str, ...]) -> tuple[float, Path | None]:
    skip = {"__pycache__", "node_modules", ".git", "workspaces", "dist"}
    best, where = 0.0, None
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*"):
            if p.suffix in suffixes and not (skip & set(p.parts)):
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if m > best:
                    best, where = m, p
    return best, where


# ---------------------------------------------------------------------------
# Processes and ports
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.replace("\\", "/").lower()


def proc_info(pid: int | None) -> dict:
    """What a pid is: its command line, folder, start time, and whether it is one of this app's
    servers (kind 'api' / 'web'), some other node/python process, or something else."""
    d = {"pid": pid, "name": "?", "cmd": "", "cwd": "", "started": None, "kind": "other",
         "ours": False, "where": ""}
    if pid is None:
        d["name"] = "a process this user cannot see"
        return d
    if IS_WIN and pid == 4:
        d["name"] = "Windows (HTTP.sys - IIS or a Windows service)"
        return d
    try:
        p = psutil.Process(pid)
        d["name"] = p.name()
        d["started"] = p.create_time()
        try:
            d["cmd"] = " ".join(p.cmdline())
        except psutil.Error:
            pass
        try:
            d["cwd"] = p.cwd()
        except psutil.Error:
            pass
    except psutil.Error:
        return d
    low = _norm(d["cmd"])
    d["kind"] = _kind(low, d["name"])
    if d["kind"] == "node/python":
        # uvicorn --reload serves from a child whose command line names neither uvicorn nor
        # the app; it belongs to its parent
        try:
            parent = psutil.Process(pid).parent()
            if parent is not None and "--reload" in parent.cmdline():
                pk = _kind(_norm(" ".join(parent.cmdline())), parent.name())
                if pk == "api":
                    d["kind"] = pk
                    d["cmd"] = d["cmd"] or " ".join(parent.cmdline())
                    low = _norm(" ".join(parent.cmdline())) + " " + low
        except psutil.Error:
            pass
    m = re.search(r"(?i)([a-z]:)?/[^\"]*?(?=/web-app/node_modules/)", d["cmd"].replace("\\", "/"))
    d["where"] = (m.group(0) if m else "") or d["cwd"]
    root = _norm(str(ROOT)).rstrip("/")
    cwd = _norm(d["cwd"]).rstrip("/")
    d["ours"] = (root + "/") in low or cwd == root or cwd.startswith(root + "/")
    return d


def _kind(low_cmd: str, name: str) -> str:
    """'web' for a Vite binary, 'api' for uvicorn serving api.main:app, 'node/python' for any
    other node/python, else 'other'. Matches the program, not any mention of it (a shell whose
    command line merely contains VITE_API_URL is not a web server)."""
    if "/vite/bin/vite" in low_cmd or re.search(r"(^|[\s/\\\"])vite(\.cmd|\.js)?(\s|\"|$)", low_cmd):
        return "web"
    if "api.main:app" in low_cmd:
        return "api"
    if name.lower().startswith(("node", "python", "py.exe", "pythonw")):
        return "node/python"
    return "other"


def describe(d: dict) -> str:
    what = {"api": "API server", "web": "web app server"}.get(d["kind"], d["name"])
    parts = [f"{what} (pid {d['pid']}"]
    if d["started"]:
        parts.append(f", started {_ago(d['started'])}")
    parts.append(")")
    if d["kind"] in ("api", "web"):
        parts.append(" from this folder" if d["ours"] else f" from ANOTHER folder: {d['where'] or '?'}")
    return "".join(parts)


def listeners(port: int) -> list[dict]:
    """Every process listening on `port`, on any address, IPv4 or IPv6."""
    by_pid: dict = {}
    for c in psutil.net_connections(kind="tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
            by_pid.setdefault(c.pid, set()).add(c.laddr.ip)
    return [dict(proc_info(pid), addrs=sorted(a)) for pid, a in by_pid.items()]


def app_servers() -> list[dict]:
    """Every API / web app server of this app that listens anywhere, from any folder."""
    ports: dict = {}
    for c in psutil.net_connections(kind="tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr:
            ports.setdefault(c.pid, set()).add(c.laddr.port)
    out = []
    for pid, ps in ports.items():
        if not pid:
            continue
        d = proc_info(pid)
        low = _norm(d["cmd"])
        if (d["kind"] == "api" and "api.main:app" in low) or (d["kind"] == "web" and "web-app" in low):
            out.append(dict(d, ports=sorted(ps)))
    return out


def _background_run(q) -> bool:
    """A run started with `--detach` (a web run, a long CLI run): it lives in a frozen copy of the
    code under runs/ and must outlive a server restart. psutil finds a process's children by
    parent id, and Windows reuses ids: a run whose launcher's id the server's child took since
    would count as the server's grandchild."""
    try:
        cmd = " ".join(q.cmdline()).replace("\\", "/").lower()
    except psutil.Error:
        return False
    return "/runs/" in cmd and "/code/" in cmd


def kill_tree(pid: int) -> None:
    try:
        p = psutil.Process(pid)
        procs = [q for q in p.children(recursive=True) if not _background_run(q)] + [p]
    except psutil.Error:
        return
    for q in procs:
        try:
            q.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for q in alive:
        try:
            q.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=3)


def wait_port_free(port: int, timeout: float = 10) -> list[dict]:
    end = time.time() + timeout
    left = listeners(port)
    while left and time.time() < end:
        time.sleep(0.3)
        left = listeners(port)
    return left


def bind_problem(host: str, port: int) -> str | None:
    """None when `host:port` can be bound right now, else why not ('reserved' = Windows keeps
    the port for Hyper-V / WSL / Docker, whatever listens there)."""
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    try:
        if IS_WIN:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind((host, port))
        return None
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10013 or exc.errno == errno.EACCES:
            return "reserved"
        if getattr(exc, "winerror", None) == 10048 or exc.errno == errno.EADDRINUSE:
            return "in use"
        return str(exc)
    finally:
        s.close()


def reserved_ranges(port: int) -> list[str]:
    """The Windows excluded port ranges that contain `port`."""
    if not IS_WIN:
        return []
    out = []
    for proto in ("ipv4", "ipv6"):
        _, text, _ = _run(["netsh", "interface", proto, "show", "excludedportrange",
                           "protocol=tcp"], timeout=15)
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+(\d+)", line)
            if m and int(m.group(1)) <= port <= int(m.group(2)):
                out.append(f"{proto}: {m.group(1)}-{m.group(2)}")
    return out


# ---------------------------------------------------------------------------
# State (what --status / --stop know about the servers this tool started)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def clear_state(own_pids: set | None = None) -> None:
    """Forget the started servers. With own_pids, only when the state is still ours - a later
    start that replaced these servers has written its own."""
    if own_pids is not None:
        st = load_state()
        if st and not ({(st.get("api") or {}).get("pid"), (st.get("web") or {}).get("pid")} & own_pids):
            return
    try:
        STATE_FILE.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def code_info() -> dict:
    """Branch and HEAD commit, in one git call (each costs ~1 s on some Windows boxes)."""
    rc, line, _ = git("log", "-1", "--format=%h%x09%H%x09%cd%x09%D%x09%s",
                      "--date=format:%Y-%m-%d %H:%M")
    if rc != 0 or not line:
        return {}
    short, full, date, refs, subject = (line.split("	", 4) + [""] * 5)[:5]
    m = re.match(r"HEAD -> ([^,]+)", refs)
    return {"branch": m.group(1) if m else "HEAD", "sha": short, "full_sha": full,
            "date": date, "subject": subject}


def check_code(rep: Report, args) -> dict:
    rep.section("Code")
    rep.info(f"Folder: {ROOT}")
    if args.pull:
        rc, out, err = git("pull", "--ff-only", timeout=180)
        if rc == 0:
            rep.ok("git pull --ff-only", (out or "").splitlines()[-1] if out else "")
        else:
            rep.fail("git pull --ff-only failed", err or out,
                     fix="commit or stash local changes, or pull by hand")
    info = code_info()
    if not info:
        rep.warn("Not a git checkout - which commit this code is can't be told",
                 "a folder copied over an older one keeps files the new code deleted;\n"
                 "the old-file check below still runs")
    else:
        head = "detached HEAD" if info["branch"] == "HEAD" else info["branch"]
        what = f"Code: {head} @ {info['sha']}  ({info['date']})  {info['subject']}"
        (rep.warn if head == "detached HEAD" else rep.ok)(what)
        _, st, _ = git("status", "--porcelain=v2", "--branch", "--", "web-app", "api", "engine")
        up, ahead, behind, changed, untracked = "", 0, 0, [], []
        for ln in st.splitlines():
            if ln.startswith("# branch.upstream "):
                up = ln.split(" ", 2)[2]
            elif ln.startswith("# branch.ab "):
                ab = ln.split()
                ahead, behind = abs(int(ab[2])), abs(int(ab[3]))
            elif ln.startswith("? "):
                untracked.append(ln[2:])
            elif ln[:2] in ("1 ", "u "):
                changed.append(ln.split(" ", 8)[-1])
            elif ln.startswith("2 "):
                changed.append(ln.split(" ", 9)[-1].split("	")[0])
        if up:
            fh = ROOT / ".git" / "FETCH_HEAD"
            when = f", fetched {_ago(fh.stat().st_mtime)}" if fh.is_file() else ""
            if behind:
                rep.warn(f"{behind} commit(s) behind {up} (as of the last fetch{when})",
                         fix="git pull   (or add --pull)")
            else:
                rep.ok(f"Not behind {up} (as of the last fetch{when})"
                       + (f"; {ahead} local commit(s) not pushed" if ahead else ""))
        else:
            rep.info("This branch has no upstream - not compared with origin")
        if changed:
            rep.info(f"{len(changed)} file(s) changed and not committed (they run as they are)",
                     _few(changed, 5))
        if untracked:
            rep.warn(f"{len(untracked)} path(s) under web-app/, api/, engine/ are not in git",
                     _few(untracked, 8),
                     fix="if you don't know them, they are leftovers from an older copy: delete them")

    # An old file beside the folder its code moved into is loaded INSTEAD of the new code.
    # (stale = the side that gets loaded, partner = the side that should be)
    moves: list[tuple[Path, Path, str]] = []
    for f, d in find_web_shadows(WEB / "src"):
        moves.append((f, d, f"{_rel(f)} is loaded instead of {_rel(d)}/ (a file wins over a folder)"))
    for pkg, mod in find_py_shadows([ROOT / "api", ROOT / "engine"]):
        moves.append((pkg, mod, f"{_rel(pkg)}/ is imported instead of {_rel(mod)} (a package wins over a module)"))
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for stale, partner, why in moves:
        if info:
            stale_in_git, partner_in_git = git_tracked(stale), git_tracked(partner)
            if stale_in_git:                # the loaded side is the committed one
                rep.warn(why, "both are in git - one of them should not be" if partner_in_git
                         else f"{_rel(partner)} is not in git and never loads: delete it")
                continue
            if not partner_in_git:          # neither is committed: someone's work in progress
                rep.fail(why, "neither is in git, so which one is old can't be told",
                         fix="delete the old one yourself")
                continue
        if args.check:
            rep.fail(why, "an old copy left behind: the old screen/code runs, not the new one",
                     fix="run without --check to move it aside, or delete it")
        elif info or args.yes:
            dest = RUN_DIR / "stale-files" / stamp / _rel(stale)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stale), str(dest))
            rep.warn(why, f"not in git - an old copy left behind. Moved aside to\n{_rel(dest)}")
        else:
            rep.fail(why, "this folder is not a git checkout, so which side is old can't be told",
                     fix=f"delete the old one yourself, or rerun with --yes to move {_rel(stale)} aside")
    if not moves:
        rep.ok("No old file hides a moved one (web-app/src, api, engine)")
    return info


def check_tools(rep: Report, args) -> dict:
    """Python + packages, Node, npm, node_modules. Returns {'install': [reasons]}."""
    rep.section("Tools")
    out: dict = {"install": []}
    v = sys.version_info
    py = f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if v < (3, 10):
        rep.fail(py, fix="install Python 3.12 or newer")
    elif v < (3, 12):
        rep.warn(py, "docs/SETUP.md asks for 3.12 or newer")
    else:
        rep.ok(py)
    for venv in (ROOT / ".venv", ROOT / "venv"):
        if (venv / "pyvenv.cfg").is_file() and not _norm(sys.prefix).startswith(_norm(str(venv))):
            exe = venv / ("Scripts/python.exe" if IS_WIN else "bin/python")
            rep.warn(f"{_rel(venv)} exists, but this runs with {sys.executable}",
                     "the packages installed in that venv are not the ones the API gets",
                     fix=f'"{exe}" tools/start_app.py   (start-app.cmd picks it up by itself)')

    missing = []
    for mod, pip in (("fastapi", "fastapi"), ("uvicorn", "uvicorn[standard]"),
                     ("sqlalchemy", "SQLAlchemy"), ("pydantic", "pydantic"),
                     ("pydantic_settings", "pydantic-settings"),
                     ("jose", "python-jose[cryptography]"), ("passlib", "passlib[bcrypt]"),
                     ("bcrypt", "bcrypt<4.0.0"), ("multipart", "python-multipart"),
                     ("sse_starlette", "sse-starlette"), ("psutil", "psutil")):
        if importlib.util.find_spec(mod) is None:
            missing.append(pip)
    if missing:
        rep.fail(f"Python packages missing for this Python: {', '.join(missing)}",
                 f"the API runs with {sys.executable}",
                 fix=f'"{sys.executable}" -m pip install -r requirements.txt')
    else:
        rep.ok("Python packages for the API are installed")
    try:
        import importlib.metadata as md
        bv = md.version("bcrypt")
        major = _version_tuple(bv)[0]
        if major >= 5:
            rep.fail(f"bcrypt {bv}: passlib 1.7 cannot hash with bcrypt 5 - every sign-in fails",
                     fix=f'"{sys.executable}" -m pip install "bcrypt>=3.2,<4"')
        elif major == 4:
            rep.warn(f"bcrypt {bv}: requirements.txt pins <4 (passlib 1.7 logs a version error)",
                     fix=f'"{sys.executable}" -m pip install "bcrypt>=3.2,<4"')
    except Exception:                                           # noqa: BLE001
        pass

    # `api` must import from THIS folder (a PYTHONPATH entry or an installed `api` would win
    # over nothing - but it is cheap to prove).
    rc, where, err = _run([sys.executable, "-c",
                           "import api,os;print(os.path.realpath(list(api.__path__)[0]))"])
    if rc != 0:
        rep.fail("`import api` fails from the repo root", err.splitlines()[-1] if err else "")
    elif _norm(where) != _norm(os.path.realpath(ROOT / "api")):
        rep.fail(f"`import api` loads {where}, not this folder's api/",
                 fix="remove that folder from PYTHONPATH / uninstall the package named api")

    node = shutil.which("node")
    if not node:
        rep.fail("Node.js is not on PATH", fix="install Node.js 22.12+ (or 20.19+)")
    else:
        _, nv, _ = _run([node, "--version"])
        rng = DEFAULT_NODE_RANGE
        try:
            vite_pkg = json.loads((WEB / "node_modules/vite/package.json").read_text(encoding="utf-8"))
            rng = (vite_pkg.get("engines") or {}).get("node") or rng
        except (OSError, ValueError):
            pass
        if node_satisfies(nv, rng):
            rep.ok(f"Node {nv} ({node})")
        else:
            rep.fail(f"Node {nv} is too old for this Vite (needs {rng})",
                     fix="install Node.js 22.12 or newer")
    out["node"] = node
    out["npm"] = shutil.which("npm")
    if not out["npm"]:
        rep.warn("npm is not on PATH", fix="install Node.js with npm")

    if not (WEB / "index.html").is_file() or not (WEB / "src/main.tsx").is_file():
        rep.fail(f"{_rel(WEB)} is incomplete (no index.html or src/main.tsx)")
    stale = stale_node_modules(WEB)
    if stale:
        out["install"] = stale
        if args.no_install or args.check:
            (rep.fail if "node_modules is missing" in stale else rep.warn)(
                "web-app/node_modules does not match package-lock.json", _few(stale, 5),
                fix="cd web-app; npm install")
        else:
            rep.info("web-app/node_modules does not match package-lock.json - npm install will run",
                     _few(stale, 5))
    else:
        rep.ok("web-app/node_modules matches package-lock.json")
    root_missing = [p for p in ("@viz-js/viz", "@mermaid-js/mermaid-cli")
                    if not (ROOT / "node_modules" / p / "package.json").is_file()]
    if root_missing:
        rep.warn(f"Repo-root npm packages missing: {', '.join(root_missing)}",
                 "the app starts, but runs can't draw flowcharts / diagrams",
                 fix="npm install   (in the repo root)")
    return out


def check_web_env(rep: Report, args, api_url: str) -> None:
    rep.section("Web app settings")
    mode = "production" if args.prod else "development"
    shell = os.environ.get("VITE_API_URL")
    if shell and shell != api_url:
        rep.warn(f"VITE_API_URL is set in this shell: {shell}",
                 f"ignored for this start ({api_url}); a plain `npm run dev` here would use it",
                 fix="Remove-Item Env:VITE_API_URL   (PowerShell)   /   set VITE_API_URL=   (cmd)")
    for name in (".env", ".env.local", f".env.{mode}", f".env.{mode}.local"):
        val = read_env_value(WEB / name, "VITE_API_URL")
        if val is None:
            continue
        if val == api_url:
            rep.ok(f"web-app/{name}: VITE_API_URL={val}")
        else:
            rep.warn(f"web-app/{name} sets VITE_API_URL={val}",
                     f"ignored for this start ({api_url} wins); a plain `npm run dev` would talk to it",
                     fix=f"delete that line, or set it to {api_url}")
    rep.info(f"The web app will call the API at {api_url}")
    dist = WEB / "dist" / "index.html"
    if dist.is_file() and not args.prod:
        src_m, _ = newest_mtime([WEB / "src"], (".ts", ".tsx", ".css"))
        built = dist.stat().st_mtime
        if src_m > built:
            rep.warn(f"web-app/dist was built {_ago(built)} and is older than the source",
                     "not used here (dev server) - but anything serving dist/ (IIS, nginx,\n"
                     "vite preview, python -m http.server) shows the UI as of that build",
                     fix="use --prod to rebuild it, or delete web-app/dist")


def _load_schema_metadata():
    """api/db/postgres/schema.py alone (only SQLAlchemy) - importing it through `api.db` would
    build the API's database object as a side effect."""
    spec = importlib.util.spec_from_file_location("_start_app_schema",
                                                  ROOT / "api/db/postgres/schema.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)                               # type: ignore[union-attr]
    return mod.metadata


def run_setup() -> int:
    print("         running: python analyzer.py setup", flush=True)
    return subprocess.call([sys.executable, str(ROOT / "analyzer.py"), "setup"], cwd=str(ROOT))


def check_database(rep: Report, args, _retried: bool = False) -> dict:
    if not _retried:
        rep.section("Database")
    info: dict = {}
    for p in (str(ROOT), str(ROOT / "engine")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from core.db import (_dsn_from_config, _redact, _unreachable_help, database_url,
                             dsn_host_port, is_database_configured)
    except Exception as exc:                                    # noqa: BLE001
        rep.fail("engine/core/db.py does not load", f"{type(exc).__name__}: {exc}",
                 fix="pip install -r requirements.txt")
        return info
    bad = rep.warn if args.allow_memory_db else rep.fail
    memory_why = ("the API would run on the in-memory TEST backend: seed data only, nothing is\n"
                  "saved, and it looks like a different app")
    if os.environ.get("API_DB_BACKEND", "").strip().lower() == "memory":
        bad("API_DB_BACKEND=memory is set in this shell", memory_why,
            fix="Remove-Item Env:API_DB_BACKEND   (or --allow-memory-db to want exactly that)")
        info["memory"] = True
        return info
    if not is_database_configured():
        bad("No database configured", memory_why,
            fix="add a `db` section to engine/config/config.local.json (docs/SETUP.md section 3),\n"
                "or pass --database-url <dsn>")
        info["memory"] = True
        return info
    try:
        dsn = database_url()
    except Exception as exc:                                    # noqa: BLE001
        rep.fail("The database URL is not valid", str(exc))
        return info
    if args.database_url:
        source = "--database-url"
    elif os.environ.get("DATABASE_URL", "").strip():
        source = "DATABASE_URL in this shell"
        cfg = None
        try:
            cfg = _dsn_from_config()
        except Exception:                                       # noqa: BLE001
            pass
        if cfg and cfg != dsn:
            source += f" (wins over config.local.json's {_redact(cfg)})"
    else:
        source = "engine/config/config.local.json"
    info.update(dsn=_redact(dsn), source=source)
    if not _retried:
        rep.info(f"Database: {_redact(dsn)}", f"from {source}")
    is_pg = dsn.startswith("postgres")
    if is_pg and importlib.util.find_spec("psycopg") is None:
        rep.fail("psycopg is not installed (the PostgreSQL driver)",
                 fix=f'"{sys.executable}" -m pip install "psycopg[binary]"')
        return info

    import sqlalchemy as sa
    from sqlalchemy.engine import make_url
    try:
        info["name"] = make_url(dsn).database
    except Exception:                                           # noqa: BLE001
        info["name"] = "?"
    # a pooled engine: the inspector connects once per call, and at ~0.5 s a connection
    # (seen on Windows) a NullPool made the 36-table schema check take 20 s
    eng = sa.create_engine(dsn, connect_args={"connect_timeout": 5} if is_pg else {})
    try:
        try:
            with eng.connect() as cx:
                cx.execute(sa.text("SELECT 1"))
        except Exception as exc:                                # noqa: BLE001
            first = (str(exc).strip().splitlines() or [""])[0]
            if "does not exist" in first and not args.check and not _retried:
                rep.warn(f"Database {info['name']!r} does not exist yet - creating it")
                if run_setup() == 0:
                    return check_database(rep, args, _retried=True)
            host, port = dsn_host_port(dsn)
            rep.fail(f"Database unreachable: {type(exc).__name__}: {first}",
                     _unreachable_help(host, port, exc) if is_pg else "")
            return info
        rep.ok("Database reachable")

        # The schema the code expects vs the one the database has.
        metadata = _load_schema_metadata()
        insp = sa.inspect(eng)
        have = set(insp.get_table_names())
        missing_tables = [t for t in metadata.tables if t not in have]
        if missing_tables and not args.check and not _retried:
            rep.warn(f"{len(missing_tables)} table(s) the code needs are missing - creating them",
                     _few(missing_tables, 6))
            if run_setup() == 0:
                eng.dispose()
                return check_database(rep, args, _retried=True)
        if missing_tables:
            rep.fail(f"{len(missing_tables)} table(s) the code needs are missing",
                     _few(missing_tables, 6), fix="python analyzer.py setup")
            return info
        missing_cols = []
        for name, table in metadata.tables.items():
            cols = {c["name"] for c in insp.get_columns(name)}
            for c in table.columns:
                if c.name not in cols:
                    try:
                        typ = c.type.compile(dialect=eng.dialect)
                    except Exception:                           # noqa: BLE001
                        typ = str(c.type)
                    missing_cols.append(f"ALTER TABLE {name} ADD COLUMN {c.name} {typ};")
        if missing_cols:
            rep.fail(f"The database is older than the code: {len(missing_cols)} column(s) missing",
                     "`analyzer.py setup` creates tables but does not add columns; the API\n"
                     "fails (500) wherever it reads them",
                     fix="python -m alembic upgrade head   - or run these by hand:\n"
                         + _few(missing_cols, 10))
            return info
        rep.ok(f"Schema matches the code ({len(metadata.tables)} tables)")

        with eng.connect() as cx:
            def count(table: str):
                try:
                    return cx.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
                except Exception:                               # noqa: BLE001
                    cx.rollback()               # a failed statement poisons the transaction
                    return "?"
            info.update(projects=count("projects"), users=count("users"),
                        versions=count("versions"))
            try:
                rows = cx.execute(sa.text(
                    "SELECT j.id, j.status, j.started_at, p.name FROM analysis_jobs j "
                    "LEFT JOIN projects p ON p.id = j.project_id WHERE j.status IN "
                    "('queued', 'running') ORDER BY j.started_at")).all()
            except Exception:                                   # noqa: BLE001
                rows = []
        info["active_jobs"] = [f"{r[3] or '?'}: job {r[0]} {r[1]} since {r[2]}" for r in rows]
        rep.info(f"{info['projects']} project(s), {info['users']} user(s), "
                 f"{info['versions']} version(s) in database {info['name']!r}",
                 "no projects: if you expected some, the API is pointed at another database"
                 if info["projects"] == 0 else "")
        if info["active_jobs"]:
            rep.warn(f"{len(rows)} analysis job(s) are marked queued/running",
                     _few(info["active_jobs"], 6)
                     + "\nif an API is running them, restarting it stops them; if none is (an earlier"
                       "\nstop cut them off), the Overview shows them running forever and blocks a new run",
                     fix="cut off ones: open the project's Overview and press Cancel Job")
    finally:
        eng.dispose()
    return info


def check_ports(rep: Report, args, hosts: dict) -> list[dict] | None:
    """The servers that must be stopped first, or None when a port can't be used."""
    rep.section("Ports")
    victims: list[dict] = []
    if args.api_port == args.web_port:
        rep.fail(f"--api-port and --web-port are both {args.api_port}")
        return None
    usable = True
    for role, port, flag in (("API", args.api_port, "--api-port"),
                             ("Web app", args.web_port, "--web-port")):
        found = listeners(port)
        if not found:
            prob = bind_problem(hosts[role], port)
            if prob == "reserved":
                rep.fail(f"{role} port {port} is reserved by Windows (Hyper-V / WSL / Docker)",
                         _few(reserved_ranges(port)) or "", fix=f"pick another: {flag} <n>")
                usable = False
            elif prob:
                rep.fail(f"{role} port {port} can't be used: {prob}", fix=f"pick another: {flag} <n>")
                usable = False
            else:
                rep.ok(f"{role} port {port} is free")
            continue
        for d in found:
            addrs = ", ".join(d.get("addrs") or [])
            if d["kind"] == "other" or not d["pid"]:
                rep.fail(f"{role} port {port} is held by {describe(d)} on {addrs}",
                         "not this app's server - it won't be stopped",
                         fix=f"pick another port: {flag} <n>")
                usable = False
            elif d["kind"] == "node/python" and not args.yes:
                rep.fail(f"{role} port {port} is held by {describe(d)} on {addrs}",
                         f"not recognised as this app's server: {d['cmd'][:160]}",
                         fix=f"stop it yourself, rerun with --yes to stop it, or {flag} <n>")
                usable = False
            else:
                note = ("" if d["ours"] else
                        "\nTHIS is how an old UI / old API shows: a server from another copy of the repo")
                rep.warn(f"{role} port {port}: {describe(d)} on {addrs}"
                         + (" - will be stopped" if not args.check else ""),
                         (d["cmd"][:200] + note).strip())
                victims.append(d)
    others = [s for s in app_servers()
              if not set(s["ports"]) & {args.api_port, args.web_port}]
    for s in others:
        rep.info(f"Also running: {describe(s)} on port(s) {', '.join(map(str, s['ports']))}",
                 "a browser tab on that port shows what it runs; stop it with --stop-others")
    if args.stop_others and not args.check:
        victims += others
    return victims if usable else None


# ---------------------------------------------------------------------------
# Running the servers
# ---------------------------------------------------------------------------

class Pump(threading.Thread):
    """Copies a child's output to its log (without colour codes) and, prefixed, to the console."""

    def __init__(self, proc: subprocess.Popen, prefix: str, log_path: Path) -> None:
        super().__init__(daemon=True)
        self.proc, self.prefix, self.log_path = proc, prefix, log_path
        self.tail: collections.deque = collections.deque(maxlen=80)

    def run(self) -> None:
        with open(self.log_path, "a", encoding="utf-8") as log:
            for raw in iter(self.proc.stdout.readline, b""):        # type: ignore[union-attr]
                line = _ANSI.sub("", raw.decode("utf-8", "replace").rstrip("\r\n"))
                self.tail.append(line)
                log.write(line + "\n")
                log.flush()
                print(f"{self.prefix} | {line}", flush=True)


class Server:
    def __init__(self, name: str, prefix: str, cmd: list, cwd: Path, env: dict,
                 log_path: Path, detach: bool) -> None:
        self.name, self.log_path = name, log_path
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            try:
                log_path.replace(log_path.with_suffix(".prev.log"))
            except OSError:
                pass
        kw: dict = dict(cwd=str(cwd), env=env, stdin=subprocess.DEVNULL)
        self.pump: Pump | None = None
        if detach:
            logf = open(log_path, "ab")
            kw.update(stdout=logf, stderr=subprocess.STDOUT)
            if IS_WIN:
                # own hidden console: survives this window closing, and git/node children of
                # the API don't pop up windows
                flags = 0x00000200 | 0x08000000             # NEW_PROCESS_GROUP | NO_WINDOW
                try:
                    self.proc = subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)
                except OSError:                              # the job forbids breakaway
                    self.proc = subprocess.Popen(cmd, creationflags=flags, **kw)
            else:
                self.proc = subprocess.Popen(cmd, start_new_session=True, **kw)
            logf.close()
        else:
            kw.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if IS_WIN:
                kw["creationflags"] = 0x00000200      # Ctrl+C reaches only this tool, which stops both
            else:
                kw["start_new_session"] = True
            self.proc = subprocess.Popen(cmd, **kw)
            self.pump = Pump(self.proc, prefix, log_path)
            self.pump.start()

    def tail(self, n: int = 25) -> list[str]:
        if self.pump:
            time.sleep(0.3)
            return list(self.pump.tail)[-n:]
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        except OSError:
            return []

    def log_text(self) -> str:
        return "\n".join(self.tail(200))

    def stop(self) -> None:
        if self.proc.poll() is None:
            kill_tree(self.proc.pid)

    def tree(self) -> set:
        try:
            p = psutil.Process(self.proc.pid)
            return {p.pid} | {c.pid for c in p.children(recursive=True)}
        except psutil.Error:
            return {self.proc.pid}


def wait_http(url: str, server: Server, timeout: float, want=lambda s, b: s == 200):
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        if server.proc.poll() is not None:
            return False, f"it exited with code {server.proc.returncode}"
        status, body = http_get(url)
        if want(status, body):
            return True, body
        last = f"HTTP {status}" if status else body
        time.sleep(0.5)
    return False, f"no answer in {int(timeout)}s ({last})"


def served_api_url(body: str) -> str | None:
    """The API URL a dev-served src/lib/http.ts will use: VITE_API_URL from the env Vite
    injected, else the code's own fallback."""
    m = re.search(r"import\.meta\.env\s*=\s*(\{.*?\});", body)
    if m:
        try:
            env = json.loads(m.group(1))
            if env.get("VITE_API_URL"):
                return env["VITE_API_URL"]
        except ValueError:
            pass
    m = re.search(r"VITE_API_URL\s*\?\?\s*[\"']([^\"']+)", body)
    return m.group(1) if m else None


def foreign_on(port: int, server: Server) -> list[dict]:
    mine = server.tree()
    return [d for d in listeners(port) if d["pid"] not in mine]


def diagnose_api_log(text: str) -> str:
    if "address already in use" in text.lower() or "10048" in text:
        return "the port was taken again just before it started - rerun"
    if "ModuleNotFoundError" in text:
        m = re.search(r"No module named '([^']+)'", text)
        return f'"{sys.executable}" -m pip install -r requirements.txt' + (f"   (missing: {m.group(1)})" if m else "")
    return "see logs/start-app/api.log"


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print(f"  {question} - no terminal to ask; rerun with --yes")
        return False
    try:
        return input(f"  {question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def start(args) -> int:
    rep = Report()
    print(f"ArtiFex - start the API and the web app from {ROOT}")
    lan = args.lan or bool(args.public_host)
    bind = "0.0.0.0" if lan else "127.0.0.1"
    public = args.public_host or (lan_ip() if lan else "localhost")
    plan = {"bind": bind, "public": public, "lan": lan,
            "api_url": f"http://{public}:{args.api_port}/api/v1",
            "web_url": f"http://{public}:{args.web_port}"}
    hosts = {"API": bind, "Web app": bind}
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    if psutil is None:
        rep.fail("psutil is not installed (needed to find and stop old servers)",
                 fix=f'"{sys.executable}" -m pip install psutil')
        return 1
    code = check_code(rep, args)
    tools = check_tools(rep, args)
    check_web_env(rep, args, plan["api_url"])
    db = check_database(rep, args)
    victims = check_ports(rep, args, hosts)
    if rep.fails or victims is None:
        print(f"\nNot started - {len(rep.fails)} problem(s) above marked FAIL.")
        return 1
    if args.check:
        print(f"\nChecks passed ({len(rep.warns)} warning(s)). --check: nothing was started or stopped.")
        return 0

    # -- stop what holds the ports --------------------------------------------------------
    if victims:
        rep.section("Stopping old servers")
        if any(v["kind"] == "api" for v in victims) and db.get("active_jobs"):
            if not confirm("Restarting the API stops the analysis runs listed above. Continue?",
                           args.yes):
                print("\nNot started.")
                return 1
        for v in victims:
            print(f"  stopping {describe(v)}", flush=True)
            kill_tree(v["pid"])
        for role, port in (("API", args.api_port), ("Web app", args.web_port)):
            left = wait_port_free(port)
            if left:
                rep.fail(f"{role} port {port} is still held after stopping: "
                         + "; ".join(describe(d) for d in left),
                         fix="stop it from Task Manager, or pick another port")
            elif bind_problem(hosts[role], port):
                rep.fail(f"{role} port {port} still can't be bound", fix="pick another port")
        if rep.fails:
            print("\nNot started.")
            return 1
        rep.ok("Old servers stopped")
    clear_state()

    # -- dependencies ---------------------------------------------------------------------
    if tools["install"] and not args.no_install:
        rep.section("npm install (web-app)")
        if not tools.get("npm"):
            rep.fail("npm is needed to install web-app/node_modules")
            return 1
        rc = subprocess.call([tools["npm"], "install", "--no-audit", "--no-fund"], cwd=str(WEB))
        left = stale_node_modules(WEB)
        if rc != 0 or left:
            rep.fail("npm install did not bring node_modules in line with package-lock.json",
                     _few(left, 5), fix="look at npm's output above (a proxy? no registry access?)")
            return 1
        rep.ok("web-app/node_modules installed")

    servers: list[Server] = []
    try:
        return run_servers(rep, args, plan, code, tools, db, servers)
    except KeyboardInterrupt:
        print("\nStopping the web app and the API ...", flush=True)
        for s in reversed(servers):
            s.stop()
        clear_state(own_pids={s.proc.pid for s in servers})
        print("Stopped.")
        return 0


def run_servers(rep: Report, args, plan: dict, code: dict, tools: dict, db: dict,
                servers: list) -> int:
    """Start the API, then the web app; prove each is the one answering; then wait.
    Every Server started is appended to `servers` so the caller can stop them on Ctrl+C."""
    bind, public, lan = plan["bind"], plan["public"], plan["lan"]
    api_url, web_url = plan["api_url"], plan["web_url"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    detach = args.detach

    def give_up(server: Server, what: str, fix: str = "", with_log: bool = True) -> int:
        rep.fail(what, _few(server.tail(), 25) if with_log else "", fix=fix)
        for s in reversed(servers):
            s.stop()
        print("\nNot started.")
        return 1

    # -- API ------------------------------------------------------------------------------
    rep.section(f"Starting the API on {bind}:{args.api_port}")
    api_cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", bind,
               "--port", str(args.api_port)]
    if args.reload:
        api_cmd += ["--reload", "--reload-dir", "api", "--reload-dir", "engine"]
    api = Server("API", "api", api_cmd, ROOT, env, RUN_DIR / "api.log", detach)
    servers.append(api)
    ok, why = wait_http(f"http://127.0.0.1:{args.api_port}/health", api, 90)
    if not ok:
        return give_up(api, f"The API did not start: {why}", fix=diagnose_api_log(api.log_text()))
    log = api.log_text()
    if "NO DATABASE CONFIGURED" in log and not args.allow_memory_db:
        return give_up(api, "The API came up on the in-memory TEST backend")
    if "DATABASE UNREACHABLE" in log:
        return give_up(api, "The API can't reach its database")
    bad = foreign_on(args.api_port, api)
    if bad:
        return give_up(api, f"Port {args.api_port} is ALSO served by "
                       + "; ".join(describe(d) for d in bad),
                       fix="a browser may reach that one instead: python tools/start_app.py --stop-others",
                       with_log=False)
    ok_pub, why_pub = True, ""
    if public not in ("localhost", "127.0.0.1"):
        status_code, body = http_get(f"http://{public}:{args.api_port}/health")
        ok_pub, why_pub = status_code == 200, (f"HTTP {status_code}" if status_code else body)
    if ok_pub:
        rep.ok(f"API answers at {api_url} (pid {api.proc.pid})")
    else:
        rep.warn(f"API answers on 127.0.0.1 but not at {public}: {why_pub}",
                 fix="check --public-host; allow python.exe through Windows Firewall")

    # -- web app --------------------------------------------------------------------------
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    web_env = dict(env, VITE_API_URL=api_url)
    if lan and not re.fullmatch(r"[\d.]+|\[?[0-9a-fA-F:]+\]?", public):
        # Vite 6+ answers "Blocked request. This host is not allowed" to a Host header naming
        # a machine it doesn't know (IP addresses always pass); this adds the one given
        web_env["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"] = public
    if detach:
        web_env["NO_COLOR"] = "1"        # Vite colours output on Windows even into a file
    if args.prod:
        rep.section("Building the web app (vite build)")
        rc = subprocess.call([tools["node"], str(vite), "build"], cwd=str(WEB), env=web_env)
        bundles = list((WEB / "dist" / "assets").glob("*.js"))
        if rc != 0 or not any(api_url in b.read_text(encoding="utf-8", errors="replace")
                              for b in bundles):
            return give_up(api, "vite build failed, or its bundle does not name the API URL",
                           fix="look at the build output above", with_log=False)
        rep.ok(f"Built web-app/dist for {api_url} (no type check - `npm run build` does that)")
        web_cmd = [tools["node"], str(vite), "preview", "--host", bind,
                   "--port", str(args.web_port), "--strictPort"]
    else:
        # --force: Vite re-bundles its dependency cache instead of trusting node_modules/.vite
        web_cmd = [tools["node"], str(vite), "--host", bind, "--port", str(args.web_port),
                   "--strictPort", "--force"]
    rep.section(f"Starting the web app on {bind}:{args.web_port}")
    web = Server("Web app", "web", web_cmd, WEB, web_env, RUN_DIR / "web.log", detach)
    servers.append(web)
    ok, why = wait_http(f"http://127.0.0.1:{args.web_port}/", web, 90,
                        want=lambda s, b: s == 200 and 'id="root"' in b)
    if not ok:
        return give_up(web, f"The web app did not start: {why}", fix="see logs/start-app/web.log")
    bad = foreign_on(args.web_port, web)
    if bad:
        return give_up(web, f"Port {args.web_port} is ALSO served by "
                       + "; ".join(describe(d) for d in bad),
                       fix="a browser may reach that one - the old UI: "
                           "python tools/start_app.py --stop-others", with_log=False)
    if not args.prod:
        status_code, body = http_get(f"http://127.0.0.1:{args.web_port}/src/lib/http.ts", timeout=30)
        served = served_api_url(body) if status_code == 200 else None
        if served != api_url:
            return give_up(web, f"The web app calls {served or '?'}, not {api_url}",
                           fix="VITE_API_URL did not reach Vite - see logs/start-app/web.log")
    if lan:                                  # the address other machines use, Host header included
        status_code, body = http_get(f"{web_url}/", timeout=10)
        if status_code != 200:
            rep.warn(f"The web app answers on 127.0.0.1 but not at {web_url}: "
                     + (f"HTTP {status_code}" if status_code else body),
                     "Vite blocks a Host it doesn't know" if status_code == 403 else "",
                     fix="check --public-host; allow node.exe through Windows Firewall")
    rep.ok(f"Web app answers at {web_url} (pid {web.proc.pid}) and calls {api_url}")

    save_state({
        "started_at": dt.datetime.now().isoformat(timespec="seconds"), "root": str(ROOT),
        "branch": code.get("branch"), "sha": code.get("sha"), "full_sha": code.get("full_sha"),
        "api": {"pid": api.proc.pid, "port": args.api_port, "host": bind, "url": api_url},
        "web": {"pid": web.proc.pid, "port": args.web_port, "host": bind, "url": web_url,
                "mode": "prod" if args.prod else "dev"},
        "database": db.get("dsn"), "detached": detach,
    })
    code_s = f"{code.get('branch')} @ {code.get('sha')}" if code else "not a git checkout"
    db_s = (f"{db.get('dsn')} - {db.get('projects')} project(s), {db.get('users')} user(s)"
            if db.get("dsn") else "in-memory TEST backend (nothing is saved)")
    bar = "-" * 72
    print(f"\n{bar}\n ArtiFex is running   (code: {code_s})\n")
    print(f"   Open       {web_url}")
    if lan:
        print(f"              (this machine: http://localhost:{args.web_port})")
    print(f"   API        {api_url}   (docs: http://{public}:{args.api_port}/docs)")
    print(f"   Database   {db_s}")
    print("   Sign in    a new database has admin@aspice.dev / admin")
    print("\n   A tab that was already open: reload it with Ctrl+Shift+R, or use a private window.")
    print(f"   Logs       {_rel(RUN_DIR / 'api.log')}, {_rel(RUN_DIR / 'web.log')}")
    if lan:
        print("   Other machines can't open it? Allow node.exe and python.exe through Windows Firewall.")
    if detach:
        print("   Stop       python tools/start_app.py --stop")
        print(bar)
        return 0
    print("   Stop       Ctrl+C here")
    print(bar + "\n", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(web_url if lan else f"http://localhost:{args.web_port}")

    while True:
        time.sleep(0.5)
        for s in servers:
            if s.proc.poll() is not None:
                print(f"\n{s.name} stopped (exit code {s.proc.returncode}) - it crashed, or was "
                      "stopped from outside (--stop, another start, Task Manager). Last lines:")
                for line in s.tail(20):
                    print(f"  {line}")
                for other in servers:
                    other.stop()
                clear_state(own_pids={x.proc.pid for x in servers})
                return 1


# ---------------------------------------------------------------------------
# --status / --stop
# ---------------------------------------------------------------------------

def _ports(args, state: dict) -> dict:
    """Ports given on the command line, else the ones the last start used, else the defaults."""
    return {"API": args.api_port or (state.get("api") or {}).get("port") or DEFAULT_API_PORT,
            "Web app": args.web_port or (state.get("web") or {}).get("port") or DEFAULT_WEB_PORT}


def status(args) -> int:
    if psutil is None:
        print('psutil is not installed:  pip install psutil')
        return 1
    state = load_state()
    info = code_info()
    print(f"Folder     {ROOT}")
    if info:
        print(f"Code       {info['branch']} @ {info['sha']}  ({info['date']})  {info['subject']}")
    if state:
        print(f"Started    {state.get('started_at')} by this tool, from "
              f"{state.get('branch')} @ {state.get('sha')}")
        if info and state.get("full_sha") and state["full_sha"] != info["full_sha"]:
            print("  !! The code changed (git) since then - restart: python tools/start_app.py")
    problems = 0
    for role, port in _ports(args, state).items():
        found = listeners(port)
        if not found:
            print(f"\n{role} :{port}   not running")
            continue
        for d in found:
            addrs = ", ".join(d.get("addrs") or [])
            print(f"\n{role} :{port}   {describe(d)}  on {addrs}")
            if d["cmd"]:
                print(f"  {d['cmd'][:200]}")
            host = _url_host((d.get("addrs") or ["127.0.0.1"])[0])
            if role == "API" and d["kind"] == "api":
                st, _ = http_get(f"http://{host}:{port}/health")
                print(f"  health      {'ok' if st == 200 else f'NO ANSWER ({st})'}")
                try:
                    envv = psutil.Process(d["pid"]).environ()
                    dsn = envv.get("DATABASE_URL", "")
                    if dsn:
                        from_env = re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)
                        print(f"  database    {from_env}  (its DATABASE_URL)")
                    else:
                        print("  database    from engine/config/config.local.json (no DATABASE_URL)")
                except psutil.Error:
                    pass
                # what the API process itself imports (runs are fresh subprocesses)
                newest, where = newest_mtime([ROOT / "api", ROOT / "engine" / "core",
                                              ROOT / "engine" / "incremental"], (".py",))
                if d["started"] and newest > d["started"] + 1 and "--reload" not in d["cmd"]:
                    problems += 1
                    print(f"  !! OLD CODE: {_rel(where)} changed {_ago(newest)}, after this API started"
                          f" ({_ago(d['started'])}).\n     The API does not reload - restart it.")
                if not d["ours"]:
                    problems += 1
                    print("  !! Runs from ANOTHER folder than this one")
            if role == "Web app" and d["kind"] == "web":
                st, body = http_get(f"http://{host}:{port}/src/lib/http.ts", timeout=10)
                if st == 200 and served_api_url(body):
                    print(f"  calls API   {served_api_url(body)}")
                elif st == 200:             # vite preview answers every path with the page
                    urls = sorted({u for b in (WEB / "dist" / "assets").glob("*.js")
                                   for u in re.findall(r"https?://[\w.\-\[\]:]+/api/v1",
                                                       b.read_text(encoding="utf-8", errors="replace"))})
                    print(f"  calls API   {', '.join(urls) or '?'}   (a built copy: web-app/dist)")
                else:
                    st2, _ = http_get(f"http://{host}:{port}/")
                    print(f"  page        {'ok' if st2 == 200 else f'NO ANSWER ({st2})'}"
                          + ("  (a built copy - vite preview)" if st2 == 200 else ""))
                if not d["ours"]:
                    problems += 1
                    print("  !! Runs from ANOTHER folder than this one - it shows THAT folder's UI")
                shadows = find_web_shadows(WEB / "src")
                for f, fd in shadows:
                    problems += 1
                    print(f"  !! {_rel(f)} hides {_rel(fd)}/ - the old page shows")
    ports = set(_ports(args, state).values())
    others = [s for s in app_servers() if not set(s["ports"]) & ports]
    if others:
        print("\nAlso running:")
        for s in others:
            print(f"  {describe(s)} on port(s) {', '.join(map(str, s['ports']))}")
    if problems:
        print(f"\n{problems} problem(s) - restart cleanly with: python tools/start_app.py")
    return 1 if problems else 0


def stop(args) -> int:
    if psutil is None:
        print('psutil is not installed:  pip install psutil')
        return 1
    state = load_state()
    victims: dict = {}
    for port in _ports(args, state).values():
        for d in listeners(port):
            if d["kind"] in ("api", "web"):
                victims[d["pid"]] = d
            elif d["pid"]:
                print(f"Port {port} is held by {describe(d)} - not this app's, left alone")
    for key in ("api", "web"):
        pid = (state.get(key) or {}).get("pid")
        if pid and psutil.pid_exists(pid) and pid not in victims:
            d = proc_info(pid)
            if d["kind"] in ("api", "web"):
                victims[pid] = d
    if args.stop_others:
        for s in app_servers():
            victims.setdefault(s["pid"], s)
    if not victims:
        print("Nothing of this app is running on those ports.")
        clear_state()
        return 0
    for d in victims.values():
        print(f"stopping {describe(d)}")
        kill_tree(d["pid"])
    clear_state()
    others = [s for s in app_servers() if s["pid"] not in victims]
    for s in others:
        print(f"still running (another port): {describe(s)} on {', '.join(map(str, s['ports']))}"
              "  - add --stop-others")
    print("Stopped.")
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="start_app", description=__doc__.split("\n\n")[0],
        epilog=__doc__.split("\n\n", 1)[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true", help="show what runs now, and what is wrong with it")
    g.add_argument("--stop", action="store_true", help="stop the servers")
    g.add_argument("--check", action="store_true", help="run the checks; start and stop nothing")
    p.add_argument("--api-port", type=int, help=f"default {DEFAULT_API_PORT}")
    p.add_argument("--web-port", type=int, help=f"default {DEFAULT_WEB_PORT}")
    p.add_argument("--lan", action="store_true",
                   help="let other machines open it: listen on all interfaces, and point the web "
                        "app at this machine's address instead of localhost")
    p.add_argument("--public-host", metavar="HOST",
                   help="the name/IP other machines use for this one (implies --lan)")
    p.add_argument("--database-url", metavar="DSN", help="the API's database (default: "
                   "DATABASE_URL, else config.local.json)")
    p.add_argument("--prod", action="store_true",
                   help="build web-app/dist afresh and serve that (faster pages) instead of the dev server")
    p.add_argument("--reload", action="store_true",
                   help="restart the API when its code changes (a restart stops running analyses)")
    p.add_argument("--detach", action="store_true",
                   help="leave the servers running in the background and return")
    p.add_argument("--pull", action="store_true", help="git pull --ff-only first")
    p.add_argument("--no-install", action="store_true", help="never run npm install")
    p.add_argument("--stop-others", action="store_true",
                   help="also stop this app's servers on OTHER ports / from other folders")
    p.add_argument("--allow-memory-db", action="store_true",
                   help="start even when the API would use the in-memory test backend")
    p.add_argument("--open", action="store_true", help="open the web app in the browser")
    p.add_argument("-y", "--yes", action="store_true",
                   help="don't ask: stop running analyses / unrecognised node or python servers")
    return p


def _interrupt(*_):
    raise KeyboardInterrupt


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace", line_buffering=True)   # type: ignore[attr-defined]
        except Exception:                                           # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    # Ctrl+Break (Windows) and SIGTERM stop both servers the way Ctrl+C does
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), _interrupt)
            except (ValueError, OSError):
                pass
    if args.status:
        return status(args)
    if args.stop:
        return stop(args)
    args.api_port = args.api_port or DEFAULT_API_PORT
    args.web_port = args.web_port or DEFAULT_WEB_PORT
    return start(args)


if __name__ == "__main__":
    raise SystemExit(main())
