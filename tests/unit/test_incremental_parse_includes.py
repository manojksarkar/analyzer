"""Unit tests for src/incremental/parse_includes.py — per-TU include closures (M4.0).

The closure must end up as repo-relative, forward-slash, case-preserved paths with
out-of-repo (system/third-party) headers dropped, so it lines up with functions.json
`location.file` and `git diff` output."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.parse_includes import to_repo_relative, build_closure

BASE = os.path.abspath(os.path.join("repo", "root"))


def _abs(*parts):
    return os.path.join(BASE, *parts)


class TestToRepoRelative:
    def test_in_repo_becomes_forward_slash_relative(self):
        assert to_repo_relative(_abs("Layer1", "Math", "Utils.h"), BASE) == "Layer1/Math/Utils.h"

    def test_out_of_repo_returns_none(self):
        assert to_repo_relative(os.path.abspath(os.path.join("usr", "include", "stdio.h")), BASE) is None

    def test_prefix_collision_not_treated_as_in_repo(self):
        # BASE = .../repo/root ; a sibling dir .../repo/rootlib must NOT count as in-repo
        assert to_repo_relative(os.path.abspath(os.path.join("repo", "rootlib", "x.h")), BASE) is None

    def test_empty_and_base_itself(self):
        assert to_repo_relative("", BASE) is None
        assert to_repo_relative(BASE, BASE) == "."   # degenerate; never a real file

    @pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive paths")
    def test_case_insensitive_in_repo_test_preserves_original_case(self):
        # an UPPER-cased drive/prefix still resolves as in-repo, casing preserved in result
        p = _abs("Layer1", "Math", "Utils.h").upper()
        rel = to_repo_relative(p, BASE)
        assert rel is not None and rel.endswith("UTILS.H") and "/" in rel


class TestBuildClosure:
    def test_normalizes_dedups_sorts_and_drops_out_of_repo(self):
        src = _abs("Layer1", "Math", "Utils.cpp")
        included = [
            _abs("Layer1", "Math", "Utils.h"),
            _abs("Layer1", "Common", "Defs.h"),
            os.path.abspath(os.path.join("usr", "include", "vector")),  # out-of-repo -> dropped
            _abs("Layer1", "Math", "Utils.h"),                           # dup -> collapsed
        ]
        assert build_closure(src, included, BASE) == [
            "Layer1/Common/Defs.h",
            "Layer1/Math/Utils.h",
        ]

    def test_excludes_the_tu_own_source(self):
        src = _abs("a", "b", "Foo.cpp")
        included = [_abs("a", "b", "Foo.cpp"), _abs("a", "b", "Foo.h")]
        assert build_closure(src, included, BASE) == ["a/b/Foo.h"]

    def test_empty_includes(self):
        assert build_closure(_abs("a", "Foo.cpp"), [], BASE) == []
