"""The compare view corrects a text as the reader does (BACKLOG NW-6): each block of the Current side
carries the render's slot, the Reference side none."""
from unittest.mock import patch

from api.services import compare_render


def _slot(key):
    return {"kind": "description", "key": key, "text": "t"}


def _render(desc, bullets, cell):
    return {"sections": [
        {"id": "fn-1", "title": "Fn", "type": "flowchart_table", "flowchart_table": {
            "description": desc, "description_slot": _slot("fn|desc"),
            "input_name": "a", "input_name_slot": _slot("fn|in"),
            "output_name": "b", "output_name_slot": _slot("fn|out"), "flowcharts": []}},
        {"id": "beh-1", "title": "Beh", "type": "behavior_table", "behavior_table": {
            "description_list": bullets, "description_slot": _slot("beh|desc")}},
        {"id": "unit-iface", "title": "Interfaces", "type": "table", "table": {
            "headers": ["Id", "Description"], "rows": [["IF-1", cell]],
            "cell_slots": [[None, _slot("if|1")]]}},
        {"id": "intro", "title": "Intro", "type": "richtext", "content": "same",
         "content_slot": _slot("intro")},
    ]}


def _diff(cur, base):
    renders = iter([cur, base])
    doc = type("Doc", (), {"name": "D", "group": "G", "process": "SWE.3"})()
    ver = type("Ver", (), {"id": "v", "tag": "v", "branch": "main", "commit_sha": "0" * 40})()
    with patch.object(compare_render, "_version_render", lambda *a, **k: next(renders)):
        return compare_render.compute_document_render_diff(None, None, doc, ver, ver, "c", "b", "p")


def _keys(blocks):
    out = []
    for b in blocks:
        if b.get("slot"):
            out.append(b["slot"]["key"])
        for row in b.get("cell_slots") or []:
            out += [c["key"] for c in row if c]
    return out


def test_the_current_side_carries_every_slot_and_the_reference_none():
    d = _diff(_render("new words", ["calls x", "then y"], "new cell"),
              _render("old words", ["calls x"], "old cell"))
    by_id = {s["id"]: s for s in d["sections"]}
    assert _keys(by_id["fn-1"]["current_blocks"]) == ["fn|desc", "fn|in", "fn|out"]
    assert _keys(by_id["beh-1"]["current_blocks"]) == ["beh|desc"]
    assert _keys(by_id["unit-iface"]["current_blocks"]) == ["if|1"]
    assert _keys(by_id["intro"]["current_blocks"]) == ["intro"], "an unchanged section is editable too"
    for s in d["sections"]:
        assert _keys(s["baseline_blocks"]) == [], s["id"]


def test_the_bullets_are_one_block_with_their_list():
    d = _diff(_render("w", ["calls x", "then y"], "c"), _render("w", ["calls x"], "c"))
    beh = next(s for s in d["sections"] if s["id"] == "beh-1")
    text = [b for b in beh["current_blocks"] if b["kind"] == "text"]
    assert len(text) == 1 and text[0]["bullets"] == ["calls x", "then y"]
    assert beh["diff_type"] == "changed"


def test_a_slot_does_not_make_a_section_changed():
    """The fingerprint compares what is printed, never the slot."""
    a, b = _render("same", ["x"], "c"), _render("same", ["x"], "c")
    b["sections"][0]["flowchart_table"]["description_slot"] = _slot("other")
    d = _diff(a, b)
    assert all(s["diff_type"] == "unchanged" for s in d["sections"])
