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
    return _walk(parser_mod, FIXTURE)[0]


def _walk(P, fixture):
    """({function name: (writes, reads)}, {function name: written pointer params}) for one
    translation unit of the real fixture."""
    from clang import cindex

    # The visibility macros are the project's own; define them away rather than pulling in
    # the macro config, which is not what this test is about.
    args = ["-x", "c++", "-std=c++14", f"-I{DIAG}",
            "-DPUBLIC=", "-DPRIVATE=", "-DPROTECTED="]
    tu = cindex.Index.create().parse(fixture, args=args)

    # The fixture must COMPILE, not merely parse. Clang error-recovers from an access
    # violation and hands the walker a usable AST, so an invalid fixture can sit here for
    # months passing every assertion below -- which is exactly what `statBumpPrivate`
    # writing a private member did until the `friend` declaration was added.
    fatal = [d.spelling for d in tu.diagnostics if d.severity >= 3]
    assert not fatal, f"fixture does not compile: {fatal}"

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
        P.param_writes.clear()
        P.visit_definitions(tu.cursor)
        P.visit_global_access(tu.cursor)

        def gname(vid):
            return P.globals_data.get(vid, {}).get("qualifiedName", vid)

        out, params, ids = {}, {}, {}

        def walk(c):
            if c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD) \
                    and c.is_definition() and c.spelling:
                k = P.get_function_key(c)
                out[c.spelling] = (
                    {gname(v) for v in P.global_access_writes.get(k, set())},
                    {gname(v) for v in P.global_access_reads.get(k, set())},
                )
                params[c.spelling] = set(P.param_writes.get(k, set()))
                ids[c.spelling] = (set(P.global_access_writes.get(k, set()))
                                   | set(P.global_access_reads.get(k, set())))
            for ch in c.get_children():
                walk(ch)

        walk(tu.cursor)
        # The entry each qualified name is recorded under where this TU holds its definition.
        defs = {g["qualifiedName"]: vid for vid, g in P.globals_data.items()
                if g.get("isDefinition")}
        result = (out, params, ids, defs)
    finally:
        P.is_project_file = real
        P.globals_data.clear()
        P.functions.clear()
        P.global_access_reads.clear()
        P.global_access_writes.clear()
        P._visited_global_access_keys.clear()
        P.param_writes.clear()
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


# ---------------------------------------------------------------------------------------
# A static member reached THROUGH AN OBJECT: `this->s_x`, `obj.s_x`, `ref.s_x`, `ptr->s_x`.
# Clang gives this spelling a MEMBER_REF_EXPR, like a field, where `Cls::s_x` and a bare
# `s_x` give a DECL_REF_EXPR -- and the walker used to record only the second. Fixture:
# Diag/StaticViaObject.{h,cpp} and StaticViaObjectUser.cpp (a second unit, so a second TU).
# ---------------------------------------------------------------------------------------

VIA = os.path.join(DIAG, "StaticViaObject.cpp")
VIA_USER = os.path.join(DIAG, "StaticViaObjectUser.cpp")

MARK = "ViaCounters::s_mark"                    # protected
PUB = "ViaCounters::s_public"
PAIR = "ViaCounters::s_pair"
PRIV = "ViaCounters::s_private"
SEEN = "ViaCounters::s_seenOnlyViaObject"
CAP = "ViaLimits::s_cap"                        # in-class initialised, in an orphan header


@pytest.fixture(scope="module")
def via(parser_mod):
    """Both translation units, walked one at a time as the parser walks them."""
    own = _walk(parser_mod, VIA)
    other = _walk(parser_mod, VIA_USER)
    merged = tuple({**a, **b} for a, b in zip(own[:3], other[:3]))
    return merged + (own[3],)


