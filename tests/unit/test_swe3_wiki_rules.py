"""SWE3_WIKI's rule ids stay usable: a review comment names one, so each must lead to one rule.

The wiki is one rule table per section of the document, each row a rule `<PREFIX>-NN`. A review's
comments are counted by rule id (BACKLOG S3-12), so an id defined twice, skipped, renumbered or
named but never defined points a comment at the wrong rule, or at none. Checked here: every id is
defined once and numbered 01, 02, … in its section; every rule marked ⚠ is in Open questions; and
every id named in the wiki, or as `SWE3_WIKI <id>` anywhere in the repo, exists.
"""
import os
import re
from collections import Counter

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIKI = os.path.join(ROOT, "docs", "spec", "SWE3_WIKI.md")
#: In document order -- the order of the wiki's sections.
PREFIXES = ("DOC", "INT", "CO", "UD", "UH", "IT", "FC", "BD", "FX")
_ID = r"(?:%s)-\d{2}" % "|".join(PREFIXES)
#: A removed rule stays in its table, struck through (`| ~~UH-07~~ |`), so no number is reused.
_ROW = re.compile(r"^\| (?:~~)?(%s)(?:~~)? \|(.*)$" % _ID, re.M)
_ANY_ID = re.compile(r"\b%s\b" % _ID)
_REFERENCE = re.compile(r"SWE3_WIKI(?:\.md)? (%s)" % _ID)
#: Where `SWE3_WIKI <id>` may be written: docs, code, tests and the context.
_SEARCHED = ("docs", "engine", "api", "tests", "project-context", ".claude")


def _wiki():
    with open(WIKI, encoding="utf-8") as fh:
        return fh.read()


def _section(text, start, end=None):
    head = text.index(start)
    return text[head:text.index(end, head)] if end else text[head:]


def _rules(text):
    """`[(id, rest of the row)]` of the rule tables, in order -- everything above the worked
    example, whose own tables quote ids without defining them."""
    return _ROW.findall(text[:text.index("## Worked example")])


def test_every_section_has_rules():
    found = {rid.split("-")[0] for rid, _ in _rules(_wiki())}
    assert found == set(PREFIXES)


def test_every_id_is_defined_once():
    counts = Counter(rid for rid, _ in _rules(_wiki()))
    assert [rid for rid, n in counts.items() if n > 1] == []


def test_ids_count_up_from_01_in_each_section():
    numbers = {}
    for rid, _ in _rules(_wiki()):
        prefix, number = rid.split("-")
        numbers.setdefault(prefix, []).append(int(number))
    for prefix, seen in numbers.items():
        assert seen == list(range(1, len(seen) + 1)), f"{prefix}: {seen}"


def test_every_open_rule_is_in_open_questions():
    text = _wiki()
    open_ids = {rid for rid, row in _rules(text) if "⚠" in row}
    listed = set(_ANY_ID.findall(_section(text, "## Open questions", "## Old spec ids")))
    assert sorted(open_ids - listed) == []


def test_open_questions_name_open_rules_only():
    text = _wiki()
    open_ids = {rid for rid, row in _rules(text) if "⚠" in row}
    listed = set(_ANY_ID.findall(_section(text, "## Open questions", "## Old spec ids")))
    assert sorted(listed - open_ids) == []


def test_every_id_named_in_the_wiki_exists():
    text = _wiki()
    defined = {rid for rid, _ in _rules(text)}
    assert sorted(set(_ANY_ID.findall(text)) - defined) == []


def test_every_old_spec_id_is_mapped():
    old = _section(_wiki(), "## Old spec ids")
    mapped = set(re.findall(r"REQ-[A-Z]{2}-\d{2}", old))
    expected = ({f"REQ-DS-{n:02}" for n in range(1, 5)} | {f"REQ-IT-{n:02}" for n in range(1, 13)}
                | {f"REQ-UH-{n:02}" for n in range(1, 3)} | {f"REQ-UD-{n:02}" for n in range(1, 10)}
                | {f"REQ-BD-{n:02}" for n in range(1, 6)} | {f"REQ-FC-{n:02}" for n in range(1, 5)}
                | {f"REQ-CO-{n:02}" for n in range(1, 4)})
    assert sorted(expected - mapped) == []


def test_every_reference_from_the_repo_exists():
    defined = {rid for rid, _ in _rules(_wiki())}
    missing = []
    for top in _SEARCHED:
        for folder, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__", ".git")]
            for name in files:
                if not name.endswith((".md", ".py")):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for rid in _REFERENCE.findall(fh.read()):
                        if rid not in defined:
                            missing.append(f"{os.path.relpath(path, ROOT)}: {rid}")
    assert missing == []
