"""The flowchart SVGs the web reader shows (views/flowcharts.write_flowchart_svgs).

Drawn on every run from the per-unit JSON's DOT, one Node process for all of them
(engine/config/render_svg.mjs). A chart is redrawn only when its DOT changed (the key inside
the file), charts over FLOWCHART_SVG_MAX_BOXES are not drawn, and no stale picture survives a
chart that changed, failed to draw, or went away."""
import json
import os
import shutil
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.flowchart_svg import svg_file_name, svg_size_px  # noqa: E402
from utils import (  # noqa: E402
    FLOWCHART_SVG_MAX_BOXES, count_dot_boxes, safe_filename, svg_content_key, svg_file_key,
)
from views.flowcharts import (  # noqa: E402
    _carry_forward_flowcharts, _prune_orphan_flowcharts, refresh_web_svgs, write_flowchart_svgs,
)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None
    or not os.path.isdir(os.path.join(PROJECT_ROOT, "node_modules", "@viz-js", "viz")),
    reason="drawing needs Node.js and the repo's @viz-js/viz",
)


def _dot(*labels):
    """A flowchart in dot_builder's shape: defaults, one node per label, a chain of edges."""
    lines = ["digraph G {", "  rankdir=TB;",
             '  node [fontname="Helvetica", shape=box];', '  edge [color="#333333"];', ""]
    lines += [f'  N{i} [shape=box, label="{lb}"];' for i, lb in enumerate(labels, 1)]
    lines += [f"  N{i} -> N{i + 1};" for i in range(1, len(labels))]
    lines += ["  N1 -> N2 [style=invis];", "}"]
    return "\n".join(lines)


def _write_unit(out_dir, unit, entries):
    with open(os.path.join(out_dir, f"{unit}.json"), "w", encoding="utf-8") as f:
        json.dump([{"name": n, "flowchart": d} for n, d in entries], f)


class TestCountBoxes:
    def test_counts_nodes_not_defaults_or_edges(self):
        assert count_dot_boxes(_dot("Start", "Work", "End")) == 3

    def test_empty(self):
        assert count_dot_boxes("") == 0
        assert count_dot_boxes(None) == 0


class TestSvgFileName:
    """The SVG's name is the PNG's with .svg -- the web render finds pictures by it."""

    @pytest.mark.parametrize("func", [
        "add", "Math::add", "operator+=", "~Buffer", "Box<int>::get", "a b", "x,y&z;w",
    ])
    def test_matches_the_png_name(self, func):
        assert svg_file_name("Unit", func) == f"Unit_{safe_filename(func)}.svg"


class TestSvgSize:
    """The web render reserves each picture's space from this before the image loads."""

    def test_graphviz_points_become_css_pixels(self, tmp_path):
        p = tmp_path / "a.svg"
        p.write_text('<?xml version="1.0"?>\n<svg width="422pt" height="300pt" '
                     'viewBox="0 0 422 300">', encoding="utf-8")
        assert svg_size_px(str(p)) == (563, 400)

    def test_no_unit_is_pixels(self, tmp_path):
        p = tmp_path / "b.svg"
        p.write_text('<svg height="50" width="120">', encoding="utf-8")
        assert svg_size_px(str(p)) == (120, 50)

    def test_missing_file(self, tmp_path):
        assert svg_size_px(str(tmp_path / "none.svg")) is None


