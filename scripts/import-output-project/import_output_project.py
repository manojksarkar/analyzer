#!/usr/bin/env python3
"""Import an existing analyzer output folder into the web-app DB as a viewable project.

Point it at a per-commit workspace snapshot (which holds ``output/`` + ``model/``, with the
project ``config.json`` one level up) *or* at a bare ``output/`` folder, and it creates a
Project + Version + Commit + Documents (+ section bodies) in the JSON-backed DB
(``api/db/data/*.json``) and copies the artifacts into the ``workspaces/<pid>/<commit[:16]>/``
layout the render route expects. No pipeline re-run — the long-ago output becomes browsable
in the web UI.

    python scripts/import-output-project/import_output_project.py <source> [options]

Then start the API json-backed and open the web app:

    API_DB_BACKEND=json uvicorn api.main:app --reload
    (cd web-app && npm run dev)

Sign in with a seeded user (e.g. admin@aspice.dev / secret) and open the new project.

Document layer/group labels come from the analyzer ``config.json`` (its ``layers`` tree) when
found; otherwise they fall back to a single synthesized layer (``--layer``). The importer
reuses the pipeline's own record builders (``pipeline_runner._make_documents`` /
``_make_sections``) so imported projects are identical to ones produced by a real run.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Put the repo root on sys.path so ``import api...`` works from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.db.json_db import JsonDatabase                       # noqa: E402
from api.models.domain import Commit, Project, ProjectMember, Version  # noqa: E402
from api.services import doc_render, pipeline_runner          # noqa: E402
from api.services.settings import get_settings                # noqa: E402


# ── source resolution ────────────────────────────────────────────────────────

def _has_docx(group_dir: Path) -> bool:
    """A dir is a real generated component iff it holds its detailed-design DOCX."""
    return (group_dir / f"software_detailed_design_{group_dir.name}.docx").is_file()


def _detect_groups(output_root: Path) -> list[str]:
    return sorted(
        d.name for d in output_root.iterdir() if d.is_dir() and _has_docx(d)
    )


def _resolve_sources(source: Path, output_override: Path | None,
                     model_override: Path | None, config_override: Path | None):
    """Map the positional source (+ overrides) to (output_root, model_dir, config_file).

    ``source`` may be a per-commit snapshot dir (has ``output/`` + ``model/``, config one
    level up) or the ``output/`` folder itself.
    """
    source = source.resolve()

    if output_override:
        output_root = output_override.resolve()
    elif (source / "output").is_dir():
        output_root = source / "output"
    else:
        output_root = source

    if model_override:
        model_dir: Path | None = model_override.resolve()
    elif (source / "model").is_dir():
        model_dir = (source / "model").resolve()
    elif (output_root.parent / "model").is_dir():
        model_dir = (output_root.parent / "model").resolve()
    else:
        model_dir = None

    config_file: Path | None = None
    candidates = [
        config_override,
        source / "config.json",
        source.parent / "config.json",          # snapshot -> project-level config
        output_root.parent / "config.json",
        output_root.parent.parent / "config.json",
    ]
    for cand in candidates:
        if cand and cand.is_file():
            config_file = cand.resolve()
            break

    return output_root, model_dir, config_file


# ── architecture (layer/group/component) ─────────────────────────────────────

def _arch_from_config(config_file: Path, groups: set[str]):
    """Build API ``architecture_layers`` from the analyzer config's ``layers`` dict.

    Analyzer schema: ``{"<LAYER>": {"path": ..., "groups": {"<GROUP>": {"<COMPONENT>": files}}}}``.
    Only components whose output-dir name (``name.replace(" ","-")``) exists on disk are kept.
    Returns ``(architecture_layers, matched_dir_names)``.
    """
    cfg = pipeline_runner._load_base_config(config_file)
    layers = cfg.get("layers")
    if not isinstance(layers, dict):
        return [], set()

    arch: list[dict] = []
    matched: set[str] = set()
    for lname, lval in layers.items():
        if not isinstance(lval, dict):
            continue
        out_groups = []
        for gname, gval in (lval.get("groups") or {}).items():
            if not isinstance(gval, dict):
                continue
            comps = []
            for cname, cfiles in gval.items():
                dirname = str(cname).replace(" ", "-")
                if dirname in groups:
                    files = cfiles if isinstance(cfiles, list) else [cfiles]
                    comps.append({"name": cname, "files": files})
                    matched.add(dirname)
            if comps:
                out_groups.append({"name": gname, "components": comps})
        if out_groups:
            arch.append({"name": lname, "path": lval.get("path", ""), "groups": out_groups})
    return arch, matched


def _build_architecture(config_file: Path | None, groups: list[str], fallback_layer: str):
    """Config-driven layers plus a fallback layer for any on-disk group the config misses."""
    arch: list[dict] = []
    matched: set[str] = set()
    if config_file:
        arch, matched = _arch_from_config(config_file, set(groups))

    leftover = [g for g in groups if g not in matched]
    if leftover:
        arch.append({
            "name": fallback_layer,
            "path": "",
            "groups": [{
                "name": fallback_layer,
                "components": [{"name": g, "files": []} for g in leftover],
            }],
        })
    return arch


# ── name / commit derivation ─────────────────────────────────────────────────

def _derive_name(model_dir: Path | None, source: Path) -> str:
    if model_dir:
        meta = model_dir / "metadata.json"
        if meta.is_file():
            try:
                pn = (json.loads(meta.read_text(encoding="utf-8")).get("projectName") or "").strip()
                if pn:
                    return pn
            except (OSError, json.JSONDecodeError):
                pass
    return source.resolve().name


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Import an existing analyzer output folder into the web-app DB as a "
                    "viewable project (no pipeline re-run).")
    ap.add_argument("source", type=Path,
                    help="A snapshot dir (has output/ + model/) or an output/ folder.")
    ap.add_argument("--output", type=Path, help="Override the output root explicitly.")
    ap.add_argument("--model", type=Path, help="Override the model dir explicitly.")
    ap.add_argument("--config", type=Path,
                    help="Override the analyzer config.json (its 'layers' set the arch).")
    ap.add_argument("--name", help="Project name (default: model metadata projectName / folder).")
    ap.add_argument("--tag", default="v1.0.0", help="Version tag (default v1.0.0).")
    ap.add_argument("--branch", default="main", help="Branch label (default main).")
    ap.add_argument("--commit", help="Commit sha (default: synthesized).")
    ap.add_argument("--layer", default="LAYER1",
                    help="Fallback layer name for groups not covered by config (default LAYER1).")
    ap.add_argument("--compliance", default="ISO_26262", help="Compliance standard.")
    ap.add_argument("--repo-url", default="", help="Repo URL label (cosmetic).")
    ap.add_argument("--client", default="", help="Client label (cosmetic).")
    ap.add_argument("--owner-email", default="admin@aspice.dev",
                    help="Seed user who owns the project (default admin@aspice.dev).")
    ap.add_argument("--status", default="approved",
                    choices=["approved", "in_review", "never", "unchanged"],
                    help="Document review status (default: approved). "
                         "'approved' also marks the version/commit approved and the project complete.")
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"error: source not found: {args.source}", file=sys.stderr)
        return 1

    output_root, model_dir, config_file = _resolve_sources(
        args.source, args.output, args.model, args.config)

    if not output_root.is_dir():
        print(f"error: output root is not a directory: {output_root}", file=sys.stderr)
        return 1

    groups = _detect_groups(output_root)
    if not groups:
        print(f"error: no generated documents found under {output_root} "
              f"(expected <group>/software_detailed_design_<group>.docx). Nothing written.",
              file=sys.stderr)
        return 1

    # Identity
    pid = f"p{uuid.uuid4().hex[:8]}"
    version_id = f"ver{uuid.uuid4().hex[:8]}"
    commit_sha = args.commit or (uuid.uuid4().hex + uuid.uuid4().hex[:8])  # 40 hex chars
    commit16 = commit_sha[:16]
    name = args.name or _derive_name(model_dir, args.source)
    arch = _build_architecture(config_file, groups, args.layer)

    print(f"Source output : {output_root}")
    print(f"Model dir     : {model_dir or '(none — render falls back to shared model/)'}")
    print(f"Config        : {config_file or '(none — using fallback layer)'}")
    print(f"Groups        : {', '.join(groups)}")
    print(f"Project       : {name}  (id {pid})")
    print(f"Version/commit: {args.tag} @ {commit16}")

    # Copy artifacts into the commit-addressed workspace the render route reads.
    repo_root = get_settings().repo_root
    dest = repo_root / "workspaces" / pid / commit16
    dest_output = dest / "output"
    if dest_output.exists():
        print(f"error: destination already exists: {dest_output}", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(output_root, dest_output)
    if model_dir:
        shutil.copytree(model_dir, dest / "model")

    # Insert DB records into the JSON-backed store (persists to api/db/data/*.json).
    db = JsonDatabase()
    owner = db.users.get_by_email(args.owner_email)
    if not owner:
        print(f"error: owner user not found: {args.owner_email} "
              f"(seeded users incl. admin@aspice.dev / developer@aspice.dev)", file=sys.stderr)
        shutil.rmtree(dest, ignore_errors=True)
        return 1

    now = datetime.now(timezone.utc)
    # Roll the requested document status up to the version/commit/project so dashboards
    # (approval %, badges) are consistent. Only "approved" flips the rollups.
    approved = args.status == "approved"
    version_status = "approved" if approved else "in_review"
    project_status = "complete" if approved else "in_review"

    project = Project(
        id=pid, org_id="org1", name=name, client=args.client,
        compliance_standard=args.compliance, repo_url=args.repo_url, repo_provider="github",
        default_branch=args.branch, build_config={}, architecture_layers=arch,
        status=project_status, created_by=owner.id, created_at=now, updated_at=now,
    )
    db.projects.create(project)

    db.commits.upsert(Commit(
        sha=commit_sha, project_id=pid, branch=args.branch,
        message="Imported from pipeline output",
        author_name=owner.name, author_email=owner.email, committed_at=now,
        has_version=True, version_id=version_id, doc_status=version_status,
    ))

    version = Version(
        id=version_id, project_id=pid, tag=args.tag, commit_sha=commit_sha, branch=args.branch,
        description="Imported from existing output", status=version_status, docs_count=0,
        created_by=owner.id, created_at=now,
    )
    db.versions.create(version)

    db.members.add_member(ProjectMember(
        id=f"m{uuid.uuid4().hex[:8]}", project_id=pid, user_id=owner.id, role="admin",
        status="active", invited_by=owner.id, invited_at=now, joined_at=now,
    ))

    # Reuse the pipeline's own builders so records match a real run exactly. Every detected
    # group is present in `arch` as a component, so this maps 1:1 to the copied output dirs.
    docs = pipeline_runner._make_documents(db, project, version, now)
    out_root = doc_render.commit_output_root(pid, commit_sha)
    if docs:
        pipeline_runner._make_sections(db, docs, now, out_root)

    # _make_documents hardcodes status="in_review"; override to the requested status
    # (default "approved") — mirrors the approve endpoint, which only sets doc.status.
    for d in docs:
        d.status = args.status
        db.documents.update(d)

    version.docs_count = len(docs)
    db.versions.update(version)

    print(f"\nCreated project {pid} with {len(docs)} document(s): "
          f"{', '.join(d.name for d in docs)}")
    print("Copied artifacts to:", dest)
    print("\nNext:")
    print("  API_DB_BACKEND=json uvicorn api.main:app --reload")
    print("  (cd web-app && npm run dev)  then sign in and open the project.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
