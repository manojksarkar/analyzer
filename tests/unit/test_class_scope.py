"""What `parser.get_class_scope` records as a function's enclosing class.

Interface tables used to print only the last `::` segment, so `AddOperation::apply`
and `MultiplyOperation::apply` — two real methods in one unit of SampleCppProject —
both rendered as `apply` with nothing to tell them apart. The class IS parsed (it is
in `qualifiedName`), but a qualifiedName string cannot be split back into namespace
vs class parts, so the class is captured separately at parse time where the cursor's
`semantic_parent` kinds are still known.

`get_qualified_name` is deliberately NOT reused or modified here: `make_function_key`
builds every fid from it, so changing it would re-key the whole model.

Needs libclang, so the module skips without it (see test_define_conditional.py).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from utils import scoped_name  # noqa: E402


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (reads argv at import; also configures libclang).

    Never repoints MODULE_BASE_PATH — `parser` is a module-level singleton shared
    with every other test module that imports it.
    """
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


def _scopes(parser_mod, tmp_path, source):
    """Parse a snippet -> {qualifiedName: get_class_scope(cursor)} for every function."""
    from clang import cindex

    src = tmp_path / "t.cpp"
    src.write_text(source, encoding="utf-8")
    tu = cindex.Index.create().parse(str(src), args=["-x", "c++", "-std=c++14"])
    found = {}

    def walk(c):
        if c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD):
            if c.spelling:
                found[parser_mod.get_qualified_name(c)] = parser_mod.get_class_scope(c)
        for ch in c.get_children():
            walk(ch)

    walk(tu.cursor)
    return found


class TestGetClassScope:
    def test_free_function_has_no_class(self, parser_mod, tmp_path):
        got = _scopes(parser_mod, tmp_path, "int add(int a, int b) { return a + b; }")
        assert got["add"] == ""

    def test_method_records_its_class(self, parser_mod, tmp_path):
        got = _scopes(parser_mod, tmp_path, """
            class AddOperation { public: int apply(int a, int b); };
            int AddOperation::apply(int a, int b) { return a + b; }
        """)
        assert got["AddOperation::apply"] == "AddOperation"

    def test_struct_counts_as_a_class(self, parser_mod, tmp_path):
        got = _scopes(parser_mod, tmp_path, "struct Ops { int run() { return 1; } };")
        assert got["Ops::run"] == "Ops"

    def test_namespace_is_dropped(self, parser_mod, tmp_path):
        """The namespace only lengthens the cell; the class is what disambiguates."""
        got = _scopes(parser_mod, tmp_path, """
            namespace pos { class Mgr { public: void start() {} }; }
        """)
        assert got["pos::Mgr::start"] == "Mgr"

    def test_namespaced_free_function_has_no_class(self, parser_mod, tmp_path):
        got = _scopes(parser_mod, tmp_path, "namespace pos { void helper() {} }")
        assert got["pos::helper"] == ""

    def test_nested_class_keeps_the_whole_chain(self, parser_mod, tmp_path):
        got = _scopes(parser_mod, tmp_path, """
            class Outer { public: class Inner { public: void run() {} }; };
        """)
        assert got["Outer::Inner::run"] == "Outer::Inner"

    def test_template_class_method_gets_a_class(self, parser_mod, tmp_path):
        """get_qualified_name misses CLASS_TEMPLATE parents; get_class_scope must not.

        A template class's method has semantic_parent kind CLASS_TEMPLATE, which
        get_qualified_name does not match — so its qualifiedName is the BARE 'run',
        with the class already lost before this fix. get_class_scope matches it, so
        the rendered name is still 'Foo::run'. (get_qualified_name is left alone on
        purpose: fids are built from it.)

        Template arguments are not in the spelling, so Foo<int>::run and Foo<char>::run
        both read 'Foo' — mangled names still keep them apart in the model.
        """
        got = _scopes(parser_mod, tmp_path, """
            template <typename T> class Foo { public: void run() {} };
            void use() { Foo<int> f; f.run(); }
        """)
        assert got["run"] == "Foo", "class lost for a template-class method"
        assert scoped_name("run", got["run"]) == "Foo::run"

    def test_anonymous_namespace_yields_no_class(self, parser_mod, tmp_path):
        """The common '(anonymous)' source is a namespace, and namespaces are dropped."""
        got = _scopes(parser_mod, tmp_path, "namespace { void helper() {} }")
        assert all(scope == "" for scope in got.values())
        assert "(anonymous)" not in "".join(got.values())


class TestSameNameDifferentClass:
    """The reported defect: two same-named methods in one translation unit."""

    SOURCE = """
        class AddOperation      { public: int apply(int a, int b); };
        class MultiplyOperation { public: int apply(int a, int b); };
        int AddOperation::apply(int a, int b)      { return a + b; }
        int MultiplyOperation::apply(int a, int b) { return a * b; }
    """

    def test_each_method_keeps_its_own_class(self, parser_mod, tmp_path):
        got = _scopes(parser_mod, tmp_path, self.SOURCE)
        assert got["AddOperation::apply"] == "AddOperation"
        assert got["MultiplyOperation::apply"] == "MultiplyOperation"

    def test_display_names_are_distinguishable(self, parser_mod, tmp_path):
        """End to end: what the interface table's Interface Name cell will show."""
        got = _scopes(parser_mod, tmp_path, self.SOURCE)
        rendered = {scoped_name(qn, cls) for qn, cls in got.items()}
        assert "AddOperation::apply" in rendered
        assert "MultiplyOperation::apply" in rendered
        assert "apply" not in rendered
