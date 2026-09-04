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

# Below this many in-repo headers per SOURCE TU, a map is almost certainly incomplete
# rather than describing a genuinely include-light project.
THIN = 5.0

# The map is keyed by every file the parser opened as a translation unit, and `-x c++`
# means a .h can be one. Averaging the two together is meaningless: a header parsed on its
# own legitimately includes little, so a codebase with many of them drags the average down
# and looks broken. Only the .c/.cpp figure says whether #include resolution is working.
_SRC_EXTS = (".cpp", ".cc", ".cxx", ".c", ".c++")


def _is_source(path: str) -> bool:
    return (path or "").lower().endswith(_SRC_EXTS)


def _stats(m):
    """(tus, edges, per-tu) over the whole map, and again over source files only."""
    src = {k: v for k, v in m.items() if _is_source(k)}
    def agg(d):
        n = len(d)
        e = sum(len(v or []) for v in d.values())
        return n, e, (e / n if n else 0.0), sum(1 for v in d.values() if not v)
    return agg(m), agg(src)


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
    print("  %-8s %-13s %-12s %14s %20s %7s" %
          ("version", "commit", "decision", "all TUs", "SOURCE files only", "0-hdr"))
    print("  %-8s %-13s %-12s %6s %7s %8s %11s %7s" %
          ("", "", "", "TUs", "per TU", "files", "edges", "per file"))
    rows = []
    for vid, sha, dec in versions:
        with eng.connect() as cx:
            m = model_store.load_tu_includes(cx, vid) or {}
        (tus, edges, per, _z), (s_n, s_e, s_per, s_zero) = _stats(m)
        rows.append((vid, tus, edges, per, s_n, s_per, s_zero))
        flag = ""
        if not tus:
            flag = "  <- no map at all"
        elif s_n and s_per < THIN:
            flag = "  <- THIN"
        print("  %-8s %-13s %-12s %6d %7.1f %8d %11d %7.1f  %d%s"
              % (vid, (sha or "?")[:12], dec or "?", tus, per, s_n, s_e, s_per,
                 s_zero, flag))
    print()
    print("  'SOURCE files only' counts .c/.cpp translation units. A .h parsed on its own")
    print("  is also a TU here and legitimately includes little, so it dilutes the overall")
    print("  average -- the per-file figure for sources is the one that means something.")
    print("  '0-hdr' = source files recording NO in-repo header at all.")

    healthy = [r for r in rows if r[4] and r[5] >= THIN]
    thin = [r for r in rows if r[4] and r[5] < THIN]
    print()
    if thin and healthy:
        print("  %d version(s) look healthy and %d look thin, on the SAME project -- so the"
              % (len(healthy), len(thin)))
        print("  thin ones are a broken parse, not a property of the code:")
        print("      healthy: %s" % ", ".join("%s (%.0f/file)" % (r[0], r[5]) for r in healthy))
        print("      thin   : %s" % ", ".join("%s (%.1f/file)" % (r[0], r[5]) for r in thin))
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
        # Split by kind: a header with no includes of its own is ordinary, a .cpp with
        # none is not. Reporting them together turned an ordinary number into an alarming
        # one and said nothing about whether resolution actually works.
        src_zero = sorted(k for k, v in m.items() if _is_source(k) and not v)
        hdr_zero = sorted(k for k, v in m.items() if not _is_source(k) and not v)
        print("  thinnest SOURCE files:")
        srcs = sorted(((k, v) for k, v in m.items() if _is_source(k)),
                      key=lambda kv: len(kv[1] or []))
        for tu, hdrs in srcs[:a.limit]:
            print("      %4d  %s" % (len(hdrs or []), tu))
        print()
        print("  %d of %d SOURCE file(s) record ZERO in-repo headers."
              % (len(src_zero), sum(1 for k in m if _is_source(k))))
        print("  %d of %d HEADER TU(s) record zero -- ordinary, they are parsed standalone."
              % (len(hdr_zero), sum(1 for k in m if not _is_source(k))))
        if src_zero:
            print()
            print("  A .c/.cpp including nothing from its own repo is the suspicious case:")
            for k in src_zero[:a.limit]:
                print("      %s" % k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
