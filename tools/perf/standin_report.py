"""Summarise a tools/perf/llm_standin.py log: calls, refusals, the busiest moment, calls per second.

    python tools/perf/standin_report.py C:/tmp/perf-out/standin-L2.jsonl
"""
import json
import sys
from collections import Counter


def main(path: str) -> None:
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not recs:
        print("  stand-in: no calls")
        return
    ok = [r for r in recs if r["status"] == 200]
    refused = Counter(r.get("why", "?") for r in recs if r["status"] == 503)
    span = max(r["end"] for r in recs) - min(r["start"] for r in recs)
    # the most requests in flight at once, per key
    events = sorted([(r["start"], 1, r["key"]) for r in ok] + [(r["end"], -1, r["key"]) for r in ok])
    live, peak = Counter(), Counter()
    for _, d, k in events:
        live[k] += d
        peak[k] = max(peak[k], live[k])
    print(f"  stand-in: {len(ok)} answered, {sum(refused.values())} refused {dict(refused)}, "
          f"{span:.0f}s, {len(ok) / span if span else 0:.2f} calls/s, peak in flight {dict(peak)}")


if __name__ == "__main__":
    main(sys.argv[1])
