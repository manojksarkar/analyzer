"""SWE3_WIKI's rule ids stay usable: a review comment names one, so each must lead to one rule.

Each section is one table, `ID | Rule`. A rule `SWE3-<SECTION>-NN` is the row whose ID cell is merged
down its rows (`<tr><td rowspan="7" …>SWE3-UH-01</td>…`) and the rows under it: its name, then its
numbered details. A section not rewritten yet has one markdown row per rule (`| SWE3-UI-02 | … |`).
A review's comments are counted by rule id (BACKLOG S3-12), so an id defined twice, skipped, renumbered
or named but never defined points a comment at the wrong rule, or at none. Checked here: every id is
defined once and numbered 01, 02, … in its section; none is written without its `SWE3-`; every rule
marked ⚠ is in Open questions; and every id named in the wiki, the test inventory or anywhere in the
repo exists.
"""
import os
import re
from collections import Counter

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIKI = os.path.join(ROOT, "docs", "spec", "SWE3_WIKI.md")
INVENTORY = os.path.join(ROOT, "docs", "spec", "TEST_INVENTORY.md")
#: In document order -- the order of the wiki's sections.
PREFIXES = ("DOC", "SD", "UH", "UI", "FD", "DB", "FX")
_ID = r"SWE3-(?:%s)-\d{2}" % "|".join(PREFIXES)
#: A removed rule stays, struck through (`>SWE3-UH-03<` as `><s>SWE3-UH-03</s><`, `| ~~SWE3-UI-01~~ |`),
#: so no number is reused.
_ROW = re.compile(r"^\| (?:~~)?(%s)(?:~~)? \|(.*)$" % _ID)
_MERGED = re.compile(r'^<tr><td rowspan="\d+"[^>]*>(?:<b>)?(?:<s>)?(%s)(?:</s>)?(?:</b>)?</td>(.*)$' % _ID)
_ANY_ID = re.compile(r"\b%s\b" % _ID)
#: An id without its `SWE3-` -- `IT-14` -- which a review sheet could not tell from another document's.
_BARE = re.compile(r"(?<![\w-])(?:%s)-\d{2}\b" % "|".join(PREFIXES))
#: Where a rule id may be written: docs, code, tests and the context.
_SEARCHED = ("docs", "engine", "api", "tests", "tools", "project-context", ".claude")


def _wiki():
    with open(WIKI, encoding="utf-8") as fh:
        return fh.read()


def _inventory():
    with open(INVENTORY, encoding="utf-8") as fh:
        return fh.read()


def _section(text, start, end=None):
    head = text.index(start)
    return text[head:text.index(end, head)] if end else text[head:]


def _rules(text):
    """`[(id, the rest of its rows)]` of the rules, in order -- everything above the worked example,
    whose own tables quote ids without defining them. A ⚠ in a rule's details marks it open."""
    rules, current = [], None
    for line in text[:text.index("## Worked example")].splitlines():
        row, merged = _ROW.match(line), _MERGED.match(line)
        if row:
            rules.append([row.group(1), row.group(2)])
            current = None
        elif merged:
            current = [merged.group(1), merged.group(2)]
            rules.append(current)
        elif current is not None and line.startswith("<tr><td>"):
            current[1] += line
        else:
            current = None
    return [tuple(r) for r in rules]


def test_every_section_has_rules():
    found = {rid.split("-")[1] for rid, _ in _rules(_wiki())}
    assert found == set(PREFIXES)


def test_the_code_table_counts_the_rules():
    """The `Rules` column of the code table at the top counts each section's rules; a struck-through
    one (`<b><s>SWE3-UH-03</s></b>`) is no longer counted."""
    text = _wiki()
    live = Counter(sec for sec in re.findall(r"<b>SWE3-([A-Z]+)-\d{2}</b></td>",
                                             text[:text.index("## Worked example")]))
    stated = {code: int(n) for code, n in re.findall(r"^\| ([A-Z]+) \|[^\n]*\| (\d+) \|$", text, re.M)
              if code in PREFIXES}
    assert stated == dict(live)


def test_no_id_is_written_without_its_prefix():
    for text in (_wiki(), _inventory()):
        assert _BARE.findall(text) == []


def test_every_id_is_defined_once():
    counts = Counter(rid for rid, _ in _rules(_wiki()))
    assert [rid for rid, n in counts.items() if n > 1] == []


def test_ids_count_up_from_01_in_each_section():
    numbers = {}
    for rid, _ in _rules(_wiki()):
        _, prefix, number = rid.split("-")
        numbers.setdefault(prefix, []).append(int(number))
    for prefix, seen in numbers.items():
        assert seen == list(range(1, len(seen) + 1)), f"{prefix}: {seen}"


def _open_questions(text):
    """The rule ids an `## Open questions` section names; the section is there only while a ⚠ is."""
    if "## Open questions" not in text:
        return set()
    return set(_ANY_ID.findall(_section(text, "## Open questions", "## Reference")))


def test_every_open_rule_is_in_open_questions():
    text = _wiki()
    open_ids = {rid for rid, row in _rules(text) if "⚠" in row}
    assert sorted(open_ids - _open_questions(text)) == []


def test_open_questions_name_open_rules_only():
    text = _wiki()
    open_ids = {rid for rid, row in _rules(text) if "⚠" in row}
    assert sorted(_open_questions(text) - open_ids) == []


def test_every_id_named_in_the_wiki_exists():
    text = _wiki()
    defined = {rid for rid, _ in _rules(text)}
    assert sorted(set(_ANY_ID.findall(text)) - defined) == []


def test_every_id_in_the_test_inventory_exists():
    defined = {rid for rid, _ in _rules(_wiki())}
    assert sorted(set(_ANY_ID.findall(_inventory())) - defined) == []


def test_every_test_the_inventory_names_exists():
    """The inventory went stale once (2026-07 → 2026-11) with a third of its tests gone: a renamed
    or deleted test must fail here, not leave a rule looking covered."""
    defs, files = set(), set()
    for top in ("unit", "api", "e2e", "live"):
        for folder, dirs, names in os.walk(os.path.join(ROOT, "tests", top)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in names:
                if not name.endswith(".py"):
                    continue
                files.add(name[:-3])
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
                    defs.update(re.findall(r"^\s*(?:def|class) (Test\w+|test_\w+)", fh.read(), re.M))
    named = set(re.findall(r"`((?:test_|Test)\w+)(?:\.py)?`", _inventory()))
    assert sorted(named - defs - files) == []


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
                    for rid in _ANY_ID.findall(fh.read()):
                        if rid not in defined:
                            missing.append(f"{os.path.relpath(path, ROOT)}: {rid}")
    assert missing == []
