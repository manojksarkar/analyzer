"""Unit and struct descriptions are generated in Phase 2 and STORED (REQ-PRE-01).

Both used to be produced inside the DOCX exporter and thrown away:

    docx_exporter.py:371   "typedef struct: description from name + fields (on the go, no store)"
    docx_exporter.py:1074  get_unit_description(...) called inline while rendering the table

So the HTML view could not show either one -- it does not run the exporter -- every export
re-paid for the LLM calls with no guarantee two exports of one version read the same, and
neither could be corrected by a reviewer because there was nothing to correct.

Phase 2 generates them now, after the function and global descriptions the unit description is
built FROM, and the exporter only renders.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import model_deriver as md


def _fn(qn, desc, *, visibility="public", class_name=""):
    return {"qualifiedName": qn, "description": desc, "visibility": visibility,
            "className": class_name}


UNITS = {"Comp|UnitA": {"name": "UnitA",
                        "functionIds": ["Comp|UnitA|alpha|", "Comp|UnitA|hidden|"],
                        "globalVariableIds": ["Comp|UnitA|gCounter"]}}
FUNCS = {"Comp|UnitA|alpha|": _fn("ns::alpha", "Starts the pump."),
         "Comp|UnitA|hidden|": _fn("ns::hidden", "Internal helper.", visibility="private")}
GLOBALS = {"Comp|UnitA|gCounter": _fn("ns::gCounter", "Counts retries.")}


class TestTheInputsMatchWhatTheExporterUsed:
    """The unit description was generated FROM the published interface entries, so the same
    two rules have to hold here or the prompt changes and so does the wording."""

    def test_private_entities_are_excluded(self):
        fn_items, _gv = md._iface_items_for_unit("Comp|UnitA", UNITS, FUNCS, GLOBALS)
        names = [n for n, _d in fn_items]
        assert "hidden" not in " ".join(names), (
            "interface_tables skips private entries, so they never reached the prompt")
        assert any("alpha" in n for n in names)

    def test_globals_are_a_separate_bucket(self):
        _fns, gv_items = md._iface_items_for_unit("Comp|UnitA", UNITS, FUNCS, GLOBALS)
        assert [d for _n, d in gv_items] == ["Counts retries."]

    def test_the_name_is_class_qualified(self):
        units = {"Comp|U": {"name": "U", "functionIds": ["Comp|U|apply|"],
                            "globalVariableIds": []}}
        funcs = {"Comp|U|apply|": _fn("ns::AddOperation::apply", "Adds.",
                                      class_name="AddOperation")}
        fn_items, _ = md._iface_items_for_unit("Comp|U", units, funcs, {})
        assert fn_items == [("AddOperation::apply", "Adds.")], (
            "two same-named methods in one unit must stay distinguishable, which is what "
            "interfaceName carried")

    def test_entries_without_a_description_contribute_nothing(self):
        units = {"Comp|U": {"name": "U", "functionIds": ["Comp|U|a|", "Comp|U|b|"],
                            "globalVariableIds": []}}
        funcs = {"Comp|U|a|": _fn("a", ""), "Comp|U|b|": _fn("b", "-")}
        assert md._iface_items_for_unit("Comp|U", units, funcs, {}) == ([], [])

    def test_duplicates_are_dropped_and_order_kept(self):
        units = {"Comp|U": {"name": "U",
                            "functionIds": ["Comp|U|a|", "Comp|U|b|", "Comp|U|c|"],
                            "globalVariableIds": []}}
        funcs = {"Comp|U|a|": _fn("a", "Same."), "Comp|U|b|": _fn("a", "Same."),
                 "Comp|U|c|": _fn("c", "Other.")}
        fn_items, _ = md._iface_items_for_unit("Comp|U", units, funcs, {})
        assert [d for _n, d in fn_items] == ["Same.", "Other."]


class TestPhase2GeneratesAndStores:
    def _patch_llm(self, monkeypatch, unit_text="A unit.", struct_text="A struct."):
        calls = {"unit": 0, "struct": 0}
        mod = type(sys)("llm_enrichment")
        mod.llm_provider_reachable = lambda cfg: True

        def _unit(name, fn_items, gv_items, cfg, abbr):
            calls["unit"] += 1
            return unit_text

        def _struct(name, fields, cfg, abbr):
            calls["struct"] += 1
            return struct_text

        mod.get_unit_description = _unit
        mod.get_struct_description = _struct
        monkeypatch.setitem(sys.modules, "llm_enrichment", mod)

        dc = type(sys)("docx_common")
        dc.load_abbreviations = lambda root, cfg: {}
        monkeypatch.setitem(sys.modules, "docx_common", dc)
        return calls

    def test_the_unit_description_is_written_onto_the_unit(self, monkeypatch):
        self._patch_llm(monkeypatch)
        units = {k: dict(v) for k, v in UNITS.items()}
        n_u, _n_s = md._enrich_unit_and_struct_descriptions(units, FUNCS, GLOBALS, {}, {})
        assert n_u == 1
        assert units["Comp|UnitA"]["description"] == "A unit."

    def test_the_struct_description_is_written_onto_the_entry(self, monkeypatch):
        self._patch_llm(monkeypatch)
        dd = {"Cfg": {"kind": "struct", "name": "Cfg", "fields": [{"name": "x"}]}}
        _n_u, n_s = md._enrich_unit_and_struct_descriptions({}, {}, {}, dd, {})
        assert n_s == 1
        assert dd["Cfg"]["description"] == "A struct."

    def test_only_structs_are_described(self, monkeypatch):
        self._patch_llm(monkeypatch)
        dd = {"E": {"kind": "enum", "name": "E"}, "T": {"kind": "typedef", "name": "T"}}
        _n_u, n_s = md._enrich_unit_and_struct_descriptions({}, {}, {}, dd, {})
        assert n_s == 0 and "description" not in dd["E"]

    def test_classes_and_unions_are_described_too(self, monkeypatch):
        """The unit header table lists class and union rows beside struct rows, and describes
        all three. Its text is read from here, so a class left undescribed would show the
        name-derived fallback forever -- and give a reviewer nothing to correct."""
        self._patch_llm(monkeypatch)
        dd = {"Pump": {"kind": "class", "name": "Pump", "fields": [{"name": "rate"}]},
              "Num": {"kind": "union", "name": "Num", "fields": [{"name": "i"}]}}
        _n_u, n_s = md._enrich_unit_and_struct_descriptions({}, {}, {}, dd, {})
        assert n_s == 2
        assert dd["Pump"]["description"] == dd["Num"]["description"] == "A struct."

    def test_an_existing_description_is_not_regenerated(self, monkeypatch):
        """Carried forward from a baseline, or already corrected by a human -- either way,
        re-paying for it would also overwrite it."""
        calls = self._patch_llm(monkeypatch)
        units = {"Comp|UnitA": dict(UNITS["Comp|UnitA"], description="Kept.")}
        dd = {"Cfg": {"kind": "struct", "name": "Cfg", "description": "Kept too."}}
        md._enrich_unit_and_struct_descriptions(units, FUNCS, GLOBALS, dd, {})
        assert units["Comp|UnitA"]["description"] == "Kept."
        assert dd["Cfg"]["description"] == "Kept too."
        assert calls == {"unit": 0, "struct": 0}

    def test_a_unit_with_nothing_to_describe_is_skipped(self, monkeypatch):
        calls = self._patch_llm(monkeypatch)
        units = {"Comp|Empty": {"name": "Empty", "functionIds": [], "globalVariableIds": []}}
        n_u, _ = md._enrich_unit_and_struct_descriptions(units, {}, {}, {}, {})
        assert n_u == 0 and calls["unit"] == 0

    def test_descriptions_disabled_means_no_calls(self, monkeypatch):
        calls = self._patch_llm(monkeypatch)
        units = {k: dict(v) for k, v in UNITS.items()}
        n_u, n_s = md._enrich_unit_and_struct_descriptions(
            units, FUNCS, GLOBALS, {}, {"llm": {"descriptions": False}})
        assert (n_u, n_s) == (0, 0) and calls == {"unit": 0, "struct": 0}

    def test_a_failing_generator_does_not_fail_the_phase(self, monkeypatch):
        """A missing sentence must not fail a phase that has already paid for the parse and
        the enrichment."""
        mod = type(sys)("llm_enrichment")
        mod.llm_provider_reachable = lambda cfg: True
        mod.get_unit_description = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gateway"))
        mod.get_struct_description = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gateway"))
        monkeypatch.setitem(sys.modules, "llm_enrichment", mod)
        dc = type(sys)("docx_common")
        dc.load_abbreviations = lambda root, cfg: {}
        monkeypatch.setitem(sys.modules, "docx_common", dc)

        units = {k: dict(v) for k, v in UNITS.items()}
        n_u, n_s = md._enrich_unit_and_struct_descriptions(units, FUNCS, GLOBALS, {}, {})
        assert (n_u, n_s) == (0, 0)
        assert "description" not in units["Comp|UnitA"]


class TestTheExporterNoLongerGenerates:
    def test_no_llm_description_call_remains_in_the_exporter(self):
        src = open(os.path.join(PROJECT_ROOT, "engine", "docx_exporter.py"),
                   encoding="utf-8").read()
        for name in ("get_unit_description", "get_struct_description"):
            assert name not in src, (
                "%s is still called during export: the text would be regenerated instead of "
                "read, so a reviewer's correction would be ignored and every export would "
                "re-pay for it" % name)


class TestTheUnitHeaderTableReadsTheStoredText:
    """The unit header table is a Phase-3 view (views/unit_headers.py). Its information column
    for a struct, class or union row is the STORED description -- what Phase 2 generated, or a
    reviewer's correction of it (`structDescription`). Asking the LLM there, at view time, would
    print different words from the ones a reviewer corrected."""

    UNIT = {"path": "Comp/U", "fileName": "U.cpp", "functionIds": [], "globalVariableIds": []}

    def _rows(self, tmp_path, dd, src):
        from views import unit_headers as uh
        (tmp_path / "Comp").mkdir()
        (tmp_path / "Comp" / "U.h").write_text(src, encoding="utf-8")
        return uh.build_rows(self.UNIT, [], dd, {}, str(tmp_path), None, {}, {}, {}, {"Comp/U"})

    @staticmethod
    def _entry(kind, name, line=1, **extra):
        return dict({"kind": kind, "name": name, "qualifiedName": name, "fields": [],
                     "location": {"file": "Comp/U.h", "line": line}}, **extra)

    def test_a_class_row_shows_the_stored_description(self, tmp_path):
        dd = {"Pump": self._entry("class", "Pump", description="Drives the pump.")}
        rows = self._rows(tmp_path, dd, "class Pump {\npublic:\n    int rate;\n};\n")
        row = next(r for r in rows if "class Pump" in r["declaration"])
        assert row["information"] == "Drives the pump."

    def test_a_union_row_shows_the_stored_description(self, tmp_path):
        dd = {"Num": self._entry("union", "Num", description="One number, two views.")}
        rows = self._rows(tmp_path, dd, "union Num {\n    int i;\n    float f;\n};\n")
        row = next(r for r in rows if "union Num" in r["declaration"])
        assert row["information"] == "One number, two views."

    def test_a_typedef_row_shows_its_records_description(self, tmp_path):
        """`typedef struct Cfg {...} Cfg_t;` is one type however it is named, so it reads the
        same text -- and one correction reaches both rows."""
        dd = {"Cfg": self._entry("struct", "Cfg", description="Holds the settings."),
              "typedef@Cfg:Comp/U.h:1": self._entry("typedef", "Cfg_t", underlyingType="Cfg")}
        rows = self._rows(tmp_path, dd, "typedef struct Cfg {\n    int x;\n} Cfg_t;\n")
        typedef_rows = [r for r in rows if r["declaration"].startswith("typedef")]
        assert typedef_rows and all(r["information"] == "Holds the settings." for r in typedef_rows)

    def test_with_nothing_stored_the_view_falls_back_without_the_llm(self, tmp_path, monkeypatch):
        mod = type(sys)("llm_enrichment")
        mod.llm_provider_reachable = lambda cfg: True
        mod.get_struct_description = lambda *a, **k: pytest.fail("the view asked the LLM")
        monkeypatch.setitem(sys.modules, "llm_enrichment", mod)
        from views import unit_headers as uh
        dd = {"Pump": self._entry("class", "Pump")}
        rows = self._rows(tmp_path, dd, "class Pump {\npublic:\n    int rate;\n};\n")
        row = next(r for r in rows if "class Pump" in r["declaration"])
        assert row["information"] == uh._struct_info_from_name("Pump", "Class")

    def test_no_llm_description_call_remains_in_the_view(self):
        src = open(os.path.join(PROJECT_ROOT, "engine", "views", "unit_headers.py"),
                   encoding="utf-8").read()
        assert "get_struct_description" not in src


class TestTheUnitDescriptionRoundTrips:
    """persist_units -> load_units. Without the column the text is written and silently lost."""

    def test_description_survives_the_database(self, tmp_path):
        import datetime
        import sqlalchemy as sa
        sys.path.insert(0, PROJECT_ROOT)
        from api.db.postgres import schema as s
        from core import model_store as ms

        eng = sa.create_engine("sqlite:///" + str(tmp_path / "t.sqlite").replace("\\", "/"))
        s.metadata.create_all(eng)
        units = {"Comp|UnitA": {"name": "UnitA", "path": "a/b", "fileName": "UnitA.cpp",
                                "includedHeaders": [], "description": "What the unit does."}}
        with eng.begin() as cx:
            now = datetime.datetime.now(datetime.timezone.utc)
            cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
            cx.execute(sa.insert(s.versions).values(id="v", project_id="p", version="v",
                                                    created_at=now))
            ms.persist_units(cx, "v", units)
        with eng.connect() as cx:
            back = ms.load_units(cx, "v")
        assert back["Comp|UnitA"]["description"] == "What the unit does."
