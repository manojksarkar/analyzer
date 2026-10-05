#!/usr/bin/env python3
"""analyzer — the one command. C++ source in, ASPICE SWE.3 documents out.

    python analyzer.py --help
    python analyzer.py <command> --help

There used to be four front doors — `tools/new_project.py`, `python -m incremental.generate`,
`python -m incremental.engine`, and `engine/run.py` — and knowing which one a given job wanted
was folklore. Worse, two of them did almost the same thing: `generate` produced a first version
and `engine` produced a later one, and picking wrong either wasted an hour re-parsing or failed
outright. That choice is made here now, from the data: `generate` looks for a usable baseline
and takes the incremental path when there is one.

`engine/run.py` still exists and still runs the four phases. It is not a front door any more —
it is what the orchestrator spawns per phase, the way a compiler spawns an assembler.

Everything below is a thin, honest wrapper: this file decides nothing about how a version is
produced. It parses arguments and calls the same functions the API calls.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import textwrap

_ROOT = os.path.dirname(os.path.abspath(__file__))
# tools/ is not a package and engine/ is imported by bare module name from inside the phases,
# so both go on the path exactly as every existing entry point does it.
for _p in (_ROOT, os.path.join(_ROOT, "engine"), os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------

def _tool(module: str, argv: list) -> int:
    """Run a `tools/<module>.py` in-process with `argv` as its command line.

    In-process rather than as a subprocess so a failure keeps its traceback and the exit code
    is the tool's own. The argv swap is needed because the older tools read `sys.argv`
    directly instead of taking a parameter.
    """
    mod = importlib.import_module(module)
    main = getattr(mod, "main", None)
    if main is None:
        raise SystemExit(f"internal: tools/{module}.py has no main()")
    saved = sys.argv
    sys.argv = [f"{module}.py", *argv]
    try:
        import inspect
        if inspect.signature(main).parameters:
            return int(main(argv) or 0)
        return int(main() or 0)
    finally:
        sys.argv = saved


def _script(path: str, argv: list) -> int:
    """Run a script as a SUBPROCESS. For the ones that do their work at import time — they
    cannot be called twice in one process, and one of the gates is written that way."""
    import subprocess
    return subprocess.run([sys.executable, path, *argv], cwd=_ROOT).returncode


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_setup(a) -> int:
    """Create or upgrade the schema. Safe to re-run; required after a git pull that brings a
    migration, because a missing one shows up as a feature that silently does nothing."""
    rc = _tool("db_setup", [])
    if rc == 0 and a.demo:
        rc = _tool("seed_db", [])
    return rc


def cmd_onboard(a) -> int:
    """The four things a project needs before it can be generated, none of which the engine
    creates for itself: the `projects` row, the workspace directory, the per-project config,
    and (optionally) the first `versions` row."""
    argv = ["--project-id", a.project_id, "--branch", a.branch]
    if a.name:
        argv += ["--name", a.name]
    if a.source:
        argv += ["--repo-url", a.source]
    if a.config:
        argv += ["--config", a.config]
    if a.use_defaults:
        argv += ["--use-defaults"]
    if a.force_config:
        argv += ["--force-config"]
    if a.version_id:
        argv += ["--version-id", a.version_id]
    if a.commit:
        argv += ["--commit", a.commit]
    rc = _tool("new_project", argv)
    if rc == 0:
        rc = _grant_after_onboard(a)
    return rc


def _grant_after_onboard(a) -> int:
    """Give somebody API access to what we just onboarded.

    Without a `project_members` row the project is invisible over HTTP to an ORDINARY user:
    `GET /projects` lists only what you are a member of, and every `/projects/{id}/...` route
    answers 403. The API's own create-project endpoint adds the caller for exactly this reason;
    the CLI has no caller, so it adds the superusers instead.

    A superuser reaches the project either way — `require_project_member` lets them through
    without a row, which is what makes their access reliable. The row is still written, because
    the team list and `my_role` are READ from `project_members`: without it the operator appears
    on no team and the UI greys out controls the API will honour.

    Never fatal. The project IS onboarded and generates fine from the CLI at this point; failing
    the command over an access row would be the tail wagging the dog. It says so instead.
    """
    argv = ["--project-id", a.project_id, "--role", a.owner_role]
    if a.owner_all:
        argv.append("--all")
    elif a.owner:
        argv += ["--email", a.owner]
    else:
        argv.append("--superusers")
    try:
        return _tool("grant_access", argv)
    except Exception as exc:                       # noqa: BLE001 - see docstring
        print(f"\nonboarded, but could not grant API access ({exc}).")
        print(f"      python analyzer.py grant --project-id {a.project_id} --email <you>")
        return 0


def cmd_grant(a) -> int:
    """Give a user access to a project, so the API will serve it.

    Authorisation here is per project, via `project_members`, so a project nobody was added to has
    nobody who can read it over HTTP, whichever account you sign in with. The one exception is a
    superuser (`users.is_superuser`), who reaches every project -- and nobody is one unless made
    one on purpose: `python tools/grant_access.py --set-superuser --email <address>`.
    """
    argv = ["--project-id", a.project_id, "--role", a.role]
    argv += ["--all"] if a.all else ["--email", a.email]
    return _tool("grant_access", argv)


def cmd_user(a) -> int:
    """User accounts: add one (and, with --project-id, make it a member), reset a password, list.

    An account is what signs in; a project membership (`grant`, or --project-id here) is what lets
    it see a project. Without --password a temporary one is made and printed ONCE: pass it on, and
    the person changes it after signing in. The web app's Team page creates accounts the same way
    when it invites an address that has none.
    """
    from core.db import is_database_configured
    if not is_database_configured():
        print("no database is configured.", file=sys.stderr)
        return 2
    from api.db.postgres.database import SqlDatabase
    from api.services import accounts
    db = SqlDatabase()

    if a.action == "list":
        users = sorted(db.users.search("", limit=100000), key=lambda u: u.email)
        for u in users:
            print(f"{u.email:<36} {u.name:<28} {'superuser' if u.is_superuser else ''}")
        print(f"\n{len(users)} account(s)")
        return 0

    if not a.email:
        print("--email is required.", file=sys.stderr)
        return 2
    try:
        if a.action == "add":
            user, temp = accounts.create_user(db, a.email, a.name, a.password)
            print(f"created  {user.email} ({user.name})")
        else:                                           # password
            user = accounts.find_user(db, a.email)
            if user is None:
                print(f"no account uses {a.email}.", file=sys.stderr)
                return 2
            temp = accounts.set_password(db, user, a.password)
            print(f"password set for {user.email}")
    except accounts.AccountError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if temp:
        print(f"temporary password: {temp}\n  (shown once; they change it after signing in)")
    if a.action == "add" and a.project_id:
        return _tool("grant_access", ["--project-id", a.project_id, "--role", a.role,
                                      "--email", user.email])
    return 0


def _project_defaults(project_id: str, version_id: str):
    """The branch and commit already recorded for this project and version.

    `onboard` writes both - the project's `default_branch` and the version's `commit_sha` -
    so asking for them again on every generate is asking the caller to repeat what the
    database already knows. Worse, `--branch` defaulted to "main": a project on `br_trunk`
    failed with `fatal: Remote branch main not found`, from a flag the caller never typed.
    """
    branch = commit = None
    try:
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            return None, None
        import sqlalchemy as sa
        from api.db.postgres import schema as sch
        with get_engine().connect() as cx:
            row = cx.execute(sa.select(sch.projects.c.default_branch)
                             .where(sch.projects.c.id == project_id)).first()
            if row:
                branch = row[0]
            if version_id:
                row = cx.execute(sa.select(sch.versions.c.commit_sha)
                                 .where(sch.versions.c.id == version_id)).first()
                if row:
                    commit = row[0]
    except Exception:
        pass                                # falls back to the flags; never fails a run
    return branch, commit


def _version_id_for(project_id: str, version: str) -> str:
    """The `versions.id` of this project's `version`, given its name or its id.

    `--version-id` is a name, unique only inside its project; the engine works on the row's id.
    One that does not exist yet gets the id `--create-version` reserves it under, so the run's
    own missing-version check still speaks, with the fix in it.
    """
    from core.run_context import resolve_version, version_key
    try:
        from core.db import is_database_configured
        if is_database_configured():
            vid = resolve_version(project_id, version)
            if vid:
                return vid
    except Exception:
        pass                    # an unreachable database is reported by the run's own check
    return version_key(project_id, version)


def cmd_generate(a) -> int:
    """Produce a version.

    FULL or INCREMENTAL is not a question the caller should have to answer. `generate_incremental`
    already resolves a baseline and returns `decision: "full"` when there is no usable one, in
    which case it delegates to `generate_full` itself — so the honest default is to always ask
    for incremental and let the data decide. `--full` forces the long way round.

    No `--scope`: a first version is the whole project; a later one makes what its baseline has
    (its scope, and every component it has documents for). `--model-only` stops after Phase 2;
    `analyzer.py export` makes the documents later, per component, into the same version. A run
    that lasts hours or days: `--detach` (a frozen copy of the code, in the background).
    """
    from incremental.generate import generate_full, AnalyzerRunFailed
    from incremental.engine import generate_incremental
    from core.run_context import DatabaseRequired
    from incremental.git_ops import GitError

    # Resolved once, here, so nothing downstream can look a version up without its project.
    name = a.version_id
    a.version_id = _version_id_for(a.project_id, name)
    if a.base_version:
        a.base_version = _version_id_for(a.project_id, a.base_version)
    _branch, _commit = _project_defaults(a.project_id, a.version_id)
    branch = a.branch or _branch or "main"
    commit = a.commit or _commit
    if not commit:
        print(f"no --commit given, and version {name!r} has no commit recorded.\n"
              f"  Either pass --commit <full-40-char-sha>, or reserve the version first:\n"
              f"    python analyzer.py onboard --project-id {a.project_id} "
              f"--version-id {name} --commit <sha>", file=sys.stderr)
        return 2

    scope = _parse_scope(a.scope) if a.scope else None
    common = dict(data_dict_id=a.data_dict, no_llm=a.no_llm, version_id=a.version_id,
                  config_path=a.config, repo_url=a.source, create_version=a.create_version,
                  selected_units=a.unit, doc_type=a.doc_type,
                  model_only=bool(getattr(a, "model_only", False)))
    if a.create_version:
        # The run record hangs off the version row, so reserve the row before the run starts
        # rather than at the parse. Idempotent; a failure is reported by the run's own check.
        try:
            from core.run_context import effective_model_store
            effective_model_store(a.version_id, project_id=a.project_id, commit=commit,
                                  create_version=True)
        except Exception:                           # noqa: BLE001
            pass
    # The phases mark how far they got on the version row (`set_pipeline_status`), which is
    # what `resume` and `progress` read. They find the version here, as under the API.
    os.environ["ANALYZER_VERSION_ID"] = a.version_id
    _retry_connects_for_run()
    from core.version_run import VersionBusy, writing
    try:
        with writing(a.version_id, command="generate", argv=getattr(a, "_argv", None),
                     log_path=os.environ.get("ANALYZER_RUN_LOG"),
                     code_dir=os.environ.get("ANALYZER_RUN_CODE")) as run:
            return run.ok(_generate(a, name, branch, commit, scope, common,
                                    generate_full, generate_incremental,
                                    AnalyzerRunFailed, DatabaseRequired, GitError))
    except VersionBusy as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _generate(a, name, branch, commit, scope, common, generate_full, generate_incremental,
              AnalyzerRunFailed, DatabaseRequired, GitError) -> int:
    try:
        if a.full:
            m = generate_full(a.project_id, branch, commit, scope, force=a.force, **common)
        else:
            m = generate_incremental(a.project_id, branch, commit, scope,
                                     base_version_id=a.base_version, force=a.force,
                                     narrowed_parse=not a.no_narrowed_parse,
                                     verify_parse=a.verify_parse,
                                     scope_from_baseline=scope is None, **common)
    except AnalyzerRunFailed as exc:
        # Exit 2 is the analyzer's USAGE code: it already printed what was wrong, in a form
        # built to be acted on. A traceback here would push that message off the screen.
        if getattr(exc, "returncode", 1) == 2:
            print("\nStopped: see the error above.", file=sys.stderr)
            return 2
        # 3: some components' documents failed; the others were made (run.py goes on).
        if getattr(exc, "returncode", 1) == 3:
            print(f"\nSome components failed (above); the others were made. Once the cause is "
                  f"fixed:\n    python analyzer.py resume --project-id {a.project_id} "
                  f"--version-id {name}", file=sys.stderr)
            return 3
        raise
    except DatabaseRequired as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except GitError as exc:
        # The commonest one by far is a branch that does not exist, and a traceback buries
        # the one line that says so.
        msg = str(exc)
        print(f"\ngit could not fetch that commit:\n  {msg}", file=sys.stderr)
        if "Remote branch" in msg and "not found" in msg:
            # Say WHICH sense of "not there": for a local source the branch is usually
            # present as a remote-tracking ref and `git branch -a` shows it, so "not in
            # that repository" reads as plainly wrong and sends people hunting for a
            # typo that does not exist.
            print(f"\n  git resolves --branch against the source's LOCAL branches only "
                  f"(refs/heads).\n  {branch!r} may still be there as a remote-tracking "
                  f"ref -- `git branch -a` shows both. Check which:\n\n"
                  f"      git -C <source> branch --format=%(refname:short)   # local\n"
                  f"      git -C <source> branch -r                          # tracking\n\n"
                  f"  If it shows only in the second, create it locally there:\n"
                  f"      git -C <source> branch {branch} origin/{branch}\n"
                  f"  or pass a branch that is local. Re-onboard to change the recorded "
                  f"default.", file=sys.stderr)
        return 2

    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, regenerated={m.get('regenerated')}, "
          f"reused={m.get('reused')}, documents={m.get('documents')}")
    if not getattr(a, "no_register", False):
        _register_for_review(a.project_id, a.version_id)
    if m.get("componentsFailed"):
        print(f"\nSome components failed (above); the others were made and recorded. Once the "
              f"cause is fixed:\n    python analyzer.py resume --project-id {a.project_id} "
              f"--version-id {name}", file=sys.stderr)
        return 3
    return 0


def _retry_connects_for_run() -> None:
    """This process is a run from here on: its database engine, made earlier for the checks,
    tries a refused or timed-out connection again (core.db.retry_connects)."""
    try:
        from core.db import retry_connects_for_run
        retry_connects_for_run()
    except Exception:                               # noqa: BLE001 - the run goes on without
        pass


def _register_for_review(project_id: str, version_id: str) -> int:
    """Record the version's documents for review and approval, and open their review; returns
    how many were new. Idempotent: what is recorded already is left alone.

    The web app's job runner always did this after a run; a run from the command line did not,
    so its documents could not be assigned, reviewed or approved (REVIEW_APPROVE_API_SPEC §4).
    Never fails the command: the documents are on disk and in the database either way, and
    `analyzer.py register` does this again by hand.
    """
    try:
        from core.db import is_database_configured
        if not is_database_configured():
            return 0
        from api.db.postgres.database import SqlDatabase
        from api.services.document_registry import register_documents
        db = SqlDatabase()
        project, version = db.projects.get(project_id), db.versions.get(version_id)
        if project is None or version is None:
            print(f"note: no project {project_id!r} / version {version_id!r} row to register "
                  f"documents under.", file=sys.stderr)
            return 0
        docs = register_documents(db, project, version)
        carried = sum(1 for d in docs if d.status == "approved")
        if docs:
            print(f"review: {len(docs)} document(s) recorded for review"
                  + (f"; {carried} keep their approval (unchanged since the baseline)" if carried else ""))
        return len(docs)
    except Exception as exc:                        # noqa: BLE001 -- see docstring
        print(f"note: the documents could not be recorded for review ({type(exc).__name__}: {exc}).\n"
              f"  Do it later with:  python analyzer.py register --project-id {project_id} "
              f"--version-id {version_id}", file=sys.stderr)
        return 0


def cmd_register(a) -> int:
    """Record a generated version's documents for review and approval, without regenerating.

    For a version generated before review and approval existed, or one whose run could not record
    them. Each real Word file of the version gets a document (SWE.3, SWE.4); one recorded already is
    left alone. Their review opens as after a run: a document unchanged since the baseline keeps its
    approval, the others start In review with the baseline's reviewer.
    """
    name = a.version_id
    vid = _version_id_for(a.project_id, name)
    known = _known_versions(a.project_id)
    if not any(v[0] == vid for v in known):
        return _no_such_version(a.project_id, name, known)
    n = _register_for_review(a.project_id, vid)
    if not n:
        print("nothing new to record: every Word file of this version already has its document.")
    return 0



def _refuse_stale_export(version_id: str, doc_type: str = None, *, quiet: bool = False) -> int:
    """0 if this version's `doc_type` documents are safe to export only (REQ-AP-04), 2 if they
    would ship stale text (said on stderr unless `quiet`).

    Asked about the documents this export writes: a SWE.3 re-derive does not make the SWE.4 specs
    current, and SWE.4 specs a SWE.3 export does not print must not hold it up.

    Never blocks a run it cannot judge. With no database configured there is no override table
    to be stale against, and a guard that turns a missing optional feature into a failed export
    would be worse than the problem it prevents.
    """
    try:
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            return 0
        from review.export_guard import StaleExport, assert_exportable
        with get_engine().connect() as cx:
            assert_exportable(cx, version_id, doc_type)
    except ImportError:
        return 0
    except Exception as exc:
        if type(exc).__name__ != "StaleExport":
            # Could not check -- say so and continue. Silence here would look like a pass.
            print(f"note: could not check whether the views are up to date ({exc}).",
                  file=sys.stderr)
            return 0
        if not quiet:
            print(str(exc), file=sys.stderr)
            print("\n  Or re-run with --force to export anyway.", file=sys.stderr)
        return 2
    return 0


def _render_version(a, *, scope, command: str, after=None, before=None):
    """Phases `a.from_phase`..4 of a version from its STORED model, into that same version --
    the work behind `reexport`, `export` and `resume`. Returns (exit code, the documents stored).

    `a.from_phase`:

      2  re-derive -- rebuild units, components and summaries from the stored parse skeleton,
         then views and export. For a change to the deriver, or a run cut short in Phase 2.
      3  views + export. For a change to a view, or components not generated yet.
      4  export only. For a change to the DOCX template.

    Phase 1 is never re-run: the parse is the expensive part and it is already rows. To
    re-parse, run `generate`.

    Holds the version's writer lock while it runs (`core.version_run.writing`): storing the
    output REPLACES what was stored, so two writers at once lose the first one's documents.
    `after(documents)` runs inside the lock once the output is stored (`resume` closes the
    version there). `before(cfg, own_cfg, checkout, doc_type)` runs inside the lock before the
    phases, and a non-zero answer stops there (`export` adds a layer to the model with it).
    """
    from incremental.store import make_store
    store = make_store(a.project_id)
    adir = store.artifact_dir(a.version_id)
    name = getattr(a, "_name", a.version_id)
    # WHICH config this version ran with, resolved exactly as generate_full resolves it.
    # A per-version config.json is written only when there is no per-project one, or when
    # --no-llm forced a rewrite; a normal run uses workspaces/<pid>/config.json directly and
    # leaves the version dir without one. Requiring the version copy meant re-export worked
    # after a --no-llm run and failed after every real one.
    cfg = os.path.join(adir, "config.json")
    own_cfg = os.path.isfile(cfg)
    if own_cfg:
        cfg = _with_current_secrets(cfg)
    if not own_cfg:
        # A version that is not THIS project's -- a typo, or another project's id -- is refused
        # here, before the project's own config stands in for its missing one. Checking only
        # when that config was missing too let such an id through to the checkout search, which
        # answered with advice about commits for a version that does not exist.
        known = _known_versions(a.project_id)
        if known and not any(vid == a.version_id for vid, _, _, _ in known):
            return _no_such_version(a.project_id, name, known), None
        # WorkspaceNotFound when the project itself is unknown — a traceback there would
        # bury the message below, which says what to do about it.
        try:
            from incremental.stores import Workspace, WorkspaceNotFound
            _proj = os.path.join(Workspace(a.project_id).root, "config.json")
            if os.path.isfile(_proj):
                cfg = _proj
        except WorkspaceNotFound:
            print(f"there is no workspace for project {a.project_id!r}.\n"
                  f"  Onboard it first:\n"
                  f"    python analyzer.py onboard --project-id {a.project_id} --source <url-or-path> --config <your.json>", file=sys.stderr)
            return 2, None
    if not os.path.isfile(cfg):
        # Name the versions that DO exist. The commonest cause by far is a typo or an
        # off-by-one in the version id, and a path the caller has never seen does not say
        # 'that version is not there' — it reads like a broken install.
        known = _known_versions(a.project_id)
        if not any(vid == a.version_id for vid, _, _, _ in known):
            return _no_such_version(a.project_id, name, known), None
        print(f"version {name!r} has no config at {cfg}.\n"
              f"  It is written at the start of a generate, so this version was reserved but "
              f"never generated. Run:\n"
              f"    python analyzer.py generate --project-id {a.project_id} --version-id {name}", file=sys.stderr)
        return 2, None
    checkout = _checkout_for(a.project_id, a.version_id, getattr(a, "commit", None) or "")
    if checkout is None:
        return 2, None

    # REQ-AP-04. `--from-phase 4` is "export only" and SKIPS Phase 3, the step that rebuilds the
    # view rows the document is built from. A correction saved a second ago has updated the model
    # and the override table; exporting now ships the previous wording with nothing to notice.
    # Phases 2 and 3 re-derive on their way through, so only phase 4 needs asking.
    #
    # `run.py` asks the same question again, and IT is the real guarantee — it is what both this
    # command and the API's re-export service spawn. Asking here as well is not redundant: it
    # fails before the checkout and the subprocess, so the CLI says so immediately.
    #
    # Which documents: a version generated as swe4/all must not come back as swe3 just because the
    # re-export did not say. The manifest records what it was; --doc-type overrides. Older
    # manifests have no docType, so swe3 stays the fallback. Resolved here, before the question,
    # because the answer depends on it.
    doc_type = a.doc_type or (store.read_manifest(a.version_id) or {}).get("docType") or "swe3"
    forced = bool(getattr(a, "force", False))
    if a.from_phase >= 4 and not forced:
        if getattr(a, "_views_when_stale", False) \
                and _refuse_stale_export(a.version_id, doc_type, quiet=True):
            # `--from-phase auto`: the web app judged "export only" when the job was made; a
            # correction saved while it waited made that stale. The views are made again
            # instead of the re-export refused.
            print("a correction is newer than the views: making them again first (phase 3).")
            a.from_phase = 3
        else:
            rc = _refuse_stale_export(a.version_id, doc_type)
            if rc:
                return rc, None

    argv = ["--config", cfg, "--version-id", a.version_id, "--project-id", a.project_id,
            "--model-root", os.path.join(adir, "model"),
            "--output-root", os.path.join(adir, "output"),
            "--from-phase", str(a.from_phase)]
    # `--force` was already honoured above; it has to travel, or run.py's backstop would refuse
    # the very export the user just insisted on.
    if forced:
        argv.append("--force-export")
    # --use-model means 'skip phases 1 AND 2 and reuse the stored model'. For a
    # re-derive we WANT phase 2 to run, so it must not be passed — with it, phase 2
    # would be skipped and --from-phase 2 would quietly do nothing but re-render.
    if a.from_phase >= 3:
        argv.append("--use-model")
    # A re-derive of a `--no-llm` version stays without the LLM, as its generate did
    # (`generate_full` passes the same flag): its own config.json has the LLM turned off.
    elif own_cfg and _llm_off(cfg):
        argv.append("--no-llm-summarize")
    if getattr(a, "to_phase", None):
        argv += ["--to-phase", str(a.to_phase)]      # resume of a `--model-only` run
    # `scope` is the caller's: the version's documents (reexport), the components to add
    # (export) or the ones a cut-short run did not finish (resume) -- None for the scope the
    # version was generated with. The model covers whole layers, so any component of them
    # renders without touching the model.
    if scope is None:
        scope = (store.read_manifest(a.version_id) or {}).get("scope") or {"type": "project"}
    from incremental.generate import scope_to_args, per_component_docx_args
    argv += scope_to_args(scope) + per_component_docx_args(scope)
    # The same documents the guard was asked about above -- see there.
    argv += ["--doc-type", doc_type]
    for u in getattr(a, "unit", None) or []:
        argv += ["--selected-unit", u]
    argv.append(checkout)

    os.environ["ANALYZER_VERSION_ID"] = a.version_id      # the phases' progress marks (as generate)
    _retry_connects_for_run()
    from core.version_run import VersionBusy, writing
    try:
        with writing(a.version_id, command=command, argv=getattr(a, "_argv", None),
                     log_path=os.environ.get("ANALYZER_RUN_LOG"),
                     code_dir=os.environ.get("ANALYZER_RUN_CODE")) as run:
            if before is not None:
                rc = before(cfg, own_cfg, checkout, doc_type)
                if rc:
                    return run.ok(rc), None
            rc = _script(os.path.join(_ROOT, "engine", "run.py"), argv)
            # 3: some components failed and run.py went on with the others -- store and record
            # what they made, and report the failure.
            if rc not in (0, 3):
                return run.ok(rc), None
            # Capture the re-rendered views back into the database. Without this a re-export
            # updated `output/` on THIS machine and left `version_output_files` holding the
            # previous render — so the document served from the database, or from any other
            # node, silently stayed stale. The API's re-export path has always done this
            # (`_capture_reexport_output`); the CLI's did not.
            try:
                docs = store.capture_output(a.version_id, os.path.join(adir, "output"))
                print(f"stored: {len(docs or [])} document(s) + the re-rendered views")
            except Exception as exc:
                print(f"WARNING: the documents were rebuilt on disk but could not be stored "
                      f"({exc}). The database still holds the previous render.",
                      file=sys.stderr)
                return run.ok(1), None
            _register_for_review(a.project_id, a.version_id)
            if rc == 0 and after is not None:
                after(docs)
            if rc:
                print("some components failed (above); the others were stored. `resume` makes "
                      "the failed ones again once the cause is fixed.", file=sys.stderr)
            return run.ok(rc), docs
    except VersionBusy as exc:
        print(str(exc), file=sys.stderr)
        return 2, None


#: A run's own LLM switches (`--no-llm`), which this machine's local config never overrides.
_RUN_SWITCHES = ("descriptions", "behaviourNames")


def _with_current_secrets(cfg_path: str) -> str:
    """The version's own config with this machine's CURRENT local settings over it (its
    `config.local.json`, `db` and `auth` aside: the LLM gateway, key, headers, rate limit), as
    `config.runtime.json` beside it; its path. A version keeps the config its run started with,
    so that a resume days later runs as it began -- but the credentials are the machine's, and a
    key rotated meanwhile failed every LLM call of the resumed run. The run's own switches stay.
    On any error the version's file as it is."""
    try:
        import json
        from core.config import _deep_merge, _strip_json_comments, _strip_trailing_commas
        root = os.environ.get("ANALYZER_DATA_ROOT") or _ROOT      # the installation, not a frozen copy
        local_path = os.path.join(root, "engine", "config", "config.local.json")
        if not os.path.isfile(local_path):
            local_path = os.path.join(_ROOT, "engine", "config", "config.local.json")
        if not os.path.isfile(local_path):
            return cfg_path

        def load(p):
            with open(p, encoding="utf-8") as fh:
                return json.loads(_strip_trailing_commas(_strip_json_comments(fh.read())))
        cfg, local = load(cfg_path), load(local_path)
        local.pop("db", None)
        local.pop("auth", None)
        kept = {k: (cfg.get("llm") or {})[k] for k in _RUN_SWITCHES if k in (cfg.get("llm") or {})}
        _deep_merge(cfg, local)
        if kept:
            cfg.setdefault("llm", {}).update(kept)
        out = os.path.join(os.path.dirname(cfg_path), "config.runtime.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        return out
    except Exception as exc:                        # noqa: BLE001 -- see docstring
        print(f"note: this machine's settings could not be laid over the version's config "
              f"({type(exc).__name__}: {exc}); using it as it is", file=sys.stderr)
        return cfg_path


def _llm_off(cfg_path: str) -> bool:
    """True when this config turns the LLM's descriptions and names off (`--no-llm`)."""
    try:
        import json
        with open(cfg_path, encoding="utf-8") as fh:
            llm = (json.load(fh) or {}).get("llm") or {}
        return llm.get("descriptions") is False and llm.get("behaviourNames") is False
    except Exception:
        return False


def _component_view(project_id: str, version_id: str):
    """(version, every component of it with its state) -- `api/services/version_components.py`.
    (None, []) when there is no database, or no such version of this project."""
    try:
        from core.db import is_database_configured
        if not is_database_configured():
            return None, []
        from api.db.postgres.database import SqlDatabase
        from api.services.version_components import components_view
        from core.version_run import alive
        db = SqlDatabase()
        version = db.versions.get(version_id)
        if version is None or version.project_id != project_id:
            return None, []
        return version, components_view(db, version, alive=alive(version_id))
    except Exception as exc:                        # noqa: BLE001
        print(f"note: could not read the version's components ({type(exc).__name__}: {exc})",
              file=sys.stderr)
        return None, []


def _parse_stored(version_id: str) -> bool:
    """Whether Phase 1 finished: its parse is stored (`parse_snapshots`, written right after it)."""
    try:
        from core.db import get_engine
        import sqlalchemy as sa
        from api.db.postgres import schema as s
        with get_engine().connect() as cx:
            return bool(cx.execute(sa.select(sa.func.count()).select_from(s.parse_snapshots)
                                   .where(s.parse_snapshots.c.version_id == version_id)).scalar())
    except Exception:                               # noqa: BLE001 - then the parse is re-run
        return False


def _pipeline_status(version_id: str):
    from core.db import get_engine
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    with get_engine().connect() as cx:
        return cx.execute(sa.select(s.versions.c.pipeline_status)
                          .where(s.versions.c.id == version_id)).scalar()


def _names(text) -> list:
    return [n.strip() for n in (text or "").split(",") if n.strip()]


def _resolve_or_report(view, text):
    from api.services.version_components import resolve
    found, problems = resolve(view, _names(text))
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    return found, problems


def cmd_reexport(a) -> int:
    """Rebuild documents the version ALREADY has, from its stored model, without parsing.

    Which documents: `--components A,B` (each must have been generated -- `export` makes the
    ones that were not), `--scope` (as before), or by default every component the version has
    documents for, whichever runs made them -- as the web app's re-export does.

    `--from-phase` chooses how far back to go:

      2  re-derive — rebuild units, components and summaries from the stored parse skeleton,
         then views and export. For a change to the deriver.
      3  views + export (the default). For a change to a view.
      4  export only. For a change to the DOCX template.

    Phase 1 is never re-run: the parse is the expensive part and it is already rows. To
    re-parse, run `generate`.
    """
    a._name = a.version_id
    a.version_id = _version_id_for(a.project_id, a.version_id)       # this project's row, as generate
    if a.from_phase == "auto":                  # 4, or 3 when a correction is newer (above)
        a.from_phase, a._views_when_stale = 4, True
    components = getattr(a, "components", None)
    if a.scope and components:
        print("give --components or --scope, not both.", file=sys.stderr)
        return 2
    # Not this project's version (a typo, another project's id): say so before anything else.
    known = _known_versions(a.project_id)
    if known and not any(vid == a.version_id for vid, _, _, _ in known):
        return _no_such_version(a.project_id, a._name, known)
    from incremental.staged import default_reexport, reexport_targets
    from incremental import extend
    pending = extend.load_pending(a.version_id)
    if pending:
        # The add's parse replaced the model and its Phase 2 has not run: a re-export now would
        # render the parse skeleton (no interface ids, no descriptions).
        print(f"an add of layer(s) {', '.join(pending.get('new_layers') or [])} to version "
              f"{a._name} was cut short, so its model is not finished. Finish it first:\n"
              f"    python analyzer.py resume --project-id {a.project_id} --version-id {a._name}",
              file=sys.stderr)
        return 2
    version, view = _component_view(a.project_id, a.version_id)
    if a.scope:
        scope = _parse_scope(a.scope)
    else:
        if version is not None and a.from_phase >= 3 and not any(c["in_model"] for c in view):
            print(f"version {a._name} has no model to re-export from: its Phase 2 did not "
                  f"finish. Complete it first:\n    python analyzer.py resume --project-id "
                  f"{a.project_id} --version-id {a._name}", file=sys.stderr)
            return 2
        if components:
            if version is None:
                return _no_such_version(a.project_id, a._name, _known_versions(a.project_id))
            found, problems = _resolve_or_report(view, components)
            if problems:
                return 2
            todo, refused = reexport_targets(view, found)
            if refused:
                print(f"not generated yet, so nothing to make again -- `export` makes them: "
                      f"{', '.join(refused)}", file=sys.stderr)
                if not todo:
                    return 2
            scope = {"type": "component", "names": todo}
        else:
            # Default to the documents the version HAS. It used to be the scope the version was
            # generated with, and since `export` adds components to a version after its run,
            # that missed every one it added. Versions whose documents are not per component
            # (an old group-scoped run) keep the old default.
            todo = default_reexport(view)
            scope = {"type": "component", "names": todo} if todo else None
    # Stale components (a layer added to the version moved their model): their views are older
    # than it, and an export alone would print them again -- and call them generated. Any stale
    # one in what this re-exports, or in the version when the scope is not by component.
    named = set((scope or {}).get("names") or []) if (scope or {}).get("type") == "component" else None
    stale = [c["component"] for c in view if c["state"] == "stale"
             and (named is None or c["component"] in named)]
    if stale and a.from_phase >= 4:
        if getattr(a, "_views_when_stale", False):
            print(f"stale: {', '.join(stale)} -- their views are made again first (phase 3).")
            a.from_phase = 3
        elif not getattr(a, "force", False):
            print(f"{', '.join(stale)} are stale: a layer added to the version changed their "
                  f"model, so their views must be made again -- run with --from-phase 3 (or "
                  f"--force to export the old views).", file=sys.stderr)
            return 2
    rc, _ = _render_version(a, scope=scope, command="reexport")
    return rc


def _layers_adder(a, *, parse_layers, new_layers, added, documented):
    """`before` for `_render_version`: add `new_layers` to the version's model, under its writer
    lock (engine/incremental/extend.py has the why of each step). Phase 1 parses every layer of
    `parse_layers` -- the old ones too, so calls from them into the new layer are found -- and
    Phase 2 describes only what is new: the old text is put back first, and the plan keeps the
    LLM to the new entities. Components of `documented` whose model the new layer changed are
    marked stale; their documents are left as they are. 0, or the failed phase's exit code."""
    def before(cfg, own_cfg, checkout, doc_type):
        from incremental import extend
        from incremental.store import make_store
        from incremental.generate import (scope_to_args, snapshot_parse_model,
                                          _persist_run_metadata)
        from core.db import _read_pipeline_status, _write_pipeline_status, _FINISHED_STATUSES
        from core.version_run import mark_components
        store = make_store(a.project_id)
        adir = store.artifact_dir(a.version_id)
        run_py = os.path.join(_ROOT, "engine", "run.py")
        pending = extend.load_pending(a.version_id)
        if pending:
            # An add cut short: its capture is the version's text from BEFORE that add's parse,
            # which replaced the model's rows -- capturing now would take the skeleton for it.
            saved = pending
            layers_all = sorted(set(parse_layers) | set(saved.get("parse_layers") or []))
            news = sorted(set(new_layers) | set(saved.get("new_layers") or []))
            adds = list(dict.fromkeys(list(saved.get("added") or []) + list(added)))
            docs = list(saved.get("documented") or documented)
            print(f"an add of layer(s) {', '.join(saved.get('new_layers') or [])} to version "
                  f"{a._name} was cut short: carrying it on from the text it saved", flush=True)
        else:
            found, status = _read_pipeline_status(a.version_id)
            layers_all, news, adds, docs = list(parse_layers), list(new_layers), list(added), list(documented)
            saved = extend.capture(a.version_id)
            saved.update(parse_layers=layers_all, new_layers=news, added=adds, documented=docs,
                         status_before=status if found else None, had_status=found,
                         in_model=sorted({c for c in saved.get("fingerprints") or {}}))
            extend.save_pending(a.version_id, saved)
        mark_components(a.version_id, adds, "waiting")       # kept if this is cut short
        print(f"adding layer(s) {', '.join(news)} to version {a._name}: the parse of "
              f"{', '.join(layers_all)}, then the model -- the LLM describes only what "
              f"{', '.join(news)} adds", flush=True)
        manifest = store.read_manifest(a.version_id) or {}

        def _status_back():
            if saved.get("had_status") and saved.get("status_before") in _FINISHED_STATUSES:
                _write_pipeline_status(a.version_id, saved["status_before"])

        common =["--config", cfg, "--version-id", a.version_id, "--project-id", a.project_id,
                  "--model-root", os.path.join(adir, "model"),
                  "--output-root", os.path.join(adir, "output"), "--doc-type", doc_type]
        try:
            from incremental.project_db import get_project
            pname = ((get_project(a.project_id) or {}).get("name") or "").strip()
        except Exception:                           # noqa: BLE001 - the parse names it then
            pname = ""
        if pname:
            common += ["--project-name", pname]     # as generate: else the cover shows the sha
        if own_cfg and _llm_off(cfg):
            common.append("--no-llm-summarize")     # a --no-llm version stays without the LLM
        dd_id = manifest.get("dataDictId")
        if dd_id:
            try:
                from incremental.stores import Workspace
                dd = Workspace(a.project_id).datadict_path(dd_id)
                if os.path.isfile(dd):
                    common += ["--data-dictionary", dd]
            except Exception:                       # noqa: BLE001 - per-layer dictionaries still apply
                pass
        layers = scope_to_args({"type": "layer", "names": list(layers_all)})
        rc = _script(run_py, common + layers + ["--to-phase", "1", checkout])
        if rc:
            if not pending:
                # A parse that fails stores nothing: the version is as it was before this add.
                extend.clear_pending(a.version_id)
                mark_components(a.version_id, adds, "failed", error=f"the parse failed (exit {rc})")
                _status_back()
            print(f"the parse failed (exit {rc}); the version's documents are as they were. "
                  f"Run the same export again once the cause is fixed.", file=sys.stderr)
            return rc
        snapshot_parse_model(os.path.join(adir, "model"), adir, store, a.version_id)
        _persist_run_metadata(store, a.version_id, a.project_id)
        n = extend.restore_text(a.version_id, saved)
        plan = extend.write_plan(a.version_id, a.project_id, saved)
        print(f"model: kept the text of {n['functions']} function(s), {n['globals']} global(s) "
              f"and {len(saved.get('units') or {})} unit(s); describing "
              f"{len(plan['impactFids'])} new function(s) and {len(plan['impactedGlobals'])} "
              f"new global(s)", flush=True)
        try:
            rc = _script(run_py, common + layers + ["--from-phase", "2", "--to-phase", "2",
                                                    checkout])
        finally:
            extend.restore_plan(a.version_id, saved)
        if rc:
            # The parse has replaced the model; the capture stays, so `resume` (or the same
            # export) finishes this add from it. Nothing else may use the version until then.
            print(f"the model (Phase 2) failed (exit {rc}). `python analyzer.py resume "
                  f"--project-id {a.project_id} --version-id {a._name}` finishes the add once the "
                  f"cause is fixed.", file=sys.stderr)
            return rc
        stale = extend.changed_components(a.version_id, saved, docs)
        if stale:
            mark_components(a.version_id, stale, "stale")
            print(f"stale: {', '.join(stale)} -- {', '.join(news)} changed what their "
                  f"documents are made from; `reexport --components {','.join(stale)}` makes "
                  f"them again")
        else:
            print(f"no document of the version changes with {', '.join(news)}")
        # Recorded once the model holds every layer: what the next version is made like.
        manifest["scope"] = extend.widen_scope(manifest.get("scope"), docs, adds,
                                               saved.get("in_model") or [])
        store.write_manifest(a.version_id, manifest)
        _status_back()                                       # the phases left it mid-way
        extend.clear_pending(a.version_id)
        return 0
    return before


def cmd_export(a) -> int:
    """Make the documents of components the version has NOT generated yet -- Phases 3-4 from its
    stored model, into the same version, recorded for review.

    The version's model covers every component of the layers its run parsed, so any of them can
    be made later without parsing or describing anything again: only their flowcharts (LLM
    labels) and documents. A component already generated is left alone (`reexport` makes it
    again). A component of a layer the version did not parse adds that layer to the model first,
    in the same version: the parse of every layer, then the model, with the LLM describing only
    the new layer; components whose documents the new layer changes are marked stale
    (`_layers_adder`, engine/incremental/extend.py).
    """
    a._name = a.version_id
    a.version_id = _version_id_for(a.project_id, a.version_id)
    if bool(a.components) == bool(a.remaining):
        print("give --components A,B or --remaining (every component not generated yet).",
              file=sys.stderr)
        return 2
    version, view = _component_view(a.project_id, a.version_id)
    if version is None:
        return _no_such_version(a.project_id, a._name, _known_versions(a.project_id))
    if not any(c["in_model"] for c in view):
        print(f"version {a._name} has no model yet: its Phase 2 did not finish. Complete it "
              f"first:\n    python analyzer.py resume --project-id {a.project_id} "
              f"--version-id {a._name}", file=sys.stderr)
        return 2
    found = []
    if a.components:
        found, problems = _resolve_or_report(view, a.components)
        if problems:
            print(f"components this version can make: python analyzer.py components "
                  f"--project-id {a.project_id} --version-id {a._name}", file=sys.stderr)
            return 2
    from incremental.staged import export_targets
    todo, skipped = export_targets(view, found, remaining=a.remaining)
    if skipped:
        print(f"already generated, left alone (`reexport` makes them again): {', '.join(skipped)}")
    if not todo:
        print("nothing to export: every component asked for has its documents.")
        return 0
    print(f"export: {len(todo)} component(s) into {a._name}: {', '.join(todo)}", flush=True)
    a.from_phase = 3
    unfinished = _pipeline_status(a.version_id) not in (None, "complete")
    closed = []
    # A component of a layer the version did not parse: that layer joins the model first, in the
    # same version (`_layers_adder`).
    before = None
    by_id = {c["component"]: c for c in view}
    in_model = {c["component"] for c in view if c["in_model"]}
    # Outside the model although its layer is parsed: a configured component with no source.
    # Parsing again would not add it (and costs the whole parse) -- refused, as before.
    sourceless = [c for c in todo if c not in in_model and by_id.get(c, {}).get("layer_parsed")]
    if sourceless:
        print(f"not in this version's model although their layer was parsed (no source file "
              f"found for them): {', '.join(sourceless)}", file=sys.stderr)
        todo = [c for c in todo if c not in sourceless]
        if not todo:
            return 2
    added = [c for c in todo if c not in in_model]
    from incremental import extend
    pending = extend.load_pending(a.version_id)
    if added or pending:
        # A layer joins the model first (or an add cut short is finished first).
        from incremental.staged import has_documents, layers_to_add
        model_layers = sorted({c.split(".", 1)[0] for c in in_model})
        new_layers = layers_to_add(view, added)
        documented = [c["component"] for c in view if c["in_model"] and has_documents(c)]
        before = _layers_adder(a, parse_layers=sorted(set(model_layers) | set(new_layers)),
                               new_layers=new_layers, added=added, documented=documented)

    def _maybe_close(docs):
        # A version whose own run was cut short stays unfinished (never a baseline) until
        # nothing in it is left to make; then this export closes it, as `resume` would.
        if not unfinished:
            return
        _, after_view = _component_view(a.project_id, a.version_id)
        left = [c["component"] for c in after_view if c["in_model"]
                and c["state"] in ("waiting", "stopped", "failed", "generating")]
        if left:
            print(f"note: {', '.join(left)} of this version's own run did not finish -- "
                  f"`python analyzer.py resume --project-id {a.project_id} --version-id "
                  f"{a._name}` makes them and closes the version.")
            return
        from incremental.engine import finish_version
        finish_version(a.project_id, a.version_id, documents=docs)
        closed.append(True)
        print(f"version {a._name}: complete")

    rc, _ = _render_version(a, scope={"type": "component", "names": todo}, command="export",
                            after=_maybe_close, before=before)
    if closed:
        # A web run's version, stopped and finished here: its web job ends too (draft no more).
        _finish_web_job(a.project_id, a.version_id)
    return rc


def cmd_resume(a) -> int:
    """Finish a version whose run was cut short (the process died, the machine restarted), from
    where it stopped:

      Phase 1 did not finish   the recorded `generate` runs again (the parse starts over; LLM
                               work already done comes back from the cache)
      Phase 2 did not finish   Phase 2 from the stored parse, then the documents
      documents unfinished     Phases 3-4 for the components the run did not finish
      only closing missing     the closing steps

    Refused while a writer still holds the version. `--detach` resumes in the background on the
    frozen code the run started with. A version a web run started is finished in the web app too
    (`_finish_web_job`).
    """
    rc = _resume(a)
    if rc in (0, 3):
        _finish_web_job(a.project_id, a.version_id)
    return rc


def _finish_web_job(project_id: str, version_id: str, db=None) -> None:
    """A version a web run started, and that run stopped, finished here by `resume`: finish the web
    run's job as the API does at a run's end (`pipeline_runner._complete`) -- the version leaves
    "draft", its documents and functions are recorded, the job says complete. Without this a web
    version resumed from the command line stayed a draft, its job "Stopped", for ever. A job an API
    is still following (queued, running) is left to that API; a version with no web job is left
    alone. Never fails the resume."""
    try:
        if db is None:
            from core.db import is_database_configured
            if not is_database_configured():
                return
            from api.db.postgres.database import SqlDatabase
            db = SqlDatabase()
        from api.models.domain import RENDER_MODES
        version = db.versions.get(version_id)
        if version is None or version.project_id != project_id:
            return
        job = next((j for j in db.jobs.list_for_version(version_id)
                    if getattr(j, "mode", None) not in RENDER_MODES), None)
        if job is None or job.status != "failed":
            return
        from api.services import pipeline_runner
        # Straight from failed to complete: never "running", which an API's check for jobs
        # nobody follows would take up and follow again.
        job.error_message = None
        db.jobs.update(job)
        pipeline_runner._complete(db, job.id, force=True)
        print(f"web app: job {job.id} complete -- version {version.tag or version_id} is out of draft")
    except Exception as exc:                        # noqa: BLE001 -- see docstring
        print(f"note: the web app's job for this version could not be finished "
              f"({type(exc).__name__}: {exc}); the documents are made and recorded.",
              file=sys.stderr)


def _resume(a) -> int:
    a._name = a.version_id
    a.version_id = _version_id_for(a.project_id, a.version_id)
    version, view = _component_view(a.project_id, a.version_id)
    if version is None:
        return _no_such_version(a.project_id, a._name, _known_versions(a.project_id))
    from core.version_run import alive, describe, holder, run_row, VersionBusy, writing
    from incremental.staged import resume_plan
    run = run_row(a.version_id)
    code = (run or {}).get("code_dir")
    if code and os.path.normcase(os.path.abspath(code)) != os.path.normcase(_ROOT):
        print(f"note: this run started on the frozen code in {code}; resuming with the code in "
              f"{_ROOT}. `resume --detach` resumes on the frozen code.")
    from incremental.store import make_store
    manifest = make_store(a.project_id).read_manifest(a.version_id) or {}
    plan = resume_plan(alive=alive(a.version_id), pipeline_status=_pipeline_status(a.version_id),
                       view=view, run=run, parse_stored=_parse_stored(a.version_id),
                       model_only=bool(manifest.get("modelOnly")))
    act = plan["action"]
    if act == "busy":
        print(f"version {a._name} is still being written by {describe(holder(a.version_id))}: "
              f"nothing was cut short.", file=sys.stderr)
        return 2
    # Before anything else: an add in progress left the status mid-parse, and "regenerate" would
    # re-run the version's first generate -- without the layer it is adding.
    from incremental import extend
    pending = extend.load_pending(a.version_id)
    if plan.get("layers_to_add") or pending:
        # An `export` that adds a layer, cut short: the same export again -- it parses every
        # layer, keeps the model's text and makes the components (`_layers_adder`).
        comps = plan.get("components") or list((pending or {}).get("added") or [])
        import copy
        e = copy.copy(a)
        e.version_id, e.components, e.remaining = a._name, ",".join(comps), False
        for k, v in (("doc_type", None), ("force", False), ("unit", None)):
            if not hasattr(e, k):
                setattr(e, k, v)
        layers = plan.get("layers_to_add") or (pending or {}).get("new_layers") or []
        print(f"an export that adds layer(s) {', '.join(layers)} was cut short: running it again "
              f"for {', '.join(comps)}", flush=True)
        return cmd_export(e)
    if act == "nothing":
        print(f"version {a._name} is complete: nothing was cut short. `export` makes the "
              f"components it has not generated.")
        return 0
    if act == "regenerate":
        if not plan["argv"]:
            print("the parse (Phase 1) did not finish, and the command that started it is not "
                  "recorded. Run the same `generate` again: the LLM work already done comes "
                  "back from the cache.", file=sys.stderr)
            return 2
        argv = list(plan["argv"])
        if "--config" in argv[:-1]:
            # The version's own config, with this machine's current settings (secrets) over it.
            i = argv.index("--config") + 1
            if os.path.basename(os.path.dirname(argv[i])) == a.version_id:
                argv[i] = _with_current_secrets(argv[i])
        print("the parse (Phase 1) did not finish: running the same generate again -- the parse "
              "starts over, the LLM work already done comes back from the cache.\n  "
              + " ".join(argv), flush=True)
        return main(argv)

    from incremental.engine import finish_version

    def _close(docs):
        finish_version(a.project_id, a.version_id, documents=docs)
        print(f"version {a._name}: complete")

    if act == "close":
        # Every component made, the run gone before it stored the output or recorded the
        # documents: do both, then close. The output on disk is the documents' own.
        try:
            with writing(a.version_id, command="resume", argv=getattr(a, "_argv", None),
                         log_path=os.environ.get("ANALYZER_RUN_LOG"),
                         code_dir=os.environ.get("ANALYZER_RUN_CODE")):
                from incremental.store import make_store
                store = make_store(a.project_id)
                docs = store.capture_output(
                    a.version_id, os.path.join(store.artifact_dir(a.version_id), "output"))
                print(f"stored: {len(docs or [])} document(s) + the views")
                _register_for_review(a.project_id, a.version_id)
                _close(docs)
        except VersionBusy as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    comps = plan.get("components") or []
    a.to_phase = plan.get("to_phase")
    if act == "derive":
        a.from_phase = 2
        print("the model (Phase 2) did not finish: Phase 2 from the stored parse"
              + (" -- a --model-only run, so no documents" if a.to_phase == 2 else
                 ", then the documents" + (f" of {', '.join(comps)}" if comps else "")),
              flush=True)
    else:
        a.from_phase = 3
        print(f"the model is complete: the documents of {', '.join(comps)}", flush=True)
    scope = {"type": "component", "names": comps} if comps else None
    rc, _ = _render_version(a, scope=scope, command="resume", after=_close)
    return rc


def cmd_clean_runs(a) -> int:
    """Remove the frozen code copies of background runs that finished (exit code 0) more than
    `--keep-days` ago -- about 10 MB each; every `--detach` run and every web job makes one. A
    run that is still going, stopped, died or had failed components keeps its copy: `resume
    --detach` carries it on with that code. Logs, run.json and exit.json stay. `--dry-run` says
    what would go."""
    from core.frozen_run import clean_runs
    from core.paths import paths
    gone = clean_runs(paths().data_root, keep_days=a.keep_days, dry_run=a.dry_run)
    for code, size in gone:
        print(f"{'would remove' if a.dry_run else 'removed'}  {code}  ({size / 1e6:.1f} MB)")
    total = sum(s for _, s in gone) / 1e6
    print(f"{len(gone)} frozen code cop{'y' if len(gone) == 1 else 'ies'}, {total:.1f} MB"
          f"{' would be freed' if a.dry_run else ' freed'} (finished more than {a.keep_days:g} "
          f"day(s) ago)")
    return 0


def cmd_progress(a) -> int:
    """How far a version's run has got: running or stopped, the phase, the current stage with the
    time left at its pace so far, and each component's state. Reads only."""
    vid = _version_id_for(a.project_id, a.version_id)
    version, view = _component_view(a.project_id, vid)
    if version is None:
        return _no_such_version(a.project_id, a.version_id, _known_versions(a.project_id))
    from core.version_run import alive, run_row
    from incremental.staged import progress_lines
    for line in progress_lines(version=version, pipeline_status=_pipeline_status(vid),
                               run=run_row(vid), alive=alive(vid), view=view,
                               project_id=a.project_id):
        print(line)
    return 0


def cmd_components(a) -> int:
    """Every component of the layers the version parsed, with the state of its documents:
    generated (with their review status), generating, waiting, stopped, failed, or not requested
    -- which `export` makes. Reads only."""
    vid = _version_id_for(a.project_id, a.version_id)
    version, view = _component_view(a.project_id, vid)
    if version is None:
        return _no_such_version(a.project_id, a.version_id, _known_versions(a.project_id))
    from incremental.staged import component_lines
    for line in component_lines(view, project_id=a.project_id, version_id=a.version_id):
        print(line)
    return 0


def _detach(a) -> int:
    """Start this same command in the background on a frozen copy of the code, and return
    (core/frozen_run.py: why, and what is copied)."""
    from core.frozen_run import detach
    from core.paths import paths
    from incremental.stores import default_workspaces_root
    vid = _version_id_for(a.project_id, a.version_id)
    try:
        from core.version_run import describe, holder, run_row
        busy = holder(vid)
    except Exception:                               # noqa: BLE001 - the run checks again
        busy, run_row = None, None
    if busy:
        print(f"version {a.version_id} is being written by {describe(busy)} -- not started.",
              file=sys.stderr)
        return 2
    existing = None
    if a.command == "resume" and run_row is not None:
        existing = (run_row(vid) or {}).get("code_dir")      # resume on the code it started with
    dsn = None
    try:
        from core.db import database_url, is_database_configured
        dsn = database_url() if is_database_configured() else None
    except Exception:                               # noqa: BLE001 - the copy resolves its own
        pass
    info = detach(list(a._argv), code_root=_ROOT, data_root=paths().data_root,
                  workspaces_dir=os.environ.get("ANALYZER_WORKSPACES_DIR") or default_workspaces_root(),
                  version_key=vid, existing_code=existing, database_url=dsn)
    follow = ("Get-Content -Wait -Tail 30 " if os.name == "nt" else "tail -f ") + str(info["log_path"])
    print(f"started in the background: pid {info['pid']}\n"
          f"  code      {info['code_dir']} (frozen: later changes here do not reach this run)\n"
          f"  log       {info['log_path']}\n"
          f"  progress  python analyzer.py progress --project-id {a.project_id} --version-id {a.version_id}\n"
          f"  follow    {follow}")
    return 0


def _known_versions(project_id: str):
    """This project's versions, newest first: (id, name, commit, status)."""
    try:
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            return []
        import sqlalchemy as sa
        from api.db.postgres import schema as sch
        with get_engine().connect() as cx:
            rows = cx.execute(
                sa.select(sch.versions.c.id, sch.versions.c.version, sch.versions.c.commit_sha,
                          sch.versions.c.pipeline_status)
                .where(sch.versions.c.project_id == project_id)
                .order_by(sch.versions.c.created_at.desc())).all()
        return [(r[0], r[1], (r[2] or '')[:10], r[3] or 'incomplete') for r in rows]
    except Exception:
        return []


def _no_such_version(project_id: str, name: str, known) -> int:
    """Say that `name` is not one of this project's versions, name the ones that are, and
    return the usage exit code. The commonest cause by far is a typo or an off-by-one in the
    version id, and a path the caller has never seen does not say 'that version is not there'
    -- it reads like a broken install."""
    print(f"there is no version {name!r} for project {project_id!r}.", file=sys.stderr)
    if known:
        print("\n  versions this project has:", file=sys.stderr)
        for _, v, sha, st in known[:10]:
            print(f"    {v:<16} {sha:<12} {st}", file=sys.stderr)
    else:
        print("\n  it has none yet — run `python analyzer.py generate` first.", file=sys.stderr)
    return 2


def _checkout_for(project_id: str, version_id: str, commit: str = ""):
    """The commit directory a version was produced from - where its C++ source is.

    THREE places claim to know the commit and they disagree, so trust the one that is on
    disk rather than a fixed order of preference:

      --commit          what the caller typed; always wins.
      the manifest      what the run actually built from (`generate` writes "commit" into it).
      versions.commit_sha  the column - filled in only by `--create-version`, so it is NULL
                        for most versions and stale for some. It cannot be the first choice:
                        preferring it sent re-export hunting for a commit that was never
                        generated, while the real checkout sat there unused.

    The first candidate whose directory EXISTS wins. A commit with no checkout is useless
    here whichever source named it -- until nothing in this workspace has it: then
    `incremental.source_checkout` looks elsewhere on the machine and, failing that, clones the
    one commit back.
    """
    from core.db import get_engine, is_database_configured
    if not is_database_configured():
        print("no database is configured.", file=sys.stderr)
        return None
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from incremental.stores import Workspace
    ws = Workspace(project_id)

    cands = []                                    # (sha, where it came from)
    if commit:
        # An explicit --commit is obeyed or refused, never quietly swapped: falling through
        # to another candidate would re-export from a DIFFERENT source than the one asked
        # for, and say nothing about it.
        if not os.path.isdir(ws.commit_dir(commit)):
            print(f"--commit {commit[:16]} has no checkout at {ws.commit_dir(commit)}.",
                  file=sys.stderr)
            _print_available_checkouts(ws, project_id, version_id)
            return None
        cands.append((commit, "--commit"))
    try:
        from incremental.store import make_store
        m = (make_store(project_id).read_manifest(version_id) or {}).get("commit")
        if m:
            cands.append((m, "the version's manifest"))
    except Exception:
        pass
    try:
        with get_engine().connect() as cx:
            row = cx.execute(sa.select(s.versions.c.commit_sha)
                             .where(s.versions.c.id == version_id)).first()
        if row and row[0]:
            cands.append((row[0], "versions.commit_sha"))
    except Exception:
        pass

    seen = set()
    for sha, src in cands:
        if sha in seen:
            continue
        seen.add(sha)
        d = ws.commit_dir(sha)
        if os.path.isdir(d):
            return d

    # Nothing in this workspace. Before telling the user to generate again -- a full LLM run to
    # recover what is at most a git checkout -- look where else it may be (another working copy's
    # `versions.base_path`, a folder named from a short sha) and, failing those, clone that ONE
    # commit from the project's repository. An explicit --commit never reaches here: it was
    # obeyed or refused above, never swapped or fetched. The manifest's commit is preferred over
    # the column, for the reason above.
    from incremental.source_checkout import SourceUnavailable, locate_or_restore
    prefer = next((sha for sha, src in cands if src == "the version's manifest"), None)
    try:
        found = locate_or_restore(project_id, version_id, commit=prefer)
    except SourceUnavailable as exc:
        print(str(exc), file=sys.stderr)
    else:
        if found.how == "restored":
            print(f"restored the source checkout for {version_id!r} ({found.path})")
        else:
            print(f"using the source checkout for {version_id!r} from {found.path} "
                  f"({found.how})")
        return found.path

    # Nothing resolved. Say what was tried and what is actually on disk - the answer is
    # almost always one of the directories listed, passed back as --commit.
    if not cands:
        print(f"no commit is recorded for version {version_id!r} anywhere.", file=sys.stderr)
    else:
        print(f"none of the commits recorded for version {version_id!r} is checked out:",
              file=sys.stderr)
        for sha, src in cands:
            print(f"    {sha[:16]:<18} ({src})", file=sys.stderr)
    _print_available_checkouts(ws, project_id, version_id)
    return None


def _print_available_checkouts(ws, project_id: str, version_id: str) -> None:
    """The checkouts this project actually has, and the command that uses one."""
    try:
        have = sorted(n for n in os.listdir(ws.root)
                      if os.path.isdir(os.path.join(ws.root, n, ".git")))
    except OSError:
        have = []
    if have:
        print("", file=sys.stderr)
        print("  checkouts this project HAS:", file=sys.stderr)
        for n in have[:10]:
            print(f"    {n}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Re-export reads the SOURCE for line numbers and flowcharts. "
              "Pass the one you want:", file=sys.stderr)
        print(f"    python analyzer.py reexport --project-id {project_id} "
              f"--version-id {version_id} --commit <one-of-the-above>", file=sys.stderr)
    else:
        print("", file=sys.stderr)
        print(f"  this project has no checkout on disk at all ({ws.root}).", file=sys.stderr)
        print("  Generate again to restore one.", file=sys.stderr)


def cmd_status(a) -> int:
    argv = ["--counts"] if not a.version else ["--version", a.version]
    if a.out:
        argv += ["--out", a.out]
    return _tool("dump_db", argv)


def cmd_check(a) -> int:
    argv = []
    if a.version:
        argv += ["--version", a.version]
    if a.out:
        argv += ["--out", a.out]
    if a.quiet:
        argv += ["--quiet"]
    return _tool("check_db", argv)


def cmd_report(a) -> int:
    """A version's generation report — reuse accounting, LLM calls, where the time went."""
    from core.db import get_engine, is_database_configured
    if not is_database_configured():
        print("no database is configured.", file=sys.stderr)
        return 2
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    with get_engine().connect() as cx:
        q = sa.select(s.versions.c.id, s.versions.c.report)
        if a.version:
            q = q.where(s.versions.c.id == a.version)
        else:
            q = q.order_by(s.versions.c.created_at.desc()).limit(1)
        row = cx.execute(q).first()
    if not row:
        print("no such version." if a.version else "no versions yet.", file=sys.stderr)
        return 2
    if not row[1]:
        print(f"version {row[0]}: no report stored (a run from before the report was wired, "
              f"or one that did not finish).", file=sys.stderr)
        return 1
    print(row[1])
    return 0


def cmd_doctor(a) -> int:
    return _tool("doctor", ["--quiet"] if a.quiet else [])


def cmd_check_llm(a) -> int:
    argv = []
    if a.raw:
        argv += ["--raw"]
    if a.only:
        argv += ["--only", a.only]
    if a.max_tokens:
        argv += ["--max-tokens", str(a.max_tokens)]
    return _tool("check_llm", argv)


def cmd_check_datadict(a) -> int:
    argv = [a.csv]
    if a.layer:
        argv += ["--layer", a.layer]
    if a.quiet:
        argv += ["--quiet"]
    return _tool("check_data_dictionary_csv", argv)


def cmd_llm_stats(a) -> int:
    return _tool("llm_stats", list(a.files))


# The gates. Ordered cheapest-first, so a break shows up as early as possible.
_GATES = [
    ("tests", None, "the unit + API suites"),
    ("incremental", "verify_incremental.py", "a two-version run reuses and regenerates correctly"),
    ("narrowed-parse", "verify_narrowed_parse.py", "a narrowed parse equals a full one"),
    ("flowchart-reuse", "verify_flowchart_reuse.py", "an incremental run carries flowcharts forward"),
    ("parity", "verify_incremental_parity.py", "an incremental document equals a full one"),
    ("db-sync", "verify_db_sync.py", "the model round-trips through real Postgres"),
    ("db-rebuild", "verify_db_rebuild.py", "a fresh node could rebuild a version from the DB"),
]


def cmd_verify(a) -> int:
    names = [g[0] for g in _GATES]
    if a.list:
        for n, _, why in _GATES:
            print(f"  {n:18} {why}")
        return 0
    wanted = a.gate or names
    unknown = [w for w in wanted if w not in names]
    if unknown:
        print(f"unknown gate(s): {', '.join(unknown)}\n  known: {', '.join(names)}",
              file=sys.stderr)
        return 2
    failed = []
    for name, script, why in _GATES:
        if name not in wanted:
            continue
        print(f"\n=== {name} — {why}")
        if name == "tests":
            import subprocess
            rc = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "tests/api", "-q"],
                                cwd=_ROOT).returncode
        else:
            extra = ["--fast"] if (name == "parity" and a.fast) else []
            rc = _script(os.path.join(_ROOT, "tools", script), extra)
        print(f"--- {name}: {'OK' if rc == 0 else 'FAILED'}")
        if rc != 0:
            failed.append(name)
            if not a.keep_going:
                break
    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"OK — {len(wanted)} gate(s) passed")
    return 0


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

