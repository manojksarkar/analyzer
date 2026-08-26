"""Tests for the unitDiagrams view (output/<group>/unit_diagrams/*.mmd).

Logical tests only — no snapshots. Checks:
- Mermaid format and structure (flowchart LR, module subgraph, styling)
- Interface topology: each unit diagram shows the unit's interface *consumers*
  (the units that call into it), split by direction, with an interfaceId (IF_)
  label on every edge (3.6 / 3.15: keep callers, orient by owner direction)

Interface partners for the "My Sample" group (from SampleCppProject source),
i.e. who consumes each unit's interfaces:
  Core ← App/Main, Cross/Hub                     (external callers only)
  Lib  ← Core, App/Main, Cross/Hub
  Util ← Core, Lib, App/Main, Cross/Hub

Core, Lib and Util belong to the "My Sample" group; a partner drawn inside the
component subgraph is "internal", one drawn outside it (App/Main, Cross/Hub) is
external. Core is not called by Lib or Util, so neither appears in its diagram.
"""
import os

import pytest

pytestmark = pytest.mark.e2e

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from tests.e2e_paths import COMPONENTS, output_for   # noqa: E402
# Diagrams land under each component now, not under one group directory.
UNIT_DIAGRAM_DIRS = [_os.path.join(output_for(c), "unit_diagrams") for c in COMPONENTS]
UNIT_DIAGRAMS_DIR = next((d for d in UNIT_DIAGRAM_DIRS if _os.path.isdir(d)),
                        UNIT_DIAGRAM_DIRS[0])


def _mmd_path(safe):
    """Where that unit's diagram is, across the component directories.

    One directory per component now, where a group-scoped run once had a single one
    for the whole group -- so looking in only the first sees only its units. Returns
    the first match, or the first candidate path so failure messages stay readable.
    """
    cands = [_os.path.join(d, safe + ".mmd") for d in UNIT_DIAGRAM_DIRS]
    return next((c for c in cands if _os.path.isfile(c)), cands[0])

# short unit name  →  safe_filename (== the main-unit node id)
#   unit_key "Sample Core|Core" → safe_filename → "Sample-Core_Core"
UNITS = {
    "Core": "Sample-Core_Core",
    "Lib":  "Lib_Lib",
    "Util": "Util_Util",
}

# subgraph label = the unit's component display name (config group component)
SUBGRAPH_LABELS = {
    "Core": "Sample Core",
    "Lib":  "Lib",
    "Util": "Util",
}

# Partner nodes that MUST appear in each unit's diagram (its interface consumers).
EXPECTED_PARTNERS = {
    "Core": {"App_Main", "Cross_Hub"},
    "Lib":  {"Sample-Core_Core", "App_Main", "Cross_Hub"},
    "Util": {"Sample-Core_Core", "Lib_Lib", "App_Main", "Cross_Hub"},
}

# Partner nodes that MUST NOT appear (units that do not consume the main unit).
ABSENT_PARTNERS = {
    "Core": {"Lib_Lib", "Util_Util"},   # Lib/Util never call Core
    "Lib":  {"Util_Util"},              # Util does not call Lib's interface here
    "Util": set(),
}


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
        path = _mmd_path(safe)
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
        if not os.path.isfile(_mmd_path(safe))
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
def test_subgraph_label_matches_component(mmd_files, unit):
    """The subgraph is labelled with the unit's component display name."""
    label = SUBGRAPH_LABELS[unit]
    assert f'subgraph internal_mod["{label}"]' in mmd_files[unit], (
        f"{unit} diagram: subgraph should be labelled '{label}'"
    )


# ---------------------------------------------------------------------------
# Styling — main unit vs peers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit,node_id", UNITS.items())
def test_main_unit_has_main_unit_class(mmd_files, unit, node_id):
    assert f"class {node_id} mainUnit" in mmd_files[unit], (
        f"{unit} diagram: '{node_id}' should be marked mainUnit"
    )


@pytest.mark.parametrize("unit,peer_id", [
    (unit, peer)
    for unit, peers in EXPECTED_PARTNERS.items()
    for peer in peers
])
def test_peer_not_styled_as_main_unit(mmd_files, unit, peer_id):
    """Partner nodes must not carry the mainUnit class."""
    assert f"class {peer_id} mainUnit" not in mmd_files[unit], (
        f"{unit} diagram: peer '{peer_id}' should not be mainUnit"
    )


# ---------------------------------------------------------------------------
# Interface topology — consumers present / non-consumers absent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit,partner", [
    (unit, partner)
    for unit, partners in EXPECTED_PARTNERS.items()
    for partner in partners
])
def test_expected_partner_present(mmd_files, unit, partner):
    """Every interface consumer of the unit must appear as a node in its diagram."""
    assert partner in mmd_files[unit], (
        f"{unit} diagram: expected interface partner '{partner}' is missing"
    )


@pytest.mark.parametrize("unit,partner", [
    (unit, partner)
    for unit, partners in ABSENT_PARTNERS.items()
    for partner in partners
])
def test_non_consumer_absent(mmd_files, unit, partner):
    """A unit that does not consume the main unit's interface must not be drawn."""
    assert partner not in mmd_files[unit], (
        f"{unit} diagram: '{partner}' does not consume {unit} and should be absent"
    )


# ---------------------------------------------------------------------------
# Every cross-unit edge carries an interfaceId (IF_) label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", UNITS)
def test_every_edge_has_if_label(mmd_files, unit):
    edge_lines = [l for l in mmd_files[unit].splitlines() if "-->" in l]
    assert edge_lines, f"{unit} diagram has no edges"
    unlabelled = [l.strip() for l in edge_lines if "IF_" not in l]
    assert not unlabelled, (
        f"{unit} diagram: edges without an IF_... interfaceId label: {unlabelled}"
    )


# ---------------------------------------------------------------------------
# Snapshot — full .mmd content for all units
# ---------------------------------------------------------------------------

def test_snapshot(mmd_files, assert_snapshot, llm_summarize_off):
    assert_snapshot(mmd_files, "Sample/unit_diagrams.json")
