#!/usr/bin/env python3
"""Set up a project so the CLI can generate for it — one command instead of four steps.

Generating from the command line needs four things to exist first, and the engine creates none
of them: the `projects` row, the workspace directory, that project's `config.json`, and a
`versions` row (the API reserves that at job start; `PgStore` never creates one). Missing any
one stops the run, and the first — the directory — stops it with `WorkspaceNotFound` before
anything useful has happened.

    python tools/new_project.py --project-id myproj --repo-url https://git/x.git
    python tools/new_project.py --project-id myproj --version-id v2 --commit <sha>
    python tools/new_project.py --project-id myproj --layers "App=src/app,Lib=src/lib"

Idempotent: run it again to reserve another version, or after editing the defaults to refresh
the config. Nothing existing is overwritten unless you pass --force-config.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]


def _load_defaults() -> dict:
    """engine/config/config.defaults.json, comments and trailing commas tolerated."""
    p = os.path.join(_ROOT, "engine", "config", "config.defaults.json")
    with open(p, encoding="utf-8") as fh:
        raw = fh.read()
    raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    return json.loads(raw)


def _parse_layers(spec: str) -> dict:
    """"App=src/app,Lib=src/lib" -> the layers block the parser expects."""
    out = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, path = part.partition("=")
        name, path = name.strip(), (path.strip() or name.strip())
        out[name] = {"path": path, "groups": {name: {name: "."}}}
    return out


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
    ap.add_argument("--layers", default=None,
                    help='"App=src/app,Lib=src/lib" — a shortcut that edits ONLY the layers of '
                         'the default config. For a quick start; use --config for real work.')
    ap.add_argument("--version-id", default=None, help="also reserve this version")
    ap.add_argument("--commit", default=None, help="the commit that version is for")
    ap.add_argument("--force-config", action="store_true",
                    help="overwrite an existing config.json")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from core.db import database_url, get_engine, require_database, _redact, DatabaseUnavailable
    from incremental.stores import default_workspaces_root

    try:
        require_database()
    except DatabaseUnavailable as exc:
        print(exc)
        print("\nRun `python tools/db_setup.py` first.")
        return 2

    pid = args.project_id
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
    ws_root = default_workspaces_root()
    proj_dir = os.path.join(ws_root, pid)
    os.makedirs(os.path.join(proj_dir, "datadict"), exist_ok=True)
    print(f"workspace: {proj_dir}")

    # 3. the per-project config -----------------------------------------------------------
    if args.config and args.layers:
        print("\n--config and --layers are alternatives: --config brings the whole file, "
              "--layers edits only the layers of the default. Pass one.")
        return 2
    cfg_path = os.path.join(proj_dir, "config.json")
    if os.path.isfile(cfg_path) and not args.force_config:
        print(f"config   : {cfg_path} (kept — --force-config to replace)")
    else:
        if args.config:
            src = os.path.abspath(args.config)
            if not os.path.isfile(src):
                print(f"\n--config not found: {src}")
                return 2
            try:
                with open(src, encoding="utf-8") as fh:
                    cfg = json.load(fh)
            except ValueError as exc:
                print(f"\n--config is not valid JSON ({exc}). Note this reads STRICT json — "
                      f"comments and trailing commas are only tolerated in "
                      f"config.defaults.json.")
                return 2
            if not (cfg.get("layers") or {}):
                print("           ! that config has no `layers` — the parser will find no "
                      "source. Add them before generating.")
        else:
            cfg = _load_defaults()
            if args.layers:
                cfg["layers"] = _parse_layers(args.layers)
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        _src_note = f" (from {os.path.basename(args.config)})" if args.config else ""
        print(f"config   : {cfg_path} WRITTEN{_src_note}"
              + (f"  layers={list(cfg.get('layers') or {})}"
                 if (args.layers or args.config) else ""))
        if not (args.layers or args.config):
            print("           ^ no --layers given, so it kept the defaults. Edit `layers` in "
                  "that file to point at your source directories.")

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
