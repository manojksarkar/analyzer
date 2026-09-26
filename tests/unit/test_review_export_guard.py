"""The export refuses to ship text a correction has already replaced (REQ-AP-04).

`reexport --from-phase 4` is "export only" and skips Phase 3, the step that rebuilds the view rows
the document is built from. Correct a description and export a second later and the DOCX carries
the previous wording, silently. That is the failure this guard exists for, and it is a query over
stored facts rather than a flag, so a future write path that forgets to re-derive still cannot slip
past it.
"""
import datetime
import os
import re
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s
from review import export_guard as g

T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
T1 = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
T2 = datetime.datetime(2026, 1, 3, tzinfo=datetime.timezone.utc)


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://")
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        now = datetime.datetime.now(datetime.timezone.utc)
        cx.execute(sa.insert(s.projects).values(id="p", name="p", created_at=now))
        cx.execute(sa.insert(s.versions).values(id="v1", project_id="p", version="v1",
                                                created_at=now))
        yield cx


def _override(conn, when, key="Comp|UnitA|f|"):
    conn.execute(sa.insert(s.text_overrides).values(
        version_id="v1", slot_kind="description", slot_key=key,
        llm_text="llm", human_text="human", is_orphaned=False, updated_at=when))


class TestTheOrdinaryCase:
    def test_a_version_nobody_corrected_is_never_stale(self, conn):
        """Every project today. It must also be cheap -- one indexed lookup that returns NULL
        and stops, with no join and no scan."""
        st = g.staleness(conn, "v1")
        assert not st.is_stale
        assert st.override_count == 0

    def test_a_correction_older_than_the_derivation_is_fine(self, conn):
        _override(conn, T0)
        g.stamp_pipeline_derivation(conn, "v1", now=T1)
        assert not g.staleness(conn, "v1").is_stale

    def test_a_correction_newer_than_the_derivation_is_stale(self, conn):
        """The whole point: the model and the override table moved, the view rows did not."""
        g.stamp_pipeline_derivation(conn, "v1", now=T0)
        _override(conn, T1)
        st = g.staleness(conn, "v1")
        assert st.is_stale
        assert "newer than the derived output" in st.reason


class TestAbsenceOfEvidence:
    def test_corrections_with_no_recorded_derivation_are_stale(self, conn):
        """Not evidence of freshness -- the absence of evidence. A guard that reads "no data" as
        "fine" is the guard that does not guard."""
        _override(conn, T1)
        st = g.staleness(conn, "v1")
        assert st.is_stale
        assert "ever recorded" in st.reason

    def test_the_oldest_derivation_decides_not_the_newest(self, conn):
        """One view re-derived after a correction must not vouch for the others. Comparing
        against the NEWEST would let a single fresh view mask every stale one."""
        g.stamp_pipeline_derivation(conn, "v1", group_name="Alpha", now=T0)
        _override(conn, T1)
        conn.execute(sa.insert(s.view_derivations).values(
            version_id="v1", view_name="interfaceTables", group_name="Alpha", derived_at=T2))
        assert g.staleness(conn, "v1").is_stale

    def test_re_deriving_everything_clears_it(self, conn):
        g.stamp_pipeline_derivation(conn, "v1", now=T0)
        _override(conn, T1)
        assert g.staleness(conn, "v1").is_stale
        g.stamp_pipeline_derivation(conn, "v1", now=T2)
        assert not g.staleness(conn, "v1").is_stale


class TestScope:
    def test_another_version_does_not_make_this_one_stale(self, conn):
        conn.execute(sa.insert(s.versions).values(
            id="v2", project_id="p", version="v2",
            created_at=datetime.datetime.now(datetime.timezone.utc)))
        g.stamp_pipeline_derivation(conn, "v1", now=T1)
        conn.execute(sa.insert(s.text_overrides).values(
            version_id="v2", slot_kind="description", slot_key="k",
            llm_text="a", human_text="b", is_orphaned=False, updated_at=T2))
        assert not g.staleness(conn, "v1").is_stale
        assert g.staleness(conn, "v2").is_stale


