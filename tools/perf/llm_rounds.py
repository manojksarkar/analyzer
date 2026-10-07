"""How many function descriptions can be asked at once, on a stored version (llm.workers > 1).

Descriptions go callees first, in rounds: a round's functions call none of each other, so a round
runs at once. When a call cycle blocks progress, everything left becomes one last round that runs
one at a time, in today's order -- on code with recursion or callbacks that round can hold every
caller above the cycle. This prints the rounds and that last round's size.

    python tools/perf/llm_rounds.py <version-id>          (needs DATABASE_URL)
"""
import os
import sys

import sqlalchemy as sa


def main(version_id: str) -> None:
    e = sa.create_engine(os.environ["DATABASE_URL"])
    with e.connect() as c:
        funcs = c.execute(sa.text("select payload from parse_snapshots where version_id=:v and name='functions.json'"),
                          {"v": version_id}).scalar()
    if not funcs:
        print(f"no functions stored for {version_id}")
        return
    calls = {k: set(f.get("callsIds") or []) for k, f in funcs.items()}
    processed, rounds, keys = set(), [], set(calls)
    while len(processed) < len(keys):          # the same rule as llm_enrichment.enrich_functions_rich
        free = [k for k in keys - processed if calls[k].issubset(processed)]
        ready = free or list(keys - processed)
        rounds.append((len(ready), not free))
        processed.update(ready)
    cycle = sum(n for n, c in rounds if c)
    print(f"{len(keys)} functions in {len(rounds)} rounds: {[n for n, _ in rounds]}")
    print(f"last round of a cycle (runs one at a time): {cycle} function(s) "
          f"({100 * cycle / max(1, len(keys)):.0f}%)")


if __name__ == "__main__":
    main(sys.argv[1])
