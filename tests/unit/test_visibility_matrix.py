"""What is published, one assertion per cell of SampleCppProject/Layer1/Access/AccessMatrix.

ONE rule decides whether an entry reaches the interface table (2026-10-13): something in
ANOTHER UNIT uses it -- a caller for a function (or its address in a file-scope table), a
reader or writer for a global. Nothing else: no PRIVATE / PROTECTED / PUBLIC macro and no C++
access is consulted. Two phases are still asserted apart, because they fail differently:

  * PHASE 1 (parser._function_visibility) RECORDS the marking as `public` or `private` --
    two values, one bit. A PRIVATE/PROTECTED/PUBLIC macro wins wherever it exists; otherwise
    a member takes its C++ access, written label or language default; a free function has
    neither, and unmarked records as `public`. It is a fact about the source and decides
    nothing any more.
  * PHASE 2 (model_deriver._fn_is_private) applies the rule, and `_enrich_interfaces`
    writes its answer into `visibility` -- over the marking, in both directions -- because
    every view and exporter filter tests `visibility == "private"`.

Until 2026-10-13 a marking could restrict: `private` was buried whatever called it (a friend,
a derived class in another unit), which is what the "private, cross-file caller" cell was.

Phase 1 is asserted against the real fixture rather than an inline snippet, so the fixture
cannot drift away from the test. It cannot be read back out of the model instead: phase 2
overwrites `visibility`, which hides exactly the mistakes this file exists to catch.

The Access component is outside the e2e run's scope (group "Layer1.My Sample"), so these
cells have no e2e coverage -- this is the only place they are checked.

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

from model_deriver import _fn_is_private  # noqa: E402

ACCESS = os.path.join(PROJECT_ROOT, "SampleCppProject", "Layer1", "Access")

# qualified name -> what phase 1 must record.
MATRIX = {
    # Free functions: no access specifier exists, so only a macro speaks. Unmarked records
    # as "public" -- the model carries two values, and the rule is one bit: private or not.
    "mtxUnmarkedCalled":                     "public",
    "mtxUnmarkedUncalled":                   "public",
    "mtxPublicUncalled":                     "public",
    # A class with no label at all -- the language default is private, and it binds
    # another unit exactly as a written label does.
    "MtxNoLabel::hidden":                    "private",
    # A struct: same four cases, but the language default is public.
    "MtxStruct::plain":                      "public",
    "MtxStruct::exposed":                    "public",
    "MtxStruct::exposedUncalled":            "public",
    "MtxStruct::guarded":                    "private",   # protected: collapses to private
    "MtxStruct::sealed":                     "private",
    # The macro wins over the label, in both directions.
    "MtxConflict::markedPrivateUnderPublic": "private",
    "MtxConflict::markedPublicUnderPrivate": "public",
    # The cross-file callers, in the neighbouring unit.
    "MtxDerived::useGuarded":                "public",
    "mtxCallSealed":                         "public",
    "mtxCallMarkedPublic":                   "public",
    "mtxUseDerived":                         "public",
    # AccessCompanion.*: declared public in one header, defined in the .cpp. Phase 1 reads
    # the access off the out-of-line definition, so both record "public" and only WHERE the
    # caller sits separates them in phase 2 -- companionFromHeader is reached from the
    # companion header (same unit, buried), companionFromOtherUnit from another unit.
    "CompanionOwner::companionFromHeader":    "public",
    "CompanionOwner::companionFromOtherUnit": "public",
    "companionEntry":                        "public",
    "companionUserProbe":                    "public",
}


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (reads argv at import; also configures libclang)."""
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser as P
    except Exception as e:                                  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


@pytest.fixture(scope="module")
def recorded(parser_mod):
    """{qualified name: what _function_visibility records}, over the real fixture."""
    from clang import cindex

    P = parser_mod
    args = ["-x", "c++", "-std=c++14", f"-I{ACCESS}",
            "-DPUBLIC=", "-DPRIVATE=", "-DPROTECTED="]
    out = {}
    for src in ("AccessMatrix.cpp", "AccessMatrixUser.cpp",
                "AccessCompanion.cpp", "AccessCompanionUser.cpp"):
        path = os.path.join(ACCESS, src)
        tu = cindex.Index.create().parse(path, args=args)

        # The fixture must COMPILE, not merely parse. Clang error-recovers from an access
        # violation and still hands over a usable AST, so an invalid fixture would sit here
        # passing every assertion below -- which is the whole point of the `friend`
        # declarations that let mtxCallSealed and mtxCallMarkedPublic reach their members.
        fatal = [d.spelling for d in tu.diagnostics if d.severity >= 3]
        assert not fatal, f"{src} does not compile: {fatal}"

        def walk(c):
            if (c.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD)
                    and c.is_definition() and c.location.file
                    and os.path.basename(c.location.file.name) == src):
                out[P.get_qualified_name(c)] = P._function_visibility(c)
            for ch in c.get_children():
                walk(ch)

        walk(tu.cursor)
    return out