@needs_node
class TestWriteSvgs:
    def test_draws_each_chart_with_its_key_then_leaves_it(self, tmp_path):
        out = str(tmp_path)
        dot = _dot("Start", "End")
        _write_unit(out, "Math", [("Math::add", dot), ("sub", _dot("A", "B"))])

        first = write_flowchart_svgs(PROJECT_ROOT, out)
        assert first["drawn"] == 2 and first["failed"] == 0
        svg = os.path.join(out, "Math_Math__add.svg")         # the PNG's name, .svg
        assert svg_file_key(svg) == svg_content_key(dot)
        with open(svg, encoding="utf-8") as f:
            assert "<svg" in f.read()

        second = write_flowchart_svgs(PROJECT_ROOT, out)
        assert second["drawn"] == 0 and second["current"] == 2

    def test_a_changed_chart_is_redrawn(self, tmp_path):
        out = str(tmp_path)
        _write_unit(out, "Math", [("add", _dot("Old", "End"))])
        write_flowchart_svgs(PROJECT_ROOT, out)

        new = _dot("New", "End")
        _write_unit(out, "Math", [("add", new)])
        counts = write_flowchart_svgs(PROJECT_ROOT, out)
        assert counts["drawn"] == 1
        assert svg_file_key(os.path.join(out, "Math_add.svg")) == svg_content_key(new)

    def test_too_large_is_not_drawn_and_its_old_picture_goes(self, tmp_path):
        out = str(tmp_path)
        _write_unit(out, "Big", [("run", _dot("A", "B"))])
        write_flowchart_svgs(PROJECT_ROOT, out)
        assert os.path.isfile(os.path.join(out, "Big_run.svg"))

        huge = _dot(*[f"step {i}" for i in range(FLOWCHART_SVG_MAX_BOXES + 1)])
        _write_unit(out, "Big", [("run", huge)])
        counts = write_flowchart_svgs(PROJECT_ROOT, out)
        assert counts["too_large"] == 1 and counts["drawn"] == 0
        assert not os.path.exists(os.path.join(out, "Big_run.svg"))

    def test_a_chart_that_fails_loses_its_old_picture_and_the_rest_still_draw(self, tmp_path):
        out = str(tmp_path)
        _write_unit(out, "U", [("bad", _dot("A", "B")), ("good", _dot("C", "D"))])
        write_flowchart_svgs(PROJECT_ROOT, out)

        _write_unit(out, "U", [("bad", "digraph G { N1 [shape=box; }"),
                               ("good", _dot("C", "D", "E"))])
        counts = write_flowchart_svgs(PROJECT_ROOT, out)
        assert counts["failed"] == 1 and counts["drawn"] == 1
        assert not os.path.exists(os.path.join(out, "U_bad.svg"))
        assert os.path.isfile(os.path.join(out, "U_good.svg"))

    def test_an_svg_no_chart_owns_is_removed(self, tmp_path):
        out = str(tmp_path)
        _write_unit(out, "U", [("f", _dot("A", "B"))])
        (tmp_path / "U_gone.svg").write_text("<svg/>", encoding="utf-8")
        counts = write_flowchart_svgs(PROJECT_ROOT, out)
        assert counts["removed"] == 1
        assert not (tmp_path / "U_gone.svg").exists()
        assert (tmp_path / "U_f.svg").exists()