class TestTheStamp:
    def test_it_is_idempotent_and_moves_forward(self, conn):
        g.stamp_pipeline_derivation(conn, "v1", now=T0)
        g.stamp_pipeline_derivation(conn, "v1", now=T2)
        rows = conn.execute(sa.select(s.view_derivations)).fetchall()
        assert len(rows) == 1, "a second run appended instead of moving the row forward"
        assert g._aware(rows[0].derived_at) == T2

    def test_groups_are_stamped_separately(self, conn):
        g.stamp_pipeline_derivation(conn, "v1", group_name="Alpha", now=T0)
        g.stamp_pipeline_derivation(conn, "v1", group_name="Beta", now=T0)
        assert len(conn.execute(sa.select(s.view_derivations)).fetchall()) == 2

    def test_a_stale_group_keeps_the_version_stale(self, conn):
        """Two groups, only one re-derived. The document for the other still carries the old
        text, so the version is not exportable."""
        g.stamp_pipeline_derivation(conn, "v1", group_name="Alpha", now=T0)
        g.stamp_pipeline_derivation(conn, "v1", group_name="Beta", now=T0)
        _override(conn, T1)
        g.stamp_pipeline_derivation(conn, "v1", group_name="Alpha", now=T2)
        assert g.staleness(conn, "v1").is_stale


class TestAssertExportable:
    def test_it_passes_when_fresh(self, conn):
        g.stamp_pipeline_derivation(conn, "v1", now=T1)
        assert g.assert_exportable(conn, "v1").is_stale is False

    def test_it_raises_when_stale_and_says_what_to_run(self, conn):
        g.stamp_pipeline_derivation(conn, "v1", now=T0)
        _override(conn, T1)
        with pytest.raises(g.StaleExport) as exc:
            g.assert_exportable(conn, "v1")
        msg = str(exc.value)
        assert "--from-phase 3" in msg, "the error must say how to fix it, not just that it failed"
        assert "v1" in msg


class TestNaiveTimestamps:
    def test_a_naive_timestamp_does_not_crash_the_export(self, conn):
        """SQLite returns naive datetimes where Postgres returns aware ones. Comparing the two
        raises TypeError, which inside an export path reads as a crash rather than as the
        stale-or-not answer the caller asked for."""
        conn.execute(sa.insert(s.view_derivations).values(
            version_id="v1", view_name=g.PIPELINE_ALL, group_name="",
            derived_at=datetime.datetime(2026, 1, 1)))          # naive
        _override(conn, T1)
        st = g.staleness(conn, "v1")
        assert st.is_stale is True


class TestItIsWiredIntoReexport:
    """The guard existing and never being called is the failure mode -- everything passes and
    `--from-phase 4` still ships stale text. `cmd_reexport` cannot be invoked here (it needs a
    workspace, a checkout and a subprocess), so the call site is checked in the source, the same
    way the flowcharts view's hook is."""

    @staticmethod
    def _source():
        return open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()

    CALL = re.compile(r"^[ 	]+rc = _refuse_stale_export\(a\.version_id\)", re.M)

    def test_reexport_calls_the_guard(self):
        assert self.CALL.search(self._source()), (
            "reexport no longer checks staleness, so --from-phase 4 can ship superseded text")

    def test_the_matcher_rejects_the_definition(self):
        """A matcher that also matches `def _refuse_stale_export(...)` could never fail. That
        exact mistake was made once already in this feature's tests."""
        assert not self.CALL.search("def _refuse_stale_export(version_id: str) -> int:")

    def test_the_check_runs_before_the_pipeline_is_launched(self):
        src = self._source()
        call = self.CALL.search(src)
        assert call and call.start() < src.index('_script(os.path.join(_ROOT, "engine", "run.py")'), (
            "the guard runs after the export; it must refuse before any work is done")

    def test_only_phase_4_is_gated(self):
        """Phases 2 and 3 re-derive on their way through, so gating them would refuse a command
        that is itself the fix."""
        assert "if a.from_phase >= 4 and not forced:" in self._source()

    def test_there_is_an_escape_hatch(self):
        """A guard with no override becomes something people work around by other means."""
        assert '"--force"' in self._source()


