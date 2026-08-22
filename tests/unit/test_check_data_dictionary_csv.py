"""Unit tests for `tools/check_data_dictionary_csv.py`.

The tool exists to say out loud what `_merge_external_data_dictionary` stays quiet
about, so each test pins one way a CSV goes wrong and asserts the tool names it.
If the merge's own tolerance changes, these tests and
`tests/unit/test_data_dictionary_csv.py` should move together.

Passes A/B are pure text work (no model). Passes C/D need a model dict; pass D
imports the real `utils.get_range`, so `engine/` must be importable.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(PROJECT_ROOT, "tools")
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

for _p in (_TOOLS, _ENGINE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_data_dictionary_csv as T  # noqa: E402  (tools/ must be on sys.path first)

HEADER = "Name,Kind,EntryName,Range,Comment\n"


def _write(tmp_path, text, name="dd.csv", encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return str(p)


def _run(tmp_path, text, **kw):
    """Passes A+B over one CSV. Returns (report, findings, top-level rows)."""
    path = _write(tmp_path, text, **kw)
    rep = T.Report()
    fieldnames, rows = T.read_csv(path, rep)
    top = T.check_rows(rows, rep) if fieldnames is not None else {}
    findings = [(lvl, msg, detail) for _t, items in rep.sections for lvl, msg, detail, _f in items]
    return rep, findings, top


def _said(findings, needle, level=None):
    return any(needle in msg or needle in detail
               for lvl, msg, detail in findings if level is None or lvl == level)


class TestFileAndHeader:
    def test_clean_csv_has_no_findings(self, tmp_path):
        rep, findings, top = _run(tmp_path, HEADER + "BOOL32,typedef,,0-1,Boolean\n")
        assert rep.counts[T.ERROR] == 0
        assert rep.counts[T.WARN] == 0
        assert set(top) == {"BOOL32"}

    def test_the_shipped_sample_csv_is_clean(self):
        """engine/config/data_dictionary.csv is the format's worked example."""
        rep = T.Report()
        fieldnames, rows = T.read_csv(
            os.path.join(_ENGINE, "config", "data_dictionary.csv"), rep)
        T.check_rows(rows, rep)
        assert rep.counts[T.ERROR] == 0
        assert rep.counts[T.WARN] == 0

    def test_non_utf8_is_an_error(self, tmp_path):
        """The merge opens encoding='utf-8' and catches only csv.Error, so this
        aborts Phase 1 with an uncaught UnicodeDecodeError."""
        _, findings, _ = _run(tmp_path, HEADER + "A_t,typedef,,0-1,valeur bornée\n",
                              encoding="cp1252")
        assert _said(findings, "not UTF-8", T.ERROR)

    def test_bom_is_tolerated(self, tmp_path):
        rep, findings, top = _run(tmp_path, "﻿" + HEADER + "A_t,typedef,,0-1,\n")
        assert rep.counts[T.ERROR] == 0
        assert set(top) == {"A_t"}

    def test_semicolon_delimiter_is_an_error(self, tmp_path):
        _, findings, _ = _run(tmp_path, "Name;Kind;EntryName;Range;Comment\nA_t;typedef;;0-1;\n")
        assert _said(findings, "not comma-delimited", T.ERROR)

    def test_title_row_above_the_header_is_an_error(self, tmp_path):
        """DictReader keys on row 1, so every row's Name becomes None."""
        _, findings, _ = _run(tmp_path, "Data Dictionary v3,,,,\n" + HEADER + "A_t,typedef,,0-1,\n")
        assert _said(findings, "no 'Name' column", T.ERROR)

    def test_empty_file_is_an_error(self, tmp_path):
        _, findings, _ = _run(tmp_path, "")
        assert _said(findings, "file is empty", T.ERROR)

    def test_unknown_column_warns(self, tmp_path):
        _, findings, _ = _run(tmp_path, "Name,Kind,EntryName,Range,Comment,Owner\n"
                                        "A_t,typedef,,0-1,,me\n")
        assert _said(findings, "column(s) the merge ignores", T.WARN)


