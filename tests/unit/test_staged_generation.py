"""Staged generation: the rules behind `export`, `reexport`, `resume`, `progress`, and the frozen
copy `--detach` runs on (engine/incremental/staged.py, engine/core/frozen_run.py,
api/services/version_components.resolve). Pure: no database, no pipeline."""
import datetime
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

from incremental import staged  # noqa: E402
from core import frozen_run  # noqa: E402
from api.services.version_components import resolve  # noqa: E402

UTC = datetime.timezone.utc


def comp(cid, state, *, in_model=True, docs=(), error=None):
    layer, _, name = cid.partition(".")
    return {"component": cid, "layer": layer, "name": name, "state": state, "in_model": in_model,
            "error": error, "documents": [{"id": f"d-{cid}-{p}", "process": p, "status": s}
                                          for p, s in docs]}


VIEW = [
    comp("L1.Math", "generated", docs=[("SWE.3", "approved"), ("SWE.4", "in_review")]),
    comp("L1.App", "not_requested"),
    comp("L1.Util", "failed", error="Components: L1.Util: stopped with exit code 1"),
    comp("L2.Gpio", "stopped"),
    comp("L2.Uart", "generating"),
    comp("L2.Old", "generated", in_model=False, docs=[("SWE.3", "in_review")]),
]


class TestExportTargets:
    def test_remaining_is_every_component_of_the_model_without_documents(self):
        todo, skipped = staged.export_targets(VIEW, [], remaining=True)
        assert todo == ["L1.App", "L1.Util", "L2.Gpio"] and skipped == []

    def test_named_ones_skip_what_is_generated_or_being_generated(self):
        todo, skipped = staged.export_targets(VIEW, ["L1.Math", "L1.App", "L2.Uart"],
                                              remaining=False)
        assert todo == ["L1.App"] and skipped == ["L1.Math", "L2.Uart"]

    def test_a_component_outside_the_model_is_never_made(self):
        assert staged.export_targets(VIEW, ["L2.Old"], remaining=False) == ([], [])


class TestReexport:
    def test_only_generated_components_are_made_again(self):
        todo, refused = staged.reexport_targets(VIEW, ["L1.Math", "L1.App", "L2.Gpio"])
        assert todo == ["L1.Math"] and refused == ["L1.App", "L2.Gpio"]

    def test_the_default_is_every_component_with_documents_in_the_model(self):
        assert staged.default_reexport(VIEW) == ["L1.Math"]


class TestResumePlan:
    RUN = {"command": "generate", "argv": ["generate", "--project-id", "P", "--version-id",
                                           "v1", "--detach"]}

    def plan(self, view, status, alive=False, run=None):
        return staged.resume_plan(alive=alive, pipeline_status=status, view=view,
                                  run=self.RUN if run is None else run)

    def test_a_live_writer_is_not_cut_short(self):
        assert self.plan(VIEW, "viewing", alive=True)["action"] == "busy"

    def test_no_model_and_still_parsing_repeats_the_generate_without_detach(self):
        p = self.plan([comp("L1.Math", "waiting", in_model=False)], "parsing")
        assert p == {"action": "regenerate",
                     "argv": ["generate", "--project-id", "P", "--version-id", "v1"]}

    def test_a_run_that_was_not_a_generate_has_nothing_to_repeat(self):
        p = self.plan([], None, run={"command": "export", "argv": ["export"]})
        assert p == {"action": "regenerate", "argv": []}

    def test_no_model_but_the_parse_finished_derives_and_makes_the_requested(self):
        p = self.plan([comp("L1.Math", "stopped", in_model=False)], "deriving")
        assert p == {"action": "derive", "components": ["L1.Math"]}

    def test_a_complete_model_makes_only_the_unfinished_components(self):
        p = self.plan(VIEW, "exporting")
        assert p == {"action": "export", "components": ["L1.Util", "L2.Gpio", "L2.Uart"]}

    def test_all_made_but_never_closed_only_closes(self):
        view = [comp("L1.Math", "generated"), comp("L1.App", "not_requested")]
        assert self.plan(view, "exporting")["action"] == "close"

    def test_a_failed_phase_2_with_its_parse_stored_derives_not_reparses(self):
        p = self.plan([comp("L1.Math", "failed", in_model=False)], "failed")
        assert p["action"] == "regenerate"                     # no stored parse: from scratch
        p = staged.resume_plan(alive=False, pipeline_status="failed", run=self.RUN,
                               view=[comp("L1.Math", "failed", in_model=False)], parse_stored=True)
        assert p == {"action": "derive", "components": ["L1.Math"]}

    def test_a_model_only_run_resumes_as_model_only(self):
        run = {"command": "generate", "argv": ["generate", "--model-only", "--project-id", "P"]}
        p = staged.resume_plan(alive=False, pipeline_status="deriving", view=[], run=run)
        assert p == {"action": "derive", "components": [], "to_phase": 2}

    def test_model_only_comes_from_the_manifest_after_a_cut_short_resume(self):
        """A resume of a model-only run that was itself cut short: the run row holds the resume
        now, not the generate's command line -- the manifest still says model-only."""
        run = {"command": "resume", "argv": ["resume", "--project-id", "P"]}
        p = staged.resume_plan(alive=False, pipeline_status="deriving", view=[], run=run,
                               parse_stored=True, model_only=True)
        assert p == {"action": "derive", "components": [], "to_phase": 2}

    def test_a_complete_version_has_nothing_to_resume(self):
        view = [comp("L1.Math", "generated"), comp("L1.App", "not_requested")]
        assert self.plan(view, "complete")["action"] == "nothing"


