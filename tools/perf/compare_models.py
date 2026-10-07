"""Compare two versions' stored models, exactly: a speed-up that claims "same output" must leave
the model identical -- the same entities, fields and values, and the same ORDER in every list
(calledByIds order picks a behaviour diagram's caller, so a set compare is not enough).

    python tools/perf/compare_models.py <version-id-a> <version-id-b> [--out C:/tmp/perf-out]

Needs DATABASE_URL. Prints each model file's verdict and, for a difference, the first few
entities and fields that differ.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

# Fields that name the version or the run, not the code
IGNORED = {"versionId", "version_id", "generatedAt", "runId"}


def dump(version_id: str, out: str) -> str:
    from core.db import get_engine
    from core import model_store
    d = os.path.join(out, f"model_{version_id.replace('.', '_')}")
    os.makedirs(d, exist_ok=True)
    with get_engine().connect() as cx:
        model_store.dump_model_to_dir(cx, version_id, d)
    return d


def strip(v):
    if isinstance(v, dict):
        return {k: strip(x) for k, x in v.items() if k not in IGNORED}
    if isinstance(v, list):
        return [strip(x) for x in v]
    return v


def first_diffs(a, b, path="", out=None, limit=8):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path}: {type(a).__name__} vs {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'b' if k not in a else 'a'}")
            elif a[k] != b[k]:
                first_diffs(a[k], b[k], f"{path}/{k}", out, limit)
            if len(out) >= limit:
                break
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} items vs {len(b)}")
        elif sorted(map(json.dumps, a)) == sorted(map(json.dumps, b)):
            out.append(f"{path}: same items, other ORDER")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    first_diffs(x, y, f"{path}[{i}]", out, limit)
                    if len(out) >= limit:
                        break
    elif a != b:
        out.append(f"{path}: {str(a)[:80]!r} vs {str(b)[:80]!r}")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--out", default="C:/tmp/perf-out")
    a = p.parse_args()
    da, db = dump(a.a, a.out), dump(a.b, a.out)
    names = sorted(set(os.listdir(da)) | set(os.listdir(db)))
    same = True
    for n in names:
        fa, fb = os.path.join(da, n), os.path.join(db, n)
        if not (os.path.isfile(fa) and os.path.isfile(fb)):
            print(f"  {n}: only in {'a' if os.path.isfile(fa) else 'b'}")
            same = False
            continue
        try:
            ja = strip(json.load(open(fa, encoding="utf-8")))
            jb = strip(json.load(open(fb, encoding="utf-8")))
        except ValueError:
            ja, jb = open(fa, encoding="utf-8").read(), open(fb, encoding="utf-8").read()
        if ja == jb:
            print(f"  {n}: identical")
        else:
            same = False
            print(f"  {n}: DIFFERS")
            for line in first_diffs(ja, jb):
                print(f"      {line}")
    print("SAME" if same else "DIFFERENT")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
