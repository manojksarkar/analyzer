"""How complete is each version's per-TU include map?

The narrowed parse decides what to re-parse from this map: a TU is affected iff it, or
something in its recorded #include closure, appears in the git diff. A map that is
missing edges therefore under-selects, silently -- the run reports a clean
"N affected TU(s)" either way.

Real C/C++ files pull in tens of in-repo headers each. A version averaging one or two is
not a project with few includes; it is a parse whose #include resolution failed, and its
map cannot be trusted to narrow anything. Comparing every version at once shows whether
that is one bad run or a standing problem -- and a version's own numbers say nothing
without its neighbours to compare against.

    python tools/include_map_health.py --project-id P
    python tools/include_map_health.py --project-id P --version v4   (which TUs are thin)
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

# Below this many in-repo headers per TU, a map is almost certainly incomplete rather
# than describing a genuinely include-light project.
THIN = 5.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--version", help="list the thinnest TUs in this version")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine
    from core import model_store
    eng = get_engine()

    with eng.connect() as cx:
        versions = [(r[0], r[1], r[2]) for r in cx.execute(sa.text(
            "select id, commit_sha, decision from versions where project_id = :p "
            "order by created_at"), {"p": a.project_id})]
    if not versions:
        print("no versions for project %r." % a.project_id)
        return 2

    print("=" * 78)
    print("INCLUDE-MAP HEALTH  %s" % a.project_id)
    print("=" * 78)
    print("  %-10s %-14s %-12s %6s %10s %8s" %
          ("version", "commit", "decision", "TUs", "edges", "per TU"))
    rows = []
    for vid, sha, dec in versions:
        with eng.connect() as cx:
            m = model_store.load_tu_includes(cx, vid) or {}
        tus = len(m)
        edges = sum(len(v or []) for v in m.values())
        per = (edges / tus) if tus else 0.0
        rows.append((vid, tus, edges, per))
        flag = ""
        if not tus:
            flag = "  <- no map at all"
        elif per < THIN:
            flag = "  <- THIN: #include resolution probably failed"
        print("  %-10s %-14s %-12s %6d %10d %8.1f%s"
              % (vid, (sha or "?")[:12], dec or "?", tus, edges, per, flag))

    healthy = [r for r in rows if r[1] and r[3] >= THIN]
    thin = [r for r in rows if r[1] and r[3] < THIN]
    print()
    if thin and healthy:
        print("  %d version(s) look healthy and %d look thin, on the SAME project -- so the"
              % (len(healthy), len(thin)))
        print("  thin ones are a broken parse, not a property of the code:")
        print("      healthy: %s" % ", ".join("%s (%.0f/TU)" % (r[0], r[3]) for r in healthy))
        print("      thin   : %s" % ", ".join("%s (%.1f/TU)" % (r[0], r[3]) for r in thin))
        print("  A thin map under-selects TUs for the narrowed parse, silently. Regenerate")
        print("  those versions, or avoid them as baselines.")
    elif thin:
        print("  EVERY version's map is thin. Either this project really does barely use")
        print("  in-repo headers, or #include resolution is failing for all runs -- check")
        print("  the include paths (model/clang_include_paths.json) before trusting a")
        print("  narrowed parse here.")
    else:
        print("  every version's map looks complete.")

    if a.version:
        with eng.connect() as cx:
            m = model_store.load_tu_includes(cx, a.version) or {}
        print()
        print("=" * 78)
        print("THINNEST TUs in %s" % a.version)
        print("=" * 78)
        if not m:
            print("  no include map stored for this version.")
            return 1
        for tu, hdrs in sorted(m.items(), key=lambda kv: len(kv[1] or []))[:a.limit]:
            print("  %4d  %s" % (len(hdrs or []), tu))
        empty = sum(1 for v in m.values() if not v)
        print()
        print("  %d of %d TU(s) record ZERO in-repo headers." % (empty, len(m)))
        if empty:
            print("  A .cpp that includes nothing from its own repo is unusual; that many")
            print("  of them means the headers were not found, not that they are absent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
