"""Unit tests for architecture_layers -> config.json layers conversion.

Covers _convert_layers / _component_paths_from_files in
api.services.pipeline_runner: the wizard's per-file/per-folder selection must be
preserved verbatim (relative to the layer path) rather than collapsed to a
common-ancestor directory.  Regression guard for punch-list Task 6.

Mark: unit (pure function, no I/O)
"""
import pytest

from api.services.pipeline_runner import _convert_layers, _component_paths_from_files

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _component_paths_from_files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("files, layer_path, expected", [
    # Multi-directory selection (the reported bug): must NOT collapse to "".
    (["Layer1/Flow/Flowcharts.cpp", "Layer1/Flow/Flowcharts.h",
      "Layer1/Math/Utils.cpp", "Layer1/Math/Utils.h"], "Layer1",
     ["Flow/Flowcharts.cpp", "Flow/Flowcharts.h", "Math/Utils.cpp", "Math/Utils.h"]),
    # Single file / single folder.
    (["Layer1/Flow/Flowcharts.cpp"], "Layer1", ["Flow/Flowcharts.cpp"]),
    (["Layer1/Sample/Core"], "Layer1", ["Sample/Core"]),
    # Multiple folders preserved as a list (no collapsing).
    (["Layer1/Direction", "Layer1/Types", "Layer1/Flow"], "Layer1",
     ["Direction", "Types", "Flow"]),
    # File directly under the layer root.
    (["Layer1/Main.cpp"], "Layer1", ["Main.cpp"]),
    # Backslashes, leading "./", and duplicates are normalized away.
    ([".\\Layer1\\Math\\Utils.cpp", "Layer1/Math/Utils.cpp"], "Layer1",
     ["Math/Utils.cpp"]),
    # Trailing slashes on the entry and the layer path.
    (["Layer1/Sample/Core/"], "Layer1/", ["Sample/Core"]),
    # Multi-segment layer path is stripped wholesale.
    (["App/Sample/Core/Core.cpp"], "App/Sample", ["Core/Core.cpp"]),
    # Whole-layer selection and empties yield nothing.
    (["Layer1"], "Layer1", []),
    ([], "Layer1", []),
    (["", None, "   "], "Layer1", []),
    # Entry outside the layer is kept as-is (defensive).
    (["OtherLayer/Foo.cpp"], "Layer1", ["OtherLayer/Foo.cpp"]),
])
def test_component_paths_from_files(files, layer_path, expected):
    assert _component_paths_from_files(files, layer_path) == expected


def test_order_preserved_and_deduped():
    files = ["Layer1/B.cpp", "Layer1/A.cpp", "Layer1/B.cpp", "Layer1/C.cpp"]
    assert _component_paths_from_files(files, "Layer1") == ["B.cpp", "A.cpp", "C.cpp"]


# ---------------------------------------------------------------------------
# _convert_layers — end-to-end shape
# ---------------------------------------------------------------------------

def test_convert_layers_bug_case_emits_file_list():
    arch = [{
        "name": "LAYER1", "path": "Layer1", "lib_paths": [],
        "groups": [{"name": "SampleGroupName", "components": [{
            "name": "ComponentName",
            "files": ["Layer1/Flow/Flowcharts.cpp", "Layer1/Flow/Flowcharts.h",
                      "Layer1/Math/Utils.cpp", "Layer1/Math/Utils.h"],
        }]}],
    }]
    assert _convert_layers(arch) == {
        "LAYER1": {"path": "Layer1", "groups": {"SampleGroupName": {
            "ComponentName": ["Flow/Flowcharts.cpp", "Flow/Flowcharts.h",
                              "Math/Utils.cpp", "Math/Utils.h"],
        }}},
    }


def test_convert_layers_single_path_is_string_multi_is_list():
    arch = [{
        "name": "L1", "path": "Layer1",
        "groups": [{"name": "G1", "components": [
            {"name": "Single", "files": ["Layer1/Sample/Core"]},
            {"name": "Multi", "files": ["Layer1/Direction", "Layer1/Types"]},
        ]}],
    }]
    groups = _convert_layers(arch)["L1"]["groups"]["G1"]
    assert groups["Single"] == "Sample/Core"           # one entry -> str
    assert groups["Multi"] == ["Direction", "Types"]   # many -> list


def test_convert_layers_empty_files_falls_back_to_component_name():
    arch = [{
        "name": "L1", "path": "Layer1",
        "groups": [{"name": "G1", "components": [{"name": "Empty", "files": []}]}],
    }]
    assert _convert_layers(arch)["L1"]["groups"]["G1"] == {"Empty": "Empty"}


def test_convert_layers_bare_string_component():
    arch = [{"name": "L1", "path": "Layer1",
             "groups": [{"name": "G1", "components": ["JustAName"]}]}]
    assert _convert_layers(arch)["L1"]["groups"]["G1"] == {"JustAName": "JustAName"}


def test_convert_layers_skips_unnamed_layer_and_path_defaults_to_name():
    arch = [
        {"name": "", "path": "X", "groups": []},          # dropped (no name)
        {"name": "L2", "groups": []},                     # path defaults to name
    ]
    out = _convert_layers(arch)
    assert "" not in out
    assert out["L2"]["path"] == "L2"
