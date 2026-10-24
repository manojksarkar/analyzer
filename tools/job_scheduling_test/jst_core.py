"""The job scheduling test's machinery: the API client, the checks, and the run's context --
the projects, the sample repository, waiting for jobs, the command line, the API it may run
itself. The scenarios (jst_normal.py, jst_complex.py) use only this module; the entry point is
job_scheduling_test.py, and README.md explains the whole tool.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO_ROOT, "engine")

#: A job's statuses (docs/spec/JOB_SCHEDULING_API_SPEC.md §1).
WAITING = ("queued", "held")
HOLDING = ("running", "paused")
ENDED = ("complete", "failed", "interrupted", "cancelled", "removed")
UTC = dt.timezone.utc


class StopScenario(Exception):
    """A scenario cannot go on: something it needs failed. `skip`: it is not a failure of the
    server -- the scenario needs what this run does not have."""

    def __init__(self, message, *, skip=False):
        super().__init__(message)
        self.skip = skip


class StopTest(Exception):
    """The whole test cannot go on: the server, the sign-in or the projects."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def short(value, limit=300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " ..."


def body_of(response) -> dict:
    try:
        out = response.json()
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def when(text):
    """An ISO time from the API, as an aware datetime; None when there is none."""
    if not text:
        return None
    try:
        t = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def seconds_between(a, b):
    a, b = when(a), when(b)
    return None if a is None or b is None else (b - a).total_seconds()


def ids(items, key="job_id") -> list:
    return [(i or {}).get(key) or (i or {}).get("id") for i in items or []]


def is_sentence(text) -> bool:
    """A message a person can read: words, not a code or a stack trace."""
    text = (text or "").strip()
    return len(text) >= 12 and " " in text and "Traceback" not in text


def _folder_key(path) -> str:
    """A folder as the server compares one (api/services/local_repos.py): no quotes, links
    followed, case folded where the file system folds it, forward slashes."""
    p = str(path).strip().strip('"').strip("'")
    return os.path.normcase(os.path.realpath(p)).replace("\\", "/").rstrip("/")


def inside(path, folder) -> bool:
    """Whether `path` is `folder` or in it."""
    p, f = _folder_key(path), _folder_key(folder)
    return p == f or p.startswith(f + "/")


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
class Checks:
    """Every check, printed as it runs and kept for the report. A check carries the requirements
    it shows (`REQ-JS-nn`); without its own, the scenario's."""

    def __init__(self):
        self.items = []
        self.scenario = None

    def begin(self, sc):
        self.scenario = sc
        print("\n== %s  %s" % (sc.sid, sc.title), flush=True)
        if sc.reqs:
            print("   requirements: %s" % ", ".join(sc.reqs), flush=True)
        if sc.doc:
            print("   %s" % sc.doc.splitlines()[0], flush=True)

    def step(self, text):
        print("   -> %s" % text, flush=True)

    def note(self, text):
        print("         %s" % text, flush=True)

    def _add(self, result, name, detail, reqs):
        sc = self.scenario
        self.items.append({"scenario": sc.sid if sc else "", "check": name, "result": result,
                           "detail": None if detail is None else short(detail, 3000),
                           "reqs": list(reqs if reqs is not None else (sc.reqs if sc else ()))})

    def check(self, name, ok, detail=None, *, reqs=None, warn=False) -> bool:
        result = "PASS" if ok else ("WARN" if warn else "FAIL")
        self._add(result, name, detail, reqs)
        line = "   %s  %s" % (result, name)
        if not ok and detail not in (None, "", [], {}):
            line += "\n         " + short(detail, 600)
        print(line, flush=True)
        return bool(ok)

    def warn(self, name, detail=None, *, reqs=None):
        return self.check(name, False, detail, reqs=reqs, warn=True)

    def skip(self, name, why, *, reqs=None):
        self._add("SKIP", name, why, reqs)
        print("   SKIP  %s -- %s" % (name, why), flush=True)

    def counts(self, items=None) -> dict:
        out = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
        for item in self.items if items is None else items:
            out[item["result"]] += 1
        return out


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------
class Scenario:
    def __init__(self, sid, title, mode, reqs, needs, uses, fn):
        self.sid, self.title, self.mode = sid, title, mode
        self.reqs, self.needs, self.uses, self.fn = tuple(reqs), tuple(needs), tuple(uses), fn
        self.doc = " ".join((fn.__doc__ or "").split())
        self.result, self.seconds, self.why = None, 0, ""


#: Every scenario, in the order they run: jst_normal's, then jst_complex's.
SCENARIOS = []


def scenario(sid, title, *, mode, reqs=(), needs=(), uses=()):
    """Register a scenario. `needs`: what it cannot run without (see Ctx.lacks); `uses`: the
    projects it works in -- each is made idle before it and after it."""
    def wrap(fn):
        SCENARIOS.append(Scenario(sid, title, mode, reqs, needs, uses, fn))
        return fn
    return wrap


