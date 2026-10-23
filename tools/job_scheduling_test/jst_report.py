"""The report: on the terminal, as Markdown and as JSON -- every scenario, every check, and each
requirement of docs/spec/JOB_SCHEDULING_SPEC.md with the scenarios that showed it."""
from __future__ import annotations

import json
import os

#: Every requirement, by the title the spec gives it.
REQS = {
    "REQ-JS-01": "Two lanes per project", "REQ-JS-02": "One running job per lane per project",
    "REQ-JS-03": "One writer per version", "REQ-JS-04": "Per-project limits",
    "REQ-JS-05": "Server cap for generations", "REQ-JS-06": "Three answers",
    "REQ-JS-07": "Checked twice", "REQ-JS-08": "No duplicates",
    "REQ-JS-09": "A retried submission is one job", "REQ-JS-10": "Baseline chosen at start",
    "REQ-JS-11": "Priority in the generation lane", "REQ-JS-12": "Updates first come, first served",
    "REQ-JS-13": "Fair across projects", "REQ-JS-14": "In the database",
    "REQ-JS-15": "One start per job", "REQ-JS-16": "The next job starts by itself",
    "REQ-JS-17": "A short outage waits", "REQ-JS-18": "Held after a restart",
    "REQ-JS-19": "Running jobs carry on", "REQ-JS-20": "A job that stops answering",
    "REQ-JS-21": "A failed job", "REQ-JS-22": "Pause, generations only", "REQ-JS-23": "Resume",
    "REQ-JS-24": "A paused job keeps its place", "REQ-JS-25": "Cancel", "REQ-JS-26": "Remove",
    "REQ-JS-27": "No queue in the CLI", "REQ-JS-28": "The CLI refuses what would break the rules",
    "REQ-JS-29": "A CLI run is the project's running job", "REQ-JS-30": "One queue or all",
    "REQ-JS-31": "Before submitting", "REQ-JS-32": "Told when it changes",
    "REQ-JS-33": "Recorded", "REQ-JS-34": "Measured",
    "REQ-JS-35": "Messages where the web app already shows them",
}
#: What this tool cannot show through the API, and where it is shown instead.
NOT_HERE = {
    "REQ-JS-17": "stopping the database for minutes is not done through the API -- try it by "
                 "hand: stop PostgreSQL for 2 minutes during a run; the run carries on",
}
ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2, "SKIP": 3}


def scenario_result(sc, items) -> str:
    mine = [i for i in items if i["scenario"] == sc.sid]
    if sc.result == "SKIP" or (mine and all(i["result"] == "SKIP" for i in mine)):
        return "SKIP"
    if not mine:
        return sc.result or "-"
    return min((i["result"] for i in mine if i["result"] != "SKIP"), key=ORDER.get,
               default="SKIP")


def coverage(scenarios, items, ran) -> list:
    """[(req, title, result, scenarios that showed it, why not)] for every requirement."""
    rows = []
    for req, title in REQS.items():
        mine = [i for i in items if req in i["reqs"]]
        shown = sorted({i["scenario"] for i in mine})
        if req in NOT_HERE and not mine:
            rows.append((req, title, "NOT HERE", shown, NOT_HERE[req]))
            continue
        results = [i["result"] for i in mine if i["result"] != "SKIP"]
        if results:
            rows.append((req, title, min(results, key=ORDER.get), shown, ""))
        elif mine:
            rows.append((req, title, "SKIP", shown, mine[0].get("detail") or ""))
        else:
            other = sorted(sc.sid for sc in scenarios if req in sc.reqs and sc.sid not in ran)
            rows.append((req, title, "NOT RUN", [],
                         "shown by %s -- not run this time" % ", ".join(other) if other else
                         "no scenario shows it"))
    return rows


