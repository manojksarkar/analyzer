"""
Real compare engine for M3 — reads per-version output snapshots captured by
pipeline_runner under workspaces/<project_id>/versions/<version_id>/output/
and diffs them to produce document + section-level change information.

Falls back to a blank result when snapshots are absent (in-memory-only runs or
versions produced before M3 was deployed).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import compare_render, doc_render
from .settings import get_settings as _get_settings
_REPO_ROOT = _get_settings().repo_root


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _snap(project_id: str, commit_sha: str) -> Optional[Path]:
    """Version snapshot dir = the per-commit dir workspaces/<pid>/<commit[:16]> (the engine
    writes model/ + output/ there; there is no separate versions/<id> tree any more)."""
    d = _REPO_ROOT / "workspaces" / project_id / (commit_sha or "")[:16]
    return d if d.is_dir() else None


def _load_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _groups(snap: Path) -> set[str]:
    output = snap / "output"
    if not output.is_dir():
        return set()
    return {d.name for d in output.iterdir() if d.is_dir()}


def _itf(snap: Path, group: str) -> dict:
    """Load interface_tables.json for a group, or empty dict."""
    return _load_json(snap / "output" / group / "interface_tables.json") or {}


def _itf_fingerprint(data: dict) -> str:
    return json.dumps(data, sort_keys=True)


_ITF_HEADERS = [
    "Interface ID", "Interface Name", "Information",
    "Data Type", "Data Range", "Direction", "Source/Dest", "Type",
]


def _itf_unit_to_markdown(data: dict) -> str:
    """Convert a unit's interface table dict to a GitHub-style markdown table."""
    entries = (data or {}).get("entries") or []
    if not entries:
        return ""

    rows: list[list[str]] = []
    for e in entries:
        itype = str(e.get("type") or "-")
        if "variableType" in e:
            data_type = str(e.get("variableType") or "-")
            data_range = str(e.get("range") or "NA")
        else:
            params = e.get("parameters") or []
            data_type = "; ".join(str(p.get("type", "")) for p in params) if params else "VOID"
            data_range = "; ".join(str(p.get("range", "")) for p in params) if params else "NA"
        rows.append([
            str(e.get("interfaceId") or ""),
            str(e.get("interfaceName") or e.get("name") or ""),
            str(e.get("description") or "-"),
            data_type,
            data_range,
            str(e.get("direction") or "-"),
            str(e.get("sourceDest") or "-"),
            itype,
        ])

    if not rows:
        return ""

    def _cell(s: str) -> str:
        return s.replace("|", "/").replace("\n", " ").strip()

    header = "| " + " | ".join(_ITF_HEADERS) + " |"
    sep = "| " + " | ".join(["---"] * len(_ITF_HEADERS)) + " |"
    data_lines = ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join([header, sep] + data_lines)


def _diff_itf_sections(c_itf: dict, b_itf: dict) -> list[str]:
    """Return unit-key section keys that differ between two interface_tables dicts."""
    skip = {"unitNames"}
    all_keys = (set(c_itf.keys()) | set(b_itf.keys())) - skip
    changed = []
    for k in sorted(all_keys):
        if _itf_fingerprint(c_itf.get(k)) != _itf_fingerprint(b_itf.get(k)):
            changed.append(k)
    return changed


# ---------------------------------------------------------------------------
# Ref resolution
# ---------------------------------------------------------------------------

def _resolve_ref(db: Any, project_id: str, ref: str):
    """Return the first Version matching ref as id, tag, or commit_sha prefix."""
    for v in db.versions.list_for_project(project_id):
        if v.id == ref or v.tag == ref or v.commit_sha == ref or v.commit_sha.startswith(ref):
            return v
    return None


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

def _docs_by_group(db: Any, project_id: str, version_id: str) -> dict[str, Any]:
    """Return {group: Document} for documents in a specific version."""
    docs, _ = db.documents.list_for_project(project_id, version_id=version_id, per_page=200)
    return {d.group: d for d in docs if d.group}


# ---------------------------------------------------------------------------
# DB fallback
# ---------------------------------------------------------------------------

def _db_fallback_compare(db: Any, project_id: str, cur_ver, base_ver,
                          c_info: dict, b_info: dict) -> dict:
    """Return compare result built from DB-stored documents only (no snapshots)."""
    c_docs, _ = db.documents.list_for_project(project_id,
                                               version_id=cur_ver.id if cur_ver else None,
                                               per_page=200)
    b_docs, _ = db.documents.list_for_project(project_id,
                                               version_id=base_ver.id if base_ver else None,
                                               per_page=200)
    c_groups = {d.group for d in c_docs if d.group}
    b_groups = {d.group for d in b_docs if d.group}
    added = c_groups - b_groups
    removed = b_groups - c_groups
    common = c_groups & b_groups
    summary = {"added": len(added), "changed": 0,
               "removed": len(removed), "unchanged": len(common)}
    changed_docs = []
    c_by_group = {d.group: d for d in c_docs if d.group}
    b_by_group = {d.group: d for d in b_docs if d.group}
    for g in sorted(added):
        d = c_by_group[g]
        changed_docs.append({"document_id": d.id, "name": d.name,
                              "process": d.process, "diff_type": "added",
                              "sections_changed": []})
    for g in sorted(removed):
        d = b_by_group[g]
        changed_docs.append({"document_id": d.id, "name": d.name,
                              "process": d.process, "diff_type": "removed",
                              "sections_changed": []})
    return {"current": c_info, "baseline": b_info,
            "summary": summary, "changed_documents": changed_docs}


