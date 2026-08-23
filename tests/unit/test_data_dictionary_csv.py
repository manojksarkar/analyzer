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


class TestMergeReport:
    """The lines telling the author whether their CSV rows landed on a parsed type."""

    def test_matched_and_new_are_separated(self, parser_mod, dd, tmp_path):
        dd["DB_TYPE"] = {"kind": "enum", "range": "0-9"}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "DB_TYPE,enum,,0-2,\n"
                              "MotorSpeed_t,typedef,,0-3000,\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd["DB_TYPE"]["range"] == "0-2"
        assert dd["MotorSpeed_t"]["range"] == "0-3000"

    def test_typo_is_reported_as_new(self, parser_mod):
        """The failure this exists to catch: DB_TYP silently becomes its own entry."""
        lines = parser_mod._format_csv_merge_report(["Status"], ["DB_TYP"], 0)
        assert any("1 matched a parsed type: Status" in ln for ln in lines)
        assert any("1 new, not found in source: DB_TYP" in ln for ln in lines)

    def test_orphan_child_rows_reported(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              ",enumerator,DB_NONE,0,\n"
                              ",enumerator,DB_MAIN,1,\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd == {}
        lines = parser_mod._format_csv_merge_report([], [], 2)
        assert any("2 child row(s) skipped" in ln for ln in lines)

    def test_all_matched_omits_the_new_line(self, parser_mod):
        lines = parser_mod._format_csv_merge_report(["A", "B"], [], 0)
        assert len(lines) == 1
        assert "matched a parsed type: A, B" in lines[0]

    def test_nothing_to_report_is_silent(self, parser_mod):
        assert parser_mod._format_csv_merge_report([], [], 0) == []

    def test_long_lists_truncate(self, parser_mod):
        lines = parser_mod._format_csv_merge_report([f"T{i}" for i in range(14)], [], 0, limit=3)
        assert "T0, T1, T2, +11 more" in lines[0]


class TestBrokenRowsAreReported:
    """The two ways a row goes wrong without moving any of the counts above.

    Both were previously invisible: the report looked exactly like a clean merge, so
    a CSV that silently lost half its rows was indistinguishable from one that worked.
    """

    def test_duplicate_name_is_reported(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "BOOL32,typedef,,0-1,first\n"
                              "BOOL32,typedef,,0-0xFFFFFFFF,second\n")
        lines = parser_mod._merge_external_data_dictionary(path)
        assert any("1 name(s) appear on more than one row" in ln and "BOOL32" in ln
                   for ln in lines)
        # Last row still wins - the report explains the outcome, it does not change it.
        assert dd["BOOL32"]["range"] == "0-0xFFFFFFFF"

    def test_duplicate_of_an_unparsed_type_is_not_called_matched(self, parser_mod, dd, tmp_path):
        """The mis-filing this fixes: the 2nd row used to see the 1st row's own entry.

        BOOL32 is in no source file, so BOTH rows are "new". Deciding against a
        snapshot taken before the loop keeps it that way.
        """
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "BOOL32,typedef,,0-1,\n"
                              "BOOL32,typedef,,0-1,\n")
        lines = parser_mod._merge_external_data_dictionary(path)
        assert any("1 new, not found in source: BOOL32" in ln for ln in lines)
        assert not any("matched a parsed type" in ln for ln in lines)

    def test_genuinely_parsed_type_is_still_matched(self, parser_mod, dd, tmp_path):
        """The snapshot must not turn a real override into a false 'new'."""
        dd["Speed_t"] = {"kind": "typedef", "range": "NA"}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "Speed_t,typedef,,0-500,\n")
        lines = parser_mod._merge_external_data_dictionary(path)
        assert any("1 matched a parsed type: Speed_t" in ln for ln in lines)

    def test_blank_name_row_is_counted(self, parser_mod, dd, tmp_path):
        """Empty Name on a non-child Kind - what a merged-cell Excel export becomes."""
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "Speed_t,typedef,,0-500,\n"
                              ",,,0-7,lost row\n"
                              ",typedef,,0-8,also lost\n")
        lines = parser_mod._merge_external_data_dictionary(path)
        assert any("2 row(s) dropped: empty Name" in ln for ln in lines)
        assert "Speed_t" in dd and len(dd) == 1

    def test_blank_separator_line_is_not_counted(self, parser_mod, dd, tmp_path):
        """A wholly empty row is a separator, not a broken row - it must stay silent."""
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "Speed_t,typedef,,0-500,\n"
                              ",,,,\n")
        lines = parser_mod._merge_external_data_dictionary(path)
        assert not any("empty Name" in ln for ln in lines)

    def test_clean_csv_reports_neither(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "A_t,typedef,,0-1,\n"
                              "B_t,typedef,,0-2,\n")
        lines = parser_mod._merge_external_data_dictionary(path)
        assert not any("more than one row" in ln or "empty Name" in ln for ln in lines)


