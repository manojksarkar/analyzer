"""The flowchart graph of a function whose file includes a header libclang cannot find.

Firmware is compiled with armclang and parsed here with libclang: the toolchain's own headers
(`stdio.h`), or a project header outside the include paths, may not be reachable. The parse
goes on past a missing header (KeepGoing, core/clang_options.py), and a statement that uses a
name from it stays in the tree as text -- so an `if` around a `printf` keeps both branches.

One thing does not survive on its own: a `case X:` whose X is an enum value or a macro of the
missing header. Clang makes no case statement for it and leaves the case's statements loose in
the switch body, and the graph builder used to drop those -- the branch was not in the
flowchart, nor in the SWE.4 Test Steps built from the same graph. The labels are read back from
the source text (`CFGBuilder._dropped_case_labels`).

Two more ways a branch went wrong, from review SWE3_V4 (the end of this file): a `{ ... }` block
written inside a statement list was folded into one box, so a `return` or `break` in it was lost
-- the Return pointed on to the next statement, a braced `case X: { ...; break; }` fell into the
next case; and a switch's case labels, drawn at the diamond, piled up on top of each other.

Needs libclang, so the module skips without it (see test_visibility_matrix.py).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(PROJECT_ROOT, "engine"), os.path.join(PROJECT_ROOT, "engine", "flowchart")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODES_H = "enum Mode { MODE_FAST = 1, MODE_SLOW = 2 };\nstruct DeviceCfg { int mode; };\n"

SWITCH = '''#include "modes.h"
int g_count;
int pick(DeviceCfg *cfg)
{
    switch (cfg->mode) {
    case MODE_FAST:
        g_count = 10;
        break;
    case MODE_SLOW:
        g_count = 20;
        break;
    default:
        g_count = 0;
        break;
    }
    return g_count;
}
'''


@pytest.fixture(scope="module")
def graph(tmp_path_factory):
    """build(source, function, headers={name: text}) -> the function's ControlFlowGraph."""
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser  # noqa: F401  -- names libclang the way a run does
    except Exception as e:                                  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    from clang import cindex
    from ast_engine.cfg_builder import CFGBuilder
    from ast_engine.parser import SourceExtractor, TranslationUnitParser
    from ast_engine.resolver import find_function_cursor
    from models import FunctionEntry

    def build(source, function, headers=None):
        folder = tmp_path_factory.mktemp("cfg")
        for name, text in (headers or {}).items():
            (folder / name).write_text(text, encoding="utf-8")
        path = folder / "unit.cpp"
        path.write_text(source, encoding="utf-8")
        tu = TranslationUnitParser("c++14", [f"-I{folder}"]).get_tu_full(str(path))
        decl = next(c for c in tu.cursor.get_children()
                    if c.spelling == function and c.kind == cindex.CursorKind.FUNCTION_DECL
                    and c.is_definition())
        entry = FunctionEntry(key=f"C|unit|{function}|", qualified_name=function, file="unit.cpp",
                              line=decl.extent.start.line, end_line=decl.extent.end.line)
        cursor = find_function_cursor(tu, entry, str(path))
        return CFGBuilder(SourceExtractor(str(folder)).get_lines("unit.cpp")).build(cursor, entry)

    return build


def _branches(cfg):
    """{edge label: the first statement it leads to} for every labelled edge of the switch."""
    return {e.label: " ".join(cfg.nodes[e.target].raw_code.split())
            for e in cfg.edges if e.label and (e.label.startswith("case") or e.label == "default")}


def _shape(cfg):
    return ([(n.node_type.name, " ".join(n.raw_code.split())) for n in cfg.nodes.values()][1:],
            sorted((e.source, e.target, e.label or "") for e in cfg.edges))


def test_a_case_of_a_missing_header_keeps_its_branch(graph):
    cfg = graph(SWITCH, "pick")                              # modes.h is not there
    assert _branches(cfg) == {"case MODE_FAST": "g_count = 10",
                              "case MODE_SLOW": "g_count = 20",
                              "default": "g_count = 0"}


