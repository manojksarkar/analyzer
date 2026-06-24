"""Rich document render — builds the {cover, toc, sections, meta} payload from a
committed snapshot of real analyzer output under ``api/fixtures/documents/<group>/``.

This is the *real-data-shaped* path: interface tables + diagram PNGs come from the
fixture (a curated copy of `output/<group>/`). When a document's group has no
fixture, the caller falls back to a synthesized payload. See the fixtures README.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Optional

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "documents"


# ── fixture lookup (path-traversal safe) ────────────────────────────────────

def fixture_group_dir(group: Optional[str]) -> Optional[Path]:
    """The fixture dir for ``group`` if it exists and is safely inside FIXTURES."""
    if not group or not FIXTURES.is_dir():
        return None
    d = (FIXTURES / group).resolve()
    if d.is_dir() and (d == FIXTURES or FIXTURES in d.parents):
        return d
    return None


def resolve_asset(group: Optional[str], asset_path: str) -> Optional[Path]:
    """Resolve ``<group>/<asset_path>`` inside the fixture, or None if unsafe/absent."""
    base = fixture_group_dir(group)
    if not base:
        return None
    target = (base / asset_path).resolve()
    if target.is_file() and base in target.parents:
        return target
    return None


# ── helpers ─────────────────────────────────────────────────────────────────

def _sec(sid: str, number: str, title: str, level: int, *, type: str = "richtext",
         content: Any = None, table: Any = None, image_url: Any = None,
         mermaid: Any = None, children: Any = None) -> dict:
    return {
        "id": sid, "number": number, "title": title, "level": level, "type": type,
        "content": content, "table": table, "image_url": image_url, "mermaid": mermaid,
        "children": children or [],
    }


def _pngs(group_dir: Path, subdir: str, pred) -> list[str]:
    d = group_dir / subdir
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix == ".png" and pred(p.name))


def _diagram_sec(project_id: str, doc_id: str, group_dir: Path, subdir: str, fn: str,
                 sid: str, number: str, title: str, level: int, caption: str) -> dict:
    rel = f"{subdir}/{fn}"
    mmd = (group_dir / subdir / fn).with_suffix(".mmd")
    return _sec(
        sid, number, title, level, type="diagram", content=caption,
        image_url=f"projects/{project_id}/documents/{doc_id}/assets/{rel}",
        mermaid=mmd.read_text(encoding="utf-8") if mmd.exists() else None,
    )


def _interfaces_table(itf: dict, unit_keys: list[str]) -> Optional[dict]:
    rows: list[list[str]] = []
    for uk in unit_keys:
        for e in (itf.get(uk, {}) or {}).get("entries", []) or []:
            rows.append([
                e.get("interfaceId", ""),
                e.get("interfaceName") or e.get("name", ""),
                e.get("type", ""),
                e.get("direction", ""),
                e.get("sourceDest", ""),
            ])
    if not rows:
        return None
    return {"headers": ["Interface ID", "Name", "Type", "Dir", "Source/Dest"], "rows": rows}


def _flatten_toc(sections: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in sections:
        out.append({"id": s["id"], "number": s["number"], "title": s["title"], "level": s["level"]})
        out.extend(_flatten_toc(s["children"]))
    return out


# ── main builder ────────────────────────────────────────────────────────────

def build_render(doc, project, version, group_dir: Path, project_id: str) -> dict:
    group = doc.group
    itf: dict = {}
    itf_path = group_dir / "interface_tables.json"
    if itf_path.exists():
        itf = json.loads(itf_path.read_text(encoding="utf-8"))
    unit_names: dict[str, str] = itf.get("unitNames", {}) or {}

    # component → its unit keys
    comps: dict[str, list[str]] = {}
    for uk in unit_names:
        comps.setdefault(uk.split("|", 1)[0], []).append(uk)

    # 1. Introduction
    sections: list[dict] = [
        _sec(
            "intro", "1", "Introduction", 1, type="richtext",
            content=(
                f"This Software Detailed Design describes the '{group}' group of "
                f"{project.name}, covering {len(unit_names)} unit(s) across "
                f"{len(comps)} component(s). Interfaces, static structure and "
                f"control-flow are derived from the Clang AST analysis."
            ),
        )
    ]

    n = 2
    for comp, ukeys in comps.items():
        children: list[dict] = []
        sub = 1

        tbl = _interfaces_table(itf, ukeys)
        if tbl:
            children.append(_sec(f"{comp}-iface", f"{n}.{sub}", "Interfaces", 2, type="table", table=tbl))
            sub += 1

        # static structure diagrams (named <Comp>.png)
        for subdir, label in (
            ("component_container_diagrams", "Component Diagram"),
            ("component_header_dependency_diagrams", "Include Dependencies"),
        ):
            for fn in _pngs(group_dir, subdir, lambda nm, c=comp: nm == f"{c}.png"):
                children.append(_diagram_sec(project_id, doc.id, group_dir, subdir, fn,
                                             f"{comp}-{subdir}", f"{n}.{sub}", label, 2,
                                             f"{label} for {comp}."))
                sub += 1

        # per-unit structure diagrams (named <Comp>_<Unit>.png)
        for uk in ukeys:
            uname = unit_names[uk]
            for fn in _pngs(group_dir, "unit_diagrams", lambda nm, p=f"{comp}_{uname}": nm == f"{p}.png"):
                children.append(_diagram_sec(project_id, doc.id, group_dir, "unit_diagrams", fn,
                                             f"unit-{uname}", f"{n}.{sub}", f"Unit — {uname}", 2,
                                             f"Static structure of unit {uname}."))
                sub += 1

        # control-flow graphs (named <Unit>_<fn>.png), capped
        fcs: list[str] = []
        for uk in ukeys:
            uname = unit_names[uk]
            fcs += _pngs(group_dir, "flowcharts", lambda nm, p=f"{uname}_": nm.startswith(p))
        for fn in fcs[:8]:
            label = fn[:-4].replace("_", " · ")
            children.append(_diagram_sec(project_id, doc.id, group_dir, "flowcharts", fn,
                                         f"cfg-{fn[:-4]}", f"{n}.{sub}", f"CFG — {label}", 2,
                                         "Control-flow graph derived from the Clang AST."))
            sub += 1

        sections.append(_sec(
            f"comp-{comp}", str(n), comp, 1, type="richtext",
            content=f"Detailed design for component {comp}.", children=children,
        ))
        n += 1

    # meta — real-ish counts from the interface tables
    all_entries = [e for uk in unit_names for e in (itf.get(uk, {}) or {}).get("entries", []) or []]
    functions_total = sum(1 for e in all_entries if e.get("type") == "Function")
    globals_total = sum(1 for e in all_entries if e.get("type") in ("Variable", "Global", "GlobalVariable"))

    cover = {
        "project_name": project.name,
        "subtitle": doc.subtitle or "Software Detailed Design Specification",
        "version": version.tag if version else doc.version_id,
        "layer": doc.layer,
        "group": group,
        "standard": project.compliance_standard,
        "process": doc.process,
        "generated_at": doc.updated_at.isoformat(),
    }
    meta = {
        "pipeline_data_available": True,
        "model_data_available": True,
        "source": "pipeline",
        "layers": [doc.layer] if doc.layer else [],
        "components": list(comps.keys()),
        "units_total": len(unit_names),
        "functions_total": functions_total,
        "globals_total": globals_total,
    }
    return {"cover": cover, "toc": _flatten_toc(sections), "sections": sections, "meta": meta}
