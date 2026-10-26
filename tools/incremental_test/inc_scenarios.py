"""The incremental test's scenarios. Each changes the sample's C++ code as a developer would -- on
a branch of its own from the base commit -- and generates the commit twice: incrementally (mode
auto: built on the nearest earlier version) and in full. The two must give the same Word files,
what they say and word for word: the baseline saves time and never changes a document
(docs/production-redesign/04-incremental-changes-implementation.md §6, §11.1).

`--mode normal`: the changes made every day. `--mode complex`: headers added and deleted, files
deleted and renamed, a function moved, the narrowed parse off, a revert, a chosen baseline that
is not an ancestor, no earlier version at all, review & update corrections, the LLM, a smaller
scope, many changes at once.
"""
from __future__ import annotations

from jst_core import StopScenario, body_of, scenario, short
from jst_docs import check_same_documents, has_words

#: What an incremental generation must do, as the report's requirements.
REQS = {
    "INC-01": "The same Word files as a full generation of the commit",
    "INC-02": "Built on the nearest earlier version; a full generation when there is none",
    "INC-03": "What did not change is reused",
    "INC-04": "A change reaches its callers, in files that did not change",
    "INC-05": "New functions and calls appear",
    "INC-06": "Deleted functions and files leave",
    "INC-07": "Signatures and types reach the interface tables",
    "INC-08": "Globals: a new value, a global newly shared with another unit",
    "INC-09": "Headers, types and macros reach every file that includes them",
    "INC-10": "A header added or deleted",
    "INC-11": "A file renamed, a function moved to another component",
    "INC-12": "The narrowed parse gives what a full parse gives",
    "INC-13": "A chain of versions, each built on the one before",
    "INC-14": "A revert gives the earlier documents back",
    "INC-15": "A chosen baseline that is not an ancestor: slower, never stale",
    "INC-16": "A reviewer's correction is carried, and orphaned when its code changes",
    "INC-17": "With the LLM: the same words as a full generation",
    "INC-18": "A smaller scope than the baseline's",
}

#: The base commit and its full version, which the scenarios' branches start from -- set by the
#: entry point before the first scenario.
BASE = {"sha": None, "vid": None}

UTIL, UTIL_H = "Layer1/Sample/Util/Util.cpp", "Layer1/Sample/Util/Util.h"
LIB, LIB_H = "Layer1/Sample/Lib/Lib.cpp", "Layer1/Sample/Lib/Lib.h"
CORE = "Layer1/Sample/Core/Core.cpp"
SHARED = "Layer1/Sample/Core/SharedDefs.h"
MATH = "Layer1/Math/Utils.cpp"
APP = "Layer1/App/Main.cpp"

LIBABS = ("PUBLIC int libAbs(int v) {\n    if (v < 0) {\n        return -v;\n    }\n"
          "    return v;\n}\n")
LOOPACCUM = ("PUBLIC int utilLoopAccum(int n) {\n"
             "    // For loop — accumulates sum of utilDouble of each index\n"
             "    int total = 0;\n"
             "    for (int i = 0; i < n; ++i) {\n"
             "        total += utilDouble(i);   // private call inside loop\n"
             "    }\n"
             "    return utilClip(total, -100000, 100000);\n"
             "}\n")


# ---------------------------------------------------------------------------
# the steps every scenario is made of
# ---------------------------------------------------------------------------
def commit(ctx, label, edits, start=None) -> str:
    """A commit on a branch of its own from `start` (the base commit), made by `edits(repo)`."""
    return ctx.sample.change("inc-%s-%s" % (label, ctx.stamp), start or BASE["sha"], edits,
                             "incremental test: %s" % label)


def generate(ctx, label, sha, *, mode, reference=None, narrowed=None, scope="long",
             no_llm=True):
    """One generation of commit `sha`, followed to its end: (version id, version)."""
    a = ctx.submit("A", label, mode=mode, commit=sha, reference=reference, narrowed=narrowed,
                   scope=scope, no_llm=no_llm)
    if a.code != 202:
        raise StopScenario("the %s generation was refused: %s" % (label, a.brief(),))
    j = ctx.wait_done("A", a.job_id, what=label, timeout=None if no_llm else ctx.llm_timeout)
    if j.get("status") != "complete":
        raise StopScenario("the %s generation did not complete (%s): %s" % (
            label, j.get("status"), short(j.get("error_message") or "", 400)))
    _, v = ctx.version("A", a.version_id)
    return a.version_id, v


