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
    return _tool("new_project", argv)


def cmd_generate(a) -> int:
    """Produce a version.

    FULL or INCREMENTAL is not a question the caller should have to answer. `generate_incremental`
    already resolves a baseline and returns `decision: "full"` when there is no usable one, in
    which case it delegates to `generate_full` itself — so the honest default is to always ask
    for incremental and let the data decide. `--full` forces the long way round.
    """
    from incremental.generate import generate_full, AnalyzerRunFailed
    from incremental.engine import generate_incremental
    from core.run_context import DatabaseRequired

    scope = _parse_scope(a.scope)
    common = dict(data_dict_id=a.data_dict, no_llm=a.no_llm, version_id=a.version_id,
                  config_path=a.config, repo_url=a.source, create_version=a.create_version,
                  selected_units=a.unit)
    try:
        if a.full:
            m = generate_full(a.project_id, a.branch, a.commit, scope, force=a.force, **common)
        else:
            m = generate_incremental(a.project_id, a.branch, a.commit, scope,
                                     base_version_id=a.base_version, force=a.force,
                                     narrowed_parse=not a.no_narrowed_parse,
                                     verify_parse=a.verify_parse, **common)
    except AnalyzerRunFailed as exc:
        # Exit 2 is the analyzer's USAGE code: it already printed what was wrong, in a form
        # built to be acted on. A traceback here would push that message off the screen.
        if getattr(exc, "returncode", 1) == 2:
            print("\nStopped: see the error above.", file=sys.stderr)
            return 2
        raise
    except DatabaseRequired as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2

    print(f"\nversion {m['versionId']} ({m['status']}): commit {m['commit'][:10]}, "
          f"decision={m['decision']}, regenerated={m.get('regenerated')}, "
          f"reused={m.get('reused')}, documents={m.get('documents')}")
    return 0


def cmd_reexport(a) -> int:
    """Rebuild a version's documents from its STORED model — phases 3 and 4 only.

    No parsing and no LLM description work: the model is already rows. This is what you run
    after changing a view or the DOCX template.
    """
    from incremental.store import make_store
    store = make_store(a.project_id)
    adir = store.artifact_dir(a.version_id)
    cfg = os.path.join(adir, "config.json")
    if not os.path.isfile(cfg):
        print(f"no config for version {a.version_id!r} at {cfg}.\n"
              f"  It is written when the version is generated — re-export needs a version that "
              f"has been generated at least once.", file=sys.stderr)
        return 2
    checkout = _checkout_for(a.project_id, a.version_id)
    if checkout is None:
        return 2
    argv = ["--config", cfg, "--version-id", a.version_id, "--project-id", a.project_id,
            "--model-root", os.path.join(adir, "model"),
            "--output-root", os.path.join(adir, "output"),
            "--use-model", "--from-phase", str(a.from_phase)]
    # Default to the SAME scope the version was generated with. Without this a re-export
    # silently produced a different document set: a project-scoped version came out as one
    # Support.docx where generate had produced App.docx and Math.docx, because the scope is
    # what decides per-group versus per-component.
    #
    # `--scope` overrides it, which is the point of running phases 3-4 on their own: the model
    # covers a whole layer, and you re-render one component of it without touching the model.
    from incremental.generate import scope_to_args, per_component_docx_args
    if a.scope:
        scope = _parse_scope(a.scope)
    else:
        scope = (store.read_manifest(a.version_id) or {}).get("scope") or {"type": "project"}
    argv += scope_to_args(scope) + per_component_docx_args(scope)
    for u in a.unit or []:
        argv += ["--selected-unit", u]
    argv.append(checkout)
    return _script(os.path.join(_ROOT, "engine", "run.py"), argv)


def _checkout_for(project_id: str, version_id: str):
    """The commit directory a version was produced from — where its C++ source is."""
    from core.db import get_engine, is_database_configured
    if not is_database_configured():
        print("no database is configured.", file=sys.stderr)
        return None
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from incremental.stores import Workspace
    with get_engine().connect() as cx:
        row = cx.execute(sa.select(s.versions.c.commit_sha)
                         .where(s.versions.c.id == version_id)).first()
    if not row or not row[0]:
        print(f"version {version_id!r} has no commit recorded.", file=sys.stderr)
        return None
    d = Workspace(project_id).commit_dir(row[0])
    if not os.path.isdir(d):
        print(f"the checkout for {version_id!r} is gone ({d}).\n"
              f"  Re-export reads the SOURCE for line numbers and flowcharts, so it needs the "
              f"commit on disk. Generate again to restore it.", file=sys.stderr)
        return None
    return d


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
    s.add_argument("--force-config", action="store_true", help="replace an existing config")
    s.add_argument("--version-id", help="also reserve this version")
    s.add_argument("--commit", help="the full 40-character sha that version is for")
    s.set_defaults(fn=cmd_onboard)

    # -- generate ------------------------------------------------------------
    s = sub.add_parser("generate", help="produce a version from a commit",
                       description=cmd_generate.__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("--project-id", required=True)
    s.add_argument("--commit", required=True, help="the full 40-character sha")
    s.add_argument("--version-id", required=True, help="the version this run produces")
    s.add_argument("--branch", default="main")
    s.add_argument("--scope", default="project",
                   help='project (default) | layer:A,B | group:A,B | component:A,B. '
                        'Quote it when it names more than one thing.')
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
                        "whole, and the documents are still the ones --scope asks for.")
    s.add_argument("--force", action="store_true", help="accepted; the commit dir is reused")
    s.set_defaults(fn=cmd_generate)

    # -- reexport ------------------------------------------------------------
    s = sub.add_parser("reexport", help="rebuild a version's documents from its stored model",
                       description=cmd_reexport.__doc__)
    s.add_argument("--project-id", required=True)
    s.add_argument("--version-id", required=True)
    s.add_argument("--from-phase", type=int, default=3, choices=(3, 4),
                   help="3 = views + export (default), 4 = export only")
    s.add_argument("--scope",
                   help="re-render a NARROWER slice than the version was generated with — the "
                        "model already covers the layer, so this costs only the views. "
                        "Default: the scope the version was generated with.")
    s.add_argument("--unit", action="append",
                   help="narrow the per-function flowchart work to this unit. Repeatable.")
    s.set_defaults(fn=cmd_reexport)

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

    s = sub.add_parser("check-llm", help="ask the LLM gateway directly whether it answers")
    s.add_argument("--raw", action="store_true", help="print the untouched reply")
    s.add_argument("--only", help="run just this prompt by name")
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


def main(argv=None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if not getattr(a, "command", None):
        p.print_help()
        return 0
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
