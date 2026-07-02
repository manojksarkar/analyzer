"""Rich compare renderer.

Builds the full DOCX-mirroring document render (descriptions, tables, mermaid
diagrams, flowchart/behaviour tables) for *each* version being compared — from
the per-version snapshots captured under
``workspaces/<project_id>/versions/<version_id>/{model,output}`` — then diffs the
two renders section-by-section into typed, highlight-annotated *blocks*.

Each block carries fine-grained change marks so the UI can highlight exactly
what changed:
  * text     → word-level segments (``add`` / ``del`` / ``none``)
  * table    → per-row + per-cell marks (``add`` / ``del`` / ``change`` / ``none``)
  * diagram  → a ``changed`` flag (mermaid source differs) + the snapshot image URL
  * keyvalue → word-level segments for the value

Every section also reports a ``source``: the artifact the data came from
(interface table, data dictionary, flowchart, …) and which side(s) it is present
on — so the consumer knows the provenance of every highlighted change.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Optional

from . import doc_render
from .settings import get_settings as _get_settings

_REPO_ROOT = _get_settings().repo_root

_MARK_NONE = "none"
_MARK_ADD = "add"
_MARK_DEL = "del"
_MARK_CHANGE = "change"

_WORD_RE = re.compile(r"\s+|\S+")


# ---------------------------------------------------------------------------
# Snapshot asset serving (path-traversal safe)
# ---------------------------------------------------------------------------

def resolve_snapshot_asset(project_id: str, version_id: str, group: str,
                           asset_path: str) -> Optional[Path]:
    """Resolve ``<snapshot>/output/<group>/<asset_path>`` safely, or None.

    ``version_id`` here is the snapshot dir key (commit[:16]); snapshots live under
    ``workspaces/<pid>/<commit[:16]>/output/<group>`` (there is no ``versions/`` tree)."""
    base = (_REPO_ROOT / "workspaces" / project_id / version_id
            / "output" / group).resolve()
    if not base.is_dir():
        return None
    target = (base / asset_path).resolve()
    if target.is_file() and base in target.parents:
        return target
    return None


# ---------------------------------------------------------------------------
# Per-version rich render
# ---------------------------------------------------------------------------

def _version_render(db: Any, project: Any, doc: Any, version: Any,
                    snap: Path, project_id: str) -> Optional[dict]:
    """Build a rich render from a version snapshot, or None when unavailable."""
    if not doc.group:
        return None
    group_dir = (snap / "output" / doc.group)
    if not group_dir.is_dir():
        return None
    model_root = snap / "model"
    # Asset URLs must key by the snapshot dir (commit[:16]), not the API Version.id —
    # resolve_snapshot_asset resolves workspaces/<pid>/<commit[:16]>/output/<group>.
    snap_key = (version.commit_sha or "")[:16]
    asset_base = f"projects/{project_id}/compare/assets/{snap_key}/{doc.group}"
    try:
        return doc_render.build_render(
            doc, project, version, group_dir, project_id,
            model_root=model_root if model_root.is_dir() else None,
            asset_base=asset_base,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Section → blocks (no diff marks yet)
# ---------------------------------------------------------------------------

_KV_FIELDS = [("Risk", "risk"), ("Capacity", "capacity"),
              ("Input Name", "input_name"), ("Output Name", "output_name")]


def _section_blocks(sec: dict) -> list[dict]:
    """Convert one rich section into a flat list of renderable blocks."""
    t = sec.get("type")
    blocks: list[dict] = []

    if t == "table" and sec.get("table"):
        tbl = sec["table"]
        blocks.append({"kind": "table",
                       "headers": list(tbl.get("headers") or []),
                       "rows": [list(r) for r in (tbl.get("rows") or [])]})

    elif t == "diagram":
        blocks.append({"kind": "diagram",
                       "image_url": sec.get("image_url"),
                       "mermaid": sec.get("mermaid"),
                       "caption": sec.get("content")})

    elif t == "flowchart_table" and sec.get("flowchart_table"):
        ft = sec["flowchart_table"]
        if ft.get("description"):
            blocks.append({"kind": "text", "text": str(ft["description"])})
        for fc in ft.get("flowcharts") or []:
            blocks.append({"kind": "diagram",
                           "image_url": fc.get("image_url"),
                           "mermaid": fc.get("mermaid"),
                           "caption": fc.get("label")})
        for label, key in _KV_FIELDS:
            blocks.append({"kind": "keyvalue", "label": label,
                           "text": str(ft.get(key, "") or "")})

    elif t == "behavior_table" and sec.get("behavior_table"):
        bt = sec["behavior_table"]
        for item in bt.get("description_list") or []:
            blocks.append({"kind": "text", "text": "• " + str(item)})
        if bt.get("diagram_url"):
            blocks.append({"kind": "diagram",
                           "image_url": bt.get("diagram_url"),
                           "mermaid": None,
                           "caption": "Behaviour diagram"})
        for label, key in _KV_FIELDS:
            blocks.append({"kind": "keyvalue", "label": label,
                           "text": str(bt.get(key, "") or "")})

    else:  # richtext / container
        if sec.get("content"):
            blocks.append({"kind": "text", "text": str(sec["content"])})

    return blocks


def _block_fingerprint(blocks: list[dict]) -> str:
    """Stable fingerprint of a block list, ignoring volatile asset URLs."""
    parts: list[str] = []
    for b in blocks:
        k = b["kind"]
        if k == "text":
            parts.append("T:" + b["text"])
        elif k == "keyvalue":
            parts.append("K:" + b["label"] + "=" + b["text"])
        elif k == "table":
            parts.append("B:" + repr(b["headers"]) + repr(b["rows"]))
        elif k == "diagram":
            parts.append("D:" + (b.get("mermaid") or "") + "|" + (b.get("caption") or ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Fine-grained diffing
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _word_segments(cur: str, base: str) -> tuple[list[dict], list[dict]]:
    """Word-level diff. Returns (current_segments, baseline_segments)."""
    c_tok, b_tok = _tokenize(cur), _tokenize(base)
    sm = difflib.SequenceMatcher(a=b_tok, b=c_tok, autojunk=False)
    cur_seg: list[dict] = []
    base_seg: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        b_chunk = "".join(b_tok[i1:i2])
        c_chunk = "".join(c_tok[j1:j2])
        if tag == "equal":
            if c_chunk:
                cur_seg.append({"text": c_chunk, "mark": _MARK_NONE})
            if b_chunk:
                base_seg.append({"text": b_chunk, "mark": _MARK_NONE})
        else:  # replace / insert / delete
            if c_chunk:
                cur_seg.append({"text": c_chunk, "mark": _MARK_ADD})
            if b_chunk:
                base_seg.append({"text": b_chunk, "mark": _MARK_DEL})
    return cur_seg, base_seg


def _all_segments(text: str, mark: str) -> list[dict]:
    return [{"text": text, "mark": mark}] if text else []


def _row_key(row: list[str]) -> str:
    return row[0] if row else ""


def _diff_table(cur: dict, base: dict) -> tuple[dict, dict]:
    """Row/cell-level table diff. Returns (current_table, baseline_table) where
    each carries ``row_marks`` and ``cell_marks`` parallel to ``rows``."""
    c_rows = cur.get("rows") or []
    b_rows = base.get("rows") or []
    b_by_key = {_row_key(r): r for r in b_rows}
    c_by_key = {_row_key(r): r for r in c_rows}

    def cells_marks(row: list[str], other: Optional[list[str]],
                    present_mark: str) -> tuple[str, list[str]]:
        if other is None:
            return present_mark, [present_mark] * len(row)
        marks = []
        changed = False
        for i, cell in enumerate(row):
            oc = other[i] if i < len(other) else None
            if oc != cell:
                marks.append(_MARK_CHANGE)
                changed = True
            else:
                marks.append(_MARK_NONE)
        return (_MARK_CHANGE if changed else _MARK_NONE), marks

    cur_row_marks: list[str] = []
    cur_cell_marks: list[list[str]] = []
    for r in c_rows:
        rm, cm = cells_marks(r, b_by_key.get(_row_key(r)), _MARK_ADD)
        cur_row_marks.append(rm)
        cur_cell_marks.append(cm)

    base_row_marks: list[str] = []
    base_cell_marks: list[list[str]] = []
    for r in b_rows:
        rm, cm = cells_marks(r, c_by_key.get(_row_key(r)), _MARK_DEL)
        base_row_marks.append(rm)
        base_cell_marks.append(cm)

    cur_tbl = {"kind": "table", "headers": cur.get("headers") or [],
               "rows": c_rows, "row_marks": cur_row_marks,
               "cell_marks": cur_cell_marks}
    base_tbl = {"kind": "table", "headers": base.get("headers") or [],
                "rows": b_rows, "row_marks": base_row_marks,
                "cell_marks": base_cell_marks}
    return cur_tbl, base_tbl


def _mark_block(block: dict, mark: str) -> dict:
    """Annotate a single block as wholly added/removed (one side only)."""
    k = block["kind"]
    if k == "text":
        return {"kind": "text", "segments": _all_segments(block["text"], mark)}
    if k == "keyvalue":
        return {"kind": "keyvalue", "label": block["label"],
                "segments": _all_segments(block["text"], mark)}
    if k == "diagram":
        return {"kind": "diagram", "image_url": block.get("image_url"),
                "mermaid": block.get("mermaid"), "caption": block.get("caption"),
                "changed": True}
    if k == "table":
        rows = block.get("rows") or []
        return {"kind": "table", "headers": block.get("headers") or [],
                "rows": rows, "row_marks": [mark] * len(rows),
                "cell_marks": [[mark] * len(r) for r in rows]}
    return block


def _diff_block_pair(cur: Optional[dict], base: Optional[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """Diff two same-kind blocks (either may be None when present on one side)."""
    if cur is None:
        return None, _mark_block(base, _MARK_DEL)
    if base is None:
        return _mark_block(cur, _MARK_ADD), None

    k = cur["kind"]
    if k == "text":
        cs, bs = _word_segments(cur["text"], base["text"])
        return ({"kind": "text", "segments": cs},
                {"kind": "text", "segments": bs})
    if k == "keyvalue":
        cs, bs = _word_segments(cur["text"], base["text"])
        return ({"kind": "keyvalue", "label": cur["label"], "segments": cs},
                {"kind": "keyvalue", "label": base["label"], "segments": bs})
    if k == "table":
        return _diff_table(cur, base)
    if k == "diagram":
        changed = (cur.get("mermaid") or "") != (base.get("mermaid") or "")
        return ({"kind": "diagram", "image_url": cur.get("image_url"),
                 "mermaid": cur.get("mermaid"), "caption": cur.get("caption"),
                 "changed": changed},
                {"kind": "diagram", "image_url": base.get("image_url"),
                 "mermaid": base.get("mermaid"), "caption": base.get("caption"),
                 "changed": changed})
    return cur, base


def _diff_blocks(cur_blocks: list[dict],
                 base_blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Align two block lists by (kind, ordinal-within-kind) and diff each pair."""
    def index(blocks: list[dict]) -> dict[tuple[str, int], dict]:
        counts: dict[str, int] = {}
        out: dict[tuple[str, int], dict] = {}
        for b in blocks:
            i = counts.get(b["kind"], 0)
            out[(b["kind"], i)] = b
            counts[b["kind"]] = i + 1
        return out

    cur_idx = index(cur_blocks)
    base_idx = index(base_blocks)

    cur_out: list[dict] = []
    for key in cur_idx:
        c, _b = _diff_block_pair(cur_idx[key], base_idx.get(key))
        if c is not None:
            cur_out.append(c)

    base_out: list[dict] = []
    for key in base_idx:
        _c, b = _diff_block_pair(cur_idx.get(key), base_idx[key])
        if b is not None:
            base_out.append(b)

    return cur_out, base_out


