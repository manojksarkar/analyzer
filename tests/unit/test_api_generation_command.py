"""A run started from the web app goes through `analyzer.py generate`.

e0f5aef made `analyzer.py` the only front door and turned `engine/incremental/generate.py` and
`engine.py` into redirects that print "This is not a command any more" and exit 2. The API's
runner kept spawning them, so every generation started from the web app failed at once, before
parsing anything -- on every branch since 2026-08-24. Nothing noticed, because the CLI was the
only thing anyone ran.

These tests pin the command to the CLI the project standardised on, and check that the CLI
accepts every option a job can carry under the name it now has.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

import analyzer as A  # noqa: E402
from api.services import pipeline_runner as pr  # noqa: E402

CONFIG = Path("workspaces") / "p1" / "config.json"


def _job(**over):
    base = dict(project_id="p1", version_id="ver1a2b3c4d", branch="br_trunk",
                commit_sha="8b3e313f892f2b3baea252d98f0b083015622e98", mode="auto",
                scope={"type": "group", "names": ["Garbage Collection Manager"]},
                reference_version_id=None, data_dict_id=None, no_llm=False,
                narrowed_parse=True)
    base.update(over)
    return SimpleNamespace(**base)


def _parsed(job):
    """The job's command as the CLI parses it -- argparse exits 2 on an unknown flag."""
    cmd = pr._generate_cmd(job, Path(ROOT), CONFIG)
    return cmd, A.build_parser().parse_args(cmd[2:])


class TestTheCommandIsTheCli:
    def test_it_runs_analyzer_generate(self):
        cmd = pr._generate_cmd(_job(), Path(ROOT), CONFIG)
        assert os.path.basename(cmd[1]) == "analyzer.py"
        assert cmd[2] == "generate"

    def test_it_runs_no_retired_script(self):
        cmd = pr._generate_cmd(_job(), Path(ROOT), CONFIG)
        assert not any(part.replace("\\", "/").endswith(("incremental/generate.py",
                                                         "incremental/engine.py"))
                       for part in cmd)

    def test_the_scripts_it_used_to_run_only_redirect(self):
        """Why the command had to change: both old entry points exit 2 whatever they are
        given. If one of them is ever made to work again, this says so, and the choice
        between them can be revisited."""
        from incremental import engine, generate
        for mod in (engine, generate):
            with pytest.raises(SystemExit) as exc:
                mod.main()
            assert exc.value.code == 2


class TestTheCliAcceptsEveryOption:
    def test_identity_scope_and_config(self):
        _, a = _parsed(_job())
        assert (a.command, a.project_id, a.version_id) == ("generate", "p1", "ver1a2b3c4d")
        assert a.branch == "br_trunk"
        assert a.commit == "8b3e313f892f2b3baea252d98f0b083015622e98"
        assert a.scope == "group:Garbage Collection Manager"
        assert a.config == str(CONFIG)

    def test_a_whole_project_scope(self):
        _, a = _parsed(_job(scope=None))
        assert a.scope == "project"

    def test_auto_leaves_the_decision_to_the_data(self):
        _, a = _parsed(_job(mode="auto"))
        assert a.full is False

    def test_full_forces_a_full_run(self):
        _, a = _parsed(_job(mode="full"))
        assert a.full is True

    def test_a_chosen_baseline_is_passed_under_auto(self):
        _, a = _parsed(_job(reference_version_id="ver0f0f0f0f"))
        assert a.base_version == "ver0f0f0f0f"

    def test_a_baseline_means_nothing_to_a_full_run(self):
        cmd, a = _parsed(_job(mode="full", reference_version_id="ver0f0f0f0f"))
        assert a.base_version is None and "--base-version" not in cmd

    def test_narrowed_parse_is_opted_out_of(self):
        _, on = _parsed(_job(narrowed_parse=True))
        _, off = _parsed(_job(narrowed_parse=False))
        assert on.no_narrowed_parse is False
        assert off.no_narrowed_parse is True

    def test_a_full_run_has_no_narrowed_parse_to_turn_off(self):
        cmd, _ = _parsed(_job(mode="full", narrowed_parse=False))
        assert "--no-narrowed-parse" not in cmd

    def test_data_dictionary_and_no_llm(self):
        _, a = _parsed(_job(data_dict_id="dd42", no_llm=True))
        assert a.data_dict == "dd42"
        assert a.no_llm is True

    def test_the_defaults_add_nothing(self):
        _, a = _parsed(_job())
        assert a.data_dict is None and a.no_llm is False and a.base_version is None
        assert a.doc_type == "swe3"      # what both engine functions default to, as before


class TestTheRunnerUsesIt:
    """The command above only matters if the runner is the one that spawns it."""

    def _run(self, monkeypatch, **job_over):
        from api.db.in_memory import InMemoryDatabase
        from api.models.domain import AnalysisJob, AnalysisPhase
        import datetime

        db = InMemoryDatabase()
        project = db.projects.get("p1")
        fields = dict(id="jobwire01", project_id="p1",
                      commit_sha="8b3e313f892f2b3baea252d98f0b083015622e98",
                      version_id="ver1a2b3c4d", reference_version_id=None, status="queued",
                      pause_after_phase1=False, layer_filter=None, phase=1, phase_pct=0,
                      current_activity="", activity_detail="", elapsed_seconds=0,
                      eta_seconds=None,
                      phases=[AnalysisPhase(n, "p%d" % n, "pending", None) for n in (1, 2, 3, 4)],
                      started_at=datetime.datetime.now(datetime.timezone.utc),
                      completed_at=None, error_message=None, branch="main", version_tag="t1",
                      mode="auto", scope=None, no_llm=False, data_dict_id=None,
                      narrowed_parse=True)
        fields.update(job_over)
        db.jobs.create(AnalysisJob(**fields))

        seen = {}
        monkeypatch.setattr(pr, "_checkout", lambda *a, **k: None)
        monkeypatch.setattr(pr, "_write_project_config",
                            lambda *a, **k: (Path("workspaces") / "p1" / "config.json", {}))
        monkeypatch.setattr(pr, "_store_resolved_config", lambda *a, **k: None)
        monkeypatch.setattr(pr, "_engine_db_env", lambda *a, **k: {})

        def _exec(_db, _job_id, cmd, **_kw):
            seen["cmd"] = cmd
            return False                 # stop before _complete: nothing to finalise
        monkeypatch.setattr(pr, "_execute_subprocess", _exec)
        pr._init_state("jobwire01")
        pr._inner_run_locked(db, "jobwire01", project)
        return db, seen

    def test_the_spawned_command_is_analyzer_generate(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        assert os.path.basename(seen["cmd"][1]) == "analyzer.py"
        assert seen["cmd"][2] == "generate"
        assert "--version-id" in seen["cmd"] and "ver1a2b3c4d" in seen["cmd"]

    def test_a_job_with_no_version_fails_with_a_reason(self, monkeypatch):
        db, seen = self._run(monkeypatch, version_id=None)
        assert "cmd" not in seen
        job = db.jobs.get("jobwire01")
        assert job.status == "failed" and "no version id" in job.error_message