def test_it_is_the_graph_the_reachable_header_gives(graph):
    """Recovered from the text or handed over by clang: the same boxes and the same arrows."""
    assert _shape(graph(SWITCH, "pick")) == _shape(graph(SWITCH, "pick", {"modes.h": MODES_H}))


def test_a_dropped_case_after_a_kept_one_takes_only_its_own_statements(graph):
    """`case 1` is clang's; `case MODE_SLOW` is not. Its statements used to be appended to
    case 1's, after its break."""
    cfg = graph('''#include "modes.h"
int g;
int f(int x)
{
    switch (x) {
    case 1:
        g = 1;
        break;
    case MODE_SLOW:
        g = 2;
        break;
    }
    return g;
}
''', "f")
    assert _branches(cfg) == {"case 1": "g = 1", "case MODE_SLOW": "g = 2"}
    one = next(e.target for e in cfg.edges if e.label == "case 1")
    after_one = {e.target for e in cfg.edges if e.source == one}
    assert all(cfg.nodes[t].raw_code.strip() != "g = 2" for t in after_one)


def test_a_dropped_label_that_falls_through_shares_the_next_body(graph):
    cfg = graph('''#include "modes.h"
int g;
int f(int x)
{
    switch (x) {
    case MODE_FAST:
    case 2:
        g = 2;
        break;
    case 3:
    case MODE_SLOW:
        g = 3;
        break;
    }
    return g;
}
''', "f")
    assert _branches(cfg) == {"case MODE_FAST": "g = 2", "case 2": "g = 2",
                              "case 3": "g = 3", "case MODE_SLOW": "g = 3"}


def test_a_switch_inside_a_case_recovers_its_own_labels(graph):
    cfg = graph('''#include "modes.h"
int g;
int f(int x, int y)
{
    switch (x) {
    case 1:
        switch (y) {
        case MODE_FAST:
            g = 11;
            break;
        default:
            g = 12;
            break;
        }
        break;
    default:
        g = 0;
        break;
    }
    return g;
}
''', "f")
    labels = sorted(e.label for e in cfg.edges if e.label)
    assert labels == ["case 1", "case MODE_FAST", "default", "default"]
    assert {" ".join(n.raw_code.split()) for n in cfg.nodes.values()} >= {"g = 11", "g = 12", "g = 0"}


@pytest.mark.parametrize("kind, label", [
    ("int", "case 1:"), ("int", "case (1 ? 2 : 3):"), ("Colour", "case Colour::Red:"),
    ("char", "case 'a':"), ("int", "default:"),
])
def test_a_switch_clang_understood_is_left_to_clang(graph, kind, label):
    """No label is read from the text when clang has them all: the walk it always took."""
    from ast_engine.cfg_builder import CFGBuilder
    seen = []
    real = CFGBuilder._flatten_with_dropped_labels
    CFGBuilder._flatten_with_dropped_labels = lambda self, body, dropped: seen.append(dropped) or real(self, body, dropped)
    try:
        cfg = graph("enum class Colour { Red = 7, Blue = 8 };\nint g;\nint f(" + kind + " x)\n{\n"
                    "    switch (x) {\n    "
                    + ("case 5:\n        g = 5;\n        break;\n    " if label == "default:" else "")
                    + label + "\n        g = 1;\n        break;\n    }\n    return g;\n}\n", "f")
    finally:
        CFGBuilder._flatten_with_dropped_labels = real
    assert seen == []
    assert any(" ".join(n.raw_code.split()) == "g = 1" for n in cfg.nodes.values())


def test_a_statement_that_uses_a_missing_header_stays_in_its_branch(graph):
    """What going on past a missing header already gives: `printf` and `NULL` are unknown
    names, and the branches around them are all there."""
    cfg = graph('''#include <stdio.h>
int g;
int f(char *p)
{
    if (p == NULL) {
        printf("none\\n");
    } else {
        g = 1;
    }
    return g;
}
''', "f")
    code = [" ".join(n.raw_code.split()) for n in cfg.nodes.values()]
    assert "p == NULL" in code and 'printf("none\\n")' in code and "g = 1" in code


