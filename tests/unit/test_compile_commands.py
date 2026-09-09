"""compile_commands.json -> layer include paths.

The fixture below is a trimmed copy of a real client database (armclang, SAVONA
flash firmware): mixed `/` and `\\` separators in the same entry, a response
file, and a `directory` on a build machine that does not exist locally.
"""
import json
import os

import pytest

from engine.core import compile_commands as cc


BUILD_DIR = "D:\\workspace\\BA190_0\\01_SRC\\02_HIL\\01_BUILD\\SAVONA\\DS5"
SRC_ROOT = "D:/workspace/BA190_0/01_SRC"


def _entry(file_name, includes, directory=BUILD_DIR):
    """One database entry with the real flag soup around the include paths."""
    args = [
        "armclang",
        "-D__CONTROLLER_TARGET__=37",
        "-D_NAND_DENSITY=512",
        "-D_CONFIG_ASIC",
        "-Werror",
        "@./WARNING_GUIDE/warnings_for_release.txt",
        "-Wno-bitfield-enum-conversion",
        "-xc++",
        "-std=c++14",
        "--target=arm-arm-none-eabi",
        "-mcpu=cortex-m7",
        "-mfpu=none",
        "-Oz",
        "-c",
    ]
    args += [f"-I{inc}" for inc in includes]
    args += ["-o", "ASIC_CM_OBJECT\\BootLoader_Init.o"]
    return {"directory": directory, "file": file_name, "arguments": args}


