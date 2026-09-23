"""The terminal report: a change drawn as what changed, and nothing else.

The old report printed a finding as `old -> new` on one line, so a declaration
that lost two members printed both declarations in full and left the reader to
find the difference. These pin the shape that replaced it: members and items
diffed one by one, the changed words marked, one change printed once however
many places it occurs in, and plain ASCII whenever the output is not a terminal.

Everything here builds findings directly -- the renderer does not care where a
finding came from, and a `.docx` would only slow the tests down.
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

from doccheck import report                                   # noqa: E402
from doccheck.compare import Finding, Result                  # noqa: E402
from doccheck.model import HIGH, INFO, LOW, MEDIUM            # noqa: E402

pytestmark = pytest.mark.unit

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _result(*findings):
    result = Result()
    for f in findings:
        result.add(f)
    result.findings.sort(key=lambda f: f.sort_key())
    return result


def _differs(path, label, left, right, severity=MEDIUM, field="", level="L2", rule=""):
    return Finding(level=level, kind="differs", path=path, field=field or label,
                   summary="%s: %s -> %s" % (label, left, right), severity=severity,
                   left=left, right=right, rule=rule)


def _missing(path, kind, rule="", severity=MEDIUM):
    name = path.rsplit(" / ", 1)[-1]
    return Finding(level="L2", kind="missing", path=path, severity=severity, left=name,
                   summary="%s %r is in the reference and not in the other document"
                           % (kind, name), rule=rule)


def _text(*findings, **kw):
    return report.text(_result(*findings), "a.docx", "b.docx", **kw)


# --- a declaration is diffed member by member ---------------------------------------

def test_a_declaration_shows_only_the_members_that_went():
    f = _differs("Access / AccessCompanion / CompanionOwner", "declaration",
                 "class CompanionOwner { public: int a(int v); int b(int v); };",
                 "class CompanionOwner { };")
    out = _text(f)
    assert "declaration: 2 members removed" in out
    assert "- public: int a(int v);" in out
    assert "- public: int b(int v);" in out
    assert "class CompanionOwner" not in out          # neither declaration is echoed whole


def test_a_member_moved_between_access_sections_is_a_change():
    f = _differs("C / U / A", "declaration",
                 "class A { public: int f(); };", "class A { private: int f(); };")
    out = _text(f)
    assert "declaration: 1 member changed" in out
    assert "- public: int f();" in out
    assert "+ private: int f();" in out


def test_a_block_reads_as_head_members_and_tail():
    head, members, tail = report._block(
        "class A { int x; public: int f(); int g() { return 1; } std::string s; "
        "protected: struct S { int a; } s2; enum E { P = 0, Q = 1 }; };")
    assert head == "class A"
    assert members == ["int x;", "public: int f();", "public: int g() { return 1; }",
                       "public: std::string s;", "protected: struct S { int a; } s2;",
                       "protected: enum E { P = 0, Q = 1 };"]
    assert tail == ";"


def test_an_enum_splits_on_commas_and_a_plain_declaration_is_no_block():
    assert report._block("enum Mode { A = 0, B = 1, };") == ("enum Mode", ["A = 0", "B = 1"], ";")
    assert report._block("extern int g_x;") is None


# --- a list is diffed item by item --------------------------------------------------

def test_a_reworded_step_prints_that_step_and_counts_the_rest():
    f = _differs("C / U / f", "Test Steps",
                 ["Issue function f.", "Expect a.", "Return x."],
                 ["Issue function f.", "Expect b.", "Return x."], severity=HIGH)
    out = _text(f)
    assert "Test Steps: 1 changed" in out
    assert "... 1 unchanged" in out                  # where the change sits
    assert "- Expect a." in out and "+ Expect b." in out
    assert "Return x." not in out                    # a trailing unchanged run says nothing


def test_a_value_that_fits_reads_on_one_line():
    out = _text(_differs("C / U / f", "Direction", "In", "Out", severity=HIGH))
    assert "Direction: In -> Out" in out


def test_a_long_difference_is_cut_and_full_shows_it_all():
    f = _differs("C / U / f", "Test Steps", ["step %d" % i for i in range(20)],
                 ["step %d changed" % i for i in range(20)], severity=HIGH)
    cut = _text(f)
    assert "... 32 more (--full shows all)" in cut
    assert cut.count("step ") < 12
    whole = _text(f, full=True)
    assert "more (--full" not in whole
    assert "+ step 19 changed" in whole


def test_a_cut_never_separates_an_old_line_from_its_new_one():
    f = _differs("C / U / f", "Test Steps", ["same"] * 3 + ["old %d" % i for i in range(6)],
                 ["same"] * 3 + ["new %d" % i for i in range(6)])
    out = _text(f)
    assert "- old 3" in out and "+ new 3" in out       # rows 8 and 9: kept as a pair


# --- colour marks the change, and only a terminal gets colour -------------------------

def test_changed_words_are_marked_in_colour():
    f = _differs("C / U / f", "Expected Results",
                 ["Successfully returned normalized result in step 5"],
                 ["Successfully returned result in step 5"])
    out = _text(f, style=report.Style(color=True, fancy=True))
    assert "\x1b[31;7mnormalized\x1b[0m" in out        # red, reversed: the removed word
    assert "\x1b[31;7m" not in out.split("normalized", 1)[1].split("\n", 1)[0]


def test_the_plain_style_is_ascii_with_no_colour_and_no_wrapping():
    rule = "a documented rule " * 20
    f = _differs("C / U / f", "Test Steps", ["x " * 80], ["y " * 80], rule=rule)
    out = _text(f)
    assert "\x1b" not in out
    assert out.isascii()
    assert any(rule.strip() in line for line in out.splitlines())


def test_fancy_output_wraps_inside_the_width():
    f = _differs("C / U / f", "Test Steps", ["word " * 40], ["other " * 40], rule="why " * 30)
    out = _text(f, style=report.Style(color=True, fancy=True, width=60))
    assert max(len(ANSI.sub("", line)) for line in out.splitlines()) <= 60


def test_the_stream_decides_the_style(monkeypatch):
    class Stream:
        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    monkeypatch.setattr(report, "_ansi_ok", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    piped = report.Style.for_stream(Stream(False))
    assert (piped.color, piped.fancy, piped.width) == (False, False, 0)
    tty = report.Style.for_stream(Stream(True))
    assert tty.color and tty.fancy and tty.width >= 60
    assert report.Style.for_stream(Stream(False), "always").color
    assert not report.Style.for_stream(Stream(True), "never").color
    monkeypatch.setenv("NO_COLOR", "1")
    assert not report.Style.for_stream(Stream(True)).color


# --- one change prints once; one rule prints once -------------------------------------

def test_the_same_change_in_two_places_prints_once():
    left, right = "class Owner { public: int a(int v); };", "class Owner { };"
    out = _text(_differs("Access / U1 / Owner", "declaration", left, right),
                _differs("Access / U2 / Owner", "declaration", left, right))
    assert out.count("members removed") + out.count("member removed") == 1
    assert "=> same change in U2 > Owner" in out


def test_one_side_findings_merge_and_a_repeated_rule_prints_once():
    rule = "we leave private items out of the table entirely"
    out = _text(_missing("C / U / f1", "interface", rule), _missing("C / U / f1", "function"),
                _missing("C / U / f2", "interface", rule), _missing("C / U / f2", "function"))
    assert out.count("- only in the reference: interface [1], function") == 2
    assert out.count(rule) == 1
    assert "rule [1]: " + rule in out


def test_a_rule_explaining_one_finding_carries_no_number():
    out = _text(_differs("C / U / f", "Direction", "In", "Out", rule="because"))
    assert "rule: because" in out


# --- the frame around the findings ------------------------------------------------------

def test_the_ladder_line_names_only_the_levels_that_disagree():
    out = _text(_differs("C / U / f", "Direction", "In", "Out"),
                _differs("C / U", "flowcharts", 1, 2, severity=INFO, level="L1"))
    assert "L0 ok   L1 ok   L2 1   L3 ok   L4 ok" in out     # info is not a disagreement


def test_info_is_counted_but_listed_only_with_full():
    info = _differs("C / U / f", "Information", "one sentence", "another", severity=INFO)
    medium = _differs("C / U / g", "Direction", "In", "Out")
    out = _text(info, medium)
    assert "1 info finding not shown (--full lists them)" in out
    assert "one sentence" not in out
    whole = _text(info, medium, full=True)
    assert "one sentence" in whole and "not shown" not in whole


def test_a_finding_quieter_than_its_entry_says_so():
    out = _text(_differs("C / U / f", "Direction", "In", "Out", severity=HIGH),
                _differs("C / U / f", "Risk", "A", "B", severity=LOW))
    assert "Risk: A -> B (low)" in out


def test_findings_group_under_their_component_worst_first():
    out = _text(_differs("Beta / U / f", "Risk", "A", "B", severity=LOW),
                _differs("Alpha / U / f", "Direction", "In", "Out", severity=HIGH))
    lines = [line.strip() for line in out.splitlines()]
    assert lines.index("Alpha") < lines.index("Beta")


def test_agreement_is_said_in_words():
    out = report.text(Result(), "a.docx", "b.docx")
    assert "the two documents agree on everything compared" in out
    assert "no findings" in out


def test_two_files_of_one_name_are_told_apart_by_their_directory():
    style = report.Style()
    assert report._names("ws/v10/documents/x.docx", "ws/v12/documents/x.docx", style) == \
        ("v10/.../x.docx", "v12/.../x.docx")
    assert report._names("a/one.docx", "b/two.docx", style) == ("one.docx", "two.docx")


def test_the_pair_report_signs_design_and_specification():
    f = Finding(level="L4", kind="extra", path="Signal / Driver - acquire (Hub - compute)",
                summary="the test specification specifies an interaction the design draws "
                        "no diagram for", severity=HIGH, rule="pairing rule")
    out = report.pair_text("d/design.docx", "s/spec.docx", "headline", [f])
    assert "- design         design.docx" in out
    assert "+ specification  spec.docx" in out
    assert "Driver - acquire (Hub - compute)" in out and "rule: pairing rule" in out


def test_the_self_report_names_the_document_and_its_type():
    out = report.self_text("x/doc.docx", "SWE.3", [])
    assert "doc.docx  SWE.3, checked against itself" in out
    assert "no findings" in out
