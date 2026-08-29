"""Is this version's model complete, or was it parsed by a build that lost fields?

Answers one question: re-render from the stored model, or re-parse it?

  parameters / returnExpr / global access at 0 means the parse predates the fixes in
  7ae0d1d and the model itself is wrong -- re-run `generate ... --full`.
  A missing address_taken snapshot means this version is unsafe as an INCREMENTAL
  BASELINE (pointer-table functions would flip private); the version's own model is fine.

    python tools/check_model_health.py --project-id <pid> --version-id <vid>
"""
import argparse, os, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--version-id", required=True)
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine
    from core import model_store

    with get_engine().connect() as cx:
        funcs = model_store.load_functions(cx, a.version_id)
        snaps = [r[0] for r in cx.execute(sa.text(
            "select name from parse_snapshots where version_id=:v"), {"v": a.version_id})]

    n = len(funcs)
    if not n:
        print(f"no model stored for {a.version_id!r} -- run `generate` first.")
        return 2

    def have(field):
        return sum(1 for f in funcs.values() if f.get(field))

    checks = [("parameters", have("parameters")), ("returnExpr", have("returnExpr")),
              ("readsGlobalIds", have("readsGlobalIds")),
              ("writesGlobalIds", have("writesGlobalIds")),
              ("addressTakenByUnits", have("addressTakenByUnits"))]
    print(f"version {a.version_id}: {n} functions")
    for name, c in checks:
        print(f"   {name:<22} {c}")

    lost = [nm for nm, c in checks[:4] if c == 0]
    print()
    if lost:
        print("MODEL IS INCOMPLETE -- " + ", ".join(lost) + " empty across every function.")
        print("  Parsed by a build that dropped them. Re-parse:")
        print(f"    python analyzer.py generate --project-id {a.project_id} "
              f"--version-id {a.version_id} --branch <b> --commit <sha> --scope <s> --full")
    else:
        print("MODEL LOOKS COMPLETE -- re-render without re-parsing:")
        print(f"    python analyzer.py reexport --project-id {a.project_id} "
              f"--version-id {a.version_id} --unit <UnitName>")

    if not any("address_taken" in s for s in snaps):
        print()
        print("NOTE: no address_taken parse snapshot on this version.")
        print("  Its own model is fine, but do NOT use it as an incremental baseline --")
        print("  pointer-table functions would flip private. Use --full for the next version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