class TestDocumentsCountAsGenerated:
    """A re-export that died leaves its components stopped or failed although their documents
    are there: they are still re-exportable, and not something `export` makes again."""
    VIEW = [comp("L1.Math", "stopped", docs=[("SWE.3", "in_review")]), comp("L1.App", "stopped")]

    def test_reexport_takes_them(self):
        assert staged.default_reexport(self.VIEW) == ["L1.Math"]
        assert staged.reexport_targets(self.VIEW, ["L1.Math", "L1.App"]) == (["L1.Math"], ["L1.App"])

    def test_export_leaves_them(self):
        assert staged.export_targets(self.VIEW, [], remaining=True) == (["L1.App"], [])
        assert staged.export_targets(self.VIEW, ["L1.Math"], remaining=False) == ([], ["L1.Math"])


class TestProgress:
    def test_the_stage_eta_follows_its_pace_so_far(self):
        start = datetime.datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
        run = {"done": 250, "total": 1000, "stage_started_at": start,
               "progress_at": start + datetime.timedelta(hours=1)}
        assert staged.stage_eta(run) == (25, 3 * 3600.0)

    def test_no_eta_before_anything_is_done(self):
        assert staged.stage_eta({"done": 0, "total": 10, "stage_started_at": None}) == (0, None)

    def test_durations_read_as_days_hours_minutes(self):
        assert staged.duration(3 * 86400 + 4 * 3600) == "3 d 4 h"
        assert staged.duration(2 * 3600 + 5 * 60) == "2 h 5 min"
        assert staged.duration(20) == "under a minute"

    def _lines(self, alive, outcome="running"):
        version = type("V", (), {"id": "P.v1", "tag": "v1", "commit_sha": "abcdef1234567"})()
        run = {"command": "generate", "pid": 42, "host": "box", "outcome": outcome,
               "started_at": datetime.datetime(2026, 10, 2, tzinfo=UTC),
               "log_path": "/runs/P.v1/run.log", "code_dir": "/runs/P.v1/code",
               "stage": "LLM-description-pass1", "done": 10, "total": 40,
               "stage_started_at": datetime.datetime(2026, 10, 2, tzinfo=UTC),
               "progress_at": datetime.datetime(2026, 10, 2, 1, tzinfo=UTC)}
        return "\n".join(staged.progress_lines(
            version=version, pipeline_status="deriving", run=run, alive=alive, view=VIEW,
            project_id="P", now=datetime.datetime(2026, 10, 2, 2, tzinfo=UTC)))

    def test_a_dead_run_says_stopped_and_how_to_resume(self):
        text = self._lines(alive=False)
        assert "STOPPED" in text and "analyzer.py resume --project-id P --version-id P.v1" in text

    def test_a_dead_run_says_where_it_stopped_not_a_time_left(self):
        """Its record still says running (a killed process closes nothing): no "now" line with a
        time left for a stage nobody is working on."""
        text = self._lines(alive=False)
        assert "now " not in text and " left" not in text
        assert "stopped   during LLM-description-pass1: 10/40, last update 1 h 0 min ago" in text

    def test_a_live_run_says_running_with_the_stage_and_time_left(self):
        text = self._lines(alive=True)
        assert "RUNNING" in text and "LLM-description-pass1: 10/40 (25%)" in text
        assert "about 3 h 0 min left" in text

    def test_a_finished_run_shows_no_current_stage(self):
        text = self._lines(alive=False, outcome="complete")
        assert "now " not in text and "state     complete" in text

    def test_the_last_minute_reads_plainly(self):
        version = type("V", (), {"id": "P.v1", "tag": "v1", "commit_sha": "abc"})()
        start = datetime.datetime(2026, 10, 2, tzinfo=UTC)
        run = {"command": "export", "outcome": "running", "stage": "flowcharts", "done": 99,
               "total": 100, "stage_started_at": start,
               "progress_at": start + datetime.timedelta(seconds=99)}
        text = "\n".join(staged.progress_lines(version=version, pipeline_status="viewing", run=run,
                                               alive=True, view=[], project_id="P", now=start))
        assert "under a minute left in this stage" in text and "about under" not in text

    def test_cut_short_components_keep_their_resume_hint_after_a_later_run(self):
        version = type("V", (), {"id": "P.v1", "tag": "v1", "commit_sha": "abc"})()
        run = {"command": "export", "outcome": "complete", "pid": 1, "host": "box"}
        text = "\n".join(staged.progress_lines(version=version, pipeline_status="exporting",
                                               run=run, alive=False, view=VIEW, project_id="P"))
        assert "cut short or failed" in text and "analyzer.py resume --project-id P" in text

    def test_the_component_table_offers_export_for_the_rest(self):
        text = "\n".join(staged.component_lines(VIEW, project_id="P", version_id="v1"))
        assert "SWE.3 Approved · SWE.4 In review" in text
        assert "analyzer.py export --project-id P --version-id v1 --remaining" in text
        assert "(not in this version's model)" in text


