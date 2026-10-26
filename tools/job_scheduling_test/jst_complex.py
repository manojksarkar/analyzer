"""The complex scenarios: what takes long runs, the LLM, a restart, a process killed, many
requests at once, or the server's own clocks. `--mode complex` (and `all`).

A scenario that needs what this run does not have -- an LLM server, the API run by this test,
short `jobs` settings -- is skipped, and says what would let it run.
"""
from __future__ import annotations

import concurrent.futures
import os
import time
import uuid

from jst_core import (ENDED, REPO_ROOT, StopScenario, body_of, ids, is_sentence, kill_tree,
                      scenario, short)
from jst_docs import check_same_documents


def _free(ctx, key):
    if ctx.preview(key).get("answer") != "start":
        raise StopScenario("the server runs other generations: this scenario needs a free slot",
                           skip=True)


def _max_wait(ctx):
    return float((ctx.cfg.get("complex") or {}).get("max_wait_minutes") or 20)


def _paused(ctx, key, label, *, no_llm=True, scope="long"):
    """A generation of `key`, paused once its Phase 2 began: its job, or None when it ended
    before it could be paused."""
    a = ctx.submit(key, label, scope=scope, no_llm=no_llm)
    if a.code != 202:
        raise StopScenario("could not start: %s" % (a.brief(),))
    limit = ctx.timeout if no_llm else ctx.llm_timeout
    j = ctx.wait_job(key, a.job_id, ("running",) + ENDED, phase=2, what="generation",
                     timeout=limit)
    if j.get("status") != "running":
        return a, None
    ctx.act(key, a.job_id, "pause")
    j = ctx.wait_job(key, a.job_id, ("paused",) + ENDED, timeout=900, what="pausing")
    return a, (j if j.get("status") == "paused" else None)


# ---------------------------------------------------------------------------
@scenario("C01", "Pause during the LLM's descriptions; the same documents as a run never paused",
          mode="complex", reqs=("REQ-JS-22", "REQ-JS-23"), needs=("llm", "docx"), uses=("A",))
def c01(ctx):
    """A generation with the LLM, paused while Phase 2 writes its descriptions, stops within a
    minute or two; resumed, it finishes, the answers already received coming from the cache; a
    second run of the same commit and scope, never paused, makes Word files with the same text."""
    c = ctx.c
    _free(ctx, "A")
    a = ctx.submit("A", "llm-paused", no_llm=False, scope="first")
    if a.code != 202:
        raise StopScenario("could not start: %s" % (a.brief(),))
    ctx.wait_job("A", a.job_id, ("running",) + ENDED, phase=2, what="generation with the LLM",
                 timeout=ctx.llm_timeout)
    asked = time.time()
    ctx.act("A", a.job_id, "pause")
    j = ctx.wait_job("A", a.job_id, ("paused",) + ENDED, timeout=900, what="pausing")
    took = int(time.time() - asked)
    if j.get("status") != "paused":
        c.warn("the run ended (%s) before it could be paused" % j.get("status"))
        return
    c.check("paused during the descriptions, it stops within a minute (%d s)" % took, took <= 60,
            took, warn=took <= 180, reqs=("REQ-JS-22",))
    ctx.act("A", a.job_id, "resume")
    j = ctx.wait_done("A", a.job_id, what="resumed", timeout=ctx.llm_timeout)
    c.check("resumed, it completes", j.get("status") == "complete", j.get("error_message"),
            reqs=("REQ-JS-23",))
    b = ctx.submit("A", "llm-straight", no_llm=False, scope="first")
    k = ctx.wait_done("A", b.job_id, what="never paused", timeout=ctx.llm_timeout)
    if k.get("status") != "complete":
        raise StopScenario("the run never paused did not complete: %s" % k.get("error_message"))
    check_same_documents(ctx, "A", a.version_id, b.version_id, what_a="paused and resumed",
                         what_b="never paused", reqs=("REQ-JS-23",))


# ---------------------------------------------------------------------------
@scenario("C02", "A restart: waiting jobs held, running ones carry on", mode="complex",
          reqs=("REQ-JS-14", "REQ-JS-18", "REQ-JS-19", "REQ-JS-28", "REQ-JS-32", "REQ-JS-33"),
          needs=("own_api", "superuser"), uses=("A", "B"))