def incremental(ctx, label, sha, *, baseline, on, reqs=(), changed=True,
                why="nothing that matters changed", **kw):
    """`sha` generated incrementally (mode auto, or on `reference=`): it must be built on
    `baseline` (`on` names it), and -- a warning, not a failure -- reuse what did not change
    (`changed` True), or regenerate nothing at all (False: `why` says why), or either (None)."""
    c = ctx.c
    vid, v = generate(ctx, label + "-incremental", sha, mode="auto", **kw)
    shown = {k: v.get(k) for k in ("decision", "baseline_version_id", "regenerated", "reused")}
    c.check("generated incrementally, built on %s" % on,
            v.get("decision") == "incremental" and v.get("baseline_version_id") == baseline,
            shown, reqs=("INC-02",) + tuple(reqs))
    regen, reused = v.get("regenerated") or 0, v.get("reused") or 0
    if changed:
        # Not "regenerated > 0": a change an earlier version of the project already made is
        # found by its content in the reuse index and copied -- correct, and regenerated is 0.
        c.check("it reused what did not change: %s reused, %s regenerated" % (reused, regen),
                reused > 0, shown, warn=True, reqs=("INC-03",))
    elif changed is False:
        c.check("%s: nothing regenerated (%s), the rest reused (%s)" % (why, regen, reused),
                regen == 0 and reused > 0, shown, warn=True, reqs=("INC-03",))
    else:
        c.note("regenerated %s, reused %s" % (regen, reused))
    return vid, v


def against_full(ctx, label, sha, vid, *, reqs=(), scope="long", no_llm=True):
    """The same commit generated in full: its Word files must be the incremental version's."""
    full, _ = generate(ctx, label + "-full", sha, mode="full", scope=scope, no_llm=no_llm)
    check_same_documents(ctx, "A", vid, full, what_a="incremental", what_b="full",
                         reqs=("INC-01",) + tuple(reqs))
    return full


def standard(ctx, label, edits, reqs, changed=True):
    """Change, generate incrementally on the base version, generate in full, compare."""
    sha = commit(ctx, label, edits)
    vid, _ = incremental(ctx, label, sha, baseline=BASE["vid"], on="the base version",
                         reqs=reqs, changed=changed)
    against_full(ctx, label, sha, vid, reqs=reqs)


# ---- the changes, used by more than one scenario --------------------------------------------
def body_change(r):
    """utilCompute's limits: Core, Lib and Util call it."""
    r.edit(UTIL, "return utilClip(a + b + g_utilBase, -1000, 1000);",
           "return utilClip(a + b + g_utilBase, -2000, 2000);")


def body_change_back(r):
    r.edit(UTIL, "return utilClip(a + b + g_utilBase, -2000, 2000);",
           "return utilClip(a + b + g_utilBase, -1000, 1000);")


def signature_change(r):
    r.edit(UTIL_H, "PUBLIC int utilAbs(int v);", "PUBLIC long utilAbs(long v);")
    r.edit(UTIL, "PUBLIC int utilAbs(int v) {", "PUBLIC long utilAbs(long v) {")


def macro_change(r):
    r.edit(SHARED, "#define SHARED_SCALE_FACTOR 8", "#define SHARED_SCALE_FACTOR 16")


def cross_group_change(r):
    """Math's add: Outer and App, other groups, call it."""
    r.edit(MATH, "return a + b;", "return b + a;")


# ---------------------------------------------------------------------------
# normal
# ---------------------------------------------------------------------------
@scenario("I01", "Nothing that matters changes: blank lines at a file's end", mode="normal",
          reqs=("INC-01", "INC-02", "INC-03"), uses=("A",))
def i01(ctx):
    """Blank lines change no function, global or type: the incremental version regenerates
    nothing, and its Word files are the base version's -- and a full generation's."""
    sha = commit(ctx, "blank", lambda r: r.append(UTIL, "\n\n"))
    vid, _ = incremental(ctx, "blank", sha, baseline=BASE["vid"], on="the base version",
                         changed=False)
    check_same_documents(ctx, "A", BASE["vid"], vid, what_a="the base version",
                         what_b="incremental", reqs=("INC-01", "INC-03"))
    against_full(ctx, "blank", sha, vid, reqs=("INC-03",))


