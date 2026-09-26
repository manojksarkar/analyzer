"""Only two places may write a `version_output_files` row.

`REQ-AP-01` holds because view output is DERIVED: the model (or, for the two Phase-3 kinds, the
override table) is the one source, and the rows are rebuilt from it. A third writer means the rows
can say something the source does not, and the two-copies bug class is back -- which is exactly
what `interface_tables.json` holding its own copy of `description` already cost this project.

The design used to state the invariant as "nothing but a VIEW_REGISTRY call writes a row". That
became false the moment a correction could be saved without running the pipeline (`REQ-AP-06`), and
it could not be kept: `persist_output_files` deletes every row for a version and rebuilds from a
full `output_dir` walk, so there is no single-row form and a save has no output dir.

So it is restated with two named writers and checked here. An invariant nobody checks is a comment,
and this codebase has been bitten by a guard that silently stopped running.
"""
import os
import re

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: repo-relative, POSIX-spelled.
ALLOWED = {
    "engine/core/model_store.py",       # persist_output_files: after a view runs
    "engine/review/rerender.py",        # write_output_row: after a correction (REQ-AP-06)
}

SEARCHED = ("engine", "api", "tools")

#: A write through SQLAlchemy Core against the table. `select(...)` is a read and not matched.
WRITE = re.compile(r"\b(?:insert|update|delete)\s*\(\s*[\w.]*version_output_files")


def _sources():
    for top in SEARCHED:
        for root, dirs, files in os.walk(os.path.join(PROJECT_ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
            for fn in files:
                if fn.endswith(".py"):
                    path = os.path.join(root, fn)
                    rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
                    try:
                        yield rel, open(path, encoding="utf-8").read()
                    except (OSError, UnicodeDecodeError):
                        continue


def test_no_third_writer_of_version_output_files():
    writers = sorted({rel for rel, src in _sources() if WRITE.search(src)})
    unexpected = [w for w in writers if w not in ALLOWED]
    assert not unexpected, (
        "these write version_output_files rows but are not one of the two sanctioned writers: %s.\n"
        "A row that something else can write is a row that can disagree with the model it is "
        "supposed to be derived from (REQ-AP-01). Either route the write through "
        "review.rerender.write_output_row, or add it to ALLOWED here with the reason."
        % ", ".join(unexpected))


def test_both_sanctioned_writers_still_exist():
    """If one is renamed or removed, ALLOWED silently stops meaning anything and this file turns
    into decoration. Better to fail and be updated."""
    writers = {rel for rel, src in _sources() if WRITE.search(src)}
    missing = sorted(ALLOWED - writers)
    assert not missing, (
        "%s no longer writes version_output_files. If that is deliberate, drop it from ALLOWED; "
        "if it was renamed, update ALLOWED so the check keeps covering it." % ", ".join(missing))


def test_the_check_would_notice_a_new_writer():
    """The regex is the whole guard, so prove it matches what it claims to and not reads."""
    assert WRITE.search("conn.execute(insert(s.version_output_files).values(x=1))")
    assert WRITE.search("conn.execute(update(s.version_output_files).where(...))")
    assert WRITE.search("conn.execute(delete(s.version_output_files))")
    assert WRITE.search("op.bulk_insert(version_output_files, rows)") is None
    assert not WRITE.search("select(s.version_output_files.c.content)")
