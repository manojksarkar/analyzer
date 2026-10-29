"""The command line in the job queue (`--mode cli`): `analyzer.py generate`, `export`, `reexport`
and `resume` as jobs of their project's lanes -- recorded, refused, past the queue, in the
background, stopped with Ctrl+C, killed, put to sleep, many at once -- each checked through the
API, as the web app shows it (docs/design/JOB_SCHEDULING_DESIGN.md §11: REQ-JS-27..29, and every
requirement a command-line run takes part in).

The command line has no queue (REQ-JS-27): a run starts now or is refused, exit 2, naming the jobs
in the way. Each run is this machine's `analyzer.py` on the API's database; with the API this test
runs (`complex.manage_api`), it reads that API's `jobs` settings too.
"""
from __future__ import annotations

import time

from jst_core import (ENDED, StopScenario, epoch, ids, is_sentence, scenario, seconds_between,
                      short)

#: How a refusal begins (api/services/job_queue.py `_cli_refused`).
BUSY = "Refused: the %s lane of project %s is taken."
WAITING = "Refused: jobs wait in the %s lane of project %s"
FULL = "Refused: %d of %d generations run on this server (jobs.maxGenerations)."


def _free(ctx, *keys):
    for key in keys:
        if ctx.preview(key).get("answer") != "start":
            raise StopScenario("the server runs other generations: this scenario needs a free "
                               "slot", skip=True)


def _job(ctx, key, run, *, timeout=180):
    """The job command-line run `run` recorded in project `key`, as the API has it now -- found
    by the process that recorded it, which its runner names. StopScenario when none comes."""
    def find():
        pid = run.pid()
        if pid is not None:
            for e in ctx.events(key, limit=60):
                d = e.get("detail") or {}
                if (e.get("kind") == "submitted" and d.get("origin") == "cli"
                        and str(d.get("runner") or "").endswith("pid %d" % pid)):
                    ctx.jobs[e["job_id"]] = key
                    return dict(ctx.job(key, e["job_id"]), job_id=e["job_id"])
        return {"_ended": True} if run.done() else None
    found = ctx.wait_for("the command line's job in %s" % key, find, timeout, poll=2)
    if not found or found.get("_ended"):
        raise StopScenario("the command-line run recorded no job (%s) -- does it use the API's "
                           "database? Its output: %s" % (
                               "it ended" if found else "none within %d s" % timeout,
                               short(run.output()[-800:], 800)))
    return found


def _refused(ctx, run, head, *, names=(), reqs=(), what="it is refused"):
    """Check that `run` was refused: exit 2, its message beginning `head`, naming `names`."""
    rc = run.wait(300)
    out = run.output()
    named = [n for n in names if n and n not in out]
    return ctx.c.check("%s: exit 2, '%s'" % (what, head.rstrip(".")),
                       rc == 2 and head in out and not named,
                       {"exit": rc, "not named": named, "output": short(out[-700:], 700)},
                       reqs=reqs)


def _past_parse(ctx, key, job_id, timeout=None):
    """Wait until job `job_id`'s version holds work a resume carries on from -- past its parse --
    so a run stopped now keeps its version. Its version id, or None when the job ended first."""
    def ready():
        j = ctx.job(key, job_id)
        if j.get("status") in ENDED:
            return "ended"
        vid = j.get("version_id")
        if not vid:
            return None
        # A component is `generating` only once the parse and the model are stored (Phase 3).
        states = {c.get("state") for c in ctx.components(key, vid)}
        return vid if states & {"generating", "generated"} else None
    got = ctx.wait_for("the run to get past its parse", ready, timeout or ctx.timeout, poll=2)
    return None if got in (None, "ended") else got


def _other_component(ctx):
    """A component outside the first group -- one a project's first version has no documents of."""
    first = _first_group_names(ctx)
    others = [c for c in ctx.component_ids if c.split(".", 1)[-1] not in first]
    return (others or ctx.component_ids)[-1]


def _first_group_names(ctx):
    for layer in (ctx.cfg.get("projects") or {}).get("architecture_layers") or []:
        for g in layer.get("groups") or []:
            return {c["name"] for c in g.get("components") or []}
    return set()


# ---------------------------------------------------------------------------
@scenario("L01", "Each command is a job of its lane, and its run ends it", mode="cli",
          reqs=("REQ-JS-01", "REQ-JS-14", "REQ-JS-29", "REQ-JS-30", "REQ-JS-32", "REQ-JS-33",
                "REQ-JS-34"), needs=("cli",), uses=("A",))