def terminal(test, scenarios, checks, rows, seconds):
    counts = checks.counts()
    print("\n" + "=" * 78)
    print("JOB SCHEDULING TEST -- %s mode, %d min %d s" % (test["mode"], seconds // 60,
                                                         seconds % 60))
    print("=" * 78)
    print("\nScenarios")
    for sc in scenarios:
        print("  %-5s %-6s %5ds  %s" % (sc.sid, scenario_result(sc, checks.items), sc.seconds,
                                        sc.title))
        if sc.why:
            print("               %s" % sc.why)
    print("\nRequirements (docs/spec/JOB_SCHEDULING_SPEC.md)")
    for req, title, result, shown, why in rows:
        print("  %-9s %-8s %-46s %s" % (req, result, title[:46], ", ".join(shown)))
        if why and result in ("SKIP", "NOT RUN", "NOT HERE"):
            print("                     %s" % why[:150])
    print("\nChecks: PASS %(PASS)d   FAIL %(FAIL)d   WARN %(WARN)d   SKIP %(SKIP)d" % counts)
    failed = [i for i in checks.items if i["result"] == "FAIL"]
    if failed:
        print("\nFailed checks")
        for i in failed:
            print("  [%s] %s" % (i["scenario"], i["check"]))
            if i.get("detail"):
                print("        %s" % i["detail"][:300])


def markdown(test, scenarios, checks, rows, seconds) -> str:
    counts = checks.counts()
    out = ["# Job scheduling test report", "",
           "| | |", "|---|---|",
           "| Mode | %s |" % test["mode"],
           "| Server | %s |" % test["server"],
           "| Started | %s |" % test["started"],
           "| Took | %d min %d s |" % (seconds // 60, seconds % 60),
           "| Checks | PASS %(PASS)d · FAIL %(FAIL)d · WARN %(WARN)d · SKIP %(SKIP)d |" % counts,
           "| Projects | %s |" % ", ".join("%s `%s`" % (k, v["id"])
                                          for k, v in test["projects"].items()),
           "", "## The server's settings, as its config files say", ""]
    out += ["- %s" % line for line in test["server_config"]]
    out += ["", "## Requirements", "",
            "| Requirement | | Result | Shown by | Note |", "|---|---|---|---|---|"]
    for req, title, result, shown, why in rows:
        out.append("| %s | %s | **%s** | %s | %s |" % (req, title, result, ", ".join(shown),
                                                     why.replace("|", "/")))
    out += ["", "## Scenarios", ""]
    for sc in scenarios:
        out += ["### %s %s — %s" % (sc.sid, sc.title, scenario_result(sc, checks.items)), "",
                sc.doc, "", "Requirements: %s · %d s" % (", ".join(sc.reqs) or "-", sc.seconds)]
        if sc.why:
            out += ["", "> %s" % sc.why]
        mine = [i for i in checks.items if i["scenario"] == sc.sid]
        if mine:
            out += ["", "| Result | Check | Detail |", "|---|---|---|"]
            for i in mine:
                detail = (i.get("detail") or "").replace("|", "/")
                if i["result"] == "PASS":
                    detail = ""
                out.append("| %s | %s | %s |" % (i["result"], i["check"].replace("|", "/"),
                                                 detail[:400]))
        out.append("")
    return "\n".join(out)


def write(test, scenarios, checks, rows, seconds, json_path, md_path):
    data = dict(test, seconds=seconds, counts=checks.counts(), checks=checks.items,
                scenarios=[{"id": sc.sid, "title": sc.title, "mode": sc.mode,
                            "requirements": list(sc.reqs),
                            "result": scenario_result(sc, checks.items),
                            "seconds": sc.seconds, "note": sc.why} for sc in scenarios],
                requirements=[{"id": r, "title": t, "result": res, "shownBy": s, "note": w}
                              for r, t, res, s, w in rows])
    written = []
    for path, text in ((json_path, json.dumps(data, indent=2, ensure_ascii=False)),
                       (md_path, markdown(test, scenarios, checks, rows, seconds))):
        if not path:
            continue
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            written.append(os.path.abspath(path))
        except OSError as exc:
            print("could not write %s: %s" % (path, exc))
    return written
