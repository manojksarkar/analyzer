"""Functions published by a function-pointer table count as public.

`_fn_is_private` equates "public" with "has a caller in another file". A layered-firmware
entry point reached only through a registration table —

    static const fp_t table[] = { fn1, fn2 };
    table[0]();

— has `calledByIds == []`, so it was relabelled private, given a `PIF_` id, and dropped from
the interface table and behaviour diagrams: missing from the very ASPICE artifact it belongs
in. Membership in the table is sufficient evidence of publicness; which entry `table[0]()`
reaches is statically unknowable and is NOT resolved.

The rule is by SHAPE, not by file: a file-scope initializer counts even when the table sits
in the same .c as the function (the canonical firmware pattern).

Parser tests need libclang, so those skip without it (see test_define_conditional.py).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from model_deriver import _fn_is_private  # noqa: E402
from incremental.parse_merge import _merge_address_taken, _apply_address_taken  # noqa: E402


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (reads argv at import; also configures libclang)."""
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


def _address_taken(parser_mod, tmp_path, source):
    """Parse a snippet -> set of function names whose address is taken anywhere in it."""
    from clang import cindex

    src = tmp_path / "t.cpp"
    src.write_text(source, encoding="utf-8")
    tu = cindex.Index.create().parse(str(src), args=["-x", "c++"])
    hits: set = set()

    # is_project_file() gates on the configured component map, which a tmp_path file is not
    # in; the walker's own logic is what's under test, so resolve names directly.
    def on_hit(func_key):
        hits.add(func_key)

    real = parser_mod.is_project_file
    parser_mod.is_project_file = lambda _p: True
    try:
        parser_mod._walk_address_taken(tu.cursor, lambda k: on_hit(k))
    finally:
        parser_mod.is_project_file = real
    # func_key is the mangled name; map back to something readable.
    names = set()

    def walk(c):
        if c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD) and c.spelling:
            if parser_mod.get_function_key(c) in hits:
                names.add(c.spelling)
        for ch in c.get_children():
            walk(ch)

    walk(tu.cursor)
    return names


class TestDetection:
    def test_initializer_table_publishes_its_entries(self, parser_mod, tmp_path):
        got = _address_taken(parser_mod, tmp_path, """
            typedef int (*fp_t)(int, int);
            static int fn1(int a, int b) { return a + b; }
            static int fn2(int a, int b) { return a * b; }
            static const fp_t table[] = { fn1, fn2 };
        """)
        assert got == {"fn1", "fn2"}

    def test_designated_struct_initializer(self, parser_mod, tmp_path):
        got = _address_taken(parser_mod, tmp_path, """
            typedef void (*hook_t)(void);
            struct Ops { hook_t init; hook_t stop; };
            static void ftlInit(void) {}
            static void ftlStop(void) {}
            static struct Ops g_ops = { ftlInit, ftlStop };
        """)
        assert got == {"ftlInit", "ftlStop"}

    def test_explicit_address_of_in_a_body(self, parser_mod, tmp_path):
        got = _address_taken(parser_mod, tmp_path, """
            static int helper(int x) { return x; }
            void use() { int (*p)(int) = &helper; (void)p; }
        """)
        assert got == {"helper"}

    def test_bare_name_assigned_in_a_body(self, parser_mod, tmp_path):
        got = _address_taken(parser_mod, tmp_path, """
            static int helper(int x) { return x; }
            void use() { int (*p)(int) = helper; (void)p; }
        """)
        assert got == {"helper"}


class TestCalleeSuppression:
    """A call is not an address-take.

    clang wraps a call's callee as CALL_EXPR -> UNEXPOSED_EXPR -> DECL_REF_EXPR, so the
    "this is a callee" flag has to propagate THROUGH the wrapper. If it stops one level
    down, every direct call reads as an address-take.
    """

    def test_direct_call_is_not_an_address_take(self, parser_mod, tmp_path):
        got = _address_taken(parser_mod, tmp_path, """
            static int direct(int x) { return x; }
            void use() { direct(2); }
        """)
        assert got == set()

    def test_call_in_a_file_scope_initializer_is_not_an_address_take(self, parser_mod, tmp_path):
        """`static int g = compute();` must NOT publish compute.

        The file-scope path counts regardless of file, so this is where a broken
        suppression would actually leak.
        """
        got = _address_taken(parser_mod, tmp_path, """
            static int compute(void) { return 7; }
            static int g_limit = compute();
        """)
        assert got == set()

    def test_call_through_a_pointer_variable_publishes_nothing(self, parser_mod, tmp_path):
        got = _address_taken(parser_mod, tmp_path, """
            typedef int (*fp_t)(int, int);
            static int fn1(int a, int b) { return a + b; }
            static const fp_t table[] = { fn1 };
            void use() { table[0](1, 2); }
        """)
        # fn1 comes from the TABLE, not from the table[0]() call site.
        assert got == {"fn1"}

    def test_arguments_of_a_call_are_still_scanned(self, parser_mod, tmp_path):
        """Only the CALLEE is suppressed — a function passed as an argument is a real take."""
        got = _address_taken(parser_mod, tmp_path, """
            static int cmp(int a, int b) { return a - b; }
            static void sorter(int (*f)(int, int)) { (void)f; }
            void use() { sorter(cmp); }
        """)
        assert got == {"cmp"}