class TestLayeredMergeReport:
    """Where the merge report meets per-layer scoping.

    Neither piece is new on its own — the report is decided against a pre-loop
    snapshot, and a layer's rows are keyed `name@layer` when the bare slot belongs
    to someone else — but the snapshot now has to be read through the SAME layer
    rule as the write, or the two disagree about which entry a row landed on.
    """

    def test_layer_row_on_a_global_type_is_matched_and_leaves_it_alone(
            self, parser_mod, dd, tmp_path):
        """The global entry answers for the layer, so the row DID land on a parsed type."""
        dd["BOOL32"] = {"kind": "typedef", "layer": None, "range": "0-0xFFFFFFFF",
                        "location": {"file": "Common/Types.h", "line": 3}}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "BOOL32,typedef,,0-1,\n")
        lines = parser_mod._merge_dd_rows(path, "Layer1")
        assert any("1 matched a parsed type: BOOL32" in ln for ln in lines)
        assert not any("not found in source" in ln for ln in lines)
        # Written to the layer's own key; the global tier keeps its measured width.
        assert dd["BOOL32@Layer1"]["range"] == "0-1"
        assert dd["BOOL32"]["range"] == "0-0xFFFFFFFF"
        # And the location was seeded from the global entry, not lost.
        assert dd["BOOL32@Layer1"]["location"]["file"] == "Common/Types.h"

    def test_duplicate_layer_rows_on_an_unparsed_type_count_once_as_new(
            self, parser_mod, dd, tmp_path):
        """The snapshot has to be consulted through the layered key too.

        Row 1 writes `Ghost_t@Layer1`; reading the LIVE dictionary for row 2 would
        find it and call the row matched, which is the exact mis-filing the snapshot
        exists to prevent - it just hides behind a different key once layers are on.
        """
        dd["Ghost_t"] = {"kind": "typedef", "layer": "Layer2", "range": "0-9"}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "Ghost_t,typedef,,0-1,\n"
                              "Ghost_t,typedef,,0-2,\n")
        lines = parser_mod._merge_dd_rows(path, "Layer1")
        assert any("1 new, not found in source: Ghost_t" in ln for ln in lines)
        assert not any("matched a parsed type" in ln for ln in lines)
        assert any("1 name(s) appear on more than one row" in ln for ln in lines)
        assert dd["Ghost_t@Layer1"]["range"] == "0-2"      # last row wins
        assert dd["Ghost_t"]["range"] == "0-9"             # Layer2 untouched

    def test_another_layers_csv_does_not_rewrite_this_layers_field(
            self, parser_mod, dd, tmp_path):
        """`_reresolve_struct_field_ranges` obeys the same global+own-layer rule.

        A CSV naming BOOL32 is the author saying they mean it - but only for THEIR
        layer. Read from one flat set, a Layer2 CSV would license overwriting a
        measured width in a Layer1 struct.
        """
        dd["Frame"] = {"kind": "struct", "layer": "Layer1", "fields": [
            {"name": "valid", "type": "BOOL32", "range": "0-0xFFFFFFFF"}]}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "BOOL32,typedef,,0-1,\n")
        parser_mod._merge_dd_rows(path, "Layer2")
        try:
            assert parser_mod._reresolve_struct_field_ranges() == 0
            assert dd["Frame"]["fields"][0]["range"] == "0-0xFFFFFFFF"
        finally:
            parser_mod._csv_top_level_names.clear()


@pytest.fixture
def csv_names(parser_mod):
    """Clean parser._csv_top_level_names per test (module-level singleton).

    It is keyed by layer; yields the GLOBAL tier's set (the project-wide CSV's), which
    is what these tests write to and what a layer-less dd entry resolves against.
    """
    saved = {k: set(v) for k, v in parser_mod._csv_top_level_names.items()}
    parser_mod._csv_top_level_names.clear()
    yield parser_mod._csv_top_level_names.setdefault(None, set())
    parser_mod._csv_top_level_names.clear()
    parser_mod._csv_top_level_names.update(saved)


