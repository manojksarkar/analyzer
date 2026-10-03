"""A finished version's documents, registered — and their review opened.

One record per real generated Word file: `output/<component dir>/software_detailed_design_<id>.docx`
(SWE.3) and `software_unit_test_specification_<id>.docx` (SWE.4), where the dir is the component's
layer-qualified id (`Layer1.Sample-Core`). Registration is **idempotent**: a document already
recorded for the version (same process, same component) is left alone, so it is safe to call after
a web run, after a CLI run, after a re-export, and by hand (`analyzer.py register`).

Every caller ends here so that review and approval work on a version however it was made: the API
job runner registered documents and the CLI never did, so a version generated from the command line
had nothing to review (REVIEW_APPROVE_API_SPEC §4).

Which component a dir is comes from, in order: the project's `architecture_layers` (web projects),
the version's `resolved_config` and its `config.json` beside the output (every run writes one), and
the project's `config.json`. A dir none of them names is skipped -- a stale dir from an earlier run
in a shared commit dir must not become a document. Only when no source names any component at all
are the dirs themselves taken, so a version is never left unregistered because its configuration
was kept somewhere this cannot read.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..models.domain import Document
from . import doc_render

UTC = timezone.utc
PROCESSES = (("SWE.3", "Detailed Design"), ("SWE.4", "Unit Test Specification"))


def _qualified_dir(layer: str, name: str) -> str:
    from core.config import make_qualified_id
    return make_qualified_id(layer, name).replace(" ", "-")


def _from_api_layers(layers: Any) -> dict:
    """The API's shape: [{name, groups: [{name, components: [name | {name}]}]}]."""
    out: dict = {}
    for layer in layers or []:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "")
        for g in layer.get("groups") or []:
            if not isinstance(g, dict):
                continue
            for c in g.get("components") or []:
                cname = c if isinstance(c, str) else (str(c.get("name") or "") if isinstance(c, dict) else "")
                if cname:
                    out[_qualified_dir(lname, cname)] = (cname, lname)
    return out


def _from_engine_layers(layers: Any) -> dict:
    """The engine's shape: {Layer: {groups: {Group: {Component: paths}}}}."""
    out: dict = {}
    if not isinstance(layers, dict):
        return out
    for lname, layer in layers.items():
        groups = layer.get("groups") if isinstance(layer, dict) else None
        if not isinstance(groups, dict):
            continue
        for comps in groups.values():
            if not isinstance(comps, dict):
                continue
            for cname in comps:
                if cname:
                    out[_qualified_dir(str(lname), str(cname))] = (str(cname), str(lname))
    return out


def _read_layers(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return _from_engine_layers((json.load(fh) or {}).get("layers"))
    except (OSError, ValueError, AttributeError):
        return {}


def component_dirs(project: Any, version: Any, out_root: Optional[Path]) -> dict:
    """`{output dir name: (display name, layer)}` for every component this version may have."""
    found: dict = {}
    for source in (
            lambda: _from_api_layers(getattr(project, "architecture_layers", None)),
            lambda: _from_engine_layers((getattr(version, "resolved_config", None) or {}).get("layers")),
            lambda: _read_layers(out_root.parent / "config.json") if out_root is not None else {},
            lambda: _read_layers(doc_render.workspaces_root() / project.id / "config.json")):
        for k, v in source().items():
            found.setdefault(k, v)
    return found


def _fallback(dir_name: str) -> tuple[str, str]:
    """A dir no configuration names: `Layer1.Sample-Core` -> ("Sample-Core", "Layer1")."""
    layer, _, name = dir_name.partition(".")
    return (name, layer) if name else (dir_name, "")


def new_documents(db: Any, project: Any, version: Any, now: Optional[datetime] = None) -> list:
    """Write a `documents` row for each Word file of the version not recorded yet; return them.
    Rows only -- `register_documents` adds the sections, the statuses and the review."""
    from .review_workflow import version_docs

    now = now or datetime.now(UTC)
    out_root = doc_render.commit_output_root(project.id, version.commit_sha, version.id)
    if out_root is None:
        return []
    known = {(d.process, d.group) for d in version_docs(db, version)}
    comps = component_dirs(project, version, out_root)
    new: list = []
    for d in sorted(out_root.iterdir()):
        if not d.is_dir():
            continue
        if comps and d.name not in comps:
            continue                    # a dir no component declares: stale, or not this run's
        disp, lname = comps.get(d.name) or _fallback(d.name)
        for process, subtitle in PROCESSES:
            if (process, d.name) in known or doc_render.find_docx(d.name, out_root, process) is None:
                continue
            doc = Document(
                id="doc" + uuid.uuid4().hex[:8], project_id=project.id, version_id=version.id,
                process=process, name=disp, subtitle=subtitle, layer=lname, group=d.name,
                status="in_review", due_date=None, created_at=now, updated_at=now)
            db.documents.update(doc)
            new.append(doc)
    return new


def register_documents(db: Any, project: Any, version: Any, *, now: Optional[datetime] = None,
                       start: bool = True) -> list:
    """Register the version's documents that are not recorded yet and open their review
    (`review_workflow.start_review`; not when `start` is False). Returns the new documents."""
    from .pipeline_runner import _make_sections
    from .review_workflow import start_review, version_docs

    now = now or datetime.now(UTC)
    new = new_documents(db, project, version, now)
    if not new:
        return []
    out_root = doc_render.commit_output_root(project.id, version.commit_sha, version.id)
    _make_sections(db, new, now, out_root)
    version.docs_count = len(version_docs(db, version))
    if version.status in (None, "", "draft"):
        version.status = "in_review"
    db.versions.update(version)
    if getattr(project, "status", None) not in ("running", "in_review", "complete"):
        project.status = "in_review"
        project.updated_at = now
        db.projects.update(project)
    if start:
        start_review(db, project, version, new)
    return new
