"""Findings as something a person reads, and as something a script reads.

The markdown form leads with the ladder, because the first question is always
"how far down did it get before it stopped agreeing" -- if the unit inventory
does not match, nothing below it is worth reading yet.
"""
from __future__ import annotations

import json

from .model import HIGH, INFO, LOW, MEDIUM

_LADDER = [
    ("L0", "document shape"),
    ("L1", "unit inventory"),
    ("L2", "per unit"),
    ("L3", "per row"),
    ("L4", "dynamic behaviour"),
]

_MARK = {HIGH: "!!", MEDIUM: "! ", LOW: "· ", INFO: "  "}


def _counts(findings):
    out = {}
    for f in findings:
        out[f.severity] = out.get(f.severity, 0) + 1
    return out


def summary_line(result):
    c = _counts(result.findings)
    return "%d finding(s): %d high, %d medium, %d low, %d info" % (
        len(result.findings), c.get(HIGH, 0), c.get(MEDIUM, 0), c.get(LOW, 0), c.get(INFO, 0))


def markdown(result, left_name, right_name, self_left=None, self_right=None):
    out = []
    add = out.append
    add("# Document comparison")
    add("")
    add("| | document |")
    add("|---|---|")
    add("| reference | `%s` |" % left_name)
    add("| compared | `%s` |" % right_name)
    add("")
    add(summary_line(result))
    add("")

    add("## Ladder")
    add("")
    add("| level | what | high | medium | low | info |")
    add("|---|---|---|---|---|---|")
    for level, label in _LADDER:
        at = [f for f in result.findings if f.level == level]
        c = _counts(at)
        add("| %s | %s | %d | %d | %d | %d |" % (
            level, label, c.get(HIGH, 0), c.get(MEDIUM, 0), c.get(LOW, 0), c.get(INFO, 0)))
    add("")

    add("## Inventory")
    add("")
    add("| kind | reference | compared | matched | score |")
    add("|---|---|---|---|---|")
    for kind in sorted(set(result.left_total) | set(result.right_total)):
        add("| %s | %d | %d | %d | %.0f%% |" % (
            kind, result.left_total.get(kind, 0), result.right_total.get(kind, 0),
            result.matched.get(kind, 0), 100 * result.score(kind)))
    add("")

    for name, findings in (("Reference document, checked against itself", self_left or []),
                           ("Compared document, checked against itself", self_right or [])):
        if findings:
            add("## %s" % name)
            add("")
            for f in findings:
                add("- **%s** — %s" % (f.path or "(document)", f.summary))
            add("")

    add("## Findings")
    add("")
    if not result.findings:
        add("Nothing to report: the two documents agree on everything compared.")
        return "\n".join(out) + "\n"

    current = None
    for f in result.findings:
        if f.severity != current:
            current = f.severity
            add("")
            add("### %s" % {HIGH: "High", MEDIUM: "Medium", LOW: "Low", INFO: "Informational"}[f.severity])
            add("")
        where = f.path or "(document)"
        add("- `%s` — %s" % (where, f.summary))
        if f.rule:
            add("  - explained by: %s" % f.rule)
    add("")
    return "\n".join(out) + "\n"


def text(result, left_name, right_name):
    """A terminal-shaped report: the ladder, then the findings worth acting on."""
    lines = ["%s" % summary_line(result), ""]
    for level, label in _LADDER:
        at = [f for f in result.findings if f.level == level]
        c = _counts(at)
        lines.append("  %s %-20s high %-3d medium %-3d low %-3d info %-3d"
                     % (level, label, c.get(HIGH, 0), c.get(MEDIUM, 0),
                        c.get(LOW, 0), c.get(INFO, 0)))
    lines.append("")
    for f in result.findings:
        if f.severity == INFO:
            continue
        lines.append("%s %-4s %s" % (_MARK.get(f.severity, "  "), f.level, f.path or "(document)"))
        lines.append("        %s" % f.summary)
        if f.rule:
            lines.append("        rule: %s" % f.rule)
    return "\n".join(lines) + "\n"


def to_json(result, left_name, right_name, self_left=None, self_right=None):
    payload = {
        "reference": left_name,
        "compared": right_name,
        "summary": {
            "findings": len(result.findings),
            "high": len([f for f in result.findings if f.severity == HIGH]),
            "medium": len([f for f in result.findings if f.severity == MEDIUM]),
            "low": len([f for f in result.findings if f.severity == LOW]),
            "info": len([f for f in result.findings if f.severity == INFO]),
        },
        "inventory": {
            kind: {
                "reference": result.left_total.get(kind, 0),
                "compared": result.right_total.get(kind, 0),
                "matched": result.matched.get(kind, 0),
                "score": round(result.score(kind), 4),
            }
            for kind in sorted(set(result.left_total) | set(result.right_total))
        },
        "self_checks": {
            "reference": [f.__dict__ for f in (self_left or [])],
            "compared": [f.__dict__ for f in (self_right or [])],
        },
        "findings": [f.__dict__ for f in result.findings],
    }
    return json.dumps(payload, indent=2, default=str) + "\n"
