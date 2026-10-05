"""A document's rich render payload — what `GET …/documents/{id}/render` answers, and what an
approval fingerprints (review_workflow.fingerprint).

One function so the page and the approval read the same content: a fingerprint taken from a
different build of the document would call an unchanged document changed, or the other way round.
"""
from __future__ import annotations

from typing import Any, Optional

from . import doc_render, swe4_render
from .model_reader import ModelReader
from .output_reader import OutputReader


def build_document_render(db: Any, project: Any, doc: Any) -> Optional[dict]:
    """The rich render of `doc`, or None when this machine has no output for it (the route then
    falls back to the stored section bodies)."""
    version = db.versions.get(doc.version_id) if doc.version_id else None
    project_id = project.id
    # Render THIS version's artifacts from its commit dir (workspaces/<pid>/<commit[:16]>/
    # output), not the shared latest run.
    out_root = doc_render.commit_output_root(project_id, version.commit_sha, version.id) if version else None
    group_dir = doc_render.output_group_dir(doc.group, out_root)
    if doc.process == "SWE.4":
        # The Unit Test Specification, from the component's test_specs.json. With no output on
        # this machine it still comes back whole in shape - the chapters, no specs.
        reader = ModelReader(db, version.id if version else None, doc_render._REPO_ROOT / "model")
        out_reader = OutputReader(db, version.id if version else None,
                                  out_root.parent if out_root is not None else None)
        return swe4_render.build_swe4_render(
            doc, project, version, group_dir, model_reader=reader, output_reader=out_reader)
    if group_dir is None:
        return None
    # Imported projects (created by tools/import-output-project, no repo_url) render
    # their own copied model snapshot (workspaces/<pid>/<commit[:16]>/model). Real
    # repo-backed projects are left exactly as before: model read from the shared repo
    # model/ (model_root=None). Scoped on repo_url so real flows are unchanged.
    model_root = None
    if not (project.repo_url or "").strip():
        commit_model = out_root.parent / "model"
        if commit_model.is_dir():
            model_root = commit_model
    # PG-7a: serve the model for THIS version from Postgres when it's there, falling back to
    # the disk dir resolved above (so behaviour is unchanged without a SQL backend).
    reader = ModelReader(db, version.id if version else None,
                         model_root or (doc_render._REPO_ROOT / "model"))
    # C0: the VIEW outputs (interface tables / flowcharts / behaviour rows) also come
    # from Postgres when present. They have been stored since PG-5a, but the rendered
    # document still read them off local disk — so the main product surface depended on
    # the machine that produced it. snap_dir is the version's own output tree, used as
    # the fallback.
    out_reader = OutputReader(db, version.id if version else None, out_root.parent)
    return doc_render.build_render(
        doc, project, version, group_dir, project_id, model_root=model_root,
        model_reader=reader, output_reader=out_reader)
