"""The command line: every check writes every report, and the gate reads priorities.

`--markdown` and `--json` used to be silently ignored by `--self` and `--pair`; a
reviewer who asked for the long form of a pairing got nothing and no message. Every
mode now renders through the same report, so every mode writes both.
"""
import glob
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))
if os.path.join(_ROOT, "tests", "unit") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tests", "unit"))

pytest.importorskip("docx", reason="python-docx is needed to write a .docx")

from doccheck.__main__ import main                                # noqa: E402
from test_doccheck_robustness import ROWS, build_design           # noqa: E402

pytestmark = pytest.mark.unit


def _pair_on_disk():
    """(design, spec) from one generated group, or None."""
    for d in sorted(glob.glob(os.path.join(_ROOT, "workspaces", "*", "versions", "*",
                                           "documents"))):
        for design in sorted(glob.glob(os.path.join(d, "software_detailed_design_*.docx"))):
            spec = design.replace("software_detailed_design_", "software_unit_test_specification_")
            if os.path.isfile(spec):
                return design, spec
    return None


PAIR = _pair_on_disk()


@pytest.fixture
def two(tmp_path):
    rows = [dict(r) for r in ROWS]
    rows[0]["direction"] = "In"
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), rows=rows)
    return ours, theirs, tmp_path


def _reports(tmp_path):
    return str(tmp_path / "r.md"), str(tmp_path / "r.json")


def test_compare_writes_markdown_and_json(two, capsys):
    ours, theirs, tmp = two
    md, js = _reports(tmp)
    assert main([ours, theirs, "--markdown", md, "--json", js]) == 0
    text = open(md, encoding="utf-8").read()
    assert "# doccheck — SWE.3 compare" in text and "Direction" in text
    payload = json.load(open(js, encoding="utf-8"))
    assert payload["mode"] == "compare" and payload["summary"]["P1"] >= 1
    assert "wrote" in capsys.readouterr().err            # the report stays on stdout


def test_self_writes_markdown_and_json(two):
    ours, _theirs, tmp = two
    md, js = _reports(tmp)
    assert main([ours, "--self", "--markdown", md, "--json", js]) == 0
    assert "# doccheck — SWE.3 on its own" in open(md, encoding="utf-8").read()
    assert json.load(open(js, encoding="utf-8"))["mode"] == "self"


@pytest.mark.skipif(PAIR is None, reason="no generated design/spec pair on disk")
def test_pair_writes_markdown_and_json(tmp_path):
    design, spec = PAIR
    md, js = _reports(tmp_path)
    main([design, spec, "--pair", "--markdown", md, "--json", js])
    text = open(md, encoding="utf-8").read()
    assert "# doccheck — SWE.3 ↔ SWE.4" in text and "## L3 · Sections" in text
    payload = json.load(open(js, encoding="utf-8"))
    assert payload["mode"] == "pair" and payload["left"]["role"] == "design"


@pytest.mark.skipif(PAIR is None, reason="no generated design/spec pair on disk")
def test_a_design_and_a_spec_are_paired_without_asking(tmp_path):
    design, spec = PAIR
    js = str(tmp_path / "r.json")
    main([spec, design, "--json", js])                   # the spec first, even
    payload = json.load(open(js, encoding="utf-8"))
    assert payload["mode"] == "pair"
    assert payload["left"]["path"] == design and payload["right"]["path"] == spec


def test_the_gate_reads_priorities(two):
    ours, theirs, _tmp = two
    assert main([ours, theirs, "--gate", "P1"]) == 1     # a Direction changed: P1
    assert main([ours, ours, "--gate", "P1"]) == 0
    assert main([ours, theirs, "--gate", "high"]) == 1   # the old name still works


def test_the_gate_ignores_what_it_is_not_asked_about(tmp_path):
    rows = [dict(r) for r in ROWS]
    rows[0]["information"] = "a reworded sentence"      # P4 only
    ours = build_design(str(tmp_path / "ours.docx"))
    theirs = build_design(str(tmp_path / "theirs.docx"), rows=rows)
    assert main([ours, theirs, "--gate", "P2"]) == 0
    assert main([ours, theirs, "--gate", "P4"]) == 1


def test_the_level_flag_stops_early(two):
    ours, theirs, tmp = two
    js = str(tmp / "r.json")
    assert main([ours, theirs, "--level", "4", "--json", js, "--gate", "P1"]) == 0
    payload = json.load(open(js, encoding="utf-8"))
    assert payload["maxLevel"] == 4 and "L5" not in payload["summary"]["levels"]


def test_quiet_prints_one_line(two, capsys):
    ours, theirs, _tmp = two
    main([ours, theirs, "--quiet"])
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "P1" in out[0]


def test_two_designs_forced_to_pair_are_refused(two, capsys):
    ours, theirs, _tmp = two
    assert main([ours, theirs, "--pair"]) == 2
    assert "one SWE.3 document and one SWE.4 document" in capsys.readouterr().err