def l01(ctx):
    """`generate` is the generation lane's running job and `reexport` the update lane's, both at
    once; `export` is a generation-lane job too. Each shows who runs it and where, is in the
    record, is told to the project's admins, and ends with its run: complete, no time waited,
    its run time measured."""
    c = ctx.c
    v = ctx.need_versions("A", 1)[0]
    _free(ctx, "A")
    began = time.time()
    gen = ctx.cli_generate("A", "l01")
    jg = _job(ctx, "A", gen)
    c.check("analyzer.py generate is the generation lane's running job, from the command line, "
            "naming who runs it", jg.get("status") == "running" and jg.get("lane") == "generation"
            and jg.get("origin") == "cli" and (jg.get("runner") or "").startswith("cli "),
            {k: jg.get(k) for k in ("status", "lane", "origin", "runner")},
            reqs=("REQ-JS-01", "REQ-JS-29"))
    upd = ctx.cli("reexport", "--project-id", ctx.pid("A"), "--version-id", v)
    ju = _job(ctx, "A", upd)
    now_g = ctx.job("A", jg["job_id"]).get("status")
    c.check("analyzer.py reexport, meanwhile, is the update lane's: both run at once",
            ju.get("status") == "running" and ju.get("lane") == "update"
            and now_g == "running", (ju.get("status"), ju.get("lane"), now_g),
            reqs=("REQ-JS-01",))
    if ctx.admin.superuser:
        mine = next((p for p in ctx.all_queues().get("projects") or []
                     if p.get("project_id") == ctx.pid("A")), {})
        active = [j.get("job_id") for lane in (mine.get("lanes") or {}).values()
                  for j in lane.get("active") or []]
        c.check("a super admin's queues show both", {jg["job_id"], ju["job_id"]} <= set(active),
                active, reqs=("REQ-JS-30",))
    rcs = [gen.wait(ctx.timeout), upd.wait(ctx.timeout)]
    c.check("both runs end well (exit 0)", rcs == [0, 0],
            (rcs, short(gen.output()[-300:]), short(upd.output()[-300:])))
    comp = _other_component(ctx)
    exp = ctx.cli("export", "--project-id", ctx.pid("A"), "--version-id", v, "--components", comp)
    je = _job(ctx, "A", exp)
    c.check("analyzer.py export is a job of the generation lane", je.get("lane") == "generation",
            {k: je.get(k) for k in ("status", "lane", "mode")}, reqs=("REQ-JS-01",))
    rc = exp.wait(ctx.timeout)
    c.check("the export ends well (exit 0)", rc == 0, short(exp.output()[-400:]))
    ended = {j: ctx.job("A", j) for j in (jg["job_id"], ju["job_id"], je["job_id"])}
    c.check("each job ends with its run: complete",
            all(j.get("status") == "complete" for j in ended.values()),
            {k: (j.get("status"), j.get("error_message")) for k, j in ended.items()},
            reqs=("REQ-JS-29",))
    j = ended[jg["job_id"]]
    waited = seconds_between(j.get("submitted_at"), j.get("started_at"))
    ran = seconds_between(j.get("started_at"), j.get("completed_at"))
    c.check("measured: it waited no time, and ran %s s" % (ran and int(ran)),
            waited is not None and abs(waited) < 2 and ran is not None and ran > 0,
            {k: j.get(k) for k in ("submitted_at", "started_at", "completed_at")},
            reqs=("REQ-JS-34",))
    events = ctx.events("A", limit=200)
    for jid in ended:
        kinds = {e.get("kind") for e in events if e.get("job_id") == jid}
        sub = next((e for e in events if e.get("job_id") == jid
                    and e.get("kind") == "submitted"), {})
        c.check("the record of %s: submitted (from the command line, by whom), started, "
                "completed -- each with its time" % jid,
                {"submitted", "started", "completed"} <= kinds
                and (sub.get("detail") or {}).get("origin") == "cli"
                and all(e.get("at") for e in events if e.get("job_id") == jid),
                sorted(k for k in kinds if k), reqs=("REQ-JS-14", "REQ-JS-33"))
    said = [n for n in ctx.notices(since=began) if n.get("project_id") == ctx.pid("A")
            and n.get("type") == "job_started" and "command line" in (n.get("message") or "")]
    c.check("the project's admins are told a run started from the command line",
            len(said) >= 3 and all(is_sentence(n.get("message")) for n in said),
            [n.get("message") for n in said[:3]], reqs=("REQ-JS-32",))