@scenario("I02", "A function's body changes; its callers in other files follow", mode="normal",
          reqs=("INC-01", "INC-04"), uses=("A",))
def i02(ctx):
    """utilCompute's limits change in Util.cpp; Core and Lib, which call it, are in files the
    change did not touch."""
    standard(ctx, "body", body_change, ("INC-04",))


@scenario("I03", "A new function, called from another component", mode="normal",
          reqs=("INC-01", "INC-05"), uses=("A",))
def i03(ctx):
    """utilTriple is added to Util and called from Core's coreCompute: a new function, a new
    call between components, and Util's interface table gains a row."""
    def edits(r):
        r.edit(UTIL_H, "PUBLIC int utilGotoGuard(int v, int limit);",
               "PUBLIC int utilGotoGuard(int v, int limit);\n"
               "PUBLIC int utilTriple(int v);                // added by the incremental test")
        r.append(UTIL, "\nPUBLIC int utilTriple(int v) {\n    return utilScale(v, 3);\n}\n")
        r.edit(CORE, "int h = coreHelper(x);     // private callee",
               "int h = coreHelper(x) + utilTriple(x);   // private callee, and a new Util one")
    standard(ctx, "new-function", edits, ("INC-05",))


@scenario("I04", "A function deleted, with the call to it", mode="normal",
          reqs=("INC-01", "INC-06", "INC-04"), uses=("A",))
def i04(ctx):
    """utilLoopAccum leaves Util, and App -- another group -- stops calling it."""
    def edits(r):
        r.edit(UTIL_H, "PUBLIC int utilLoopAccum(int n);", "")
        r.edit(UTIL, LOOPACCUM, "")
        r.edit(APP, "int ul = utilLoopAccum(5);", "int ul = 5;")
    standard(ctx, "deleted-function", edits, ("INC-06", "INC-04"))


@scenario("I05", "A parameter's type changes", mode="normal",
          reqs=("INC-01", "INC-07"), uses=("A",))
def i05(ctx):
    """utilAbs takes and returns long, not int: its interface table row and its callers."""
    standard(ctx, "signature", signature_change, ("INC-07",))


@scenario("I06", "Globals: a new value, and one newly shared with another unit", mode="normal",
          reqs=("INC-01", "INC-08"), uses=("A",))
def i06(ctx):
    """g_utilBase starts at 7, not 0; and Lib starts reading Core's g_result -- used by Core
    alone until now, so it gets an interface row only now."""
    def edits(r):
        r.edit(UTIL, "PUBLIC int g_utilBase = 0;", "PUBLIC int g_utilBase = 7;")
        r.edit(LIB, '#include "../Core/SharedDefs.h"',
               '#include "../Core/SharedDefs.h"\n'
               "extern int g_result;   // Core's; read here from now on")
        r.edit(LIB_H, "PUBLIC int libMeanOf(int total, int count, int lastSample);",
               "PUBLIC int libMeanOf(int total, int count, int lastSample);\n"
               "PUBLIC int libResultScale(int v);")
        r.append(LIB, "\nPUBLIC int libResultScale(int v) {\n    return v * g_result;\n}\n")
    standard(ctx, "globals", edits, ("INC-08",))


@scenario("I07", "A type in a shared header changes", mode="normal",
          reqs=("INC-01", "INC-09"), uses=("A",))
def i07(ctx):
    """SharedDefs.h -- included by Core, Lib and Util -- gains an enum value."""
    standard(ctx, "type", lambda r: r.edit(SHARED, "LEVEL_HIGH = 2",
                                           "LEVEL_HIGH = 2,\n    LEVEL_MAX  = 3"), ("INC-09",))


@scenario("I08", "A macro in a shared header changes", mode="normal",
          reqs=("INC-01", "INC-09"), uses=("A",))
def i08(ctx):
    """SHARED_SCALE_FACTOR goes from 8 to 16; Lib's libScaleShared uses it."""
    standard(ctx, "macro", macro_change, ("INC-09",))