def _parse_scope(text: str) -> dict:
    """`project` | `layer:A,B` | `group:A,B` | `component:A,B`.

    Quote the whole value when it names more than one thing — the comma is an argument
    separator to some shells, which surfaces as "expected one argument" and reads like a bug
    in the tool.
    """
    text = (text or "project").strip()
    if text == "project":
        return {"type": "project"}
    kind, _, names = text.partition(":")
    kind = kind.strip().lower()
    if kind not in ("layer", "group", "component") or not names.strip():
        raise SystemExit(
            f"bad --scope {text!r}. Use one of:\n"
            f"    project\n    layer:Layer1\n    group:Support\n    component:App,Math")
    return {"type": kind, "names": [n.strip() for n in names.split(",") if n.strip()]}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_EPILOG = textwrap.dedent("""
    Typical first run
      python analyzer.py setup
      python analyzer.py onboard --project-id myproj --source D:\\code\\my-cpp --config my-config.json --version-id v1 --commit <sha>
      python analyzer.py generate --project-id myproj --commit <sha> --version-id v1

    Then, after a code change
      python analyzer.py generate --project-id myproj --commit <sha2> --version-id v2 --create-version

    `generate` decides full vs incremental itself: with a usable baseline it re-parses only the
    changed translation units and reuses the rest, and without one it does a full run.
""")