def _write_db(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


def _make_tree(root, *rel_dirs):
    for rel in rel_dirs:
        os.makedirs(os.path.join(str(root), *rel.split("/")), exist_ok=True)


# ---------------------------------------------------------------------------
# include_args - include flags only
# ---------------------------------------------------------------------------

def test_include_args_takes_joined_and_separate_forms():
    args = ["armclang", "-I../foo", "-I", "../bar", "-isystem/sys/inc", "-iquote", "q/inc"]
    assert cc.include_args(args) == ["../foo", "../bar", "/sys/inc", "q/inc"]


def test_include_args_drops_everything_that_is_not_an_include():
    args = ["armclang", "-D_CONFIG_ASIC", "-Werror", "@./WARNING_GUIDE/w.txt",
            "-Oz", "-c", "-o", "out.o", "--target=arm-arm-none-eabi", "-I../keep"]
    assert cc.include_args(args) == ["../keep"]


def test_include_args_ignores_a_trailing_flag_with_no_operand():
    assert cc.include_args(["armclang", "-I../keep", "-I"]) == ["../keep"]


# ---------------------------------------------------------------------------
# Resolution against each entry's own `directory`
# ---------------------------------------------------------------------------

def test_relative_includes_resolve_against_the_entry_directory():
    entries = [_entry("../../../../04_FIL/x.cpp",
                      ["../../../../04_FIL/02_Src_Product/03_Ucf/FlashDriver/Driver/Io"])]
    assert cc.entry_include_dirs(entries) == [
        f"{SRC_ROOT}/04_FIL/02_Src_Product/03_Ucf/FlashDriver/Driver/Io"
    ]


def test_backslash_includes_resolve_the_same_as_forward_slash():
    entries = [_entry("x.cpp", ["..\\..\\05_CTRL\\01.SFR\\MMAP"])]
    assert cc.entry_include_dirs(entries) == [
        "D:/workspace/BA190_0/01_SRC/02_HIL/01_BUILD/05_CTRL/01.SFR/MMAP"
    ]


def test_absolute_includes_are_not_joined_to_the_directory():
    entries = [_entry("x.cpp", ["D:/elsewhere/inc", "/opt/inc"])]
    assert cc.entry_include_dirs(entries) == ["D:/elsewhere/inc", "/opt/inc"]


def test_include_dirs_are_deduped_across_entries_in_first_seen_order():
    shared = "../../../../04_FIL/00_NBuild"
    entries = [_entry("a.cpp", [shared, "../../../../04_FIL/01_Src_Core"]),
               _entry("b.cpp", ["../../../../04_FIL/02_Service", shared])]
    assert cc.entry_include_dirs(entries) == [
        f"{SRC_ROOT}/04_FIL/00_NBuild",
        f"{SRC_ROOT}/04_FIL/01_Src_Core",
        f"{SRC_ROOT}/04_FIL/02_Service",
    ]


def test_legacy_command_string_entries_are_read():
    entries = [{"directory": BUILD_DIR, "file": "x.cpp",
                "command": "armclang -c -I../../../../04_FIL/00_NBuild x.cpp"}]
    assert cc.entry_include_dirs(entries) == [f"{SRC_ROOT}/04_FIL/00_NBuild"]


def test_entries_without_a_directory_are_skipped(tmp_path):
    db = _write_db(tmp_path / "cc.json",
                   [{"file": "x.cpp", "arguments": ["armclang"]}, _entry("y.cpp", [])])
    assert len(cc.read_entries(db)) == 1


# ---------------------------------------------------------------------------
# Root prefix derivation
# ---------------------------------------------------------------------------

def test_derive_strips_the_build_machine_prefix(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product/03_Ucf/FlashDriver/Driver/Io")
    dirs = [f"{SRC_ROOT}/04_FIL/02_Src_Product/03_Ucf/FlashDriver/Driver/Io"]

    root = cc.derive_root_prefix(dirs, str(tmp_path))

    assert root is not None
    assert root.prefix == SRC_ROOT
    assert root.derived is True
    assert root.votes == 1


def test_derive_prefers_the_deepest_remainder(tmp_path):
    # `04_FIL` exists at both depths locally. Matching the longer tail is the
    # safer read: a short folder name colliding by accident is common.
    _make_tree(tmp_path, "04_FIL", "01_SRC/04_FIL/02_Src_Product")
    dirs = [f"{SRC_ROOT}/04_FIL/02_Src_Product"]

    root = cc.derive_root_prefix(dirs, str(tmp_path))

    assert root.prefix == "D:/workspace/BA190_0"


def test_derive_takes_the_majority_prefix(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product", "04_FIL/01_Src_Core", "04_FIL/05_Hardware")
    dirs = [f"{SRC_ROOT}/04_FIL/02_Src_Product",
            f"{SRC_ROOT}/04_FIL/01_Src_Core",
            f"{SRC_ROOT}/04_FIL/05_Hardware",
            "E:/other_build/04_FIL/02_Src_Product"]

    root = cc.derive_root_prefix(dirs, str(tmp_path))

    assert root.prefix == SRC_ROOT
    assert root.votes == 3
    assert root.total == 4
    assert root.share == pytest.approx(0.75)


def test_derive_returns_none_when_nothing_resolves_locally(tmp_path):
    assert cc.derive_root_prefix([f"{SRC_ROOT}/04_FIL/nope"], str(tmp_path)) is None


def test_derive_is_stable_across_runs(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product", "05_CTRL/01.SFR")
    dirs = [f"{SRC_ROOT}/04_FIL/02_Src_Product", f"{SRC_ROOT}/05_CTRL/01.SFR"]

    first = cc.derive_root_prefix(dirs, str(tmp_path))
    second = cc.derive_root_prefix(dirs, str(tmp_path))

    assert (first.prefix, first.votes) == (second.prefix, second.votes)


# ---------------------------------------------------------------------------
# Applying the prefix
# ---------------------------------------------------------------------------

def test_apply_splits_kept_unmapped_and_missing(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product")
    dirs = [f"{SRC_ROOT}/04_FIL/02_Src_Product",   # kept
            f"{SRC_ROOT}/04_FIL/03_Gone",          # mapped, not on disk
            "E:/third_party/inc"]                  # never had the prefix

    kept, unmapped, missing = cc.apply_root_prefix(dirs, SRC_ROOT, str(tmp_path))

    assert kept == [cc.normalize(os.path.join(str(tmp_path), "04_FIL/02_Src_Product"))]
    assert missing == [cc.normalize(os.path.join(str(tmp_path), "04_FIL/03_Gone"))]
    assert unmapped == ["E:/third_party/inc"]


# ---------------------------------------------------------------------------
# load_sources - cores to layers
# ---------------------------------------------------------------------------

def test_cores_sharing_a_layer_concatenate_and_dedupe(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product", "04_FIL/01_Src_Core", "05_CTRL/01.SFR")
    shared = "../../../../04_FIL/02_Src_Product"
    fcore = _write_db(tmp_path / "fcore.json", [_entry("a.cpp", [shared, "../../../../04_FIL/01_Src_Core"])])
    hcore = _write_db(tmp_path / "hcore.json", [_entry("b.cpp", [shared, "../../../../05_CTRL/01.SFR"])])

    by_layer, reports = cc.load_sources(
        [cc.CoreSource("FCore", fcore, "Layer1"), cc.CoreSource("HCore", hcore, "Layer1")],
        str(tmp_path))

    assert list(by_layer) == ["Layer1"]
    assert [os.path.basename(d) for d in by_layer["Layer1"]] == [
        "02_Src_Product", "01_Src_Core", "01.SFR"]
    assert [r.core for r in reports] == ["FCore", "HCore"]


def test_cores_in_different_layers_stay_separate(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product", "05_CTRL/01.SFR")
    fcore = _write_db(tmp_path / "fcore.json", [_entry("a.cpp", ["../../../../04_FIL/02_Src_Product"])])
    ncore = _write_db(tmp_path / "ncore.json", [_entry("b.cpp", ["../../../../05_CTRL/01.SFR"])])

    by_layer, _ = cc.load_sources(
        [cc.CoreSource("FCore", fcore, "Layer1"), cc.CoreSource("NCore", ncore, "Layer2")],
        str(tmp_path))

    assert [os.path.basename(d) for d in by_layer["Layer1"]] == ["02_Src_Product"]
    assert [os.path.basename(d) for d in by_layer["Layer2"]] == ["01.SFR"]


def test_a_configured_root_prefix_skips_derivation(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product")
    db = _write_db(tmp_path / "cc.json", [_entry("a.cpp", ["../../../../04_FIL/02_Src_Product"])])

    _, reports = cc.load_sources(
        [cc.CoreSource("FCore", db, "Layer1", root_prefix=SRC_ROOT)], str(tmp_path))

    assert reports[0].root_prefix.derived is False
    assert reports[0].kept_dirs == 1


def test_an_unreadable_database_is_skipped_not_fatal(tmp_path):
    _make_tree(tmp_path, "04_FIL/02_Src_Product")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    good = _write_db(tmp_path / "cc.json", [_entry("a.cpp", ["../../../../04_FIL/02_Src_Product"])])

    by_layer, reports = cc.load_sources(
        [cc.CoreSource("Bad", str(bad), "Layer1"), cc.CoreSource("FCore", good, "Layer1")],
        str(tmp_path))

    assert reports[0].entries == 0
    assert len(by_layer["Layer1"]) == 1


def test_a_database_that_resolves_to_nothing_contributes_no_dirs(tmp_path):
    db = _write_db(tmp_path / "cc.json", [_entry("a.cpp", ["../../../../04_FIL/absent"])])

    by_layer, reports = cc.load_sources([cc.CoreSource("FCore", db, "Layer1")], str(tmp_path))

    assert by_layer == {}
    assert reports[0].root_prefix is None


# ---------------------------------------------------------------------------
# Config reading
# ---------------------------------------------------------------------------

def test_a_core_takes_its_layer_from_the_layer_that_names_it():
    cfg = {"cores": {"Core1": {"compileCommands": "build/core1/cc.json"}},
           "layers": {"Layer1": {"cores": ["Core1"]}}}
    sources = cc.sources_from_layers(cfg, "C:/proj")

    assert sources[0].core == "Core1"
    assert sources[0].layer == "Layer1"
    assert sources[0].path == "C:/proj/build/core1/cc.json"


def test_cores_are_emitted_in_layer_then_declaration_order():
    """Reproducible merge order - the include list depends on it."""
    cfg = {"cores": {"Core1": {"compileCommands": "a.json"},
                     "Core2": {"compileCommands": "b.json"},
                     "Core3": {"compileCommands": "c.json"}},
           "layers": {"Layer1": {"cores": ["Core1", "Core2"]},
                      "Layer2": {"cores": ["Core3"]}}}

    assert [(s.core, s.layer) for s in cc.sources_from_layers(cfg, "C:/proj")] == [
        ("Core1", "Layer1"), ("Core2", "Layer1"), ("Core3", "Layer2")]


def test_the_object_form_carries_a_root_prefix_override():
    cfg = {"cores": {"Core1": {"compileCommands": {"file": "f.json",
                                                   "rootPrefix": "D:/build/src"}}},
           "layers": {"Layer1": {"cores": ["Core1"]}}}
    source = cc.sources_from_layers(cfg, "C:/proj")[0]

    assert source.path == "C:/proj/f.json"
    assert source.root_prefix == "D:/build/src"


def test_a_core_without_a_database_contributes_nothing():
    """A core may declare only macros and a dictionary."""
    cfg = {"cores": {"Core1": {"macros": "m.json"}, "Core2": {"compileCommands": "c.json"}},
           "layers": {"Layer1": {"cores": ["Core1", "Core2"]}}}
    assert [s.core for s in cc.sources_from_layers(cfg, "C:/proj")] == ["Core2"]


def test_a_layer_naming_no_cores_contributes_nothing():
    cfg = {"cores": {"Core1": {"compileCommands": "c.json"}},
           "layers": {"Layer1": {"path": "Layer1", "cores": []}}}
    assert cc.sources_from_layers(cfg, "C:/proj") == []
    assert cc.sources_from_layers({}, "C:/proj") == []


# ---------------------------------------------------------------------------
# The shipped example databases
# ---------------------------------------------------------------------------

def test_the_example_databases_resolve_against_sample_cpp_project():
    """The shipped `engine/config/compile_commands.*.example.json` still load.

    Reads the real `cores` / `layers.*.cores` wiring rather than a hand-built
    config, so `config.defaults.json` itself is what is under test. Their include
    paths point into the real `SampleCppProject` tree, so if that fixture is
    restructured and the examples are not updated, derivation quietly finds nothing.
    """
    from engine.core.config import app_config

    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sources = cc.sources_from_layers(app_config(), repo)
    assert [(s.core, s.layer) for s in sources] == [("Core1", "Layer1"), ("Core2", "Layer2")]
    by_layer, reports = cc.load_sources(sources, os.path.join(repo, "SampleCppProject"))

    for report in reports:
        assert report.entries > 0, f"{report.core} contributed no entries"
        assert report.root_prefix is not None, f"{report.core} derived no root prefix"
        assert report.root_prefix.prefix.endswith("01_SRC")
        assert report.kept_dirs > 0

    assert sorted(by_layer) == ["Layer1", "Layer2"]
    for dirs in by_layer.values():
        assert len(dirs) == len(set(dirs))
    assert any(d.endswith("Layer1/Types") for d in by_layer["Layer1"])


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def test_report_warns_when_the_prefix_has_weak_agreement():
    report = cc.LoadReport(core="FCore", layer="Layer1", entries=10, raw_dirs=10, kept_dirs=4,
                           root_prefix=cc.RootPrefix(prefix=SRC_ROOT, votes=4, total=10))
    text = "\n".join(cc.format_report(report))

    assert "WARNING" in text
    assert "40%" in text


def test_report_is_quiet_when_the_prefix_is_solid():
    report = cc.LoadReport(core="FCore", layer="Layer1", entries=10, raw_dirs=10, kept_dirs=10,
                           root_prefix=cc.RootPrefix(prefix=SRC_ROOT, votes=10, total=10))
    assert "WARNING" not in "\n".join(cc.format_report(report))
