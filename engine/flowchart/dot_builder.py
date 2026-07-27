"""
Graphviz DOT builder (graphviz-normal).

Converts a labeled ControlFlowGraph into a Graphviz `dot` script.  Graphviz is
used instead of Mermaid because its dagre-style hierarchical layout keeps nodes
in SOURCE ORDER (a statement written earlier in the function renders above one
written later — e.g. a loop body sits below its loop head) while still giving
clean, corner-routed orthogonal edges.

Loop handling keeps two invariants the client asked for:
  1. Return/End sink to the BOTTOM.  A loop head's exit branch would otherwise
     rank the exit node one row below the head — floating Return/End up beside
     the loop body.  Invisible constraint edges from every loop tail to each
     exit node push the exit (and its Return/End chain) below the whole body.
  2. No crossing lines.  Loop back-edges are drawn with `constraint=false` so
     they stop distorting the rank assignment, and are routed into a lane
     separate from the exit branch (back-edges enter the head from the east,
     the exit branch leaves/arrives from the west).

Shape mapping (classic flowchart):
  START / END                          -> ellipse
  DECISION / LOOP_HEAD / SWITCH_HEAD   -> diamond
  CATCH                                -> box
  everything else                      -> box

Edge (Yes/No/case) labels are placed with `taillabel` so they sit on the branch
at the decision node, not floating beside the edge.
"""

from collections import defaultdict
from typing import Dict, List, Set, Tuple

from mermaid.normalizer import normalize_edge_label
from models import CfgEdge, CfgNode, ControlFlowGraph, NodeType

_DIAMOND_TYPES = frozenset({
    NodeType.DECISION,
    NodeType.LOOP_HEAD,
    NodeType.SWITCH_HEAD,
})
_ELLIPSE_TYPES = frozenset({
    NodeType.START,
    NodeType.END,
})

# Graph/appearance defaults (match the flowchart-preview/graphviz look).
_GRAPH_ATTRS = [
    "rankdir=TB",
    "splines=ortho",
    "nodesep=0.5",
    "ranksep=0.55",
]
_NODE_ATTRS = 'fontname="Helvetica", fontsize=12, color="#8b7fd6", penwidth=1.4, style=filled, fillcolor="#eae6fb"'
_EDGE_ATTRS = 'fontname="Helvetica", fontsize=11, color="#333333", penwidth=1.4'


def build_dot(cfg: ControlFlowGraph) -> str:
    """Render a ControlFlowGraph as a Graphviz dot script (graphviz-normal)."""
    layout = _analyze_loops(cfg)

    lines: List[str] = ["digraph G {"]
    for attr in _GRAPH_ATTRS:
        lines.append(f"  {attr};")
    lines.append(f"  node [{_NODE_ATTRS}];")
    lines.append(f"  edge [{_EDGE_ATTRS}];")
    lines.append("")

    # Node definitions — in CFG insertion order (≈ source order).
    for node in cfg.nodes.values():
        lines.append(f"  {_node_def(node)}")

    lines.append("")

    # Edge definitions.
    for edge in cfg.edges:
        lines.append(f"  {_edge_def(edge, layout)}")

    # Invisible push-down edges: force loop-exit nodes (Return/End) below the
    # loop body so they land at the bottom instead of beside the loop head.
    if layout.push_down:
        lines.append("")
        for src, tgt in layout.push_down:
            lines.append(f"  {src} -> {tgt} [style=invis];")

    lines.append("}")
    return "\n".join(lines) + "\n"


class _LoopLayout:
    """Loop-derived edge roles + the invisible edges that anchor Return/End."""

    def __init__(self) -> None:
        self.back_edges: Set[Tuple[str, str]] = set()
        self.exit_edges: Set[Tuple[str, str]] = set()
        self.push_down: List[Tuple[str, str]] = []


