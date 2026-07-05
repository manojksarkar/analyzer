"""
Mermaid flowchart builder.

Converts a labeled ControlFlowGraph into a Mermaid `flowchart TD` script.

Rules (DO NOT CHANGE):
  - Structural truth (edges, topology) comes only from the CFG.
  - Labels are wrapped in double-quotes; the few characters that still break
    inside quotes (", <, >, & and the edge-label pipe |) are swapped for
    fullwidth look-alikes so the raw script pastes cleanly into mermaid.live.
  - <br/> line breaks within labels are preserved.
  - START/END nodes use stadium shape  (["..."])
  - DECISION / LOOP_HEAD / SWITCH_HEAD nodes use diamond  {"..."}
  - All other nodes use rectangle  ["..."]
  - CATCH nodes use subroutine shape  [["..."]]
"""

import re
from typing import Dict, List, Optional

from mermaid.normalizer import normalize_edge_label
from models import CfgEdge, CfgNode, ControlFlowGraph, NodeType


# ---------------------------------------------------------------------------
# Shape mapping
# ---------------------------------------------------------------------------

_DIAMOND_TYPES = frozenset({
    NodeType.DECISION,
    NodeType.LOOP_HEAD,
    NodeType.SWITCH_HEAD,
})

_STADIUM_TYPES = frozenset({
    NodeType.START,
    NodeType.END,
})

_SUBROUTINE_TYPES = frozenset({
    NodeType.CATCH,
})


