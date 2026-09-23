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


def test_an_orphan_header_global_reaches_its_user_only(unit_headers):
    """g_sharedTick is declared in SharedDefs.h, defined in Core.cpp, read by Lib.

    Util includes the same header and touches nothing in it, which is the control: lending
    is on USE, not on #include.
    """
    assert any("g_sharedTick" in d for d in _decls(unit_headers["Layer1.Lib|Lib"]))
    assert any("g_sharedTick" in d for d in _decls(unit_headers["Layer1.Sample-Core|Core"]))
    assert not any("g_sharedTick" in d for d in _decls(unit_headers["Layer1.Util|Util"]))


def test_the_defining_unit_shows_the_definition_not_the_extern(unit_headers):
    """Core both defines it and (through the orphan header) declares it: one row, valued."""
    rows = [r for r in unit_headers["Layer1.Sample-Core|Core"]
            if "g_sharedTick" in r.get("declaration", "")]
    assert len(rows) == 1
    assert "extern" not in rows[0]["declaration"]
    assert rows[0]["information"] == "0"


def test_only_used_orphan_macros_are_lent(unit_headers):
    """Each unit shows its own subset of SharedDefs.h, never the whole header."""
    core = _decls(unit_headers["Layer1.Sample-Core|Core"])
    lib = _decls(unit_headers["Layer1.Lib|Lib"])
    assert any("SHARED_MAX_ITEMS" in d for d in core)
    assert not any("SHARED_SCALE_FACTOR" in d for d in core)
    assert any("SHARED_SCALE_FACTOR" in d for d in lib)


def test_a_plain_struct_is_not_listed(unit_headers):
    """On this branch a struct reaches the table only through a typedef."""
    for rows in unit_headers.values():
        for d in _decls(rows):
            assert not d.strip().startswith("class "), d


def test_snapshot(unit_headers, assert_snapshot, llm_descriptions_off):
    assert_snapshot(unit_headers, "Sample/unit_headers.json")