@scenario("I09", "A change in one group reaches callers in other groups", mode="normal",
          reqs=("INC-01", "INC-04"), uses=("A",))
def i09(ctx):
    """Math's add changes; Outer's helperCompute and App's calculate call it."""
    standard(ctx, "cross-group", cross_group_change, ("INC-04",))


@scenario("I10", "A chain: each version built on the one before", mode="normal",
          reqs=("INC-01", "INC-02", "INC-13"), uses=("A",))
def i10(ctx):
    """Two commits one after the other: the first built on the base version, the second on the
    first -- and the second's Word files are a full generation's."""
    sha1 = commit(ctx, "chain-1", lambda r: r.edit(UTIL, "if (factor == 0) return 0;",
                                                   "if (factor == 0) return 1;"))
    v1, _ = incremental(ctx, "chain-1", sha1, baseline=BASE["vid"], on="the base version",
                        reqs=("INC-13",))
    sha2 = commit(ctx, "chain-2", lambda r: r.edit(LIB, "return a + b;", "return b + a;"),
                  start=sha1)
    v2, _ = incremental(ctx, "chain-2", sha2, baseline=v1, on="the version before it",
                        reqs=("INC-13",))
    against_full(ctx, "chain-2", sha2, v2, reqs=("INC-13",))


# ---------------------------------------------------------------------------
# complex
# ---------------------------------------------------------------------------
@scenario("X01", "The narrowed parse, on and off", mode="complex",
          reqs=("INC-01", "INC-12", "INC-09"), uses=("A",))
def x01(ctx):
    """A shared header's macro changes. Generated incrementally twice on the base version --
    parsing only the files the change reaches (the server's default), and parsing them all --
    and once in full: three times the same Word files."""
    sha = commit(ctx, "narrowed", lambda r: r.edit(SHARED, "#define SHARED_MAX_ITEMS 256",
                                                   "#define SHARED_MAX_ITEMS 512"))
    on, _ = incremental(ctx, "narrowed-on", sha, baseline=BASE["vid"], on="the base version",
                        reference=BASE["vid"], narrowed=True, reqs=("INC-12",))
    off, _ = incremental(ctx, "narrowed-off", sha, baseline=BASE["vid"],
                         on="the base version", reference=BASE["vid"], narrowed=False,
                         reqs=("INC-12",))
    check_same_documents(ctx, "A", on, off, what_a="narrowed parse", what_b="whole parse",
                         reqs=("INC-12",))
    against_full(ctx, "narrowed", sha, on, reqs=("INC-12",))


@scenario("X02", "A header added", mode="complex", reqs=("INC-01", "INC-10"), uses=("A",))
def x02(ctx):
    """UtilExtra.h is new, included by Util.cpp, whose utilChain uses its macro. A header added
    may shadow another, so the narrowed parse must parse everything."""
    def edits(r):
        r.create("Layer1/Sample/Util/UtilExtra.h",
                 "#pragma once\n\n// Added by the incremental test.\n#define UTIL_EXTRA_STEP (3)\n")
        r.edit(UTIL, '#include "Util.h"', '#include "Util.h"\n#include "UtilExtra.h"')
        r.edit(UTIL, "int scaled = utilScale(normed, 3);",
               "int scaled = utilScale(normed, UTIL_EXTRA_STEP);")
    standard(ctx, "header-added", edits, ("INC-10",))


@scenario("X03", "A header deleted", mode="complex", reqs=("INC-01", "INC-10", "INC-06"),
          uses=("A",))
def x03(ctx):
    """LibLimits.h goes; Core and Util, which included it, define its macro themselves."""
    def edits(r):
        r.remove("Layer1/Sample/Lib/LibLimits.h")
        for rel in (CORE, UTIL):
            r.edit(rel, '#include "../Lib/LibLimits.h"',
                   "#define LIB_LIMIT (64)   // LibLimits.h is gone")
    standard(ctx, "header-deleted", edits, ("INC-10", "INC-06"))


@scenario("X04", "A source file deleted", mode="complex", reqs=("INC-01", "INC-06"),
          uses=("A",))
def x04(ctx):
    """CoreStats.cpp goes -- a unit of Sample Core; CoreGateway still calls what its header
    declares."""
    standard(ctx, "file-deleted", lambda r: r.remove("Layer1/Sample/Core/CoreStats.cpp"),
             ("INC-06",))


