"""SAD view: Layer Static Diagram.

For each layer in the `layers` config block, generates an SVG showing:
  - Group label boxes  (light orange)
  - Module boxes       (light green)
  - Unit boxes         (light violet)

Both components within a group and units within a component wrap to the next row
when their combined width exceeds _MAX_ROW_W. All boxes are separate (not
nested). The SVG is written to
  output/add/layer_static_diagrams/<LayerName>_static.svg

A summary JSON (_layer_static_data.json) is written alongside for the
ADD DOCX exporter.
"""

import json
import os

from .registry import register
from utils import log, KEY_SEP
from core.config import layers_config

# ── layout constants ──────────────────────────────────────────────────────────
_CHAR_W        = 7
_MIN_UNIT_W    = 80
_UNIT_GAP      = 8
_UNIT_ROW_GAP  = 4   # vertical gap between wrapped unit rows within a component
_COMPONENT_GAP    = 12
_ROW_GAP       = 10  # vertical gap between wrapped component rows within a group
_GROUP_GAP     = 24
_SVG_MARGIN    = 20
_MAX_ROW_W     = 900

_GROUP_BOX_H      = 28
_COMPONENT_BOX_H     = 26
_UNIT_BOX_H       = 24
_GAP_GROUP_COMPONENT = 8
_GAP_COMPONENT_UNIT  = 6

# ── colors ────────────────────────────────────────────────────────────────────
_C_GROUP_FILL   = "#FFF3E0"
_C_GROUP_STROKE = "#FB8C00"
_C_GROUP_TEXT   = "#E65100"
_C_MOD_FILL     = "#E8F5E9"
_C_MOD_STROKE   = "#43A047"
_C_MOD_TEXT     = "#2E7D32"
_C_UNIT_FILL    = "#EDE7F6"
_C_UNIT_STROKE  = "#7C4DFF"
_C_UNIT_TEXT    = "#4A148C"


# ── geometry helpers ──────────────────────────────────────────────────────────

def _uw(name: str) -> int:
    return max(len(name) * _CHAR_W + 24, _MIN_UNIT_W)


def _unit_rows_for(units: list) -> list:
    """Split a component's units into rows, each fitting within _MAX_ROW_W."""
    rows, cur, cur_w = [], [], 0
    for u in units:
        uw = _uw(u)
        gap = _UNIT_GAP if cur else 0
        if cur and cur_w + gap + uw > _MAX_ROW_W:
            rows.append(cur)
            cur, cur_w = [u], uw
        else:
            cur.append(u)
            cur_w += gap + uw
    if cur:
        rows.append(cur)
    return rows or [[]]


def _unit_row_w(row: list) -> int:
    return sum(_uw(u) for u in row) + max(0, len(row) - 1) * _UNIT_GAP


def _comp_w(unit_rows: list) -> int:
    return max((_unit_row_w(r) for r in unit_rows), default=_MIN_UNIT_W)


def _comp_section_h(unit_rows: list) -> int:
    n = len(unit_rows)
    return _COMPONENT_BOX_H + _GAP_COMPONENT_UNIT + n * _UNIT_BOX_H + max(0, n - 1) * _UNIT_ROW_GAP


def _comp_row_w(comps: list) -> int:
    """Width of one group component-row (list of (comp_name, unit_rows))."""
    return sum(_comp_w(ur) for _, ur in comps) + max(0, len(comps) - 1) * _COMPONENT_GAP


def _comp_row_h(comps: list) -> int:
    """Height of one group component-row = tallest component section."""
    return max((_comp_section_h(ur) for _, ur in comps), default=_COMPONENT_BOX_H)


def _split_component_rows(comps: list) -> list:
    """Wrap components into rows fitting _MAX_ROW_W."""
    rows, cur, cur_w = [], [], 0
    for item in comps:
        mw = _comp_w(item[1])
        gap = _COMPONENT_GAP if cur else 0
        if cur and cur_w + gap + mw > _MAX_ROW_W:
            rows.append(cur)
            cur, cur_w = [item], mw
        else:
            cur.append(item)
            cur_w += gap + mw
    if cur:
        rows.append(cur)
    return rows


def _group_section_h(component_rows: list) -> int:
    n = len(component_rows)
    return (_GROUP_BOX_H + _GAP_GROUP_COMPONENT
            + sum(_comp_row_h(r) for r in component_rows)
            + max(0, n - 1) * _ROW_GAP)


# ── SVG primitives ────────────────────────────────────────────────────────────

def _rect(x, y, w, h, fill, stroke, sw=1, rx=3) -> str:
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"'
            f' fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def _text(x, y, s, size, weight, color, anchor="middle") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}"'
            f' fill="{color}" text-anchor="{anchor}">{s}</text>')


# ── SVG builder ───────────────────────────────────────────────────────────────

