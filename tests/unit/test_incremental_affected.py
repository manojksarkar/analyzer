"""Unit tests for narrowed-parse foundations (M4.1 affected-TU set + M4.2 parse fp)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental.affected import affected_tus, case_collisions, full_reparse_reason
from incremental.fingerprint import parse_fingerprint

# Closure map: Main.cpp includes Utils.h + Helper.h; Utils.cpp includes Utils.h; Lone.cpp none.
TU_INCLUDES = {
    "Layer1/App/Main.cpp": ["Layer1/Math/Utils.h", "Layer1/Outer/Helper.h"],
    "Layer1/Math/Utils.cpp": ["Layer1/Math/Utils.h"],
    "Layer1/App/Lone.cpp": [],
}


class TestAffectedTUs:
    def test_changed_cpp_itself(self):
        assert affected_tus(["Layer1/Math/Utils.cpp"], TU_INCLUDES) == {"Layer1/Math/Utils.cpp"}

    def test_changed_header_fans_out_to_all_includers(self):
        # Utils.h is included by Main.cpp AND Utils.cpp -> both affected, Lone.cpp not
        assert affected_tus(["Layer1/Math/Utils.h"], TU_INCLUDES) == {
            "Layer1/App/Main.cpp", "Layer1/Math/Utils.cpp"}

    def test_unrelated_change_affects_nothing(self):
        assert affected_tus(["Layer1/Other/Thing.h"], TU_INCLUDES) == set()

    def test_new_cpp_not_in_closure_map_is_parsed(self):
        assert "Layer1/New/New.cpp" in affected_tus(["Layer1/New/New.cpp"], TU_INCLUDES)

    def test_empty_diff(self):
        assert affected_tus([], TU_INCLUDES) == set()

    def test_case_insensitive_match_on_every_platform(self):
        # Was skipped off Windows, because the fold was conditional on os.name -- which is
        # exactly what made a Windows-parsed baseline unusable from Linux. It now holds
        # everywhere, so the skip would hide the behaviour it is here to protect.
        assert affected_tus(["layer1/math/UTILS.h"], TU_INCLUDES) == {
            "Layer1/App/Main.cpp", "Layer1/Math/Utils.cpp"}


class TestFullReparseReason:
    def test_no_closure_map_forces_full(self):
        assert full_reparse_reason([("M", "x.cpp")], {}) is not None
        assert full_reparse_reason([("M", "x.cpp")], None) is not None

    def test_header_added_forces_full(self):
        r = full_reparse_reason([("A", "Layer1/Math/New.h")], TU_INCLUDES)
        assert r and "added" in r

    def test_header_deleted_forces_full(self):
        r = full_reparse_reason([("D", "Layer1/Math/Old.h")], TU_INCLUDES)
        assert r and "deleted" in r

    def test_cpp_add_delete_is_fine(self):
        # adding/removing a .cpp is handled by the affected set, not a full re-parse
        assert full_reparse_reason([("A", "x.cpp"), ("D", "y.cpp"), ("M", "z.h")], TU_INCLUDES) is None


class TestParseFingerprint:
    def test_deterministic_and_hex(self):
        import re
        a = parse_fingerprint(["-Iinc", "-DFOO=1"], std="c++14", toolchain="clang-17")
        assert a == parse_fingerprint(["-Iinc", "-DFOO=1"], std="c++14", toolchain="clang-17")
        assert re.fullmatch(r"[0-9a-f]{64}", a)

    def test_changes_on_flag_std_toolchain(self):
        base = parse_fingerprint(["-Iinc"], std="c++14", toolchain="clang-17")
        assert base != parse_fingerprint(["-Iinc", "-DX"], std="c++14", toolchain="clang-17")
        assert base != parse_fingerprint(["-Iinc"], std="c++17", toolchain="clang-17")
        assert base != parse_fingerprint(["-Iinc"], std="c++14", toolchain="clang-18")

    def test_include_order_matters(self):
        assert (parse_fingerprint(["-Ia", "-Ib"]) != parse_fingerprint(["-Ib", "-Ia"]))


class TestPathMatchingIsPlatformIndependent:
    """A baseline parsed on one OS must be comparable on the other.

    libclang reports a path as it was written, so a Windows parse can record
    `01_SRC/x.cpp` where git says `01_src/x.cpp`. Folding case only on Windows meant the
    two matched there and not on Linux -- where the file then read as unchanged and its
    entities kept the baseline's hashes, silently. Folding everywhere can only match one
    file too many, which costs a re-parse; matching too few is a stale document.
    """

    def test_a_windows_cased_baseline_matches_a_git_cased_diff(self):
        tu_includes = {"01_SRC/Fcore/Common.cpp": ["01_SRC/Fcore/Common.h"]}
        got = affected_tus(["01_src/fcore/common.h"], tu_includes)
        assert got == {"01_SRC/Fcore/Common.cpp"}, (
            "the header changed; its TU must be re-parsed whatever the casing")

    def test_the_returned_path_keeps_its_original_casing(self):
        tu_includes = {"01_SRC/Fcore/Common.cpp": []}
        got = affected_tus(["01_src/fcore/Common.cpp"], tu_includes)
        assert got == {"01_SRC/Fcore/Common.cpp"}, (
            "matching folds case; what we hand back must not")

    def test_an_unrelated_file_still_does_not_match(self):
        tu_includes = {"a/Common.cpp": ["a/Common.h"]}
        assert affected_tus(["a/Other.h"], tu_includes) == set()


class TestCaseCollisions:
    def test_reports_paths_differing_only_by_case(self):
        got = case_collisions(["src/Foo.h", "src/foo.h", "src/bar.h"])
        assert got == {"src/foo.h": ["src/Foo.h", "src/foo.h"]}

    def test_empty_for_a_normal_repo(self):
        assert case_collisions(["src/a.cpp", "src/b.cpp", "src/a.h"]) == {}

    def test_separator_and_blank_differences_are_not_collisions(self):
        # Same file spelled with backslashes is one path, not a clash.
        assert case_collisions(["src\a.cpp", "src/a.cpp", ""]) == {}
