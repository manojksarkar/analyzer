"""The server's own `jobs` settings (complex mode): each scenario runs under values of its own, and
the API this test runs is restarted with them (`complex.manage_api`, jst_core.Ctx.use_jobs) --
config.local.json's `jobs` block, docs/design/JOB_SCHEDULING_DESIGN.md §12. What is days or
minutes on a real server is a part of one here, so a scenario lasts minutes: `keepFinishedDays`
0.002 (about three minutes), `pausedDays` 0.003 (C04, about four), `interruptedAfterMinutes` 2
(C03, the least the server takes).

Against an API the test does not run, a scenario whose values that server does not have is
skipped, saying so.
"""
from __future__ import annotations

import time

from jst_core import ENDED, StopScenario, epoch, ids, scenario, short


def _free(ctx, key):
    if ctx.preview(key).get("answer") != "start":
        raise StopScenario("the server runs other generations: this scenario needs a free slot",
                           skip=True)


def _pause(ctx, key, job_id, what="generation"):
    """Job `job_id`, running, paused once its Phase 2 began; its state -- None when it ended
    first."""
    j = ctx.wait_job(key, job_id, ("running",) + ENDED, phase=2, what=what)
    if j.get("status") != "running":
        return None
    ctx.act(key, job_id, "pause")
    j = ctx.wait_job(key, job_id, ("paused",) + ENDED, timeout=900, what="pausing")
    return j if j.get("status") == "paused" else None


def _slot_message(job, running, cap):
    return (job.get("current_activity") == "Waiting for a free server slot"
            and "%d of %d" % (running, cap) in (job.get("activity_detail") or ""))


# ---------------------------------------------------------------------------
@scenario("C12", "One generation at a time on the server (maxGenerations 1)", mode="complex",
          reqs=("REQ-JS-05", "REQ-JS-13", "REQ-JS-16", "REQ-JS-23", "REQ-JS-24", "REQ-JS-28",
                "REQ-JS-31", "REQ-JS-35"),
          needs=("jobs",), uses=("A", "B", "C", "D"), jobs={"maxGenerations": 1})
def c12(ctx):
    """With a cap of one: another project's generation waits for the server's slot, and says
    so, as the Run dialog does before it is submitted; the command line is refused, the server
    full. A paused job gives the slot up: the project that has waited longest starts. Its resume
    then waits for the slot, and takes it before a generation that waited longer."""
    c = ctx.c
    _free(ctx, "A")
    a = ctx.submit("A", "cap1", scope="long")
    c.check("the first generation starts", a.code == 202 and a.status == "running", a.brief(),
            reqs=("REQ-JS-05",))
    b = ctx.submit("B", "cap1-b")
    jb = ctx.job("B", b.job_id) if b.job_id else {}
    c.check("another project's generation waits for the server's slot: 'Waiting for a free "
            "server slot', 1 of 1", b.code == 202 and b.status == "queued"
            and _slot_message(jb, 1, 1),
            (b.brief(), jb.get("current_activity"), jb.get("activity_detail")),
            reqs=("REQ-JS-05", "REQ-JS-35"))
    pv = ctx.preview("C")
    c.check("the Run dialog of a third project says it would wait for a server slot",
            pv.get("answer") == "wait" and "free server slot" in (pv.get("message") or "")
            and "1 of 1" in (pv.get("message") or ""), pv, reqs=("REQ-JS-31",))
    time.sleep(1.5)                                 # C's place is after B's
    cc = ctx.submit("C", "cap1-c")
    c.check("... and once submitted, it waits", cc.code == 202 and cc.status == "queued",
            cc.brief(), reqs=("REQ-JS-05",))
    if ctx.lacks("cli") is None:
        run = ctx.cli_generate("D", "cap1-cli")
        rc, out = run.wait(300), run.output()
        c.check("the command line is refused: 'Refused: 1 of 1 generations run on this server' "
                "(exit 2)", rc == 2 and "1 of 1 generations run on this server" in out,
                (rc, short(out[-600:], 600)), reqs=("REQ-JS-28", "REQ-JS-35"))
    else:
        c.skip("the command line, refused", ctx.lacks("cli"), reqs=("REQ-JS-28",))
    c.step("pause the running generation")
    ja = _pause(ctx, "A", a.job_id)
    if ja is None:
        raise StopScenario("the generation ended before it could be paused")
    jb = ctx.wait_job("B", b.job_id, ("running",) + ENDED, timeout=120, what="B")
    jc = ctx.job("C", cc.job_id)
    c.check("paused, it gives up the slot: the project that waited longest starts, the other "
            "still waits", jb.get("status") in ("running", "complete")
            and jc.get("status") == "queued", (jb.get("status"), jc.get("status")),
            reqs=("REQ-JS-13", "REQ-JS-24", "REQ-JS-16"))
    r = ctx.act("A", a.job_id, "resume")
    ja = ctx.job("A", a.job_id)
    if jb.get("status") == "running":
        c.check("its resume waits for the slot, and says so",
                r.code == 200 and ja.get("status") == "paused"
                and "free server slot" in (ja.get("current_activity") or ""),
                (r.brief(), ja.get("status"), ja.get("current_activity")),
                reqs=("REQ-JS-23", "REQ-JS-35"))
    else:
        c.warn("B ended before the resume could be seen waiting", jb.get("status"))
    ja = ctx.wait_job("A", a.job_id, ("running",) + ENDED, timeout=ctx.timeout,
                      what="resumed A")
    jc = ctx.job("C", cc.job_id)
    c.check("the slot free, the resume takes it -- before the generation that waited longer",
            ja.get("status") in ("running", "complete") and jc.get("status") == "queued",
            (ja.get("status"), jc.get("status")), reqs=("REQ-JS-23", "REQ-JS-05"))
    ja = ctx.wait_done("A", a.job_id, what="resumed A")
    c.check("the resumed generation completes", ja.get("status") == "complete",
            ja.get("error_message"), reqs=("REQ-JS-23",))
    jc = ctx.wait_job("C", cc.job_id, ("running",) + ENDED, timeout=180, what="C")
    c.check("then the last one starts", jc.get("status") in ("running", "complete"),
            jc.get("status"), reqs=("REQ-JS-16",))


