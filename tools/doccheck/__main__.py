"""Compare two generated documents, pair a design with its spec, or check one alone.

    python -m doccheck a.docx b.docx                  # compare two of one type
    python -m doccheck design.docx spec.docx          # SWE.3 + SWE.4: paired
    python -m doccheck a.docx --self                  # one document, on its own
    python -m doccheck a.docx b.docx --markdown r.md  # and the long form
    python -m doccheck a.docx b.docx --level 3        # stop after L3
    python -m doccheck a.docx b.docx --json r.json --gate P1

Two documents of one type are compared; a SWE.3 and a SWE.4 are paired (the
V-model check), with or without `--pair`. The type is worked out from each
document itself; `--profile` forces it for a comparison.

Every check reports on the same five levels -- headings, inventory, sections,
views, content -- and gives every finding a priority, P1 (blocker) to P4
(cosmetic). `--gate` sets the priority that makes the exit code non-zero, so the
same command serves a reviewer reading the report and a pipeline deciding
whether to stop.

Nothing here needs the repository, a database or a pipeline run: paths in, a
report out, which is what running it where the client's document lives requires.
"""
from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):            # run as a file rather than a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "doccheck"

from . import (blocks, compare as comparing, match, pairing, report, rules, swe3,
               swe4)
from .model import P1, P2, P3, P4, PRIORITIES, priority_rank

PROFILES = {"swe3": swe3, "swe4": swe4}

# The severities the first version used, still accepted by --gate.
_OLD_GATES = {"high": P1, "medium": P2, "low": P3, "info": P4}


def detect(blocks_, filename=""):
    """Which profile reads this document, from its headings and its name."""
    name = os.path.basename(filename).casefold()
    if "unit_test" in name or "swe4" in name:
        return swe4
    if "detailed_design" in name or "swe3" in name:
        return swe3
    headings = " ".join(b.text.casefold() for b in blocks_ if b.kind == "heading")
    if "unit test specification" in headings:
        return swe4
    return swe3


def _load(path, forced):
    bs = blocks.read(path)
    profile = PROFILES[forced] if forced else detect(bs, path)
    return profile, profile.extract(bs)


def _gate(findings, gate):
    """1 when a counted finding at the gate's priority or worse exists."""
    if not gate:
        return 0
    limit = priority_rank(_OLD_GATES.get(gate, gate))
    return 1 if any(f.counted and priority_rank(f.priority) <= limit for f in findings) else 0


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s" % path, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="doccheck", description=__doc__.splitlines()[0])
    ap.add_argument("reference", help="the document to compare against (or the design)")
    ap.add_argument("compared", nargs="?", help="the document under review (or the spec)")
    ap.add_argument("--self", action="store_true",
                    help="check one document against its own rules, no second document")
    ap.add_argument("--pair", action="store_true",
                    help="hold a SWE.3 design against its SWE.4 specification (V-model); "
                         "chosen anyway when the two documents are of those two types")
    ap.add_argument("--profile", choices=sorted(PROFILES),
                    help="force the document type instead of detecting it")
    ap.add_argument("--aliases", help="a file of `ours = theirs` name pairs")
    ap.add_argument("--level", type=int, choices=[1, 2, 3, 4, 5], default=5,
                    help="stop after this level: 1 headings, 2 inventory, 3 sections, "
                         "4 views, 5 content (the default)")
    ap.add_argument("--markdown", help="write the long-form report here")
    ap.add_argument("--json", dest="json_out", help="write machine-readable findings here")
    ap.add_argument("--gate", choices=list(PRIORITIES) + sorted(_OLD_GATES), default=None,
                    help="exit non-zero when a finding at this priority or worse exists")
    ap.add_argument("--quiet", action="store_true", help="print the summary line only")
    ap.add_argument("--full", action="store_true",
                    help="list P3/P4 findings too, and every changed line of a long difference")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                    help="colour and box-drawing: auto uses them on a terminal only")
    args = sys.argv[1:] if argv is None else list(argv)
    a = ap.parse_args(args)
    command = "doccheck " + " ".join(args)

    for path in (a.reference, a.compared):
        if path and not os.path.isfile(path):
            print("no such file: %s" % path, file=sys.stderr)
            return 2

    profile, left = _load(a.reference, a.profile)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    style = report.Style.for_stream(sys.stdout, a.color)

    if a.self or not a.compared:
        result = comparing.self_result(left, profile, a.level)
        findings = result.findings
        right_name = ""
    else:
        right_profile, right = _load(a.compared, None if a.pair else a.profile)
        if a.pair or right_profile is not profile:
            if right_profile is profile:
                print("--pair wants one SWE.3 document and one SWE.4 document; both are %s"
                      % profile.DOC_TYPE, file=sys.stderr)
                return 2
            swap = profile is swe4
            design, spec = (right, left) if swap else (left, right)
            a.reference, a.compared = ((a.compared, a.reference) if swap
                                       else (a.reference, a.compared))
            result = pairing.check(design, spec, a.level)
            result.self_left = comparing.self_checks(design, swe3, a.level)
            result.self_right = comparing.self_checks(spec, swe4, a.level)
            pairing.explain_id_gaps(result.self_right, design, spec)
        else:
            aliases = match.Aliases.load(a.aliases) if a.aliases else match.Aliases()
            result = comparing.compare(left, right, profile, aliases, a.level)
            rules.annotate(result, left, right, profile)
            result.self_left = comparing.self_checks(left, profile, a.level)
            result.self_right = comparing.self_checks(right, profile, a.level)
        findings = result.findings
        right_name = a.compared

    if a.quiet:
        print(report.summary_line(result))
    else:
        print(report.text(result, a.reference, right_name, style=style, full=a.full), end="")
    if a.markdown:
        _write(a.markdown, report.markdown(result, a.reference, right_name, command=command))
    if a.json_out:
        _write(a.json_out, report.to_json(result, a.reference, right_name))
    return _gate(findings, a.gate)


if __name__ == "__main__":
    raise SystemExit(main())
