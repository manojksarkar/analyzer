"""Interface tables view tests.

Covers every rule in docs/spec/SWE3_SPEC.md — Interface Tables section.
Update the spec first, then update these tests.
"""
import copy

import pytest

pytestmark = pytest.mark.e2e

REQUIRED_ENTRY_FIELDS = {
    "interfaceId", "type", "name", "unitKey", "unitName",
    "direction", "callerUnits", "calleesUnits",
}
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
# Unit inclusion (spec: only .cpp-backed units; module-scoped runs filter)
# ---------------------------------------------------------------------------

def test_expected_units_present(interface_tables):
    for key in ("Layer1.Sample-Core|Core", "Layer1.Lib|Lib", "Layer1.Util|Util"):
        assert key in interface_tables, f"Unit '{key}' missing from interface_tables"


def test_unit_names_present(interface_tables):
    assert "unitNames" in interface_tables


def test_unit_names_map(interface_tables):
    assert interface_tables["unitNames"]["Layer1.Sample-Core|Core"] == "Core"
    assert interface_tables["unitNames"]["Layer1.Lib|Lib"] == "Lib"
    assert interface_tables["unitNames"]["Layer1.Util|Util"] == "Util"


# ---------------------------------------------------------------------------
# Entry inclusion (spec: PUBLIC and PROTECTED in; PRIVATE out)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entries_fixture,unit", [
    ("core_entries", "Core"),
    ("lib_entries", "Lib"),
    ("util_entries", "Util"),
])
def test_unit_has_entries(request, entries_fixture, unit):
    entries = request.getfixturevalue(entries_fixture)
    assert len(entries) > 0, f"{unit} has no entries"


def test_private_functions_excluded(all_entries):
    names = {e["name"] for e in all_entries}
    for name in PRIVATE_FUNCTIONS:
        assert name not in names, f"PRIVATE function '{name}' leaked into interface table"


def test_private_globals_excluded(core_entries):
    global_names = {e["name"] for e in core_entries if e["type"] == "Global Variable"}
    for name in PRIVATE_GLOBALS:
        assert name not in global_names, f"PRIVATE global '{name}' leaked into interface table"


def test_protected_functions_excluded(core_entries):
    # coreGetCount is PROTECTED. A protected item is unreachable from another unit except
    # through inheritance, so it is not an interface: the parser records PROTECTED as
    # "private" and the row never reaches the table. Reverses the earlier reading of
    # REQ-IT-02, which asked for protected items to be listed.
    names = {e["name"] for e in core_entries if e["type"] == "Function"}
    assert "coreGetCount" not in names, "PROTECTED function 'coreGetCount' leaked into interface table"


@pytest.mark.parametrize("entries_fixture,expected,unit", [
    ("core_entries", {"coreAdd", "coreSetResult", "coreProcess",
                      "coreOrchestrate"},                                 "Core"),
    ("lib_entries",  {"libAdd", "libNormalize"},                          "Lib"),
    ("util_entries", {"utilCompute", "utilScale"},                        "Util"),
])
def test_public_functions_present(request, entries_fixture, expected, unit):
    entries = request.getfixturevalue(entries_fixture)
    names = {e["name"] for e in entries if e["type"] == "Function"}
    missing = expected - names
    assert not missing, f"PUBLIC functions missing from {unit}: {missing}"


# A global gets a row only when a function in ANOTHER unit reads or writes it (S3-7), the
# bar a function already meets with a caller. Both published ones are reached through an
# `extern`: g_sharedTick through the orphan SharedDefs.h (Lib reads it), g_utilBase through
# Util's own Util.h (Core's coreUtilBase reads it).
@pytest.mark.parametrize("entries_fixture,global_name,unit", [
    ("core_entries", "g_sharedTick", "Core"),
    ("util_entries", "g_utilBase",   "Util"),
])
def test_global_used_by_another_unit_present(request, entries_fixture, global_name, unit):
    entries = request.getfixturevalue(entries_fixture)
    names = {e["name"] for e in entries if e["type"] == "Global Variable"}
    assert global_name in names, f"global '{global_name}' missing from {unit} entries"


# PUBLIC-marked, but only their own unit touches them: a marking may restrict, never promote.
@pytest.mark.parametrize("entries_fixture,global_name,unit", [
    ("core_entries", "g_result",  "Core"),
    ("util_entries", "g_utilBuf", "Util"),
])
def test_global_used_only_by_its_own_unit_absent(request, entries_fixture, global_name, unit):
    entries = request.getfixturevalue(entries_fixture)
    names = {e["name"] for e in entries if e["type"] == "Global Variable"}
    assert global_name not in names, f"'{global_name}' has no user outside {unit}"