def _build_svg(groups: list) -> str:
    """
    groups: [(group_name, [(component_name, [unit_name, ...]), ...]), ...]
    Returns SVG string.
    """
    # Pre-process: compute unit_rows per component, then split into component rows
    processed = []
    for g_name, components in groups:
        comps_ur = [(m, _unit_rows_for(units)) for m, units in components]
        component_rows = _split_component_rows(comps_ur)
        processed.append((g_name, component_rows))

    content_w = max(
        (_comp_row_w(row) for _, mr in processed for row in mr),
        default=200,
    )
    svg_w = _SVG_MARGIN * 2 + content_w
    total_h = (_SVG_MARGIN
               + sum(_group_section_h(mr) for _, mr in processed)
               + max(0, len(processed) - 1) * _GROUP_GAP
               + _SVG_MARGIN)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{total_h}"'
        f' style="font-family:Arial,sans-serif;background:#ffffff">'
    ]

    gy = _SVG_MARGIN
    for g_name, component_rows in processed:
        gw = max((_comp_row_w(row) for row in component_rows), default=200)

        # group label
        parts.append(_rect(_SVG_MARGIN, gy, gw, _GROUP_BOX_H,
                            _C_GROUP_FILL, _C_GROUP_STROKE, sw=1.5, rx=4))
        parts.append(_text(_SVG_MARGIN + 10, gy + 18, g_name,
                            size=12, weight="bold", color=_C_GROUP_TEXT, anchor="start"))

        row_y = gy + _GROUP_BOX_H + _GAP_GROUP_COMPONENT
        for mod_row in component_rows:
            mx = _SVG_MARGIN
            for m_name, unit_rows in mod_row:
                mw = _comp_w(unit_rows)

                # component box
                parts.append(_rect(mx, row_y, mw, _COMPONENT_BOX_H,
                                   _C_MOD_FILL, _C_MOD_STROKE, rx=3))
                parts.append(_text(mx + mw // 2, row_y + 17, m_name,
                                   size=10, weight="bold", color=_C_MOD_TEXT))

                # unit rows (wrapped)
                uy = row_y + _COMPONENT_BOX_H + _GAP_COMPONENT_UNIT
                for urow in unit_rows:
                    ux = mx
                    for u_name in urow:
                        uw_ = _uw(u_name)
                        parts.append(_rect(ux, uy, uw_, _UNIT_BOX_H,
                                           _C_UNIT_FILL, _C_UNIT_STROKE, rx=3))
                        parts.append(_text(ux + uw_ // 2, uy + 16, u_name,
                                           size=9, weight="normal", color=_C_UNIT_TEXT))
                        ux += uw_ + _UNIT_GAP
                    uy += _UNIT_BOX_H + _UNIT_ROW_GAP

                mx += mw + _COMPONENT_GAP

            row_y += _comp_row_h(mod_row) + _ROW_GAP

        gy += _group_section_h(component_rows) + _GROUP_GAP

    parts.append("</svg>")
    return "\n".join(parts)


# ── model helpers ─────────────────────────────────────────────────────────────

def _units_for_component(component_name: str, units_data: dict) -> list:
    """Return unit names belonging to component_name (first KEY_SEP segment of unit key)."""
    return [
        uk.split(KEY_SEP, 1)[1] if KEY_SEP in uk else uk
        for uk in units_data
        if uk.split(KEY_SEP, 1)[0] == component_name
    ]


# ── view entry point ──────────────────────────────────────────────────────────

@register("layerStaticDiagram")
def run(model, output_dir, model_dir, config):
    layers = layers_config()
    if not layers:
        log("no layers defined in config", component="layerStaticDiagram")
        return

    units_data = model.get("units", {})
    out_dir = os.path.join(output_dir, "layer_static_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    summary = {}

    for layer_name, layer in layers.items():
        groups_cfg = layer.get("groups") or {}

        # Load component summaries from this layer's knowledge_base.json
        from core.model_io import layer_model_dir
        kb_path = os.path.join(layer_model_dir(layer_name), "knowledge_base.json")
        comp_summaries: dict = {}
        if os.path.isfile(kb_path):
            try:
                import json as _json
                with open(kb_path, "r", encoding="utf-8") as _f:
                    _kb = _json.load(_f)
                comp_summaries = _kb.get("component_summaries", {})
            except Exception:
                pass

        groups = []
        for group_name, components_cfg in groups_cfg.items():
            components = []
            for comp_name, comp_path in components_cfg.items():
                unit_names = _units_for_component(comp_name, units_data)
                if not unit_names:
                    unit_names = [comp_name]
                # Resolve description: keys in component_summaries are layer-prefixed
                # e.g. "Layer2/Platform/Adc", but comp_path is "Platform/Adc"
                desc = ""
                paths = comp_path if isinstance(comp_path, list) else [str(comp_path)]
                for p in paths:
                    key = f"{layer_name}/{p}".replace("\\", "/")
                    desc = comp_summaries.get(key, "")
                    if desc:
                        break
                components.append((comp_name, unit_names, desc))
            if components:
                groups.append((group_name, components))

        if not groups:
            log(f"layer {layer_name} has no groups, skipping", component="layerStaticDiagram")
            continue

        svg = _build_svg([(g, [(c, u) for c, u, _ in comps]) for g, comps in groups])
        svg_path = os.path.join(out_dir, f"{layer_name}_static.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)

        summary[layer_name] = {
            "svgPath": svg_path,
            "groups": {
                g: {c: {"units": u, "description": d} for c, u, d in comps}
                for g, comps in groups
            },
        }
        log(f"{layer_name}: {len(groups)} groups", component="layerStaticDiagram")

    out_json = os.path.join(out_dir, "_layer_static_data.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log(f"done — {len(summary)} layer(s)", component="layerStaticDiagram")
