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

`--model-store` defaults to `db` (doc 10 step 9). `effective_model_store` degrades that to
files when the machine cannot honour it, so the default is safe everywhere.
"""
from __future__ import annotations

import threading
from typing import Optional

from .paths import apply_cli_path_overrides

_LOCK = threading.Lock()
_VERSION_ID: Optional[str] = None
_PROJECT_ID: Optional[str] = None
_MODEL_STORE: str = "files"

# Flags this consumes, each taking one value.
_FLAGS = ("--version-id", "--project-id", "--model-store")


def version_id() -> Optional[str]:
    """The version this phase is working on, or None for a plain file-based run."""
    return _VERSION_ID


def project_id() -> Optional[str]:
    return _PROJECT_ID


def model_store_kind() -> str:
    """``"files"`` (default) or ``"db"``."""
    return _MODEL_STORE


def set_run_context(*, version: Optional[str] = None, project: Optional[str] = None,
                    model_store: Optional[str] = None) -> None:
    """Set the context in-process (the orchestrator's route; phases use the CLI)."""
    global _VERSION_ID, _PROJECT_ID, _MODEL_STORE
    with _LOCK:
        if version is not None:
            _VERSION_ID = version
        if project is not None:
            _PROJECT_ID = project
        if model_store is not None:
            _MODEL_STORE = model_store


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


def effective_model_store(requested: str, version_id: Optional[str]) -> str:
    """Resolve a requested backing store against what this machine can actually do.

    `db` is the default since step 9, which means it has to survive being the default on a
    machine with no database and on a CLI run whose version was never reserved. Both degrade to
    files *with a reason on stderr* rather than failing: the wrong backing store is a
    recoverable annoyance, a dead generation is not.

    Resolve ONCE, in the orchestrator, and pass the result down — a phase that picks its own
    answer can disagree with the orchestrator, which is the worst of both stores.
    """
    if requested != "db":
        return "files"
    if not version_id:
        why = "no version id"
    else:
        from .db import is_database_configured
        if not is_database_configured():
            why = "no database configured"
        elif not _version_row_exists(version_id):
            why = f"no versions row for {version_id!r} — the API reserves it at job start"
        else:
            return "db"
    import sys
    print(f"WARNING: model store 'db' requested but {why}; using model files instead.",
          file=sys.stderr)
    return "files"


def install_model_repository() -> str:
    """Install the model repository implied by the context. Returns the kind installed.

    Falls back to files — loudly — when `db` is asked for but unusable, rather than failing the
    phase: a run that cannot reach the database should say so and still produce a document from
    the files it has, not die at import.
    """
    from . import model_repo
    if _MODEL_STORE != "db":
        model_repo.set_repository(None)                     # the file default
        return "files"
    from .db import is_database_configured
    if not (_VERSION_ID and is_database_configured()):
        import sys
        why = "no --version-id" if not _VERSION_ID else "no database configured"
        print(f"WARNING: --model-store db requested but {why}; using model files.",
              file=sys.stderr)
        model_repo.set_repository(None)
        return "files"
    model_repo.set_repository(model_repo.DbRepository(_VERSION_ID, _PROJECT_ID or ""))
    return "db"


def apply_cli_run_context(argv) -> list:
    """Apply path overrides + run identity from `argv`; return argv without those flags."""
    argv = apply_cli_path_overrides(argv)
    out, i = [], 0
    version = project = store = None
    while i < len(argv):
        a = argv[i]
        if a in _FLAGS and i + 1 < len(argv):
            val = argv[i + 1]
            if a == "--version-id":
                version = val
            elif a == "--project-id":
                project = val
            else:
                store = val
            i += 2                                          # drop the flag AND its value
            continue
        out.append(a)
        i += 1
    set_run_context(version=version, project=project, model_store=store)
    install_model_repository()
    return out


def flush_model() -> None:
    """Persist anything the repository buffered. Called at the end of a phase.

    A no-op in file mode (writes already landed) and when nothing is pending, so it is safe to
    call unconditionally.
    """
    from . import model_repo
    model_repo.flush()
