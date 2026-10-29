#!/usr/bin/env python3
"""Incremental generation, end to end through the REST API.

Makes a project of its own on a git copy of SampleCppProject and generates its first commit in
full: the base version. Then each scenario changes the code as a developer would, on a branch of
its own, and generates that commit twice -- incrementally, built on an earlier version, and in
full. The two must give the same Word files, what they say (tools/doccheck) and word for word: an
incremental generation saves time and never changes a document. Each check names what it shows;
the report gives each its result.

    python tools/incremental_test/incremental_test.py --mode normal
    python tools/incremental_test/incremental_test.py --mode complex

README.md says how to set it up. Exit code: 0 every check passed (warnings allowed), 1 a check
failed, 2 the test could not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(os.path.dirname(HERE), "job_scheduling_test")   # the machinery both share
for _p in (HERE, SHARED):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import inc_scenarios  # noqa: E402 -- registers its scenarios
import jst_report  # noqa: E402
from jst_core import SCENARIOS, Api, Checks, Ctx, SampleRepo, ServerConfig, StopTest, short  # noqa: E402
from jst_run import (MODES, choose, list_scenarios, load_config, new_folder,  # noqa: E402
                     outside_problem, report_path, run_one, sample_root, sample_source)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="Test incremental generation end to end through "
                                             "the REST API (see README.md).")
    ap.add_argument("--mode", choices=sorted(MODES), default="normal",
                    help="normal: the changes made every day; complex: headers, files, the "
                         "narrowed parse, reverts, baselines, corrections, the LLM; all: both")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"),
                    help="the test's JSON config (see config.example.json); default config.json "
                         "here")
    ap.add_argument("--only", help="run only these scenarios, e.g. I02,X01")
    ap.add_argument("--skip", help="leave these scenarios out, e.g. X11")
    ap.add_argument("--list", action="store_true", help="list the scenarios and stop")
    ap.add_argument("--yes", action="store_true", help="do not ask before creating the project")
    ap.add_argument("--keep", action="store_true",
                    help="keep the test project even when cleanup.delete_projects is true")
    ap.add_argument("--log-dir", help="where the downloaded Word files go (default: a temp "
                                      "folder)")
    args = ap.parse_args(argv)
    if args.list:
        list_scenarios()
        return 0
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print("cannot read the config %s: %s\nCopy config.example.json to config.json and fill it "
              "in -- README.md says how." % (args.config, exc), file=sys.stderr)
        return 2
    server = ServerConfig()
    picked = choose(args)
    s = cfg.get("server") or {}
    print("Incremental test -- %s mode, %d scenarios, against %s" % (
        args.mode, len(picked), s.get("base_url")))
    print("This machine's config files say:")
    for line in server.lines():
        print("   " + line)
    if not picked:
        print("no scenario chosen")
        return 2
    why = (outside_problem(cfg, sample_root(cfg, server), server)
           if s.get("same_machine", True) else None)
    if why:
        print("\n" + why, file=sys.stderr)
        return 2
    if not args.yes:
        print("\nIt creates a test project on the server and generates many versions in it. Use "
              "a test server and database, never the review site's.")
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
    ctx = None
    code = 0
    try:
        admin = probe.signin()
        ctx = Ctx(cfg, args, checks, admin, None, server)
        print("signed in as %s" % admin.email)
        dest = new_folder(sample_root(cfg, server), "inc-sample-" + ctx.stamp)
        source = sample_source(cfg)
        print("sample repository: %s, from %s" % (
            dest, source or "the repository's SampleCppProject"))
        ctx.use_sample(SampleRepo.make(dest, source))
        print("creating the test project")
        ctx.create_projects(["A"])
        print("\ngenerating the base version: the sample's first commit, in full")
        base = ctx.submit("A", "base", mode="full", commit=ctx.sha, scope="long")
        if base.code != 202:
            raise StopTest("the base version was refused: %s" % (base.brief(),))
        job = ctx.wait_done("A", base.job_id, what="base version")
        if job.get("status") != "complete":
            raise StopTest("the base version did not complete: %s" % short(
                job.get("error_message") or job.get("status")))
        inc_scenarios.BASE.update(sha=ctx.sha, vid=base.version_id)
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
                print("\ndeleting the test project")
                ctx.delete_projects()

    seconds = int(time.time() - started)
    ran = {sc.sid for sc in picked}
    rows = jst_report.coverage(SCENARIOS, checks.items, ran, reqs=inc_scenarios.REQS,
                               not_here={})
    test = {"title": "Incremental test", "reqs_source": "tools/incremental_test/README.md",
            "mode": args.mode, "server": probe.base, "started": started_at,
            "projects": ctx.projects if ctx else {}, "server_config": server.lines(),
            "logDir": ctx.log_dir if ctx else tempfile.gettempdir(),
            "sampleRepo": ctx.sample.path if ctx and ctx.sample else None}
    jst_report.terminal(test, picked, checks, rows, seconds)
    report = cfg.get("report") or {}
    stamp = dt.datetime.fromisoformat(started_at).strftime("%Y%m%d-%H%M%S")
    written = jst_report.write(
        test, picked, checks, rows, seconds,
        report_path(report.get("json") or "incremental_test_report.json", args.mode, stamp),
        report_path(report.get("markdown") or "incremental_test_report.md", args.mode, stamp))
    for path in written:
        print("report: %s" % path)
    if code:
        return code
    return 1 if checks.counts()["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
