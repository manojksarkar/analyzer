"""SAD view: Component Design Diagram.

For each component in each layer, generates an SVG showing:
  - Left column:  same-layer components that call INTO this component
  - Centre:       this component (outer box) with unit boxes stacked inside
  - Right column: same-layer components this component calls

Output:
  output/sad/layer_static_diagrams/<LayerName>_<CompName>_design.svg
  output/sad/layer_static_diagrams/_component_design_data.json
"""

import json
import os

from .registry import register
from utils import log, KEY_SEP
from core.config import layers_config
from core.model_io import layer_model_dir

# ── layout constants ──────────────────────────────────────────────────────────

_CHAR_W       = 7
_SVG_MARGIN   = 20
_ARROW_W      = 60     # gap between peer column and centre box (= ⇨ textLength)

# Peer (caller / callee) boxes — all same width per column
_PEER_BOX_H   = 30
_PEER_BOX_GAP = 10
_PEER_MIN_W   = 80

# Centre (this component) outer box
_CENTRE_PAD   = 8      # left/right internal padding
_NAME_AREA_H  = 28     # height reserved for the component name at the top
_UNIT_TOP_GAP = 6      # gap between name area and first unit
_UNIT_H       = 26     # height of each unit box
_UNIT_MIN_W   = 60     # minimum unit inner width
_UNIT_TEXT_W  = 16     # min char padding inside unit box
_UNIT_GAP     = 4      # vertical gap between stacked unit boxes
_BOT_PAD      = 10     # bottom padding inside centre box


# ── geometry helpers ──────────────────────────────────────────────────────────

def _peer_w(name: str) -> int:
    return max(len(name) * _CHAR_W + 24, _PEER_MIN_W)


def _unit_inner_w(name: str) -> int:
    return max(len(name) * _CHAR_W + _UNIT_TEXT_W, _UNIT_MIN_W)


def _comp_name_min_w(name: str) -> int:
    return len(name) * _CHAR_W + 20


# ── SVG primitives ────────────────────────────────────────────────────────────

def _rect(x, y, w, h, rx=3) -> str:
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"'
            f' fill="#ffffff" stroke="#333333" stroke-width="1"/>')


def _text(x, y, s, size, bold=False, anchor="middle") -> str:
    weight = "bold" if bold else "normal"
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}"'
            f' fill="#333333" text-anchor="{anchor}"'
            f' dominant-baseline="middle">{s}</text>')


def _arrow(x, y, length) -> str:
    return (f'<text x="{x}" y="{y}" textLength="{length}"'
            f' lengthAdjust="spacingAndGlyphs" font-size="16" fill="#333333"'
            f' text-anchor="start" dominant-baseline="middle">⇨</text>')


# ── SVG builder for one component ─────────────────────────────────────────────

