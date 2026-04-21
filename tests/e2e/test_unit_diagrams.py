"""Tests for the unitDiagrams view (output/unit_diagrams/*.mmd).

Logical tests only — no snapshots. Checks:
- Mermaid format and structure (flowchart LR, module subgraph, styling)
- Call-graph topology: each cross-module edge appears in both the source and
  target unit's diagram, with an interfaceId (IF_) label
- Direction invariants: Util never calls out, Core has no incoming callers

Call graph for the Sample group (from SampleCppProject source):
  Core → Lib  (coreAdd→libAdd, coreOrchestrate→libAdd/libNormalize,
               coreProcess→libNormalize)
  Core → Util (coreOrchestrate→utilCompute/utilScale)
  Lib  → Util (libNormalize→utilCompute)
  Util → (nothing cross-module)

All three modules belong to the Sample group, so every unit is "internal"
— nodes and edges live inside the module subgraph, not outside it.
"""
import os

import pytest

pytestmark = pytest.mark.e2e

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UNIT_DIAGRAMS_DIR = os.path.join(PROJECT_ROOT, "output", "unit_diagrams")

# unit_key "Core|Core"  →  safe_filename  →  "Core_Core"
UNITS = {
    "Core": "Core_Core",
    "Lib":  "Lib_Lib",
    "Util": "Util_Util",
}

# Every cross-module edge × every diagram it must appear in.
# Each graph edge appears twice: once in the source unit's diagram (as outgoing)
# and once in the target unit's diagram (as incoming caller).
CROSS_MODULE_EDGES = [
    # (diagram,  src_node,    dst_node,    reason)
    ("Core", "Core_Core", "Lib_Lib",   "coreAdd/coreOrchestrate→libAdd, coreProcess/coreOrchestrate→libNormalize"),
    ("Core", "Core_Core", "Util_Util", "coreOrchestrate→utilCompute/utilScale"),
    ("Lib",  "Core_Core", "Lib_Lib",   "Core is caller — must appear in Lib's diagram"),
    ("Lib",  "Lib_Lib",   "Util_Util", "libNormalize→utilCompute"),
    ("Util", "Core_Core", "Util_Util", "Core is caller — must appear in Util's diagram"),
    ("Util", "Lib_Lib",   "Util_Util", "Lib is caller — must appear in Util's diagram"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mmd_files(run_pipeline):
    """Dict of short unit name → .mmd content.
    Fails immediately with a clear message if any expected file is missing,
    so downstream tests don't produce confusing KeyError failures.
    """
    result = {}
    missing = []
    for name, safe in UNITS.items():
        path = os.path.join(UNIT_DIAGRAMS_DIR, f"{safe}.mmd")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                result[name] = f.read()
        else:
            missing.append(f"{safe}.mmd")
    if missing:
        pytest.fail(f"Missing unit diagram file(s): {missing}")
    return result


# ---------------------------------------------------------------------------
# File presence
# ---------------------------------------------------------------------------

def test_expected_mmd_files_exist(run_pipeline):
    missing = [
        f"{safe}.mmd"
        for name, safe in UNITS.items()
        if not os.path.isfile(os.path.join(UNIT_DIAGRAMS_DIR, f"{safe}.mmd"))
    ]
    assert not missing, f"Missing unit diagram files: {missing}"


# ---------------------------------------------------------------------------
# Mermaid format
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", UNITS)
def test_flowchart_direction_is_lr(mmd_files, unit):
    assert "flowchart LR" in mmd_files[unit]


@pytest.mark.parametrize("unit", UNITS)
def test_subgraph_present(mmd_files, unit):
    assert "subgraph internal_mod" in mmd_files[unit]


@pytest.mark.parametrize("unit", UNITS)
def test_subgraph_label_matches_module(mmd_files, unit):
    """The subgraph must be labelled with the unit's own module name."""
    assert f"subgraph internal_mod[{unit}]" in mmd_files[unit]


# ---------------------------------------------------------------------------
# Styling — main unit vs peers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit,node_id", UNITS.items())
def test_main_unit_has_main_unit_class(mmd_files, unit, node_id):
    assert f"class {node_id} mainUnit" in mmd_files[unit], (
        f"{unit} diagram: '{node_id}' should be marked mainUnit"
    )


@pytest.mark.parametrize("unit,peer_id", [
    ("Core", "Lib_Lib"),
    ("Core", "Util_Util"),
    ("Lib",  "Core_Core"),
    ("Lib",  "Util_Util"),
    ("Util", "Core_Core"),
    ("Util", "Lib_Lib"),
])
def test_peer_not_styled_as_main_unit(mmd_files, unit, peer_id):
    """Peer nodes must not carry the mainUnit class."""
    assert f"class {peer_id} mainUnit" not in mmd_files[unit], (
        f"{unit} diagram: peer '{peer_id}' should not be mainUnit"
    )


# ---------------------------------------------------------------------------
# Cross-module edges — topology and label format
#
# Each graph edge must appear in both the source and target unit's diagram,
# labeled with an interfaceId (IF_ prefix).  Two assertions per case:
#   1. The edge line exists (topology is correct)
#   2. The label uses IF_ format (not a raw function name)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("diagram,src,dst,reason", CROSS_MODULE_EDGES)
def test_cross_module_edge_with_if_label(mmd_files, diagram, src, dst, reason):
    lines = mmd_files[diagram].splitlines()
    edge_lines = [l for l in lines if src in l and dst in l and "-->" in l]
    assert edge_lines, (
        f"{diagram} diagram: missing edge {src} --> {dst}\n  ({reason})"
    )
    assert any("IF_" in l for l in edge_lines), (
        f"{diagram} diagram: edge {src} --> {dst} must carry an IF_... interfaceId label"
    )


# ---------------------------------------------------------------------------
# Direction invariants (negative)
# ---------------------------------------------------------------------------

def test_util_never_initiates_cross_module_call(mmd_files):
    """Util has no outgoing cross-module calls — Util_Util must never be an edge source."""
    bad = [l.strip() for l in mmd_files["Util"].splitlines() if "Util_Util -->" in l]
    assert not bad, f"Util_Util should not initiate calls, found: {bad}"


def test_core_has_no_incoming_cross_module_callers(mmd_files):
    """Nothing in the Sample group calls Core — Core_Core must never be an edge target."""
    bad = [l.strip() for l in mmd_files["Core"].splitlines() if "--> Core_Core" in l]
    assert not bad, f"Core_Core should have no incoming edges, found: {bad}"


# ---------------------------------------------------------------------------
# Snapshot — full .mmd content for all units
# ---------------------------------------------------------------------------

def test_snapshot(mmd_files, assert_snapshot, llm_summarize_off):
    assert_snapshot(mmd_files, "Sample/unit_diagrams.json")
