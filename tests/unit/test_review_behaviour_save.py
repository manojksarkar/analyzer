"""Correcting one behaviour row's description (REQ-ED-02, REQ-AP-05).

Three things make this kind different from a node label, and each is tested here:

  * the value is a LIST of bullets, edited as one block, stored as one text;
  * it appears in NO picture, so a correction renders nothing;
  * the row is addressed by two ENTITY KEYS, never by the display label -- the label is
    "<unit> - <shortName>", and two different callers can share one.

That last one is the September collision shape: a lossy display string used as an identifier.
The view already learned it on the other half of the pair, which is why `currentFunctionId`
exists beside `currentFunctionName`.
"""
import datetime
import json
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine", "flowchart"))

from api.db.postgres import schema as s
from review import override_service as svc, phase3_overrides as p3, slot
from views import behaviour_diagram as bd

FID = "Comp|UnitA|ns::doThing|void"
ADD = "CompX|UnitB|ns::AddOperation::apply|int"
MUL = "CompX|UnitB|ns::MultiplyOperation::apply|int"
REL = "Sample/behaviour_diagrams/_behaviour_pngs.json"


def _row(caller, label, bullets):
    return {"currentFunctionName": "doThing", "currentFunctionId": FID,
            "currentFunctionDisplay": "doThing", "externalUnitFunction": label,
            "externalCallerId": caller, "pngPath": "x.png",
            "behaviorDescription": list(bullets)}


def _payload():
    # Both callers render to the SAME display label -- the collision, in the fixture.
    return {"_docxRows": {"Comp": {"UnitA": [
        _row(ADD, "UnitB - apply", ["apply calls doThing to add"]),
        _row(MUL, "UnitB - apply", ["apply calls doThing to multiply"]),
    ]}}}


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        cx.execute(sa.insert(s.version_output_files).values(
            version_id="v1", rel_path=REL, content=json.dumps(_payload()),
            group_name="Sample"))
        yield cx


def _stored(conn):
    return json.loads(conn.execute(sa.select(s.version_output_files.c.content)).scalar())


def _rows_of(payload):
    return payload["_docxRows"]["Comp"]["UnitA"]


class TestTheCollisionIsGone:
    def test_two_callers_sharing_a_label_are_separate_slots(self, conn):
        """The whole reason the key changed. Before, both rows produced one slot key, the unique
        constraint kept ONE row, and correcting the second silently replaced the first."""
        a = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Adds two numbers"])
        b = svc.apply_behaviour_override(conn, "v1", FID, MUL, ["Multiplies two numbers"])
        assert a.slot_key != b.slot_key
        assert conn.execute(sa.select(sa.func.count())
                            .select_from(s.text_overrides)).scalar() == 2

    def test_correcting_one_leaves_the_other_alone(self, conn):
        svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Adds two numbers"])
        rows = _rows_of(_stored(conn))
        by_caller = {r["externalCallerId"]: r["behaviorDescription"] for r in rows}
        assert by_caller[ADD] == ["Adds two numbers"]
        assert by_caller[MUL] == ["apply calls doThing to multiply"]

    def test_a_row_without_a_caller_id_is_not_matched_by_its_label(self, conn):
        """A row written before externalCallerId existed cannot be addressed unambiguously, so
        it is not addressed at all. Falling back to the label would apply a correction to
        whichever of the two colliding rows came first."""
        payload = _payload()
        for r in _rows_of(payload):
            r.pop("externalCallerId")
        conn.execute(sa.update(s.version_output_files)
                     .values(content=json.dumps(payload)))
        with pytest.raises(svc.SlotUnknown):
            svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Adds"])


class TestTheListIsOneBlock:
    def test_the_bullets_are_stored_as_one_text(self, conn):
        """REQ-ED-02. `human_text` stays genuinely text for all seven kinds, so REQ-ST-06's
        emptiness check is one rule and the REQ-TD-01 pair stays sentence-against-sentence."""
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["First line", "Second line"])
        row = svc.get_override(conn, "v1", slot.BEHAVIOUR_DESCRIPTION, out.slot_key)
        assert row.human_text == "First line\nSecond line"
        assert "[" not in row.human_text, "stored as JSON; it is meant to stay readable text"

    def test_the_list_comes_back_as_a_list(self, conn):
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["First", "Second"])
        assert list(out.bullets) == ["First", "Second"]
        assert _rows_of(_stored(conn))[0]["behaviorDescription"] == ["First", "Second"]

    def test_a_bullet_containing_a_newline_cannot_split_into_two(self, conn):
        """The separator is only safe because a bullet is collapsed onto one line when it is
        generated. Collapsing again on the way in makes that true regardless of the caller."""
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["one\ntwo", "three"])
        assert list(out.bullets) == ["one two", "three"]

    def test_blank_bullets_are_dropped(self, conn):
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Real", "   ", ""])
        assert list(out.bullets) == ["Real"]

    def test_an_all_blank_list_is_refused(self, conn):
        with pytest.raises(svc.EmptyText):
            svc.apply_behaviour_override(conn, "v1", FID, ADD, ["", "  "])

    def test_an_empty_list_is_refused(self, conn):
        with pytest.raises(svc.EmptyText):
            svc.apply_behaviour_override(conn, "v1", FID, ADD, [])


