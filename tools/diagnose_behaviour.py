"""Why is `_behaviour_pngs.json` empty when the .mmd/.png files are right there?

The view writes a row per diagram only if it agrees with the GENERATOR about which
caller each diagram is for. They reach that answer by different routes:

    generator : components[<name>]["units"] -> the unit's component
    view      : the fid prefix, i.e. "Comp|Unit|fn|sig".split("|")[0]

and the loop that pairs them is positional:

    for idx, mmd_path in enumerate(mmd_paths):
        if idx >= len(external_callers):
            break            # <- files already on disk, no row recorded

So a diagram gets written and then dropped whenever the generator calls a caller
"external" and the view does not. This prints both answers side by side for a real
version, and decodes the .mmd filenames (which encode target__caller) so you can see
exactly which pairing was rejected and why.

    python tools/diagnose_behaviour.py --project-id <pid> --version-id <vid>
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def _resolve_fid(part: str, funcs: dict) -> str:
    """The full function id whose flattened form starts this half of the filename."""
    best = ""
    for fid in funcs:
        flat = fid.replace("|", "_").replace(",", "_")
        if part == flat and len(fid) > len(best):
            best = fid
    if best:
        return best
    for fid in funcs:                       # signatures flatten lossily; prefix match
        flat = fid.replace("|", "_").replace(",", "_")
        if part.startswith(flat) and len(fid) > len(best):
            best = fid
    return best


def _fid_from_filename(stem: str, units: dict) -> tuple:
    """A .mmd is named <target-fid>__<caller-fid> with '|' and ',' flattened to '_'.

    That is lossy, so match back against the real unit keys rather than guessing where
    the separators were: the longest unit key whose flattened form prefixes the stem is
    the owner.
    """
    def owner(part):
        best = ""
        for uk in units:
            flat = uk.replace("|", "_")
            if part.startswith(flat + "_") and len(flat) > len(best):
                best = uk
        return best or "?"
    if "__" in stem:
        t, c = stem.split("__", 1)
        return owner(t), owner(c)
    return owner(stem), "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--version-id", required=True)
    ap.add_argument("--output", help="output dir (default: the version's)")
    a = ap.parse_args()

    from core.db import get_engine
    from core import model_store
    with get_engine().connect() as cx:
        comps = model_store.load_components(cx, a.version_id)
        units = model_store.load_units(cx, a.version_id)
        funcs = model_store.load_functions(cx, a.version_id)

    print("=" * 72)
    print("MODEL")
    print("=" * 72)
    print(f"  components {len(comps)}   units {len(units)}   functions {len(funcs)}")

    gen_map = {u: c for c, d in comps.items() for u in d.get("units", [])}
    unmapped = [u for u in units if u not in gen_map]
    mismatched = [(u, u.split("|")[0], gen_map[u])
                  for u in units if u in gen_map and gen_map[u] != u.split("|")[0]]

    print()
    print(f"  units the generator cannot place (component has no row): {len(unmapped)}")
    for u in unmapped[:15]:
        print(f"      {u}   -> generator sees 'Unknown', view sees {u.split('|')[0]!r}")
    print(f"  units where the two disagree                           : {len(mismatched)}")
    for u, v, g in mismatched[:15]:
        print(f"      {u}   view={v!r}  generator={g!r}")
    if not unmapped and not mismatched:
        print("      (none — the two agree everywhere, so this is NOT the cause)")

    out = a.output or os.path.join(_ROOT, "workspaces", a.project_id, "versions",
                                   a.version_id, "output")
    print()
    print("=" * 72)
    print(f"DIAGRAMS ON DISK   {out}")
    print("=" * 72)
    if not os.path.isdir(out):
        print("  no output directory — pass --output")
        return 2

    total_mmd = total_rows = 0
    for comp_dir in sorted(os.listdir(out)):
        bd = os.path.join(out, comp_dir, "behaviour_diagrams")
        if not os.path.isdir(bd):
            continue
        mmds = sorted(f for f in os.listdir(bd) if f.endswith(".mmd"))
        pj = os.path.join(bd, "_behaviour_pngs.json")
        rows = {}
        if os.path.isfile(pj):
            try:
                rows = json.load(open(pj, encoding="utf-8")).get("_docxRows", {})
            except Exception:
                pass
        n_rows = sum(len(v) for u in rows.values() for v in u.values())
        total_mmd += len(mmds)
        total_rows += n_rows
        if not mmds and not n_rows:
            continue
        print(f"\n  {comp_dir}:  {len(mmds)} .mmd   {n_rows} row(s) recorded"
              f"{'   <== FILES BUT NO ROWS' if mmds and not n_rows else ''}")
        for f in mmds[:20]:
            tgt, clr = _fid_from_filename(os.path.splitext(f)[0], units)
            tc, cc = tgt.split("|")[0], clr.split("|")[0]
            gt = gen_map.get(tgt, "Unknown")
            gc = gen_map.get(clr, "Unknown")
            view_external = (cc != tc)
            gen_external = (gc != gt)
            verdict = "ok" if view_external else "DROPPED: same component to the view"
            print(f"      target {tgt}")
            print(f"      caller {clr}")
            print(f"        view      : {cc!r} vs {tc!r} -> external={view_external}")
            print(f"        generator : {gc!r} vs {gt!r} -> external={gen_external}   {verdict}")
            # tgt is a UNIT key; the callers live on the FUNCTION, so resolve it.
            tfid = _resolve_fid(os.path.splitext(f)[0].split("__", 1)[0], funcs)
            cb = (funcs.get(tfid) or {}).get("calledByIds") or []
            print(f"        target fn : {tfid or '(not resolved)'}")
            print(f"        calledBy({len(cb)}) components: "
                  f"{sorted({c.split(chr(124))[0] for c in cb}) or 'NONE -- nothing calls it'}")

    print()
    print("=" * 72)
    print(f"TOTAL  {total_mmd} diagram file(s), {total_rows} row(s) in _docxRows")
    if total_mmd and not total_rows:
        print("  -> every diagram was written and then dropped. The 'view' lines above say why.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
