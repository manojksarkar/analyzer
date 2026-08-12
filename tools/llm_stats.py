"""Compare LLM stats between two runs.

Every run writes `logs/llm_stats_<run-id>.json` (merged from the per-process
files under `logs/llm_stats/<run-id>/`). This tool reads two of them and shows
what changed — config first, then the per-stage numbers.

    python tools/llm_stats.py logs/llm_stats_A.json logs/llm_stats_B.json

    python tools/llm_stats.py logs/llm_stats_A.json          # single run

The intended use is answering "did that change help?" — a different server, a
different rateLimitSeconds, a bigger batch size. The config diff is printed
first because a comparison you can't attribute to a specific config change is
just two columns of numbers.

Exit codes: 0 on success, 2 when a file is missing or unreadable.
"""

import argparse
import json
import os
import sys


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _label(path: str, report: dict) -> str:
    rid = (report.get("run") or {}).get("id") or os.path.basename(path)
    return str(rid)


# ---------------------------------------------------------------------------
# Config diff
# ---------------------------------------------------------------------------

def _flatten(cfg: dict, prefix: str = "") -> dict:
    """Flatten one level of nesting so `enrichment.selfReview` compares cleanly."""
    out = {}
    for key, val in (cfg or {}).items():
        name = f"{prefix}{key}"
        if isinstance(val, dict):
            out.update(_flatten(val, prefix=f"{name}."))
        else:
            out[name] = val
    return out