class TestTheApiRederivesRatherThanRefusing:
    """The same question, answered differently because the asker is different.

    The CLI refuses and prints `--from-phase 3`. A reviewer who pressed "re-export" in the UI
    seconds after fixing a sentence should not have to learn what a phase is, so the API applies
    that remedy instead of recommending it.

    These drive the real function with a real database, because the wiring tests beside them only
    read the source -- and a decision that is computed correctly and then ignored looks identical
    to source.
    """

    @staticmethod
    def _decide(conn, monkeypatch, version_id="v1"):
        """Run `_reexport_from_phase` against this test's SQLite connection."""
        import api.services.pipeline_runner as pr
        from core import db as core_db

        class _Eng:
            def connect(self):
                class _Cx:
                    def __enter__(_s):
                        return conn

                    def __exit__(_s, *a):
                        return False
                return _Cx()

        monkeypatch.setattr(core_db, "is_database_configured", lambda: True)
        monkeypatch.setattr(core_db, "get_engine", lambda *a, **k: _Eng())
        return pr._reexport_from_phase(version_id)

    def test_a_clean_version_exports_only(self, conn, monkeypatch):
        """Nothing has been corrected since the views were built, so Phase 3 would be waste."""
        g.stamp_pipeline_derivation(conn, "v1", now=T1)
        assert self._decide(conn, monkeypatch) == 4

    def test_a_correction_newer_than_the_views_re_derives(self, conn, monkeypatch):
        """THE CASE THIS EXISTS FOR. Phase 4 alone would ship what Phase 3 wrote last time."""
        g.stamp_pipeline_derivation(conn, "v1", now=T1)
        _override(conn, T2)
        assert self._decide(conn, monkeypatch) == 3

    def test_a_version_never_derived_re_derives(self, conn, monkeypatch):
        """Absence of evidence is not evidence of freshness -- the same rule the guard uses."""
        _override(conn, T2)
        assert self._decide(conn, monkeypatch) == 3

    def test_a_pending_picture_re_derives(self, conn, monkeypatch):
        """A correction saved where no output tree existed leaves the text right and the PNG
        owed. Exporting now yields a document whose words and picture disagree, which is worse
        than one that is uniformly out of date."""
        g.stamp_pipeline_derivation(conn, "v1", now=T2)
        _override(conn, T1)
        from review import render_queue
        render_queue.enqueue(conn, "v1", "Comp|UnitA|f|", "f.png", user_id="u1", now=T1)
        assert self._decide(conn, monkeypatch) == 3

    def test_no_version_id_exports_only(self, conn, monkeypatch):
        """A legacy commit-keyed job. There is nothing to be stale against."""
        assert self._decide(conn, monkeypatch, version_id=None) == 4

    def test_no_database_exports_only(self, monkeypatch):
        """An unavailable guard must not quietly change what the pipeline does."""
        import api.services.pipeline_runner as pr
        from core import db as core_db
        monkeypatch.setattr(core_db, "is_database_configured", lambda: False)
        assert pr._reexport_from_phase("v1") == 4

    def test_a_failing_guard_exports_only(self, monkeypatch):
        """Same rule, arrived at the hard way: if asking raises, the answer is the old
        behaviour, not a new one."""
        import api.services.pipeline_runner as pr
        from core import db as core_db

        def _boom():
            raise RuntimeError("database is down")

        monkeypatch.setattr(core_db, "is_database_configured", _boom)
        assert pr._reexport_from_phase("v1") == 4