def build_mermaid(cfg: ControlFlowGraph) -> str:
    """
    Render a ControlFlowGraph as a Mermaid flowchart TD script.
    Returns the complete Mermaid string.
    """
    # graphs have crossings that are mathematically unavoidable.
    MERMAID_CONFIG = """---
config:
  flowchart:
    defaultRenderer: elk
---
%%{
  init: {
    "flowchart": {
      "defaultRenderer": "elk",
      "padding": 0,
      "nodeSpacing": 50,
      "rankSpacing": 60,
      "wrappingWidth": 500,
      "curve": "linear"
    },
    "elk": {
      "mergeEdges": false,
      "nodePlacementStrategy": "BRANDES_KOEPF",
      "cycleBreakingStrategy": "GREEDY",
      "feedbackEdges": true,
      "elk.layered.feedbackEdges": true,
      "elk.layered.thoroughness": 50,
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP"
    },
    "sequence": {
      "padding": 0,
      "nodeMargin": 10,
      "noteMargin": 10,
      "messageMargin": 40,
      "actorMargin": 50,
      "mirrorActors": false
    },
    "theme": "base",
    "themeVariables": {
      "primaryColor": "#fff",
      "nodeBorder": "#000",
      "strokeWidth": "1px",
      "fontSize": "12px",
      "padding": 0
    }
  }
}%%
"""
    MERMAID_CONFIG_LINES = [line for line in MERMAID_CONFIG.split("\n") if line]
    lines: List[str] = MERMAID_CONFIG_LINES + ["flowchart TD"]

    # Node definitions
    for node in _topo_order(cfg):
        lines.append(f"    {_node_def(node)}")

    lines.append("")  # blank line between defs and edges

    # Edge definitions
    for edge in cfg.edges:
        lines.append(f"    {_edge_def(edge)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node definition rendering
# ---------------------------------------------------------------------------

def _node_def(node: CfgNode) -> str:
    """
    Render a single Mermaid node definition line.

    Labels are NOT wrapped in double-quotes.  Wrapping in " causes the
    Mermaid script stored in JSON to contain \" (JSON-escaped quotes),
    which breaks mermaid.live when users copy-paste the raw value.
    All special characters are already encoded with #NNN; entity codes
    by _escape_label(), so no delimiters are needed.
    """
    label = node.label or node.raw_code[:60] or node.node_id
    label = _enforce_line_length(label)
    escaped = _escape_label(label)

    nid = node.node_id
    t = node.node_type

    if t in _STADIUM_TYPES:
        return f'{nid}(["{escaped}"])'
    if t in _DIAMOND_TYPES:
        return f'{nid}{{"{escaped}"}}'
    if t in _SUBROUTINE_TYPES:
        return f'{nid}[["{escaped}"]]'
    return f'{nid}["{escaped}"]'


# ---------------------------------------------------------------------------
# Edge definition rendering
# ---------------------------------------------------------------------------

def _edge_def(edge: CfgEdge) -> str:
    """
    Render a Mermaid edge with an optional label.

    Edge labels are wrapped in double-quotes and escaped by _escape_edge_label()
    (which also neutralises the pipe `|`, since it delimits the edge label).
    """
    norm_label = normalize_edge_label(edge.label)
    if norm_label:
        escaped = _escape_edge_label(norm_label)
        return f'{edge.source} -->|"{escaped}"| {edge.target}'
    return f"{edge.source} --> {edge.target}"


# ---------------------------------------------------------------------------
# Topological ordering (deterministic: entry node first, then BFS)
# ---------------------------------------------------------------------------

def _topo_order(cfg: ControlFlowGraph) -> List[CfgNode]:
    """
    Return nodes in a stable order: entry first, then BFS.
    Deterministic output (no random set iteration).
    """
    if not cfg.nodes:
        return []

    adjacency: Dict[str, List[str]] = {nid: [] for nid in cfg.nodes}
    for edge in cfg.edges:
        if edge.source in adjacency:
            adjacency[edge.source].append(edge.target)

    visited: List[str] = []
    seen = set()
    queue = [cfg.entry_node_id] if cfg.entry_node_id in cfg.nodes else [
        next(iter(cfg.nodes))
    ]

    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        if nid in cfg.nodes:
            visited.append(nid)
        for child in adjacency.get(nid, []):
            if child not in seen:
                queue.append(child)

    # Append any nodes not reached by BFS (isolated or back-edge-only nodes)
    for nid in cfg.nodes:
        if nid not in seen:
            visited.append(nid)

    return [cfg.nodes[nid] for nid in visited]


# ---------------------------------------------------------------------------
# Label escaping
# ---------------------------------------------------------------------------

# Characters that must be neutralised even inside a double-quoted Mermaid label.
# Instead of #NNN; entities we wrap labels in double-quotes and swap the few
# remaining breakers for look-alike glyphs, so the raw script pastes cleanly
# into mermaid.live (and survives JSON round-tripping).
_QUOTED_LABEL_MAP: dict = {
    '"': "'",
    "<": "＜",  # ＜ fullwidth less-than
    ">": "＞",  # ＞ fullwidth greater-than
    "&": "＆",  # ＆ fullwidth ampersand
}

_NODE_LABEL_RE = re.compile(r'["<>&]')
_EDGE_LABEL_MAP: dict = dict(_QUOTED_LABEL_MAP, **{"|": "｜"})  # ｜ fullwidth pipe
_EDGE_LABEL_RE = re.compile(r'["<>&|]')

_BR_PLACEHOLDER = "\x00BR\x00"

# Maximum characters per visual line in a Mermaid node label.
# Mermaid's SVG renderer does NOT word-wrap within a line; it only breaks
# at explicit <br/> tags.  If a line is too long it extends beyond the node
# boundary and wraps awkwardly when the browser wraps the SVG text element.
# This limit is applied mechanically AFTER the LLM generates labels so that
# even labels that violate the system-prompt guideline are fixed before render.
_MAX_LINE_CHARS = 40


def _enforce_line_length(label: str, max_chars: int = _MAX_LINE_CHARS) -> str:
    """
    Ensure no <br/>-separated segment exceeds max_chars characters.

    Algorithm:
      1. Split label on existing <br/> tags.
      2. For each segment, if it is longer than max_chars, word-wrap it:
         break at the last space that keeps the current chunk ≤ max_chars,
         inserting a <br/> at each break point.
      3. Rejoin all segments with <br/>.

    Words longer than max_chars are never broken mid-word to avoid
    corrupting function names or technical terms.
    """
    if not label:
        return label

    # Normalise <br /> → <br/>
    label = label.replace("<br />", "<br/>")
    segments = label.split("<br/>")

    result_segments: List[str] = []
    for seg in segments:
        seg = seg.strip()
        if len(seg) <= max_chars:
            result_segments.append(seg)
            continue

        # Word-wrap this segment
        words = seg.split(" ")
        current_line: List[str] = []
        current_len = 0
        wrapped: List[str] = []

        for word in words:
            # +1 for the space before the word (except at start of line)
            addition = len(word) + (1 if current_line else 0)
            if current_line and current_len + addition > max_chars:
                wrapped.append(" ".join(current_line))
                current_line = [word]
                current_len = len(word)
            else:
                current_line.append(word)
                current_len += addition

        if current_line:
            wrapped.append(" ".join(current_line))

        result_segments.extend(wrapped)

    return "<br/>".join(result_segments)


def _escape_label(text: str) -> str:
    """
    Make a node label safe inside a double-quoted Mermaid label.

    - <br/> line-break tags are preserved verbatim (and protected from the
      `<`/`>` look-alike substitution below).
    - Newline characters (\\n) are converted to <br/> for multi-line labels.
    - Only ", <, >, & are replaced (see _QUOTED_LABEL_MAP); everything else is
      literal inside the quotes.
    """
    if not text:
        return text

    # Protect <br/> line-break tags (so their < > are not turned into look-alikes)
    text = text.replace("<br/>", _BR_PLACEHOLDER)
    text = text.replace("<br />", _BR_PLACEHOLDER)

    # Convert real newlines to <br/>
    text = text.replace("\n", _BR_PLACEHOLDER)
    text = text.replace("\r", "")

    # Single-pass substitution — a replacement char never feeds back into the pattern
    text = _NODE_LABEL_RE.sub(lambda m: _QUOTED_LABEL_MAP[m.group(0)], text)

    # Restore line-break placeholders
    text = text.replace(_BR_PLACEHOLDER, "<br/>")

    return text


def _escape_edge_label(text: str) -> str:
    """
    Make an edge label safe inside `-->|"..."|`. Same as _escape_label plus the
    pipe `|` (which delimits the edge label) is replaced with a look-alike.
    """
    if not text:
        return text
    return _EDGE_LABEL_RE.sub(lambda m: _EDGE_LABEL_MAP[m.group(0)], text)
