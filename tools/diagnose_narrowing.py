"""Did the narrowed parse re-read every file it needed to?

The narrowed parse decides what to re-parse from the BASELINE's include map: a TU is
re-parsed iff it, or something in its recorded include closure, appears in the git diff.
That map is a snapshot of the code as it was at the baseline. If an include edge was
added after the baseline -- B.c starts including X.h -- the map never learns it, so an
edit to X.h leaves B.c unparsed. B.c's functions keep their baseline source_hash, are
classified UNCHANGED, and no later phase can recover them. Nothing errors.

The only way to see this is to compare against a run of the SAME commit that parsed
everything (--no-narrowed-parse or --full). That version is ground truth:

    same commit  =>  every function's source_hash MUST match.

Any function whose hash differs is one the narrowed parse missed. This reports those
first (the WHAT), then compares the two versions' include maps to explain WHY.

    python tools/diagnose_narrowing.py --project-id P --baseline v1 --narrowed v3 --full v4
    python tools/diagnose_narrowing.py --project-id P --baseline v1 --narrowed v3 --full v4 --name myFunc
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

_TAB = chr(9)
_HEADER_EXTS = (".h", ".hpp", ".hh", ".hxx", ".inc", ".ipp", ".tcc")


def _checkout_dir(pid, *shas):
    """The repo checkout a version was parsed from, if it is still on this machine."""
    wroot = os.path.join(_ROOT, "workspaces", pid)
    for sha in shas:
        if not sha:
            continue
        d = os.path.join(wroot, sha[:16])
        if os.path.isdir(os.path.join(d, ".git")):
            return d
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--baseline", required=True, help="the version the narrowed run built on")
    ap.add_argument("--narrowed", required=True, help="the version produced by a narrowed parse")
    ap.add_argument("--full", required=True,
                    help="a version of the SAME commit parsed in full (--no-narrowed-parse)")
    ap.add_argument("--name", help="also trace one function whose key contains this")
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine
    from core import model_store
    from incremental.affected import affected_tus, _norm

    eng = get_engine()

    def meta(vid):
        with eng.connect() as cx:
            r = cx.execute(sa.text("select commit_sha, decision, baseline_version_id "
                                   "from versions where id = :v"), {"v": vid}).fetchone()
        return (r[0], r[1], r[2]) if r else (None, None, None)

    def fn_rows(vid):
        """{entity_key: (source_hash, file)} for every function in the version."""
        q = ("select e.entity_key, v.source_hash, e.file_path from entity_versions v "
             "join entities e on e.entity_id = v.entity_id "
             "where v.version_id = :v and e.kind = 'function'")
        with eng.connect() as cx:
            return {r[0]: (r[1], r[2]) for r in cx.execute(sa.text(q), {"v": vid})}

    def includes(vid):
        with eng.connect() as cx:
            return model_store.load_tu_includes(cx, vid) or {}

    sha_b, dec_b, _ = meta(a.baseline)
    sha_n, dec_n, base_of_n = meta(a.narrowed)
    sha_f, dec_f, base_of_f = meta(a.full)

    print("=" * 78)
    print("VERSIONS")
    print("=" * 78)
    for label, vid, sha, dec, bs in (("baseline", a.baseline, sha_b, dec_b, None),
                                     ("narrowed", a.narrowed, sha_n, dec_n, base_of_n),
                                     ("full", a.full, sha_f, dec_f, base_of_f)):
        print("  %-9s %-10s commit=%-14s decision=%-12s baseline=%s"
              % (label, vid, (sha or "?")[:12], dec or "?", bs or "-"))

    if not (sha_n and sha_f):
        print()
        print("  a commit sha is missing -- check the version ids.")
        return 2
    if sha_n != sha_f:
        print()
        print("  !! --narrowed and --full are DIFFERENT commits, so a hash difference")
        print("     proves nothing. Re-run the full parse on %s." % sha_n[:12])
        return 2

    # ---- WHAT was missed: same commit, so any hash difference is a miss ---------------
    hn, hf = fn_rows(a.narrowed), fn_rows(a.full)
    print()
    print("=" * 78)
    print("WHAT the narrowed parse missed  (same commit -> hashes must be identical)")
    print("=" * 78)
    print("  functions: narrowed=%d  full=%d" % (len(hn), len(hf)))

    differing = sorted(k for k in hf if k in hn and hf[k][0] != hn[k][0])
    only_full = sorted(k for k in hf if k not in hn)
    only_narrow = sorted(k for k in hn if k not in hf)

    missed_files = sorted({(hf[k][1] or "?") for k in differing} |
                          {(hf[k][1] or "?") for k in only_full})
    if not (differing or only_full or only_narrow):
        print()
        print("  the two models are IDENTICAL. The narrowed parse missed nothing --")
        print("  whatever is wrong with the document is downstream of the parse.")
    else:
        print("  stale hash  %d      missing entirely %d      extra %d"
              % (len(differing), len(only_full), len(only_narrow)))
        for k in differing[:a.limit]:
            print("      stale:   %s   [%s]" % (k, hf[k][1] or "?"))
        for k in only_full[:a.limit]:
            print("      absent:  %s   [%s]" % (k, hf[k][1] or "?"))
        print()
        print("  %d source file(s) were not re-parsed but should have been:" % len(missed_files))
        for f in missed_files[:a.limit]:
            print("      %s" % f)

    # ---- WHY: what the two include maps say ------------------------------------------
    inc_b, inc_f = includes(a.baseline), includes(a.full)
    print()
    print("=" * 78)
    print("WHY  the baseline's include map vs the truth at this commit")
    print("=" * 78)
    print("  %-10s %d TUs, %d include edges"
          % (a.baseline, len(inc_b), sum(len(v or []) for v in inc_b.values())))
    print("  %-10s %d TUs, %d include edges"
          % (a.full, len(inc_f), sum(len(v or []) for v in inc_f.values())))
    if not inc_b:
        print("  the baseline has NO include map -- a narrowed parse should have refused.")
    if not inc_f:
        print("  the full version stored no include map -- cannot compare. Stopping here.")
        return 1 if (differing or only_full) else 0

    checkout = _checkout_dir(a.project_id, sha_f, sha_n, sha_b)
    if not checkout:
        print("  no checkout under workspaces/%s -- cannot read the diff." % a.project_id)
        return 1 if (differing or only_full) else 0

    r = subprocess.run(["git", "-C", checkout, "diff", "--name-status",
                        "%s..%s" % (sha_b, sha_n)],
                       capture_output=True, text=True, shell=(os.name == "nt"))
    if r.returncode != 0:
        print("  git diff failed: %s" % (r.stderr or "").strip()[:200])
        return 1 if (differing or only_full) else 0

    status = []
    for ln in r.stdout.splitlines():
        cols = ln.split(_TAB)
        if len(cols) >= 2 and cols[0]:
            status.append((cols[0][:1], cols[-1]))
    changed = [p for _s, p in status]
    print("  %d file(s) changed between %s and %s" % (len(changed), a.baseline, a.narrowed))

    aff_b = affected_tus(changed, inc_b)     # what the narrowed run actually re-parsed
    aff_f = affected_tus(changed, inc_f)     # what it should have re-parsed
    only_truth = sorted(set(_norm(t) for t in aff_f) - set(_norm(t) for t in aff_b))
    print("  TUs selected using the baseline map : %d" % len(aff_b))
    print("  TUs selected using this commit's map: %d" % len(aff_f))
    if only_truth:
        print()
        print("  *** %d TU(s) the baseline map did NOT select but the current map does."
              % len(only_truth))
        print("      These are files whose #include set grew after the baseline was taken:")
        for t in only_truth[:a.limit]:
            print("      %s" % t)
    else:
        print()
        print("  both maps select the same TUs -- a stale include map is NOT the cause.")

    # Per changed header: how many TUs each map thinks include it. A header that gained
    # includers since the baseline is exactly the silent-miss case.
    hdr_rows = []
    for _s, p in status:
        if p.lower().endswith(_HEADER_EXTS):
            n = _norm(p)
            cb = sum(1 for v in inc_b.values() if n in {_norm(x) for x in (v or [])})
            cf = sum(1 for v in inc_f.values() if n in {_norm(x) for x in (v or [])})
            if cb != cf:
                hdr_rows.append((p, cb, cf))
    if hdr_rows:
        print()
        print("  changed headers whose includer count moved (baseline -> now):")
        for p, cb, cf in hdr_rows[:a.limit]:
            print("      %-58s %d -> %d" % (p[-58:], cb, cf))

    # ---- one named function ----------------------------------------------------------
    if a.name:
        print()
        print("=" * 78)
        print("TRACE  %s" % a.name)
        print("=" * 78)
        hits = [k for k in hf if a.name.lower() in k.lower()]
        if not hits:
            print("  no function matching that name in %s." % a.full)
        for k in hits[:10]:
            f = hf[k][1] or "?"
            same = (k in hn and hn[k][0] == hf[k][0])
            print("  %s" % k)
            print("      file            : %s" % f)
            print("      hash matches %-4s: %s" % (a.full, "yes" if same else "NO -- missed"))
            n = _norm(f)
            print("      a TU in the baseline map : %s"
                  % ("yes" if n in {_norm(t) for t in inc_b} else "no"))
            print("      selected for re-parse    : %s"
                  % ("yes" if n in {_norm(t) for t in aff_b} else "NO"))
            includers_b = sorted(t for t, v in inc_b.items() if n in {_norm(x) for x in (v or [])})
            includers_f = sorted(t for t, v in inc_f.items() if n in {_norm(x) for x in (v or [])})
            if includers_b or includers_f:
                print("      TUs including this file  : %d at baseline, %d now"
                      % (len(includers_b), len(includers_f)))

    return 1 if (differing or only_full) else 0


if __name__ == "__main__":
    raise SystemExit(main())