def c02(ctx):
    """The API restarts with a generation running and two waiting in project A, none in B: the
    run goes on and is followed again; A's waiting jobs are held, in their order, and A's admins
    told; a new job of A is held too, one of B starts; with A's lane free and its jobs held, the
    command line is refused; a super admin clears one held job and starts the rest, in order."""
    c = ctx.c
    if ctx.server.jobs.get("startQueuedAfterRestart"):
        raise StopScenario("jobs.startQueuedAfterRestart is true on this server: nothing is held",
                           skip=True)
    _free(ctx, "A")
    # A running job, two held and one submitted after the restart: one more than the lane's
    # default limit, which counts the held ones too.
    ctx.set_limits("A", generation_limit=5)
    try:
        _restart(ctx, c)
    finally:
        ctx.drain("A")
        ctx.set_limits("A", generation_limit=3)


def _restart(ctx, c):
    run = ctx.submit("A", "restart-run", scope="long")
    w1, w2 = ctx.submit("A", "held-1"), ctx.submit("A", "held-2")
    if [a.code for a in (run, w1, w2)] != [202] * 3:
        raise StopScenario("could not set up: %s" % ([a.brief() for a in (run, w1, w2)],))
    ctx.wait_job("A", run.job_id, ("running",) + ENDED, what="generation")
    bg = ctx.background_run("A", run.job_id, run.version_id)
    if bg is None:
        raise StopScenario("the generation's process never started: its version's run record "
                           "names none")
    if not ctx.wait_for("the run to leave the API's processes",
                        lambda: not ctx.own_api.beneath(bg["pid"]), 30, poll=2):
        raise StopScenario("web runs are the API's own child processes here, not in the "
                           "background (JOB_DETACH off?): a restart stops them", skip=True)
    c.note("the run's process %s goes on in the background" % bg["pid"])
    ctx.restart_api()
    j = ctx.job("A", run.job_id)
    c.check("the running generation carries on through the restart",
            j.get("status") in ("running", "complete"), j.get("status"), reqs=("REQ-JS-19",))

    def held_now():
        waiting = ctx.lane("A").get("waiting") or []
        return waiting if waiting and all(w.get("status") == "held" for w in waiting) else None
    # The scheduler's first round holds them, a few seconds after the API is up.
    waiting = (ctx.wait_for("A's waiting jobs to be held", held_now, 90, poll=2)
               or ctx.lane("A").get("waiting") or [])
    c.check("A's waiting jobs are held, in their order",
            ids(waiting) == [w1.job_id, w2.job_id]
            and all(w.get("status") == "held" for w in waiting),
            [(w.get("job_id"), w.get("status")) for w in waiting], reqs=("REQ-JS-14", "REQ-JS-18"))
    c.check("each says it is held after a restart",
            all(w.get("current_activity") == "Held after a restart" for w in waiting),
            [w.get("current_activity") for w in waiting], reqs=("REQ-JS-18", "REQ-JS-35"))
    held = [e for e in ctx.events("A") if e.get("kind") == "held"]
    c.check("the record has the holding", len(held) >= 2, len(held), reqs=("REQ-JS-33",))
    pid_a = ctx.pid("A")
    told = [n for n in ctx.notices() if n.get("project_id") == pid_a
            and n.get("type") == "jobs_held"]
    c.check("A's admins are told the jobs are held", bool(told), told[:1], reqs=("REQ-JS-32",))
    late = ctx.submit("A", "held-3")
    c.check("a job submitted to A now is held too", late.code == 202 and late.status == "held"
            and late.message.startswith("Held"), late.brief(), reqs=("REQ-JS-18",))
    other = ctx.submit("B", "after-restart")
    c.check("B, which had nothing waiting, runs what is submitted to it",
            other.code == 202 and other.status == "running", other.brief(), reqs=("REQ-JS-18",))
    jr = ctx.wait_done("A", run.job_id, what="carried on")
    c.check("the generation that ran through the restart completes, and its job says so",
            jr.get("status") == "complete", jr.get("error_message"), reqs=("REQ-JS-19",))
    if ctx.lacks("cli") is None:
        out = ctx.cli_generate("A", "cli-held")
        rc = out.wait(300)
        text = out.output()
        c.check("with A's jobs held, the command line is refused: jobs wait in the lane (exit 2)",
                rc == 2 and "jobs wait in the generation lane of project %s" % pid_a in text,
                (rc, short(text[-600:])), reqs=("REQ-JS-28",))
    else:
        c.skip("the command line, refused", ctx.lacks("cli"), reqs=("REQ-JS-28",))
    r = ctx.admin.ask("POST", "/queues/held", json={"project_id": pid_a, "remove": [w2.job_id]})
    c.check("a super admin clears one held job and starts the rest",
            r.code == 200 and r.data.get("removed") == [w2.job_id]
            and set(r.data.get("released") or []) == {w1.job_id, late.job_id}, r.brief(),
            reqs=("REQ-JS-18",))
    jw = ctx.wait_job("A", w1.job_id, ("running",) + ENDED, timeout=180, what="released")
    behind = ctx.job("A", late.job_id).get("status") if late.job_id else None
    c.check("the released jobs start in their order: the oldest first",
            jw.get("status") in ("running", "complete") and behind == "queued",
            (jw.get("status"), behind), reqs=("REQ-JS-18",))


