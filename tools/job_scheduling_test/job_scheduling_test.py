#!/usr/bin/env python3
"""Job scheduling, end to end through the REST API -- with review & update and incremental runs.

Creates its own projects on a git copy of SampleCppProject, then drives the queue the way the web
app and the command line do: submits, waits, limits, the server cap, priority, pause and resume,
cancel and remove, updates beside generations, a failed job, the command line in the lanes, and
-- in complex mode -- the LLM, a restart, a killed process, many requests at once and the server's
own clocks. Every answer is checked through the API, and the report says which requirement of
docs/spec/JOB_SCHEDULING_SPEC.md each check shows.

    python tools/job_scheduling_test/job_scheduling_test.py --mode normal
    python tools/job_scheduling_test/job_scheduling_test.py --mode complex

README.md in this folder explains the config and every scenario. Exit code: 0 every check passed
(warnings allowed), 1 a check failed, 2 the test could not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import jst_complex  # noqa: E402,F401 -- registers its scenarios
import jst_normal  # noqa: E402,F401 -- registers its scenarios
import jst_report  # noqa: E402
from jst_core import (SCENARIOS, Api, Checks, Ctx, OwnApi, SampleRepo, ServerConfig,  # noqa: E402
                      StopScenario, StopTest, short)

MODES = {"normal": ("normal",), "complex": ("complex",), "all": ("normal", "complex")}


def load_config(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return _no_comments(json.load(fh))


def _no_comments(obj):
    """The config without its `_...` keys -- JSON has no comments of its own."""
    if isinstance(obj, dict):
        return {k: _no_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_no_comments(v) for v in obj]
    return obj


def ordered() -> list:
    """Normal scenarios first, then complex ones, each in its id's order."""
    return sorted(SCENARIOS, key=lambda sc: (sc.mode != "normal", sc.sid))


def choose(args) -> list:
    picked = [sc for sc in ordered() if sc.mode in MODES[args.mode]]
    if args.only:
        wanted = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        picked = [sc for sc in ordered() if sc.sid in wanted]
    if args.skip:
        unwanted = {x.strip().upper() for x in args.skip.split(",") if x.strip()}
        picked = [sc for sc in picked if sc.sid not in unwanted]
    return picked


def list_scenarios():
    for sc in ordered():
        print("%-4s %-8s %s" % (sc.sid, sc.mode, sc.title))
        print("              requirements: %s" % (", ".join(sc.reqs) or "-"))
        if sc.needs:
            print("              needs: %s" % ", ".join(sc.needs))
        print("              %s\n" % sc.doc)


def sample_source(cfg):
    """The SampleCppProject code to copy: `sample.source_dir`, else None -- the repository's."""
    return ((cfg.get("sample") or {}).get("source_dir") or "").strip() or None


def architecture_problem(cfg):
    """Why projects.architecture_layers cannot carry the scenarios, or None."""
    layers = (cfg.get("projects") or {}).get("architecture_layers") or []
    groups = [g for layer in layers for g in layer.get("groups") or []]
    if len(groups) < 3:
        return ("projects.architecture_layers has %d group(s); the scenarios need 3 or more -- "
                "a first group of two or more components, and a last one of its own" % len(groups))
    if any(not g.get("components") for g in groups):
        return "a group in projects.architecture_layers has no components"
    return None


def sample_dir(cfg, server, stamp) -> str:
    """A new folder for this run's git copy of SampleCppProject, so every run has its own: in
    `sample.repo_dir` when it is set, else under the first repositories.localRoots, else the
    temp folder."""
    chosen = ((cfg.get("sample") or {}).get("repo_dir") or "").strip()
    root = chosen or (server.local_roots[0] if server.local_roots else tempfile.gettempdir())
    return os.path.abspath(os.path.join(root, "jst-sample-" + stamp))


def project_count(cfg, mode, cap) -> int:
    pcfg = cfg.get("projects") or {}
    wanted = int(pcfg.get("count") or 0)
    if not wanted:
        wanted = max(3 if mode == "normal" else 4, cap + 1)
    return max(3, min(wanted, int(pcfg.get("max_count") or 6), 26))


