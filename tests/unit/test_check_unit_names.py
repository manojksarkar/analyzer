"""tools/check_unit_names.py — does it actually FIND a collision?

A unit key is `<componentId>|<basename>` with no directory in it, so two files
sharing a basename in different directories of one component merge into a single
unit carrying both files' functions. Nothing fails; the document just describes a
unit that does not exist.

This tool answers "does my tree have that?" before a parse, or "did this version?"
after one. The tests that matter are the ones proving it does not just print
"0 collisions" at everything — an empty pass is not a pass.

Mark: unit (filesystem scan against a tmp tree; no DB, no parse)
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine"),
                os.path.join(PROJECT_ROOT, "tools")]

import check_unit_names as CUN  # noqa: E402


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A tiny checkout whose component map is stubbed: first path segment = component."""
    monkeypatch.setattr(CUN, "_from_filesystem", _scan_by_first_segment)
    return tmp_path


def _scan_by_first_segment(base_path):
    """Stand-in for the config-driven resolver: `<Component>/<...>/<file>`."""
    rows = []
    for root, dirnames, files in os.walk(base_path):
        dirnames.sort()
        for fn in sorted(files):
            if not fn.lower().endswith(CUN._SRC_EXTS):
                continue
            rel = os.path.relpath(os.path.join(root, fn), base_path).replace("\\", "/")
            parts = rel.split("/")
            if len(parts) < 2:
                continue
            rows.append((parts[0], os.path.splitext(fn)[0],
                         os.path.dirname(rel) or ".", rel))
    return rows


def _write(root, *rel_files):
    for rel in rel_files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("void f(void) {}\n", encoding="utf-8")


class TestItFindsCollisions:

    def test_the_same_basename_in_two_directories_is_reported(self, tree, capsys):
        _write(tree, "Ftl/Core/Table.cpp", "Ftl/Cache/Table.cpp")
        rc = CUN.main(["--path", str(tree)])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "collisions    : 1" in out
        assert "Ftl|Table" in out
        assert "Ftl/Core/Table.cpp" in out and "Ftl/Cache/Table.cpp" in out

    def test_a_cpp_and_its_header_together_are_not_a_collision(self, tree, capsys):
        """One unit's two halves — the check compares DIRECTORIES, not names."""
        _write(tree, "Ftl/Core/Table.cpp", "Ftl/Core/Table.h")
        rc = CUN.main(["--path", str(tree)])
        assert rc == 0, capsys.readouterr().out

    def test_the_same_basename_in_two_COMPONENTS_is_not_a_collision(self, tree, capsys):
        """Different keys — `Ftl|Table` and `Hil|Table` never merged."""
        _write(tree, "Ftl/Core/Table.cpp", "Hil/Core/Table.cpp")
        rc = CUN.main(["--path", str(tree)])
        assert rc == 0, capsys.readouterr().out

    def test_every_colliding_file_is_listed_not_just_the_count(self, tree, capsys):
        _write(tree, "Ftl/A/T.cpp", "Ftl/B/T.cpp", "Ftl/C/T.cpp")
        CUN.main(["--path", str(tree)])
        out = capsys.readouterr().out
        for rel in ("Ftl/A/T.cpp", "Ftl/B/T.cpp", "Ftl/C/T.cpp"):
            assert rel in out

    def test_a_clean_tree_exits_zero_and_says_so(self, tree, capsys):
        _write(tree, "Ftl/Core/Table.cpp", "Ftl/Core/Map.cpp", "Hil/Io/Port.cpp")
        rc = CUN.main(["--path", str(tree)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "collisions    : 0" in out and "No unit-key collisions" in out


class TestFilters:

    def test_a_component_filter_narrows_the_scan(self, tree, capsys):
        _write(tree, "Ftl/A/T.cpp", "Ftl/B/T.cpp", "Hil/A/T.cpp", "Hil/B/T.cpp")
        rc = CUN.main(["--path", str(tree), "--component", "Hil", "--collisions-only"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "Hil|T" in out and "Ftl|T" not in out

    def test_a_unit_filter_narrows_the_scan(self, tree, capsys):
        _write(tree, "Ftl/A/T.cpp", "Ftl/B/T.cpp", "Ftl/A/Other.cpp")
        CUN.main(["--path", str(tree), "--unit", "Other", "--collisions-only"])
        out = capsys.readouterr().out
        assert "collisions    : 0" in out

    def test_collisions_only_suppresses_the_listing(self, tree, capsys):
        _write(tree, "Ftl/Core/Table.cpp", "Ftl/Core/Map.cpp")
        CUN.main(["--path", str(tree), "--collisions-only"])
        assert "unit keys:" not in capsys.readouterr().out

    def test_a_filter_matching_nothing_is_not_an_error(self, tree, capsys):
        _write(tree, "Ftl/Core/Table.cpp")
        rc = CUN.main(["--path", str(tree), "--component", "Nope"])
        assert rc == 0 and "no units matched" in capsys.readouterr().out


class TestBadInput:

    def test_a_missing_path_exits_2(self, tmp_path, capsys):
        rc = CUN.main(["--path", str(tmp_path / "nope")])
        assert rc == 2

    def test_a_bare_name_matches_a_layer_qualified_id(self):
        """`--component Cache` has to find `Ftl.Cache`; the caller should not need
        to know which form the model stored."""
        assert CUN._matches("Ftl.Cache", "Cache")
        assert CUN._matches("Ftl.Cache", "Ftl.Cache")
        assert CUN._matches("Ftl.Sample Core", "sample-core")
        assert not CUN._matches("Ftl.Cache", "Ache")
