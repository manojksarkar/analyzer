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

from .settings import get_settings as _get_settings
_REPO_ROOT = _get_settings().repo_root


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _snap(project_id: str, version_id: str) -> Optional[Path]:
    d = _REPO_ROOT / "workspaces" / project_id / "versions" / version_id
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
# Public API
# ---------------------------------------------------------------------------

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

    c_snap = _snap(project_id, cur_ver.id)
    b_snap = _snap(project_id, base_ver.id)

    if not c_snap or not b_snap:
        return _db_fallback_compare(db, project_id, cur_ver, base_ver, c_info, b_info)

    c_groups = _groups(c_snap)
    b_groups = _groups(b_snap)
    added = c_groups - b_groups
    removed = b_groups - c_groups
    common = c_groups & b_groups
    changed = {g for g in common
               if _itf_fingerprint(_itf(c_snap, g)) != _itf_fingerprint(_itf(b_snap, g))}
    unchanged = common - changed

    summary = {
        "added": len(added), "changed": len(changed),
        "removed": len(removed), "unchanged": len(unchanged),
    }

    c_by_group = _docs_by_group(db, project_id, cur_ver.id)
    b_by_group = _docs_by_group(db, project_id, base_ver.id)

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

    cur_ver = _resolve_ref(db, project_id, current_ref)
    base_ver = _resolve_ref(db, project_id, baseline_ref)

    c_snap = _snap(project_id, cur_ver.id) if cur_ver else None
    b_snap = _snap(project_id, base_ver.id) if base_ver else None

    if not c_snap or not b_snap or not doc.group:
        # Fall back to DB-stored sections; mark changed if in the seeded diff set
        sections_stored = db.documents.list_sections(doc_id)
        cr = db.compare.get_or_create(project_id, current_ref, baseline_ref)
        diff = db.compare.get_document_diff(cr.id, doc_id)
        changed_keys = set(diff.sections_changed) if diff else set()
        result = []
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

    sections = []
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
