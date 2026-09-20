"""Compare two generated documents, or check one on its own.

    python -m doccheck a.docx b.docx                 # compare, terminal report
    python -m doccheck a.docx b.docx --markdown r.md # and write the long form
    python -m doccheck a.docx --self                 # one document, on its own
    python -m doccheck a.docx b.docx --json r.json --gate high

`--gate` sets the severity that makes the exit code non-zero, so the same command
serves a reviewer reading the report and a pipeline deciding whether to stop.

The document type is worked out from the document itself; `--profile` forces it.
Nothing here needs the repository, a database or a pipeline run: two paths in, a
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
from .model import HIGH, INFO, LOW, MEDIUM

PROFILES = {"swe3": swe3, "swe4": swe4}
_GATE_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3}


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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="doccheck", description=__doc__.splitlines()[0])
    ap.add_argument("reference", help="the document to compare against")
    ap.add_argument("compared", nargs="?", help="the document under review")
    ap.add_argument("--self", action="store_true",
                    help="check one document against its own rules, no second document")
    ap.add_argument("--pair", action="store_true",
                    help="hold a SWE.3 design against its SWE.4 specification (V-model)")
    ap.add_argument("--profile", choices=sorted(PROFILES),
                    help="force the document type instead of detecting it")
    ap.add_argument("--aliases", help="a file of `ours = theirs` name pairs")
    ap.add_argument("--markdown", help="write the long-form report here")
    ap.add_argument("--json", dest="json_out", help="write machine-readable findings here")
    ap.add_argument("--gate", choices=[HIGH, MEDIUM, LOW, INFO], default=None,
                    help="exit non-zero when a finding at this severity or above exists")
    ap.add_argument("--quiet", action="store_true", help="print the summary line only")
    a = ap.parse_args(argv)

    for path in (a.reference, a.compared):
        if path and not os.path.isfile(path):
            print("no such file: %s" % path, file=sys.stderr)
            return 2

    profile, left = _load(a.reference, a.profile)

    if a.self or not a.compared:
        findings = comparing.self_checks(left, profile)
        print("%s: %s, %d finding(s) checking the document against itself"
              % (os.path.basename(a.reference), profile.DOC_TYPE, len(findings)))
        for f in findings:
            print("  %-4s %s" % (f.level, f.path or "(document)"))
            print("        %s" % f.summary)
        if a.json_out:
            with open(a.json_out, "w", encoding="utf-8") as fh:
                fh.write(report.to_json(comparing.Result(), a.reference, "",
                                        self_left=findings))
        return 1 if (findings and a.gate) else 0

    right_profile, right = _load(a.compared, a.profile)

    if a.pair:
        design, spec = (left, right) if profile is swe3 else (right, left)
        if profile is right_profile:
            print("--pair wants one SWE.3 document and one SWE.4 document; both are %s"
                  % profile.DOC_TYPE, file=sys.stderr)
            return 2
        findings = pairing.check(design, spec)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(pairing.summary(design, spec, findings))
        print()
        for f in findings:
            print("  %-6s %-4s %s" % (f.severity, f.level, f.path))
            print("         %s" % f.summary)
            if f.rule:
                print("         rule: %s" % f.rule)
        if a.json_out:
            import json as _json
            with open(a.json_out, "w", encoding="utf-8") as fh:
                fh.write(_json.dumps([f.__dict__ for f in findings], indent=2, default=str) + "\n")
            print("wrote %s" % a.json_out)
        if a.gate:
            limit = _GATE_ORDER[a.gate]
            return 1 if any(_GATE_ORDER.get(f.severity, 9) <= limit for f in findings) else 0
        return 0

    if right_profile is not profile:
        print("the two documents are different types (%s and %s)"
              % (profile.DOC_TYPE, right_profile.DOC_TYPE), file=sys.stderr)
        return 2

    aliases = match.Aliases.load(a.aliases) if a.aliases else match.Aliases()
    result = comparing.compare(left, right, profile, aliases)
    rules.annotate(result, left, right)
    self_left = comparing.self_checks(left, profile)
    self_right = comparing.self_checks(right, profile)

    if a.quiet:
        print(report.summary_line(result))
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(report.text(result, a.reference, a.compared))

    if a.markdown:
        with open(a.markdown, "w", encoding="utf-8") as fh:
            fh.write(report.markdown(result, a.reference, a.compared, self_left, self_right))
        print("wrote %s" % a.markdown)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            fh.write(report.to_json(result, a.reference, a.compared, self_left, self_right))
        print("wrote %s" % a.json_out)

    if a.gate:
        limit = _GATE_ORDER[a.gate]
        if any(_GATE_ORDER.get(f.severity, 9) <= limit for f in result.findings):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
