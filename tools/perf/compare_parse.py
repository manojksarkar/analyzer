"""Compare two versions' Phase 1 output exactly: every parse snapshot (functions, globals, data
dictionary, hashes, edges, func_keys, entity_files, override_pairs, address_taken) and the include
lists -- the parse alone, whatever the LLM did after it. `metadata.json` is compared without its
timestamp.

    python tools/perf/compare_parse.py <version-id-a> <version-id-b>      (needs DATABASE_URL)
"""
import json
import os
import sys

import sqlalchemy as sa


def main(a: str, b: str) -> int:
    e = sa.create_engine(os.environ["DATABASE_URL"])
    same = True
    with e.connect() as c:
        def snaps(v):
            rows = c.execute(sa.text("select name, payload from parse_snapshots where version_id=:v"), {"v": v}).all()
            out = {}
            for name, payload in rows:
                if name == "metadata.json" and isinstance(payload, dict):
                    payload = {k: x for k, x in payload.items() if k != "generatedAt"}
                out[name] = json.dumps(payload, sort_keys=False, default=str)
            return out
        sa_, sb = snaps(a), snaps(b)
        for name in sorted(set(sa_) | set(sb)):
            ok = sa_.get(name) == sb.get(name)
            same &= ok
            print(f"  {name}: {'identical' if ok else 'DIFFERS'}")
        for v in (a, b):
            n = c.execute(sa.text("select count(*) from tu_includes where version_id=:v"), {"v": v}).scalar()
            print(f"  tu_includes {v}: {n} rows")
    print("SAME" if same else "DIFFERENT")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