# ---------------------------------------------------------------------------
@scenario("L02", "Refused: the lane taken, jobs waiting, the server full -- nothing queued",
          mode="cli", reqs=("REQ-JS-02", "REQ-JS-05", "REQ-JS-27", "REQ-JS-28", "REQ-JS-35"),
          needs=("cli", "jobs"), uses=("A", "B", "C"), jobs={"maxGenerations": 1})
def l02(ctx):
    """With one generation running (the server's one slot) and another project's waiting for
    it, each command is refused the way the rule says -- the lane taken (generate, export), jobs
    waiting, the server full, the update lane taken, a project the database lacks -- with exit 2
    and the jobs in the way named; and none of it adds a job anywhere."""
    c = ctx.c
    v = ctx.need_versions("A", 1)[0]
    _free(ctx, "A")
    a = ctx.submit("A", "l02-run", scope="long")
    b = ctx.submit("B", "l02-waits")
    if a.status != "running" or b.status != "queued":
        raise StopScenario("could not set up: %s" % ([a.brief(), b.brief()],))
    pa, pb = ctx.pid("A"), ctx.pid("B")
    _refused(ctx, ctx.cli_generate("A", "l02-busy"), BUSY % ("generation", pa),
             names=(a.job_id, "--ignore-queue"), reqs=("REQ-JS-02", "REQ-JS-28", "REQ-JS-35"),
             what="generate where a job runs: the lane is taken")
    _refused(ctx, ctx.cli("export", "--project-id", pa, "--version-id", v, "--components",
                          _other_component(ctx)), BUSY % ("generation", pa), names=(a.job_id,),
             reqs=("REQ-JS-28",), what="export there too")
    _refused(ctx, ctx.cli_generate("B", "l02-waiting"), WAITING % ("generation", pb),
             names=(b.job_id,), reqs=("REQ-JS-28", "REQ-JS-35"),
             what="generate where a job waits: it would go before it")
    _refused(ctx, ctx.cli_generate("C", "l02-full"), FULL % (1, 1),
             reqs=("REQ-JS-05", "REQ-JS-28", "REQ-JS-35"), what="generate in an idle project: "
             "the server is full")
    nobody = "jst-none-%s" % ctx.stamp
    run = ctx.cli("generate", "--project-id", nobody, "--version-id", ctx.tag("none"),
                  "--branch", "main", "--commit", ctx.sha, "--create-version", "--no-llm",
                  "--full")
    _refused(ctx, run, "Refused: there is no project %s in the database." % nobody,
             names=("onboard",), reqs=("REQ-JS-28", "REQ-JS-35"),
             what="a project the database lacks: onboard it first")
    c.step("the update lane: a web update of v, then the command line's")
    upd = ctx.reexport("A", v, {"scope": "all"})
    if upd.code == 202 and upd.status == "running":
        cli_upd = ctx.cli("reexport", "--project-id", pa, "--version-id", v)
        rc = cli_upd.wait(300)
        out = cli_upd.output()
        if rc == 0:
            c.warn("the web update ended before the command line looked: it ran", short(out[-300:]))
        else:
            c.check("reexport where an update runs: exit 2, the update lane is taken",
                    rc == 2 and BUSY % ("update", pa) in out and upd.job_id in out,
                    (rc, short(out[-600:], 600)), reqs=("REQ-JS-02", "REQ-JS-28"))
    else:
        c.warn("the web update did not start at once", upd.brief())
    stray = [(p.get("project_id"), j.get("job_id")) for p in (ctx.all_queues().get("projects")
                                                             or [])
             for lane in (p.get("lanes") or {}).values() for j in lane.get("waiting") or []
             if j.get("origin") == "cli"] if ctx.admin.superuser else []
    lanes = {k: ids(ctx.lane(k).get("waiting")) for k in ("A", "B", "C")}
    c.check("none of the refused runs added a job: B still waits its own, A and C wait nothing",
            not stray and lanes == {"A": [], "B": [b.job_id], "C": []},
            {"waiting": lanes, "command-line jobs waiting anywhere": stray}, reqs=("REQ-JS-27",))
    helped = ctx.cli("--help")
    helped.wait(120)
    names = [line.split()[0] for line in helped.output().splitlines()
             if line.startswith("    ") and line.split()]
    c.check("analyzer.py has no queue command", names and not [n for n in names if "queue" in n
                                                                   or n in ("jobs", "enqueue")],
            names, reqs=("REQ-JS-27",))


