"""The reports: a change drawn as what changed, on five levels, in three forms.

The terminal report prints each level's disagreeing summary rows and its P1/P2
findings, a change as what changed and nothing else: members and items diffed one
by one, the changed words marked, one change printed once however many places it
occurs in, plain ASCII whenever the output is not a terminal.

The markdown report shows every level's summary and collapses the details under
`<details>` -- summaries visible, details a click away. JSON carries all of it.

Everything here builds findings and summary rows directly -- the renderer does not
care where they came from, and a `.docx` would only slow the tests down.
"""
import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

from doccheck import report                                   # noqa: E402
from doccheck.compare import Check, Finding, Result           # noqa: E402
from doccheck.model import P1, P2, P3, P4                     # noqa: E402

pytestmark = pytest.mark.unit

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _where(path):
    parts = path.split(" / ")
    return dict(component=parts[0], unit=parts[1] if len(parts) > 1 else "",
                item=parts[2] if len(parts) > 2 else "")


def _result(*findings, checks=(), mode="compare"):
    result = Result(mode=mode, doc_type="SWE.3")
    for f in findings:
        result.add(f)
    result.checks = list(checks)
    result.findings.sort(key=lambda f: f.sort_key())
    return result


def _differs(path, label, left, right, priority=P2, field="", level="L5", rule="",
             explained=False, view="interface table", follows=""):
    return Finding(level=level, kind="differs", path=path, field=field or label,
                   summary="%s: %s -> %s" % (label, left, right), priority=priority,
                   left=left, right=right, rule=rule, explained=explained, view=view,
                   follows=follows, entity="interface", **_where(path))


def _missing(path, entity="interface", rule="", priority=P2, level="L4"):
    name = path.rsplit(" / ", 1)[-1]
    return Finding(level=level, kind="missing", path=path, priority=priority, left=name,
                   summary="%s %r is only in the reference" % (entity, name), rule=rule,
                   entity=entity, **_where(path))


def _text(*findings, **kw):
    return report.text(_result(*findings), "a.docx", "b.docx", **kw)


def _md(*findings, checks=(), mode="compare"):
    return report.markdown(_result(*findings, checks=checks, mode=mode), "a.docx", "b.docx")


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
                 ["Issue function f.", "Expect b.", "Return x."], priority=P1)
    out = _text(f)
    assert "Test Steps: 1 changed" in out
    assert "... 1 unchanged" in out                  # where the change sits
    assert "- Expect a." in out and "+ Expect b." in out
    assert "Return x." not in out                    # a trailing unchanged run says nothing


def test_a_value_that_fits_reads_on_one_line():
    out = _text(_differs("C / U / f", "Direction", "In", "Out", priority=P1))
    assert "Direction: In -> Out" in out


def test_a_long_difference_is_cut_and_full_shows_it_all():
    f = _differs("C / U / f", "Test Steps", ["step %d" % i for i in range(20)],
                 ["step %d changed" % i for i in range(20)], priority=P1)
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
    assert "=> same change in Owner" in out


def test_a_repeated_rule_prints_once_and_is_numbered():
    rule = "we leave private items out of the table entirely"
    out = _text(_missing("C / U / f1", rule=rule), _missing("C / U / f2", rule=rule))
    assert out.count(rule) == 1
    assert "possible reason [1]: " + rule in out
    assert "possible reason [1], as above" in out


def test_a_rule_explaining_one_finding_carries_no_number():
    out = _text(_differs("C / U / f", "Direction", "In", "Out", rule="because"))
    assert "possible reason: because" in out


def test_a_broken_rule_is_named_as_the_rule():
    f = _differs("C / U / f", "Direction", "In", "Out", rule="the pairing rule")
    f.breaks = True
    assert "the rule: the pairing rule" in _text(f)


# --- the frame: the ladder, the levels, what is left out ------------------------------