# ---------------------------------------------------------------------------
# the API
# ---------------------------------------------------------------------------
class Answer:
    """One answer of the API: its status code and its JSON, and the fields the tests read."""

    def __init__(self, response, request=None):
        self.code = response.status_code
        self.data = body_of(response)
        self.text = response.text
        self.request = request

    @property
    def detail(self) -> dict:
        d = self.data.get("detail")
        return d if isinstance(d, dict) else {}

    @property
    def error(self):
        return self.detail.get("code")

    @property
    def job(self) -> dict:
        j = self.data.get("job")
        return j if isinstance(j, dict) else {}

    @property
    def job_id(self):
        return self.data.get("job_id") or self.job.get("id")

    @property
    def status(self):
        return self.data.get("status") or self.job.get("status")

    @property
    def position(self):
        return self.data.get("position")

    @property
    def message(self):
        return self.data.get("message") or ""

    @property
    def ahead(self):
        return ids(self.data.get("ahead"))

    @property
    def version_id(self):
        return self.data.get("version_id") or self.job.get("version_id")

    def brief(self):
        return (self.code, short(self.data or self.text, 400))


class Api:
    """Signs in, sends requests, and signs in again once when a token has expired."""

    def __init__(self, base_url, email, password, *, timeout=120, verify=True):
        import requests
        from urllib.parse import urlsplit, urlunsplit
        base = (base_url or "http://localhost:8000").rstrip("/")
        parts = urlsplit(base)
        if parts.hostname == "localhost":
            # On Windows "localhost" is tried over IPv6 first, and uvicorn listens on IPv4: two
            # seconds lost by every request on a new connection -- each of them, here.
            base = urlunsplit(parts._replace(netloc=parts.netloc.replace("localhost",
                                                                         "127.0.0.1", 1)))
        self.base = base if base.endswith("/api/v1") else base + "/api/v1"
        self.root = self.base[:-len("/api/v1")]
        self.email, self.password, self.timeout, self.verify = email, password, timeout, verify
        self.http = requests.Session()
        self.token = None
        self.user = {}

    def _send(self, method, path, *, json=None, params=None, headers=None, auth=True):
        url = path if path.startswith("http") else self.base + path
        head = dict(headers or {})
        if auth and self.token:
            head["Authorization"] = "Bearer " + self.token
        # A new connection for every request: a kept-alive one goes stale while a job is
        # followed, and a request sent on it fails although the server never saw it.
        head["Connection"] = "close"
        attempts = 3 if method == "GET" else 1      # a write is never sent twice: it may have landed
        for attempt in range(attempts):
            try:
                return self.http.request(method, url, json=json, params=params, headers=head,
                                         timeout=self.timeout, verify=self.verify)
            except Exception as exc:                # noqa: BLE001 -- say where, then stop
                if not type(exc).__module__.startswith(("requests", "urllib3", "http")):
                    raise
                if attempt + 1 < attempts:
                    time.sleep(1 + attempt)
                    continue
                raise StopScenario("cannot reach %s: %s" % (url, exc)) from None

    def signin(self):
        r = self._send("POST", "/auth/signin",
                       json={"email": self.email, "password": self.password}, auth=False)
        if r.status_code != 200:
            raise StopTest("sign-in as %s failed: %s %s" % (self.email, r.status_code,
                                                            short(r.text)))
        self.token = r.json()["access_token"]
        self.user = body_of(self._send("GET", "/auth/me")).get("user") or {}
        return self

    def call(self, method, path, *, json=None, params=None, headers=None, auth=True):
        r = self._send(method, path, json=json, params=params, headers=headers, auth=auth)
        if r.status_code == 401 and auth and self.token:
            self.signin()
            r = self._send(method, path, json=json, params=params, headers=headers, auth=auth)
        return r

    def ask(self, method, path, **kw) -> Answer:
        return Answer(self.call(method, path, **kw), kw.get("json"))

    @property
    def superuser(self) -> bool:
        return bool(self.user.get("is_superuser"))

    @property
    def uid(self):
        return self.user.get("id")