# ---------------------------------------------------------------------------
# Phase 1 — what gets recorded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("qname,expected", sorted(MATRIX.items()))
def test_phase_one_records(recorded, qname, expected):
    assert qname in recorded, f"'{qname}' not found in the fixture -- has it been renamed?"
    assert recorded[qname] == expected, (
        f"'{qname}' recorded {recorded[qname]!r}, expected {expected!r}")


def test_no_protected_is_ever_recorded(recorded):
    """`protected` is collapsed at the point of recording, so no later phase sees it."""
    leaked = {k: v for k, v in recorded.items() if v == "protected"}
    assert not leaked, f"'protected' reached the model: {leaked}"


def test_a_neighbours_macro_does_not_leak_downwards(recorded):
    """The 5-line backward scan must not cross a declaration boundary.

    `MtxNoLabel::hidden` sits four lines below `PUBLIC int mtxPublicUncalled() {...}` in
    AccessMatrix.cpp. Before _detect_visibility stopped at the `}` above it, the scan
    walked straight past that function and adopted its macro, recording a C++-private
    method as public -- publishable the moment anything called it across files.
    """
    assert recorded["MtxNoLabel::hidden"] == "private"


# ---------------------------------------------------------------------------
# Phase 2 — what the recording buys
# ---------------------------------------------------------------------------

BASE = os.path.join(PROJECT_ROOT, "SampleCppProject")


def _fn(visibility=None, callers=(), address_taken=None, file="Layer1/Access/AccessMatrix.cpp"):
    f = {"location": {"file": os.path.join(BASE, file)}, "calledByIds": list(callers)}
    if visibility:
        f["visibility"] = visibility
    if address_taken:
        f["addressTakenByUnits"] = list(address_taken)
    return f


OTHER = "Layer1.App|Main|caller|"
SAME = "Layer1.Access|AccessMatrix|sibling|"
# Same UNIT, different FILE: inline code in the companion header of AccessMatrix.cpp.
# make_unit_key strips the extension, so this caller is inside the callee's own unit --
# which is why it does not publish it, though a file-keyed rule said it did.
COMPANION = "Layer1.Access|AccessMatrix|headerInline|"
WORLD = {
    OTHER: _fn(file="Layer1/App/Main.cpp"),
    SAME: _fn(),
    COMPANION: _fn(file="Layer1/Access/AccessMatrix.h"),
}


@pytest.mark.parametrize("label,fn,expected_private", [
    ("private, no caller",            _fn("private"),                       True),
    ("private, same-file caller only", _fn("private", [SAME]),              True),
    ("private, companion-header caller only", _fn("private", [COMPANION]),  True),
    # The cell that changed on 2026-10-13: a marking no longer restricts. A friend, or a
    # derived class in another unit calling a protected method, is a user in another unit.
    ("private, cross-file caller",    _fn("private", [OTHER]),              False),
    ("public, cross-file caller",     _fn("public", [OTHER]),               False),
    ("public, same-file caller only", _fn("public", [SAME]),                True),
    ("public, companion-header caller only", _fn("public", [COMPANION]),  True),
    ("public, companion + cross-unit",  _fn("public", [COMPANION, OTHER]), False),
    ("public, no caller",             _fn("public"),                        True),
    ("unmarked, cross-file caller",   _fn(None, [OTHER]),                   False),
    ("unmarked, no caller",           _fn(None),                            True),
    ("address-taken, no caller",      _fn(None, (), ["Cross|OpsTable"]),    False),
    ("private but address-taken",     _fn("private", (), ["Cross|OpsTable"]), False),
])
def test_phase_two_buckets(label, fn, expected_private):
    assert _fn_is_private(fn, WORLD, BASE) is expected_private, label


def test_public_no_longer_guarantees_a_row():
    """A marking cannot publish.

    `PUBLIC` used to short-circuit _fn_is_private and publish a function whatever the call
    graph said. It no longer does, so `public` and unmarked are indistinguishable here.
    """
    assert _fn_is_private(_fn("public"), WORLD, BASE) is True
    assert _fn_is_private(_fn(None), WORLD, BASE) is True


@pytest.mark.parametrize("marking", ["private", "public", None])
def test_no_marking_changes_the_answer(marking):
    """The whole rule: used from another unit, or not. Three markings, the same two answers."""
    assert _fn_is_private(_fn(marking, [OTHER]), WORLD, BASE) is False
    assert _fn_is_private(_fn(marking, [SAME]), WORLD, BASE) is True
    assert _fn_is_private(_fn(marking), WORLD, BASE) is True