# ---------------------------------------------------------------------------
@scenario("C13", "Three generations at once (maxGenerations 3)", mode="complex",
          reqs=("REQ-JS-05", "REQ-JS-16", "REQ-JS-30"), needs=("jobs",),
          uses=("A", "B", "C", "D"), jobs={"maxGenerations": 3})
def c13(ctx):
    """With a cap of three: three projects' generations run at the same time, a fourth waits
    for a slot -- '3 of 3' -- and starts when one of them ends."""
    c = ctx.c
    _free(ctx, "A")
    runs = {k: ctx.submit(k, "cap3", scope="long") for k in ("A", "B", "C")}
    c.check("three projects' generations run at once",
            all(a.code == 202 and a.status == "running" for a in runs.values()),
            [a.brief() for a in runs.values()], reqs=("REQ-JS-05",))
    d = ctx.submit("D", "cap3-d")
    jd = ctx.job("D", d.job_id) if d.job_id else {}
    c.check("a fourth waits: 'Waiting for a free server slot', 3 of 3",
            d.code == 202 and d.status == "queued" and _slot_message(jd, 3, 3),
            (d.brief(), jd.get("current_activity"), jd.get("activity_detail")),
            reqs=("REQ-JS-05",))
    if ctx.admin.superuser:
        cap = ctx.all_queues().get("cap") or {}
        c.check("a super admin's queues say 3 of 3 slots taken",
                cap.get("max_generations") == 3 and cap.get("running_generations") == 3, cap,
                reqs=("REQ-JS-30",))

    def one_ended():
        for k, a in runs.items():
            if ctx.job(k, a.job_id).get("status") in ENDED:
                return k
        return None
    first = ctx.wait_for("one of the three to end", one_ended, ctx.timeout)
    if first is None:
        raise StopScenario("none of the three generations ended")
    jd = ctx.wait_job("D", d.job_id, ("running",) + ENDED, timeout=120, what="D")
    c.check("one ends (%s): the fourth starts" % first, jd.get("status") in ("running", "complete"),
            jd.get("status"), reqs=("REQ-JS-16", "REQ-JS-05"))


# ---------------------------------------------------------------------------
@scenario("C14", "A restart that holds nothing (startQueuedAfterRestart true)", mode="complex",
          reqs=("REQ-JS-14", "REQ-JS-16", "REQ-JS-18", "REQ-JS-19"),
          needs=("jobs", "own_api"), uses=("A",), jobs={"startQueuedAfterRestart": True})