class TestAnExportOnlyRunDrawsWhatItsRestorePutBackStale:
    """`refresh_web_svgs`, after an export-only run's restore (`run._restore_output_from_db`).
    The stored SVG is the last capture's, drawn from the DOT before a label correction, and Phase
    3 does not run: the web page read "Flowchart not drawn for this run" after every label update
    (FAST_WORD_FILE_UPDATES P2)."""

    def test_only_the_runs_components_by_the_guards_spelling(self, tmp_path, monkeypatch):
        import views.flowcharts as fc
        seen = []
        monkeypatch.setattr(fc, "write_flowchart_svgs",
                            lambda root, d: seen.append(d) or {"drawn": 1})
        for comp in ("Layer1.Sample-Core", "Layer1.Lib"):
            (tmp_path / comp / "flowcharts").mkdir(parents=True)
        (tmp_path / "Layer1.Util").mkdir()                 # a component with no charts
        total = fc.refresh_web_svgs(PROJECT_ROOT, str(tmp_path), ["Layer1.Sample Core"])
        assert seen == [str(tmp_path / "Layer1.Sample-Core" / "flowcharts")]
        assert total["drawn"] == 1
        seen.clear()
        fc.refresh_web_svgs(PROJECT_ROOT, str(tmp_path))   # no components named: every one
        assert sorted(seen) == sorted(str(tmp_path / c / "flowcharts")
                                      for c in ("Layer1.Lib", "Layer1.Sample-Core"))

    def test_no_output_tree_draws_nothing(self, tmp_path):
        assert refresh_web_svgs(PROJECT_ROOT, str(tmp_path / "absent"))["drawn"] == 0

    @needs_node
    def test_the_picture_of_the_corrected_dot_replaces_the_restored_one(self, tmp_path):
        fc_dir = tmp_path / "Layer1.Sample-Core" / "flowcharts"
        fc_dir.mkdir(parents=True)
        _write_unit(str(fc_dir), "Core", [("add", _dot("Old", "End"))])
        write_flowchart_svgs(PROJECT_ROOT, str(fc_dir))      # what the last capture stored
        corrected = _dot("Corrected", "End")
        _write_unit(str(fc_dir), "Core", [("add", corrected)])   # the restored, corrected chart
        counts = refresh_web_svgs(PROJECT_ROOT, str(tmp_path), ["Layer1.Sample Core"])
        assert counts["drawn"] == 1
        assert svg_file_key(str(fc_dir / "Core_add.svg")) == svg_content_key(corrected)


class TestIncrementalCarriesSvgs:
    def test_carry_forward_copies_svgs(self, tmp_path):
        base, out = tmp_path / "base", tmp_path / "out"
        base.mkdir()
        out.mkdir()
        _write_unit(str(base), "U", [("f", _dot("A", "B"))])
        (base / "U_f.svg").write_text("<svg/>", encoding="utf-8")
        _carry_forward_flowcharts(str(base), str(out))
        assert (out / "U_f.svg").exists()

    def test_prune_removes_an_orphan_units_svgs(self, tmp_path):
        out = tmp_path
        _write_unit(str(out), "Gone", [("f", _dot("A", "B"))])
        (out / "Gone_f.svg").write_text("<svg/>", encoding="utf-8")
        (out / "Kept_f.svg").write_text("<svg/>", encoding="utf-8")
        _write_unit(str(out), "Kept", [("f", _dot("A", "B"))])
        _prune_orphan_flowcharts(str(out), {"Kept"})
        assert not (out / "Gone_f.svg").exists()
        assert (out / "Kept_f.svg").exists()