class TestStaticMemberThroughAnObject:
    """Every function's EXACT read and write sets. Exact, not `in`: a global that must stay
    out -- the object named only to reach the member -- is as much the point as the member."""

    @pytest.mark.parametrize("fn, writes, reads", [
        # this->
        ("bumpThis",             {MARK}, set()),
        ("peekThis",             set(),  {MARK}),
        ("orThis",               {MARK}, {MARK}),          # |= reads the old value
        ("bumpPairThis",         {PAIR}, set()),           # through a field of the member
        ("getAndBump",           {MARK}, {MARK}),
        ("bumpAndReturn",        {MARK}, {MARK}),
        # through a local object, a pointer, a reference, an array element
        ("viaBumpLocalObject",   {PUB},  set()),
        ("viaBumpByPointer",     {PUB},  {PUB}),           # +=
        ("viaBumpPrivateByRef",  {PRIV}, set()),
        ("viaBumpArrayElement",  {PUB},  set()),
        # through a global object / a global pointer: those two are in NEITHER set
        ("viaBumpGlobalObject",  {PUB},  set()),
        ("viaBumpGlobalPointer", {PUB},  set()),
        # an in-class-initialised static with no definition anywhere
        ("viaReadCap",           set(),  {CAP}),
        # from the other translation unit, where the reference resolves to the declaration
        ("markFromDerived",      {MARK}, set()),
        ("viaReadFromOtherUnit", set(),  {SEEN}),
    ])
    def test_the_member_is_recorded(self, via, fn, writes, reads):
        got_w, got_r = via[0][fn]
        assert got_w == writes, f"{fn} writes"
        assert got_r == reads, f"{fn} reads"

    @pytest.mark.parametrize("fn", [
        "touchField",       # this->m_count is a FIELD of the object, not a global
        "callsBumpThis",    # writes only through a callee -- phase 2's transitive set
        "viaDriveDerived",  # calls only
        "viaDriveAll",      # calls only
    ])
    def test_nothing_is_recorded(self, via, fn):
        assert via[0][fn] == (set(), set()), fn

    @pytest.mark.parametrize("fn", ["viaBumpByPointer", "viaBumpPrivateByRef"])
    def test_the_object_is_not_an_output_parameter(self, via, fn):
        """`p->s_public += 2` stores into the member, which does not live inside `*p`. The
        FIELD form (`p->n = 1`) does write through p and is recorded; this one must not be."""
        assert via[1][fn] == set(), fn

    def test_this_arrow_lands_on_the_same_entry_as_the_qualified_name(self, via):
        """`this->s_mark` must resolve to the entry `ViaCounters::s_mark` resolves to -- the
        DEFINITION where the translation unit holds one -- or one variable is split in two,
        with its reads and writes divided between the halves."""
        defs = via[3]
        assert via[2]["bumpThis"] == {defs[MARK]}
        assert via[2]["viaBumpGlobalObject"] == {defs[PUB]}


class TestTheFieldFormIsUnchanged:
    """The FIELD branch shares the MEMBER_REF_EXPR case with the new one; a write through a
    field must still reach its base -- including when the base is a static member reached
    through `this->` (bumpPairThis above) or named directly (below)."""

    def test_field_of_a_named_static_member_is_still_a_write(self, access):
        writes, _ = access["statInsertCache"]
        assert COUNTS in writes

    def test_a_named_protected_member_through_a_field_is_still_a_write(self, access):
        writes, reads = access["bumpNsPlain"]
        assert writes == {"NsCounters::var"} and not reads


# ---------------------------------------------------------------------------------------
# A method's own member variables (review SWE3-025, SWE3_WIKI SWE3-UI-05 rows 3-4): a void
# method that writes one -- itself, through a method it calls on its own object, or through
# a local pointer it points there -- is In, like one that writes a global. Fixture:
# Direction/MemberWrites.{h,cpp}; App/Main.cpp calls every public method of MwTable.
# ---------------------------------------------------------------------------------------

MW_DIR = os.path.join(PROJECT_ROOT, "SampleCppProject", "Layer1", "Direction")
MW = os.path.join(MW_DIR, "MemberWrites.cpp")


def _clear_member_state(P):
    for store in (P.globals_data, P.functions, P.global_access_reads, P.global_access_writes,
                  P.param_writes, P.member_writes, P.self_calls, P._local_aliases,
                  P.call_graph, P.reverse_call_graph):
        store.clear()
    P._visited_global_access_keys.clear()
    P._visited_call_keys.clear()


@pytest.fixture(scope="module")
def members(parser_mod):
    """{method: {"members", "globals", "self", "returnType"}} over the real fixture: the own
    members it writes, the globals it writes, the methods it calls on its own object."""
    from clang import cindex

    P = parser_mod
    tu = cindex.Index.create().parse(MW, args=["-x", "c++", "-std=c++14", f"-I{MW_DIR}"])
    fatal = [d.spelling for d in tu.diagnostics if d.severity >= 3]
    assert not fatal, f"fixture does not compile: {fatal}"
    real = P.is_project_file
    P.is_project_file = lambda _p: True
    try:
        _clear_member_state(P)
        P.visit_definitions(tu.cursor)
        P.visit_global_access(tu.cursor)
        P.visit_calls(tu.cursor)
        names = {}
        for c in tu.cursor.walk_preorder():
            if c.kind == cindex.CursorKind.CXX_METHOD and c.is_definition():
                names[P.get_function_key(c)] = (c.spelling, c.result_type.spelling)
        out = {}
        for k, (name, ret) in names.items():
            out[name] = {
                "members": set(P.member_writes.get(k, ())),
                "globals": {P.globals_data.get(v, {}).get("qualifiedName", v)
                            for v in P.global_access_writes.get(k, ())},
                "self": {names.get(c, (c,))[0] for c, _ in P.self_calls.get(k, ())},
                "returnType": ret,
            }
    finally:
        P.is_project_file = real
        _clear_member_state(P)
    return out