# ---------------------------------------------------------------------------
# what the server's own config files say -- read, never written
# ---------------------------------------------------------------------------
class ServerConfig:
    """config.defaults.json and config.local.json as this machine has them, read with the
    engine's own reader: the `jobs` block, whether an LLM server is set, the folders a local
    repository may be in, and the database's kind. Nothing secret is kept or printed."""

    def __init__(self):
        for p in (REPO_ROOT, ENGINE):
            if p not in sys.path:
                sys.path.insert(0, p)
        from core import config as c
        self.local_path = c.local_config_path()
        self.found = os.path.isfile(self.local_path)
        local = c._read_jsonc(self.local_path) if self.found else {}
        merged = c.app_config()
        self.jobs = c.jobs_settings()
        self.llm = c.has_llm_server(merged)
        self.llm_model = str((c.llm_server(merged) or {}).get("defaultModel") or "")
        self.llm_text = c.llm_text_wanted(merged)
        views = merged.get("views") or {}
        self.flowcharts = bool((views.get("flowcharts") or {}).get("enabled", True)
                               if isinstance(views.get("flowcharts"), dict)
                               else views.get("flowcharts", True))
        roots = (local.get("repositories") or {}).get("localRoots") or []
        if isinstance(roots, str):                  # the server takes one folder as a string too
            roots = [roots]
        self.local_roots = ([str(r).strip() for r in roots if str(r).strip()]
                            if isinstance(roots, list) else [])
        env = os.environ.get("DATABASE_URL", "").strip()
        db = local.get("db") or {}
        source = env or str(db.get("url") or db.get("driver") or "")
        self.db_kind = ("postgresql" if "postgres" in source else
                        "sqlite" if "sqlite" in source else "not set")
        self.db_from = "DATABASE_URL" if env else ("config.local.json" if db else "-")

    def lines(self):
        j = self.jobs
        return [
            "config.local.json : %s" % (self.local_path if self.found else "not found"),
            "database          : %s (from %s)" % (self.db_kind, self.db_from),
            "LLM server        : %s" % (("set, model %s" % self.llm_model) if self.llm
                                        else "not set: LLM runs are skipped"),
            "jobs              : maxGenerations %s, startQueuedAfterRestart %s, pausedDays %s, "
            "interruptedAfterMinutes %s, keepFinishedDays %s" % (
                j["maxGenerations"], j["startQueuedAfterRestart"], j["pausedDays"],
                j["interruptedAfterMinutes"], j["keepFinishedDays"]),
            "local repositories: %s" % (", ".join(self.local_roots) or "any folder"),
        ]


