"""Flowchart SVGs: the facts the engine (which draws them) and the web render (which shows
them, api/services/doc_render.py) must agree on. Kept free of engine-wide imports so the API
can load it without pulling in the engine's config.

Charts over FLOWCHART_SVG_MAX_BOXES are not drawn. Graphviz's layout time grows steeply with
size -- measured with the repo's viz-js on flowcharts in dot_builder's style: 500 nodes ~2 s,
750 ~14-22 s, 1,000 ~1-2 min, and one 1,000-node graph aborted the WASM module -- and a
picture that size is unreadable anyway. The web render uses the same count and limit to tell
"too large to draw" from "not drawn".
"""
import hashlib
import re

FLOWCHART_SVG_MAX_BOXES = 500

# Bumped whenever engine/config/render_svg.mjs starts drawing a DIFFERENT SVG for the same DOT,
# so every SVG on disk counts as stale and is redrawn (the key is stored in each file).
_SVG_RENDERER_VERSION = 1

# A node statement: `N3 [shape=box, ...];` (dot_builder._node_def). Edge statements have
# `->` before their `[`, and `node [...]` / `edge [...]` / `graph [...]` set defaults.
_DOT_NODE_RE = re.compile(r'^[ \t]*("(?:[^"\\]|\\.)*"|[A-Za-z_][\w.]*)[ \t]*\[', re.M)
_SVG_KEY_RE = re.compile(rb"<!-- dot-key: ([0-9a-f]{64}) -->")
_SVG_TAG_RE = re.compile(rb"<svg\b[^>]*>")
_SVG_DIM_RE = {dim: re.compile(rb'\b' + dim + rb'="([\d.]+)(pt|px)?"') for dim in (b"width", b"height")}


def svg_file_name(unit_stem, function_name) -> str:
    """`<unit>_<function>.svg`: a chart's PNG name with .svg. The function part is
    utils.safe_filename's, kept identical so the pair never drift apart; the web render looks
    files up with this, not with its own display-name cleaning, which differs for operators."""
    safe = re.sub(r'[<>:"/\\|?*,&;]', "_", (function_name or "").replace(" ", "-"))
    return f"{unit_stem}_{safe}.svg"


def count_dot_boxes(dot) -> int:
    """How many nodes a flowchart DOT declares: the boxes, diamonds and ovals a reader sees."""
    return sum(1 for m in _DOT_NODE_RE.finditer(dot or "")
               if m.group(1) not in ("node", "edge", "graph"))


def svg_content_key(dot) -> str:
    """What an SVG drawn from `dot` carries in its `<!-- dot-key: ... -->` comment."""
    src = f"{dot or ''}|svg-r={_SVG_RENDERER_VERSION}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _head(svg_path, size: int):
    try:
        with open(svg_path, "rb") as f:
            return f.read(size)
    except OSError:
        return None


def svg_file_key(svg_path):
    """The content key an SVG on disk was drawn from, or None (absent / not ours)."""
    head = _head(svg_path, 512)
    m = _SVG_KEY_RE.search(head) if head else None
    return m.group(1).decode("ascii") if m else None


def svg_size_px(svg_path):
    """(width, height) in CSS pixels, from the <svg> tag's own size, or None.

    Graphviz sizes the tag in points; a browser draws a point as 4/3 of a pixel, so this is the
    size an <img> of the file comes out at -- what the web reader reserves before it loads.
    """
    head = _head(svg_path, 2048)
    tag = _SVG_TAG_RE.search(head) if head else None
    if not tag:
        return None
    size = []
    for dim in (b"width", b"height"):
        m = _SVG_DIM_RE[dim].search(tag.group(0))
        if not m:
            return None
        size.append(round(float(m.group(1)) * (4 / 3 if m.group(2) == b"pt" else 1)))  # no unit = px
    return tuple(size)
