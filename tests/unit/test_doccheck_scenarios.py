"""Every scenario, on a real document: one change in, one finding out, at its level.

Each scenario (`doccheck_scenarios.py`) copies a document our exporter wrote,
changes one thing, and names where the comparison must report it. The test holds
the tool to three things at once:

- the change is found, at the level and with the priority the scenario names;
- nothing else is counted -- a finding that merely restates it is marked `follows`,
  and one a documented rule explains is P3;
- the reports render it: markdown and JSON, with the same counts.
"""
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for extra in (os.path.join(_ROOT, "tools"), os.path.join(_ROOT, "tests", "unit")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

pytest.importorskip("docx", reason="python-docx is needed to write a .docx")

import doccheck_scenarios as sc                                    # noqa: E402
from doccheck import blocks, compare as comparing, pairing, report, rules, swe3, swe4  # noqa: E402

pytestmark = [pytest.mark.unit,
              pytest.mark.skipif(not (os.path.isfile(sc.DESIGN) and os.path.isfile(sc.SPEC)),
                                 reason="the longdecl-ab.office documents are not on disk")]


def _compare(source, changed, profile):
    left = profile.extract(blocks.read(source))
    right = profile.extract(blocks.read(changed))
    result = comparing.compare(left, right, profile)
    rules.annotate(result, left, right, profile)
    return result


def _key(f):
    return f.field if f.kind == "differs" else f.kind


def _assert_lands(result, scenario):
    counted = [f for f in result.findings if f.counted]
    hit = [f for f in counted if _key(f) == scenario.field]
    assert hit, "%s: not found; counted: %s" % (
        scenario.name, [(f.level, _key(f), f.priority, f.summary) for f in counted])
    f = hit[0]
    assert (f.level, f.priority) == (scenario.level, scenario.priority), \
        "%s: %s at %s, want %s at %s" % (scenario.name, f.priority, f.level,
                                         scenario.priority, scenario.level)
    others = [g for g in counted if _key(g) not in [scenario.field] + scenario.also]
    assert not others, "%s: also counted %s" % (
        scenario.name, [(g.level, _key(g), g.priority, g.summary) for g in others])


@pytest.mark.parametrize("scenario", sc.SWE3, ids=[s.name for s in sc.SWE3])
def test_a_swe3_change_lands_at_its_level(scenario, tmp_path):
    changed = sc.apply(sc.DESIGN, [scenario], str(tmp_path / "changed.docx"))
    _assert_lands(_compare(sc.DESIGN, changed, swe3), scenario)


@pytest.mark.parametrize("scenario", sc.SWE4, ids=[s.name for s in sc.SWE4])
def test_a_swe4_change_lands_at_its_level(scenario, tmp_path):
    changed = sc.apply(sc.SPEC, [scenario], str(tmp_path / "changed.docx"))
    _assert_lands(_compare(sc.SPEC, changed, swe4), scenario)


def test_every_swe3_scenario_at_once_is_found_once_each(tmp_path):
    changed = sc.apply(sc.DESIGN, sc.SWE3, str(tmp_path / "all.docx"))
    result = _compare(sc.DESIGN, changed, swe3)
    for scenario in sc.SWE3:
        assert [f for f in result.findings if f.counted and _key(f) == scenario.field
                and f.level == scenario.level], scenario.name


def test_the_reports_agree_on_the_counts(tmp_path):
    changed = sc.apply(sc.DESIGN, sc.SWE3, str(tmp_path / "all.docx"))
    result = _compare(sc.DESIGN, changed, swe3)
    payload = json.loads(report.to_json(result, sc.DESIGN, changed))
    counted = [f for f in result.findings if f.counted]
    for p in ("P1", "P2", "P3", "P4"):
        assert payload["summary"][p] == sum(1 for f in counted if f.priority == p)
    md = report.markdown(result, sc.DESIGN, changed)
    assert "**P1 %d**" % payload["summary"]["P1"] in md


def test_the_real_pair_reads_on_levels_and_every_finding_names_its_rule():
    design = swe3.extract(blocks.read(sc.DESIGN))
    spec = swe4.extract(blocks.read(sc.SPEC))
    result = pairing.check(design, spec)
    assert result.findings and all(f.rule for f in result.findings)
    levels = {f.level for f in result.findings}
    assert levels <= {"L1", "L2", "L3", "L4", "L5"}
    # The spec has four interaction specs and the design draws no diagram: one L1 fact.
    l1 = [f for f in result.findings if f.level == "L1" and f.counted]
    assert [f.priority for f in l1] == ["P1"]


# --- SWE.3 as the input to SWE.4, on the real pair ----------------------------------

def _pair_result(tmp_path, scenarios):
    design = sc.apply(sc.DESIGN, scenarios, str(tmp_path / "design.docx"))
    return pairing.check(swe3.extract(blocks.read(design)), swe4.extract(blocks.read(sc.SPEC)))


def test_a_drawn_behaviour_pairs_with_its_spec_and_its_arrows_match(tmp_path):
    result = _pair_result(tmp_path, sc.PAIR[:1])
    calls = [c for c in result.checks if c.what == "call arrows ↔ cross-unit calls"]
    assert len(calls) == 1 and calls[0].ok and calls[0].left == 1
    # one of the four specs now has its diagram: three are left unpaired, and L1 is clean
    extra = [f for f in result.findings if f.level == "L2" and f.entity == "interaction"]
    assert len(extra) == 3 and all(f.counted for f in extra)
    assert not [f for f in result.findings if f.level == "L1" and f.counted]


def test_an_arrow_the_spec_does_not_call_lands_at_L5(tmp_path):
    result = _pair_result(tmp_path, sc.PAIR[:2])
    calls = sorted((f.kind, f.left or f.right) for f in result.findings
                   if f.field == "interactionCall")
    assert calls == [("extra", "MtxConflict::markedPublicUnderPrivate"),
                     ("missing", "MtxStruct::exposed")]


def test_a_row_without_its_flowchart_entry_still_owes_a_spec(tmp_path):
    result = _pair_result(tmp_path, sc.PAIR[2:])
    # The spec still has the test case: at L3 it has no heading to pair with (extra),
    # while at L4 the interface row and the test case pair up -- nothing missing there.
    l3 = [f for f in result.findings if f.level == "L3" and f.item.endswith("nestedPublicMode")]
    l4 = [f for f in result.findings if f.level == "L4" and "nestedPublicMode" in f.item]
    assert [(f.kind, f.priority) for f in l3] == [("extra", "P2")] and not l4
    assert "interface table" in l3[0].rule


# --- headings: the design's headings printed again in the spec -----------------------

@pytest.mark.parametrize("scenario", sc.PAIR_HEADINGS, ids=[s.name for s in sc.PAIR_HEADINGS])
def test_a_spec_heading_change_lands_at_its_level(scenario, tmp_path):
    design = sc.apply(sc.DESIGN, sc.PAIR, str(tmp_path / "design.docx"))
    spec = sc.apply(sc.SPEC, [scenario], str(tmp_path / "spec.docx"))
    base = pairing.check(swe3.extract(blocks.read(design)), swe4.extract(blocks.read(sc.SPEC)))
    result = pairing.check(swe3.extract(blocks.read(design)), swe4.extract(blocks.read(spec)))
    before = {(f.level, f.kind, f.field, f.item) for f in base.findings if f.counted}
    new = [f for f in result.findings if f.counted
           and (f.level, f.kind, f.field, f.item) not in before]
    hit = [f for f in new if _key(f) == scenario.field and f.level == scenario.level]
    assert hit, "%s: new counted findings %s" % (
        scenario.name, [(f.level, _key(f), f.priority, f.summary) for f in new])
    assert hit[0].priority == scenario.priority


def test_a_spaced_test_case_heading_is_still_the_same_function(tmp_path):
    spec = sc.apply(sc.SPEC, sc.PAIR_HEADINGS[:1], str(tmp_path / "spec.docx"))
    result = pairing.check(swe3.extract(blocks.read(sc.DESIGN)), swe4.extract(blocks.read(spec)))
    moved = [f for f in result.findings if "mtxUnmarkedCalled" in f.item]
    assert [(f.level, f.field, f.priority, f.view) for f in moved] == \
        [("L5", "headingText", "P4", "headings")]