# ---------------------------------------------------------------------------
@scenario("L03", "Past the queue: --ignore-queue", mode="cli",
          reqs=("REQ-JS-05", "REQ-JS-16", "REQ-JS-28", "REQ-JS-33"), needs=("cli", "jobs"),
          uses=("A", "B"), jobs={"maxGenerations": 1})
def l03(ctx):
    """`--ignore-queue` starts a run beside the job the lane is running, past the server's full
    slot -- the super admin's choice -- and the record says so. It counts as any running
    generation: another project's waits until both have ended."""
    c = ctx.c
    _free(ctx, "A")
    a = ctx.submit("A", "l03-run", scope="long")
    if a.status != "running":
        raise StopScenario("could not set up: %s" % (a.brief(),))
    run = ctx.cli_generate("A", "l03-forced", extra=("--ignore-queue",))
    jf = _job(ctx, "A", run)
    active = ids(ctx.lane("A").get("active"))
    c.check("it runs beside the lane's job: two running in one lane",
            jf.get("status") == "running" and {a.job_id, jf["job_id"]} <= set(active),
            active, reqs=("REQ-JS-28",))
    sub = next((e for e in ctx.events("A") if e.get("job_id") == jf["job_id"]
                and e.get("kind") == "submitted"), {})
    c.check("the record says it went past the queue (forced)",
            (sub.get("detail") or {}).get("forced") is True, sub.get("detail"),
            reqs=("REQ-JS-33",))
    b = ctx.submit("B", "l03-b")
    jb = ctx.job("B", b.job_id) if b.job_id else {}
    c.check("it takes a server slot as any generation: another project's waits for one",
            b.status == "queued" and jb.get("current_activity") == "Waiting for a free server slot",
            (b.brief(), jb.get("current_activity"), jb.get("activity_detail")),
            reqs=("REQ-JS-05",))
    rc = run.wait(ctx.timeout)
    c.check("the forced run ends well (exit 0), its job complete",
            rc == 0 and ctx.job("A", jf["job_id"]).get("status") == "complete",
            (rc, short(run.output()[-300:])), reqs=("REQ-JS-28",))
    ja = ctx.wait_done("A", a.job_id, what="web run")
    jb = ctx.wait_job("B", b.job_id, ("running",) + ENDED, timeout=180, what="B")
    last = max(epoch(ja.get("completed_at")) or 0,
               epoch(ctx.job("A", jf["job_id"]).get("completed_at")) or 0)
    c.check("the other project's starts once both have ended",
            jb.get("status") in ("running", "complete")
            and (epoch(jb.get("started_at")) or 0) >= last - 1,
            {"started": jb.get("started_at"), "last end": last}, reqs=("REQ-JS-05", "REQ-JS-16"))


# ---------------------------------------------------------------------------
@scenario("L04", "A command-line run is the project's running job", mode="cli",
          reqs=("REQ-JS-04", "REQ-JS-16", "REQ-JS-22", "REQ-JS-25", "REQ-JS-29", "REQ-JS-31",
                "REQ-JS-35"), needs=("cli",), uses=("A",))
