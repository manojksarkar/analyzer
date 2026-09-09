"""Compare two LLM prompt-parity corpora (docs/production-redesign/07 §2).

Exit 0 => the prompts sent are identical, so the model's input did not change and
LLM output quality cannot have regressed. Exit 1 => something the AI sees moved;
the report names exactly which prompts appeared, vanished, or changed.

Comparison is by content digest (a *set*), because phases run as separate
subprocesses and interleave — ordering is not meaningful, but the set of prompts
and the total call count both are.

    python tools/parity/compare.py .parity/before .parity/after
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _load(corpus: str) -> tuple[dict, int]:
    """(digest -> prompt record, total call count) for a capture directory."""
    prompts = {}
    for name in os.listdir(corpus):
        if not name.endswith(".json") or name.startswith("_capture-config"):
            continue
        with open(os.path.join(corpus, name), encoding="utf-8") as fh:
            prompts[name[:-5]] = json.load(fh)
    calls_path = os.path.join(corpus, "calls.jsonl")
    calls = sum(1 for _ in open(calls_path, encoding="utf-8")) if os.path.isfile(calls_path) else 0
    return prompts, calls


def _excerpt(rec: dict, limit: int = 220) -> str:
    parts = rec.get("parts") or []
    user = next((p.get("content", "") for p in reversed(parts) if p.get("role") == "user"), "")
    return " ".join(str(user).split())[:limit]


def compare(before_dir: str, after_dir: str) -> int:
    before, before_calls = _load(before_dir)
    after, after_calls = _load(after_dir)

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))

    print(f"before : {len(before):4d} distinct prompt(s), {before_calls} call(s)")
    print(f"after  : {len(after):4d} distinct prompt(s), {after_calls} call(s)")

    ok = True
    if removed:
        ok = False
        print(f"\n{len(removed)} prompt(s) NO LONGER SENT — the AI lost this input:")
        for d in removed[:10]:
            print(f"  - {d}  {_excerpt(before[d])}")
    if added:
        ok = False
        print(f"\n{len(added)} NEW prompt(s) — the AI now sees different input:")
        for d in added[:10]:
            print(f"  + {d}  {_excerpt(after[d])}")
    if before_calls != after_calls:
        ok = False
        print(f"\nCALL COUNT CHANGED: {before_calls} -> {after_calls} "
              f"(a dropped or duplicated call is as harmful as a changed prompt)")

    # ASCII only: Windows consoles are cp1252 and mangle dashes (see PROJECT_CONTEXT s18).
    print("\nPARITY OK - prompts identical, LLM output quality unchanged by construction."
          if ok else "\nPARITY FAILED - see above.")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Diff two prompt-parity corpora.")
    ap.add_argument("before")
    ap.add_argument("after")
    args = ap.parse_args()
    raise SystemExit(compare(args.before, args.after))


if __name__ == "__main__":
    main()
