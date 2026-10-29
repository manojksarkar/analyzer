"""What both REST test tools run with (tools/job_scheduling_test, tools/incremental_test): the
config, the modes and the choice of scenarios, where the sample copies go, the report's name, and
running one scenario. Nothing here registers a scenario: each tool's entry imports its own.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import traceback

from jst_core import REPO_ROOT, SCENARIOS, StopScenario, StopTest, inside

MODES = {"normal": ("normal",), "complex": ("complex",), "all": ("normal", "complex")}
#: The order the scenarios of the modes run in.
MODE_ORDER = ("normal", "complex", "cli")


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
    """Normal scenarios first, then complex ones, then the command line's, each in its id's
    order."""
    rank = {m: i for i, m in enumerate(MODE_ORDER)}
    return sorted(SCENARIOS, key=lambda sc: (rank.get(sc.mode, len(rank)), sc.sid))


def choose(args, modes=MODES) -> list:
    picked = [sc for sc in ordered() if sc.mode in modes[args.mode]]
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
        if sc.jobs:
            print("              jobs: %s" % json.dumps(sc.jobs))
        print("              %s\n" % sc.doc)


def sample_source(cfg):
    """The SampleCppProject code to copy: `sample.source_dir`, else None -- the repository's."""
    return ((cfg.get("sample") or {}).get("source_dir") or "").strip() or None


def sample_root(cfg, server) -> str:
    """The folder each run's git copy of SampleCppProject goes in, as a new jst-sample-<time>
    folder: `sample.repo_dir` when it is set, else the first repositories.localRoots that does
    not hold the sample code itself -- a copy there would be inside its source -- else the temp
    folder."""
    chosen = ((cfg.get("sample") or {}).get("repo_dir") or "").strip()
    if not chosen:
        source = sample_source(cfg) or os.path.join(REPO_ROOT, "SampleCppProject")
        chosen = next((r for r in server.local_roots if not inside(r, source)),
                      tempfile.gettempdir())
    return os.path.abspath(chosen)


def new_folder(root, name) -> str:
    """`root/name`, or `name-2`, `name-3` ... when it is taken -- two runs started in the same
    second (one per database, side by side) once picked the same sample folder."""
    path, n = os.path.join(root, name), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(root, "%s-%d" % (name, n))
    return path


def outside_problem(cfg, root, server):
    """Why the server will refuse a sample copy in `root`, or None. A server whose
    config.local.json lists repositories.localRoots clones a local repository only from inside
    one of them: POST /projects refuses any other (api/services/local_repos.py)."""
    if not server.local_roots or any(inside(root, r) for r in server.local_roots):
        return None
    listed = [r.replace("\\", "/") for r in server.local_roots]
    chosen = ((cfg.get("sample") or {}).get("repo_dir") or "").strip()
    folder = root.replace("\\", "/") if chosen else "C:/jst"
    first = ("The sample copies go in %s" % folder if chosen else
             "sample.repo_dir is empty, and no folder in that list can hold the sample copies "
             "(a copy may not go inside the SampleCppProject code itself), so they would go in "
             "the temp folder")
    return ("%s -- but the server takes a local repository only from the folders in "
            "repositories.localRoots of %s: %s.\n"
            "%s -- the server reads it on every request, no restart:\n"
            '    "repositories": {"localRoots": [%s]}' % (
                first, server.local_path, ", ".join(listed),
                "Add the copies' folder to that list" if chosen else
                "Set sample.repo_dir to a short folder of your own, e.g. %s, and add it to that "
                "list" % folder,
                ", ".join(json.dumps(r) for r in listed + [folder])))


def report_path(path, mode, stamp) -> str:
    """`path` with the mode and the run's start put before its extension: every run writes reports
    of its own, so a complex run no longer overwrites the normal run's."""
    root, ext = os.path.splitext(path)
    return "%s_%s_%s%s" % (root, mode, stamp, ext)


def run_one(ctx, checks, sc):
    for need in sc.needs:
        why = ctx.lacks_jobs(sc.jobs) if need == "jobs" else ctx.lacks(need)
        if why:
            checks.begin(sc)
            checks.skip("the scenario", why)
            sc.result, sc.why = "SKIP", why
            return
    checks.begin(sc)
    started = time.time()
    try:
        ctx.use_jobs(sc.jobs)               # the API this test runs: the scenario's settings
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