_DETACH_HELP = ("run in the background on a frozen copy of the code: API restarts, a closed "
                "terminal and later code changes do not reach it. Prints the log and how to "
                "follow it (`progress`).")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analyzer", description=__doc__.split("\n\n")[0],
        epilog=_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", metavar="<command>")

    # -- setup ---------------------------------------------------------------
    s = sub.add_parser("setup", help="create or upgrade the database schema",
                       description=cmd_setup.__doc__)
    s.add_argument("--demo", action="store_true", help="also seed demo users and projects")
    s.set_defaults(fn=cmd_setup)

    # -- onboard -------------------------------------------------------------
    s = sub.add_parser("onboard", help="register a project so it can be generated",
                       description=cmd_onboard.__doc__)
    s.add_argument("--project-id", required=True)
    s.add_argument("--name", help="display name (default: the id)")
    s.add_argument("--source", metavar="URL|PATH",
                   help="where the C++ lives — a git URL or a local path to a git repo. "
                        "Omit when the commit is already checked out in the workspace.")
    s.add_argument("--branch", default="main")
    s.add_argument("--config", help="this project's config.json (only `layers` is required; "
                                    "clang/views/llm are merged in from the defaults)")
    s.add_argument("--use-defaults", action="store_true",
                   help="use this repo's SAMPLE tree as the config. Alternative to --config, "
                        "never both.")
    s.add_argument("--owner", metavar="EMAIL",
                   help="give this user API access to the project. The default is every "
                        "superuser, so the operator account is on the team list of what you "
                        "just created; naming someone here adds them instead.")
    s.add_argument("--owner-all", action="store_true",
                   help="give EVERY user API access. For a single-team internal instance.")
    s.add_argument("--owner-role", default="admin", choices=("admin", "developer", "reviewer"))
    s.add_argument("--force-config", action="store_true", help="replace an existing config")
    s.add_argument("--version-id", help="also reserve this version")
    s.add_argument("--commit", help="the full 40-character sha that version is for")
    s.set_defaults(fn=cmd_onboard)

    # -- grant ---------------------------------------------------------------
    s = sub.add_parser("grant", help="give a user API access to a project",
                       description=cmd_grant.__doc__)
    s.add_argument("--project-id", required=True)
    s.add_argument("--email", help="the user to add")
    s.add_argument("--all", action="store_true", help="add EVERY user in the database")
    s.add_argument("--role", default="admin", choices=("admin", "developer", "reviewer"))
    s.set_defaults(fn=cmd_grant)

    # -- user ----------------------------------------------------------------
    s = sub.add_parser("user", help="add a user account, reset its password, list accounts",
                       description=cmd_user.__doc__)
    s.add_argument("action", choices=("add", "password", "list"))
    s.add_argument("--email", help="the account's address")
    s.add_argument("--name", help="add: the person's name (default: from the address)")
    s.add_argument("--password", help="add/password: this password instead of a temporary one")
    s.add_argument("--project-id", help="add: also make the account a member of this project")
    s.add_argument("--role", default="developer", choices=("admin", "developer", "reviewer"),
                   help="add: the role in --project-id (default developer)")
    s.set_defaults(fn=cmd_user)

    # -- generate ------------------------------------------------------------
    s = sub.add_parser("generate", help="produce a version from a commit",
                       description=cmd_generate.__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True, help="the version this run produces")
    s.add_argument("--commit",
                   help="the full 40-character sha. Default: the one recorded for this "
                        "version when it was reserved.")
    s.add_argument("--branch",
                   help="default: the project's branch, as recorded by onboard")
    s.add_argument("--scope",
                   help='project | layer:A,B | group:A,B | component:A,B. Quote it when it names '
                        'more than one thing. Default: what the baseline has (its scope, and every '
                        'component it has documents for); the whole project when there is none.')
    s.add_argument("--source", metavar="URL|PATH",
                   help="clone from here if the commit is not checked out yet")
    s.add_argument("--config", help="use this config instead of the project's")
    s.add_argument("--data-dict", metavar="ID",
                   help="merge workspaces/<pid>/datadict/<ID>.csv into the data dictionary")
    s.add_argument("--create-version", action="store_true",
                   help="reserve the versions row if absent. Opt-in, so a mistyped "
                        "--version-id fails instead of silently starting a new version.")
    s.add_argument("--no-llm", action="store_true",
                   help="no LLM at all — structure only, mechanical prose and labels")
    s.add_argument("--full", action="store_true",
                   help="force a FULL run even when a baseline exists")
    s.add_argument("--base-version", metavar="ID",
                   help="force this baseline instead of the nearest ancestor")
    s.add_argument("--no-narrowed-parse", action="store_true",
                   help="re-parse everything instead of only the changed translation units")
    s.add_argument("--verify-parse", action="store_true",
                   help="run narrowed AND full, diff them, use the full one. Slow; validation.")
    s.add_argument("--unit", action="append", metavar="NAME",
                   help="narrow the per-function FLOWCHART work to this unit. Repeatable. A "
                        "speed aid while iterating — the model and every other view stay "
                        "whole, and the documents are still the ones --scope asks for. Used "
                        "by Phase 3 only: Phases 1-2 parse and derive the whole scope, and the "
                        "name is checked against the units that run just built.")
    s.add_argument("--doc-type", default="all", choices=("swe3", "swe4", "all"),
                   help="which document(s) to emit: all (SWE.3 and SWE.4, default, like a "
                        "web run), swe3 (detailed design) or swe4 (unit test specification)")
    s.add_argument("--force", action="store_true", help="accepted; the commit dir is reused")
    s.add_argument("--no-register", action="store_true",
                   help="do not record the documents for review and approval at the end "
                        "(`analyzer.py register` does it later)")
    s.add_argument("--model-only", action="store_true",
                   help="stop after Phase 2: the model of the scope's layers, no documents. "
                        "`export` makes them later, per component, into this version.")
    s.add_argument("--detach", action="store_true", help=_DETACH_HELP)
    s.set_defaults(fn=cmd_generate)

    # -- register ------------------------------------------------------------
    s = sub.add_parser("register", help="record a version's documents for review and approval",
                       description=cmd_register.__doc__)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.set_defaults(fn=cmd_register)

    # -- reexport ------------------------------------------------------------
    s = sub.add_parser("reexport", help="make a version's documents again, from its stored model",
                       description=cmd_reexport.__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.add_argument("--force", action="store_true",
                   help="export even when a correction is newer than the derived views "
                        "(REQ-AP-04); the document will carry the previous text")
    s.add_argument("--from-phase", type=lambda v: v if v == "auto" else int(v), default=3,
                   choices=(2, 3, 4, "auto"),
                   help="2 = re-derive (units, components, summaries) then views + export; "
                        "3 = views + export (default); 4 = export only; auto = 4, or 3 when a "
                        "correction is newer than the views (the web app's re-export)")
    s.add_argument("--components", metavar="A,B",
                   help="only these components (each must have been generated; `export` makes "
                        "the others). Default: every component the version has documents for.")
    s.add_argument("--scope",
                   help="a scope instead of --components (project | layer:A | group:A | "
                        "component:A), unchecked -- the model covers the layers the version parsed")
    s.add_argument("--unit", action="append",
                   help="narrow the per-function flowchart work to this unit. Repeatable.")
    s.add_argument("--commit",
                   help="the commit this version was built from. Only needed when it was "
                        "never recorded on the version row (re-export finds the source "
                        "checkout by it).")
    s.add_argument("--doc-type", choices=("swe3", "swe4", "all"),
                   help="which document(s) to rebuild. Default: whatever this version "
                        "was generated with (from its manifest).")
    s.add_argument("--detach", action="store_true", help=_DETACH_HELP)
    s.set_defaults(fn=cmd_reexport)

    # -- export --------------------------------------------------------------
    s = sub.add_parser("export", help="make the documents of components a version has not "
                                      "generated yet (Phases 3-4, same version)",
                       description=cmd_export.__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.add_argument("--components", metavar="A,B",
                   help="these components (Layer1.Math, or Math when one layer has it)")
    s.add_argument("--remaining", action="store_true",
                   help="every component of the parsed layers that has no documents yet")
    s.add_argument("--commit", help="as for reexport: only when the version never recorded it")
    s.add_argument("--detach", action="store_true", help=_DETACH_HELP)
    s.set_defaults(fn=cmd_export, doc_type=None, force=False, unit=None, from_phase=3)

    # -- resume --------------------------------------------------------------
    s = sub.add_parser("resume", help="finish a version whose run was cut short, from where it "
                                      "stopped",
                       description=cmd_resume.__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.add_argument("--commit", help="as for reexport: only when the version never recorded it")
    s.add_argument("--detach", action="store_true",
                   help="resume in the background, on the frozen code the run started with")
    s.set_defaults(fn=cmd_resume, doc_type=None, force=False, unit=None, from_phase=3)

    # -- progress / components -----------------------------------------------
    s = sub.add_parser("progress", help="how far a version's run has got, and its components",
                       description=cmd_progress.__doc__)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.set_defaults(fn=cmd_progress)

    s = sub.add_parser("clean-runs", help="remove the code copies of background runs that "
                                          "finished (keeps logs; never a resumable run's)",
                       description=cmd_clean_runs.__doc__)
    s.add_argument("--keep-days", type=float, default=7,
                   help="keep the copies of runs that finished within this many days (default 7)")
    s.add_argument("--dry-run", action="store_true", help="only say what would be removed")
    s.set_defaults(fn=cmd_clean_runs)

    s = sub.add_parser("components", help="a version's components and the state of their "
                                          "documents",
                       description=cmd_components.__doc__)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.set_defaults(fn=cmd_components)

    # -- status / check / report --------------------------------------------
    s = sub.add_parser("status", help="what the database holds")
    s.add_argument("--version", help="dump this version in full instead of the counts")
    s.add_argument("--out", help="write to a file instead of stdout")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("check", help="check the database, reporting only what is wrong",
                       description=("Reports only problems: a healthy database gives a few "
                                    "lines saying so, and each finding says what it means "
                                    "and how to fix it."))
    s.add_argument("--version", help="check this version instead of all of them")
    s.add_argument("--out", help="write the report to a file")
    s.add_argument("--quiet", action="store_true", help="findings only")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("report", help="print a version's generation report",
                       description=cmd_report.__doc__)
    s.add_argument("--version", help="default: the newest version")
    s.set_defaults(fn=cmd_report)

    # -- diagnose ------------------------------------------------------------
    s = sub.add_parser("doctor", help="check prerequisites (clang, node, graphviz, browser)")
    s.add_argument("--quiet", action="store_true", help="only problems")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("check-llm", help="ask the LLM (gateway or Ollama) directly whether it answers")
    s.add_argument("--raw", action="store_true", help="print the untouched reply")
    s.add_argument("--only", help="run just one prompt: tiny, description or large (or 1-3)")
    s.add_argument("--max-tokens", type=int)
    s.set_defaults(fn=cmd_check_llm)

    s = sub.add_parser("check-datadict", help="validate a data-dictionary CSV before a run",
                       description=("A malformed CSV used to be accepted in silence and the "
                                    "ranges simply never appeared in the document."))
    s.add_argument("csv", help="path to the CSV")
    s.add_argument("--layer", help="check it against one layer's types")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_check_datadict)

    s = sub.add_parser("llm-stats", help="compare the LLM cost of two runs",
                       description=("Every run writes logs/llm_stats_<run-id>.json. Pass two to "
                                    "see what changed — config first, then the per-stage "
                                    "numbers."))
    s.add_argument("files", nargs="+", metavar="STATS.json")
    s.set_defaults(fn=cmd_llm_stats)

    # -- verify --------------------------------------------------------------
    s = sub.add_parser("verify", help="run the correctness gates",
                       description=("Each gate exists because something passed the unit tests "
                                    "and was still broken. They build their own fixtures and "
                                    "throwaway databases; none touch your data."))
    s.add_argument("gate", nargs="*", help="which gates (default: all). --list to see them.")
    s.add_argument("--list", action="store_true", help="list the gates and what each proves")
    s.add_argument("--fast", action="store_true", help="the parity gate's quick mode")
    s.add_argument("--keep-going", action="store_true",
                   help="run the rest after a failure instead of stopping")
    s.set_defaults(fn=cmd_verify)

    return p


_PATH_FLAGS = ("--config", "--source")


def _absolute_paths(argv: list) -> list:
    """The values of path flags as absolute paths, when they name something here: the command
    line is recorded for `resume` and replayed by `--detach`, and either may run elsewhere."""
    out = list(argv)
    for i, x in enumerate(out[:-1]):
        if x in _PATH_FLAGS and os.path.exists(out[i + 1]):
            out[i + 1] = os.path.abspath(out[i + 1])
    return out


def main(argv=None) -> int:
    p = build_parser()
    raw = _absolute_paths(list(sys.argv[1:] if argv is None else argv))
    a = p.parse_args(raw)
    if not getattr(a, "command", None):
        p.print_help()
        return 0
    a._argv = raw                       # recorded with the run, so `resume` can repeat it
    if getattr(a, "detach", False):
        return _detach(a)
    return int(a.fn(a) or 0)


def _main_recording_exit() -> int:
    """`main()`; a run started with `--detach` also writes its exit code beside its log, since
    nobody waits for it (core/frozen_run.py `record_exit`). The variable naming the file is taken
    out of the environment first, so the processes the run starts do not write it too."""
    exit_file = os.environ.pop("ANALYZER_EXIT_FILE", None)
    rc = 1
    try:
        rc = main()
        return rc
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        raise
    finally:
        if exit_file:
            from core.frozen_run import record_exit
            record_exit(rc, exit_file)


if __name__ == "__main__":
    raise SystemExit(_main_recording_exit())