class TestResolve:
    def test_a_bare_name_one_layer_has(self):
        assert resolve(VIEW, ["Math"]) == (["L1.Math"], [])

    def test_a_qualified_id(self):
        assert resolve(VIEW, ["L2.Gpio"]) == (["L2.Gpio"], [])

    def test_a_name_two_layers_share_is_a_problem(self):
        view = VIEW + [comp("L2.Math", "not_requested")]
        found, problems = resolve(view, ["Math"])
        assert found == [] and "more than one layer" in problems[0]

    def test_a_name_no_parsed_layer_has_is_a_problem(self):
        assert "not a component of the layers" in resolve(VIEW, ["Nope"])[1][0]


class TestFrozenRun:
    def test_the_background_command_is_the_same_without_detach(self):
        assert frozen_run.strip_detach(["generate", "--detach", "--project-id", "P"]) == \
            ["generate", "--project-id", "P"]

    def test_runs_live_under_the_data_root_per_version_and_time(self, tmp_path):
        d = frozen_run.run_dir(str(tmp_path), "P.v1/x", datetime.datetime(2026, 10, 2, 9, 30))
        assert d == os.path.join(str(tmp_path), "runs", "P.v1_x", "20261002-093000")

    def test_the_child_works_on_this_installation_s_data(self, tmp_path):
        env = frozen_run.child_env(data_root=str(tmp_path), workspaces_dir=str(tmp_path / "ws"),
                                   log_path=str(tmp_path / "run.log"),
                                   code_dir=str(tmp_path / "code"), base={"KEEP": "1"})
        assert env["ANALYZER_DATA_ROOT"] == str(tmp_path)
        assert env["ANALYZER_WORKSPACES_DIR"] == str(tmp_path / "ws")
        assert env["KEEP"] == "1" and env["PYTHONUNBUFFERED"] == "1"

    def test_the_child_uses_the_database_this_process_resolved(self, tmp_path):
        env = frozen_run.child_env(data_root=str(tmp_path), workspaces_dir=str(tmp_path),
                                   log_path="l", code_dir="c", base={},
                                   database_url="sqlite:///C:/data/analyzer-dev.db")
        assert env["DATABASE_URL"] == "sqlite:///C:/data/analyzer-dev.db"

    def test_freeze_copies_the_code_and_leaves_caches_behind(self, tmp_path):
        src = tmp_path / "src"
        (src / "engine" / "core" / "__pycache__").mkdir(parents=True)
        (src / "engine" / "core" / "x.py").write_text("X = 1", encoding="utf-8")
        (src / "engine" / "core" / "__pycache__" / "x.cpython.pyc").write_bytes(b"0")
        (src / "engine" / "logs").mkdir()
        (src / "engine" / "logs" / "big.log").write_text("..", encoding="utf-8")
        (src / "analyzer.py").write_text("print('hi')", encoding="utf-8")
        (src / "workspaces").mkdir()
        code = frozen_run.freeze(str(src), str(tmp_path / "run"))
        assert os.path.isfile(os.path.join(code, "analyzer.py"))
        assert os.path.isfile(os.path.join(code, "engine", "core", "x.py"))
        assert not os.path.exists(os.path.join(code, "engine", "core", "__pycache__"))
        assert not os.path.exists(os.path.join(code, "engine", "logs"))
        assert not os.path.exists(os.path.join(code, "workspaces")), "data is never copied"

    def test_a_database_file_in_the_code_is_not_copied(self, tmp_path):
        src = tmp_path / "src"
        (src / "engine" / "config").mkdir(parents=True)
        (src / "engine" / "config" / "analyzer-dev.db").write_bytes(b"sqlite")
        (src / "engine" / "config" / "config.local.json").write_text("{}", encoding="utf-8")
        code = frozen_run.freeze(str(src), str(tmp_path / "run"))
        assert os.path.isfile(os.path.join(code, "engine", "config", "config.local.json"))
        assert not os.path.exists(os.path.join(code, "engine", "config", "analyzer-dev.db"))


