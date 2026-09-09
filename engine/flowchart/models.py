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