def test_the_ladder_line_names_only_the_levels_that_disagree():
    out = _text(_differs("C / U / f", "Direction", "In", "Out"),
                _differs("C / U / f", "Risk", "A", "B", priority=P3, explained=True,
                         level="L3"))
    assert "L1 ok   L2 ok   L3 ok   L4 ok   L5 1" in out     # explained is not a disagreement


def test_p3_and_p4_are_counted_but_listed_only_with_full():
    cosmetic = _differs("C / U / f", "Information", "one sentence", "another", priority=P4)
    real = _differs("C / U / g", "Direction", "In", "Out")
    out = _text(cosmetic, real)
    assert "1 finding not listed" in out
    assert "one sentence" not in out
    whole = _text(cosmetic, real, full=True)
    assert "one sentence" in whole and "not listed" not in whole


def test_a_finding_that_follows_is_not_counted():
    f = _missing("C / U / f")
    f.follows = "function heading at L3"
    out = _text(f, _differs("C / U / g", "Direction", "In", "Out"))
    assert "P2 1" in out.replace(",", " ·").replace(" · ", " ") or "P2 1" in out
    assert "L4 ok" in out


def test_a_finding_quieter_than_its_entry_says_so():
    out = _text(_differs("C / U / f", "Direction", "In", "Out", priority=P1),
                _differs("C / U / f", "Risk", "A", "B", priority=P2))
    assert "Risk: A -> B (P2)" in out


def test_findings_group_under_their_component_worst_first():
    out = _text(_differs("Beta / U / f", "Risk", "A", "B", priority=P2),
                _differs("Alpha / U / f", "Direction", "In", "Out", priority=P1))
    lines = [line.strip() for line in out.splitlines()]
    assert lines.index("Alpha") < lines.index("Beta")


def test_agreement_is_said_in_words():
    out = report.text(Result(), "a.docx", "b.docx")
    assert "nothing to report at any level" in out
    assert "no findings" in out


def test_the_max_level_limits_the_ladder():
    result = _result()
    result.max_level = 2
    out = report.text(result, "a.docx", "b.docx")
    assert "L1 ok   L2 ok" in out and "L3" not in out


def test_two_files_of_one_name_are_told_apart_by_their_directory():
    style = report.Style()
    assert report._names("ws/v10/documents/x.docx", "ws/v12/documents/x.docx", style) == \
        ("v10/.../x.docx", "v12/.../x.docx")
    assert report._names("a/one.docx", "b/two.docx", style) == ("one.docx", "two.docx")


def test_the_pair_report_signs_design_and_specification():
    f = Finding(level="L2", kind="extra", path="Signal / Driver - acquire (Hub - compute)",
                summary="the specification has an interaction spec the design draws no "
                        "diagram for", priority=P1, rule="pairing rule", breaks=True,
                component="Signal", unit="Driver", item="Driver - acquire (Hub - compute)",
                entity="interaction")
    result = _result(f, mode="pair")
    result.sides = ("design", "specification")
    out = report.text(result, "d/design.docx", "s/spec.docx")
    assert "- design         design.docx" in out
    assert "+ specification  spec.docx" in out
    assert "Driver - acquire (Hub - compute)" in out and "the rule: pairing rule" in out


def test_the_self_report_names_the_document_and_its_type():
    result = _result(mode="self")
    out = report.text(result, "x/doc.docx")
    assert "doc.docx  SWE.3, checked against itself" in out
    assert "no findings" in out


# --- markdown: summaries shown, details collapsed ------------------------------------

def test_markdown_has_a_summary_and_a_section_per_level():
    out = _md(_differs("C / U / f", "Direction", "In", "Out", priority=P1))
    assert "## Summary" in out
    for level in ("## L1", "## L2", "## L3", "## L4", "## L5"):
        assert level in out
    assert "| **L5** content |" in out and "✗ 1" in out


def test_every_accordion_starts_closed():
    out = _md(_differs("C / U / f", "Direction", "In", "Out", priority=P1),
              _missing("C / U / g"))
    assert "<details>" in out and "<details open>" not in out