class TestFollowingABackgroundRun:
    """What a web job needs to follow a run nobody waits for (staged generation, C4): its exit
    code, its run folder after an API restart, whether its process lives, stopping it."""

    def test_the_child_is_told_where_to_write_its_exit_code(self, tmp_path):
        env = frozen_run.child_env(data_root=str(tmp_path), workspaces_dir=str(tmp_path),
                                   log_path="l", code_dir="c", base={},
                                   exit_path=str(tmp_path / "exit.json"))
        assert env[frozen_run.EXIT_ENV] == str(tmp_path / "exit.json")

    def test_an_exit_code_is_read_back(self, tmp_path):
        assert frozen_run.read_exit(str(tmp_path)) is None           # still running, or died
        frozen_run.record_exit(3, str(tmp_path / frozen_run.EXIT_FILE))
        assert frozen_run.read_exit(str(tmp_path)) == 3

    @pytest.mark.parametrize("argv,code", [(["--help"], 0), (["no-such-command"], 2)])
    def test_analyzer_records_how_it_exited(self, tmp_path, argv, code):
        """`analyzer.py` writes it as it exits -- and takes the variable out of the environment,
        so the phases it starts do not write it too."""
        import subprocess
        exit_file = tmp_path / "exit.json"
        env = {**os.environ, frozen_run.EXIT_ENV: str(exit_file)}
        rc = subprocess.run([sys.executable, os.path.join(ROOT, "analyzer.py"), *argv], env=env,
                            capture_output=True).returncode
        assert rc == code
        assert frozen_run.read_exit(str(tmp_path)) == code

    def test_the_run_a_job_started_is_found_by_the_job(self, tmp_path):
        import json
        base = tmp_path / "runs" / "verabc"
        for stamp, job in (("20261002-090000", "jobA"), ("20261002-100000", None),
                           ("20261002-110000", "jobA"), ("20261002-120000", "jobB")):
            (base / stamp).mkdir(parents=True)
            (base / stamp / "run.json").write_text(json.dumps({"pid": 1, "job_id": job}),
                                                   encoding="utf-8")
        found = frozen_run.find_job_run(str(tmp_path), "verabc", "jobA")
        assert found["run_dir"] == str(base / "20261002-110000")      # its newest
        assert frozen_run.find_job_run(str(tmp_path), "verabc", "jobC") is None
        assert frozen_run.find_job_run(str(tmp_path), "nosuch", "jobA") is None

    def test_a_live_analyzer_process_is_alive_until_stopped(self, tmp_path):
        """By its command line: a process id the system gave to another program since is not
        the run. `stop` ends the run and what it started."""
        pytest.importorskip("psutil")
        import subprocess
        script = tmp_path / "fake_analyzer.py"
        script.write_text("import subprocess, sys, time\n"
                          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                          "time.sleep(60)\n", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(script)])
        try:
            assert frozen_run.process_alive(proc.pid) is True
            assert frozen_run.process_alive(os.getpid()) is False      # not an analyzer
            frozen_run.stop(proc.pid)
            proc.wait(timeout=30)
            assert frozen_run.process_alive(proc.pid) is False
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_no_process_is_not_alive(self):
        assert frozen_run.process_alive(None) is False


class TestRecordedCommandLine:
    def test_path_flags_are_made_absolute_names_and_urls_are_not(self, tmp_path, monkeypatch):
        import analyzer
        (tmp_path / "my.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        out = analyzer._absolute_paths(["generate", "--config", "my.json", "--source",
                                        "https://git/x.git", "--version-id", "v1"])
        assert out[2] == str(tmp_path / "my.json")
        assert out[4] == "https://git/x.git" and out[6] == "v1"
