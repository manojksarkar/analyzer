"""What a phase needs to know about the run it is part of (doc 10, step 3).

Each phase is its own process, so it starts knowing nothing. Historically it inferred everything
from the filesystem: the model was "whatever is in `model/`". That is implicit, ambiguous, and
stops working entirely once the model lives in the database — there, a phase has to be told
WHICH version it is working on (D10-8).

One call at the top of every phase establishes the lot:

    sys.argv = apply_cli_run_context(sys.argv)

It applies the path overrides, records the version/project identity, and installs the model
repository. Returns argv with its own flags removed, because `docx_exporter` parses POSITIONAL
arguments — an unconsumed flag becomes a file path.

**Must run before `paths()` is snapshotted.** Three of the four phases cache `paths()` into
module constants at import; applying overrides later leaves those constants pointing at the
default directories while the run uses per-version ones. That exact ordering caused a release
where an incremental run silently emitted only the diagrams it regenerated — see
`tests/unit/test_phase_path_overrides.py`, which guards it.

The model lives in Postgres and nowhere else. `effective_model_store` is the check that a run
can actually reach it, run ONCE in the orchestrator so a phase cannot answer differently from
the run that spawned it.
"""
from __future__ import annotations

import threading
from typing import Optional

from .paths import apply_cli_path_overrides

_LOCK = threading.Lock()
_VERSION_ID: Optional[str] = None
_PROJECT_ID: Optional[str] = None
_SCRATCH_MODEL: bool = False

# Flags this consumes, each taking one value.
_FLAGS = ("--version-id", "--project-id")
# ...and this one, which takes none. The narrowed parse's partial pass sets it: that model is
# scratch for parse_merge, not a version's. Phases are separate processes, so it has to travel
# on the command line like the run identity does.
_SCRATCH_FLAG = "--model-scratch"


def version_id() -> Optional[str]:
    """The version this phase is working on. Every real run has one."""
    return _VERSION_ID


def project_id() -> Optional[str]:
    return _PROJECT_ID


def scratch_model() -> bool:
    """True when this run's model is scratch for a merge, not a version's."""
    return _SCRATCH_MODEL


def set_run_context(*, version: Optional[str] = None, project: Optional[str] = None,
                    scratch: Optional[bool] = None) -> None:
    """Set the context in-process (the orchestrator's route; phases use the CLI)."""
    global _VERSION_ID, _PROJECT_ID, _SCRATCH_MODEL
    with _LOCK:
        if version is not None:
            _VERSION_ID = version
        if project is not None:
            _PROJECT_ID = project
        if scratch is not None:
            _SCRATCH_MODEL = bool(scratch)


def _create_version_row(version_id: str, project_id: str, commit: str) -> bool:
    """Reserve the versions row a CLI run needs. True on success.

    Only ever called behind an explicit `--create-version`: the row is normally the API's to
    own, and creating one silently would turn a mistyped `--version-id` into a brand-new
    version rather than the error it should be.
    """
    try:
        import datetime
        import sqlalchemy as sa
        from api.db.postgres import schema as s
        from .db import get_engine
        with get_engine().begin() as cx:
            if not cx.execute(sa.select(s.projects.c.id)
                              .where(s.projects.c.id == project_id)).first():
                import sys
                print(f"WARNING: no project {project_id!r} — run `python analyzer.py onboard` first.",
                      file=sys.stderr)
                return False
            cx.execute(sa.insert(s.versions), {
                "id": version_id, "project_id": project_id, "version": version_id,
                "commit_sha": commit, "status": "in_review",
                "created_at": datetime.datetime.now(datetime.timezone.utc)})
        return True
    except Exception as exc:
        import sys
        print(f"WARNING: could not reserve the versions row ({exc}).", file=sys.stderr)
        return False


def _version_row_exists(version_id: str) -> bool:
    """Is there a `versions` row to hang this run's model off?

    Everything per-version is foreign-keyed to it, and the row is owned by the API (reserved at
    job start) — `PgStore` never creates one. So a CLI run against a version the API has not
    reserved would fail on the first insert, which is a poor way for a *default* to behave.
    """
    try:
        import sqlalchemy as sa
        from api.db.postgres import schema as s
        from .db import get_engine
        with get_engine().connect() as cx:
            return cx.execute(sa.select(s.versions.c.id)
                              .where(s.versions.c.id == version_id)).first() is not None
    except Exception as exc:                                # unreachable DB, missing table, …
        import sys
        print(f"WARNING: could not read the versions table ({exc}).", file=sys.stderr)
        return False


