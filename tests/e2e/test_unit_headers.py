"""Unit header table view tests — output/<component>/unit_headers.json.

The table moved out of the exporter and into phase 3, so its rules are testable without
opening a .docx. The rules themselves are in docs/spec/SWE3_WIKI.md, N.1.4: update that
first, then these.

The filesystem-free cases (orphan-header lending, the extern collapse, comment stripping)
live in tests/unit/test_unit_header_orphan.py and test_unit_header_comments.py. What can
only be checked against a real run is here: that the view runs at all, that its keys are
the units that get a document section, and that the rows it produces are the ones the
fixtures set up.
"""
import pytest

pytestmark = pytest.mark.e2e


def _decls(rows):
    return [r.get("declaration", "") for r in rows]


def test_every_unit_with_a_section_has_an_entry(unit_headers):
    """Keys are source-backed units. A header-only entry renders nowhere, so it is absent."""
    assert unit_headers, "the view produced nothing — is views.unitHeaders enabled?"
    assert "Layer1.Sample-Core|Core" in unit_headers
    assert "Layer1.Lib|Lib" in unit_headers
    assert "Layer1.Util|Util" in unit_headers
    assert "Layer1.Sample-Core|SharedDefs" not in unit_headers


def test_rows_have_both_columns(unit_headers):
    for unit_key, rows in unit_headers.items():
        for row in rows:
            assert set(row) == {"declaration", "information"}, unit_key
            assert row["declaration"], unit_key


def test_a_private_global_is_listed(unit_headers):
    """Visibility does not filter this table — the client decision of 2026-09-22."""
    decls = _decls(unit_headers["Layer1.Sample-Core|Core"])
    assert any("g_count" in d for d in decls)
    assert any("g_result" in d for d in decls)


CORE, LIB, UTIL = "Layer1.Sample-Core|Core", "Layer1.Lib|Lib", "Layer1.Util|Util"


def _units_listing(unit_headers, symbol):
    """The units with a row DECLARING `symbol` -- a row that merely uses it does not count."""
    return sorted(uk for uk in (CORE, LIB, UTIL)
                  if any(d.startswith(symbol) or f" {symbol}" in f" {d}".split("=")[0]
                         for d in _decls(unit_headers[uk])))


@pytest.mark.parametrize("symbol", [
    "#define SHARED_MAX_ITEMS",      # used by Core
    "#define SHARED_SCALE_FACTOR",   # used by Lib only
    "#define SHARED_BUFSZ",          # used by Util only, at file scope (Util's own
                                     # `g_utilBuf[SHARED_BUFSZ]` row still names it)
    "enum SharedLevel",      # used by Core
])
def test_an_orphan_header_is_listed_once_by_its_owner(unit_headers, symbol):
    """SharedDefs.h sits in Core's component and Core uses it, so Core owns it: Core lists
    every symbol of it that ANY unit uses, and Lib and Util list none (review RV-4)."""
    assert _units_listing(unit_headers, symbol) == [CORE]


def test_an_orphan_header_global_is_not_repeated_in_its_reader(unit_headers):
    """g_sharedTick is declared in SharedDefs.h, defined in Core.cpp and read by Lib. Lib no
    longer repeats the header's `extern`; Core's definition is the one row."""
    assert _units_listing(unit_headers, "g_sharedTick") == [CORE]


def test_the_owner_is_the_first_user_in_the_headers_own_component(unit_headers):
    """UtilLimits.h is in Util's component and used by Util and Core. Util owns it, although
    Core comes first by name."""
    assert _units_listing(unit_headers, "#define UTIL_LIMIT ") == [UTIL]
    assert _units_listing(unit_headers, "enum UtilMode") == [UTIL]


def test_with_no_user_in_its_component_the_first_user_by_name_owns_it(unit_headers):
    """LibLimits.h is in Lib's component, but only Core and Util use it: Core owns it."""
    assert _units_listing(unit_headers, "#define LIB_LIMIT") == [CORE]


def test_an_orphan_symbol_nobody_uses_is_listed_nowhere(unit_headers):
    assert _units_listing(unit_headers, "#define UTIL_LIMIT_UNUSED") == []


def test_the_defining_unit_shows_the_definition_not_the_extern(unit_headers):
    """Core both defines it and (through the orphan header) declares it: one row, valued."""
    rows = [r for r in unit_headers["Layer1.Sample-Core|Core"]
            if "g_sharedTick" in r.get("declaration", "")]
    assert len(rows) == 1
    assert "extern" not in rows[0]["declaration"]
    assert rows[0]["information"] == "0"


def test_a_class_static_definition_has_no_row(unit_headers):
    """The class declares the member, so its out-of-line definition is not listed again.

    None of the My Sample units declares a class, so this asserts the absence pattern that
    would appear if the rule regressed -- a `Foo::s_x` row.
    """
    for unit_key, rows in unit_headers.items():
        for d in _decls(rows):
            assert "::" not in d.split("=")[0], "%s: %r" % (unit_key, d)


def test_snapshot(unit_headers, assert_snapshot, llm_descriptions_off):
    assert_snapshot(unit_headers, "Sample/unit_headers.json")
