"""Re-onboarding must not silently keep an old --source / --branch.

An existing projects row used to mean "nothing to do", so an explicitly passed --source
was dropped and the row kept whatever the FIRST onboard recorded. `generate` clones from
projects.repo_url, so the run then fetched a repo the caller never named -- and the
failure surfaced far away, blaming the wrong thing:

    fatal: Remote branch Ravora/Proj/v2_LOP_Auto not found in upstream origin

The branch was present in the source on the command line. It was missing from the OLD
one still in the database. Onboard exited 0 throughout.

These are pointers the caller supplied on the command line, not hand-editable content
like the config, so an explicit value updates the row. Only when explicitly passed (a
plain re-onboard for a new version keeps what is stored) and only when different (the
common case stays quiet).
"""

import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SRC = os.path.join(_ROOT, "tools", "new_project.py")


def _existing_branch():
    """The `if existing:` arm of the projects-row step."""
    with open(_SRC, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("        if existing:")
    j = src.index("        else:", i)
    return src[i:j]


def test_an_explicit_source_updates_the_row():
    body = _existing_branch()
    assert "sa.update(s.projects)" in body
    assert "repo_url" in body


def test_an_explicit_branch_updates_the_row():
    assert "default_branch" in _existing_branch()


def test_only_when_explicitly_passed():
    """A re-onboard that names no source must keep the stored one, or every
    `--project-id x --version-id v2` call would blank the repo."""
    body = _existing_branch()
    assert "if args.repo_url and" in body
    assert "if args.branch and" in body


def test_the_change_is_printed():
    """Silently repointing a project at a different repo is its own trap."""
    body = _existing_branch()
    assert "UPDATED" in body


def test_unchanged_values_are_not_rewritten():
    """Comparing against the current row is what keeps the common path quiet."""
    body = _existing_branch()
    assert "cur.repo_url" in body and "cur.default_branch" in body
    assert "if changes:" in body