def test_the_parse_summary_names_every_header_not_found(monkeypatch):
    """The headers to give include folders for, all of them, with how many files asked."""
    from collections import defaultdict
    import parser as P

    class _Diag:
        def __init__(self, text):
            self.severity, self.spelling = 4, text
    monkeypatch.setattr(P, "_diag_missing_headers", defaultdict(int))
    monkeypatch.setattr(P, "_diag_tu_errors", [])
    monkeypatch.setattr(P, "_diag_counts", defaultdict(int))
    for rel, texts in (("a.c", ["'stdio.h' file not found", "use of undeclared identifier 'X'"]),
                       ("b.c", ["'stdio.h' file not found", "'board_cfg.h' file not found"]),
                       ("c.c", ["unknown type name 'u32'"])):
        P._record_tu_diagnostics(type("TU", (), {"diagnostics": [_Diag(t) for t in texts]})(), rel)
    assert dict(P._diag_missing_headers) == {"stdio.h": 2, "board_cfg.h": 1}
    said = []
    monkeypatch.setattr(P._log, "warning", lambda msg, *a: said.append(msg % a if a else msg))
    P._log_parse_summary(0)
    line = next(s for s in said if "header(s) not found" in s)
    assert "2 header(s) not found" in line and "stdio.h (2 files), board_cfg.h (1 file)" in line


# -- review SWE3_V4: a block in braces, and the case labels -------------------------------------

RETURN_IN_BRACES = """int g;
int f(int avail, int hw)
{
    if (!avail) {
#if (FEATURE_OFF)
        if (hw) {
            g = 1;
        }
        else
#endif
        {
            return -1;
        }
    }
    g = 2;
    return g;
}
"""

BRACED_CASE = """enum class Mode { eREAD, eREAD_FUA, ePRE_FETCH };
int g;
int f(Mode m)
{
    switch (m) {
    case Mode::eREAD:
    case Mode::eREAD_FUA:
        g = 1;
        break;
    case Mode::ePRE_FETCH: {
        g = 2;
        break;
    }
    default:
        g = 0;
        break;
    }
    return g;
}
"""


def _node(cfg, code):
    return next(n for n in cfg.nodes.values() if " ".join(n.raw_code.split()) == code)


def _next(cfg, node):
    """What a box's arrows lead to, by code."""
    return {" ".join(cfg.nodes[e.target].raw_code.split()) for e in cfg.edges
            if e.source == node.node_id}


def test_a_return_in_an_extra_block_goes_to_end(graph):
    """SWE3-011: the `else` of an #if whose macro is off leaves `{ return -1; }` inside the if."""
    cfg = graph(RETURN_IN_BRACES, "f")
    ret = _node(cfg, "return -1")
    assert ret.node_type.name == "RETURN"
    assert _next(cfg, ret) == {"End"}


def test_with_the_macro_on_the_else_block_returns_too(graph):
    cfg = graph("#define FEATURE_ON 1\n" + RETURN_IN_BRACES.replace("FEATURE_OFF", "FEATURE_ON"), "f")
    assert _next(cfg, _node(cfg, "return -1")) == {"End"}
    assert _node(cfg, "hw").node_type.name == "DECISION"


def test_a_braced_case_keeps_its_break(graph):
    """It used to be one box, `{ g = 2; break; }`, with an arrow into the default's box."""
    cfg = graph(BRACED_CASE, "f")
    assert _branches(cfg)["case Mode::ePRE_FETCH"] == "g = 2"
    assert _next(cfg, _node(cfg, "g = 2")) == {"break"}


def test_a_block_of_plain_statements_stays_one_box(graph):
    """Only a block that holds a return, break, branch or loop is opened up."""
    cfg = graph("""int g;
int f(int x)
{
    g = x;
    {
        int t = x * 2;
        g += t;
    }
    return g;
}
""", "f")
    actions = [n for n in cfg.nodes.values() if n.node_type.name == "ACTION"]
    assert len(actions) == 1 and "int t = x * 2;" in actions[0].raw_code


