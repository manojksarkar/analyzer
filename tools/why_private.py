"""Why did this function come out private?

A function is public if it has a cross-file caller, OR if it is published by a file-scope
pointer table (`addressTakenByUnits`). Nothing CALLS a table-published function by name, so
that field is the only thing holding it public -- and it has to survive three hops:

    parser sets it  ->  persist_functions stores it  ->  model_deriver reads it

This walks all three for one version and says which hop lost it, so the answer is a fact
rather than a guess.

    python tools/why_private.py --project-id <pid> --version-id <vid>
    python tools/why_private.py --project-id <pid> --version-id <vid> --name opsAdd
"""
import argparse, json, os, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--version-id", required=True)
    ap.add_argument("--name", help="only functions whose key contains this")
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine
    from core import model_store

    with get_engine().connect() as cx:
        funcs = model_store.load_functions(cx, a.version_id)
        rows = {r[0]: (r[1], r[2]) for r in cx.execute(sa.text(
            "select e.entity_key, v.visibility, v.interface_id "
            "from entity_versions v join entities e on e.entity_id=v.entity_id "
            "where v.version_id=:v and e.kind='function'"), {"v": a.version_id})}
        snap = cx.execute(sa.text(
            "select payload from parse_snapshots where version_id=:v "
            "and name like '%address_taken%'"), {"v": a.version_id}).first()

    # HOP 1 -- what the parser found, as captured in the parse snapshot
    recs = []
    if snap and snap[0]:
        try:
            recs = json.loads(snap[0]) if isinstance(snap[0], str) else snap[0]
        except Exception:
            recs = []
    print("=" * 70)
    print("HOP 1  parser -> parse snapshot")
    print("=" * 70)
    if snap is None:
        print("  NO address_taken snapshot row for this version.")
        print("  Harmless for THIS version's own model (a full parse sets the field")
        print("  directly on the function), but it cannot serve as an incremental baseline.")
    else:
        print(f"  {len(recs)} registration(s) recorded by the parser")
        for r in recs[:5]:
            print(f"      {r}")

    # HOP 2 -- what survived into the model
    with_field = {k: v.get("addressTakenByUnits") for k, v in funcs.items()
                  if v.get("addressTakenByUnits")}
    print()
    print("=" * 70)
    print("HOP 2  stored model")
    print("=" * 70)
    print(f"  {len(funcs)} functions, {len(with_field)} carry addressTakenByUnits")
    if recs and not with_field:
        print("  *** the parser found registrations but NONE survived into the model.")
        print("      That is the store dropping the field (see _FN_PAYLOAD_FIELDS).")
    if not recs and not with_field and snap is not None:
        print("  the parser found no pointer tables in this source at all.")

    # HOP 3 -- what the deriver concluded
    print()
    print("=" * 70)
    print("HOP 3  derived visibility")
    print("=" * 70)
    shown = 0
    suspects = []
    for fid, f in sorted(funcs.items()):
        if a.name and a.name.lower() not in fid.lower():
            continue
        vis, iid = rows.get(fid, ("?", "?"))
        callers = f.get("calledByIds") or []
        atu = f.get("addressTakenByUnits")
        # the shape the bug is about: no caller, no table record, so private
        if vis == "private" and not callers and not atu:
            suspects.append(fid)
        if a.name or (vis == "private" and not callers):
            if shown < a.limit:
                print(f"  {fid}")
                print(f"      visibility={vis}  interface_id={iid}")
                print(f"      calledBy={len(callers)}  addressTakenByUnits={atu}")
                shown += 1
    if not a.name:
        print()
        print(f"  {len(suspects)} function(s) are private with NO caller and NO table record.")
        print("  If any of those should be public, they are published by a table the parser")
        print("  did not recognise -- send one of their names and its C++ declaration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