def l04(ctx):
    """While `analyzer.py generate` runs, the Run dialog says a generation would wait; one does,
    behind it, and the lane's limit counts it -- the next is refused, naming it. The web app
    neither pauses nor cancels it: it says where to stop it. When it ends, the job behind starts."""
    c = ctx.c
    _free(ctx, "A")
    run = ctx.cli_generate("A", "l04", scope="project")
    j = _job(ctx, "A", run)
    pv = ctx.preview("A")
    c.check("the Run dialog says a generation would wait, as #1",
            pv.get("answer") == "wait" and pv.get("position") == 1, pv, reqs=("REQ-JS-31",))
    ctx.set_limits("A", generation_limit=2)
    try:
        w1 = ctx.submit("A", "l04-w1")
        c.check("a web generation waits behind it", w1.code == 202 and w1.status == "queued"
                and w1.ahead == [j["job_id"]], w1.brief(), reqs=("REQ-JS-29",))
        w2 = ctx.submit("A", "l04-w2")
        c.check("with a limit of 2, the next is refused -- the command-line run counts, and is "
                "named", w2.code == 409 and w2.error == "LANE_FULL" and j["job_id"] in w2.text,
                w2.brief(), reqs=("REQ-JS-04", "REQ-JS-35"))
    finally:
        ctx.set_limits("A", generation_limit=3)
    for action in ("pause", "cancel"):
        r = ctx.act("A", j["job_id"], action)
        c.check("the web app does not %s it: 409 CLI_RUN, saying where to stop it" % action,
                r.code == 409 and r.error == "CLI_RUN" and "command line" in (
                    r.detail.get("message") or ""), r.brief(),
                reqs=("REQ-JS-22" if action == "pause" else "REQ-JS-25", "REQ-JS-35"))
    rc = run.wait(ctx.timeout)
    jc = ctx.job("A", j["job_id"])
    c.check("the run ends well, and its job with it: complete",
            rc == 0 and jc.get("status") == "complete", (rc, jc.get("status")),
            reqs=("REQ-JS-29",))
    jw = ctx.wait_job("A", w1.job_id, ("running",) + ENDED, timeout=180, what="behind it")
    c.check("the web job behind it starts", jw.get("status") in ("running", "complete"),
            jw.get("status"), reqs=("REQ-JS-16", "REQ-JS-29"))


# ---------------------------------------------------------------------------
@scenario("L05", "Command-line runs take the server's slots", mode="cli",
          reqs=("REQ-JS-05", "REQ-JS-16", "REQ-JS-28", "REQ-JS-31"), needs=("cli", "jobs"),
          uses=("A", "B", "C", "D"), jobs={"maxGenerations": 2})
def l05(ctx):
    """Two command-line generations fill a server of two slots: a web generation of a third
    project waits for a slot, the Run dialog of a fourth says it would, and a third command-line
    run is refused. When one of them ends, the web job starts."""
    c = ctx.c
    _free(ctx, "A", "B")
    ra = ctx.cli_generate("A", "l05-a", scope="project")
    ja = _job(ctx, "A", ra)
    rb = ctx.cli_generate("B", "l05-b", scope="project")
    jb = _job(ctx, "B", rb)
    w = ctx.submit("C", "l05-c")
    jw = ctx.job("C", w.job_id) if w.job_id else {}
    c.check("a web generation of another project waits for a slot: 2 of 2",
            w.status == "queued" and jw.get("current_activity") == "Waiting for a free server slot"
            and "2 of 2" in (jw.get("activity_detail") or ""),
            (w.brief(), jw.get("current_activity"), jw.get("activity_detail")),
            reqs=("REQ-JS-05",))
    pv = ctx.preview("D")
    c.check("the Run dialog of a fourth says it would wait for a slot",
            pv.get("answer") == "wait" and "2 of 2" in (pv.get("message") or ""), pv,
            reqs=("REQ-JS-31",))
    _refused(ctx, ctx.cli_generate("D", "l05-d"), FULL % (2, 2), reqs=("REQ-JS-05", "REQ-JS-28"),
             what="a third command-line run: the server is full")

    def first_end():
        return next((r for r in (ra, rb) if r.done()), None)
    if not ctx.wait_for("a command-line run to end", first_end, ctx.timeout):
        raise StopScenario("neither command-line run ended")
    jw = ctx.wait_job("C", w.job_id, ("running",) + ENDED, timeout=180, what="C")
    c.check("one ends: the web job starts", jw.get("status") in ("running", "complete"),
            jw.get("status"), reqs=("REQ-JS-16",))
    for r, j, key in ((ra, ja, "A"), (rb, jb, "B")):
        r.wait(ctx.timeout)
        c.check("the run of %s ends, its job complete" % key,
                ctx.job(key, j["job_id"]).get("status") == "complete",
                (r.proc.returncode, ctx.job(key, j["job_id"]).get("status")))


# ---------------------------------------------------------------------------
@scenario("L06", "A run that fails, and one stopped with Ctrl+C", mode="cli",
          reqs=("REQ-JS-16", "REQ-JS-21", "REQ-JS-25", "REQ-JS-29", "REQ-JS-35"),
          needs=("cli",), uses=("A", "B"))