# ---------------------------------------------------------------------------
@scenario("C03", "A run whose process dies is interrupted", mode="complex",
          reqs=("REQ-JS-20", "REQ-JS-16", "REQ-JS-32", "REQ-JS-35"), needs=("same_machine",),
          uses=("B", "C"))
def c03(ctx):
    """A web run's process killed: the API following it interrupts the job at once and starts
    the next. A command-line run's process killed: nobody follows it, so it is interrupted once
    silent for jobs.interruptedAfterMinutes -- and its version resumes as a job of its own."""
    c = ctx.c
    _free(ctx, "B")
    g = ctx.submit("B", "die", scope="long")
    nxt = ctx.submit("B", "after-death")
    ctx.wait_job("B", g.job_id, ("running",) + ENDED, what="generation")
    run = ctx.background_run("B", g.job_id, g.version_id)
    if run is None:
        raise StopScenario("the generation's process never started: its version's run record "
                           "names none")
    c.step("kill the run's process %s" % run["pid"])
    killed = time.time()
    kill_tree(int(run["pid"]))
    j = ctx.wait_job("B", g.job_id, ENDED, timeout=300, what="killed")
    took = int(time.time() - killed)
    text = j.get("error_message") or ""
    c.check("the job is interrupted at once (%d s), saying why" % took,
            j.get("status") == "interrupted" and is_sentence(text) and took <= 60,
            (j.get("status"), took, short(text, 300)),
            warn=j.get("status") in ("interrupted", "failed"), reqs=("REQ-JS-20", "REQ-JS-35"))
    tag = g.request["version_tag"]
    told = [n for n in ctx.notices() if n.get("type") == "job_interrupted"
            and tag in (n.get("message") or "")]
    c.check("its submitter and the project's admins are told", bool(told), told[:1],
            reqs=("REQ-JS-20", "REQ-JS-32"))
    jn = ctx.wait_job("B", nxt.job_id, ("running",) + ENDED, timeout=180, what="next")
    c.check("the next job starts", jn.get("status") in ("running", "complete"), jn.get("status"),
            reqs=("REQ-JS-16", "REQ-JS-20"))
    minutes = float(ctx.server.jobs.get("interruptedAfterMinutes") or 10)
    if ctx.lacks("cli") is not None:
        c.skip("a command-line run gone silent", ctx.lacks("cli"), reqs=("REQ-JS-20",))
        return
    if minutes + 4 > _max_wait(ctx):
        c.skip("a command-line run gone silent",
               "jobs.interruptedAfterMinutes is %g: longer than this run waits (complex."
               "max_wait_minutes %g) -- set it to 2 on a test server, and restart the API"
               % (minutes, _max_wait(ctx)), reqs=("REQ-JS-20",))
        return
    _free(ctx, "C")
    cli = ctx.cli_generate("C", "cli-die")

    def cli_job():
        for j in ctx.lane("C").get("active") or []:
            if j.get("origin") == "cli":
                return j
        return None
    found = ctx.wait_for("the command line's job", cli_job, 120)
    if found is None:
        raise StopScenario("the command-line run never showed in the lane")
    time.sleep(20)                                  # into its parse: a version with work
    c.step("kill the command-line run")
    cli.kill()
    j = ctx.wait_job("C", found["job_id"], ENDED, timeout=(minutes + 5) * 60,
                     what="silent command-line run")
    c.check("silent for %g minutes, it is interrupted: 'no sign of life'" % minutes,
            j.get("status") == "interrupted"
            and "no sign of life" in (j.get("error_message") or ""),
            (j.get("status"), short(j.get("error_message") or "", 300)), reqs=("REQ-JS-20",))
    vid = j.get("version_id")
    if not vid or ctx.version("C", vid)[0] != 200:
        c.skip("resuming its version", "the run left no version to resume", reqs=("REQ-JS-21",))
        return
    r = ctx.resume_version("C", vid)
    c.check("its version resumes as a job of its own -- not the command line's",
            r.code == 202 and r.job_id and r.job_id != found["job_id"], r.brief(),
            reqs=("REQ-JS-21", "REQ-JS-23"))
    if r.job_id:
        jr = ctx.wait_done("C", r.job_id, what="resume")
        c.check("the resume completes the version", jr.get("status") == "complete",
                jr.get("error_message"), reqs=("REQ-JS-23",))


