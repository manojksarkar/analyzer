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
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import jst_complex  # noqa: E402,F401 -- registers its scenarios
import jst_normal  # noqa: E402,F401 -- registers its scenarios
import jst_report  # noqa: E402
from jst_core import (SCENARIOS, Api, Checks, Ctx, OwnApi, SampleRepo,  # noqa: E402
                      ServerConfig, StopTest, short)
from jst_run import (MODES, choose, list_scenarios, load_config,  # noqa: E402
                     outside_problem, report_path, run_one, sample_root, sample_source)

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


def project_count(cfg, mode, cap) -> int:
    pcfg = cfg.get("projects") or {}
    wanted = int(pcfg.get("count") or 0)
    if not wanted:
        wanted = max(3 if mode == "normal" else 4, cap + 1)
    return max(3, min(wanted, int(pcfg.get("max_count") or 6), 26))


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
    # This machine's config.local.json is the server's when the test runs on its machine: a
    # sample copy the server would refuse stops the test here, before anything is created.
    why = (outside_problem(cfg, sample_root(cfg, server), server)
           if s.get("same_machine", True) else None)
    if why:
        print("\n" + why, file=sys.stderr)
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
        dest = os.path.join(sample_root(cfg, server), "jst-sample-" + ctx.stamp)
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
    stamp = dt.datetime.fromisoformat(started_at).strftime("%Y%m%d-%H%M%S")
    written = jst_report.write(
        test, picked, checks, rows, seconds,
        report_path(report.get("json") or "job_scheduling_test_report.json", args.mode, stamp),
        report_path(report.get("markdown") or "job_scheduling_test_report.md", args.mode, stamp))
    for path in written:
        print("report: %s" % path)
    if code:
        return code
    return 1 if checks.counts()["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
