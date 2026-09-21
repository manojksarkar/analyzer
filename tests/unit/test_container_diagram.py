"""Static Design component container diagram: layout config, uniform box widths,
and page-fitted sizing.

The container diagram is the edgeless "component box with its unit boxes" figure
in section N.1. It used to be emitted with dagre's `ranksep`/`nodesep` keys, which
mermaid ignores, and inserted at a hardcoded 6in width regardless of the image's
natural size -- a 16-unit component came out 6.00 x 44.9in, five pages of overflow.

Only this diagram is in scope; the header-dependency, unit and behaviour diagrams
keep their existing sizing.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for path in (os.path.join(_ROOT, "engine"),):
    if path not in sys.path:
        sys.path.insert(0, path)

pytest.importorskip("docx", reason="python-docx is needed by docx_exporter")

import docx_exporter as dx                                        # noqa: E402

pytestmark = pytest.mark.unit


def _rows(*names):
    """unit_rows shape the exporter passes: (key, display_name, interfaces)."""
    return [(f"Comp|{n}", n, None) for n in names]


# --- layout config -------------------------------------------------------

def test_init_uses_mermaid_spacing_keys_not_dagre_ones():
    mmd = dx._build_component_container_mermaid("Uart", _rows("Uart", "UartBuf"))
    init = mmd.splitlines()[0]
    assert "rankSpacing" in init and "nodeSpacing" in init
    # dagre's own names are silently ignored by mermaid -- they must not come back
    assert "ranksep" not in init and "nodesep" not in init


def test_init_reserves_room_under_the_component_title():
    init = dx._build_component_container_mermaid("Uart", _rows("Uart")).splitlines()[0]
    assert "subGraphTitleMargin" in init


def test_labels_render_monospace_and_title_bold():
    init = dx._build_component_container_mermaid("Uart", _rows("Uart")).splitlines()[0]
    assert "monospace" in init
    assert "font-weight: 700" in init


def test_borders_are_black():
    mmd = dx._build_component_container_mermaid("Uart", _rows("Uart"))
    assert "classDef unitNode fill:#2563eb,stroke:#000000,color:#ffffff" in mmd
    assert "style MOD fill:#fef9c3,stroke:#000000,color:#000000" in mmd


# --- uniform box widths --------------------------------------------------

def test_every_unit_label_is_padded_to_the_same_length():
    names = ["Uart", "UartBuf", "UartParity", "UartTx"]
    mmd = dx._build_component_container_mermaid("Uart", _rows(*names))
    labels = [ln.split('["', 1)[1].rsplit('"]', 1)[0]
              for ln in mmd.splitlines() if ln.strip().startswith("U") and '["' in ln]
    assert len(labels) == len(names)
    widths = {len(x.replace("&nbsp;", " ")) for x in labels}
    assert len(widths) == 1, f"labels not equal width: {widths}"
    # the longest name is the target width and is left unpadded
    assert "&nbsp;" not in labels[names.index("UartParity")]


def test_padding_is_centred():
    assert dx._pad_label_to_width("ab", 6) == "&nbsp;&nbsp;ab&nbsp;&nbsp;"
    assert dx._pad_label_to_width("abc", 6) == "&nbsp;abc&nbsp;&nbsp;"
    assert dx._pad_label_to_width("abcdef", 6) == "abcdef"
    assert dx._pad_label_to_width("toolong", 3) == "toolong"


def test_unit_names_survive_padding():
    mmd = dx._build_component_container_mermaid("Uart", _rows("Uart", "UartBuf"))
    assert "UartBuf" in mmd and "Uart" in mmd


def test_empty_component_does_not_crash():
    mmd = dx._build_component_container_mermaid("Empty", [])
    assert "flowchart TB" in mmd
    assert "class " not in mmd          # no unit ids to classify


# --- page-fitted sizing --------------------------------------------------

@pytest.fixture
def png(tmp_path):
    def _make(w, h):
        Image = pytest.importorskip("PIL.Image", reason="Pillow needed")
        p = tmp_path / f"{w}x{h}.png"
        Image.new("RGB", (w, h), "white").save(p)
        return str(p)
    return _make


def test_tall_image_is_bounded_by_page_height(png):
    # the 16-unit Uart case: tall and narrow
    w = dx._fit_picture_width(png(398, 2204), 6.5, 9.0)
    assert w == pytest.approx(398 / 96.0 * (9.0 / (2204 / 96.0)), rel=1e-6)
    assert w < 6.5
    # and the resulting height lands exactly on the page bound
    assert w * (2204 / 398) == pytest.approx(9.0, rel=1e-6)


def test_wide_image_is_bounded_by_page_width(png):
    assert dx._fit_picture_width(png(1568, 316), 6.5, 9.0) == pytest.approx(6.5)


def test_small_image_is_never_upscaled(png):
    # 192x192px = 2x2in at 96dpi -- must stay 2in, not stretch to 6.5in
    assert dx._fit_picture_width(png(192, 192), 6.5, 9.0) == pytest.approx(2.0)


def test_missing_file_falls_back_to_max_width():
    assert dx._fit_picture_width("does_not_exist.png", 6.5, 9.0) == 6.5


def test_fit_respects_a_narrower_configured_box(png):
    assert dx._fit_picture_width(png(1568, 316), 4.0, 9.0) == pytest.approx(4.0)


# --- config parsing ------------------------------------------------------

def test_bare_bool_config():
    assert dx._parse_component_static_diagram_cfg({"componentStaticDiagram": True}) == (
        True, True, dx._CONTAINER_MAX_WIDTH_IN)
    assert dx._parse_component_static_diagram_cfg({"componentStaticDiagram": False})[0] is False


def test_missing_config_defaults_to_enabled():
    assert dx._parse_component_static_diagram_cfg({})[0] is True
    assert dx._parse_component_static_diagram_cfg(None)[0] is True


def test_dict_form_enabled_false_actually_disables():
    """bool({"enabled": False}) is True -- the old parse rendered it anyway."""
    enabled, _, _ = dx._parse_component_static_diagram_cfg(
        {"componentStaticDiagram": {"enabled": False}})
    assert enabled is False


def test_dict_form_width_inches_is_read():
    _, _, width = dx._parse_component_static_diagram_cfg(
        {"componentStaticDiagram": {"widthInches": 4.25}})
    assert width == pytest.approx(4.25)


def test_dict_form_bad_width_falls_back():
    _, _, width = dx._parse_component_static_diagram_cfg(
        {"componentStaticDiagram": {"widthInches": "wide"}})
    assert width == dx._CONTAINER_MAX_WIDTH_IN


def test_dict_form_render_png_is_read():
    _, render_png, _ = dx._parse_component_static_diagram_cfg(
        {"componentStaticDiagram": {"renderPng": False}})
    assert render_png is False


# --- scope guard ---------------------------------------------------------

def test_other_diagrams_keep_their_fixed_width():
    """Only the container diagram was rescoped; the rest must be untouched."""
    src = open(os.path.join(_ROOT, "engine", "docx_exporter.py"), encoding="utf-8").read()
    assert "doc.add_picture(dep_png, width=Inches(6))" in src
    assert "doc.add_picture(unit_png, width=Inches(6))" in src
    assert src.count("width=Inches(4.0))") == 1          # flowchart table cell
