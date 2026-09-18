"""Core data models for the flowchart engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class NodeType(str, Enum):
    START = "START"
    END = "END"
    ACTION = "ACTION"
    DECISION = "DECISION"
    LOOP_HEAD = "LOOP_HEAD"
    SWITCH_HEAD = "SWITCH_HEAD"
    CASE = "CASE"
    DEFAULT_CASE = "DEFAULT_CASE"
    RETURN = "RETURN"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    TRY_HEAD = "TRY_HEAD"
    CATCH = "CATCH"


@dataclass
class CfgEdge:
    source: str
    target: str
    label: Optional[str] = None


@dataclass
class CfgNode:
    node_id: str
    node_type: NodeType
    raw_code: str
    start_line: int
    end_line: int
    label: str = ""
    enriched_context: Dict = field(default_factory=dict)


@dataclass
class ControlFlowGraph:
    function_key: str
    qualified_name: str
    source_file: str
    start_line: int
    end_line: int
    nodes: Dict[str, CfgNode] = field(default_factory=dict)
    edges: List[CfgEdge] = field(default_factory=list)
    entry_node_id: str = ""
    exit_node_ids: List[str] = field(default_factory=list)


@dataclass
class FunctionEntry:
    key: str
    qualified_name: str
    file: str
    line: int
    end_line: int
    params: List[Dict] = field(default_factory=list)
    calls_ids: List[str] = field(default_factory=list)
    called_by_ids: List[str] = field(default_factory=list)
    interface_id: str = ""
    description: str = ""
    # Var-decls recorded as pseudo-functions (e.g. a macro-obscured
    # "UNIT _f(arg);" parsed as a VAR_DECL). These have no body, so no CFG can
    # be built — the engine skips them. Every other entry is a real definition.
    synthetic_from_var_decl: bool = False


@dataclass
class ProjectMeta:
    base_path: str
    project_name: str


@dataclass
class FlowchartResult:
    function_key: str
    qualified_name: str
    mermaid_script: str
    error: Optional[str] = None
    # Serialized ControlFlowGraph (see serialize_cfg). The DOT script above is a
    # rendering; this is the graph itself, kept so consumers that need the
    # structure rather than a picture — SWE.4 Test Steps — do not have to
    # re-parse the source. None when the CFG could not be built.
    cfg: Optional[Dict] = None


def cfg_for_rendering(data: Dict) -> "ControlFlowGraph":
    """A stored CFG dict -> the graph the DOT builder needs. **Not** the inverse of
    `serialize_cfg`.

    Deliberately NOT called `deserialize_cfg`, because `serialize_cfg` is lossy and a function
    claiming to invert it would be lying to the next caller: `label` is written as
    `n.label or n.raw_code`, so the two collapse into one field, and `function_key`,
    `qualified_name`, `source_file` and the CFG's own line numbers are not written at all (they
    live one level up, on the surrounding flowchart-JSON entry).

    What this DOES restore is everything `dot_builder.build_dot` reads, which was checked rather
    than assumed: `nodes`, `edges`, `entry_node_id`, and per node `node_id`, `node_type`, `label`
    and `raw_code`. All of those are stored, so a picture drawn from the reloaded graph is
    identical to one drawn from the live graph — pinned by a test that compares the two DOT
    strings.

    Used when a reviewer corrects a node label: the correction patches the stored CFG and the DOT
    is regenerated from it. The DOT is never edited directly — labels are line-wrapped and escaped
    on the way in, so patching the text would put those rules in a second place to drift from the
    first, and the SWE.4 Test Steps read the CFG rather than the DOT.

    Fields this cannot know are left at their defaults. Anything needing them must read the
    flowchart-JSON entry that carries them.
    """
    data = data or {}
    nodes: Dict[str, CfgNode] = {}
    for n in data.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        # Carried because it is there, not because the picture needs it: `serialize_cfg` writes
        # `label or raw_code`, so the stored `label` is already non-empty whenever raw_code was,
        # and `build_dot`'s `label or raw_code` fallback never fires on a reloaded graph. No test
        # can observe this field through the DOT -- that is a property of the format, not a gap.
        raw = n.get("rawCode") or ""
        nodes[str(n["id"])] = CfgNode(
            node_id=str(n["id"]),
            node_type=_node_type(n.get("type")),
            raw_code=raw,
            start_line=int(n.get("line") or 0),
            end_line=int(n.get("endLine") or 0),
            # `label or raw_code` on the way out means a node the LLM never labelled is stored
            # with its source line as the label. Reading it straight back keeps the picture the
            # same, which is what matters here; it is the training data that must tell them
            # apart, not the renderer.
            label=n.get("label") or "",
        )
    edges = [CfgEdge(source=str(e.get("source") or ""), target=str(e.get("target") or ""),
                     label=e.get("label"))
             for e in (data.get("edges") or [])
             if isinstance(e, dict) and e.get("source") and e.get("target")]
    return ControlFlowGraph(
        function_key="", qualified_name="", source_file="", start_line=0, end_line=0,
        nodes=nodes, edges=edges,
        entry_node_id=str(data.get("entry") or ""),
        exit_node_ids=[str(x) for x in (data.get("exits") or [])],
    )


def _node_type(value) -> NodeType:
    """A stored `type` string -> NodeType, falling back to ACTION.

    An unknown type means the stored graph predates a node kind this build knows, or the reverse.
    ACTION is the neutral shape: the node still appears, still connects, and the picture stays
    readable. Raising would make one unrecognised node lose a whole flowchart.
    """
    try:
        return NodeType(value)
    except ValueError:
        return NodeType.ACTION


def serialize_cfg(cfg: "ControlFlowGraph") -> Dict:
    """ControlFlowGraph -> JSON-serializable dict.

    Node text is the enriched/LLM `label` where one exists, falling back to the
    raw source so a run with labelling disabled still carries usable text.
    """
    return {
        "entry": cfg.entry_node_id,
        "exits": list(cfg.exit_node_ids),
        "nodes": [
            {
                "id": n.node_id,
                "type": n.node_type.value,
                "label": n.label or n.raw_code,
                "rawCode": n.raw_code,
                "line": n.start_line,
                "endLine": n.end_line,
            }
            for n in cfg.nodes.values()
        ],
        "edges": [
            {"source": e.source, "target": e.target, "label": e.label}
            for e in cfg.edges
        ],
    }


@dataclass
class FileResult:
    source_file: str
    flowcharts: List[FlowchartResult] = field(default_factory=list)
