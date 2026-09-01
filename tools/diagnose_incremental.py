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


def _output_components(pid, vid):
    """Component directories this version actually rendered. A version's MODEL is whole,
    but its OUTPUT only covers the scope that was generated -- so a changed function in a
    component that is not here was never in this document to begin with."""
    base = os.path.join(_version_dir(pid, vid), "output")
    if not os.path.isdir(base):
        return set()
    return {d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))}


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

    # ---- HOP 0: what git says changed, vs what the parse noticed ----------------------
    # The narrowed parse re-parses only the translation units it believes are affected. If
    # it misses one, every function in that file keeps its baseline hash and looks
    # unchanged forever -- no error, and nothing downstream can recover it. So compare the
    # commit's own file list against the files whose functions actually moved.
    import subprocess
    with get_engine().connect() as cx:
        shas = {r[0]: r[1] for r in cx.execute(sa.text(
            "select id, commit_sha from versions where id in (:a, :b)"),
            {"a": a.baseline, "b": a.target})}
    sha_b, sha_t = shas.get(a.baseline), shas.get(a.target)
    print()
    print("=" * 74)
    print("HOP 0  the commit's changed files vs the files the parse noticed")
    print("=" * 74)
    print("  %s = %s" % (a.baseline, (sha_b or "?")[:12]))
    print("  %s = %s" % (a.target, (sha_t or "?")[:12]))
    if sha_b and sha_t and sha_b == sha_t:
        print("  the two versions are the SAME commit -- nothing can have changed.")
    elif sha_b and sha_t:
        checkout = None
        wroot = os.path.join(_ROOT, "workspaces", a.project_id)
        for cand in (sha_t[:16], sha_b[:16]):
            d = os.path.join(wroot, cand)
            if os.path.isdir(os.path.join(d, ".git")):
                checkout = d
                break
        if not checkout:
            print("  no checkout found under %s -- cannot read the diff." % wroot)
        else:
            r = subprocess.run(["git", "-C", checkout, "diff", "--name-only", sha_b, sha_t],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print("  git diff failed: %s" % (r.stderr or "").strip()[:160])
                print("  (the baseline commit may not be present in this checkout)")
            else:
                files = [f.strip() for f in r.stdout.splitlines() if f.strip()]
                print("  git says %d file(s) changed between them" % len(files))
                # which files DID produce a hash change?
                noticed = set()
                with get_engine().connect() as cx:
                    q = ("select e.entity_key, v.file from entity_versions v "
                         "join entities e on e.entity_id = v.entity_id "
                         "where v.version_id = :v and e.kind = 'function'")
                    fmap = {r2[0]: (r2[1] or "") for r2 in cx.execute(sa.text(q), {"v": a.target})}
                for k in changed + added:
                    f = fmap.get(k)
                    if f:
                        noticed.add(f.replace("\\", "/").lstrip("./"))
                srcs = [f for f in files
                        if os.path.splitext(f)[1].lower() in (".c", ".cpp", ".cc", ".h", ".hpp")]
                silent = [f for f in srcs
                          if not any(n.endswith(f) or f.endswith(n) for n in noticed)]
                print("  of those, %d are C/C++ sources" % len(srcs))
                print("  files whose functions the parse noticed : %d" % len(noticed))
                if silent:
                    print()
                    print("  *** %d changed source file(s) produced NO function hash change:"
                          % len(silent))
                    for f in silent[:12]:
                        print("        %s" % f)
                    print("  Each was edited in the commit and produced no hash change.")
                    print("  Expected for a file OUTSIDE the analysed layers -- it is never")
                    print("  parsed. For a file inside them this is the narrowed parse missing")
                    print("  it: re-run the target with --full and compare again. If the hashes")
                    print("  move under --full, the narrowed parse is the fault.")

    # ---- a NAMED function, whether or not it was detected as changed ------------------
    # The question that actually matters is "I edited X -- what happened to it?", and X may
    # not be in the changed set at all. Reporting only within `changed` cannot answer that,
    # and silently looking past the one function asked about is how this tool sent us
    # chasing five functions nobody had touched.
    if a.name:
        hits = [k for k in ht if a.name.lower() in k.lower()]
        print()
        print("=" * 74)
        print("NAMED  %r" % a.name)
        print("=" * 74)
        if not hits:
            print("  no function in the target model matches that name at all.")
            near = [k for k in ht if a.name.lower()[:6] in k.lower()][:5]
            if near:
                print("  closest: %s" % ", ".join(near))
        for k in sorted(hits)[:10]:
            hb_, ht_ = hb.get(k), ht.get(k)
            if k not in hb:
                verdict = "NEW in the target"
            elif hb_ != ht_:
                verdict = "CHANGED  (source_hash differs)"
            else:
                verdict = "UNCHANGED  <== the parse sees identical source"
            print("  %s" % k)
            print("      baseline hash : %s" % (hb_ or "(absent)"))
            print("      target   hash : %s" % (ht_ or "(absent)"))
            print("      -> %s" % verdict)
            if k in hb and hb_ == ht_:
                print("      If you edited this function, the parse never saw the edit. Either the")
                print("      commit does not contain it, or the narrowed parse did not re-parse")
                print("      its file. Re-run the target with --full to tell those apart.")

    # ---- HOPS 3 and 4 -----------------------------------------------------------------
    db_, dt = _flowchart_dots(a.project_id, a.baseline), _flowchart_dots(a.project_id, a.target)
    pb, pt = _pngs(a.project_id, a.baseline), _pngs(a.project_id, a.target)
    comps_b, comps_t = _output_components(a.project_id, a.baseline), _output_components(a.project_id, a.target)
    print()
    print("=" * 74)
    print("HOPS 3-4  per changed function: did the DOT and the PNG follow?")
    print("=" * 74)
    if not dt:
        print("  the target has no flowchart JSON at all -- is views.flowcharts on?")
    shown, stuck, png_stuck, examined = 0, [], [], 0
    out_of_scope, no_entry = [], []
    for k in changed + added:
        if a.name and a.name.lower() not in k.lower():
            continue
        examined += 1
        parts = k.split("|")
        fn = parts[2] if len(parts) > 2 else k
        comp = parts[0] if parts else ""
        cands = [key for key in dt if key[1] == fn]
        if not cands:
            if comp and comps_t and comp not in comps_t:
                out_of_scope.append((fn, comp))
                if shown < a.limit:
                    print("  %s: component %r is NOT in this version's output -- out of scope"
                          % (fn, comp))
                    shown += 1
            else:
                no_entry.append((fn, comp))
                if shown < a.limit:
                    print("  %s: component %r IS in scope but has no flowchart entry" % (fn, comp))
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
    elif out_of_scope and not stuck and not png_stuck and not no_entry:
        # The commonest false alarm, and not a defect at all: a version's MODEL is whole
        # but its OUTPUT covers only the scope that was generated. Editing a function in
        # a component outside that scope changes the model and cannot change a document
        # that never contained it.
        print("  OUT OF SCOPE -- not a pipeline fault.")
        print("  %d changed function(s) live in components this version did not render:"
              % len(out_of_scope))
        for fn, c in out_of_scope[:8]:
            print("      %-46s component %r" % (fn, c))
        print()
        print("  rendered here : %s" % (", ".join(sorted(comps_t)) or "(none)"))
        print("  -> re-run with a --scope that covers those components, e.g."
              " --scope \"component:%s\"" % out_of_scope[0][1])
    elif no_entry:
        print("  %d changed function(s) are IN scope but have no flowchart entry:"
              % len(no_entry))
        for fn, c in no_entry[:8]:
            print("      %-46s component %r" % (fn, c))
        print("  The view never produced a diagram for them -- check views.flowcharts,")
        print("  and whether they are private (tools/why_private.py).")
    else:
        print("  Every changed function got a new DOT and a new PNG. If the document still")
        print("  looks wrong, the export embedded something else -- or the file being read")
        print("  is not this version's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
