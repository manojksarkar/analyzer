"""Flowchart pictures in the web render (api/services/doc_render.py).

Each flowchart is an SVG the engine draws on every run (views/flowcharts.write_flowchart_svgs).
The render sends one entry per chart -- its SVG link and size, or why there is no picture --
and never the DOT, which a document can carry 500+ of. Compare tells a changed flowchart by
the DOT's hash instead, and the asset route serves the SVG as an image that cannot run script.
"""
import datetime
import json
import os
import sys
from types import SimpleNamespace

import pytest

from api.services import compare_render as cr
from api.services import doc_render as dr

pytestmark = pytest.mark.unit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine"))
from core.flowchart_svg import FLOWCHART_SVG_MAX_BOXES, svg_content_key  # noqa: E402

UNIT = "Layer1.Lib|Lib"
ENTRY = {"interfaceId": "IF_1", "interfaceName": "libAdd", "name": "libAdd", "type": "Function",
         "description": "Adds.", "parameters": [{"type": "int", "name": "a", "range": "R"}],
         "returnType": "int", "returnRange": "R", "direction": "Out", "sourceDest": "Core/Core"}


def _dot(n=3):
    nodes = "\n".join(f'  N{i} [shape=box, label="step {i}"];' for i in range(1, n + 1))
    return f'digraph G {{\n  node [shape=box];\n{nodes}\n  N1 -> N2;\n}}'


def _svg(dot, width_pt=300, height_pt=150):
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<!-- dot-key: {svg_content_key(dot)} -->\n'
            f'<svg width="{width_pt}pt" height="{height_pt}pt" viewBox="0 0 {width_pt} {height_pt}">'
            f'</svg>\n')


def _render(tmp_path, dot, svg_text=None):
    group = tmp_path / "Layer1.Lib"
    (group / "flowcharts").mkdir(parents=True)
    (group / "interface_tables.json").write_text(json.dumps({
        "unitNames": {UNIT: "Lib"}, UNIT: {"entries": [ENTRY]}}), encoding="utf-8")
    (group / "flowcharts" / "Lib.json").write_text(
        json.dumps([{"name": "libAdd", "flowchart": dot}]), encoding="utf-8")
    if svg_text is not None:
        (group / "flowcharts" / "Lib_libAdd.svg").write_text(svg_text, encoding="utf-8")
    now = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
    doc = SimpleNamespace(id="d1", group="Layer1.Lib", layer="Layer1", subtitle=None,
                          process="SWE.3", updated_at=now, version_id="v1")
    project = SimpleNamespace(name="Brake ECU", compliance_standard="ISO_26262")
    version = SimpleNamespace(id="v1", tag="v1.0.0", resolved_config=None)
    return dr.build_render(doc, project, version, group, "p1",
                           model_reader=SimpleNamespace(load=lambda name: {}), output_reader=None)


def _flowchart_section(render):
    stack = list(render["sections"])
    while stack:
        s = stack.pop()
        if s.get("type") == "flowchart_table":
            return s
        stack.extend(s.get("children") or [])
    raise AssertionError("no flowchart_table section")