# ---------------------------------------------------------------------------
@scenario("C04", "A job paused too long is cancelled", mode="complex",
          reqs=("REQ-JS-24", "REQ-JS-25", "REQ-JS-32", "REQ-JS-35"), uses=("A",))
def c04(ctx):
    """A job left paused for jobs.pausedDays is cancelled, saying why; its version, never
    finished, is deleted."""
    c = ctx.c
    days = float(ctx.server.jobs.get("pausedDays") or 7)
    minutes = days * 24 * 60
    if minutes + 3 > _max_wait(ctx):
        raise StopScenario("jobs.pausedDays is %g (%d minutes): longer than this run waits -- set "
                           "it to 0.003 (about 4 minutes) on a test server, and restart the API"
                           % (days, minutes), skip=True)
    _free(ctx, "A")
    a, j = _paused(ctx, "A", "left-paused")
    if j is None:
        raise StopScenario("the run ended before it could be paused", skip=True)
    j = ctx.wait_job("A", a.job_id, ENDED, timeout=(minutes + 4) * 60, what="paused too long")
    c.check("cancelled after its paused days, saying why",
            j.get("status") == "cancelled" and "not resumed" in (j.get("error_message") or ""),
            (j.get("status"), j.get("error_message")), reqs=("REQ-JS-24", "REQ-JS-35"))
    code = ctx.version_gone("A", a.version_id)
    c.check("its unfinished version is deleted", code == 404, code, reqs=("REQ-JS-25",))
    told = [n for n in ctx.notices() if n.get("type") == "job_cancelled"
            and "not resumed" in (n.get("message") or "")]
    c.check("the submitter is told", bool(told), len(told), reqs=("REQ-JS-32",))


# ---------------------------------------------------------------------------
@scenario("C05", "A stopped web run resumes as its own job", mode="complex",
          reqs=("REQ-JS-21", "REQ-JS-23"), needs=("same_machine",), uses=("B",))
def c05(ctx):
    """A web generation killed once its parse is stored keeps its version (it holds work); a
    resume reopens the version's own job, at the back of the lane, and completes the version --
    with the Word files of a run never stopped, what they say and word for word."""
    c = ctx.c
    _free(ctx, "B")
    g = ctx.submit("B", "stop-and-resume", scope="long")
    j = ctx.wait_job("B", g.job_id, ("running",) + ENDED, phase=3, what="generation")
    if j.get("status") != "running":
        raise StopScenario("the generation ended (%s) before its Phase 3 was seen" %
                           j.get("status"))
    run = ctx.background_run("B", g.job_id, g.version_id, timeout=60)
    if run is None:
        raise StopScenario("no process of the run to stop: its version's run record names none")
    c.step("kill the run's process %s in Phase 3" % run["pid"])
    kill_tree(int(run["pid"]))
    j = ctx.wait_job("B", g.job_id, ENDED, timeout=300, what="stopped")
    code, _ = ctx.version("B", g.version_id)
    c.check("stopped after its parse, the job ends and its version is kept (it holds work)",
            j.get("status") in ("interrupted", "failed") and code == 200,
            (j.get("status"), code), reqs=("REQ-JS-21",))
    r = ctx.resume_version("B", g.version_id)
    c.check("a resume reopens the version's own job", r.code == 202 and r.job_id == g.job_id,
            r.brief(), reqs=("REQ-JS-21", "REQ-JS-23"))
    jr = ctx.wait_done("B", g.job_id, what="resumed")
    c.check("the version completes", jr.get("status") == "complete", jr.get("error_message"),
            reqs=("REQ-JS-23",))
    if jr.get("status") != "complete":
        return
    c.step("generate the same once more, never stopped, and compare the Word files")
    s = ctx.submit("B", "never-stopped", scope="long")
    js = ctx.wait_done("B", s.job_id, what="never stopped") if s.code == 202 else {}
    if js.get("status") != "complete":
        raise StopScenario("the run never stopped did not complete: %s" % (
            js.get("error_message") or s.brief(),))
    check_same_documents(ctx, "B", g.version_id, s.version_id, what_a="killed and resumed",
                         what_b="never stopped", reqs=("REQ-JS-21", "REQ-JS-23"))