# ---------------------------------------------------------------------------
# the sample repository the server clones
# ---------------------------------------------------------------------------
class SampleRepo:
    """A git copy of SampleCppProject that the server can clone -- made by this run, so its
    commits are this run's to add to: a new function (an incremental change), or a branch
    without a component (a run that stops before the parse)."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.change_file = None         # where add_function writes, relative (Ctx.use_sample)

    @classmethod
    def make(cls, dest, source=None):
        """Copy `source` -- the SampleCppProject code, the repository's own when None -- into a
        new git repository at `dest`. A `.git` in the source is left out: the copy is this run's,
        and the source is never changed."""
        src = os.path.abspath(source or os.path.join(REPO_ROOT, "SampleCppProject"))
        if not os.path.isdir(src):
            raise StopTest("the sample code %s is not a folder (sample.source_dir)" % src)
        dest = os.path.abspath(dest)
        if os.path.normcase(dest + os.sep).startswith(os.path.normcase(src + os.sep)):
            raise StopTest("the sample copy %s would be inside its source %s: set "
                           "sample.repo_dir to a folder outside it" % (dest, src))
        if os.path.isdir(dest) and os.listdir(dest):
            raise StopTest("%s exists and is not empty" % dest)
        shutil.copytree(src, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", ".flowchart_cache"))
        repo = cls(dest)
        repo.git("init", "-q")
        repo.git("symbolic-ref", "HEAD", "refs/heads/main")
        repo.git("add", "-A")
        repo.commit("SampleCppProject")
        return repo

    def git(self, *args) -> str:
        done = subprocess.run(["git", "-C", self.path, *args], capture_output=True, text=True,
                              shell=(os.name == "nt"))
        if done.returncode != 0:
            raise StopScenario("git %s: %s" % (" ".join(args), short(done.stderr)))
        return done.stdout.strip()

    def commit(self, message) -> str:
        self.git("-c", "user.email=jst@example.com", "-c", "user.name=job-scheduling-test",
                 "commit", "-q", "-m", message)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def first_source(self, folders):
        """The first C++ source file in `folders` (relative paths), in name order; None when
        they have none."""
        for rel in folders:
            for dirpath, dirnames, files in os.walk(os.path.join(self.path, rel)):
                dirnames.sort()
                for name in sorted(files):
                    if name.endswith((".cpp", ".cc", ".cxx")):
                        return os.path.relpath(os.path.join(dirpath, name), self.path)
        return None

    def add_function(self, label) -> str:
        """A commit on main that adds a function to the first group's first C++ file -- what an
        incremental run of that group picks up."""
        path = os.path.join(self.path, self.change_file)
        name = "jst_" + "".join(ch if ch.isalnum() else "_" for ch in label)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\nint %s(int x)\n{\n    return x + %d;\n}\n" % (name, len(label)))
        self.git("add", "-A")
        return self.commit("job scheduling test: %s" % name)

    def branch_with_function(self, branch, label) -> str:
        """A commit on a branch of its own that adds a function; main is left as it was."""
        self.git("checkout", "-q", "-b", branch)
        try:
            sha = self.add_function(label)
        finally:
            self.git("checkout", "-q", "main")
        return sha

    def branch_without(self, branch, rel_dir) -> str:
        """A commit on a branch of its own with `rel_dir` deleted; main is left as it was."""
        self.git("checkout", "-q", "-b", branch)
        try:
            self.git("rm", "-r", "-q", rel_dir)
            sha = self.commit("job scheduling test: without %s" % rel_dir)
        finally:
            self.git("checkout", "-q", "main")
        return sha

    def drop_branch(self, branch):
        """The branch and its commits gone for good, as if it never was."""
        self.git("branch", "-D", branch)
        self.git("reflog", "expire", "--expire=now", "--all")
        self.git("gc", "-q", "--prune=now")


# ---------------------------------------------------------------------------
# processes on this machine: the command line, the API this run may own
# ---------------------------------------------------------------------------
def kill_one(pid):
    """Stop one process -- not its children: a background run the API started goes on."""
    try:
        import psutil
        psutil.Process(pid).kill()
    except Exception:                               # noqa: BLE001 -- gone already
        pass


def kill_tree(pid):
    """Stop a process and everything beneath it -- a run cut short, as a crash would."""
    try:
        import psutil
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except Exception:                       # noqa: BLE001
                pass
        proc.kill()
    except Exception:                               # noqa: BLE001
        pass


def pid_alive(pid) -> bool:
    """Whether process `pid` exists on this machine -- True when this cannot be told."""
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:                               # noqa: BLE001 -- no psutil: believe the record
        return True


class CliRun:
    """`python analyzer.py ...` on this machine, in the background; its output in a log file."""

    def __init__(self, args, log_dir):
        os.makedirs(log_dir, exist_ok=True)
        self.args = list(args)
        self.log_path = os.path.join(log_dir, "cli-%s-%s.log" % (
            args[0], dt.datetime.now().strftime("%H%M%S-%f")))
        env = dict(os.environ)
        env.pop("ANALYZER_JOB_ID", None)
        self.log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen([sys.executable, os.path.join(REPO_ROOT, "analyzer.py"),
                                      *self.args], cwd=REPO_ROOT, stdout=self.log,
                                     stderr=subprocess.STDOUT, env=env, shell=(os.name == "nt"))

    def done(self) -> bool:
        return self.proc.poll() is not None

    def wait(self, timeout) -> int:
        try:
            self.proc.wait(timeout=timeout)
        finally:
            self.log.flush()
        return self.proc.returncode

    def output(self) -> str:
        self.log.flush()
        with open(self.log_path, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def kill(self):
        kill_tree(self.proc.pid)
        self.proc.wait(timeout=30)
        self.log.close()


class OwnApi:
    """The API, run by this test so it can be restarted (complex mode, `complex.manage_api`):
    `python -m uvicorn api.main:app` from the repository, with this shell's environment, on the
    host and port of `server.base_url` -- the address the test sends its requests to. Stopping it
    stops that process only -- the runs it started in the background go on, as they do when a
    server restarts."""

    def __init__(self, root, log_dir):
        from urllib.parse import urlsplit
        parts = urlsplit(root)
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.host = parts.hostname if parts.hostname not in (None, "localhost",
                                                              "127.0.0.1") else None
        self.log_dir, self.proc, self.log = log_dir, None, None

    def _pid(self):
        """The uvicorn process itself: through a shell on Windows, the shell's child."""
        if self.proc is None:
            return None
        try:
            import psutil
            for child in psutil.Process(self.proc.pid).children():
                if "python" in (child.name() or "").lower():
                    return child.pid
        except Exception:                           # noqa: BLE001
            pass
        return self.proc.pid

    def beneath(self, pid) -> bool:
        """Whether process `pid` is one of the API's own -- a run started as its child, not in
        the background, which a restart stops."""
        try:
            import psutil
            return int(pid) in {p.pid for p in psutil.Process(self._pid()).children(recursive=True)}
        except Exception:                           # noqa: BLE001
            return False

    def start(self, api: Api, timeout=120):
        os.makedirs(self.log_dir, exist_ok=True)
        self.log = open(os.path.join(self.log_dir, "api-%s.log" % dt.datetime.now().strftime(
            "%H%M%S")), "w", encoding="utf-8", errors="replace")
        where = ["--port", str(self.port)] + (["--host", self.host] if self.host else [])
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", *where],
                                     cwd=REPO_ROOT, stdout=self.log, stderr=subprocess.STDOUT,
                                     shell=(os.name == "nt"))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if api.http.get(api.root + "/health", timeout=5).status_code == 200:
                    return
            except Exception:                       # noqa: BLE001 -- not up yet
                pass
            if self.proc.poll() is not None:
                raise StopTest("the API stopped as it started: see %s" % self.log.name)
            time.sleep(1)
        raise StopTest("the API did not answer within %d s: see %s" % (timeout, self.log.name))

    def stop(self):
        pid = self._pid()
        if pid is not None:
            kill_one(pid)
        if self.proc is not None:
            if self.proc.pid != pid:
                kill_one(self.proc.pid)
            try:
                self.proc.wait(timeout=30)
            except Exception:                       # noqa: BLE001
                pass
        if self.log is not None:
            self.log.close()
        self.proc = None


