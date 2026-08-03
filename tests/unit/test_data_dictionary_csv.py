"""External data-dictionary CSV merge (`--data-dictionary`) and how its ranges
reach the interface tables.

The CSV is merged into the parser's in-memory `data_dictionary` as the LAST step
of Phase 1, on top of everything libclang parsed (`parser.main`). These tests
drive `_merge_external_data_dictionary` directly and then check the result
through `utils.get_range`, which is what the views call.

Importing `parser` needs libclang, so the whole module skips without it — same
approach as test_define_conditional.py.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from utils import get_range  # noqa: E402  (engine/ must be on sys.path first)


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (it reads argv at import). Skips if libclang is unavailable.

    Uses the repo root as the base path and never touches `MODULE_BASE_PATH`
    afterwards: `parser` is a module-level singleton, so a fixture that pointed it
    at a temp dir and then deleted that dir would break whichever test module
    imports it second (see test_define_conditional.py). These tests only exercise
    `_merge_external_data_dictionary`, which does not read the base path.
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


@pytest.fixture
def dd(parser_mod):
    """Give each test a clean parser.data_dictionary and restore it afterwards."""
    saved = dict(parser_mod.data_dictionary)
    parser_mod.data_dictionary.clear()
    yield parser_mod.data_dictionary
    parser_mod.data_dictionary.clear()
    parser_mod.data_dictionary.update(saved)


def _csv(tmp_path, text):
    p = tmp_path / "dd.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestMergeSemantics:
    def test_new_entry_added(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "MotorSpeed_t,typedef,,0-3000,Motor speed in RPM\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd["MotorSpeed_t"]["range"] == "0-3000"
        assert dd["MotorSpeed_t"]["comment"] == "Motor speed in RPM"

    def test_parsed_entry_updated_and_location_preserved(self, parser_mod, dd, tmp_path):
        dd["Speed_t"] = {"kind": "typedef", "name": "Speed_t", "qualifiedName": "Speed_t",
                         "underlyingType": "Foo_t", "range": "NA",
                         "location": {"file": "Layer1/Types.h", "line": 7}}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "Speed_t,typedef,,0-500,Speed\n")
        parser_mod._merge_external_data_dictionary(path)
        e = dd["Speed_t"]
        assert e["range"] == "0-500"
        assert e["location"] == {"file": "Layer1/Types.h", "line": 7}
        assert e["underlyingType"] == "Foo_t"

    def test_untouched_entry_survives(self, parser_mod, dd, tmp_path):
        dd["Other_t"] = {"kind": "typedef", "range": "0-9"}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "MotorSpeed_t,typedef,,0-3000,x\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd["Other_t"]["range"] == "0-9"

    def test_enumerator_child_rows_attach_to_parent(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "DB_TYPE,enum,,0-2,Database selection\n"
                              ",enumerator,DB_NONE,0,No database\n"
                              ",enumerator,DB_MAIN,1,Main database\n")
        parser_mod._merge_external_data_dictionary(path)
        assert [e["name"] for e in dd["DB_TYPE"]["enumerators"]] == ["DB_NONE", "DB_MAIN"]
        assert dd["DB_TYPE"]["enumerators"][0]["value"] == 0

    def test_field_child_rows_attach_to_parent(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "GG,struct,,NA,Position data\n"
                              ",field,x,0-100,X coordinate\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd["GG"]["fields"] == [{"name": "x", "range": "0-100",
                                       "comment": "X coordinate"}]

    def test_enumerators_reset_before_child_rows(self, parser_mod, dd, tmp_path):
        """A CSV enum row replaces the parsed enumerator list rather than appending."""
        dd["DB_TYPE"] = {"kind": "enum", "enumerators": [{"name": "STALE", "value": 9}]}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "DB_TYPE,enum,,0-1,\n"
                              ",enumerator,DB_NONE,0,\n")
        parser_mod._merge_external_data_dictionary(path)
        assert [e["name"] for e in dd["DB_TYPE"]["enumerators"]] == ["DB_NONE"]

    def test_orphan_child_row_without_parent_is_ignored(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              ",enumerator,DB_NONE,0,No database\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd == {}

    def test_missing_file_exits(self, parser_mod, tmp_path):
        with pytest.raises(SystemExit):
            parser_mod._merge_external_data_dictionary(str(tmp_path / "nope.csv"))


class TestCsvRangeReachesLookup:
    """The point of the CSV: a range set there must surface in the interface tables,
    including through an alias whose own range was baked as "NA" at parse time."""

    def test_alias_of_csv_typed_base_resolves(self, parser_mod, dd, tmp_path):
        # What the parser produces for `typedef Foo_t MotorSpeed_t;` when Foo_t is a
        # project type: get_range_for_type("Foo_t") knows nothing, so range == "NA".
        dd["MotorSpeed_t"] = {"kind": "typedef", "name": "MotorSpeed_t",
                              "qualifiedName": "MotorSpeed_t",
                              "underlyingType": "Foo_t", "range": "NA"}
        dd["Foo_t"] = {"kind": "typedef", "name": "Foo_t", "qualifiedName": "Foo_t",
                       "underlyingType": "", "range": "NA"}
        assert get_range("MotorSpeed_t", dd) == "NA"

        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "Foo_t,typedef,,0-3000,Base type\n")
        parser_mod._merge_external_data_dictionary(path)

        assert get_range("Foo_t", dd) == "0-3000"
        assert get_range("MotorSpeed_t", dd) == "0-3000"

    def test_csv_range_on_the_alias_itself_wins(self, parser_mod, dd, tmp_path):
        dd["MotorSpeed_t"] = {"kind": "typedef", "underlyingType": "uint8_t",
                              "range": "NA"}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "MotorSpeed_t,typedef,,0-3000,\n")
        parser_mod._merge_external_data_dictionary(path)
        assert get_range("MotorSpeed_t", dd) == "0-3000"

    def test_csv_na_on_a_struct_stays_na(self, parser_mod, dd, tmp_path):
        """`GG,struct,,NA,...` in the shipped sample CSV must not start resolving to
        something else."""
        dd["GG"] = {"kind": "struct", "qualifiedName": "GG", "range": "NA"}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "GG,struct,,NA,Position data\n")
        parser_mod._merge_external_data_dictionary(path)
        assert get_range("GG", dd) == "NA"
