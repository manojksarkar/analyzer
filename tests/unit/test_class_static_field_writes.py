"""Writes that reach a static data member through a FIELD.

`StatCounters::s_counts.inserts++` is the shape a cache insert has in firmware: a void
function, named for what it does rather than Set/Get, whose only effect is a bump of one
counter inside a shared struct. Its In/Out direction is decided entirely by rule 3 of the
3.17 precedence (model_deriver.main) -- the name carries no Set/Get and there is no return
value -- so it comes down to whether the parser put the member in the WRITE set.

Two independent things have to hold for that, and each one fails the same way:

  * `x++` must register as a write. The operator is the LAST token in the postfix form,
    so a check of tokens[0] alone sees only `++x` (parser._is_inc_dec_op).
  * that write must be carried down the MEMBER_REF_EXPR to its base, or the walker
    records `s_counts` from the `.inserts` access alone, with is_write lost on the way.

Either miss is worse than dropping the access, because the fallback is to record a READ --
and a read-only bump reads out as Out, the exact inverse of the truth.

Parsed from the real SampleCppProject fixture rather than an inline snippet, so the fixture
cannot drift away from the test. Needs libclang, so the module skips without it
(see test_define_conditional.py).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from model_deriver import _name_words  # noqa: E402

DIAG = os.path.join(PROJECT_ROOT, "SampleCppProject", "Layer1", "Diag")
FIXTURE = os.path.join(DIAG, "ClassStatics.cpp")


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


@pytest.fixture(scope="module")
def access(parser_mod):
    """{function name: (writes, reads)} of qualified global names, over the real fixture."""
    from clang import cindex

    # The visibility macros are the project's own; define them away rather than pulling in
    # the macro config, which is not what this test is about.
    args = ["-x", "c++", "-std=c++14", f"-I{DIAG}",
            "-DPUBLIC=", "-DPRIVATE=", "-DPROTECTED="]
    tu = cindex.Index.create().parse(FIXTURE, args=args)

    # The fixture must COMPILE, not merely parse. Clang error-recovers from an access
    # violation and hands the walker a usable AST, so an invalid fixture can sit here for
    # months passing every assertion below -- which is exactly what `statBumpPrivate`
    # writing a private member did until the `friend` declaration was added.
    fatal = [d.spelling for d in tu.diagnostics if d.severity >= 3]
    assert not fatal, f"fixture does not compile: {fatal}"

    P = parser_mod
    # is_project_file gates on the configured component map; the walker's own logic is what
    # is under test. Module-level state is shared with every other test that imports parser,
    # so it is cleared going in and left clean going out.
    real = P.is_project_file
    P.is_project_file = lambda _p: True
    try:
        P.globals_data.clear()
        P.functions.clear()
        P.global_access_reads.clear()
        P.global_access_writes.clear()
        P._visited_global_access_keys.clear()
        P.visit_definitions(tu.cursor)
        P.visit_global_access(tu.cursor)

        def gname(vid):
            return P.globals_data.get(vid, {}).get("qualifiedName", vid)

        out = {}

        def walk(c):
            if c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD) \
                    and c.is_definition() and c.spelling:
                k = P.get_function_key(c)
                out[c.spelling] = (
                    {gname(v) for v in P.global_access_writes.get(k, set())},
                    {gname(v) for v in P.global_access_reads.get(k, set())},
                )
            for ch in c.get_children():
                walk(ch)

        walk(tu.cursor)
        result = out
    finally:
        P.is_project_file = real
        P.globals_data.clear()
        P.functions.clear()
        P.global_access_reads.clear()
        P.global_access_writes.clear()
        P._visited_global_access_keys.clear()
    return result


COUNTS = "StatCounters::s_counts"


class TestTheAggregateMemberIsAGlobal:
    def test_the_struct_typed_static_member_is_recorded(self, access):
        """A static member of aggregate type is storage like any other; the type is
        irrelevant to whether it is an interface."""
        touched = set()
        for writes, reads in access.values():
            touched |= writes | reads
        assert COUNTS in touched


class TestFieldWrites:
    """Each one is void and free of Get/Set, so the write set alone decides direction."""

    def test_postfix_bump_of_a_field_is_a_write(self, access):
        writes, reads = access["statInsertCache"]
        assert COUNTS in writes, "s_counts.inserts++ must be a WRITE -> In"
        assert COUNTS not in reads, "a pure bump is not a read"

    def test_assignment_to_a_field_is_a_write(self, access):
        writes, reads = access["statPrimeCache"]
        assert COUNTS in writes
        assert COUNTS not in reads

    def test_compound_assignment_to_a_field_is_both(self, access):
        """`+=` consults the old value before storing the new one, so the member is in
        both sets -- writing decides the direction, the read still has to be recorded for
        the SWE.4 precondition that sets the member up."""
        writes, reads = access["statAddCacheHits"]
        assert COUNTS in writes
        assert COUNTS in reads

    def test_reading_a_field_is_not_a_write(self, access):
        """The mirror case: a walker that logged every member access as a write would pass
        all three above and fail here."""
        writes, reads = access["statReadCacheHits"]
        assert COUNTS in reads
        assert COUNTS not in writes, "reading a field must not be recorded as a write -> Out"


class TestNamingTheMemberDirectlyStillWorks:
    """The shapes that were already in the fixture, so a regression cannot hide behind the
    new cases."""

    def test_bump_of_a_scalar_member(self, access):
        writes, _ = access["statBumpPublic"]
        assert "StatCounters::s_publicCount" in writes

    def test_read_of_a_scalar_member(self, access):
        writes, reads = access["statReadPublic"]
        assert "StatCounters::s_publicCount" in reads
        assert not writes


class TestTheNameRuleDoesNotDecideThese:
    """Rule 1 runs before the global-access rule, so a false Set/Get match would settle the
    direction without ever consulting the write set."""

    @pytest.mark.parametrize("name", [
        "statInsertCache", "statPrimeCache", "statAddCacheHits", "statReadCacheHits",
    ])
    def test_no_setter_or_getter_word(self, name):
        words = _name_words(name)
        assert "set" not in words, f"'{name}' contains the letters of 'set' but is not a setter"
        assert "get" not in words

    def test_insert_is_one_word(self):
        """The specific trap: 'Insert' would match a substring test for 'set'."""
        assert _name_words("InsertCache") == {"insert", "cache"}
