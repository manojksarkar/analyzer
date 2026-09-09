"""List a project's unit names and report unit-key COLLISIONS.

Read-only. Changes nothing, needs no LLM, and can run before a project has ever
been generated.

A unit key is `<componentId>|<basename without extension>` — it carries no
directory. Two source files with the same basename in different directories of ONE
component therefore collapse to one key, and the deriver folds them into a single
unit carrying both files' functions but only the first file's path and name. The
document then describes a unit that does not exist. Nothing fails; the run is green.

    Ftl/Core/Table.cpp    ->  Ftl|Table
    Ftl/Cache/Table.cpp   ->  Ftl|Table     <- same identity

`Foo.cpp` + `Foo.h` sharing a stem in the SAME directory is a unit's two halves and
is never a collision. The check compares directories, not file names.

Two sources, because the useful moment differs:

  --project-id P [--version-id V]   the STORED model (Postgres). What was actually
                                    built. Needs a generated version.
  --path <checkout>                 the FILESYSTEM, resolved through the config's
                                    component map. Answers "would this tree
                                    collide?" before any parse — seconds, no DB.

Filters (`--layer`, `--component`, `--unit`) narrow either source; they accept a
bare name or a layer-qualified id and match case- and space-insensitively.

    python tools/check_unit_names.py --path <checkout>
    python tools/check_unit_names.py --path <checkout> --layer Ftl
    python tools/check_unit_names.py --project-id P --collisions-only
    python tools/check_unit_names.py --project-id P --version-id v7 --component Ftl.Cache

Exit 0 = no collisions. 1 = collisions found. 2 = could not run.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

_SRC_EXTS = (".cpp", ".cc", ".cxx", ".c", ".c++", ".h", ".hpp", ".hh")


def _ident(name: str) -> str:
    """Space- and case-insensitive comparison form, as everywhere else."""
    return (name or "").strip().replace(" ", "-").casefold()


def _matches(value: str, wanted: str) -> bool:
    """True when `value` is what the filter asked for.

    A component id is layer-qualified (`Ftl.Cache`), so `--component Cache` has to
    match it as well as the full id — the caller should not have to know which form
    the model stored.
    """
    if not wanted:
        return True
    v, w = _ident(value), _ident(wanted)
    return v == w or v.endswith("." + w)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _from_filesystem(base_path: str):
    """[(component_id, unit_name, rel_dir, rel_file)] resolved through the config."""
    import utils
    from core.config import app_config

    utils.init_component_mapping(app_config())
    rows = []
    for root, dirnames, files in os.walk(base_path):
        dirnames.sort()
        for fn in sorted(files):
            if not fn.lower().endswith(_SRC_EXTS):
                continue
            rel = os.path.relpath(os.path.join(root, fn), base_path).replace("\\", "/")
            component = utils._resolve_component_from_rel(rel)
            if component == "unknown":
                continue            # outside every configured component: not parsed
            rows.append((component, os.path.splitext(fn)[0],
                         os.path.dirname(rel) or ".", rel))
    return rows


def _from_database(project_id: str, version_id: str | None):
    """[(component_id, unit_name, stored_path, stored_path)] from model_units."""
    import sqlalchemy as sa
    from core.db import get_engine
    from api.db.postgres import schema as s

    eng = get_engine()
    with eng.connect() as cx:
        if not version_id:
            row = cx.execute(sa.select(s.versions.c.id)
                             .where(s.versions.c.project_id == project_id)
                             .order_by(s.versions.c.created_at.desc()).limit(1)).first()
            if not row:
                raise SystemExit(f"no versions for project {project_id!r}")
            version_id = row[0]
        found = cx.execute(sa.select(s.model_units.c.unit_key, s.model_units.c.component,
                                     s.model_units.c.name, s.model_units.c.path)
                           .where(s.model_units.c.version_id == version_id)).all()
    if not found:
        raise SystemExit(f"version {version_id!r} has no stored units — generate it first")

    rows = []
    for r in found:
        unit = r.name or (r.unit_key or "").split("|")[-1]
        path = (r.path or "").replace("\\", "/")
        rows.append((r.component or "", unit, os.path.dirname(path) or ".", path))
    return rows, version_id


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--project-id", help="read the STORED model for this project")
    src.add_argument("--path", help="scan this checkout instead (no DB, no parse needed)")
    ap.add_argument("--version-id", help="with --project-id; default the newest version")
    ap.add_argument("--layer", help="only units in this layer")
    ap.add_argument("--component", help="only this component (bare name or Layer.Name)")
    ap.add_argument("--unit", help="only this unit name")
    ap.add_argument("--collisions-only", action="store_true",
                    help="skip the full listing; report only the clashes")
    a = ap.parse_args(argv)

    version_id = None
    try:
        if a.path:
            if not os.path.isdir(a.path):
                print(f"not a directory: {a.path}", file=sys.stderr)
                return 2
            rows = _from_filesystem(a.path)
            origin = f"filesystem {a.path}"
        else:
            rows, version_id = _from_database(a.project_id, a.version_id)
            origin = f"project {a.project_id} version {version_id}"
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    except Exception as exc:                                   # noqa: BLE001
        print(f"cannot read units: {exc}", file=sys.stderr)
        return 2

    if a.layer:
        rows = [r for r in rows if _matches((r[0].split(".", 1)[0] if "." in r[0] else ""), a.layer)]
    if a.component:
        rows = [r for r in rows if _matches(r[0], a.component)]
    if a.unit:
        rows = [r for r in rows if _matches(r[1], a.unit)]

    if not rows:
        print(f"no units matched ({origin}).")
        return 0

    # key -> {directory: [files]}. Same stem in ONE directory is a .cpp/.h pair.
    by_key: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for component, unit, rel_dir, rel_file in rows:
        by_key[f"{component}|{unit}"][rel_dir].append(rel_file)

    collisions = {k: v for k, v in by_key.items() if len(v) > 1}

    print(f"source        : {origin}")
    print(f"units         : {len(by_key)}   (files scanned: {len(rows)})")
    print(f"collisions    : {len(collisions)}")

    if not a.collisions_only:
        print("\nunit keys:")
        for key in sorted(by_key):
            dirs = by_key[key]
            mark = "  <-- COLLISION" if len(dirs) > 1 else ""
            print(f"  {key}{mark}")
            if len(dirs) > 1:
                for d in sorted(dirs):
                    print(f"        {d}/  ({', '.join(os.path.basename(f) for f in sorted(dirs[d]))})")

    if collisions:
        print("\nCOLLISIONS — one unit key, files in more than one directory:")
        for key in sorted(collisions):
            print(f"\n  {key}")
            for d in sorted(collisions[key]):
                for f in sorted(collisions[key][d]):
                    print(f"      {f}")
        print("\nEach of these merges into ONE unit carrying every listed file's functions,")
        print("under the first file's path and name. Rename one file, or split the")
        print("component so the two live in different components.")
        return 1

    print("\nNo unit-key collisions. Every unit name is unique within its component.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
