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