# ---------------------------------------------------------------------------
# the run's context: projects, versions, and every call a scenario makes
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, cfg, args, checks, admin, dev, server: ServerConfig):
        self.cfg, self.args, self.c, self.admin, self.dev, self.server = (
            cfg, args, checks, admin, dev, server)
        self.stamp = dt.datetime.now().strftime("%m%d-%H%M%S")
        self.prefix = "jst-" + self.stamp
        self.runs = cfg.get("runs") or {}
        self.poll = float(self.runs.get("poll_seconds") or 3)
        self.timeout = float(self.runs.get("job_timeout_minutes") or 30) * 60
        self.llm_timeout = float(self.runs.get("llm_job_timeout_minutes") or 180) * 60
        self.same_machine = bool((cfg.get("server") or {}).get("same_machine", True))
        self.log_dir = os.path.abspath(args.log_dir or os.path.join(
            tempfile.gettempdir(), "job-scheduling-test-" + self.stamp))
        self.groups, self.component_ids, self.folders = [], [], {}   # folders: group -> dirs
        for layer in (cfg.get("projects") or {}).get("architecture_layers") or []:
            for g in layer.get("groups") or []:
                gid = "%s.%s" % (layer["name"], g["name"])
                self.groups.append(gid)
                for comp in g.get("components") or []:
                    self.component_ids.append("%s.%s" % (layer["name"], comp["name"]))
                    self.folders.setdefault(gid, []).extend(comp.get("files") or [])
        # The short runs: one component each -- the shortest there are -- then each group. All
        # different, so jobs waiting side by side never have the same settings (REQ-JS-08).
        self.short_scopes = ([{"type": "component", "names": [c]} for c in self.component_ids]
                             + [{"type": "group", "names": [g]} for g in self.groups])
        self.projects = {}          # "A" -> {"id", "name"}
        self.done = {}              # "A" -> [{"id", "tag", "scope"}]: versions with documents
        self.sample = None
        self.sha = None
        self.cap = int(server.jobs.get("maxGenerations") or 2)
        self.refusals = []          # every refusal seen: its code and message (REQ-JS-35)
        self.endings = []           # every ended job's error_message (REQ-JS-35)
        self.jobs = {}              # job id -> project key, for the report
        self.did = set()            # what the scenarios did -- the record and the notices to find
        self.cli_runs = []
        self.own_api = None
        self._tags = 0
        self._scope_turn = 0

    # ---- what this run can do ---------------------------------------------------------------
    def lacks(self, need):
        """Why this run cannot do `need`, or None when it can."""
        complex_cfg = self.cfg.get("complex") or {}
        if need == "superuser" and not self.admin.superuser:
            return ("%s is not a super admin: python tools/grant_access.py --set-superuser "
                    "--email %s" % (self.admin.email, self.admin.email))
        if need == "developer" and self.dev is None:
            return "no developer user in the config (developer.email)"
        if need == "same_machine" and not self.same_machine:
            return "server.same_machine is false"
        if need == "cli" and not (self.same_machine and (self.cfg.get("cli") or {}).get(
                "enabled", True)):
            return "the command line is not tested (cli.enabled false, or not the server's machine)"
        if need == "llm" and not (self.server.llm and complex_cfg.get("use_llm", True)):
            return "no LLM server in config.local.json, or complex.use_llm is false"
        if need == "own_api" and self.own_api is None:
            return ("the test does not run the API itself (complex.manage_api false) -- a restart "
                    "needs it")
        if need == "docx":
            import importlib.util
            if importlib.util.find_spec("docx") is None:
                return "python-docx is not installed"
        if need.startswith("projects:"):
            want = int(need.split(":", 1)[1])
            if len(self.projects) < want:
                return "needs %d projects, this run has %d" % (want, len(self.projects))
        return None

    # ---- names --------------------------------------------------------------------------------
    def tag(self, label):
        self._tags += 1
        return "%s-%s-%d" % (self.prefix, label, self._tags)

    def scope(self, which="short"):
        """`short`: one component, or one group, a different one each time -- two waiting jobs
        of a project never have the same settings, which would be a duplicate (REQ-JS-08).
        `first`: the first group. `long`: the whole project. A dict: as it is."""
        if isinstance(which, dict) or which is None:
            return which
        if which == "long":
            return None
        if which == "first":
            return {"type": "group", "names": [self.groups[0]]}
        scope = self.short_scopes[self._scope_turn % len(self.short_scopes)]
        self._scope_turn += 1
        return dict(scope)

    def use_sample(self, repo):
        """This run's sample repository. Every folder the config's components name must be in
        it -- a folder missing is a run that fails for nothing -- and a new function goes into
        the first group's first C++ file, what an incremental run of that group picks up."""
        missing = [f for g in self.groups for f in self.folders.get(g, [])
                   if not os.path.isdir(os.path.join(repo.path, f))]
        if missing:
            raise StopTest("the sample code has no %s, which projects.architecture_layers names: "
                           "list only the components your SampleCppProject has" %
                           ", ".join(missing))
        repo.change_file = repo.first_source(self.folders.get(self.groups[0], []))
        if repo.change_file is None:
            raise StopTest("the first group, %s, has no C++ file for an incremental change" %
                           self.groups[0])
        self.sample, self.sha = repo, repo.head()

    def pid(self, key):
        return self.projects[key]["id"]

    def P(self, key, rest=""):
        return "/projects/%s%s" % (self.pid(key), rest)

    def V(self, key, vid, rest=""):
        return "/projects/%s/versions/%s%s" % (self.pid(key), vid, rest)

    # ---- submitting ---------------------------------------------------------------------------
    def submit(self, key, label=None, *, api=None, tag=None, scope="short", no_llm=True,
               mode="full", priority=None, commit=None, reference=None, idem=None) -> Answer:
        """POST /projects/{id}/jobs -- a generation. Short and without the LLM unless asked."""
        body = {"commit_sha": commit or self.sha, "version_tag": tag or self.tag(label or "gen"),
                "mode": mode, "no_llm": bool(no_llm)}
        sc = self.scope(scope)
        if sc is not None:
            body["scope"] = sc
        if priority:
            body["priority"] = priority
        if reference:
            body["reference_version_id"] = reference
        headers = {"Idempotency-Key": idem} if idem else None
        a = (api or self.admin).ask("POST", self.P(key, "/jobs"), json=body, headers=headers)
        if a.job_id:
            self.jobs[a.job_id] = key
        self._seen(a)
        return a

    def _seen(self, a: Answer):
        if a.code >= 400 and a.detail:
            self.refusals.append({"status": a.code, "code": a.detail.get("code"),
                                  "message": a.detail.get("message")})

    def reexport(self, key, vid, body=None, *, api=None, idem=None) -> Answer:
        headers = {"Idempotency-Key": idem} if idem else None
        a = (api or self.admin).ask("POST", self.V(key, vid, "/reexport"), json=body,
                                    headers=headers)
        if a.job_id:
            self.jobs[a.job_id] = key
        self._seen(a)
        return a

    def export(self, key, vid, components) -> Answer:
        a = self.admin.ask("POST", self.V(key, vid, "/documents/generate"),
                           json={"components": list(components)})
        if a.job_id:
            self.jobs[a.job_id] = key
        self._seen(a)
        return a

    def resume_version(self, key, vid) -> Answer:
        a = self.admin.ask("POST", self.V(key, vid, "/resume"))
        if a.job_id:
            self.jobs[a.job_id] = key
        self._seen(a)
        return a

    # ---- acting on a job ----------------------------------------------------------------------
    def act(self, key, job_id, action, *, api=None) -> Answer:
        a = (api or self.admin).ask("POST", self.P(key, "/jobs/%s/%s" % (job_id, action)))
        self._seen(a)
        return a

    def set_priority(self, key, job_id, value, *, api=None) -> Answer:
        a = (api or self.admin).ask("PATCH", self.P(key, "/jobs/%s" % job_id),
                                    json={"priority": value})
        self._seen(a)
        return a

    def set_limits(self, key, *, api=None, **limits) -> Answer:
        a = (api or self.admin).ask("PATCH", self.P(key, "/job-limits"), json=limits)
        self._seen(a)
        return a

    # ---- reading ------------------------------------------------------------------------------
    def job(self, key, job_id) -> dict:
        r = self.admin.call("GET", self.P(key, "/jobs/%s" % job_id))
        if r.status_code != 200:
            raise StopScenario("GET job %s: %s %s" % (job_id, r.status_code, short(r.text)))
        return r.json().get("job") or {}

    def queues(self, key, *, api=None) -> dict:
        r = (api or self.admin).call("GET", self.P(key, "/queues"))
        if r.status_code != 200:
            raise StopScenario("GET queues: %s %s" % (r.status_code, short(r.text)))
        return r.json()

    def lane(self, key, name="generation") -> dict:
        return (self.queues(key).get("lanes") or {}).get(name) or {}

    def preview(self, key, lane="generation") -> dict:
        return body_of(self.admin.call("GET", self.P(key, "/queues/preview"),
                                       params={"lane": lane}))

    def events(self, key, limit=200) -> list:
        return body_of(self.admin.call("GET", self.P(key, "/queues/events"),
                                       params={"limit": limit})).get("events") or []

    def all_queues(self) -> dict:
        r = self.admin.call("GET", "/queues")
        return body_of(r) if r.status_code == 200 else {}

    def notices(self, api=None) -> list:
        return body_of((api or self.admin).call("GET", "/notifications",
                                                params={"all": "true", "limit": 200})
                       ).get("notifications") or []

    def version(self, key, vid):
        r = self.admin.call("GET", self.V(key, vid))
        data = body_of(r)
        return r.status_code, (data.get("version") or data)

    def versions(self, key) -> list:
        return body_of(self.admin.call("GET", self.P(key, "/versions"))).get("versions") or []

    def components(self, key, vid) -> list:
        return body_of(self.admin.call("GET", self.V(key, vid, "/components"))).get(
            "components") or []

    def documents(self, key, vid) -> list:
        return body_of(self.admin.call("GET", self.P(key, "/documents"), params={
            "version_id": vid, "per_page": 100})).get("documents") or []

    def run_of(self, key, vid) -> dict:
        """The version's latest run as GET .../components says it: command, pid, outcome,
        started_at -- and alive, null where the database cannot tell (SQLite)."""
        return body_of(self.admin.call("GET", self.V(key, vid, "/components"))).get("run") or {}

    def background_run(self, key, job_id, vid, timeout=180):
        """The run of job `job_id` once its process is at work, as the version's run record names
        it; None when there is none within `timeout`, or it ended first. A job says "running,
        phase 1" from its checkout on: its process starts after that."""
        began = self.job(key, job_id).get("started_at")
        deadline = time.time() + timeout
        while time.time() < deadline:
            run = self.run_of(key, vid)
            gap = seconds_between(began, run.get("started_at"))
            fresh = gap is None or gap >= -5                # not an earlier run of the version
            if (fresh and run.get("pid") and run.get("outcome") == "running"
                    and run.get("alive") is not False
                    and (not self.same_machine or pid_alive(run["pid"]))):
                return run
            if fresh and run.get("outcome") not in (None, "running"):
                self.c.note("the run ended (%s) before its process was looked at" %
                            run.get("outcome"))
                return None
            time.sleep(self.poll)
        self.c.note("gave up waiting for the run's process after %d s" % timeout)
        return None

    # ---- waiting ------------------------------------------------------------------------------
    def wait_for(self, what, test, timeout, poll=None):
        """Call `test()` until it answers something true; that answer, or None after `timeout`."""
        deadline = time.time() + timeout
        while True:
            got = test()
            if got:
                return got
            if time.time() > deadline:
                self.c.note("gave up waiting for %s after %d s" % (what, timeout))
                return None
            time.sleep(poll or self.poll)

    def wait_job(self, key, job_id, until=ENDED, *, timeout=None, what="job", phase=None,
                 poll=None) -> dict:
        """Follow job `job_id` until its status is in `until` (and, when given, its phase has
        reached `phase`); its last state. StopScenario when it never gets there. `poll`: seconds
        between two looks, when a phase passes too fast for `runs.poll_seconds`."""
        limit = timeout or self.timeout
        started, last = time.time(), None
        while True:
            job = self.job(key, job_id)
            line = "%s %s: %s, phase %s" % (what, job_id, job.get("status"), job.get("phase"))
            if line != last:
                activity = short(job.get("current_activity") or "", 90)
                self.c.note(line + (" -- " + activity if activity else ""))
                last = line
            status = job.get("status")
            if status in until and (phase is None or status != "running"
                                    or (job.get("phase") or 0) >= phase):
                if status in ENDED and job.get("error_message"):
                    self.endings.append({"status": status, "text": job["error_message"]})
                return job
            if status in ENDED and status not in until:
                raise StopScenario("%s %s ended %s, not %s: %s" % (
                    what, job_id, status, "/".join(until), short(job.get("error_message") or "")))
            if time.time() - started > limit:
                raise StopScenario("%s %s is still %s after %d minutes" % (
                    what, job_id, status, limit // 60))
            time.sleep(poll or self.poll)

    def version_gone(self, key, vid, timeout=90) -> int:
        """GET version's status once it answers 404, or its last answer after `timeout`: a job's
        thread deletes an unfinished version just after the job's status has changed."""
        code = [None]

        def gone():
            code[0] = self.version(key, vid)[0]
            return code[0] == 404
        self.wait_for("version %s to go" % vid, gone, timeout, poll=2)
        return code[0]

    def wait_done(self, key, job_id, *, what="job", timeout=None) -> dict:
        """Follow a job to its end; record the version it made when it completed."""
        job = self.wait_job(key, job_id, ENDED, what=what, timeout=timeout)
        if job.get("status") == "complete" and job.get("version_id") and job.get(
                "mode") not in ("reexport", "export"):
            kept = self.done.setdefault(key, [])
            if job["version_id"] not in [v["id"] for v in kept]:
                kept.append({"id": job["version_id"], "tag": job.get("version_tag"),
                             "scope": job.get("scope")})
        return job

    # ---- keeping projects tidy between scenarios -------------------------------------------------
    def drain(self, *keys, timeout=300):
        """Every job of these projects ended: the waiting ones removed, the running and paused
        ones cancelled -- a command-line run this test started is stopped. Then wait for both
        lanes to be empty."""
        for key in keys:
            if key not in self.projects:
                continue
            for name, lane in (self.queues(key).get("lanes") or {}).items():
                for job in (lane.get("waiting") or []) + (lane.get("active") or []):
                    jid = job.get("job_id") or job.get("id")
                    if job.get("origin") == "cli":
                        continue
                    self.admin.call("POST", self.P(key, "/jobs/%s/cancel" % jid))
        for run in self.cli_runs:
            if not run.done():
                run.kill()

        def empty():
            for key in keys:
                if key not in self.projects:
                    continue
                for lane in (self.queues(key).get("lanes") or {}).values():
                    if lane.get("waiting") or lane.get("active"):
                        return False
            return True
        if not self.wait_for("the lanes of %s to empty" % ", ".join(keys), empty, timeout):
            raise StopScenario("the lanes of %s are not empty after %d s" % (
                ", ".join(keys), timeout))

    def need_versions(self, key, n) -> list:
        """At least `n` versions of project `key` with documents: generated now when this run
        has fewer. The first is always a run of the first group only (`scope("first")`)."""
        have = self.done.setdefault(key, [])
        while len(have) < n:
            self.c.step("generating a version of %s to work on (%d of %d)" % (key, len(have) + 1, n))
            a = self.submit(key, "base", scope="first" if not have else "short")
            if a.code != 202:
                raise StopScenario("the version could not be started: %s" % (a.brief(),))
            job = self.wait_done(key, a.job_id, what="generation")
            if job.get("status") != "complete":
                raise StopScenario("the version did not complete: %s" % short(
                    job.get("error_message") or job.get("status")))
        return [v["id"] for v in have]

    # ---- the command line ---------------------------------------------------------------------
    def cli(self, *args) -> CliRun:
        run = CliRun(args, os.path.join(self.log_dir, "cli"))
        self.cli_runs.append(run)
        return run

    def cli_generate(self, key, label, *, extra=(), scope="group:%s"):
        return self.cli("generate", "--project-id", self.pid(key), "--version-id",
                        self.tag(label), "--branch", "main", "--commit", self.sha,
                        "--create-version", "--no-llm", "--full",
                        "--scope", scope % self.groups[0], *extra)

    # ---- the API this run owns ----------------------------------------------------------------
    def restart_api(self):
        self.c.step("restarting the API (the test's own, port %d)" % self.own_api.port)
        self.own_api.stop()
        time.sleep(2)
        self.own_api.start(self.admin)
        self.admin.signin()
        if self.dev is not None:
            self.dev.signin()

    # ---- the projects ---------------------------------------------------------------------------
    def create_projects(self, keys):
        pcfg = self.cfg.get("projects") or {}
        team = [{"email": self.dev.email, "role": "developer"}] if self.dev is not None else []
        for key in keys:
            body = {"name": "%s %s %s" % (pcfg.get("name_prefix") or "JST", key, self.stamp),
                    "client": "job scheduling test", "compliance_standard": "ASPICE_L2",
                    "repo_url": self.sample.path.replace("\\", "/"), "repo_provider": "local",
                    "default_branch": "main", "access_token": None,
                    "build_config": pcfg.get("build_config") or {},
                    "architecture_layers": pcfg.get("architecture_layers") or [], "team": team}
            r = self.admin.call("POST", "/projects", json=body)
            if r.status_code not in (200, 201):
                hint = ""
                if "outside the folders this server allows" in r.text:
                    hint = ("\nThe server takes a local repository only from the folders in "
                            "repositories.localRoots of ITS config.local.json: add the folder "
                            "the sample copies go in (sample.repo_dir, %s) to that list. The "
                            "server reads it on every request -- no restart."
                            % os.path.dirname(self.sample.path).replace("\\", "/"))
                raise StopTest("POST /projects for %s: %s %s%s" % (
                    key, r.status_code, short(r.text, 800), hint))
            project = r.json()["project"]
            self.projects[key] = {"id": project["id"], "name": body["name"]}
            commits = body_of(self.admin.call("GET", self.P(key, "/commits"),
                                              params={"per_page": 100})).get("commits") or []
            if self.sha not in [c.get("sha") for c in commits]:
                raise StopTest("project %s lists no commit %s of %s (it lists %d): the server "
                               "could not read the sample repository. On Windows a long path is "
                               "the usual cause -- keep the API's folder and sample.repo_dir "
                               "short, or git config --global core.longpaths true" % (
                                   key, self.sha, self.sample.path, len(commits)))
            print("   project %s: %s  (%s)" % (key, project["id"], body["name"]), flush=True)

    def delete_projects(self):
        for key, p in self.projects.items():
            r = self.admin.call("DELETE", "/projects/%s" % p["id"])
            print("   project %s (%s): %s" % (key, p["id"], "deleted" if r.status_code == 204
                                             else "%s %s" % (r.status_code, short(r.text))))