def test_case_arrows_show_the_constant_in_the_middle(graph):
    """SWE3-010: a plain label, which Graphviz makes room for, not a taillabel at the diamond;
    only the constant; one arrow for the cases that go to one box. The graph keeps every case."""
    from dot_builder import build_dot
    cfg = graph(BRACED_CASE, "f")
    dot = build_dot(cfg)
    assert 'label="eREAD\\neREAD_FUA"' in dot          # DOT's line break, one arrow for both
    assert 'label="ePRE_FETCH"' in dot and 'label="default"' in dot
    assert "case " not in dot and "Mode::" not in dot and "taillabel" not in dot
    assert sum(1 for e in cfg.edges if e.label and e.label.startswith("case Mode::eREAD")) == 2


def test_yes_and_no_stay_at_the_diamond(graph):
    from dot_builder import build_dot
    dot = build_dot(graph(RETURN_IN_BRACES, "f"))
    assert 'taillabel="Yes"' in dot and 'taillabel="No"' in dot


@pytest.mark.parametrize("label, shown", [
    ("case BufType::eREAD", "eREAD"), ("case ::ns::A::kX", "kX"), ("case MODE_FAST", "MODE_FAST"),
    ("case 1", "1"), ("case 'a'", "'a'"), ("case (1 ? 2 : 3)", "(1 ? 2 : 3)"), ("default", "default"),
])
def test_what_a_case_arrow_shows(label, shown):
    """A qualified name loses its scope; any other value is kept whole -- `1` stays `1`, not Yes."""
    from dot_builder import _case_value
    assert _case_value(label) == shown


# -- an empty branch, an empty loop body ---------------------------------------------------------
# A `{ }` -- or one an #if whose macro is off emptied -- gave no arrow at all: that side of the
# decision was missing from the chart (review SWE3-012 names the symptom).

def _sides(cfg, code):
    """{edge label: what it leads to} for the decision or loop head written `code`."""
    head = _node(cfg, code)
    return {e.label: " ".join(cfg.nodes[e.target].raw_code.split())
            for e in cfg.edges if e.source == head.node_id}


@pytest.mark.parametrize("then_body, else_body, sides", [
    ("g = 1;", "\n#if (FEATURE_OFF)\n        g = 3;\n#endif\n", {"Yes": "g = 1", "No": "g = 2"}),
    ("", "g = 1;", {"Yes": "g = 2", "No": "g = 1"}),
    ("\n#if (FEATURE_OFF)\n        g = 3;\n#endif\n", None, {"Yes": "g = 2", "No": "g = 2"}),
])
def test_an_empty_branch_keeps_its_arrow(graph, then_body, else_body, sides):
    tail = "" if else_body is None else " else {" + else_body + "}"
    cfg = graph("int g;\nint f(int a)\n{\n    if (a) {" + then_body + "}" + tail
                + "\n    g = 2;\n    return g;\n}\n", "f")
    assert _sides(cfg, "a") == sides


@pytest.mark.parametrize("loop, head", [
    ("while (!*ready) { }", "!*ready"),
    ("for (int i = 0; i < *ready; ++i) { }", "for (int i = 0; i < *ready; ++i)"),
    ("do { } while (!*ready);", "do-while: !*ready"),
])
def test_an_empty_loop_body_loops_on_its_head(graph, loop, head):
    """The do-while one was worse: Start skipped the loop, its head had no way in."""
    cfg = graph("int f(volatile int *ready)\n{\n    " + loop + "\n    return *ready;\n}\n", "f")
    assert _sides(cfg, head) == {"Yes": head, "No": "return *ready"}
    start = next(n for n in cfg.nodes.values() if n.node_type.name == "START")
    assert _next(cfg, start) == {head}


def test_a_continue_in_a_switch_goes_back_to_its_loop(graph):
    """The switch passed `break` on but dropped `continue`: its box was a dead end."""
    cfg = graph("""int g;
int f(int n)
{
    for (int i = 0; i < n; ++i) {
        switch (i % 3) {
        case 0:
            continue;
        default:
            g += 2;
            break;
        }
        g += 10;
    }
    return g;
}
""", "f")
    assert _next(cfg, _node(cfg, "continue")) == {"for (int i = 0; i < n; ++i)"}
