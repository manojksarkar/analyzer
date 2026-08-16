#!/usr/bin/env python3
"""Compare a version's model in Postgres against the same model on disk (doc 09, C11a).

**The gate for C11.** C11 makes Postgres the channel between pipeline phases instead of
`model/*.json`. Before any phase is allowed to *read* from the database (C11b), the database
copy has to be proven equal to the file copy it replaces — otherwise a silent field loss
surfaces later as a wrong document, which is the failure mode this whole migration exists to
avoid.

Same idea as `--verify-parse` for narrowed parse: run both, diff, trust neither until they
agree.

    python tools/verify_model_parity.py                    # newest version
    python tools/verify_model_parity.py <version_id>
    python tools/verify_model_parity.py <version_id> --model-dir path/to/model

Exit 0 = the DB copy carries everything the files do. Exit 1 = a real difference.

Two differences are EXPECTED and reported separately, not as failures:

  * **DB-only fields** — `isVisible` exists in `entity_versions` but never in `model/*.json`
    (D-18). Extra information is not a loss.
  * **Edge list ORDER** — `callsIds` / `calledByIds` / `reads|writesGlobalIds` are rebuilt from
    `model_edges` rows, so their order differs by construction. Compared as SETS, which is the
    same correctness bar `parse_merge.diff_models` already settled on: order is cosmetic, no
    consumer depends on it.

What it is really hunting: fields the payload whitelists silently drop. `_FN_PAYLOAD_FIELDS`
and `_GLOBAL_PAYLOAD_FIELDS` are allow-lists, so any model field added later that nobody
remembers to register would round-trip as MISSING. That class of bug is invisible until a
document comes out wrong, and it is exactly what this catches.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "engine"))

from core.db import database_url, get_engine, require_database, _redact, DatabaseUnavailable  # noqa: E402
from core.paths import paths                                                     # noqa: E402
from incremental import model_store                                              # noqa: E402

# Rebuilt from model_edges, so order is an artefact of row order, not of meaning.
_EDGE_FIELDS = frozenset((
    "callsIds", "calledByIds", "readsGlobalIds", "writesGlobalIds",
    "readsGlobalIdsTransitive", "writesGlobalIdsTransitive",
))
# Present in the DB by design, absent from model/*.json. Extra, not missing.
_DB_ONLY_FIELDS = frozenset(("isVisible",))

# model_store.load_model key -> the file it corresponds to on disk
_FILES = {
    "functions": "functions.json", "globals": "globalVariables.json",
    "datadict": "dataDictionary.json", "edges": "edges.json", "units": "units.json",
    "components": "components.json", "summaries": "summaries.json", "hashes": "hashes.json",
}


def _model_dir_candidates(version_id):
    """Every place a version's model could be, newest layout first.

    C11b moved the model out of the shared <repo>/model into versions/<ver>/model, so this
    tool — written before that move — looked in a directory a current run never writes, and
    failed with "model dir not found". The legacy locations stay in the list so a version
    generated before the move still verifies.
    """
    from incremental.stores import default_workspaces_root
    out, ws_root = [], default_workspaces_root()
    if os.path.isdir(ws_root):
        for pid in sorted(os.listdir(ws_root)):
            pdir = os.path.join(ws_root, pid)
            if not os.path.isdir(pdir):
                continue
            out.append(os.path.join(pdir, "versions", version_id or "", "model"))
            out.append(os.path.join(pdir, (version_id or "")[:16], "model"))   # legacy commit-keyed
    out.append(paths().model_dir)                      # the pre-C11b shared dir
    return out


def _resolve_model_dir(version_id):
    """The first candidate that actually holds a model, or None."""
    for c in _model_dir_candidates(version_id):
        if os.path.isfile(os.path.join(c, "functions.json")):
            return c
    return None


def _read_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"  ! could not read {path}: {exc}")
        return None


def _norm(value, field):
    """Normalise one field for comparison — edge lists become sets."""
    if field in _EDGE_FIELDS and isinstance(value, list):
        return frozenset(value)
    return value


def _compare_entities(name, db_map, file_map, report, *, max_examples=5):
    """Compare two {key: dict} maps. Appends findings to `report`."""
    db_keys, file_keys = set(db_map or {}), set(file_map or {})

    only_file = file_keys - db_keys
    only_db = db_keys - file_keys
    if only_file:
        report.append((f"{name}: {len(only_file)} entit(y/ies) on disk are MISSING from the DB",
                       sorted(only_file)[:max_examples]))
    if only_db:
        report.append((f"{name}: {len(only_db)} entit(y/ies) in the DB are absent on disk",
                       sorted(only_db)[:max_examples]))

    field_misses, value_diffs, order_only = {}, [], 0
    for key in sorted(db_keys & file_keys):
        d, f = db_map[key] or {}, file_map[key] or {}
        if not isinstance(d, dict) or not isinstance(f, dict):
            if d != f:
                value_diffs.append(f"{key}: {f!r} -> {d!r}")
            continue
        for field, fval in f.items():
            if field not in d:
                field_misses.setdefault(field, []).append(key)
                continue
            dval = d[field]
            if dval == fval:
                continue
            if _norm(dval, field) == _norm(fval, field):
                order_only += 1                     # same members, different order
                continue
            if len(value_diffs) < max_examples:
                value_diffs.append(f"{key}.{field}: disk={fval!r} db={dval!r}")

    for field, keys in sorted(field_misses.items()):
        report.append((f"{name}: field '{field}' present on disk but DROPPED by the DB "
                       f"({len(keys)} entities) — check the payload whitelist",
                       sorted(keys)[:max_examples]))
    if value_diffs:
        report.append((f"{name}: {len(value_diffs)}+ field value mismatch(es)", value_diffs))
    return order_only


def _compare_plain(name, db_obj, file_obj, report):
    """Compare a non-entity structure (hashes, edges, summaries) by exact equality."""
    if db_obj == file_obj:
        return
    if isinstance(db_obj, dict) and isinstance(file_obj, dict):
        only_file = set(file_obj) - set(db_obj)
        only_db = set(db_obj) - set(file_obj)
        if only_file:
            report.append((f"{name}: {len(only_file)} key(s) on disk missing from the DB",
                           sorted(only_file)[:5]))
        if only_db:
            report.append((f"{name}: {len(only_db)} key(s) in the DB absent on disk",
                           sorted(only_db)[:5]))
        diffs = [f"{k}: disk={file_obj[k]!r} db={db_obj[k]!r}"
                 for k in sorted(set(db_obj) & set(file_obj)) if db_obj[k] != file_obj[k]]
        if diffs:
            report.append((f"{name}: {len(diffs)} value mismatch(es)", diffs[:5]))
    else:
        report.append((f"{name}: differs", [f"disk={type(file_obj).__name__} "
                                            f"db={type(db_obj).__name__}"]))


def _newest_version(cx):
    from sqlalchemy import select
    from api.db.postgres import schema as s
    row = cx.execute(select(s.versions.c.id)
                     .order_by(s.versions.c.created_at.desc()).limit(1)).first()
    return row.id if row else None


def main(argv):
    version_id = next((a for a in argv if not a.startswith("--")), None)
    model_dir = None
    if "--model-dir" in argv:
        model_dir = argv[argv.index("--model-dir") + 1]

    try:
        require_database()
    except DatabaseUnavailable as exc:
        print(exc)
        return 2

    print(f"database : {_redact(database_url())}")
    with get_engine().connect() as cx:
        if not version_id:
            version_id = _newest_version(cx)
            if not version_id:
                print("no versions in the database — run a generation first")
                return 2
        print(f"version  : {version_id}")
        db_model = model_store.load_model(cx, version_id)

    if not model_dir:
        model_dir = _resolve_model_dir(version_id)
    print(f"model dir: {model_dir or '(not found)'}")
    if not model_dir or not os.path.isdir(model_dir):
        print(f"\nFAIL: no model directory found for {version_id}.\n"
              f"  Since C11b a run writes its model to versions/<ver>/model, not <repo>/model.\n"
              f"  Looked in:")
        for c in _model_dir_candidates(version_id):
            print(f"    {c}")
        print(f"  If this version was generated elsewhere, point at it explicitly:\n"
              f"    python tools/verify_model_parity.py {version_id} --model-dir <path>")
        return 2
    print()

    report, order_only_total, checked = [], 0, 0
    for key, filename in _FILES.items():
        file_obj = _read_json(os.path.join(model_dir, filename))
        db_obj = db_model.get(key)
        if file_obj is None:
            print(f"  {key:11s} SKIP  ({filename} not on disk)")
            continue
        checked += 1
        before = len(report)
        if key in ("functions", "globals", "units", "components", "datadict"):
            order_only_total += _compare_entities(key, db_obj, file_obj, report)
        else:
            _compare_plain(key, db_obj, file_obj, report)
        n_db = len(db_obj or {})
        status = "OK  " if len(report) == before else "DIFF"
        print(f"  {key:11s} {status}  ({n_db} in DB)")

    print()
    if order_only_total:
        print(f"note: {order_only_total} field(s) matched as sets but differ in ORDER — expected, "
              f"edge lists are rebuilt from rows (order is not a correctness property).")
    if _DB_ONLY_FIELDS:
        print(f"note: DB-only fields ignored by design: {', '.join(sorted(_DB_ONLY_FIELDS))}")

    if not report:
        print(f"\nOK — the DB copy carries everything the {checked} on-disk model file(s) do.")
        return 0

    print(f"\nFAIL — {len(report)} difference(s):\n")
    for headline, examples in report:
        print(f"  * {headline}")
        for ex in examples:
            print(f"      {ex}")
    print("\nThe DB is NOT yet a safe substitute for the files. Do not land C11b (reads) until "
          "this is clean.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