class TestNodeAvailable:
    """A slow `node --version` used to count as "Node is not installed": under load one
    component's check timed out and it shipped with no flowchart at all (2026-09-30)."""

    @staticmethod
    def _fc():
        import views.flowcharts as fc
        return fc

    def test_node_on_path_needs_no_probe(self, monkeypatch):
        fc = self._fc()
        monkeypatch.setattr(fc.shutil, "which", lambda name: "C:/node/node.exe")
        monkeypatch.setattr(fc.subprocess, "run", lambda *a, **k: pytest.fail("probed"))
        assert fc._node_available(PROJECT_ROOT) is True

    def test_a_slow_probe_means_node_is_there(self, monkeypatch):
        import subprocess
        fc = self._fc()
        monkeypatch.setattr(fc.shutil, "which", lambda name: None)

        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        monkeypatch.setattr(fc.subprocess, "run", slow)
        assert fc._node_available(PROJECT_ROOT) is True

    def test_no_node_is_no_node(self, monkeypatch):
        import subprocess
        fc = self._fc()
        monkeypatch.setattr(fc.shutil, "which", lambda name: None)
        monkeypatch.setattr(fc.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 1, b"", b"'node' is not recognized"))
        assert fc._node_available(PROJECT_ROOT) is False

        def missing(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        monkeypatch.setattr(fc.subprocess, "run", missing)
        assert fc._node_available(PROJECT_ROOT) is False


# ---------------------------------------------------------------------------
# The Word pictures: only the charts a Word file prints
# ---------------------------------------------------------------------------
PUB, HELPER, LONE, OTHER = ("C|U|pub|", "C|U|helper|", "C|U|lone|", "C|V|other|")
FUNCS = {
    PUB: {"qualifiedName": "pub", "visibility": "public", "callsIds": [HELPER, OTHER]},
    HELPER: {"qualifiedName": "helper", "visibility": "private", "callsIds": []},
    LONE: {"qualifiedName": "lone", "visibility": "private", "callsIds": []},
    OTHER: {"qualifiedName": "other", "visibility": "public", "callsIds": []},
}
TABLES = {"C|U": {"entries": [{"functionId": PUB, "type": "Function"},
                              {"functionId": "C|U|g", "type": "Global Variable"}]},
          "unitNames": ["U"]}


class TestOnlyPrintedChartsGetAWordPicture:
    """SWE.3 prints a public function's flowchart and its private callees'
    (`docx_common.printed_flowcharts`, the exporter's own rule). Phase 3 drew a Word picture for
    every chart -- 28 on Sample Core, of which 4 were printed."""

    def test_the_rule(self):
        from docx_common import flowchart_section, printed_flowcharts, private_callee_flowcharts
        # pub's own; helper, its private callee; not `other` (public: printed in ITS unit's
        # section, here it has none); not `lone`, which no public function calls.
        assert printed_flowcharts(TABLES, FUNCS) == {PUB, HELPER}
        assert private_callee_flowcharts(PUB, FUNCS) == [HELPER]
        assert private_callee_flowcharts(PUB, FUNCS, hidden={HELPER}) == []
        assert not flowchart_section({"functionId": PUB, "type": "Function"}, hidden={PUB})
        assert not flowchart_section({"functionId": "C|U|g", "type": "Global Variable"})

    def test_a_hidden_function_still_counts(self):
        """Hiding is Phase 4's alone (set from the web app, no Phase 3): shown again later, the
        function is printed with the picture Phase 3 drew."""
        from docx_common import printed_flowcharts
        funcs = {**FUNCS, PUB: {**FUNCS[PUB], "hidden": True}}
        assert printed_flowcharts(TABLES, funcs) == {PUB, HELPER}

    def test_the_exporter_prints_by_the_same_rule(self):
        src = open(os.path.join(PROJECT_ROOT, "engine", "docx_exporter.py"), encoding="utf-8").read()
        assert "(i for i in interfaces if _flowchart_section(i, _hidden_fids))" in src
        assert "_private_callee_flowcharts(iface.get(\"functionId\")," in src

    def _items(self, carried=False):
        return [("U", name, "digraph{}", key, carried)
                for name, key in (("pub", PUB), ("helper", HELPER), ("lone", LONE), ("old", None))]

    def test_only_printed_charts_are_drawn(self, tmp_path):
        from views.flowcharts import _pictures_to_draw
        drawn = _pictures_to_draw(self._items(), {PUB, HELPER}, str(tmp_path))
        # `old`: a chart stored before charts carried their key -- drawn, as before
        assert [it[1] for it in drawn] == ["pub", "helper", "old"]

    def test_without_interface_tables_every_chart_is_drawn(self, tmp_path):
        from views.flowcharts import _pictures_to_draw
        assert len(_pictures_to_draw(self._items(), None, str(tmp_path))) == 4

    def test_a_carried_chart_is_drawn_only_when_printed_and_missing(self, tmp_path):
        """A baseline drew only the charts it printed: a chart printed since, with no picture to
        carry, is drawn; one with its picture (or its slices) on disk is not."""
        from views.flowcharts import _pictures_to_draw
        (tmp_path / "U_helper_part_1_of_2.png").write_bytes(b"png")
        drawn = _pictures_to_draw(self._items(carried=True), {PUB, HELPER}, str(tmp_path))
        assert [it[1] for it in drawn] == ["pub", "old"]