class TestStructFieldRanges:
    """Struct field ranges are baked at parse time, long before the CSV is read.

    Without the re-resolution pass a BOOL32 field keeps the width-derived
    0-0xFFFFFFFF while the BOOL32 *type* entry says 0-1 - the same model asserting
    two different ranges for one type.
    """

    def test_csv_override_reaches_the_field(self, parser_mod, dd, tmp_path, csv_names):
        dd["Frame"] = {"kind": "struct", "fields": [
            {"name": "valid", "type": "BOOL32", "range": "0-0xFFFFFFFF"}]}
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "BOOL32,typedef,,0-1,Boolean 32-bit\n")
        parser_mod._merge_external_data_dictionary(path)
        assert parser_mod._reresolve_struct_field_ranges() == 1
        assert dd["Frame"]["fields"][0]["range"] == "0-1"

    def test_na_field_picks_up_a_dictionary_answer(self, parser_mod, dd, csv_names):
        """libclang had no answer; the dictionary does. No CSV involved."""
        dd["Speed_t"] = {"kind": "typedef", "range": "0-500"}
        dd["Motor"] = {"kind": "struct", "fields": [
            {"name": "speed", "type": "Speed_t", "range": "NA"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 1
        assert dd["Motor"]["fields"][0]["range"] == "0-500"

    def test_measured_width_is_not_overwritten(self, parser_mod, dd, csv_names):
        """A width measured from the canonical type outranks anything name-derived."""
        dd["unsigned char"] = {"kind": "primitive", "range": "0-0xFF"}
        dd["Buf"] = {"kind": "struct", "fields": [
            {"name": "b", "type": "unsigned int", "range": "0-0xFFFFFFFF"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 0
        assert dd["Buf"]["fields"][0]["range"] == "0-0xFFFFFFFF"

    def test_struct_typed_field_stays_na(self, parser_mod, dd, csv_names):
        dd["Point"] = {"kind": "struct", "range": "NA", "fields": []}
        dd["Line"] = {"kind": "struct", "fields": [
            {"name": "a", "type": "Point", "range": "NA"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 0
        assert dd["Line"]["fields"][0]["range"] == "NA"

    def test_unknown_pointer_field_stays_na(self, parser_mod, dd, csv_names):
        """`const char *name` is a string, not an int8.

        get_range answers a pointer from its pointee, so without this guard the pass
        stamped -0x80-0x7F on every char* field that previously read NA — a worse
        answer than the one it replaced.
        """
        dd["Widget_t"] = {"kind": "struct", "fields": [
            {"name": "name", "type": "const char *", "range": "NA"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 0
        assert dd["Widget_t"]["fields"][0]["range"] == "NA"

    def test_unknown_array_field_stays_na(self, parser_mod, dd, csv_names):
        dd["Buf"] = {"kind": "struct", "fields": [
            {"name": "data", "type": "char[16]", "range": "NA"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 0
        assert dd["Buf"]["fields"][0]["range"] == "NA"

    def test_pointer_field_resolves_through_its_pointee(self, parser_mod, dd, csv_names):
        """get_range strips the '*', so a CSV row for the pointee reaches the field."""
        dd["BOOL32"] = {"kind": "typedef", "range": "0-1"}
        csv_names.add("BOOL32")
        dd["Frame"] = {"kind": "struct", "fields": [
            {"name": "flags", "type": "BOOL32 *", "range": "0-0xFFFFFFFF"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 1
        assert dd["Frame"]["fields"][0]["range"] == "0-1"

    def test_csv_authored_field_row_is_left_alone(self, parser_mod, dd, tmp_path, csv_names):
        """A field row from the CSV carries no `type` - the author's range stands."""
        path = _csv(tmp_path, "Name,Kind,EntryName,Range,Comment\n"
                              "GG,struct,,NA,Position\n"
                              ",field,x,0-100,X coordinate\n")
        parser_mod._merge_external_data_dictionary(path)
        assert parser_mod._reresolve_struct_field_ranges() == 0
        assert dd["GG"]["fields"][0]["range"] == "0-100"

    def test_idempotent(self, parser_mod, dd, csv_names):
        """Determinism contract: a second pass must change nothing."""
        dd["Speed_t"] = {"kind": "typedef", "range": "0-500"}
        dd["Motor"] = {"kind": "struct", "fields": [
            {"name": "speed", "type": "Speed_t", "range": "NA"}]}
        assert parser_mod._reresolve_struct_field_ranges() == 1
        assert parser_mod._reresolve_struct_field_ranges() == 0