class DatabaseRequired(RuntimeError):
    """The run needs the database and cannot have it. Raised instead of quietly using files."""


def effective_model_store(version_id: Optional[str],
                          *, project_id: str = "", commit: str = "",
                          create_version: bool = False) -> str:
    """Check that this run can actually reach the database. Raises if it cannot.

    There is nothing to fall back to. The model, the parse artifacts and the phase hand-offs
    are all rows, so a run that could not reach the database and carried on would produce a
    version that LOOKS generated and is missing from every table the API reads. Failing at the
    start beats that.

    Resolve ONCE, in the orchestrator, and pass the result down — a phase that answers
    differently from its orchestrator leaves half a model in each store.
    """
    if not version_id:
        why, fix = ("no version id was given", "pass --version-id <id>")
    else:
        from .db import is_database_configured
        if not is_database_configured():
            why = "no database is configured"
            fix = ("set the `db` section in engine/config/config.local.json, then run "
                   "`python analyzer.py setup`")
        elif not _version_row_exists(version_id):
            if create_version and project_id and commit:
                if _create_version_row(version_id, project_id, commit):
                    return "db"
                why = f"could not create the versions row for {version_id!r}"
                fix = "check the database is writable and the project id exists"
            else:
                why = f"there is no versions row for {version_id!r}"
                # Name the command, not a design document. The row is trivially creatable and
                # the tool that does it already exists; sending someone to read §9 of a plan to
                # find that out is a poor trade for one line of output.
                _pid = project_id or "<project-id>"
                _sha = commit or "<full-40-char-sha>"
                fix = (f"reserve it first —\n"
                       f"    python analyzer.py onboard --project-id {_pid} "
                       f"--version-id {version_id} --commit {_sha}\n"
                       f"  or add --create-version to this command to do it in one step. "
                       f"(The API reserves the row itself when a job starts.)")
        else:
            return "db"
    raise DatabaseRequired(
        f"this run needs the database but {why}.\n"
        f"  Fix: {fix}.\n"
        f"  The model, parse artifacts and phase hand-offs are all database rows now, so "
        f"continuing would produce a version that looks generated and is not there.")


def install_model_repository() -> str:
    """Install this run's model repository. Returns "db", or "" when there is nothing to install.

    It used to fall back to model files when the database was out of reach. There is no file
    backing any more, so there is nothing to fall back TO: a phase with no version id or no
    database simply has no repository, and the first read says so by name. Silence here was the
    old hazard — a run wrote a model to disk, said nothing, and left the version empty in every
    table the API reads.
    """
    from . import model_repo
    if _SCRATCH_MODEL:
        model_repo.set_repository(model_repo.ScratchRepository())
        return "scratch"
    from .db import is_database_configured
    if not (_VERSION_ID and is_database_configured()):
        model_repo.set_repository(None)
        return ""
    model_repo.set_repository(model_repo.DbRepository(_VERSION_ID, _PROJECT_ID or ""))
    return "db"


def apply_cli_run_context(argv) -> list:
    """Apply path overrides + run identity from `argv`; return argv without those flags."""
    argv = apply_cli_path_overrides(argv)
    out, i = [], 0
    version = project = None
    scratch = False
    while i < len(argv):
        a = argv[i]
        if a == _SCRATCH_FLAG:
            scratch = True
            i += 1
            continue
        if a in _FLAGS and i + 1 < len(argv):
            val = argv[i + 1]
            if a == "--version-id":
                version = val
            else:
                project = val
            i += 2                                          # drop the flag AND its value
            continue
        out.append(a)
        i += 1
    set_run_context(version=version, project=project, scratch=scratch)
    install_model_repository()
    return out


def flush_model() -> None:
    """Persist anything the repository buffered. Called at the end of a phase.

    A no-op in file mode (writes already landed) and when nothing is pending, so it is safe to
    call unconditionally.
    """
    from . import model_repo
    model_repo.flush()