# ---------------------------------------------------------------------------
@scenario("C06", "Cancelled in any phase, a new version leaves nothing", mode="complex",
          reqs=("REQ-JS-25",), uses=("C",))
def c06(ctx):
    """A new version's generation cancelled in Phase 1, 2 or 3 -- or while paused -- is gone:
    no version, no name taken, no folder."""
    c = ctx.c
    for phase in (1, 2, 3):
        _free(ctx, "C")
        a = ctx.submit("C", "cancel-p%d" % phase, scope="long")
        # Without the LLM, Phase 2 takes seconds: looked at twice a second, not every poll.
        j = ctx.wait_job("C", a.job_id, ("running",) + ENDED, phase=phase, what="generation",
                         poll=0.5)
        if j.get("status") != "running" or (j.get("phase") or 0) != phase:
            c.warn("it was not in Phase %d when looked at (%s, phase %s)" % (
                phase, j.get("status"), j.get("phase")))
            ctx.drain("C")
            continue
        ctx.act("C", a.job_id, "cancel")
        jc = ctx.wait_job("C", a.job_id, ENDED, timeout=180, what="cancelled")
        _gone(ctx, "C", a, "cancelled in Phase %d" % phase, jc)
    a, j = _paused(ctx, "C", "cancel-paused")
    if j is None:
        c.warn("the run ended before it could be paused")
        return
    ctx.act("C", a.job_id, "cancel")
    jc = ctx.wait_job("C", a.job_id, ENDED, timeout=180, what="cancelled")
    _gone(ctx, "C", a, "cancelled while paused", jc)


def _gone(ctx, key, a, when_, job):
    c = ctx.c
    code = ctx.version_gone(key, a.version_id)
    names = [v.get("tag") for v in ctx.versions(key)]
    folder = os.path.join(REPO_ROOT, "workspaces", ctx.pid(key), "versions", a.version_id)
    looked = os.path.isdir(os.path.join(REPO_ROOT, "workspaces", ctx.pid(key)))
    c.check("%s: cancelled, no version, its name free%s" % (
        when_, ", no folder" if looked else ""),
        job.get("status") == "cancelled" and code == 404
        and a.request["version_tag"] not in names and not (looked and os.path.isdir(folder)),
        {"status": job.get("status"), "version": code, "folder left": looked
         and os.path.isdir(folder)}, reqs=("REQ-JS-25",))


# ---------------------------------------------------------------------------
@scenario("C07", "Many requests at the same moment", mode="complex",
          reqs=("REQ-JS-15", "REQ-JS-04", "REQ-JS-09"), uses=("D",))
