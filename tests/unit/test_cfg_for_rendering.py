"""A flowchart drawn from a STORED graph must match one drawn from the live graph.

REQ-AP-06. Correcting a node label patches the stored CFG and regenerates the DOT from it, so
there are now two routes to the same picture:

    live CFG ───────────────────────► build_dot ──► DOT
    live CFG ─► serialize ─► store ─► load ─► build_dot ──► DOT

If those two ever disagree, a flowchart re-rendered after a correction quietly stops matching the
one a full regeneration produces -- two paths drawing "the same" picture and drifting apart, with
no error. That is the defect shape this codebase keeps being caught by, so the equality is pinned
directly rather than approximated by checking fields.

`cfg_for_rendering` is NOT the inverse of `serialize_cfg` and is not tested as one: `serialize_cfg`
writes `label or raw_code` into a single field and drops the CFG's own metadata entirely. The
property that matters is not "the object round-trips" but "the picture is the same".
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
# The flowchart package imports its own submodules flat (`from mermaid.normalizer import ...`),
# so its directory goes on the path too -- same as test_flowchart_engine_db_inputs.
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine", "flowchart"))

from flowchart.dot_builder import build_dot
from flowchart.models import (CfgEdge, CfgNode, ControlFlowGraph, NodeType, cfg_for_rendering,
                              serialize_cfg)


def _node(nid, ntype, raw, label="", line=1):
    return CfgNode(node_id=nid, node_type=ntype, raw_code=raw, start_line=line,
                   end_line=line, label=label)


def _cfg():
    """A graph with the features the DOT builder treats differently: a decision with labelled
    branches, a loop with a back edge, a return, and a node with no LLM label."""
    nodes = [
        _node("n0", NodeType.START, "", "", 1),
        _node("n1", NodeType.ACTION, "init();", "Initialise the driver", 2),
        _node("n2", NodeType.LOOP_HEAD, "while (i < n)", "For every block", 3),
        _node("n3", NodeType.DECISION, "if (busy)", "Is the device busy?", 4),
        _node("n4", NodeType.ACTION, "wait();", "", 5),          # no LLM label
        _node("n5", NodeType.RETURN, "return OK;", "Report success", 6),
        _node("n6", NodeType.END, "", "", 7),
    ]
    return ControlFlowGraph(
        function_key="Comp|UnitA|doThing|", qualified_name="ns::doThing",
        source_file="a/b/UnitA.cpp", start_line=1, end_line=7,
        nodes={n.node_id: n for n in nodes},
        edges=[CfgEdge("n0", "n1"), CfgEdge("n1", "n2"),
               CfgEdge("n2", "n3", "true"), CfgEdge("n3", "n4", "yes"),
               CfgEdge("n4", "n2"),                               # back edge
               CfgEdge("n3", "n5", "no"), CfgEdge("n5", "n6")],
        entry_node_id="n0", exit_node_ids=["n6"])


class TestThePictureSurvivesStorage:
    def test_the_dot_is_byte_identical_through_a_store_and_load(self):
        live = _cfg()
        reloaded = cfg_for_rendering(serialize_cfg(live))
        assert build_dot(reloaded) == build_dot(live)

    def test_it_holds_after_a_label_is_corrected(self):
        """The real use: patch the stored graph, redraw. The correction must appear, and nothing
        else about the picture may move."""
        stored = serialize_cfg(_cfg())
        for n in stored["nodes"]:
            if n["id"] == "n3":
                n["label"] = "Is the write-protect flag set?"
        dot = build_dot(cfg_for_rendering(stored))
        # Matched on a distinctive word, not the whole sentence: build_dot line-wraps, so no
        # label appears verbatim. That is the behaviour the next test is about.
        assert "write-protect" in dot
        assert "busy" not in dot, "the old wording survived the correction"
        assert "Initialise" in dot, "an unrelated node changed"

    def test_a_long_correction_is_re_wrapped_not_pasted(self):
        """Why the DOT is regenerated instead of patched: labels are line-wrapped on the way in,
        so a longer replacement needs re-wrapping. Patching DOT text would mean writing the
        wrapping rules a second time, in a second place, to drift from the first."""
        stored = serialize_cfg(_cfg())
        long_text = ("Check whether the write-protect flag is set on the currently selected "
                     "flash die before issuing the erase")
        for n in stored["nodes"]:
            if n["id"] == "n3":
                n["label"] = long_text
        dot = build_dot(cfg_for_rendering(stored))
        assert long_text not in dot, "the label went in unwrapped: build_dot was bypassed"
        assert "write-protect" in dot


class TestWhatItRestores:
    def test_the_graph_structure_comes_back(self):
        live = _cfg()
        back = cfg_for_rendering(serialize_cfg(live))
        assert set(back.nodes) == set(live.nodes)
        assert back.entry_node_id == live.entry_node_id
        assert [(e.source, e.target, e.label) for e in back.edges] == \
               [(e.source, e.target, e.label) for e in live.edges]

    def test_node_types_come_back(self):
        """A DECISION that returned as an ACTION would be drawn as a box instead of a diamond."""
        back = cfg_for_rendering(serialize_cfg(_cfg()))
        assert back.nodes["n3"].node_type is NodeType.DECISION
        assert back.nodes["n2"].node_type is NodeType.LOOP_HEAD
        assert back.nodes["n0"].node_type is NodeType.START

    def test_an_unknown_node_type_does_not_lose_the_flowchart(self):
        """A stored graph from a build that knows a node kind this one does not. ACTION is the
        neutral shape -- the node still appears and still connects. Raising would trade one
        unrecognised node for a whole missing picture."""
        stored = serialize_cfg(_cfg())
        stored["nodes"][3]["type"] = "QUANTUM_HEAD"
        back = cfg_for_rendering(stored)
        assert back.nodes["n3"].node_type is NodeType.ACTION
        assert "n3" in build_dot(back)


class TestItDoesNotOverclaim:
    def test_the_metadata_serialize_drops_is_not_invented(self):
        """`serialize_cfg` never writes these, so they cannot come back. Returning a plausible
        value would be worse than an empty one: a caller would believe it."""
        back = cfg_for_rendering(serialize_cfg(_cfg()))
        assert back.function_key == ""
        assert back.qualified_name == ""
        assert back.source_file == ""

    def test_it_is_not_a_round_trip_and_does_not_pretend_to_be(self):
        """Pinning the lossiness on purpose. If someone later "fixes" this into a true inverse
        they will have to change serialize_cfg, and this test says why that is not free."""
        live = _cfg()
        assert live.nodes["n4"].label == ""
        back = cfg_for_rendering(serialize_cfg(live))
        assert back.nodes["n4"].label == "wait();", (
            "serialize writes `label or raw_code`, so an unlabelled node comes back carrying its "
            "source line -- the renderer cannot tell, and must not; the training export must")

    def test_rubbish_does_not_raise(self):
        for bad in ({}, None, {"nodes": None}, {"nodes": [{"no_id": 1}], "edges": [{}]}):
            assert cfg_for_rendering(bad).nodes == {}

    def test_an_edge_to_nowhere_is_dropped(self):
        back = cfg_for_rendering({"nodes": [{"id": "n0", "type": "START"}],
                                  "edges": [{"source": "n0"}, {"target": "n1"}]})
        assert back.edges == []
