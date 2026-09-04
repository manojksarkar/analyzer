"""Where did each version's flowchart for this function come from?

A flowchart reaches a document by one of three routes, and they are indistinguishable in
the output: rendered fresh, spliced from another version that shares the function's
content fingerprint, or carried forward from the baseline. When the wrong one wins, the
document shows a diagram for code that has changed and nothing reports it.

Comparing two versions cannot tell them apart -- "identical to the baseline" and "spliced
from a version that happens to match the baseline" look the same. So lay every version
out at once: the same DOT bytes appearing in v5 and v8 but not v7 says the splice reached
past v7; a DOT that never moves says nothing ever regenerated it.

Reads the OUTPUT directory, which is what the document embeds -- not the model.

    python tools/flowchart_lineage.py --project-id P --name myFunc
    python tools/flowchart_lineage.py --project-id P --name myFunc --versions v5,v7,v8
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


def _dots(pid, vid):
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
            for e in (arr if isinstance(arr, list) else []):
                n = (e.get("name") or "").strip()
                if n:
                    out[(f[:-5], n)] = e.get("flowchart") or ""
    return out


def _pngs_for(pid, vid, unit, fname):
    """{png filename -> md5} for this function's images (including split parts)."""
    out = {}
    base = os.path.join(_version_dir(pid, vid), "output")
    stem = "%s_%s" % (unit, fname)
    if not os.path.isdir(base):
        return out
    for comp in sorted(os.listdir(base)):
        d = os.path.join(base, comp, "flowcharts")
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".png") and f.startswith(stem):
                p = os.path.join(d, f)
                out[f] = hashlib.md5(open(p, "rb").read()).hexdigest()[:10]
    return out


def _md5(s):
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()[:10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--name", required=True, help="function name (not the full key)")
    ap.add_argument("--versions", help="comma-separated; default every version, oldest first")
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine
    eng = get_engine()

    with eng.connect() as cx:
        rows = [(r[0], r[1], r[2], r[3]) for r in cx.execute(sa.text(
            "select id, commit_sha, decision, baseline_version_id from versions "
            "where project_id = :p order by created_at"), {"p": a.project_id})]
    if a.versions:
        want = [v.strip() for v in a.versions.split(",") if v.strip()]
        rows = [r for r in rows if r[0] in want]
    if not rows:
        print("no versions for %r." % a.project_id)
        return 2

    # Locate the function once, from whichever version has it.
    unit = fname = None
    for vid, *_ in rows:
        for (u, n) in _dots(a.project_id, vid):
            if a.name.lower() in n.lower():
                unit, fname = u, n
                break
        if unit:
            break
    if not unit:
        print("no flowchart entry matching %r in any version's output." % a.name)
        print("(the function may be outside the generated scope, or the output dir is gone)")
        return 2

    print("=" * 78)
    print("FLOWCHART LINEAGE  %s   [unit %s]" % (fname, unit))
    print("=" * 78)
    print("  %-8s %-13s %-12s %-9s %8s %-11s %s"
          % ("version", "commit", "decision", "baseline", "DOT len", "DOT md5", "PNG md5"))

    seen = {}          # dot md5 -> first version that showed it
    prev_dot = None
    lines = []
    for vid, sha, dec, base in rows:
        dot = _dots(a.project_id, vid).get((unit, fname))
        if dot is None:
            lines.append((vid, None, None, None, {}, "no output for this version"))
            continue
        h = _md5(dot)
        note = ""
        if h in seen and seen[h] != vid:
            note = "same DOT as %s" % seen[h]
        else:
            seen.setdefault(h, vid)
            note = "NEW" if prev_dot is not None else ""
        pngs = _pngs_for(a.project_id, vid, unit, fname)
        lines.append((vid, sha, dec, base, pngs, note))
        print("  %-8s %-13s %-12s %-9s %8d %-11s %s"
              % (vid, (sha or "?")[:12], dec or "?", base or "-", len(dot), h,
                 ", ".join(sorted(pngs.values())) or "-"))
        if note:
            print("           %s" % note)
        prev_dot = h

    # A DOT and its PNG must move together: the image is rendered FROM the graph.
    print()
    print("=" * 78)
    print("CONSISTENCY")
    print("=" * 78)
    # Compare each version against ITS OWN BASELINE, not the one before it in time. That
    # is the pair the run itself reasoned about, and the pair a reuse report quotes -- v8
    # built on v5 says nothing about v7, which may sit between them.
    by_vid = {ln[0]: ln for ln in lines}
    bad, checked = [], 0
    for vid, _sha, _dec, base, pngs, _note in lines:
        prior = by_vid.get(base)
        if not base or prior is None:
            continue
        pd = _dots(a.project_id, base).get((unit, fname))
        cd = _dots(a.project_id, vid).get((unit, fname))
        if pd is None or cd is None:
            continue
        checked += 1
        dot_same, png_same = (_md5(pd) == _md5(cd)), (prior[4] == pngs)
        if dot_same != png_same:
            bad.append((base, vid, dot_same, png_same))
    if not checked:
        print("  no version here has its baseline in the set -- add it with --versions.")
    elif not bad:
        print("  DOT and PNG moved together everywhere -- the images match their graphs.")
    for pv, cv, ds, ps in bad:
        print("  %s (baseline) -> %s: DOT %s but PNG %s"
              % (pv, cv, "identical" if ds else "changed", "identical" if ps else "changed"))
        if ds and not ps:
            print("      The image changed while the graph did not. The PNG was not rendered")
            print("      from this stored DOT -- the stored graph and the picture in the")
            print("      document have different origins.")
        else:
            print("      The graph changed but the image did not: a stale PNG is being served")
            print("      for a regenerated flowchart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