class TestRows:
    def test_duplicate_name(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "BOOL32,typedef,,0-1,\n"
                                                 "BOOL32,typedef,,0-2,\n")
        assert _said(findings, "duplicated Name", T.ERROR)

    def test_blank_name_row_dropped_with_no_trace(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "A_t,typedef,,0-1,\n,,,0-7,lost\n")
        assert _said(findings, "dropped with NO trace", T.ERROR)

    def test_wholly_blank_row_is_silent(self, tmp_path):
        rep, _, _ = _run(tmp_path, HEADER + "A_t,typedef,,0-1,\n,,,,\n")
        assert rep.counts[T.ERROR] == 0

    def test_orphan_child_row(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + ",enumerator,STRAY,0,\n")
        assert _said(findings, "orphan child row", T.WARN)

    def test_enum_with_no_children_wipes(self, tmp_path):
        """The merge resets enumerators to [] before child rows append."""
        _, findings, _ = _run(tmp_path, HEADER + "DB_TYPE,enum,,0-2,\n")
        assert _said(findings, "WIPE parsed children", T.ERROR)

    def test_enum_with_children_does_not_wipe(self, tmp_path):
        rep, _, top = _run(tmp_path, HEADER + "DB_TYPE,enum,,0-2,\n,enumerator,DB_NONE,0,\n")
        assert rep.counts[T.ERROR] == 0
        assert len(top["DB_TYPE"]["children"]) == 1

    def test_unquoted_comma_past_the_header(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "A_t,typedef,,0-9,comment, with a comma\n")
        assert _said(findings, "more fields than the header", T.ERROR)

    def test_pointer_in_name_warns(self, tmp_path):
        """get_range strips '*' before the lookup, so such a Name can never match."""
        _, findings, _ = _run(tmp_path, HEADER + "UINT8 *,typedef,,0-0xFF,\n")
        assert _said(findings, "not plain type identifiers", T.WARN)

    def test_prose_range_warns(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "A_t,typedef,,0 to 4095,\n")
        assert _said(findings, "suspicious Range", T.WARN)

    @pytest.mark.parametrize("rng", ["0-255", "0-0xFF", "-0x80-0x7F", "-1-1", "NA", "VOID"])
    def test_accepted_range_forms(self, tmp_path, rng):
        rep, _, _ = _run(tmp_path, HEADER + f"A_t,typedef,,{rng},\n")
        assert rep.counts[T.WARN] == 0

    def test_empty_range_warns(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "A_t,typedef,,,\n")
        assert _said(findings, "empty Range", T.WARN)

    def test_unknown_kind_warns(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "A_t,alias,,0-1,\n")
        assert _said(findings, "unrecognised Kind", T.WARN)

    def test_non_integer_enumerator_value_warns(self, tmp_path):
        _, findings, _ = _run(tmp_path, HEADER + "DB_TYPE,enum,,0-2,\n"
                                                 ",enumerator,DB_NONE,zero,\n")
        assert _said(findings, "must be an integer", T.WARN)


class TestAppliedPass:
    """Pass C. The merge writes top-level rows unconditionally, so absence from the
    model proves the CSV never ran — that is the whole diagnostic value."""

    def test_no_row_present_means_the_csv_never_ran(self):
        rep = T.Report()
        top = {"BOOL32": {"kind": "typedef", "range": "0-1", "line": 2, "children": []}}
        T.check_applied(top, {"Point": {"kind": "struct"}}, rep)
        findings = [(l, m, d) for _t, items in rep.sections for l, m, d, _f in items]
        assert _said(findings, "NOT ONE row", T.ERROR)

    def test_present_rows_are_reported_ok(self):
        rep = T.Report()
        top = {"BOOL32": {"kind": "typedef", "range": "0-1", "line": 2, "children": []}}
        T.check_applied(top, {"BOOL32": {"kind": "typedef", "range": "0-1"}}, rep)
        findings = [(l, m, d) for _t, items in rep.sections for l, m, d, _f in items]
        assert _said(findings, "present in dataDictionary.json", T.OK)

    def test_emptied_child_list_is_detected(self):
        rep = T.Report()
        top = {"DB_TYPE": {"kind": "enum", "range": "0-2", "line": 2, "children": []}}
        T.check_applied(top, {"DB_TYPE": {"kind": "enum", "enumerators": []}}, rep)
        findings = [(l, m, d) for _t, items in rep.sections for l, m, d, _f in items]
        assert _said(findings, "EMPTY child list", T.ERROR)