def c14(ctx):
    """With startQueuedAfterRestart true the API restarts with a generation running and two
    waiting: nothing is held -- no hold in the record, no notice -- a new job waits as any, and
    the waiting ones start by themselves, in their order, when the running one ends."""
    c = ctx.c
    _free(ctx, "A")
    ctx.set_limits("A", generation_limit=5)
    try:
        run = ctx.submit("A", "restart-run", scope="long")
        w1, w2 = ctx.submit("A", "kept-1"), ctx.submit("A", "kept-2")
        if [a.code for a in (run, w1, w2)] != [202] * 3:
            raise StopScenario("could not set up: %s" % ([a.brief() for a in (run, w1, w2)],))
        ctx.wait_job("A", run.job_id, ("running",) + ENDED, what="generation")
        bg = ctx.background_run("A", run.job_id, run.version_id)
        if bg is None or ctx.own_api.beneath(bg["pid"]):
            raise StopScenario("the run is not in the background (JOB_DETACH off?): a restart "
                               "stops it", skip=True)
        restarted = time.time()
        ctx.restart_api()
        # The scheduler's first round, which holds when the setting is false, comes in seconds.
        seen = set()
        deadline = time.time() + 40
        while time.time() < deadline:
            seen.update(w.get("status") for w in ctx.lane("A").get("waiting") or [])
            time.sleep(2)
        waiting = ctx.lane("A").get("waiting") or []
        c.check("after the restart the waiting jobs are not held: they wait, in their order",
                "held" not in seen and ids(waiting)[:2] == [w1.job_id, w2.job_id]
                and all(w.get("status") == "queued" for w in waiting),
                {"statuses seen": sorted(s for s in seen if s),
                 "waiting": [(w.get("job_id"), w.get("status")) for w in waiting]},
                reqs=("REQ-JS-14", "REQ-JS-18"))
        late = [e for e in ctx.events("A") if e.get("kind") == "held"
                and (epoch(e.get("at")) or 0) >= restarted - 5]
        c.check("the record has no hold", not late, late[:2], reqs=("REQ-JS-18",))
        told = [n for n in ctx.notices(since=restarted) if n.get("project_id") == ctx.pid("A")
                and n.get("type") == "jobs_held"]
        c.check("nobody is told of held jobs", not told, told[:1], reqs=("REQ-JS-18",))
        new = ctx.submit("A", "after-restart")
        c.check("a job submitted now waits as any, not held",
                new.code == 202 and new.status == "queued", new.brief(), reqs=("REQ-JS-18",))
        jr = ctx.wait_done("A", run.job_id, what="carried on")
        c.check("the running generation carried on through the restart and completes",
                jr.get("status") == "complete", jr.get("error_message"), reqs=("REQ-JS-19",))
        j1 = ctx.wait_job("A", w1.job_id, ("running",) + ENDED, timeout=180, what="first waiting")
        j2 = ctx.job("A", w2.job_id)
        c.check("the waiting ones start by themselves, the oldest first",
                j1.get("status") in ("running", "complete") and j2.get("status") == "queued",
                (j1.get("status"), j2.get("status")), reqs=("REQ-JS-16", "REQ-JS-18"))
    finally:
        ctx.drain("A")
        ctx.set_limits("A", generation_limit=3)


# ---------------------------------------------------------------------------
KEEP_DAYS = 0.002


@scenario("C15", "Old job records go (keepFinishedDays 0.002, about three minutes)",
          mode="complex", reqs=("REQ-JS-33", "REQ-JS-34"), needs=("jobs",), uses=("B",),
          jobs={"keepFinishedDays": KEEP_DAYS})