def _build_component_svg(comp_name: str, units: list,
                          callers: list, callees: list) -> str:
    # ── centre sizing ─────────────────────────────────────────────────────────
    n = len(units)
    centre_inner_w = max(
        max((_unit_inner_w(u) for u in units), default=_UNIT_MIN_W),
        _comp_name_min_w(comp_name),
    )
    centre_w = centre_inner_w + 2 * _CENTRE_PAD
    centre_h = (_NAME_AREA_H + _UNIT_TOP_GAP
                + n * _UNIT_H + max(0, n - 1) * _UNIT_GAP
                + _BOT_PAD)

    # ── peer column sizing ────────────────────────────────────────────────────
    peer_w_left  = max((_peer_w(c) for c in callers),  default=0)
    peer_w_right = max((_peer_w(c) for c in callees), default=0)
    left_h  = (len(callers)  * _PEER_BOX_H
               + max(0, len(callers)  - 1) * _PEER_BOX_GAP)
    right_h = (len(callees) * _PEER_BOX_H
               + max(0, len(callees) - 1) * _PEER_BOX_GAP)

    # ── overall SVG ───────────────────────────────────────────────────────────
    content_h   = max(left_h, centre_h, right_h, 1)
    left_col_w  = (peer_w_left  + _ARROW_W) if callers  else 0
    right_col_w = (peer_w_right + _ARROW_W) if callees else 0
    svg_w = _SVG_MARGIN + left_col_w + centre_w + right_col_w + _SVG_MARGIN
    svg_h = _SVG_MARGIN * 2 + content_h

    # ── X anchors ─────────────────────────────────────────────────────────────
    left_boxes_x  = _SVG_MARGIN
    centre_x      = _SVG_MARGIN + left_col_w
    right_boxes_x = centre_x + centre_w + _ARROW_W

    # ── Y anchors (each panel vertically centred) ─────────────────────────────
    left_y0   = _SVG_MARGIN + (content_h - left_h)   // 2
    centre_y0 = _SVG_MARGIN + (content_h - centre_h) // 2
    right_y0  = _SVG_MARGIN + (content_h - right_h)  // 2

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}"'
        f' style="font-family:Arial,sans-serif;background:#ffffff">',
    ]

    # ── left callers ──────────────────────────────────────────────────────────
    for i, name in enumerate(callers):
        by  = left_y0 + i * (_PEER_BOX_H + _PEER_BOX_GAP)
        mid = by + _PEER_BOX_H // 2
        parts.append(_rect(left_boxes_x, by, peer_w_left, _PEER_BOX_H))
        parts.append(_text(left_boxes_x + peer_w_left // 2, mid, name, 9))
        parts.append(_arrow(left_boxes_x + peer_w_left, mid, _ARROW_W))

    # ── centre component ──────────────────────────────────────────────────────
    parts.append(_rect(centre_x, centre_y0, centre_w, centre_h))
    # component name inside at top
    parts.append(_text(centre_x + centre_w // 2,
                       centre_y0 + _NAME_AREA_H // 2,
                       comp_name, 10, bold=True))
    # unit boxes stacked
    uy = centre_y0 + _NAME_AREA_H + _UNIT_TOP_GAP
    ux = centre_x + _CENTRE_PAD
    for unit_name in units:
        parts.append(_rect(ux, uy, centre_inner_w, _UNIT_H))
        parts.append(_text(ux + centre_inner_w // 2, uy + _UNIT_H // 2,
                           unit_name, 9))
        uy += _UNIT_H + _UNIT_GAP

    # ── right callees ─────────────────────────────────────────────────────────
    for i, name in enumerate(callees):
        by  = right_y0 + i * (_PEER_BOX_H + _PEER_BOX_GAP)
        mid = by + _PEER_BOX_H // 2
        parts.append(_arrow(centre_x + centre_w, mid, _ARROW_W))
        parts.append(_rect(right_boxes_x, by, peer_w_right, _PEER_BOX_H))
        parts.append(_text(right_boxes_x + peer_w_right // 2, mid, name, 9))

    parts.append("</svg>")
    return "\n".join(parts)


# ── call graph builder ────────────────────────────────────────────────────────

def _build_call_graph(layer_comp_names: set, functions: dict):
    """Return (callers_of, callees_of) dicts mapping comp → set of comp names."""
    callers_of = {c: set() for c in layer_comp_names}
    callees_of = {c: set() for c in layer_comp_names}

    for fid, fdata in functions.items():
        segs = fid.split(KEY_SEP)
        if len(segs) < 2:
            continue
        src = segs[0]
        if src not in layer_comp_names:
            continue
        for callee_fid in fdata.get("callsIds", []):
            csegs = callee_fid.split(KEY_SEP)
            if len(csegs) < 2:
                continue
            dst = csegs[0]
            if dst not in layer_comp_names or dst == src:
                continue
            callees_of[src].add(dst)
            callers_of[dst].add(src)

    return callers_of, callees_of


# ── model helpers ─────────────────────────────────────────────────────────────

def _units_for_component(comp_name: str, units_data: dict) -> list:
    return [
        uk.split(KEY_SEP, 1)[1] if KEY_SEP in uk else uk
        for uk in units_data
        if uk.split(KEY_SEP, 1)[0] == comp_name
    ]


# ── view entry point ──────────────────────────────────────────────────────────

@register("componentDesignDiagram")
def run(model, output_dir, model_dir, config):
    layers = layers_config()
    if not layers:
        log("no layers defined in config", component="componentDesignDiagram")
        return

    units_data = model.get("units", {})
    out_dir = os.path.join(output_dir, "layer_static_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    summary = {}

    for layer_name, layer in layers.items():
        groups_cfg = layer.get("groups") or {}

        layer_comp_names = set()
        for comps in groups_cfg.values():
            layer_comp_names.update(comps.keys())

        if not layer_comp_names:
            continue

        func_path = os.path.join(layer_model_dir(layer_name), "functions.json")
        if not os.path.isfile(func_path):
            log(f"{layer_name}: functions.json not found, skipping",
                component="componentDesignDiagram")
            continue

        with open(func_path, "r", encoding="utf-8") as f:
            layer_functions = json.load(f)

        callers_of, callees_of = _build_call_graph(layer_comp_names, layer_functions)

        layer_summary = {}
        for comps_cfg in groups_cfg.values():
            for comp_name in comps_cfg:
                unit_names = _units_for_component(comp_name, units_data)
                if not unit_names:
                    unit_names = [comp_name]

                callers = sorted(callers_of.get(comp_name, set()))
                callees = sorted(callees_of.get(comp_name, set()))

                svg = _build_component_svg(comp_name, unit_names, callers, callees)

                safe = comp_name.replace("/", "_").replace("\\", "_")
                svg_path = os.path.join(out_dir, f"{layer_name}_{safe}_design.svg")
                with open(svg_path, "w", encoding="utf-8") as f:
                    f.write(svg)

                layer_summary[comp_name] = {"svgPath": svg_path}
                log(f"{layer_name}/{comp_name}: {len(callers)} caller(s), "
                    f"{len(callees)} callee(s)",
                    component="componentDesignDiagram")

        summary[layer_name] = layer_summary

    out_json = os.path.join(out_dir, "_component_design_data.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    total = sum(len(v) for v in summary.values())
    log(f"done — {total} component(s)", component="componentDesignDiagram")