def l06(ctx):
    """A run of a commit the repository lacks fails: its job fails, saying why and where to look,
    and the web job behind it starts. A run stopped with Ctrl+C ends its job cancelled, and its
    lane is free at once."""
    c = ctx.c
    _free(ctx, "A")
    bad = ctx.cli_generate("A", "l06-bad", commit="0" * 40)
    jb = _job(ctx, "A", bad)
    w = ctx.submit("A", "l06-after")
    rc = bad.wait(300)
    jb = ctx.wait_job("A", jb["job_id"], ENDED, timeout=120, what="the failed run")
    text = jb.get("error_message") or ""
    c.check("the run fails (exit %s), and its job: 'Failed: analyzer.py generate ended with exit "
            "code ...', then where to look" % rc,
            rc not in (0, 3) and jb.get("status") == "failed"
            and text.startswith("Failed: analyzer.py generate ended with exit code")
            and "\n- " in text, (rc, jb.get("status"), short(text, 300)),
            reqs=("REQ-JS-21", "REQ-JS-29", "REQ-JS-35"))
    if w.code == 202:
        jw = ctx.wait_job("A", w.job_id, ("running",) + ENDED, timeout=180, what="behind it")
        c.check("the web job behind it starts", jw.get("status") in ("running", "complete"),
                jw.get("status"), reqs=("REQ-JS-16", "REQ-JS-21"))
    c.step("a run stopped with Ctrl+C")
    _free(ctx, "B")
    run = ctx.cli_generate("B", "l06-ctrl-c", scope="project")
    j = _job(ctx, "B", run)
    time.sleep(10)
    run.ctrl_c()
    try:
        rc = run.wait(120)
    except Exception:                               # noqa: BLE001 -- it did not stop
        rc = None
    jc = ctx.wait_job("B", j["job_id"], ENDED, timeout=120, what="stopped")
    c.check("Ctrl+C ends its job cancelled: 'Cancelled: stopped with Ctrl+C.'",
            jc.get("status") == "cancelled" and (jc.get("error_message") or "").startswith(
                "Cancelled: stopped with Ctrl+C"),
            (rc, jc.get("status"), short(jc.get("error_message") or "", 200)),
            reqs=("REQ-JS-25", "REQ-JS-29"))
    pv = ctx.preview("B")
    c.check("its lane is free at once", pv.get("answer") == "start", pv, reqs=("REQ-JS-16",))


# ---------------------------------------------------------------------------
@scenario("L07", "In the background (--detach), and through a restart of the API", mode="cli",
          reqs=("REQ-JS-19", "REQ-JS-20", "REQ-JS-29"), needs=("cli",), uses=("C",))
def l07(ctx):
    """`generate --detach` records its job and hands the run to the background: the command ends
    at once, the job runs on and sends its alive signal. The API restarted meanwhile (when this
    test runs it) leaves it alone -- a command-line run is followed by its own signal -- and the
    job ends complete with its run."""
    c = ctx.c
    _free(ctx, "C")
    run = ctx.cli_generate("C", "l07", scope="project", extra=("--detach",))
    jid = _job(ctx, "C", run)["job_id"]
    rc = run.wait(180)
    j = ctx.job("C", jid)
    c.check("the command ends at once (exit 0) and its job runs on in the background",
            rc == 0 and j.get("status") == "running" and j.get("origin") == "cli",
            (rc, j.get("status"), short(run.output()[-300:])), reqs=("REQ-JS-29",))
    first = epoch(j.get("heartbeat_at"))
    if first is None:
        c.skip("its alive signal", "the job shows no heartbeat_at", reqs=("REQ-JS-20",))
    else:
        moved = ctx.wait_for("its alive signal", lambda: (
            (epoch(ctx.job("C", jid).get("heartbeat_at")) or 0) > first
            or ctx.job("C", jid).get("status") in ENDED), 150, poll=10)
        jn = ctx.job("C", jid)
        if jn.get("status") in ENDED:
            c.warn("it ended before its next alive signal", jn.get("status"))
        else:
            c.check("its background run sends the job's alive signal", bool(moved),
                    (j.get("heartbeat_at"), jn.get("heartbeat_at")), reqs=("REQ-JS-20",))
    if ctx.own_api is not None:
        if ctx.job("C", jid).get("status") == "running":
            ctx.restart_api()
            time.sleep(20)
            c.check("the API restarted, the command-line job still runs",
                    ctx.job("C", jid).get("status") in ("running", "complete"),
                    ctx.job("C", jid).get("status"), reqs=("REQ-JS-19",))
        else:
            c.warn("it ended before the API could be restarted")
    else:
        c.skip("through a restart", ctx.lacks("own_api"), reqs=("REQ-JS-19",))
    jd = ctx.wait_job("C", jid, ENDED, what="background run")
    c.check("the job ends with its run: complete", jd.get("status") == "complete",
            (jd.get("status"), short(jd.get("error_message") or "", 300)),
            reqs=("REQ-JS-19", "REQ-JS-29"))