# ---------------------------------------------------------------------------
# Whole-document change detection (covers descriptions, tables, mermaid)
# ---------------------------------------------------------------------------

def _group_changed(db: Any, project: Any, project_id: str, group: str,
                   c_snap: Path, b_snap: Path, cur_ver: Any, base_ver: Any,
                   c_doc: Any, b_doc: Any) -> bool:
    """A group is changed if its interface tables differ OR — when they match —
    any other rendered content (descriptions, diagrams, mermaid) differs."""
    if _itf_fingerprint(_itf(c_snap, group)) != _itf_fingerprint(_itf(b_snap, group)):
        return True
    # Interface tables identical — fall through to a full-render comparison so
    # description / flowchart / behaviour / diagram changes are still detected.
    if not project or not c_doc or not b_doc:
        return False
    try:
        c_render = compare_render._version_render(db, project, c_doc, cur_ver, c_snap, project_id)
        b_render = compare_render._version_render(db, project, b_doc, base_ver, b_snap, project_id)
    except Exception:
        return False
    if c_render is None or b_render is None:
        return False
    return (compare_render.render_fingerprint(c_render)
            != compare_render.render_fingerprint(b_render))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_document_diff(db: Any, project_id: str, doc_id: str,
                          current_ref: str, baseline_ref: str) -> Optional[dict]:
    """Highlight-annotated rich diff for a single document.

    Builds the full DOCX-mirroring render for each version snapshot and diffs
    them into typed, highlighted blocks (descriptions, tables, mermaid). Falls
    back to the flat interface-table section diff when no rich render is
    available. Returns None only when the document does not exist.
    """
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        return None

    project = db.projects.get(project_id)
    cur_ver = _resolve_ref(db, project_id, current_ref)
    base_ver = _resolve_ref(db, project_id, baseline_ref)
    # Snapshots live under workspaces/<pid>/<commit[:16]> — key by commit_sha, NOT the
    # API Version.id ('ver…'), which would never match the on-disk dir.
    c_snap = _snap(project_id, cur_ver.commit_sha) if cur_ver else None
    b_snap = _snap(project_id, base_ver.commit_sha) if base_ver else None

    rich = compare_render.compute_document_render_diff(
        db, project, doc, cur_ver, base_ver, c_snap, b_snap, project_id,
    )
    if rich is not None:
        rich["mode"] = "rich"
        return rich

    # Fallback — flat interface-table section diff (legacy shape).
    flat = compute_document_sections_diff(db, project_id, doc_id, current_ref, baseline_ref)
    if flat is None:
        return None
    flat["mode"] = "flat"
    return flat


def compute_compare(db: Any, project_id: str, current_ref: str, baseline_ref: str) -> dict:
    """Compute a compare result from version snapshots, falling back to DB docs.

    Returned shape matches GET /compare:
      {current, baseline, summary: {added,changed,removed,unchanged}, changed_documents}
    """
    cur_ver = _resolve_ref(db, project_id, current_ref)
    base_ver = _resolve_ref(db, project_id, baseline_ref)

    c_info = {
        "ref": current_ref,
        "version": cur_ver.tag if cur_ver else None,
        "branch": cur_ver.branch if cur_ver else "main",
    }
    b_info = {
        "ref": baseline_ref,
        "version": base_ver.tag if base_ver else None,
        "branch": base_ver.branch if base_ver else "main",
    }

    if not cur_ver or not base_ver:
        return {"current": c_info, "baseline": b_info,
                "summary": {"added": 0, "changed": 0, "removed": 0, "unchanged": 0},
                "changed_documents": []}

    c_snap = _snap(project_id, cur_ver.commit_sha)
    b_snap = _snap(project_id, base_ver.commit_sha)

    if not c_snap or not b_snap:
        return _db_fallback_compare(db, project_id, cur_ver, base_ver, c_info, b_info)

    c_groups = _groups(c_snap)
    b_groups = _groups(b_snap)
    added = c_groups - b_groups
    removed = b_groups - c_groups
    common = c_groups & b_groups

    c_by_group = _docs_by_group(db, project_id, cur_ver.id)
    b_by_group = _docs_by_group(db, project_id, base_ver.id)
    project = db.projects.get(project_id)

    changed = {g for g in common
               if _group_changed(db, project, project_id, g,
                                  c_snap, b_snap, cur_ver, base_ver,
                                  c_by_group.get(g), b_by_group.get(g))}
    unchanged = common - changed

    summary = {
        "added": len(added), "changed": len(changed),
        "removed": len(removed), "unchanged": len(unchanged),
    }

    changed_docs = []
    for g in sorted(added):
        if g in c_by_group:
            d = c_by_group[g]
            changed_docs.append({"document_id": d.id, "name": d.name,
                                  "process": d.process, "diff_type": "added",
                                  "sections_changed": []})
    for g in sorted(changed):
        d = c_by_group.get(g)
        if d:
            secs = _diff_itf_sections(_itf(c_snap, g), _itf(b_snap, g))
            changed_docs.append({"document_id": d.id, "name": d.name,
                                  "process": d.process, "diff_type": "changed",
                                  "sections_changed": secs})
    for g in sorted(removed):
        if g in b_by_group:
            d = b_by_group[g]
            changed_docs.append({"document_id": d.id, "name": d.name,
                                  "process": d.process, "diff_type": "removed",
                                  "sections_changed": []})

    return {"current": c_info, "baseline": b_info,
            "summary": summary, "changed_documents": changed_docs}


