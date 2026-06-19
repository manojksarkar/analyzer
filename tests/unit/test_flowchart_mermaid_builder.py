"""Unit tests for the flowchart Mermaid builder's label escaping.

Locks in the quoted-label fix: labels are wrapped in double-quotes and only
", <, >, & are altered (the last three -> fullwidth look-alikes), so they render
correctly under ANY Mermaid `htmlLabels` setting. The previous scheme emitted
`#NNN;` entity codes that render literally (e.g. `#40;`) when htmlLabels is false.
"""
import os
import re
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "flowchart"))

from models import CfgNode, CfgEdge, ControlFlowGraph, NodeType  # noqa: E402
from mermaid.builder import build_mermaid, _escape_label, _escape_edge_label  # noqa: E402

LT, GT, AMP, PIPE = "＜", "＞", "＆", "｜"  # fullwidth ＜ ＞ ＆ ｜
_ENTITY_RE = re.compile(r"#\d+;|#quot;")


class TestEscapeLabel:
    def test_double_quote_becomes_apostrophe(self):
        assert _escape_label('say "hi"') == "say 'hi'"

    def test_brackets_parens_braces_pipe_left_raw(self):
        # Inside double quotes these render fine — must NOT be touched.
        assert _escape_label("f(x) [y] {z} a|b") == "f(x) [y] {z} a|b"

    def test_angle_and_amp_become_fullwidth(self):
        assert _escape_label("i < n & j > 0") == f"i {LT} n {AMP} j {GT} 0"

    def test_newline_becomes_br(self):
        assert _escape_label("a\nb") == "a<br/>b"

    def test_existing_br_preserved_not_mangled(self):
        # The < > of <br/> must survive the look-alike substitution.
        assert _escape_label("keep<br/>break") == "keep<br/>break"
        assert _escape_label("keep<br />break") == "keep<br/>break"

    def test_never_emits_entity_codes(self):
        for s in ("back(info[index])", "a < b > c & d", 'q"x', "p|q"):
            assert not _ENTITY_RE.search(_escape_label(s)), s

    def test_empty(self):
        assert _escape_label("") == ""


class TestEscapeEdgeLabel:
    def test_pipe_becomes_fullwidth(self):
        # The pipe delimits the edge label, so it must be neutralised here.
        assert _escape_edge_label("a|b") == f"a{PIPE}b"

    def test_angle_amp_quote_handled(self):
        assert _escape_edge_label('x > 0 & "y"') == f"x {GT} 0 {AMP} 'y'"


class TestBuildMermaidQuoting:
    def _cfg(self, ntype, label):
        cfg = ControlFlowGraph(function_key="k", qualified_name="q",
                               source_file="f.cpp", start_line=1, end_line=2)
        cfg.nodes["N1"] = CfgNode("N1", ntype, "", 1, 1, label=label)
        cfg.nodes["N2"] = CfgNode("N2", NodeType.END, "", 2, 2, label="End")
        cfg.edges = [CfgEdge("N1", "N2")]
        cfg.entry_node_id = "N1"
        cfg.exit_node_ids = ["N2"]
        return cfg

    def test_stadium_label_quoted_parens_raw(self):
        out = build_mermaid(self._cfg(NodeType.START, "compute(int a, int b)"))
        assert 'N1(["compute(int a, int b)"])' in out
        assert not _ENTITY_RE.search(out)

    def test_diamond_quoted(self):
        out = build_mermaid(self._cfg(NodeType.DECISION, "x > 0"))
        assert f'N1{{"x {GT} 0"}}' in out

    def test_rectangle_quoted(self):
        out = build_mermaid(self._cfg(NodeType.ACTION, "y = f(z)"))
        assert 'N1["y = f(z)"]' in out

    def test_subroutine_quoted(self):
        out = build_mermaid(self._cfg(NodeType.CATCH, "handle(e)"))
        assert 'N1[["handle(e)"]]' in out

    def test_no_entity_codes_anywhere(self):
        out = build_mermaid(self._cfg(NodeType.START, "back(info[index]) < max & x"))
        assert not _ENTITY_RE.search(out)
        assert '"' in out  # labels are quoted