# ---------------------------------------------------------------------------
@scenario("L08", "A run gone silent: killed, or asleep", mode="cli",
          reqs=("REQ-JS-16", "REQ-JS-20", "REQ-JS-21", "REQ-JS-23", "REQ-JS-32", "REQ-JS-35"),
          needs=("cli", "same_machine"), uses=("C", "D"), jobs={"interruptedAfterMinutes": 2})
def l08(ctx):
    """A command-line run killed past its parse: nobody follows it, so once silent for
    jobs.interruptedAfterMinutes its job is interrupted -- 'no sign of life' -- its admins told,
    the web job behind it started; `analyzer.py resume` finishes its version as a job of its own.
    A run put to sleep is interrupted the same; woken, it finishes, and its job takes the end it
    really had."""
    c = ctx.c
    minutes = float(ctx.server.jobs.get("interruptedAfterMinutes") or 10)
    wait_max = float((ctx.cfg.get("complex") or {}).get("max_wait_minutes") or 20)
    if minutes + 4 > wait_max:
        raise StopScenario("jobs.interruptedAfterMinutes is %g: longer than this run waits "
                           "(complex.max_wait_minutes %g) -- run with complex.manage_api true"
                           % (minutes, wait_max), skip=True)
    _free(ctx, "C")
    run = ctx.cli_generate("C", "l08-killed", scope="project")
    j = _job(ctx, "C", run)
    vid = _past_parse(ctx, "C", j["job_id"])
    if vid is None:
        raise StopScenario("the run ended before it got past its parse")
    behind = ctx.submit("C", "l08-behind")
    c.step("kill the command-line run")
    killed = time.time()
    run.kill()
    jk = ctx.wait_job("C", j["job_id"], ENDED, timeout=(minutes + 5) * 60, what="killed run")
    c.check("silent for %g minutes, it is interrupted: 'no sign of life'" % minutes,
            jk.get("status") == "interrupted" and "no sign of life" in (
                jk.get("error_message") or "") and is_sentence(jk.get("error_message")),
            (jk.get("status"), short(jk.get("error_message") or "", 300)),
            reqs=("REQ-JS-20", "REQ-JS-35"))
    told = [n for n in ctx.notices(since=killed) if n.get("type") == "job_interrupted"
            and n.get("project_id") == ctx.pid("C")]
    c.check("the project's admins are told", bool(told), told[:1], reqs=("REQ-JS-32",))
    jw = ctx.wait_done("C", behind.job_id, what="behind it")
    c.check("the web job behind it starts, and completes", jw.get("status") == "complete",
            jw.get("status"), reqs=("REQ-JS-16", "REQ-JS-20"))
    code, _ = ctx.version("C", vid)
    if code != 200:
        c.check("its version, past its parse, is kept for a resume", False, code,
                reqs=("REQ-JS-21",))
    else:
        res = ctx.cli("resume", "--project-id", ctx.pid("C"), "--version-id", vid)
        rid = _job(ctx, "C", res)["job_id"]
        rc = res.wait(ctx.timeout)
        jr = ctx.job("C", rid)
        left = [x.get("name") for x in ctx.components("C", vid)
                if x.get("state") in ("waiting", "generating", "stopped", "failed")]
        c.check("analyzer.py resume finishes the version, as a job of its own",
                rc == 0 and rid != j["job_id"] and jr.get("status") == "complete" and not left,
                (rc, jr.get("status"), {"components not made": left}),
                reqs=("REQ-JS-21", "REQ-JS-23"))
    c.step("a run put to sleep")
    _free(ctx, "D")
    run = ctx.cli_generate("D", "l08-asleep", scope="project")
    j = _job(ctx, "D", run)
    if _past_parse(ctx, "D", j["job_id"]) is None:
        raise StopScenario("the run ended before it got past its parse")
    run.sleep()
    js = ctx.wait_job("D", j["job_id"], ENDED, timeout=(minutes + 5) * 60, what="asleep")
    pv = ctx.preview("D")
    c.check("asleep past the limit, it is interrupted, and its lane is free",
            js.get("status") == "interrupted" and pv.get("answer") == "start",
            (js.get("status"), pv.get("answer")), reqs=("REQ-JS-20",))
    run.wake()
    try:
        rc = run.wait(ctx.timeout)
    except Exception:                               # noqa: BLE001
        rc = None
    jw = ctx.job("D", j["job_id"])
    c.check("woken, it finishes -- and its job takes the end it really had: complete",
            rc == 0 and jw.get("status") == "complete", (rc, jw.get("status")),
            reqs=("REQ-JS-20",))