def _table_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
    """Render a header+rows table as a GitHub-style markdown pipe table."""
    def cell(s: str) -> str:
        return str(s).replace("|", "/").replace("\n", " ").strip()
    if not headers:
        return ""
    head = "| " + " | ".join(cell(h) for h in headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join([head, sep] + body)


def _flat_intro_sections(components: list[str], project_name: str) -> list[dict]:
    """Flat (markdown) Introduction sections (Purpose / Scope / Terms) mirroring
    the exported DOCX — so the compare flat fallback shows them too. Intro content
    is version-independent, hence always ``unchanged``."""
    intro = doc_render.intro_section_from_config(components, project_name)
    out: list[dict] = []
    for child in intro.get("children") or []:
        if child.get("type") == "table" and child.get("table"):
            content = _table_to_markdown(child["table"]["headers"], child["table"]["rows"])
        else:
            content = child.get("content") or ""
        out.append({
            "key": child["id"],
            "title": f'{child["number"]} {child["title"]}',
            "diff_type": "unchanged",
            "current_content": content,
            "baseline_content": content,
        })
    return out


def compute_document_sections_diff(
    db: Any, project_id: str, doc_id: str,
    current_ref: str, baseline_ref: str,
) -> Optional[dict]:
    """Section-level diff for a single document.

    Returned shape matches GET /compare/documents/{doc_id}:
      {document_name, sections: [{key, title, diff_type, current_content, baseline_content}]}
    Returns None if the document is not found.
    """
    doc = db.documents.get(doc_id)
    if not doc or doc.project_id != project_id:
        return None

    project = db.projects.get(project_id)
    project_name = project.name if project else (doc.group or "")

    cur_ver = _resolve_ref(db, project_id, current_ref)
    base_ver = _resolve_ref(db, project_id, baseline_ref)

    # Key snapshots by commit_sha (dir is workspaces/<pid>/<commit[:16]>), not Version.id.
    c_snap = _snap(project_id, cur_ver.commit_sha) if cur_ver else None
    b_snap = _snap(project_id, base_ver.commit_sha) if base_ver else None

    if not c_snap or not b_snap or not doc.group:
        # Fall back to DB-stored sections; mark changed if in the seeded diff set
        sections_stored = db.documents.list_sections(doc_id)
        cr = db.compare.get_or_create(project_id, current_ref, baseline_ref)
        diff = db.compare.get_document_diff(cr.id, doc_id)
        changed_keys = set(diff.sections_changed) if diff else set()
        result = _flat_intro_sections([doc.group] if doc.group else [], project_name)
        for s in sections_stored:
            dt = "changed" if s.section_key in changed_keys else "unchanged"
            result.append({
                "key": s.section_key, "title": s.title, "diff_type": dt,
                "current_content": s.content,
                "baseline_content": s.content if dt == "unchanged" else "[previous version content]",
            })
        return {"document_name": doc.name, "sections": result}

    c_itf = _itf(c_snap, doc.group)
    b_itf = _itf(b_snap, doc.group)

    unit_names: dict[str, str] = c_itf.get("unitNames") or b_itf.get("unitNames") or {}
    skip = {"unitNames"}
    all_keys = sorted((set(c_itf.keys()) | set(b_itf.keys())) - skip)

    intro_comps = sorted({uk.split("|", 1)[0] for uk in unit_names}) or ([doc.group] if doc.group else [])
    sections = _flat_intro_sections(intro_comps, project_name)
    for k in all_keys:
        cv = c_itf.get(k, {})
        bv = b_itf.get(k, {})
        diff_type = ("unchanged"
                     if _itf_fingerprint(cv) == _itf_fingerprint(bv)
                     else "changed")
        title = unit_names.get(k, k)
        sections.append({
            "key": k,
            "title": title,
            "diff_type": diff_type,
            "current_content": _itf_unit_to_markdown(cv),
            "baseline_content": _itf_unit_to_markdown(bv),
        })

    return {"document_name": doc.name, "sections": sections}
