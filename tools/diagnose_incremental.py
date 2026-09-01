"""Why does this version's document still show the OLD flowchart?

A code change has to survive four hops to reach a diagram, and each can fail silently:

    1. PARSE    the function's source_hash must differ from the baseline's
    2. PLAN     it must be classified changed and land in the plan's flowchartFids
    3. ENGINE   the flowchart DOT stored for it must be regenerated
    4. RENDER   the PNG must be re-rendered from that DOT

This compares a baseline version against a target and reports, per function, which hop
stopped. The inconsistent pairs are the interesting ones: a source_hash that differs while
the DOT is byte-identical means the parse saw the change and the flowchart did not.

The incremental plan is deliberately deleted at the end of a run, so hop 2 is inferred
from its effects rather than read directly.

    python tools/diagnose_incremental.py --project-id P --baseline v1 --target v3
    python tools/diagnose_incremental.py --project-id P --baseline v1 --target v3 --name myFunc
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def _version_dir(pid, vid):
    return os.path.join(_ROOT, "workspaces", pid, "versions", vid)


def _flowchart_dots(pid, vid):
    """{(unit, funcName) -> dot} from every <unit>.json under output/*/flowcharts/."""
    out = {}
    base = os.path.join(_version_dir(pid, vid), "output")
    if not os.path.isdir(base):
        return out
    for comp in sorted(os.listdir(base)):
        d = os.path.join(base, comp, "flowcharts")
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".json"):
                continue
            try:
                arr = json.load(open(os.path.join(d, f), encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(arr, list):
                continue
            for e in arr:
                n = (e.get("name") or "").strip()
                if n:
                    out[(f[:-5], n)] = e.get("flowchart") or ""
    return out


def _pngs(pid, vid):
    out = {}
    base = os.path.join(_version_dir(pid, vid), "output")
    if not os.path.isdir(base):
        return out
    for comp in sorted(os.listdir(base)):
        d = os.path.join(base, comp, "flowcharts")
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".png"):
                out[f] = hashlib.md5(open(os.path.join(d, f), "rb").read()).hexdigest()[:10]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--name", help="only functions whose key contains this")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine

    def hashes(vid):
        q = ("select e.entity_key, v.source_hash from entity_versions v "
             "join entities e on e.entity_id = v.entity_id "
             "where v.version_id = :v and e.kind = 'function'")
        with get_engine().connect() as cx:
            return {r[0]: r[1] for r in cx.execute(sa.text(q), {"v": vid})}

    with get_engine().connect() as cx:
        rows = {r[0]: (r[1], r[2]) for r in cx.execute(sa.text(
            "select id, decision, baseline_version_id from versions where id in (:a, :b)"),
            {"a": a.baseline, "b": a.target})}

    hb, ht = hashes(a.baseline), hashes(a.target)
    print("=" * 74)
    print("VERSIONS")
    print("=" * 74)
    for v in (a.baseline, a.target):
        d, b = rows.get(v, (None, None))
        n = len(hb if v == a.baseline else ht)
        print("  %-10s decision=%-12s baseline=%-10s functions=%d"
              % (v, d or "?", b or "-", n))
    if not hb or not ht:
        print()
        print("  one of these versions has no model -- check the ids.")
        return 2

    # ---- HOP 1: did the parse see it? -------------------------------------------------
    changed = sorted(k for k in ht if k in hb and ht[k] != hb[k])
    added = sorted(k for k in ht if k not in hb)
    missing_hash = [k for k in ht if not ht[k]]
    print()
    print("=" * 74)
    print("HOP 1  parse: source_hash vs the baseline")
    print("=" * 74)
    print("  changed %d   new %d   unchanged %d"
          % (len(changed), len(added), len(ht) - len(changed) - len(added)))
    if missing_hash:
        print("  !! %d function(s) have NO source_hash stored -- change detection cannot"
              % len(missing_hash))
        print("     work for them, and they will look unchanged forever.")
        for k in missing_hash[:5]:
            print("        %s" % k)
    for k in changed[:8]:
        print("      changed: %s" % k)
    if not changed and not added:
        print("  *** NOTHING changed at the parse level. Either the target really is the")
        print("      same code, or the narrowed parse never re-parsed the edited file.")
        print("      Re-run the target with --full: if the change appears then, the")
        print("      narrowed parse is at fault; if not, the commit lacks your edit.")

    # ---- HOPS 3 and 4 -----------------------------------------------------------------
    db_, dt = _flowchart_dots(a.project_id, a.baseline), _flowchart_dots(a.project_id, a.target)
    pb, pt = _pngs(a.project_id, a.baseline), _pngs(a.project_id, a.target)
    print()
    print("=" * 74)
    print("HOPS 3-4  per changed function: did the DOT and the PNG follow?")
    print("=" * 74)
    if not dt:
        print("  the target has no flowchart JSON at all -- is views.flowcharts on?")
    shown, stuck, png_stuck, examined = 0, [], [], 0
    for k in changed + added:
        if a.name and a.name.lower() not in k.lower():
            continue
        examined += 1
        parts = k.split("|")
        fn = parts[2] if len(parts) > 2 else k
        cands = [key for key in dt if key[1] == fn]
        if not cands:
            if shown < a.limit:
                print("  %s: no flowchart entry in the target at all" % fn)
                shown += 1
            continue
        for key in cands:
            dot_b, dot_t = db_.get(key, ""), dt.get(key, "")
            same_dot = dot_b == dot_t
            names = sorted(n for n in set(pb) | set(pt)
                           if n.startswith(key[0] + "_") and fn in n)
            same_png = all(pb.get(n) == pt.get(n) for n in names) if names else None
            if shown < a.limit:
                print("  %s::%s" % (key[0], fn))
                print("      source_hash : CHANGED")
                print("      DOT         : %s   (%d -> %d chars)"
                      % ("IDENTICAL  <== flowchart NOT regenerated" if same_dot else "updated",
                         len(dot_b), len(dot_t)))
                if names:
                    detail = ", ".join("%s %s->%s" % (n, pb.get(n), pt.get(n)) for n in names[:2])
                    print("      PNG         : %s   %s"
                          % ("IDENTICAL  <== NOT re-rendered" if same_png else "updated", detail))
                shown += 1
            if same_dot:
                stuck.append("%s::%s" % (key[0], fn))
            elif same_png:
                png_stuck.append("%s::%s" % (key[0], fn))

    # ---- verdict ----------------------------------------------------------------------
    print()
    print("=" * 74)
    print("VERDICT")
    print("=" * 74)
    if not changed and not added:
        print("  HOP 1. The parse saw no change; nothing downstream can help.")
    elif not examined:
        # An empty examination is NOT a pass. Saying "all good" here is how this tool
        # wasted a run: the name filter matched none of the changed functions and the
        # verdict reported success anyway.
        print("  NOTHING WAS EXAMINED.")
        if a.name:
            print("  --name %r matched none of the %d changed function(s). They are:"
                  % (a.name, len(changed) + len(added)))
            for k in (changed + added)[:12]:
                print("      %s" % k)
            print()
            print("  Re-run WITHOUT --name to check them all, or copy a name from above.")
        else:
            print("  No changed function could be matched to a flowchart. Is"
                  " views.flowcharts on for this run?")
    elif stuck:
        print("  HOP 3. %d function(s) changed in the parse but kept the baseline's DOT:"
              % len(stuck))
        for s in stuck[:8]:
            print("      %s" % s)
        print("  The flowchart was not regenerated for code that changed.")
    elif png_stuck:
        print("  HOP 4. %d function(s) got a new DOT but the PNG was not re-rendered:"
              % len(png_stuck))
        for s in png_stuck[:8]:
            print("      %s" % s)
    else:
        print("  Every changed function got a new DOT and a new PNG. If the document still")
        print("  looks wrong, the export embedded something else -- or the file being read")
        print("  is not this version's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