def c15(ctx):
    """With keepFinishedDays a few minutes: a removed job, a cancelled one and a finished update
    stay for that long, then go with their record; the job that made a version stays as long as
    the version does -- an update reads how the version was made from it. NOTE: the server
    prunes the whole database's ended jobs this old, not the test's alone -- a test database."""
    c = ctx.c
    keep = KEEP_DAYS * 24 * 3600
    v = ctx.need_versions("B", 1)[0]
    made = next((d.get("job") for d in ctx.done.get("B") or [] if d["id"] == v), None)
    _free(ctx, "B")
    c.step("end three jobs: an update completed, a generation cancelled, one removed")
    upd = ctx.reexport("B", v, {"scope": "all"})
    g1, g2 = ctx.submit("B", "keep-1"), ctx.submit("B", "keep-2")
    if [a.code for a in (upd, g1, g2)] != [202] * 3:
        raise StopScenario("could not set up: %s" % ([a.brief() for a in (upd, g1, g2)],))
    ctx.act("B", g2.job_id, "cancel")
    ctx.wait_job("B", g1.job_id, ("running",) + ENDED, what="generation")
    ctx.act("B", g1.job_id, "cancel")
    ended = {}
    for what, a in (("update", upd), ("cancelled", g1), ("removed", g2)):
        j = ctx.wait_job("B", a.job_id, ENDED, what=what)
        ended[a.job_id] = (what, epoch(j.get("completed_at")) or time.time())
    c.check("just ended, all three are still there",
            all(ctx.admin.call("GET", ctx.P("B", "/jobs/%s" % j)).status_code == 200
                for j in ended), list(ended), reqs=("REQ-JS-34",))
    gone_at = {}
    limit = 2 * keep + 150                         # twice the days, and a sweep's minute
    c.step("wait up to %d s for them to go" % limit)
    deadline = max(t for _, t in ended.values()) + limit
    while time.time() < deadline and len(gone_at) < len(ended):
        for j in ended:
            if j not in gone_at and ctx.admin.call(
                    "GET", ctx.P("B", "/jobs/%s" % j)).status_code == 404:
                gone_at[j] = time.time()
                c.note("%s job %s gone %d s after it ended" % (
                    ended[j][0], j, gone_at[j] - ended[j][1]))
        time.sleep(10)
    early = {ended[j][0]: int(t - ended[j][1]) for j, t in gone_at.items()
             if t - ended[j][1] < keep - 10}
    c.check("each goes once keepFinishedDays (%d s) has passed, by twice that -- never before"
            % keep, len(gone_at) == len(ended) and not early,
            {"gone after (s)": {ended[j][0]: int(t - ended[j][1]) for j, t in gone_at.items()},
             "still there": [ended[j][0] for j in ended if j not in gone_at],
             "too early": early}, reqs=("REQ-JS-34",))
    left = [e for e in ctx.events("B", limit=500) if e.get("job_id") in gone_at]
    c.check("their record goes with them", not left,
            [(e.get("job_id"), e.get("kind")) for e in left[:5]], reqs=("REQ-JS-33", "REQ-JS-34"))
    if made:
        r = ctx.admin.call("GET", ctx.P("B", "/jobs/%s" % made))
        code, _ = ctx.version("B", v)
        c.check("the job that made the version stays while the version does",
                r.status_code == 200 and code == 200, (r.status_code, code),
                reqs=("REQ-JS-34",))
    else:
        c.skip("the version's own job", "the job that made version %s is not known" % v,
               reqs=("REQ-JS-34",))


# ---------------------------------------------------------------------------
#: Each wrong in its own way; the server takes its default for each, and says so.
BAD = {"maxGenerations": 1.5, "pausedDays": 0, "interruptedAfterMinutes": 1,
       "keepFinishedDays": "90", "startQueuedAfterRestart": "yes", "maxRunning": 4}


@scenario("C16", "Wrong values: the server says so and goes on with its defaults",
          mode="complex", reqs=("REQ-JS-05", "REQ-JS-28", "REQ-JS-35"), needs=("own_api",),
          uses=("A", "B", "C", "D"))
def c16(ctx):
    """config.local.json's jobs block with a wrong value in each key -- a cap of 1.5, no paused
    days, a minute's silence, days as text, yes for true, a key that is no setting: the server
    names each in its log and uses its default (interruptedAfterMinutes its least, 2), so its
    jobs run on: two generations at once, the third waiting. The command line says the same."""
    c = ctx.c
    ctx.use_jobs(raw=BAD)
    got, _ = ctx.own_api.settings()
    log = ctx.own_api.log_text()
    expect = {"maxGenerations": 2, "pausedDays": 7, "interruptedAfterMinutes": 2,
              "keepFinishedDays": 90, "startQueuedAfterRestart": False}
    c.check("the settings read: each wrong value replaced (interruptedAfterMinutes raised to 2)",
            got == expect, got)
    missing = [k for k in BAD if "jobs.%s" % k not in log]
    c.check("the API's log names each wrong value and what it uses instead", not missing,
            {"not named": missing}, reqs=("REQ-JS-35",))
    if ctx.admin.superuser:
        cap = ctx.all_queues().get("cap") or {}
        c.check("the cap is the default, 2", cap.get("max_generations") == 2, cap,
                reqs=("REQ-JS-05",))
    _free(ctx, "A")
    a, b = ctx.submit("A", "bad-a", scope="long"), ctx.submit("B", "bad-b", scope="long")
    cc = ctx.submit("C", "bad-c")
    c.check("its jobs run on: two generations at once, a third waiting",
            a.status == "running" and b.status == "running" and cc.status == "queued",
            [x.brief() for x in (a, b, cc)], reqs=("REQ-JS-05",))
    if ctx.lacks("cli") is None:
        run = ctx.cli_generate("D", "bad-cli")
        rc, out = run.wait(300), run.output()
        c.check("the command line reads the same: 2 of 2, refused -- and names the wrong values",
                rc == 2 and "2 of 2 generations run on this server" in out
                and "jobs.maxGenerations" in out, (rc, short(out[-900:], 900)),
                reqs=("REQ-JS-28", "REQ-JS-35"))