@scenario("X05", "A source file renamed", mode="complex", reqs=("INC-01", "INC-11"),
          uses=("A",))
def x05(ctx):
    """CoreGateway.cpp becomes CoreGate.cpp: the unit's name changes, its functions do not."""
    standard(ctx, "file-renamed",
             lambda r: r.move("Layer1/Sample/Core/CoreGateway.cpp",
                              "Layer1/Sample/Core/CoreGate.cpp"), ("INC-11",))


@scenario("X06", "A function moved to another component", mode="complex",
          reqs=("INC-01", "INC-11"), uses=("A",))
def x06(ctx):
    """libAbs moves from Lib to Util; Lib and App still call it."""
    def edits(r):
        r.edit(LIB, LIBABS, "")
        r.edit(LIB_H, "PUBLIC int libAbs(int v);", "")
        r.edit(UTIL_H, "PUBLIC int utilAbs(int v);",
               "PUBLIC int utilAbs(int v);\nPUBLIC int libAbs(int v);   // moved here from Lib")
        r.append(UTIL, "\n" + LIBABS)
    standard(ctx, "function-moved", edits, ("INC-11",))


@scenario("X07", "A revert gives the earlier documents back", mode="complex",
          reqs=("INC-01", "INC-14", "INC-13"), uses=("A",))
def x07(ctx):
    """A change, then a commit that takes it back: the second version -- built on the first --
    has the base version's Word files, and a full generation's."""
    sha1 = commit(ctx, "revert-1", body_change)
    v1, _ = incremental(ctx, "revert-1", sha1, baseline=BASE["vid"], on="the base version",
                        reqs=("INC-14",))
    sha2 = commit(ctx, "revert-2", body_change_back, start=sha1)
    v2, _ = incremental(ctx, "revert-2", sha2, baseline=v1, on="the changed version",
                        reqs=("INC-14",), changed=False,
                        why="the code is the base version's again, its output found by content")
    check_same_documents(ctx, "A", BASE["vid"], v2, what_a="the base version",
                         what_b="reverted", reqs=("INC-14",))
    against_full(ctx, "revert-2", sha2, v2, reqs=("INC-14",))


@scenario("X08", "A chosen baseline that is not an ancestor", mode="complex",
          reqs=("INC-01", "INC-15"), uses=("A",))
def x08(ctx):
    """Two branches from the base commit, P and Q. Q is generated on P's version, which it does
    not descend from: the difference is larger, the documents are still Q's."""
    sha_p = commit(ctx, "branch-p", lambda r: r.edit(UTIL, "if (factor == 0) return 0;",
                                                     "if (factor == 0) return 2;"))
    vp, _ = incremental(ctx, "branch-p", sha_p, baseline=BASE["vid"], on="the base version")
    sha_q = commit(ctx, "branch-q", cross_group_change)
    vq, _ = incremental(ctx, "branch-q", sha_q, baseline=vp, on="branch P's version, chosen",
                        reference=vp, reqs=("INC-15",))
    against_full(ctx, "branch-q", sha_q, vq, reqs=("INC-15",))


@scenario("X09", "No earlier version is an ancestor: a full generation", mode="complex",
          reqs=("INC-02",), uses=("A",))
def x09(ctx):
    """A commit with no history in common with any version (an orphan branch): mode auto finds
    no baseline and generates in full."""
    repo = ctx.sample
    repo.git("checkout", "-q", "--orphan", "inc-orphan-%s" % ctx.stamp)
    try:
        body_change(repo)
        repo.git("add", "-A")
        sha = repo.commit("incremental test: no common history")
    finally:
        repo.git("checkout", "-q", "-f", "main")
    _, v = generate(ctx, "orphan", sha, mode="auto")
    ctx.c.check("generated in full: no earlier version to build on",
                v.get("decision") == "full" and not v.get("baseline_version_id"),
                {k: v.get(k) for k in ("decision", "baseline_version_id")}, reqs=("INC-02",))


@scenario("X10", "A reviewer's correction: carried, then orphaned", mode="complex",
          reqs=("INC-16", "INC-01"), uses=("A",))
