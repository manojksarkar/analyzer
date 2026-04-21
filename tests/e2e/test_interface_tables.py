"""Tests for the interface_tables view (output/interface_tables.json).

Checks:
- JSON structure: unitNames, entries per unit, required fields
- Filtering: private functions and private globals excluded
- Direction: Out for read-only functions, In for write functions, In/Out for globals
- Values: interfaceId prefix, entry types
- Snapshot: full file matches golden
"""
import copy

import pytest

pytestmark = pytest.mark.e2e

REQUIRED_ENTRY_FIELDS = {"interfaceId", "type", "name", "unitKey", "unitName", "direction"}
FUNCTION_REQUIRED_FIELDS = REQUIRED_ENTRY_FIELDS | {"functionId"}

PRIVATE_FUNCTIONS = {
    "coreHelper", "coreSwitch",   # PRIVATE in Core
    "libClamp",                   # PRIVATE in Lib
    "utilClip",                   # PRIVATE in Util
}

PRIVATE_GLOBALS = {
    "g_count",                    # PRIVATE in Core
}


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_unit_names_present(interface_tables):
    assert "unitNames" in interface_tables


def test_expected_units_present(interface_tables):
    for key in ("Core|Core", "Lib|Lib", "Util|Util"):
        assert key in interface_tables, f"Unit '{key}' missing from interface_tables"


def test_unit_names_map(interface_tables):
    assert interface_tables["unitNames"]["Core|Core"] == "Core"
    assert interface_tables["unitNames"]["Lib|Lib"] == "Lib"
    assert interface_tables["unitNames"]["Util|Util"] == "Util"


@pytest.mark.parametrize("entries_fixture,unit", [
    ("core_entries", "Core"),
    ("lib_entries", "Lib"),
    ("util_entries", "Util"),
])
def test_unit_has_entries(request, entries_fixture, unit):
    entries = request.getfixturevalue(entries_fixture)
    assert len(entries) > 0, f"{unit} has no entries"


def test_required_fields_present(all_entries):
    for entry in all_entries:
        required = FUNCTION_REQUIRED_FIELDS if entry.get("type") == "Function" else REQUIRED_ENTRY_FIELDS
        missing = required - set(entry.keys())
        assert not missing, f"Entry '{entry.get('name')}' missing fields: {missing}"


def test_interface_ids_start_with_IF(all_entries):
    for entry in all_entries:
        assert entry["interfaceId"].startswith("IF_"), (
            f"Bad interfaceId for '{entry['name']}': {entry['interfaceId']}"
        )


def test_entry_types_valid(all_entries):
    valid_types = {"Function", "Global Variable"}
    for entry in all_entries:
        assert entry["type"] in valid_types, (
            f"Unexpected type '{entry['type']}' for '{entry['name']}'"
        )


# ---------------------------------------------------------------------------
# Filtering — private items must be excluded
# ---------------------------------------------------------------------------

def test_private_functions_excluded(all_entries):
    names = {e["name"] for e in all_entries}
    for name in PRIVATE_FUNCTIONS:
        assert name not in names, f"Private function '{name}' leaked into interface table"


def test_private_globals_excluded(core_entries):
    global_names = {e["name"] for e in core_entries if e["type"] == "Global Variable"}
    for name in PRIVATE_GLOBALS:
        assert name not in global_names, f"Private global '{name}' leaked into interface table"


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected_direction,entries_fixture", [
    ("coreGetCount",  "Out", "core_entries"),
    ("coreSetResult", "In",  "core_entries"),
    ("utilCompute",   "Out", "util_entries"),
])
def test_function_direction(request, name, expected_direction, entries_fixture):
    entries = request.getfixturevalue(entries_fixture)
    entry = next((e for e in entries if e["name"] == name), None)
    assert entry is not None, f"'{name}' not found in entries"
    assert entry["direction"] == expected_direction, (
        f"'{name}' direction should be {expected_direction}, got {entry['direction']}"
    )


def test_function_direction_values_valid(all_entries):
    for entry in all_entries:
        if entry["type"] == "Function":
            assert entry["direction"] in ("In", "Out"), (
                f"Function '{entry['name']}' has invalid direction: {entry['direction']}"
            )


def test_global_variable_direction_is_inout(core_entries, util_entries):
    for entry in core_entries + util_entries:
        if entry["type"] == "Global Variable":
            assert entry["direction"] == "In/Out", (
                f"Global '{entry['name']}' should be In/Out, got {entry['direction']}"
            )


# ---------------------------------------------------------------------------
# Specific entries present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entries_fixture,expected,unit", [
    ("core_entries", {"coreAdd", "coreCompute", "coreLoopSum", "coreCheck",
                      "coreSumPoint", "coreSetResult", "coreProcess",
                      "coreOrchestrate", "coreSetMode", "coreGetCount"}, "Core"),
    ("lib_entries",  {"libAdd", "libNormalize"},                          "Lib"),
    ("util_entries", {"utilCompute", "utilScale"},                        "Util"),
])
def test_public_functions_present(request, entries_fixture, expected, unit):
    entries = request.getfixturevalue(entries_fixture)
    names = {e["name"] for e in entries if e["type"] == "Function"}
    missing = expected - names
    assert not missing, f"Public functions missing from {unit}: {missing}"


@pytest.mark.parametrize("entries_fixture,global_name,unit", [
    ("core_entries", "g_result",   "Core"),
    ("util_entries", "g_utilBase", "Util"),
])
def test_public_global_present(request, entries_fixture, global_name, unit):
    entries = request.getfixturevalue(entries_fixture)
    names = {e["name"] for e in entries if e["type"] == "Global Variable"}
    assert global_name in names, f"PUBLIC global {global_name} missing from {unit} entries"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def _normalize(data):
    out = copy.deepcopy(data)
    for unit_key, unit in out.items():
        if unit_key == "unitNames":
            continue
        for entry in unit.get("entries", []):
            loc = entry.get("location", {})
            if "file" in loc:
                loc["file"] = loc["file"].replace("\\", "/")
    return out


def test_snapshot(interface_tables, assert_snapshot, llm_descriptions_off, llm_behaviour_names_off):
    assert_snapshot(_normalize(interface_tables), "Sample/interface_tables.json")