class TestPrivacyRule:
    """`_fn_is_private` — pure, no libclang needed."""

    BASE = "/proj"

    def _fn(self, **kw):
        f = {"location": {"file": "a/b/Ops.cpp"}, "calledByIds": []}
        f.update(kw)
        return f

    def test_no_caller_and_no_table_stays_private(self):
        assert _fn_is_private(self._fn(), {}, self.BASE) is True

    def test_table_membership_makes_it_public(self):
        f = self._fn(addressTakenByUnits=["Cross|OpsTable"])
        assert _fn_is_private(f, {}, self.BASE) is False

    def test_explicit_private_still_wins_over_the_table(self):
        """A source-level PRIVATE annotation stays authoritative."""
        f = self._fn(visibility="private", addressTakenByUnits=["Cross|OpsTable"])
        assert _fn_is_private(f, {}, self.BASE) is True

    def test_empty_list_does_not_make_it_public(self):
        assert _fn_is_private(self._fn(addressTakenByUnits=[]), {}, self.BASE) is True


class TestIncrementalReplay:
    """Without replay a narrowed parse loses the registration, the function flips back to
    private, and the same source yields a different document run to run."""

    ENTITY_FILES = {"Cross|OpsTable|opsAdd|int,int": "Layer1/Poly/OpsTable.cpp",
                    "Other|Mod|fn|": "Layer1/Other/Mod.cpp"}

    def test_baseline_record_survives_when_its_file_was_not_reparsed(self):
        got = _merge_address_taken(
            [["Cross|OpsTable|opsAdd|int,int", "Cross|OpsClient"]], [],
            self.ENTITY_FILES, {"layer1/other/mod.cpp"},
        )
        assert got == [["Cross|OpsTable|opsAdd|int,int", "Cross|OpsClient"]]

    def test_fresh_record_replaces_baseline_for_a_reparsed_file(self):
        drop = {"layer1/poly/opstable.cpp"}
        got = _merge_address_taken(
            [["Cross|OpsTable|opsAdd|int,int", "Cross|Old"]],
            [["Cross|OpsTable|opsAdd|int,int", "Cross|New"]],
            self.ENTITY_FILES, drop,
        )
        assert got == [["Cross|OpsTable|opsAdd|int,int", "Cross|New"]]

    def test_apply_reattaches_units_to_functions(self):
        functions = {"Cross|OpsTable|opsAdd|int,int": {}, "Other|Mod|fn|": {}}
        _apply_address_taken(functions, [["Cross|OpsTable|opsAdd|int,int", "Cross|OpsClient"]],
                             self.ENTITY_FILES, {"layer1/poly/opstable.cpp"})
        assert functions["Cross|OpsTable|opsAdd|int,int"]["addressTakenByUnits"] == ["Cross|OpsClient"]
        assert "addressTakenByUnits" not in functions["Other|Mod|fn|"]

    def test_apply_clears_a_stale_flag_for_a_reparsed_file(self):
        """Deletion semantics: a registration removed from a table that WAS re-parsed must
        disappear. The fresh records are authoritative for those files."""
        functions = {"Cross|OpsTable|opsAdd|int,int": {"addressTakenByUnits": ["Cross|Gone"]}}
        _apply_address_taken(functions, [], self.ENTITY_FILES, {"layer1/poly/opstable.cpp"})
        assert "addressTakenByUnits" not in functions["Cross|OpsTable|opsAdd|int,int"]

    def test_apply_keeps_the_flag_when_the_file_was_not_reparsed(self):
        """The regression this guards. `_merge_address_taken` can only carry a baseline
        record forward if the baseline HAS one, so a MISSING baseline address_taken
        artifact arrives here as an empty record list -- indistinguishable from a
        deliberate removal. Clearing on that evidence wiped the field from functions in
        files nobody touched.

        It is not hypothetical: `address_taken` was registered in DB_BACKED_PARSE only in
        421f4e5, so any version generated in database mode before that has no such parse
        snapshot. Chaining an incremental run off one flipped every function published
        solely through a file-scope pointer table to private -- `_fn_is_private` keeps
        those public through this field alone, nothing CALLS them by name -- and they left
        the interface tables, the diagrams and the document. Reproduced end to end before
        the fix, and B == A == baseline after it.
        """
        functions = {"Cross|OpsTable|opsAdd|int,int":
                     {"addressTakenByUnits": ["Cross|OpsClient"]}}
        _apply_address_taken(functions, [], self.ENTITY_FILES, {"layer1/other/mod.cpp"})
        assert functions["Cross|OpsTable|opsAdd|int,int"]["addressTakenByUnits"] == ["Cross|OpsClient"]

    def test_apply_leaves_untouched_files_alone_while_clearing_reparsed_ones(self):
        """Both halves in one merge, which is the shape a real narrowed parse produces."""
        functions = {"Cross|OpsTable|opsAdd|int,int": {"addressTakenByUnits": ["Cross|OpsClient"]},
                     "Other|Mod|fn|": {"addressTakenByUnits": ["Other|Gone"]}}
        _apply_address_taken(functions, [], self.ENTITY_FILES, {"layer1/other/mod.cpp"})
        assert functions["Cross|OpsTable|opsAdd|int,int"]["addressTakenByUnits"] == ["Cross|OpsClient"]
        assert "addressTakenByUnits" not in functions["Other|Mod|fn|"]