# ---------------------------------------------------------------------------
# Section flattening + ordered merge
# ---------------------------------------------------------------------------

def _flatten(sections: list[dict]) -> list[dict]:
    """Pre-order DFS flatten — keeps document order, drops the nesting."""
    out: list[dict] = []
    for s in sections:
        out.append(s)
        out.extend(_flatten(s.get("children") or []))
    return out


def _merge_ids(cur_ids: list[str], base_ids: list[str]) -> list[str]:
    """Interleave two id sequences preserving order (difflib opcodes)."""
    sm = difflib.SequenceMatcher(a=base_ids, b=cur_ids, autojunk=False)
    merged: list[str] = []
    seen: set[str] = set()

    def push(x: str) -> None:
        if x not in seen:
            seen.add(x)
            merged.append(x)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for x in cur_ids[j1:j2]:
                push(x)
        elif tag == "replace":
            for x in base_ids[i1:i2]:
                push(x)
            for x in cur_ids[j1:j2]:
                push(x)
        elif tag == "delete":
            for x in base_ids[i1:i2]:
                push(x)
        elif tag == "insert":
            for x in cur_ids[j1:j2]:
                push(x)
    return merged


# ---------------------------------------------------------------------------
# Source/provenance attribution
# ---------------------------------------------------------------------------

