#!/usr/bin/env python3
"""Set up a project so the CLI can generate for it — one command instead of four steps.

Generating from the command line needs four things to exist first, and the engine creates none
of them: the `projects` row, the workspace directory, that project's `config.json`, and a
`versions` row (the API reserves that at job start; `PgStore` never creates one). Missing any
one stops the run, and the first — the directory — stops it with `WorkspaceNotFound` before
anything useful has happened.

    python tools/new_project.py --project-id myproj --repo-url https://git/x.git
    python tools/new_project.py --project-id myproj --version-id v2 --commit <sha>
    python tools/new_project.py --project-id myproj --config my-config.json

Idempotent: run it again to reserve another version, or after editing the defaults to refresh
the config. Nothing existing is overwritten unless you pass --force-config.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


_CONFIG_DIR = os.path.join(_ROOT, "engine", "config")


def _load_jsonc(path: str) -> dict:
    """Parse a config the way every other reader in this repo does — comments and trailing
    commas tolerated.

    --config used a strict json.load, so it rejected config.defaults.json itself: the one file
    the docs tell you to copy and edit. The engine (core.config.load_config) and the API
    (pipeline_runner._load_base_config) have always accepted JSONC; this is the same stripper.
    """
    from core.config import _strip_json_comments, _strip_trailing_commas
    with open(path, encoding="utf-8") as fh:
        return json.loads(_strip_trailing_commas(_strip_json_comments(fh.read())))


def _load_defaults() -> dict:
    return _load_jsonc(os.path.join(_CONFIG_DIR, "config.defaults.json"))


def _resolve_config(user_path):
    """Build the per-project config the way the API does (pipeline_runner._write_project_config):
    the defaults as the BASE, the project's own file layered on top, then config.local.json's
    machine-specific settings.

    Copying --config verbatim was the bug. A project config carrying only `layers` — the only
    part that is genuinely per-project — produced a workspace config with no `clang`, no `views`
    and no `llm` at all, so the run stopped at load_llm_config or parsed with no include paths.
    The UI never hit it because the API has merged onto the defaults all along.
    """
    from core.config import _deep_merge
    cfg = _load_defaults()
    if user_path:
        user = _load_jsonc(user_path)
        _deep_merge(cfg, user)
        # `layers` is REPLACED, never merged. A deep merge keeps every layer, group and
        # component of the SAMPLE tree the user's file does not mention — which is exactly how
        # a config naming only Math and App still produced a document for Outer.
        if user.get("layers"):
            cfg["layers"] = user["layers"]
    local = os.path.join(_CONFIG_DIR, "config.local.json")
    if os.path.isfile(local):
        try:
            over = _load_jsonc(local)
            # The engine reaches Postgres through its own config, and a workspace file is no
            # place for the password. `layers` are the project's identity, not a machine
            # setting, so a local override must not silently replace what --config just set.
            over.pop("db", None)
            over.pop("layers", None)
            _deep_merge(cfg, over)
        except Exception:
            pass                         # best-effort, as in the API
    return cfg


def _describe_layers(cfg: dict, limit: int = 12) -> None:
    """Print what was actually written. The point of the exercise is that the caller can see
    the groups and components this project will use WITHOUT opening the file."""
    shown = 0
    for lname, layer in (cfg.get("layers") or {}).items():
        for gname, comps in ((layer or {}).get("groups") or {}).items():
            if shown >= limit:
                print("           ...")
                return
            names = ", ".join(comps) if isinstance(comps, dict) else str(comps)
            print(f"           {lname} / {gname}: {names}")
            shown += 1
    if not shown:
        print("           ! no `layers` — the parser will find no source.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--name", default=None, help="display name (default: the id)")
    ap.add_argument("--repo-url", default="", help="clone URL, so the engine can fetch commits")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--config", default=None,
                    help="an existing config.json to use as this project's config. Preferred "
                         "for a real project: layers are only one part of it, and clang args, "
                         "views and llm settings do not fit on a command line.")
    ap.add_argument("--version-id", default=None, help="also reserve this version")
    ap.add_argument("--commit", default=None, help="the commit that version is for")
    ap.add_argument("--force-config", action="store_true",
                    help="overwrite an existing config.json")
    ap.add_argument("--use-defaults", action="store_true",
                    help="onboard with config.defaults.json as the project config. Only for "
                         "this repo's own sample tree — its `layers` are the sample's, not "
                         "your code's. Without it, a project with no config needs --config.")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from incremental.stores import default_workspaces_root

    # --- resolve the config FIRST, before anything is created ----------------------------
    # This was step 3, after the projects row and the workspace directory already existed. A
    # --config path that did not resolve therefore exited 2 having left a half-onboarded
    # project behind — and the obvious next command (`--version-id v2 --commit <sha>`, which
    # takes no --config) then filled that empty workspace with the SAMPLE defaults, quietly.
    # That is how a project ends up carrying layers, groups and components nobody asked for.
    pid = args.project_id
    proj_dir = os.path.join(default_workspaces_root(), pid)
    cfg_path = os.path.join(proj_dir, "config.json")
    have_config = os.path.isfile(cfg_path)
    src = os.path.abspath(args.config) if args.config else None
    if src and not os.path.isfile(src):
        print(f"--config not found: {src}")
        print("\nNothing was created. Check the path and run the same command again.")
        return 2
    if not src and not have_config and not args.use_defaults:
        print(f"{pid} has no config yet, and no --config was given.")
        print("\n  Pass --config <your.json>. Only `layers` has to be in it — clang, views and")
        print("  llm are merged in from config.defaults.json:")
        print('\n      {"layers": {"Layer1": {"path": "Layer1", '
              '"groups": {"MyGroup": {"CompA": "A"}}}}}')
        print("\n  Or pass --use-defaults to onboard against this repo's own SAMPLE tree.")
        print("\nNothing was created.")
        return 2
    try:
        cfg = _resolve_config(src)
    except ValueError as exc:
        print(f"--config is not valid JSON ({exc}).")
        print("\nNothing was created.")
        return 2

    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from core.db import database_url, get_engine, require_database, _redact, DatabaseUnavailable

    try:
        require_database()
    except DatabaseUnavailable as exc:
        print(exc)
        print("\nRun `python tools/db_setup.py` first.")
        return 2

    eng = get_engine()
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"database : {_redact(database_url())}")

    # 1. the projects row -----------------------------------------------------------------
    with eng.begin() as cx:
        existing = cx.execute(sa.select(s.projects.c.id)
                              .where(s.projects.c.id == pid)).first()
        if existing:
            print(f"project  : {pid} (already exists)")
        else:
            cx.execute(sa.insert(s.projects), {
                "id": pid, "name": args.name or pid, "repo_url": args.repo_url,
                "default_branch": args.branch, "status": "active", "created_at": now})
            print(f"project  : {pid} CREATED")

    # 2. the workspace directory ----------------------------------------------------------
    # `Workspace.__init__` raises WorkspaceNotFound if this is missing, before the run does
    # anything — the engine treats the workspace as onboarding-owned and never creates it.
    os.makedirs(os.path.join(proj_dir, "datadict"), exist_ok=True)
    print(f"workspace: {proj_dir}")

    # 3. the per-project config -----------------------------------------------------------
    if have_config and not args.force_config:
        # Keeping an existing config is right for `new_project.py --project-id x --version-id v2`,
        # where no config is involved at all. It is WRONG to do it quietly when a --config WAS
        # passed and differs: the run then uses a config the caller never saw, and the first sign
        # of it is a document full of components they did not ask for.
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                on_disk = json.load(fh)
        except Exception:
            on_disk = None
        if src and on_disk != cfg:
            print(f"\nconfig   : {cfg_path}")
            print(f"           ALREADY EXISTS and differs from --config, so it was NOT replaced.")
            print(f"           Nothing here uses {os.path.basename(src)} — stopping rather than "
                  f"generating from the wrong config.")
            print(f"\n           Re-run with --force-config to replace it, or delete that file.")
            return 2
        print(f"config   : {cfg_path} (kept — --force-config to replace)")
        _describe_layers(cfg if on_disk is None else on_disk)
    else:
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        _src_note = f" (from {os.path.basename(src)} + defaults)" if src else ""
        print(f"config   : {cfg_path} WRITTEN{_src_note}")
        _describe_layers(cfg)
        if not src:
            print("           ! --use-defaults: these `layers` are this repo's SAMPLE tree, "
                  "not your code.")

    # 4. the versions row -----------------------------------------------------------------
    if args.version_id:
        if not args.commit:
            print("\n--version-id needs --commit (the 40-character sha it is for).")
            return 2
        if len(args.commit) < 40:
            print(f"\n--commit must be the FULL 40-character sha, got {len(args.commit)} chars. "
                  f"`git rev-parse HEAD` gives it.")
            return 2
        with eng.begin() as cx:
            if cx.execute(sa.select(s.versions.c.id)
                          .where(s.versions.c.id == args.version_id)).first():
                print(f"version  : {args.version_id} (already reserved)")
            else:
                cx.execute(sa.insert(s.versions), {
                    "id": args.version_id, "project_id": pid, "version": args.version_id,
                    "commit_sha": args.commit, "branch": args.branch,
                    "status": "in_review", "created_at": now})
                print(f"version  : {args.version_id} RESERVED for {args.commit[:10]}")

    print("\nReady. Next:")
    print("  cd engine")
    if args.version_id:
        cmd = (f"python -m incremental.generate --project-id {pid} --branch {args.branch} "
               f"--commit {args.commit} --version-id {args.version_id} --scope project")
        if args.repo_url:
            cmd += f" --repo-url {args.repo_url}"
        print(f"  {cmd}")
    else:
        print(f"  python tools/new_project.py --project-id {pid} --version-id v1 "
              f"--commit <full-sha>      # reserve a version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