def format_config_diff(a: dict, b: dict, label_a: str, label_b: str) -> str:
    """Show only the config keys that differ between the two runs."""
    fa, fb = _flatten(a.get("config") or {}), _flatten(b.get("config") or {})
    keys = sorted(set(fa) | set(fb))
    diffs = [(k, fa.get(k, "—"), fb.get(k, "—")) for k in keys if fa.get(k) != fb.get(k)]

    if not diffs:
        return ("Config: identical in both runs — any difference below is noise, "
                "server variance, or a code change.")

    width = max(len(k) for k, _, _ in diffs)
    lines = ["Config differences:"]
    for key, va, vb in diffs:
        sa, sb = str(va), str(vb)
        # Long values (URLs) get their own lines — squeezing them into columns
        # misaligns the table and hides the part that actually differs.
        if max(len(sa), len(sb)) > 24:
            lines.append(f"  {key}")
            lines.append(f"      {label_a}: {sa}")
            lines.append(f"      {label_b}: {sb}")
        else:
            lines.append(f"  {key:{width}s}  {sa:>22s}  {sb:>22s}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage comparison
# ---------------------------------------------------------------------------

_METRICS = [
    ("calls", "calls", "{:.0f}"),
    ("fail", None, "{:.0f}"),
    ("avgSeconds", "avg per call", "{:.1f}s"),
    ("maxSeconds", "slowest call", "{:.1f}s"),
    ("httpSeconds", "http total", "{:.1f}s"),
    ("throttleSeconds", "throttle", "{:.1f}s"),
    ("tokensPerSecond", "out tokens/s", "{:.1f}"),
]


def _by_stage(report: dict) -> dict:
    return {row["stage"]: row for row in (report.get("stages") or [])}


def _fails(row: dict) -> int:
    return int(row.get("empty", 0)) + int(row.get("error", 0))


def _delta(va: float, vb: float, lower_is_better: bool = True) -> str:
    """Percent change from a to b, annotated with better/worse."""
    if va == 0:
        return "" if vb == 0 else "new"
    pct = 100.0 * (vb - va) / va
    if abs(pct) < 1:
        return "="
    better = (pct < 0) if lower_is_better else (pct > 0)
    return f"{pct:+.0f}% {'better' if better else 'worse'}"


def format_comparison(a: dict, b: dict, label_a: str, label_b: str) -> str:
    sa, sb = _by_stage(a), _by_stage(b)
    stages = sorted(set(sa) | set(sb),
                    key=lambda s: -(sb.get(s, sa.get(s, {})).get("totalSeconds") or 0))

    lines = []
    for stage in stages:
        ra, rb = sa.get(stage), sb.get(stage)
        lines.append("")
        lines.append(f"{stage}")
        if ra is None:
            lines.append(f"  only in {label_b}")
        if rb is None:
            lines.append(f"  only in {label_a}")
        ra, rb = ra or {}, rb or {}
        lines.append(f"  {'':16s}{label_a:>14s}{label_b:>14s}   change")
        for key, title, fmt in _METRICS:
            if key == "fail":
                va, vb = _fails(ra), _fails(rb)
                title = "failures"
            else:
                va, vb = float(ra.get(key) or 0), float(rb.get(key) or 0)
            # More output tokens per second is better; everything else is a cost.
            lower_better = key != "tokensPerSecond"
            lines.append(
                f"  {title or key:16s}{fmt.format(va):>14s}{fmt.format(vb):>14s}"
                f"   {_delta(va, vb, lower_better)}"
            )

    ta, tb = a.get("totals") or {}, b.get("totals") or {}
    lines.append("")
    lines.append("TOTAL")
    lines.append(f"  {'':16s}{label_a:>14s}{label_b:>14s}   change")
    for key, title, fmt in _METRICS:
        if key == "fail":
            va, vb = _fails(ta), _fails(tb)
            title = "failures"
        elif key == "tokensPerSecond":
            continue
        else:
            va, vb = float(ta.get(key) or 0), float(tb.get(key) or 0)
        lines.append(
            f"  {title or key:16s}{fmt.format(va):>14s}{fmt.format(vb):>14s}"
            f"   {_delta(va, vb)}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Single-run view
# ---------------------------------------------------------------------------

def format_single(report: dict, label: str) -> str:
    rows = report.get("stages") or []
    if not rows:
        return f"{label}: no LLM calls recorded."
    totals = report.get("totals") or {}
    cfg = report.get("config") or {}

    head = (f"  {'stage':32s} {'calls':>6s} {'fail':>5s} {'avg':>8s} "
            f"{'max':>8s} {'http':>10s} {'throttle':>10s} {'tok/s':>7s}")
    lines = [f"{label} - {cfg.get('provider', '?')}/{cfg.get('model', '?')} "
             f"@ {cfg.get('baseUrl', '?')}  (rateLimit={cfg.get('rateLimitSeconds', '?')}s)",
             head, "  " + "-" * (len(head) - 2)]
    for r in rows:
        lines.append(
            f"  {r['stage'][:32]:32s} {r['calls']:6d} {_fails(r):5d} "
            f"{r['avgSeconds']:7.1f}s {r['maxSeconds']:7.1f}s "
            f"{r['httpSeconds']:9.1f}s {r['throttleSeconds']:9.1f}s "
            f"{r['tokensPerSecond']:7.1f}"
        )
    lines.append("  " + "-" * (len(head) - 2))
    lines.append(
        f"  {'TOTAL':32s} {totals.get('calls', 0):6d} {_fails(totals):5d} "
        f"{totals.get('avgSeconds', 0):7.1f}s {totals.get('maxSeconds', 0):7.1f}s "
        f"{totals.get('httpSeconds', 0):9.1f}s {totals.get('throttleSeconds', 0):9.1f}s"
    )

    run_seconds = totals.get("runSeconds")
    total_llm = totals.get("totalSeconds", 0)
    if run_seconds:
        share = 100.0 * total_llm / run_seconds if run_seconds else 0
        lines.append(f"  LLM was {total_llm:.1f}s of a {run_seconds:.1f}s run ({share:.0f}%).")
    if total_llm and totals.get("throttleSeconds"):
        share = 100.0 * totals["throttleSeconds"] / total_llm
        lines.append(f"  Throttle (llm.rateLimitSeconds) was {share:.0f}% of LLM time.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare LLM stats between two runs (or summarise one).")
    parser.add_argument("files", nargs="+", metavar="STATS.json",
                        help="one or two logs/llm_stats_<run-id>.json files")
    args = parser.parse_args(argv)

    if len(args.files) > 2:
        parser.error("give one or two files")

    reports = []
    for path in args.files:
        if not os.path.isfile(path):
            print(f"No such file: {path}", file=sys.stderr)
            return 2
        try:
            reports.append((path, _load(path)))
        except ValueError as exc:
            print(f"Not valid JSON: {path} ({exc})", file=sys.stderr)
            return 2

    if len(reports) == 1:
        path, report = reports[0]
        print(format_single(report, _label(path, report)))
        return 0

    (pa, ra), (pb, rb) = reports
    la, lb = _label(pa, ra), _label(pb, rb)
    print(format_config_diff(ra, rb, la, lb))
    print(format_comparison(ra, rb, la, lb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