def c07(ctx):
    """Six submissions to one empty lane at the same moment: one starts, the limit's worth wait,
    the rest are refused -- never two running, never a server error. The same request sent four
    times at once makes one job."""
    c = ctx.c
    key = "D" if "D" in ctx.projects else "C"
    if len(ctx.short_scopes) < 6:
        raise StopScenario("six different short runs are needed: the config has %d components "
                           "and groups" % len(ctx.short_scopes), skip=True)
    _free(ctx, key)
    tags = [ctx.tag("burst") for _ in range(6)]
    scopes = [ctx.scope("short") for _ in range(6)]
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        answers = list(pool.map(lambda i: ctx.submit(key, tag=tags[i], scope=scopes[i]),
                                range(6)))
    codes = [(a.code, a.status if a.code == 202 else a.error) for a in answers]
    running = [a for a in answers if a.code == 202 and a.status == "running"]
    waiting = [a for a in answers if a.code == 202 and a.status == "queued"]
    full = [a for a in answers if a.code == 409 and a.error == "LANE_FULL"]
    c.check("one starts, two wait, three are refused (limit 3) -- no server error",
            len(running) == 1 and len(waiting) == 2 and len(full) == 3, codes,
            reqs=("REQ-JS-15", "REQ-JS-04"))
    lane = ctx.lane(key)
    c.check("the lane runs one job", len(lane.get("active") or []) == 1, lane,
            reqs=("REQ-JS-15",))
    inside = (lane.get("active") or []) + (lane.get("waiting") or [])
    c.check("the lane holds no more jobs than its limit (%d of %s)" % (
        len(inside), lane.get("limit")), len(inside) <= int(lane.get("limit") or 3),
        [(j.get("what"), j.get("status")) for j in inside], reqs=("REQ-JS-04", "REQ-JS-15"))
    ctx.drain(key)
    _free(ctx, key)
    rkey, tag = uuid.uuid4().hex, ctx.tag("same")
    scope = {"type": "group", "names": [ctx.groups[0]]}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        answers = list(pool.map(lambda _i: ctx.submit(key, tag=tag, scope=scope, idem=rkey),
                                range(4)))
    made = {a.job_id for a in answers if a.code == 202}
    ok = all(a.code == 202 or (a.code == 409 and a.error == "VERSION_EXISTS") for a in answers)
    c.check("the same request four times at once: one job, the others its answer or the name's "
            "refusal -- never a server error", ok and len(made) == 1,
            [a.brief() for a in answers], reqs=("REQ-JS-09",))


# ---------------------------------------------------------------------------
@scenario("C08", "The update lane at its limit, first come first served", mode="complex",
          reqs=("REQ-JS-04", "REQ-JS-12"), uses=("B",))
def c08(ctx):
    """With the update limit set to 3, three updates of three versions fill the lane and a
    fourth is refused; they start in the order they came."""
    c = ctx.c
    vids = ctx.need_versions("B", 4)
    ctx.set_limits("B", update_limit=3)
    try:
        ups = [ctx.reexport("B", v, {"scope": "all"}) for v in vids[:3]]
        c.check("three updates: one runs, two wait in order",
                [u.code for u in ups] == [202] * 3 and ups[0].status == "running"
                and [u.position for u in ups[1:]] == [1, 2], [u.brief() for u in ups],
                reqs=("REQ-JS-12",))
        fourth = ctx.reexport("B", vids[3], {"scope": "all"})
        c.check("a fourth is refused: 409 LANE_FULL", fourth.code == 409
                and fourth.error == "LANE_FULL", fourth.brief(), reqs=("REQ-JS-04",))
    finally:
        ctx.set_limits("B", update_limit=10)
    done = [ctx.wait_done("B", u.job_id, what="update") for u in ups if u.job_id]
    starts = [d.get("started_at") for d in done]
    c.check("they complete, started in the order they came",
            all(d.get("status") == "complete" for d in done) and starts == sorted(starts),
            [(d.get("status"), d.get("started_at")) for d in done], reqs=("REQ-JS-12",))


# ---------------------------------------------------------------------------
@scenario("C09", "An incremental chain: each version's baseline chosen when it starts",
          mode="complex", reqs=("REQ-JS-10",), uses=("C",))
def c09(ctx):
    """Three new commits submitted one after another while the first runs: each generation,
    when it starts, takes the version the one before it made as its baseline."""
    c = ctx.c
    ctx.need_versions("C", 1)
    _free(ctx, "C")
    shas = [ctx.sample.add_function("chain-%s-%d" % (ctx.stamp, i)) for i in range(3)]
    jobs = [ctx.submit("C", "chain%d" % i, mode="auto", commit=sha, scope="first")
            for i, sha in enumerate(shas)]
    if [a.code for a in jobs] != [202] * 3:
        raise StopScenario("a submit was refused: %s" % ([a.brief() for a in jobs],))
    done = [ctx.wait_done("C", a.job_id, what="chain") for a in jobs]
    if any(d.get("status") != "complete" for d in done):
        raise StopScenario("a generation did not complete: %s" % (
            [d.get("error_message") for d in done],))
    bases = [ctx.version("C", a.version_id)[1].get("baseline_version_id") for a in jobs]
    c.check("the second's baseline is the first, the third's the second",
            bases[1] == jobs[0].version_id and bases[2] == jobs[1].version_id, bases,
            reqs=("REQ-JS-10",))


