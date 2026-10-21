"""Only the job repositories write a job's status.

A status changes by `jobs.transition()` -- one statement that checks the status it changes from --
and `jobs.update()` never writes it (`JOB_STATE_FIELDS`; `tests/api/test_job_state_writes.py`). That
holds only while nothing else writes the column: a raw `update(analysis_jobs).values(status=...)`
elsewhere could put back "running" over a cancel exactly as the old whole-row `update()` did
(docs/design/JOB_SCHEDULING_DESIGN.md §1). Checked here, as `test_output_row_writers.py` checks its
table.
"""
import os
import re

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: repo-relative, POSIX-spelled.
ALLOWED = {
    "api/db/postgres/database.py",      # _JobRepo.transition: the one SQL writer of the status
}

SEARCHED = ("engine", "api", "tools")
EXTRA_FILES = ("analyzer.py",)

#: A name the table goes by in a file: `j = s.analysis_jobs`.
ALIAS = re.compile(r"\b(\w+)\s*=\s*(?:[\w.]+\.)?analysis_jobs\b(?!\s*\.)")


def _writes_status(src: str) -> bool:
    """A SQLAlchemy Core update of analysis_jobs -- by its name or an alias -- whose values name
    the status."""
    names = ["[\\w.]*analysis_jobs"] + [re.escape(a) for a in set(ALIAS.findall(src))]
    write = re.compile(r"update\(\s*(?:%s)\s*\)(?:(?!update\()[\s\S]){0,400}?"
                       r"\.values\([^)]*\bstatus\s*=" % "|".join(names))
    return bool(write.search(src))


def _sources():
    paths = [os.path.join(PROJECT_ROOT, f) for f in EXTRA_FILES]
    for top in SEARCHED:
        for root, dirs, files in os.walk(os.path.join(PROJECT_ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
            paths += [os.path.join(root, fn) for fn in files if fn.endswith(".py")]
    for path in paths:
        rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
        try:
            yield rel, open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue


def test_no_other_writer_of_a_jobs_status():
    writers = sorted({rel for rel, src in _sources() if _writes_status(src)})
    unexpected = [w for w in writers if w not in ALLOWED]
    assert not unexpected, (
        "these write analysis_jobs.status but are not the job repository: %s.\n"
        "Change a job's status with db.jobs.transition(job_id, from_status, to_status, ...), "
        "which checks the status it changes from; a write that does not check it can undo a "
        "cancel." % ", ".join(unexpected))


def test_the_repository_still_writes_it():
    """If the writer is renamed or moved, ALLOWED silently stops meaning anything."""
    writers = {rel for rel, src in _sources() if _writes_status(src)}
    missing = sorted(ALLOWED - writers)
    assert not missing, (
        "%s no longer writes analysis_jobs.status. If it moved, update ALLOWED so the check keeps "
        "covering it." % ", ".join(missing))


def test_the_check_would_notice_a_new_writer():
    """The regex is the whole guard, so prove it matches what it claims to and not other writes."""
    assert _writes_status("cx.execute(update(s.analysis_jobs).where(j.c.id == i).values(status='x'))")
    assert _writes_status("cx.execute(update(analysis_jobs)\n    .where(c)\n    .values(\n"
                          "        error_message=m, status=to))")
    assert _writes_status("t = s.analysis_jobs\ncx.execute(update(t).where(c).values(status=s))")
    assert not _writes_status("cx.execute(update(s.analysis_jobs).where(c).values(version_id=None))")
    assert not _writes_status("update(s.versions).values(status='draft')")
    assert not _writes_status("t = s.analysis_jobs\nupdate(s.versions).values(status='draft')")
    assert not _writes_status("j = s.analysis_jobs.c.status\nupdate(j)")