class TestRenderEntry:
    def test_drawn_chart_links_its_svg_with_its_size(self, tmp_path):
        dot = _dot()
        render = _render(tmp_path, dot, _svg(dot, 300, 150))
        (fc,) = _flowchart_section(render)["flowchart_table"]["flowcharts"]
        assert fc["status"] == "drawn"
        assert fc["image_url"] == "projects/p1/documents/d1/assets/flowcharts/Lib_libAdd.svg"
        assert (fc["width"], fc["height"]) == (400, 200)          # points -> CSS px
        assert fc["boxes"] == 3
        assert fc["label"] == "int libAdd(int a)"

    def test_the_dot_is_not_sent(self, tmp_path):
        dot = _dot()
        render = _render(tmp_path, dot, _svg(dot))
        (fc,) = _flowchart_section(render)["flowchart_table"]["flowcharts"]
        assert "mermaid" not in fc
        assert "digraph" not in json.dumps(render)

    def test_no_svg_is_missing(self, tmp_path):
        (fc,) = _flowchart_section(_render(tmp_path, _dot()))["flowchart_table"]["flowcharts"]
        assert fc["status"] == "missing" and fc["image_url"] is None

    def test_an_svg_drawn_from_another_dot_is_not_shown(self, tmp_path):
        render = _render(tmp_path, _dot(3), _svg(_dot(4)))
        (fc,) = _flowchart_section(render)["flowchart_table"]["flowcharts"]
        assert fc["status"] == "missing" and fc["image_url"] is None

    def test_over_the_limit_is_too_large(self, tmp_path):
        big = _dot(FLOWCHART_SVG_MAX_BOXES + 1)
        (fc,) = _flowchart_section(_render(tmp_path, big))["flowchart_table"]["flowcharts"]
        assert fc["status"] == "too_large"
        assert fc["boxes"] == FLOWCHART_SVG_MAX_BOXES + 1
        assert fc["image_url"] is None


class TestCompare:
    """Compare sees a flowchart change through the DOT hash, as it did through the DOT."""

    def _blocks(self, tmp_path, dot):
        return cr._section_blocks(_flowchart_section(_render(tmp_path, dot, _svg(dot))))

    def test_a_changed_flowchart_is_changed(self, tmp_path):
        a = [b for b in self._blocks(tmp_path / "a", _dot(3)) if b["kind"] == "diagram"][0]
        b = [b for b in self._blocks(tmp_path / "b", _dot(4)) if b["kind"] == "diagram"][0]
        cur, _ = cr._diff_block_pair(a, b)
        assert cur["changed"] is True
        assert cur["mermaid"] is None                      # no source to show, only a hash

    def test_the_same_flowchart_is_unchanged(self, tmp_path):
        a = self._blocks(tmp_path / "a", _dot(3))
        b = self._blocks(tmp_path / "b", _dot(3))
        da = [x for x in a if x["kind"] == "diagram"][0]
        db = [x for x in b if x["kind"] == "diagram"][0]
        assert cr._diff_block_pair(da, db)[0]["changed"] is False
        assert cr._block_fingerprint(a) == cr._block_fingerprint(b)


class TestAssetRoute:
    def _serve(self, monkeypatch, tmp_path, name):
        from api.routes import documents as routes
        target = tmp_path / name
        target.write_bytes(b"<svg/>" if name.endswith(".svg") else b"\x89PNG")
        doc = SimpleNamespace(project_id="p1", version_id=None, group="G")
        db = SimpleNamespace(documents=SimpleNamespace(get=lambda _id: doc),
                             versions=SimpleNamespace(get=lambda _id: None))
        monkeypatch.setattr(routes.doc_render, "resolve_asset", lambda group, path, root: target)
        return routes.document_asset("p1", "d1", f"flowcharts/{name}", db=db)

    def test_svg_is_an_image_that_cannot_run_script(self, monkeypatch, tmp_path):
        resp = self._serve(monkeypatch, tmp_path, "U_f.svg")
        assert resp.media_type == "image/svg+xml"
        assert "default-src 'none'" in resp.headers["content-security-policy"]
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_png_is_served_as_before(self, monkeypatch, tmp_path):
        resp = self._serve(monkeypatch, tmp_path, "U_f.png")
        assert "content-security-policy" not in resp.headers

    def test_the_browser_asks_again_for_an_svg(self, monkeypatch, tmp_path):
        """A label correction redraws the SVG under the same name (R8), so a cached copy would
        show the old labels; `no-cache` makes the browser revalidate (FileResponse sends the
        ETag and Last-Modified to revalidate against)."""
        resp = self._serve(monkeypatch, tmp_path, "U_f.svg")
        assert resp.headers["cache-control"] == "no-cache"
