"""Re-export must not touch the SHARED repo model/ and output/ (doc 09, B1 + C11b).

Generation was moved onto per-version directories, but re-export bypasses the incremental
orchestrator entirely and kept its own staging step:

    for sub in ("model", "output"):
        shutil.rmtree(root / sub)          # the shared <repo>/model, <repo>/output
        shutil.copytree(adir / sub, root / sub)

which is the exact concurrency hazard B1 removed — two jobs re-exporting at once wipe each
other's staged trees mid-run, and a re-export wipes a *generation* using those dirs. It also
copied the whole model and output twice per re-export.

These assert on the command and on the source, because the failure is "a directory was
deleted", which a normal unit test cannot observe after the fact.
"""
import os

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _source(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestReexportRunsInPlace:
    def test_no_staging_into_the_shared_repo_dirs(self):
        src = _source("api/services/pipeline_runner.py")
        assert 'for sub in ("model", "output"):' not in src, (
            "re-export must not stage the version's trees into the shared repo dirs")
        assert "shutil.rmtree(dst, ignore_errors=True)" not in src, (
            "re-export must not rmtree a shared directory another job may be using")

    def test_reexport_passes_the_version_scoped_roots(self):
        src = _source("api/services/pipeline_runner.py")
        assert 'model_root=adir / "model"' in src
        assert 'output_root=adir / "output"' in src

    def test_build_cmd_emits_the_flags(self):
        """The flags have to reach run.py, not just exist as parameters."""
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd

        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = _build_cmd(job, "/checkout", "/cfg.json", from_phase=4, use_model=True,
                         model_root="/ver/model", output_root="/ver/output")
        assert "--model-root" in cmd and cmd[cmd.index("--model-root") + 1] == "/ver/model"
        assert "--output-root" in cmd and cmd[cmd.index("--output-root") + 1] == "/ver/output"

    @staticmethod
    def _cmd(scope, layer_filter=None):
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd
        job = type("J", (), {"scope": scope, "layer_filter": layer_filter, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        return _build_cmd(job, "/checkout", "/cfg.json", from_phase=3, use_model=True)

    @staticmethod
    def _values(cmd, flag):
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == flag]

    @pytest.mark.parametrize("stype,flag", [("group", "--selected-group"),
                                            ("component", "--selected-component"),
                                            ("layer", "--selected-layer")])
    def test_every_name_of_the_scope_is_re_derived(self, stype, flag):
        """A re-export copies the generation's scope. A version generated for two groups was
        re-exported for the first alone: the second group's views were never re-derived, and
        its corrections never reached the Word file."""
        cmd = self._cmd({"type": stype, "names": ["Layer1.My Sample", "Layer1.Full"]})
        assert self._values(cmd, flag) == ["Layer1.My Sample", "Layer1.Full"]

    @pytest.mark.parametrize("stype", ["component", "group", "layer", "project"])
    def test_every_scope_gets_one_document_per_component(self, stype):
        """A component scope used to be left without `--component-per-docx`: a version of several
        components was re-exported as ONE bundled document, and each component's own document
        kept its old text."""
        cmd = self._cmd({"type": stype, "names": ["Layer1.Lib", "Layer1.Util"]})
        assert "--component-per-docx" in cmd

    def test_a_project_scope_selects_nothing(self):
        cmd = self._cmd({"type": "project"}, layer_filter=None)
        assert not any(a.startswith("--selected-") for a in cmd)

    def test_the_legacy_layer_filter_still_applies_without_a_scope(self):
        assert self._values(self._cmd(None, layer_filter="Layer2"), "--selected-layer") ==             ["Layer2"]

    def test_flags_are_omitted_when_not_given(self):
        """Generation calls _build_cmd without them; that path must be unchanged."""
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _build_cmd

        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = _build_cmd(job, "/checkout", "/cfg.json")
        assert "--model-root" not in cmd and "--output-root" not in cmd
        assert "--doc-type" not in cmd


class TestAReexportWritesEveryDocumentTheVersionHas:
    """A web run writes SWE.4 beside SWE.3 (`--doc-type all`), and a node-label correction
    re-derives the SWE.4 specs at save time. A re-export ran run.py with no `--doc-type` and asked
    the export guard about SWE.3 alone, so the SWE.4 Word file kept the old labels."""

    @staticmethod
    def _db(total=0, fail=False):
        class Documents:
            def list_for_project(self, project_id, version_id=None, process=None, **_kw):
                if fail:
                    raise RuntimeError("database unavailable")
                assert (project_id, version_id, process) == ("p1", "v1", "SWE.4")
                return [], total
        return type("Db", (), {"documents": Documents()})()

    @staticmethod
    def _runner():
        import sys
        sys.path.insert(0, ROOT)
        from api.services import pipeline_runner
        return pipeline_runner

    def test_a_version_with_swe4_documents_exports_both(self):
        assert self._runner().export_doc_type(self._db(total=2), "p1", "v1") == "all"

    def test_a_version_with_swe3_alone_exports_swe3(self):
        assert self._runner().export_doc_type(self._db(total=0), "p1", "v1") == "swe3"

    def test_a_question_that_cannot_be_answered_keeps_swe3(self):
        """What the re-export did before: better than failing the job over the lookup."""
        assert self._runner().export_doc_type(self._db(fail=True), "p1", "v1") == "swe3"

    def test_the_doc_type_reaches_run_py(self):
        job = type("J", (), {"scope": None, "layer_filter": None, "no_llm": False,
                             "data_dict_id": None, "project_id": "p1"})()
        cmd = self._runner()._build_cmd(job, "/checkout", "/cfg.json", from_phase=4,
                                        use_model=True, doc_type="all")
        assert cmd[cmd.index("--doc-type") + 1] == "all"

    def test_the_phase_question_is_asked_about_those_documents(self, monkeypatch):
        import core.db as core_db
        import review.export_guard as guard

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        asked = []
        monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: True)
        monkeypatch.setattr(core_db, "get_engine",
                            lambda *a, **k: type("E", (), {"connect": lambda self: Connection()})())
        monkeypatch.setattr(guard, "staleness", lambda cx, vid, doc_types=None, **kw: (
            asked.append(doc_types) or type("S", (), {"is_stale": False})()))
        assert self._runner()._reexport_from_phase("v1", "all") == 4
        assert asked == ["all"]

    def test_an_update_by_component_is_judged_on_its_components(self, monkeypatch):
        """A correction in ANOTHER component sent an update of Sample Core through Phase 3 --
        every one of its 28 flowcharts redrawn, 416 s, for a description change in Lib (the
        real-app test of 2026-10-06). An update by component asks about its components only."""
        import core.db as core_db
        import review.export_guard as guard

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: True)
        monkeypatch.setattr(core_db, "get_engine",
                            lambda *a, **k: type("E", (), {"connect": lambda self: Connection()})())
        monkeypatch.setattr(guard, "staleness", lambda *a, **k: type(
            "S", (), {"is_stale": True, "explain": lambda self: "a correction"})())
        behind = {"L1.Lib"}
        monkeypatch.setattr(guard, "stale_components",
                            lambda cx, vid, doc_types, comps, **kw: [c for c in comps if c in behind])
        runner = self._runner()
        assert runner._reexport_from_phase("v1", "all", ["L1.Sample-Core"]) == 4
        assert runner._reexport_from_phase("v1", "all", ["L1.Sample-Core", "L1.Lib"]) == 3
        assert runner._reexport_from_phase("v1", "all") == 3            # a whole version, as before
        job = type("J", (), {"scope": {"type": "component", "names": ["L1.Sample-Core"]}})()
        assert runner._scoped_components(job) == ["L1.Sample-Core"]
        assert runner._scoped_components(type("J", (), {"scope": {"type": "group",
                                                                  "names": ["G"]}})()) is None

    def test_the_reexport_passes_one_answer_to_both(self):
        src = _source("api/services/pipeline_runner.py")
        assert 'doc_type = export_doc_type(db, job.project_id, getattr(job, "version_id", None))' in src
        assert '_reexport_from_phase(getattr(job, "version_id", None), doc_type,' in src
        assert "doc_type=doc_type)" in src


class TestReexportPersistsItsOutput:
    """With C0 the document renders from Postgres, so a re-export that only rewrote FILES
    would leave the stored views at the previous render — the re-export would appear to have
    done nothing at all."""

    def test_reexport_captures_output_back_into_the_store(self):
        src = _source("api/services/pipeline_runner.py")
        assert "_capture_reexport_output(db, job, adir, since=since)" in src
        assert "def _capture_reexport_output" in src
        # Only the components it wrote (WORD_FILE_UPDATES S4a), and when it started (S0).
        assert ("store.capture_output(version_id, str(adir / \"output\"), components=comps, "
                "since=since)") in src

    def test_capture_is_skipped_without_a_version_id(self):
        """A legacy commit-keyed run has nothing version-scoped to update, and must not raise."""
        import sys
        sys.path.insert(0, ROOT)
        from api.services.pipeline_runner import _capture_reexport_output
        job = type("J", (), {"project_id": "p1", "version_id": None})()
        _capture_reexport_output(None, job, None)          # must be a silent no-op