class TestAppliedPassLayerScoped:
    """A layer's rows land on `name@<layer>` when the bare name belongs to someone
    else, so a bare-name lookup calls a perfectly applied CSV "never reached the
    model" — an ERROR, and a non-zero exit, on a correct run."""

    def _findings(self, top, dd, layer):
        rep = T.Report()
        T.check_applied(top, dd, rep, layer)
        return [(l, m, d) for _t, items in rep.sections for l, m, d, _f in items]

    def test_layer_qualified_key_counts_as_applied(self):
        top = {"BOOL32": {"kind": "typedef", "range": "0-1", "line": 2, "children": []}}
        dd = {"BOOL32": {"kind": "typedef", "layer": None, "range": "0-0xFFFFFFFF"},
              "BOOL32@Layer1": {"kind": "typedef", "layer": "Layer1", "range": "0-1"}}
        findings = self._findings(top, dd, "Layer1")
        assert _said(findings, "present in dataDictionary.json", T.OK)
        assert not _said(findings, "NOT ONE row", T.ERROR)

    def test_global_tier_entry_answers_for_a_layer(self):
        """No layer key was needed: the bare slot is the global tier, visible to all."""
        top = {"BOOL32": {"kind": "typedef", "range": "0-1", "line": 2, "children": []}}
        dd = {"BOOL32": {"kind": "typedef", "layer": None, "range": "0-1"}}
        findings = self._findings(top, dd, "Layer1")
        assert _said(findings, "present in dataDictionary.json", T.OK)

    def test_another_layers_entry_is_not_an_answer(self):
        """Not a worse answer - the wrong type. This CSV really did not apply."""
        top = {"BOOL32": {"kind": "typedef", "range": "0-1", "line": 2, "children": []}}
        dd = {"BOOL32": {"kind": "typedef", "layer": "Layer2", "range": "0-9"}}
        findings = self._findings(top, dd, "Layer1")
        assert _said(findings, "NOT ONE row", T.ERROR)

    def test_range_and_child_checks_read_the_layer_key(self):
        """The follow-up checks must read the SAME entry the applied check found."""
        top = {"DB_TYPE": {"kind": "enum", "range": "0-2", "line": 2, "children": []}}
        dd = {"DB_TYPE": {"kind": "enum", "layer": None, "enumerators": [{"name": "A"}]},
              "DB_TYPE@Layer1": {"kind": "enum", "layer": "Layer1", "enumerators": []}}
        findings = self._findings(top, dd, "Layer1")
        assert _said(findings, "EMPTY child list", T.ERROR)


class TestNaPass:
    """Pass D buckets the NAs, because only one bucket is a row worth writing."""

    def _na(self, dd, functions, top=None):
        rep = T.Report()
        T.check_na(top or {}, {"dd": dd, "fn": functions, "gv": {}}, rep)
        return [(l, m, d) for _t, items in rep.sections for l, m, d, _f in items]

    def test_unknown_scalar_is_the_actionable_bucket(self):
        findings = self._na({}, {"f": {"returnType": "BOOL32", "parameters": []}})
        assert _said(findings, "ADD THESE to the CSV")

    def test_struct_is_not_actionable(self):
        """A struct has no scalar range; telling the author to add a row is wrong."""
        findings = self._na({"Point": {"kind": "struct", "range": "NA"}},
                            {"f": {"returnType": "Point", "parameters": []}})
        assert _said(findings, "NA is correct here")
        assert not _said(findings, "ADD THESE to the CSV")

    def test_pointer_spelling_is_not_actionable(self):
        findings = self._na({"Point": {"kind": "struct", "range": "NA"}},
                            {"f": {"returnType": "", "parameters": [{"type": "Point *"}]}})
        assert _said(findings, "NA is correct here")

    def test_row_in_the_csv_that_is_still_na_is_an_error(self):
        """Named by the author but ineffective — empty Range, or a spelling mismatch."""
        top = {"BOOL32": {"kind": "typedef", "range": "", "line": 2, "children": []}}
        findings = self._na({"BOOL32": {"kind": "typedef"}},
                            {"f": {"returnType": "BOOL32", "parameters": []}}, top)
        assert _said(findings, "ARE named in the CSV but still NA", T.ERROR)

    def test_resolved_types_produce_no_finding(self):
        findings = self._na({"BOOL32": {"kind": "typedef", "range": "0-1"}},
                            {"f": {"returnType": "BOOL32", "parameters": []}})
        assert _said(findings, "resolve to a range", T.OK)


class TestExitCode:
    def test_errors_exit_1(self, tmp_path):
        rep, _, _ = _run(tmp_path, HEADER + "BOOL32,typedef,,0-1,\nBOOL32,typedef,,0-2,\n")
        assert rep.emit() == 1

    def test_clean_exits_0(self, tmp_path):
        rep, _, _ = _run(tmp_path, HEADER + "BOOL32,typedef,,0-1,\n")
        assert rep.emit() == 0

    def test_warnings_alone_do_not_fail(self, tmp_path):
        rep, _, _ = _run(tmp_path, HEADER + "A_t,alias,,0-1,\n")
        assert rep.counts[T.WARN] > 0
        assert rep.emit() == 0
