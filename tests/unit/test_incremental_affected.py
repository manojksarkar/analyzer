"""Unit tests for narrowed-parse foundations (M4.1 affected-TU set + M4.2 parse fp)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.affected import affected_tus, full_reparse_reason
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

    @pytest.mark.skipif(os.name != "nt", reason="case-insensitive match is Windows-only")
    def test_case_insensitive_match_on_windows(self):
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