def run_one(ctx, checks, sc):
    for need in sc.needs:
        why = ctx.lacks(need)
        if why:
            checks.begin(sc)
            checks.skip("the scenario", why)
            sc.result, sc.why = "SKIP", why
            return
    checks.begin(sc)
    started = time.time()
    try:
        ctx.drain(*sc.uses)
        sc.fn(ctx)
    except StopScenario as exc:
        sc.why = str(exc)
        if exc.skip:
            checks.skip("the scenario", str(exc))
            sc.result = "SKIP"
        else:
            checks.check("the scenario could go on", False, str(exc))
    except (StopTest, KeyboardInterrupt):
        raise
    except Exception as exc:                        # noqa: BLE001 -- report it, go on
        checks.check("the scenario raised %s" % type(exc).__name__, False,
                     traceback.format_exc()[-1500:])
    finally:
        try:
            ctx.drain(*sc.uses)
        except Exception as exc:                    # noqa: BLE001
            checks.note("could not leave %s idle: %s" % (", ".join(sc.uses), exc))
        sc.seconds = int(time.time() - started)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="Test job scheduling end to end through the REST "
                                             "API (see README.md).")
    ap.add_argument("--mode", choices=sorted(MODES), default="normal",
                    help="normal: every requirement once, short runs (about half an hour); "
                         "complex: the long, timed and stressful ones; all: both")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"),
                    help="the test's JSON config (see config.example.json); default config.json "
                         "here")
    ap.add_argument("--only", help="run only these scenarios, e.g. N02,N09")
    ap.add_argument("--skip", help="leave these scenarios out, e.g. N11,C01")
    ap.add_argument("--list", action="store_true", help="list the scenarios and stop")
    ap.add_argument("--yes", action="store_true", help="do not ask before creating projects")
    ap.add_argument("--keep", action="store_true",
                    help="keep the test projects even when cleanup.delete_projects is true")
    ap.add_argument("--log-dir", help="where the command-line runs and the API this test starts "
                                      "write their output (default: a temp folder)")
    ap.add_argument("--make-sample-repo", metavar="DIR",
                    help="only make a git copy of SampleCppProject in DIR, then stop")
    args = ap.parse_args(argv)
    if args.list:
        list_scenarios()
        return 0
    if args.make_sample_repo:
        try:
            source = sample_source(load_config(args.config))
        except (OSError, ValueError):
            source = None
        repo = SampleRepo.make(os.path.abspath(args.make_sample_repo), source)
        print("sample repository: %s\ncommit: %s" % (repo.path, repo.head()))
        return 0
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print("cannot read the config %s: %s\nCopy config.example.json to config.json and fill it "
              "in -- README.md says how." % (args.config, exc), file=sys.stderr)
        return 2
    problem = architecture_problem(cfg)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    server = ServerConfig()
    picked = choose(args)
    s = cfg.get("server") or {}
    print("Job scheduling test -- %s mode, %d scenarios, against %s" % (
        args.mode, len(picked), s.get("base_url")))
    print("This machine's config files say:")
    for line in server.lines():
        print("   " + line)
    if not picked:
        print("no scenario chosen")
        return 2
    if not args.yes:
        print("\nIt creates test projects on the server (and runs analyses in them). Use a test "
              "server and database, never the review site's.")
        try:
            if input("Go on? [y/N] ").strip().lower() not in ("y", "yes"):
                return 2
        except EOFError:
            print("no answer: pass --yes to run without asking", file=sys.stderr)
            return 2

    checks = Checks()
    started = time.time()
    started_at = dt.datetime.now().isoformat(timespec="seconds")
    probe = Api(s.get("base_url"), s.get("email"), s.get("password"),
                timeout=float(s.get("request_timeout_seconds") or 120),
                verify=s.get("verify_tls", True))
    complex_cfg = cfg.get("complex") or {}
    own = None
    ctx = None
    code = 0
    try:
        if args.mode in ("complex", "all") and complex_cfg.get("manage_api"):
            log_dir = args.log_dir or os.path.join(tempfile.gettempdir(), "job-scheduling-test")
            own = OwnApi(probe.root, os.path.join(log_dir, "api"))
            print("starting the API (port %d) -- this test restarts it" % own.port)
            own.start(probe)
        admin = probe.signin()
        dev_cfg = cfg.get("developer") or {}
        dev = None
        if (dev_cfg.get("email") or "").strip():
            dev = Api(s.get("base_url"), dev_cfg["email"], dev_cfg.get("password"),
                      timeout=probe.timeout, verify=probe.verify).signin()
        ctx = Ctx(cfg, args, checks, admin, dev, server)
        ctx.own_api = own
        print("signed in as %s%s%s" % (admin.email, " (super admin)" if admin.superuser else "",
                                       "; developer %s" % dev.email if dev else ""))
        if admin.superuser:
            everything = ctx.all_queues()
            cap = (everything.get("cap") or {})
            ctx.cap = int(cap.get("max_generations") or ctx.cap)
            if cap.get("running_generations"):
                print("note: %d generation(s) of other projects run on this server -- scenarios "
                      "that need a free slot are skipped while it lasts" %
                      cap["running_generations"])
        dest = sample_dir(cfg, server, ctx.stamp)
        source = sample_source(cfg)
        print("sample repository: %s, from %s" % (
            dest, source or "the repository's SampleCppProject"))
        ctx.use_sample(SampleRepo.make(dest, source))
        print("an incremental change goes into %s" % ctx.sample.change_file)
        keys = [chr(ord("A") + i) for i in range(project_count(cfg, args.mode, ctx.cap))]
        print("creating %d projects (the server's cap is %d)" % (len(keys), ctx.cap))
        ctx.create_projects(keys)
        for sc in picked:
            run_one(ctx, checks, sc)
    except StopTest as exc:
        print("\nthe test cannot go on: %s" % exc, file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        print("\nstopped (Ctrl+C) -- tidying up and reporting what ran", file=sys.stderr)
        code = 2
    finally:
        if ctx is not None and ctx.projects:
            try:
                ctx.drain(*ctx.projects)
            except Exception as exc:                # noqa: BLE001
                print("could not stop every test job: %s" % short(str(exc)))
            if (cfg.get("cleanup") or {}).get("delete_projects") and not args.keep:
                print("\ndeleting the test projects")
                ctx.delete_projects()
        if own is not None:
            own.stop()

    seconds = int(time.time() - started)
    ran = {sc.sid for sc in picked}
    rows = jst_report.coverage(SCENARIOS, checks.items, ran)
    test = {"mode": args.mode, "server": probe.base, "started": started_at,
            "projects": ctx.projects if ctx else {}, "server_config": server.lines(),
            "logDir": ctx.log_dir if ctx else None,
            "sampleRepo": ctx.sample.path if ctx and ctx.sample else None}
    jst_report.terminal(test, picked, checks, rows, seconds)
    report = cfg.get("report") or {}
    written = jst_report.write(test, picked, checks, rows, seconds,
                               report.get("json") or "job_scheduling_test_report.json",
                               report.get("markdown") or "job_scheduling_test_report.md")
    for path in written:
        print("report: %s" % path)
    if code:
        return code
    return 1 if checks.counts()["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