class TestTheOriginalAndTheHistory:
    def test_the_llm_original_is_captured_once(self, conn):
        first = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Corrected once"])
        svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Corrected twice"])
        row = svc.get_override(conn, "v1", slot.BEHAVIOUR_DESCRIPTION, first.slot_key)
        assert row.llm_text == "apply calls doThing to add"
        assert row.human_text == "Corrected twice"

    def test_history_accumulates_per_row(self, conn):
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["One"])
        svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Two"])
        hist = svc.history_for(conn, "v1", slot.BEHAVIOUR_DESCRIPTION, out.slot_key)
        assert [r.human_text for r in hist] == ["One", "Two"]

    def test_no_shape_is_stored(self, conn):
        """There is no graph for it to be wrong about."""
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["One"])
        row = svc.get_override(conn, "v1", slot.BEHAVIOUR_DESCRIPTION, out.slot_key)
        assert row.slot_shape is None

    def test_an_unknown_row_is_refused(self, conn):
        with pytest.raises(svc.SlotUnknown):
            svc.apply_behaviour_override(conn, "v1", FID, "Comp|UnitZ|gone|", ["x"])


class TestNoPictureIsRendered:
    def test_the_kind_declares_it_renders_nothing(self):
        """MermaidBuilder labels each arrow `<callee>()` -- the function's name -- and appends
        the description to a separate list, so the text is in no image."""
        assert not p3.renders_image(slot.BEHAVIOUR_DESCRIPTION)

    def test_the_png_path_is_untouched_by_a_correction(self, conn):
        svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Corrected"])
        assert all(r["pngPath"] == "x.png" for r in _rows_of(_stored(conn)))


class TestTheDerivation:
    def test_the_deriver_runs_and_is_stamped(self, conn):
        out = svc.apply_behaviour_override(conn, "v1", FID, ADD, ["Corrected"],
                                           derive=lambda **kw: ["behaviourDiagram"])
        assert list(out.views_derived) == ["behaviourDiagram"]
        names = {r.view_name for r in conn.execute(sa.select(s.view_derivations)).fetchall()}
        assert names == {"behaviourDiagram"}


class TestSurvivingARegeneration:
    """REQ-AP-05. Phase 3 regenerates these descriptions from scratch, so the corrections are
    handed to it as an input rather than written into its output."""

    def test_the_view_applies_corrections_from_config(self):
        payload = _payload()
        key = slot.for_behaviour_row(FID, ADD)
        n = bd._apply_text_overrides(
            payload["_docxRows"],
            {p3.CONFIG_KEY: {p3.BEHAVIOUR_KIND: {key: "Corrected by a reviewer"}}})
        assert n == 1
        by_caller = {r["externalCallerId"]: r["behaviorDescription"]
                     for r in _rows_of(payload)}
        assert by_caller[ADD] == ["Corrected by a reviewer"]
        assert by_caller[MUL] == ["apply calls doThing to multiply"]

    def test_an_ordinary_run_changes_nothing(self):
        payload = _payload()
        before = json.dumps(payload)
        assert bd._apply_text_overrides(payload["_docxRows"], {}) == 0
        assert json.dumps(payload) == before

    def test_a_failure_does_not_fail_the_run(self, monkeypatch):
        monkeypatch.setattr(p3, "apply_to_docx_rows",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
        assert bd._apply_text_overrides(
            _payload()["_docxRows"],
            {p3.CONFIG_KEY: {p3.BEHAVIOUR_KIND: {"k": "x"}}}) == 0

    def test_it_is_wired_into_the_view(self):
        """The helper working and never being called is the failure this guards -- everything
        passes and corrections silently stop surviving a regeneration."""
        import re
        src = open(os.path.join(PROJECT_ROOT, "engine", "views", "behaviour_diagram.py"),
                   encoding="utf-8").read()
        call = re.compile(r"^[ \t]+_apply_text_overrides\(docx_rows, config\)", re.M)
        assert call.search(src), "the behaviour view no longer applies corrections"
        assert not call.search("def _apply_text_overrides(docx_rows, config) -> int:"), (
            "the matcher also matches the definition, so it could never fail")
        assert call.search(src).start() < src.index('out_path = os.path.join'), (
            "corrections are applied after the manifest is written")