class TestOwnMemberWrites:
    """Every method's EXACT sets: what must stay out -- another object's member, a pointer a
    function returns -- is as much the point as what goes in."""

    @pytest.mark.parametrize("fn, written", [
        ("mwDeleteEntry", {"MwTable::m_table", "MwTable::m_used"}),   # m_x[i] = 0, m_x--
        ("mwBumpBase",    {"MwBase::m_cx"}),                          # MwBase::m_cx.a++
        ("mwMarkRow",     {"MwTable::m_rows"}),                       # a local reference to it
        ("mwBaseReset",   {"MwBase::m_baseCount"}),
        ("mwHelperReset", {"MwHelper::m_n"}),
        ("mwClearAll",    set()),     # only through mwDeleteEntry: Phase 2 follows it
        ("mwResetAll",    set()),     # only through MwBase::mwBaseReset
        ("mwInsertX",     set()),     # a global, not a member (below)
        ("mwDump",        set()),     # reads only
        ("mwCopyTo",      set()),     # other.m_used: another object's
        ("mwResetHelper", set()),     # helper.mwHelperReset(): another object's
        ("mwFind",        set()),     # returns &m_rows[id]: an address, no write
        ("mwMarkFound",   set()),     # through a pointer mwFind returns: not followed
    ])
    def test_the_members_written(self, members, fn, written):
        assert members[fn]["members"] == written, fn

    def test_a_global_written_through_a_local_pointer(self, members):
        """`MwEntry* bbx = &MwBase::s_block.xa[id]; bbx->a = id;` writes the static member."""
        assert members["mwInsertX"]["globals"] == {"MwBase::s_block"}

    def test_no_other_method_writes_a_global(self, members):
        assert {fn for fn, m in members.items() if m["globals"]} == {"mwInsertX"}

    @pytest.mark.parametrize("fn, called", [
        ("mwClearAll",    {"mwDeleteEntry"}),   # f()
        ("mwResetAll",    {"mwBaseReset"}),     # Base::f()
        ("mwMarkFound",   {"mwFind"}),
        ("mwResetHelper", set()),               # helper.f(): not its own object
    ])
    def test_the_methods_called_on_its_own_object(self, members, fn, called):
        assert members[fn]["self"] == called, fn


class TestMemberWritesDecideDirection:
    """Phase 2 (`derive_directions`) over the parser's facts for the fixture."""

    @pytest.fixture(scope="class")
    def directions(self, members):
        from model_deriver import derive_directions

        functions = {
            fn: {"qualifiedName": f"MwTable::{fn}", "returnType": m["returnType"],
                 "writesMembers": sorted(m["members"]),
                 "selfCallIds": sorted(m["self"]),
                 "writesGlobalIds": sorted(m["globals"])}
            for fn, m in members.items()
        }
        for f in functions.values():
            for k in ("writesMembers", "selfCallIds", "writesGlobalIds"):
                if not f[k]:
                    del f[k]
        derive_directions(functions, {})
        return functions

    @pytest.mark.parametrize("fn, direction", [
        ("mwDeleteEntry", "In"),
        ("mwClearAll",    "In"),
        ("mwResetAll",    "In"),
        ("mwBumpBase",    "In"),
        ("mwInsertX",     "In"),
        ("mwMarkRow",     "In"),
        ("mwDump",        "Out"),
        ("mwCopyTo",      "Out"),
        ("mwResetHelper", "Out"),
        ("mwMarkFound",   "Out"),
        ("mwFind",        "Out"),    # returns a value
    ])
    def test_direction(self, directions, fn, direction):
        assert directions[fn]["direction"] == direction, directions[fn]["directionReason"]

    def test_the_reason_names_the_members(self, directions):
        assert directions["mwDeleteEntry"]["directionReason"] == \
            "In: writes member variable(s) m_table, m_used directly."
        assert directions["mwClearAll"]["directionReason"] == \
            "In: writes member variable(s) through its own methods: " \
            "m_table (via mwDeleteEntry); m_used (via mwDeleteEntry)."

    def test_a_global_still_comes_first(self, directions):
        assert directions["mwInsertX"]["directionReason"].startswith("In: writes global(s)")

    def test_a_value_returned_still_means_out(self):
        """Rule 2 is before the member rule: writing a member does not make it In."""
        from model_deriver import derive_directions

        fns = {"f": {"qualifiedName": "C::count", "returnType": "int",
                     "writesMembers": ["C::m_n"]}}
        derive_directions(fns, {})
        assert fns["f"]["direction"] == "Out"