# ---------------------------------------------------------------------------
# Direction (spec: writes global→In; reads only→Out; no access→Out; globals→In/Out)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected_direction,entries_fixture", [
    # Writes a global — In
    ("coreSetResult", "In",  "core_entries"),
    # Reads a global, writes none — Out. coreGetCount used to cover this from Core;
    # it is PROTECTED, so it no longer has a table row to read a direction from.
    ("utilCompute",   "Out", "util_entries"),
    # No global access — Out
    ("coreAdd",       "Out", "core_entries"),
    ("libAdd",        "Out", "lib_entries"),
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


def test_global_variable_direction_is_inout(all_entries):
    for entry in all_entries:
        if entry["type"] == "Global Variable":
            assert entry["direction"] == "In/Out", (
                f"Global '{entry['name']}' should be In/Out, got {entry['direction']}"
            )


# ---------------------------------------------------------------------------
# Interface ID (spec: IF_<PROJ>_<GROUP>_<UNIT>_<NN>, uppercase letters + index)
# ---------------------------------------------------------------------------

def test_interface_ids_start_with_IF(all_entries):
    for entry in all_entries:
        assert entry["interfaceId"].startswith("IF_"), (
            f"Bad interfaceId for '{entry['name']}': {entry['interfaceId']}"
        )


def test_interface_id_segments_uppercase(all_entries):
    import re
    # Segments are uppercase alphanumeric (e.g. the layer segment 'LAYER1'),
    # followed by a numeric index: IF_<SEG>_<SEG>..._<NN>.
    pattern = re.compile(r"^IF(_[A-Z0-9]+)+_\d+$")
    for entry in all_entries:
        iid = entry["interfaceId"]
        assert pattern.match(iid), (
            f"interfaceId '{iid}' for '{entry['name']}' does not match IF_<UPPER>..._<NN>"
        )


# ---------------------------------------------------------------------------
# Caller / callee units (spec: callerUnits/calleesUnits include same-module;
# sourceDest lists every interacting unit except the function's own unit — REQ-IT-12)
# ---------------------------------------------------------------------------

def test_required_fields_present(all_entries):
    for entry in all_entries:
        required = FUNCTION_REQUIRED_FIELDS if entry.get("type") == "Function" else REQUIRED_ENTRY_FIELDS
        missing = required - set(entry.keys())
        assert not missing, f"Entry '{entry.get('name')}' missing fields: {missing}"


def test_entry_types_valid(all_entries):
    valid_types = {"Function", "Global Variable"}
    for entry in all_entries:
        assert entry["type"] in valid_types, (
            f"Unexpected type '{entry['type']}' for '{entry['name']}'"
        )


def test_global_entries_have_empty_caller_callee(all_entries):
    for entry in all_entries:
        if entry["type"] == "Global Variable":
            assert entry["callerUnits"] == [], (
                f"Global '{entry['name']}' callerUnits should be empty"
            )
            assert entry["calleesUnits"] == [], (
                f"Global '{entry['name']}' calleesUnits should be empty"
            )


def test_sourcedest_includes_cross_unit_callers(util_entries):
    # utilCompute and utilScale are called by the Core unit (a different unit, same group).
    # Per REQ-IT-12 the sourceDest lists every interacting unit except the function's own
    # unit, so the Core caller appears even though it is inside the group. The component-name
    # prefix varies with config ("Core/Core" vs "Sample-Core/Core"), so match the ".../Core" tail.
    for name in ("utilCompute", "utilScale"):
        entry = next((e for e in util_entries if e["name"] == name), None)
        assert entry is not None, f"'{name}' not found in util_entries"
        assert "/Core" in entry["sourceDest"], (
            f"'{name}' is called by the Core unit; sourceDest should include a '.../Core' unit, "
            f"got '{entry['sourceDest']}'"
        )


def test_caller_units_populated(core_entries):
    # coreAdd is called by App/Main and Cross/Hub (external)
    entry = next((e for e in core_entries if e["name"] == "coreAdd"), None)
    assert entry is not None
    assert len(entry["callerUnits"]) > 0, "coreAdd should have callerUnits"


def test_callee_units_populated(core_entries):
    # coreAdd calls libAdd — Lib|Lib should be in calleesUnits
    entry = next((e for e in core_entries if e["name"] == "coreAdd"), None)
    assert entry is not None
    assert "Layer1.Lib|Lib" in entry["calleesUnits"], "coreAdd should list Lib|Lib in calleesUnits"


# ---------------------------------------------------------------------------
# Sort order (spec: entries sorted by source line order)
# ---------------------------------------------------------------------------

def test_function_entries_sorted_by_line(core_entries):
    func_lines = [
        e["location"]["line"]
        for e in core_entries
        if e["type"] == "Function"
    ]
    assert func_lines == sorted(func_lines), "Function entries are not sorted by source line"


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