def _artifact_label(sec: dict) -> str:
    sid = sec.get("id") or ""
    t = sec.get("type")
    if t == "diagram":
        if "container" in sid:
            return "Component structure diagram"
        if "-dep" in sid:
            return "Header dependency diagram"
        if sid.startswith("unit-"):
            return "Unit diagram"
        return "Diagram"
    if t == "flowchart_table":
        return "Function flowchart"
    if t == "behavior_table":
        return "Dynamic behaviour"
    if t == "table":
        if sid.endswith("-iface"):
            return "Unit interface table"
        if sid.endswith("-header"):
            return "Unit header (data dictionary)"
        if sid.endswith("-unit-table"):
            return "Component/unit table"
        if sid == "intro-terms":
            return "Abbreviations"
        return "Table"
    return "Description"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_document_render_diff(
    db: Any, project: Any, doc: Any,
    cur_ver: Any, base_ver: Any,
    cur_snap: Optional[Path], base_snap: Optional[Path],
    project_id: str,
) -> Optional[dict]:
    """Build a highlight-annotated rich diff for a single document, or None when
    no version snapshot render is available (caller should fall back)."""
    cur_render = (_version_render(db, project, doc, cur_ver, cur_snap, project_id)
                  if (cur_ver and cur_snap) else None)
    base_render = (_version_render(db, project, doc, base_ver, base_snap, project_id)
                   if (base_ver and base_snap) else None)

    if cur_render is None and base_render is None:
        return None

    cur_flat = _flatten(cur_render["sections"]) if cur_render else []
    base_flat = _flatten(base_render["sections"]) if base_render else []
    cur_by_id = {s["id"]: s for s in cur_flat}
    base_by_id = {s["id"]: s for s in base_flat}

    order = _merge_ids([s["id"] for s in cur_flat], [s["id"] for s in base_flat])

    sections: list[dict] = []
    counts = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}

    for sid in order:
        c_sec = cur_by_id.get(sid)
        b_sec = base_by_id.get(sid)
        ref_sec = c_sec or b_sec

        c_blocks = _section_blocks(c_sec) if c_sec else []
        b_blocks = _section_blocks(b_sec) if b_sec else []

        if c_sec and not b_sec:
            diff_type = "added"
            cur_out = [_mark_block(b, _MARK_ADD) for b in c_blocks]
            base_out: list[dict] = []
        elif b_sec and not c_sec:
            diff_type = "removed"
            cur_out = []
            base_out = [_mark_block(b, _MARK_DEL) for b in b_blocks]
        else:
            same = _block_fingerprint(c_blocks) == _block_fingerprint(b_blocks)
            diff_type = "unchanged" if same else "changed"
            cur_out, base_out = _diff_blocks(c_blocks, b_blocks)

        counts[diff_type] += 1

        present = ("both" if (c_sec and b_sec)
                   else "current" if c_sec else "baseline")
        sections.append({
            "id": sid,
            "number": ref_sec.get("number") or "",
            "title": ref_sec.get("title") or "",
            "level": ref_sec.get("level") or 1,
            "diff_type": diff_type,
            "source": {"artifact": _artifact_label(ref_sec), "present": present},
            "current_blocks": cur_out,
            "baseline_blocks": base_out,
        })

    def _ref_info(ver: Any, has_render: bool) -> dict:
        return {
            "ref": (ver.id if ver else None),
            "version": (ver.tag if ver else None),
            "branch": (ver.branch if ver else None),
            "short_sha": (ver.commit_sha[:7] if ver and ver.commit_sha else None),
            "has_snapshot": has_render,
        }

    return {
        "document_name": doc.name,
        "current": _ref_info(cur_ver, cur_render is not None),
        "baseline": _ref_info(base_ver, base_render is not None),
        "summary": counts,
        "sections": sections,
    }


def render_fingerprint(render: Optional[dict]) -> str:
    """Whole-document fingerprint (descriptions + tables + mermaid), URL-agnostic —
    used for document-level change detection covering all content types."""
    if not render:
        return ""
    parts: list[str] = []
    for sec in _flatten(render.get("sections") or []):
        parts.append(sec.get("id") or "")
        parts.append(_block_fingerprint(_section_blocks(sec)))
    return "\n".join(parts)
