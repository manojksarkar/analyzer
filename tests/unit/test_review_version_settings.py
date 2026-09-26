"""A correction obeys the version's own settings, and records what produced the text.

Two audit findings, both of the same shape: a thing the spec said would happen, that nothing did.

**`llm.overrideHistoryDepth` was documented and ignored.** Setting it to 3 still kept 10 — a
configuration key that does nothing is worse than none, because somebody sets it and believes it.

**The provenance columns were always NULL** (`REQ-TD-02`). `llm_model` and `llm_cache_version`
exist so a correction can still be interpreted after a prompt change, which is the entire reason
the (wrong, right) pair is kept. Empty, they cannot.

Both read the **version's** config, not today's. A correction made now is a correction to text
generated then, so its provenance is then's model, and the cap it obeys is the one that version
was created under.
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

from api.db.postgres import schema as s
from review import override_service as svc, slot

FN = "Comp|UnitA|ns::doThing|void"
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _engine(resolved_config=None):
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    cx = eng.connect()
    tx = cx.begin()
    cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=NOW))
    cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                            created_at=NOW,
                                            resolved_config=resolved_config))
    return cx, tx


@pytest.fixture
def plain():
    cx, tx = _engine()
    yield cx
    tx.rollback()


def _model():
    return {"functions": {FN: {"qualifiedName": "ns::doThing", "description": "LLM words."}},
            "globalVariables": {}, "units": {}, "dataDictionary": {}}


def _save(cx, text, **kw):
    return svc.apply_override(cx, "v1", slot.DESCRIPTION,
                              slot.for_entity(slot.DESCRIPTION, FN), text,
                              models=svc.ModelAccess(artifacts=_model()), **kw)


class TestReadingTheVersionsSettings:
    def test_no_stored_config_falls_back(self, plain):
        st = svc.version_settings(plain, "v1")
        assert st == svc.VersionSettings(svc.DEFAULT_HISTORY_DEPTH, None, None)

    def test_the_settings_are_read(self):
        cx, tx = _engine({"llm": {"overrideHistoryDepth": 3, "model": "gpt-4o-mini",
                                  "cacheVersion": 7}})
        try:
            st = svc.version_settings(cx, "v1")
            assert st.history_depth == 3
            assert st.llm_model == "gpt-4o-mini"
            assert st.llm_cache_version == 7
        finally:
            tx.rollback()

    def test_a_partial_config_uses_the_default_for_what_is_missing(self):
        cx, tx = _engine({"llm": {"model": "ollama/llama3"}})
        try:
            st = svc.version_settings(cx, "v1")
            assert st.history_depth == svc.DEFAULT_HISTORY_DEPTH
            assert st.llm_model == "ollama/llama3"
            assert st.llm_cache_version is None
        finally:
            tx.rollback()

    def test_rubbish_does_not_stop_a_save(self):
        """A malformed config must not be the reason somebody cannot save a sentence."""
        cx, tx = _engine({"llm": {"overrideHistoryDepth": "lots", "cacheVersion": "v2"}})
        try:
            st = svc.version_settings(cx, "v1")
            assert st.history_depth == svc.DEFAULT_HISTORY_DEPTH
            assert st.llm_cache_version is None
        finally:
            tx.rollback()

    def test_an_unknown_version_is_not_an_error(self, plain):
        assert svc.version_settings(plain, "nope").history_depth == svc.DEFAULT_HISTORY_DEPTH


class TestTheHistoryCapIsHonoured:
    def test_the_versions_depth_is_used(self):
        """The finding: this setting was documented in the spec, named in the schema comment and
        in the API docs, and read by nothing."""
        cx, tx = _engine({"llm": {"overrideHistoryDepth": 2}})
        try:
            for i in range(5):
                _save(cx, "Edit %d." % i)
            hist = svc.history_for(cx, "v1", slot.DESCRIPTION,
                                   slot.for_entity(slot.DESCRIPTION, FN))
            assert [h.human_text for h in hist] == ["Edit 3.", "Edit 4."]
        finally:
            tx.rollback()

    def test_an_explicit_argument_still_wins(self):
        """Tests and callers that pass a depth must keep deciding for themselves."""
        cx, tx = _engine({"llm": {"overrideHistoryDepth": 2}})
        try:
            for i in range(5):
                _save(cx, "Edit %d." % i, history_depth=4)
            hist = svc.history_for(cx, "v1", slot.DESCRIPTION,
                                   slot.for_entity(slot.DESCRIPTION, FN))
            assert len(hist) == 4
        finally:
            tx.rollback()

    def test_no_config_keeps_ten(self, plain):
        for i in range(12):
            _save(plain, "Edit %d." % i)
        hist = svc.history_for(plain, "v1", slot.DESCRIPTION,
                               slot.for_entity(slot.DESCRIPTION, FN))
        assert len(hist) == svc.DEFAULT_HISTORY_DEPTH


class TestProvenanceIsRecorded:
    def test_the_model_and_prompt_version_are_stored(self):
        """REQ-TD-02. Without them a correction cannot be interpreted after a prompt change."""
        cx, tx = _engine({"llm": {"model": "gpt-4o-mini", "cacheVersion": 7}})
        try:
            _save(cx, "Human words.")
            row = svc.get_override(cx, "v1", slot.DESCRIPTION,
                                   slot.for_entity(slot.DESCRIPTION, FN))
            assert row.llm_model == "gpt-4o-mini"
            assert row.llm_cache_version == 7
        finally:
            tx.rollback()

    def test_a_flowchart_correction_records_it_too(self):
        cx, tx = _engine({"llm": {"model": "gpt-4o-mini", "cacheVersion": 7}})
        try:
            cx.execute(sa.insert(s.version_output_files).values(
                version_id="v1", rel_path="Sample/flowcharts/UnitA.json", group_name="Sample",
                content=json.dumps([{"name": "ns::doThing", "functionKey": FN,
                                     "cfg": {"entry": "n0", "exits": ["n1"], "edges": [],
                                             "nodes": [{"id": "n0", "type": "ACTION",
                                                        "label": "llm n0", "rawCode": "c",
                                                        "line": 1, "endLine": 1},
                                                       {"id": "n1", "type": "ACTION",
                                                        "label": "llm n1", "rawCode": "c",
                                                        "line": 1, "endLine": 1}]},
                                     "flowchart": "digraph G {}"}])))
            svc.apply_flowchart_overrides(cx, "v1", FN, {"n1": "Corrected"})
            row = svc.get_override(cx, "v1", slot.NODE_LABEL, slot.for_node(FN, "n1"))
            assert row.llm_model == "gpt-4o-mini" and row.llm_cache_version == 7
        finally:
            tx.rollback()

    def test_no_config_leaves_it_null_rather_than_guessing(self, plain):
        """A version generated before `resolved_config` existed has none. Inventing today's model
        would be a plausible-looking lie in the training data."""
        _save(plain, "Human words.")
        row = svc.get_override(plain, "v1", slot.DESCRIPTION,
                               slot.for_entity(slot.DESCRIPTION, FN))
        assert row.llm_model is None and row.llm_cache_version is None

    def test_an_explicit_argument_still_wins(self):
        cx, tx = _engine({"llm": {"model": "gpt-4o-mini"}})
        try:
            _save(cx, "Human words.", llm_model="explicitly-this-one")
            row = svc.get_override(cx, "v1", slot.DESCRIPTION,
                                   slot.for_entity(slot.DESCRIPTION, FN))
            assert row.llm_model == "explicitly-this-one"
        finally:
            tx.rollback()