def x10(ctx):
    """A correction of utilCompute's description in a version of its own. The next version --
    utilAbs changed -- carries it, in force, into its Word file; the one after -- utilCompute
    itself changed -- keeps it as an orphan, not printed."""
    c = ctx.c
    sha0 = commit(ctx, "review-0", lambda r: r.append(UTIL, "\n"))
    v0, _ = generate(ctx, "review-base", sha0, mode="full")
    slots = body_of(ctx.admin.call("GET", ctx.V("A", v0, "/slots"), params={
        "slot_kind": "description", "limit": 1000})).get("slots") or []
    slot = next((s for s in slots if "utilCompute" in (s.get("slotKey") or "")
                 or "utilCompute" in (s.get("label") or "")), None)
    if slot is None:
        raise StopScenario("the version has no description slot for utilCompute", skip=True)
    words = "JST %s: a reviewer's words for utilCompute." % ctx.stamp
    r = ctx.admin.ask("PUT", ctx.V("A", v0, "/overrides/slot"), json={
        "slot_kind": "description", "slot_key": slot["slotKey"], "text": words})
    c.check("utilCompute's description is corrected", r.code == 200, r.brief(),
            reqs=("INC-16",))

    def state(vid):
        rows = body_of(ctx.admin.call("GET", ctx.V("A", vid, "/overrides"),
                                      params={"limit": 1000})).get("overrides") or []
        return next((o for o in rows if o.get("slotKey") == slot["slotKey"]), {})

    sha1 = commit(ctx, "review-1", signature_change, start=sha0)
    v1, _ = incremental(ctx, "review-1", sha1, baseline=v0, on="the corrected version")
    o = state(v1)
    c.check("the next version carries the correction, in force (its code did not change)",
            o.get("isOverridden") is True and o.get("text") == words, o, reqs=("INC-16",))
    c.check("... and its Word file prints the reviewer's words", has_words(ctx, "A", v1, words),
            words, reqs=("INC-16",))
    sha2 = commit(ctx, "review-2", body_change, start=sha1)
    v2, _ = incremental(ctx, "review-2", sha2, baseline=v1, on="the version carrying it")
    o = state(v2)
    c.check("utilCompute changed: the correction is kept as an orphan, not in force",
            o.get("isOrphaned") is True and o.get("isOverridden") is not True, o,
            reqs=("INC-16",))
    c.check("... and the Word file no longer prints it", not has_words(ctx, "A", v2, words),
            words, reqs=("INC-16",))


@scenario("X11", "With the LLM: the same words as a full generation", mode="complex",
          reqs=("INC-17", "INC-01"), needs=("llm",), uses=("A",))
def x11(ctx):
    """With the LLM: a base of its own, a change generated incrementally on it, and the same
    commit in full after it -- the LLM's answers come from the project's cache, so the words
    match too."""
    sha0 = commit(ctx, "llm-0", lambda r: r.append(UTIL, "\n"))
    v0, _ = generate(ctx, "llm-base", sha0, mode="full", no_llm=False)
    sha1 = commit(ctx, "llm-1", body_change, start=sha0)
    v1, _ = incremental(ctx, "llm-1", sha1, baseline=v0, on="the LLM base version",
                        no_llm=False, reqs=("INC-17",))
    against_full(ctx, "llm-1", sha1, v1, no_llm=False, reqs=("INC-17",))


@scenario("X12", "Several changes at once, across components", mode="complex",
          reqs=("INC-01", "INC-04", "INC-07", "INC-09"), uses=("A",))
def x12(ctx):
    """One commit: a body, a signature, a shared macro and Math's add."""
    def edits(r):
        body_change(r)
        signature_change(r)
        macro_change(r)
        cross_group_change(r)
    standard(ctx, "many", edits, ("INC-04", "INC-07", "INC-09"))


@scenario("X13", "A smaller scope than the baseline's", mode="complex",
          reqs=("INC-01", "INC-18"), uses=("A",))
def x13(ctx):
    """The base version covers the whole project; the change is generated for its first group
    only -- incrementally and in full."""
    sha = commit(ctx, "scope", body_change)
    vid, _ = incremental(ctx, "scope", sha, baseline=BASE["vid"], on="the base version",
                         scope="first", reqs=("INC-18",))
    against_full(ctx, "scope", sha, vid, scope="first", reqs=("INC-18",))
