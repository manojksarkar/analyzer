"""The project context stays readable whole — by Claude or any other assistant, one read per file.

PROJECT_CONTEXT.md had grown to 8,991 lines (750 KB) with the dated change log on top. A new
session read its first 2,000 lines — the newest change notes — and never reached the architecture,
which began at line 4,831. Since 2026-09-28 it is an index, and the detail is in `project-context/`:
topic files and the dated history, each small enough for one read. Nothing breaks when a file grows
past that; a reader just stops early and never knows what it missed. So the limits are checked here.
"""
import os
import re

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(ROOT, "PROJECT_CONTEXT.md")
CONTEXT = os.path.join(ROOT, "project-context")

#: CLAUDE.md imports the index, so it is loaded into every session.
INDEX_MAX_LINES = 300
#: One Claude Code read returns at most 2,000 lines and 25,000 tokens. 60,000 characters of this
#: text is about 20k tokens — room for denser content.
FILE_MAX_LINES = 1200
FILE_MAX_CHARS = 60000
#: Some tools cut a line longer than this.
LINE_MAX_CHARS = 2000

_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)\s]*)?\)")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def _context_files():
    for folder, _dirs, files in sorted(os.walk(CONTEXT)):
        for name in sorted(files):
            yield os.path.join(folder, name)


def _index_links():
    return [t for t in _LINK.findall(_read(INDEX)) if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", t)]


def _rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def test_the_index_is_short():
    lines = _read(INDEX).count("\n")
    assert lines <= INDEX_MAX_LINES, (
        "PROJECT_CONTEXT.md has %d lines (limit %d). It is the index and is loaded into every "
        "session: move the detail into the project-context/ file for its area and link it."
        % (lines, INDEX_MAX_LINES))


@pytest.mark.parametrize("path", list(_context_files()), ids=_rel)
def test_every_context_file_fits_one_read(path):
    text = _read(path)
    lines, chars = text.count("\n"), len(text)
    longest = max((len(l) for l in text.split("\n")), default=0)
    assert lines <= FILE_MAX_LINES and chars <= FILE_MAX_CHARS, (
        "%s: %d lines, %d characters (limits %d / %d), so a reader gets only part of it. A history "
        "file: start the next NN-<date>.md and add its row to PROJECT_CONTEXT.md. A topic file: "
        "split it by section and update the index's table."
        % (_rel(path), lines, chars, FILE_MAX_LINES, FILE_MAX_CHARS))
    assert longest <= LINE_MAX_CHARS, (
        "%s has a %d-character line; some tools cut lines past %d. Break it — inside a "
        "blockquote, continue on a new line starting with '> '." % (_rel(path), longest, LINE_MAX_CHARS))


def test_every_context_file_is_linked_from_the_index():
    linked = {os.path.normpath(os.path.join(ROOT, t)) for t in _index_links()}
    orphans = [_rel(p) for p in _context_files() if os.path.normpath(p) not in linked]
    assert not orphans, (
        "not linked from PROJECT_CONTEXT.md, so no session will find them: %s" % orphans)


def test_every_link_in_the_index_resolves():
    broken = sorted({t for t in _index_links() if not os.path.exists(os.path.join(ROOT, t))})
    assert not broken, "PROJECT_CONTEXT.md links to files that do not exist: %s" % broken


def test_claude_loads_the_index_and_other_assistants_are_sent_to_it():
    claude = _read(os.path.join(ROOT, "CLAUDE.md"))
    assert "@PROJECT_CONTEXT.md" in claude.split("\n"), (
        "CLAUDE.md must import the index on a line of its own (`@PROJECT_CONTEXT.md`), so every "
        "Claude session starts with it loaded")
    assert "PROJECT_CONTEXT.md" in _read(os.path.join(ROOT, "AGENTS.md"))