# ---------------------------------------------------------------------------
@scenario("L09", "Command-line runs at the same moment", mode="cli",
          reqs=("REQ-JS-15", "REQ-JS-28"), needs=("cli",), uses=("A",))
def l09(ctx):
    """Three `analyzer.py generate` of one project started at the same moment: one runs, the
    other two are refused, the lane taken -- never two at once."""
    c = ctx.c
    _free(ctx, "A")
    runs = [ctx.cli_generate("A", "l09-%d" % i) for i in range(3)]
    most = 0
    while not all(r.done() for r in runs):
        most = max(most, sum(1 for j in ctx.lane("A").get("active") or []
                             if j.get("status") == "running"))
        time.sleep(1)
    rcs = sorted(r.proc.returncode for r in runs)
    c.check("one runs, two are refused (exit 2), the lane taken", rcs == [0, 2, 2]
            and sum(1 for r in runs if BUSY % ("generation", ctx.pid("A")) in r.output()) == 2,
            (rcs, [short(r.output()[-200:]) for r in runs if r.proc.returncode == 2]),
            reqs=("REQ-JS-15", "REQ-JS-28"))
    c.check("never two running at once in the lane (the most seen: %d)" % most, most <= 1, most,
            reqs=("REQ-JS-15",))


# ---------------------------------------------------------------------------
@scenario("L10", "Beside a paused web job", mode="cli",
          reqs=("REQ-JS-05", "REQ-JS-23", "REQ-JS-24", "REQ-JS-28"), needs=("cli", "jobs"),
          uses=("A", "B"), jobs={"maxGenerations": 1})
def l10(ctx):
    """A paused web generation keeps its project's lane: the command line's generate there, and
    its resume of that version, are refused, naming the paused job. It does not keep the server's
    one slot: a run of another project starts -- and the paused job's resume waits for it."""
    c = ctx.c
    _free(ctx, "A")
    a = ctx.submit("A", "l10-paused", scope="long")
    ctx.wait_job("A", a.job_id, ("running",) + ENDED, phase=2, what="generation")
    ctx.act("A", a.job_id, "pause")
    ja = ctx.wait_job("A", a.job_id, ("paused",) + ENDED, timeout=900, what="pausing")
    if ja.get("status") != "paused":
        raise StopScenario("it ended before it could be paused")
    pa = ctx.pid("A")
    _refused(ctx, ctx.cli_generate("A", "l10-gen"), BUSY % ("generation", pa),
             names=(a.job_id, "paused"), reqs=("REQ-JS-24", "REQ-JS-28"),
             what="generate where a job is paused: the lane is taken")
    _refused(ctx, ctx.cli("resume", "--project-id", pa, "--version-id", a.version_id),
             BUSY % ("generation", pa), names=(a.job_id,), reqs=("REQ-JS-23", "REQ-JS-28"),
             what="resume of the paused version: resume it from the web app")
    _free(ctx, "B")
    rb = ctx.cli_generate("B", "l10-b", scope="project")
    jb = _job(ctx, "B", rb)
    c.check("a run of another project starts: the paused job holds no server slot",
            jb.get("status") == "running", jb.get("status"), reqs=("REQ-JS-24", "REQ-JS-05"))
    r = ctx.act("A", a.job_id, "resume")
    ja = ctx.job("A", a.job_id)
    c.check("the paused job's resume waits for the slot the command line holds",
            r.code == 200 and ja.get("status") == "paused"
            and "free server slot" in (ja.get("current_activity") or ""),
            (r.brief(), ja.get("status"), ja.get("current_activity")), reqs=("REQ-JS-23",))
    rb.wait(ctx.timeout)
    ja = ctx.wait_done("A", a.job_id, what="resumed")
    c.check("the command-line run ended, it resumes and completes",
            ja.get("status") == "complete" and ctx.job("B", jb["job_id"]).get("status")
            == "complete", (ja.get("status"), ja.get("error_message")), reqs=("REQ-JS-23",))