# ---------------------------------------------------------------------------
@scenario("C10", "A commit gone before its job starts", mode="complex",
          reqs=("REQ-JS-07", "REQ-JS-21", "REQ-JS-16"), uses=("A",))
def c10(ctx):
    """A generation of a commit that exists when it is submitted but is gone when it starts
    (its branch deleted meanwhile) fails when it starts, saying so, and the next job starts."""
    c = ctx.c
    _free(ctx, "A")
    branch = "jst-gone-%s" % ctx.stamp
    sha = ctx.sample.branch_with_function(branch, "gone-%s" % ctx.stamp)
    blocker = ctx.submit("A", "gone-blocker")
    doomed = ctx.submit("A", "gone", commit=sha)
    after = ctx.submit("A", "after-gone")
    if [a.code for a in (blocker, doomed, after)] != [202] * 3:
        raise StopScenario("could not set up: %s" % ([a.brief() for a in
                                                      (blocker, doomed, after)],))
    c.check("the commit is accepted at submit, while it exists", doomed.status == "queued",
            doomed.brief(), reqs=("REQ-JS-07",))
    ctx.sample.drop_branch(branch)
    c.note("branch %s deleted, its commit %s pruned" % (branch, sha[:10]))
    ctx.act("A", blocker.job_id, "cancel")
    j = ctx.wait_job("A", doomed.job_id, ENDED, what="doomed")
    c.check("checked again when it starts, it fails, saying so",
            j.get("status") == "failed" and is_sentence(j.get("error_message")),
            (j.get("status"), short(j.get("error_message") or "", 300)),
            reqs=("REQ-JS-07", "REQ-JS-21"))
    ja = ctx.wait_job("A", after.job_id, ("running",) + ENDED, timeout=180, what="next")
    c.check("the next job starts", ja.get("status") in ("running", "complete"), ja.get("status"),
            reqs=("REQ-JS-16",))


# ---------------------------------------------------------------------------
@scenario("C11", "An update cancelled half way", mode="complex", reqs=("REQ-JS-25",),
          uses=("B",))
def c11(ctx):
    """An update of out-of-date Word files cancelled while it runs: what it had not finished
    still shows out of date."""
    c = ctx.c
    v = ctx.need_versions("B", 1)[0]
    slots = body_of(ctx.admin.call("GET", ctx.V("B", v, "/slots"), params={
        "slot_kind": "description", "limit": 1000})).get("slots") or []
    by_component = {}
    for s in slots:
        if s.get("shownIn") and s.get("component"):
            by_component.setdefault(s["component"], s)
    picked = list(by_component.values())[:2]
    if len(picked) < 2:
        raise StopScenario("the version has fewer than two components with descriptions",
                           skip=True)
    for s in picked:
        ctx.admin.call("PUT", ctx.V("B", v, "/overrides/slot"), json={
            "slot_kind": "description", "slot_key": s["slotKey"],
            "text": "JST %s: cancelled update of %s." % (ctx.stamp, s["component"])})
    upd = ctx.reexport("B", v, {"scope": "out_of_date"})
    if upd.code != 202:
        raise StopScenario("the update did not start: %s" % (upd.brief(),))
    ctx.wait_job("B", upd.job_id, ("running",) + ENDED, what="update")
    ctx.act("B", upd.job_id, "cancel")
    j = ctx.wait_job("B", upd.job_id, ENDED, timeout=180, what="cancelled update")
    r9 = body_of(ctx.admin.call("GET", ctx.V("B", v, "/export-readiness")))
    if j.get("status") != "cancelled":
        c.warn("the update finished (%s) before the cancel reached it" % j.get("status"))
        return
    c.check("cancelled half way, what it had not finished still shows out of date",
            r9.get("stale") is True, r9, reqs=("REQ-JS-25",))