def test_markdown_groups_content_by_unit_then_view():
    out = _md(_differs("C / U / f", "Direction", "In", "Out", priority=P1),
              _differs("C / U / h", "Input Name", "a", "b", view="function sections"))
    assert "<summary><b>C › U</b> · P1 1 · P2 1</summary>" in out
    assert "<summary><b>C › U › interface table</b> · P1 1</summary>" in out
    assert "<summary><b>C › U › function sections</b> · P2 1</summary>" in out


def test_markdown_shows_a_list_change_as_a_diff_block():
    out = _md(_differs("C / U / f", "Test Steps", ["a", "b"], ["a", "c"]))
    assert "```diff" in out and "- b" in out and "+ c" in out


def test_markdown_marks_the_words_of_a_reworded_sentence():
    old = "Returns the absolute value of the argument it was given by the caller"
    new = "Returns the non-negative value of the argument it was given by the caller"
    out = _md(_differs("C / U / f", "Information", old, new, priority=P4, field="information"))
    assert "~~absolute~~ **non-negative**" in out


def test_explained_findings_sit_in_their_own_collapsed_table():
    out = _md(_differs("C / U / f", "Risk", "A", "Medium", priority=P3, explained=True,
                       rule="fixed at Medium", view="function sections", field="risk"))
    assert "<i>Explained by a rule · 1</i>" in out
    assert "| f | Risk `A` → `Medium` | fixed at Medium |" in out


def test_a_follows_finding_says_so_in_markdown():
    f = _missing("C / U / f")
    f.follows = "function heading at L3"
    out = _md(f)
    assert "follows from the function heading at L3" in out
    assert "shown for detail" in out


def test_markdown_escapes_names_that_look_like_formatting():
    out = _md(_missing("C / U / _MTM_SB_SETDbType"))
    assert "\\_MTM\\_SB\\_SETDbType" in out


def test_markdown_l2_and_l3_tables_come_from_the_summary_rows():
    checks = [Check(level="L2", what="units", component="C", left=3, right=2, ok=False,
                    names="✗ 1 differs", detail="− U2", entity="unit"),
              Check(level="L3", what="function headings", component="C", unit="U", left=5,
                    right=5, ok=False, names="✗ 2 differ", entity="function"),
              Check(level="L3", what="unit header section", component="C", unit="U",
                    left=True, right=False, ok=False, entity="unit")]
    out = _md(_missing("C / U2", entity="unit", priority=P1, level="L2"), checks=checks)
    assert "| C › units | 3 | 2 | ✗ 1 differs | **P1** |" in out
    assert "| **U** | 5 | 5 | ✗ 2 differ | **✗ only in −** |" in out


def test_the_self_markdown_lists_findings_by_level():
    f = Finding(level="L5", kind="integrity", path="C / U / f", priority=P1,
                summary="interface id numbering reads 09 where 08 was due",
                component="C", unit="U", item="f", field="id-gap")
    out = report.markdown(_result(f, mode="self"), "doc.docx")
    assert "# doccheck — SWE.3 on its own" in out
    assert "<summary><b>L5 C › U</b> · P1 1</summary>" in out
    assert "## Each document on its own" not in out


# --- json ----------------------------------------------------------------------------

def test_json_carries_levels_checks_and_findings():
    checks = [Check(level="L2", what="units", component="C", left=1, right=1)]
    payload = json.loads(report.to_json(
        _result(_differs("C / U / f", "Direction", "In", "Out", priority=P1), checks=checks),
        "a.docx", "b.docx"))
    assert payload["schema"] == "doccheck/2"
    assert payload["summary"]["P1"] == 1 and payload["summary"]["open"] == 1
    assert payload["summary"]["levels"]["L5"]["worst"] == P1
    assert payload["checks"][0]["what"] == "units"
    assert payload["findings"][0]["counted"] is True