def test_the_answer_is_written_over_the_marking():
    """Every view and exporter filter tests `visibility == "private"`. A function marked
    private that another unit calls must therefore not keep that marking, or it would be
    published by the rule and dropped by every reader of it -- and one marked public that
    nobody outside calls must get it."""
    import model_deriver as md
    functions = {
        "Layer1.Access|AccessMatrix|sealedButCalled|": dict(
            _fn("private", [OTHER]), qualifiedName="sealedButCalled", parameters=[]),
        "Layer1.Access|AccessMatrix|publicUncalled|": dict(
            _fn("public"), qualifiedName="publicUncalled", parameters=[]),
        OTHER: dict(WORLD[OTHER], qualifiedName="caller", parameters=[]),
    }
    functions[OTHER]["location"]["line"] = 1
    for f in functions.values():
        f["location"].setdefault("line", 1)
    idx = md._build_interface_index(BASE, functions, {}, "Proj", None)
    md._enrich_interfaces(BASE, "Proj", functions, {}, idx, None)
    called = functions["Layer1.Access|AccessMatrix|sealedButCalled|"]
    uncalled = functions["Layer1.Access|AccessMatrix|publicUncalled|"]
    assert (called["visibility"], called["interfaceId"][:3]) == ("public", "IF_")
    assert (uncalled["visibility"], uncalled["interfaceId"][:4]) == ("private", "PIF_")
    # ...and deriving again from the model it wrote gives the same answer
    idx = md._build_interface_index(BASE, functions, {}, "Proj", None)
    md._enrich_interfaces(BASE, "Proj", functions, {}, idx, None)
    assert (called["visibility"], uncalled["visibility"]) == ("public", "private")


# ---------------------------------------------------------------------------
# Phase 2 — globals (S3-7): published only when a function in ANOTHER unit uses it
# ---------------------------------------------------------------------------

from model_deriver import _glb_is_private, _glb_used_outside  # noqa: E402

G_DEF = "Layer1.Access|AccessMatrix|g_x"            # defined in AccessMatrix.cpp


def _glb(qn="g_x", file="Layer1/Access/AccessMatrix.cpp", visibility=None, definition=True):
    g = {"qualifiedName": qn, "location": {"file": os.path.join(BASE, file)}}
    if visibility:
        g["visibility"] = visibility
    if not definition:
        g["isDefinition"] = False
    return g


def _user(file, reads=(), writes=()):
    return {"location": {"file": os.path.join(BASE, file)},
            "readsGlobalIds": list(reads), "writesGlobalIds": list(writes)}


def _private(globals_data, functions_data, vid=G_DEF):
    used = _glb_used_outside(functions_data, globals_data, BASE)
    return _glb_is_private(vid, globals_data[vid], used)


@pytest.mark.parametrize("label,users,visibility,expected_private", [
    ("read from another unit",           [_user("Layer1/App/Main.cpp", reads=[G_DEF])], None, False),
    ("written from another unit",        [_user("Layer1/App/Main.cpp", writes=[G_DEF])], None, False),
    ("used by its own unit only",        [_user("Layer1/Access/AccessMatrix.cpp", reads=[G_DEF])], None, True),
    ("used from its companion header",   [_user("Layer1/Access/AccessMatrix.h", reads=[G_DEF])], None, True),
    ("used by nobody",                   [], None, True),
    ("PUBLIC, used by its own unit only", [_user("Layer1/Access/AccessMatrix.cpp", reads=[G_DEF])], "public", True),
    # Changed on 2026-10-13, with the function rule: a marking no longer restricts.
    ("PRIVATE, read from another unit",  [_user("Layer1/App/Main.cpp", reads=[G_DEF])], "private", False),
    ("PRIVATE, used by its own unit only", [_user("Layer1/Access/AccessMatrix.cpp", reads=[G_DEF])], "private", True),
])
def test_phase_two_buckets_globals(label, users, visibility, expected_private):
    globals_data = {G_DEF: _glb(visibility=visibility)}
    functions_data = {f"f{i}": u for i, u in enumerate(users)}
    assert _private(globals_data, functions_data) is expected_private, label


def test_a_use_through_an_extern_declaration_counts_for_the_definition():
    """Main.cpp reads g_x through its own `extern int g_x;`, which the model keys to Main's
    unit, not to AccessMatrix's. The use still publishes the definition; the declaration
    itself is never published."""
    decl = "Layer1.App|Main|g_x"
    globals_data = {G_DEF: _glb(), decl: _glb(file="Layer1/App/Main.cpp", definition=False)}
    functions_data = {"f": _user("Layer1/App/Main.cpp", reads=[decl])}
    assert _private(globals_data, functions_data) is False
    assert _private(globals_data, functions_data, vid=decl) is True


def test_an_extern_used_only_inside_the_defining_unit_does_not_publish():
    """The declaration sits in another file (an orphan header), but the only reader is the
    defining unit itself -- nothing outside the unit uses the storage."""
    decl = "Layer1.Access|Shared|g_x"
    globals_data = {G_DEF: _glb(), decl: _glb(file="Layer1/Access/Shared.h", definition=False)}
    functions_data = {"f": _user("Layer1/Access/AccessMatrix.cpp", reads=[decl])}
    assert _private(globals_data, functions_data) is True


def test_a_marking_cannot_publish_a_global():
    """`PUBLIC` and unmarked are indistinguishable: both need a user in another unit."""
    for vis in ("public", None):
        assert _private({G_DEF: _glb(visibility=vis)}, {}) is True