def _analyze_loops(cfg: ControlFlowGraph) -> _LoopLayout:
    """Classify edges (back / loop-exit) and derive Return/End push-down edges.

    Back-edges are found by a DFS from the entry node: an edge to a node that is
    still on the DFS stack loops back to an enclosing head.  (Insertion order is
    NOT a reliable signal — the builder emits the End node early, so a plain
    ``return -> End`` edge would look "backwards".)  Each loop's natural body is
    the header plus every node that can reach a back-edge tail without passing
    through the header.  A loop-exit edge leaves a loop head for a node outside
    every loop body.
    """
    layout = _LoopLayout()
    if not cfg.nodes:
        return layout

    succ: Dict[str, List[str]] = defaultdict(list)
    preds: Dict[str, Set[str]] = defaultdict(set)
    for e in cfg.edges:
        succ[e.source].append(e.target)
        preds[e.target].add(e.source)

    back_edges = _find_back_edges(cfg, succ)
    if not back_edges:
        return layout

    layout.back_edges = back_edges
    heads = {tgt for _, tgt in back_edges}

    # Natural loop body per head (union over its back-edges) + global union.
    body_by_head: Dict[str, Set[str]] = defaultdict(set)
    for src, tgt in back_edges:
        body_by_head[tgt] |= _natural_loop(src, tgt, preds)
    loop_body: Set[str] = set()
    for body in body_by_head.values():
        loop_body |= body

    back_sources = {src for src, _ in back_edges}

    # Loop-exit edges: an edge out of a loop head to a node in no loop.
    exits_by_head: Dict[str, List[str]] = defaultdict(list)
    for e in cfg.edges:
        key = (e.source, e.target)
        if (e.source in heads and key not in back_edges
                and e.target not in loop_body):
            layout.exit_edges.add(key)
            exits_by_head[e.source].append(e.target)

    # Anchor each exit below its loop: push down from every back-edge tail that
    # lives inside that loop's body (covers nested-loop tails too).
    seen: Set[Tuple[str, str]] = set()
    for head, exit_targets in exits_by_head.items():
        body = body_by_head.get(head, set())
        for tail in back_sources:
            if tail not in body:
                continue
            for exit_node in exit_targets:
                key = (tail, exit_node)
                if key not in seen:
                    seen.add(key)
                    layout.push_down.append(key)
    return layout


def _find_back_edges(cfg: ControlFlowGraph,
                     succ: Dict[str, List[str]]) -> Set[Tuple[str, str]]:
    """Back-edges via iterative DFS: an edge to a node still on the stack.

    Starts at the CFG entry (falling back to the first node) so detection is
    independent of node insertion order."""
    entry = cfg.entry_node_id if cfg.entry_node_id in cfg.nodes else next(iter(cfg.nodes))
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = defaultdict(int)  # default WHITE
    back: Set[Tuple[str, str]] = set()

    # Restart from every unvisited node so disconnected pieces are still scanned.
    for root in (entry, *cfg.nodes):
        if color[root] != WHITE:
            continue
        color[root] = GRAY
        stack = [(root, iter(succ.get(root, ())))]
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if color[nxt] == GRAY:
                    back.add((node, nxt))
                elif color[nxt] == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(succ.get(nxt, ()))))
                    break
            else:
                color[node] = BLACK
                stack.pop()
    return back


def _natural_loop(tail: str, header: str, preds: Dict[str, Set[str]]) -> Set[str]:
    """Nodes in the natural loop of back-edge tail -> header.

    Reverse-reachability from the tail over the whole CFG, never expanding past
    the header (so inner-loop nodes of an enclosing loop are still included)."""
    loop = {header, tail}
    stack = [tail]
    while stack:
        node = stack.pop()
        for pred in preds.get(node, ()):  # header stays un-expanded
            if pred not in loop:
                loop.add(pred)
                stack.append(pred)
    return loop


def _shape(node: CfgNode) -> str:
    if node.node_type in _ELLIPSE_TYPES:
        return "ellipse"
    if node.node_type in _DIAMOND_TYPES:
        return "diamond"
    return "box"


def _node_def(node: CfgNode) -> str:
    label = node.label or node.raw_code[:60] or node.node_id
    return f'{node.node_id} [shape={_shape(node)}, label="{_escape(label)}"];'


def _edge_def(edge: CfgEdge, layout: _LoopLayout) -> str:
    attrs: List[str] = []
    label = normalize_edge_label(edge.label)
    if label:
        # taillabel keeps the Yes/No/case text on the branch at the decision.
        attrs.append(f'taillabel="{_escape(label)}", labeldistance=2.0, labelfontsize=11')

    key = (edge.source, edge.target)
    if key in layout.back_edges:
        # Free the rank solver and route back-edges up their own (east) lane.
        attrs.append("constraint=false")
        attrs.append("headport=e")
    elif key in layout.exit_edges:
        # Keep the loop-exit branch in a lane separate from the back-edges.
        attrs.append("tailport=w")
        attrs.append("headport=w")

    if attrs:
        return f'{edge.source} -> {edge.target} [{", ".join(attrs)}];'
    return f"{edge.source} -> {edge.target};"


def _escape(text: str) -> str:
    """
    Escape a label for a Graphviz double-quoted string.

    Backslashes and double-quotes are escaped; <br/> tags and real newlines
    become the DOT line-break sequence.  All other characters — ( ) ; < > | & —
    are literal inside a quoted DOT label, so no entity encoding is needed.
    """
    if not text:
        return ""
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("<br/>", "\\n").replace("<br />", "\\n")
    text = text.replace("\n", "\\n").replace("\r", "")
    return text
