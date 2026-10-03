"""Staged generation on the SQL backend: component states, the run record, the component view
(engine/core/version_run.py, api/services/version_components.py) and the runner's refusal of a
re-export while another process writes the version. SQLite: the writer LOCK is Postgres-only and
is checked by tests/unit/test_version_lock_pg.py."""
import datetime
import uuid

import pytest
import sqlalchemy as sa

from api.db.postgres import schema as s


@pytest.fixture
def sql_db(db):
    if not hasattr(db, "_engine"):
        pytest.skip("rows of the SQL backend")
    return db


@pytest.fixture
def version(sql_db):
    """A fresh version of p1 whose model has three components."""
    vid = "versg" + uuid.uuid4().hex[:6]
    with sql_db._engine.begin() as cx:
        cx.execute(sa.insert(s.versions).values(
            id=vid, project_id="p1", version=vid, commit_sha="c" * 40, status="in_review",
            pipeline_status="viewing", created_at=datetime.datetime.now(datetime.timezone.utc)))
        cx.execute(sa.insert(s.model_components), [
            {"version_id": vid, "name": n} for n in ("Layer1.Math", "Layer1.App", "Layer2.Gpio")])
    return sql_db.versions.get(vid)


def _rows(db, vid):
    from core.version_run import component_rows
    return component_rows(vid)


class TestComponentStates:
    def test_waiting_generating_generated(self, sql_db, version):
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.Math"], "waiting")
        first = _rows(sql_db, version.id)["Layer1.Math"]
        assert first["state"] == "waiting" and first["requested_at"] is not None
        mark_components(version.id, ["Layer1.Math"], "waiting")     # the engine's second call
        assert _rows(sql_db, version.id)["Layer1.Math"]["requested_at"] == first["requested_at"]
        mark_components(version.id, ["Layer1.Math"], "generating")
        assert _rows(sql_db, version.id)["Layer1.Math"]["started_at"] is not None
        mark_components(version.id, ["Layer1.Math"], "generated")
        row = _rows(sql_db, version.id)["Layer1.Math"]
        assert row["state"] == "generated" and row["finished_at"] is not None and not row["error"]

    def test_failed_keeps_why(self, sql_db, version):
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.App"], "failed", error="Components: App: exit 1")
        assert _rows(sql_db, version.id)["Layer1.App"]["error"] == "Components: App: exit 1"

    def test_an_unknown_state_writes_nothing(self, sql_db, version):
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.App"], "done")
        assert _rows(sql_db, version.id) == {}


class TestRunRecord:
    def test_a_run_is_recorded_and_closed(self, sql_db, version):
        from core.version_run import run_row, writing
        with writing(version.id, command="export", argv=["export", "--remaining"]) as run:
            row = run_row(version.id)
            assert row["outcome"] == "running" and row["command"] == "export"
            assert row["argv"] == ["export", "--remaining"] and row["pid"]
            run.ok(0)
        row = run_row(version.id)
        assert row["outcome"] == "complete" and row["finished_at"] is not None

    def test_a_failure_is_recorded_as_failed(self, sql_db, version):
        from core.version_run import run_row, writing
        with pytest.raises(RuntimeError):
            with writing(version.id, command="generate"):
                raise RuntimeError("phase 3 died")
        assert run_row(version.id)["outcome"] == "failed"

    def test_a_nonzero_exit_is_failed(self, sql_db, version):
        from core.version_run import run_row, writing
        with writing(version.id, command="reexport") as run:
            run.ok(2)
        assert run_row(version.id)["outcome"] == "failed"

    def test_progress_lands_on_the_run_row(self, sql_db, version, monkeypatch):
        import core.version_run as vr
        from core.run_context import set_run_context
        monkeypatch.setattr(vr, "_last_publish", 0.0)
        set_run_context(version=version.id, scratch=False)
        try:
            vr.progress("LLM-description-pass1", 7, 40, 1_700_000_000.0, force=True)
        finally:
            set_run_context(version="", scratch=False)
        row = vr.run_row(version.id)
        assert (row["stage"], row["done"], row["total"]) == ("LLM-description-pass1", 7, 40)
        assert row["progress_at"] is not None and row["stage_started_at"] is not None

    def test_sqlite_cannot_tell_who_is_alive(self, sql_db, version):
        from core.version_run import alive, holder
        assert alive(version.id) is None and holder(version.id) is None


class TestComponentView:
    def _doc(self, db, version, comp, process="SWE.3", status="in_review"):
        from api.models.domain import Document
        now = datetime.datetime.now(datetime.timezone.utc)
        db.documents.update(Document(
            id="doc" + uuid.uuid4().hex[:8], project_id="p1", version_id=version.id,
            process=process, name=comp.split(".")[-1], subtitle="", layer=comp.split(".")[0],
            group=comp, status=status, due_date=None, created_at=now, updated_at=now))

    def test_every_component_of_the_model_with_its_state(self, sql_db, version):
        from api.services.version_components import components_view, counts
        from core.version_run import mark_components
        self._doc(sql_db, version, "Layer1.Math", status="approved")       # older run: no row
        mark_components(version.id, ["Layer2.Gpio"], "generating")
        view = components_view(sql_db, version, alive=True)
        states = {c["component"]: c["state"] for c in view}
        assert states == {"Layer1.App": "not_requested", "Layer1.Math": "generated",
                          "Layer2.Gpio": "generating"}
        assert [c["component"] for c in view] == ["Layer1.App", "Layer1.Math", "Layer2.Gpio"]
        math = next(c for c in view if c["component"] == "Layer1.Math")
        assert math["documents"][0]["status"] == "approved" and math["layer"] == "Layer1"
        assert counts(view) == {"generating": 1, "generated": 1, "not_requested": 1}

    def test_a_dead_run_s_components_are_stopped(self, sql_db, version):
        from api.services.version_components import components_view
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.App"], "waiting")
        mark_components(version.id, ["Layer2.Gpio"], "generating")
        view = components_view(sql_db, version, alive=False)
        states = {c["component"]: c["state"] for c in view}
        assert states["Layer1.App"] == "stopped" and states["Layer2.Gpio"] == "stopped"

    def test_generated_components_count_documents_and_rows(self, sql_db, version):
        from core.version_run import generated_components, mark_components
        self._doc(sql_db, version, "Layer1.Math")
        mark_components(version.id, ["Layer2.Gpio"], "generated")
        mark_components(version.id, ["Layer1.App"], "failed")
        assert generated_components(version.id) == ["Layer1.Math", "Layer2.Gpio"]


class TestReexportWhileWritten:
    def test_a_web_reexport_is_refused_while_another_process_writes(self, sql_db, monkeypatch):
        from api.services import pipeline_runner as pr
        monkeypatch.setattr(pr, "version_writer_busy",
                            lambda db, vid: "analyzer export pid 9 on box (since 2026-10-02 09:00)")
        with pytest.raises(pr.ReexportRefused) as exc:
            pr.start_reexport(sql_db, sql_db.versions.get("ver4"))
        assert exc.value.code == "VERSION_BUSY" and exc.value.status == 409
        assert "analyzer export pid 9" in str(exc.value)

    def test_the_api_records_its_jobs_on_its_own_database(self, sql_db, version):
        from api.services import pipeline_runner as pr
        from core.version_run import run_row
        with pr._version_writer(sql_db, version.id, "web run"):
            assert run_row(version.id, engine=sql_db._engine)["command"] == "web run"
        assert run_row(version.id, engine=sql_db._engine)["outcome"] == "complete"

    def test_the_in_memory_database_records_nothing(self):
        import contextlib
        from api.db.in_memory import InMemoryDatabase
        from api.services import pipeline_runner as pr
        assert isinstance(pr._version_writer(InMemoryDatabase(), "ver3", "web run"),
                          contextlib.nullcontext)


def _hdr(client, name):
    r = client.post("/api/v1/auth/signin", json={"email": f"{name}@aspice.dev", "password": "secret"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestRoutes:
    """GET .../components and POST .../documents/generate (api/routes/version_components.py)."""

    def _url(self, version, tail="components"):
        return f"/api/v1/projects/p1/versions/{version.id}/{tail}"

    def test_the_components_of_a_version_with_their_state(self, client, sql_db, version):
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.Math"], "generated")
        r = client.get(self._url(version), headers=_hdr(client, "bob"))
        assert r.status_code == 200, r.text
        body = r.json()
        states = {c["component"]: c["state"] for c in body["components"]}
        assert states == {"Layer1.App": "not_requested", "Layer1.Math": "generated",
                          "Layer2.Gpio": "not_requested"}
        assert body["counts"] == {"generated": 1, "not_requested": 2} and body["run"] is None

    def test_the_job_at_work_on_the_version_is_named(self, client, sql_db, version):
        """What the panel's Stop cancels: a Components -> Generate job is never the project's
        current run, so the Overview's Cancel does not reach it."""
        job = _bg_job(sql_db, version, mode="export", status="running")
        r = client.get(self._url(version), headers=_hdr(client, "bob"))
        assert r.status_code == 200, r.text
        assert r.json()["job"] == {"id": job.id, "mode": "export", "status": "running"}

    def test_no_job_when_none_is_at_work(self, client, sql_db, version):
        _bg_job(sql_db, version, mode="export", status="complete")
        r = client.get(self._url(version), headers=_hdr(client, "bob"))
        assert r.json()["job"] is None

    def test_another_project_s_version_is_not_found(self, client, sql_db, version):
        r = client.get(f"/api/v1/projects/p2/versions/{version.id}/components",
                       headers=_hdr(client, "alice"))
        assert r.status_code == 404

    def test_generate_starts_an_export_job_for_what_is_missing(self, client, sql_db, version,
                                                                monkeypatch):
        from api.services import pipeline_runner as pr
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.Math"], "generated")
        started = {}

        def fake_start(db, v, comps):
            started.update(version=v.id, components=comps)
            return type("J", (), {"id": "jobexport1", "status": "queued"})()

        monkeypatch.setattr(pr, "start_export", fake_start)
        r = client.post(self._url(version, "documents/generate"), headers=_hdr(client, "alice"),
                        json={"components": ["Math", "App", "Layer2.Gpio"]})
        assert r.status_code == 202, r.text
        assert r.json()["components"] == ["Layer1.App", "Layer2.Gpio"]
        assert r.json()["skipped"] == ["Layer1.Math"] and r.json()["job_id"] == "jobexport1"
        assert started == {"version": version.id, "components": ["Layer1.App", "Layer2.Gpio"]}

    def test_a_component_outside_the_model_is_422(self, client, sql_db, version):
        r = client.post(self._url(version, "documents/generate"), headers=_hdr(client, "alice"),
                        json={"components": ["Nope"]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_COMPONENTS"

    def test_nothing_left_to_make_is_409(self, client, sql_db, version):
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.App"], "generated")
        r = client.post(self._url(version, "documents/generate"), headers=_hdr(client, "alice"),
                        json={"components": ["Layer1.App"]})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NOTHING_TO_GENERATE"

    def test_a_version_without_a_model_is_409(self, client, sql_db):
        r = client.post("/api/v1/projects/p1/versions/ver3/documents/generate",
                        headers=_hdr(client, "alice"), json={"components": ["Math"]})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_MODEL"

    def test_a_busy_version_is_refused_with_the_runner_s_answer(self, client, sql_db, version,
                                                                monkeypatch):
        from api.services import pipeline_runner as pr

        def busy(db, v, comps):
            raise pr.ReexportRefused(409, "VERSION_BUSY", "being written by analyzer generate")

        monkeypatch.setattr(pr, "start_export", busy)
        r = client.post(self._url(version, "documents/generate"), headers=_hdr(client, "alice"),
                        json={"components": ["App"]})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_BUSY"

    def test_only_an_admin_generates(self, client, sql_db, version):
        r = client.post(self._url(version, "documents/generate"), headers=_hdr(client, "bob"),
                        json={"components": ["App"]})
        assert r.status_code == 403


class TestCliMadeVersionsInTheWebApp:
    def test_a_version_the_cli_made_answers_strings_not_nulls(self, client, sql_db, version):
        """`--create-version` leaves branch, description and author empty; the web app refused the
        WHOLE version list on one null (so no version of the project showed)."""
        r = client.get("/api/v1/projects/p1/versions", headers=_hdr(client, "alice"))
        assert r.status_code == 200, r.text
        mine = next(v for v in r.json()["versions"] if v["id"] == version.id)
        assert (mine["branch"], mine["description"], mine["created_by"]) == ("", "", "")


class TestWebRunLocking:
    def test_a_web_run_leaves_the_lock_to_the_generate_it_starts(self, sql_db, monkeypatch):
        """The web job runs `analyzer.py generate`, which takes the version's writer lock in its
        own process. Holding it in the API as well refused that process: every web run failed."""
        from api.services import pipeline_runner as pr
        calls = []
        monkeypatch.setattr(pr, "_version_writer", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(pr, "_inner_run_locked", lambda db, job_id, project: None)
        pr._inner_run(sql_db, "job2")
        assert calls == []

    def test_a_web_reexport_holds_it_itself(self, sql_db, version, monkeypatch):
        """A re-export runs the engine directly, so the API process is the writer."""
        import contextlib
        import dataclasses
        from api.services import pipeline_runner as pr
        calls = []

        def writer(db, vid, command):
            calls.append((vid, command))
            return contextlib.nullcontext()

        monkeypatch.setattr(pr, "_version_writer", writer)
        monkeypatch.setattr(pr, "_do_reexport", lambda db, job_id: False)
        # A job of this test's own: the seeded ones are shared by the whole session.
        job = dataclasses.replace(sql_db.jobs.get("job2"), id="jobrx" + uuid.uuid4().hex[:6],
                                  project_id="p1", version_id=version.id, mode="reexport",
                                  status="queued")
        sql_db.jobs.create(job)
        pr._run_reexport(sql_db, job.id)
        assert calls == [(version.id, "web reexport")]


class TestWebReexportScope:
    def test_a_web_reexport_makes_every_document_the_version_has(self, sql_db, version,
                                                               monkeypatch):
        """Including the components `export` added after the generation: re-exporting only the
        generation's scope left their Word files without the corrections."""
        import dataclasses
        from api.services import pipeline_runner as pr
        from core.version_run import mark_components
        monkeypatch.setattr(pr, "_run_reexport", lambda db, job_id: None)    # no engine here
        gen = dataclasses.replace(sql_db.jobs.get("job2"), id="jobgen" + uuid.uuid4().hex[:6],
                                  project_id="p1", version_id=version.id, mode="auto",
                                  status="complete",
                                  scope={"type": "component", "names": ["Layer1.Math"]})
        sql_db.jobs.create(gen)
        mark_components(version.id, ["Layer1.Math", "Layer2.Gpio"], "generated")   # Gpio: exported
        job = pr.start_reexport(sql_db, version)
        assert job.scope == {"type": "component", "names": ["Layer1.Math", "Layer2.Gpio"]}


class TestPartialRuns:
    """Exit 3: some components failed, the run went on with the others. A web job treats it as a
    success with failures in it -- a failed job would delete its draft version and everything the
    run made."""

    def _job(self, sql_db, version):
        import dataclasses
        job = dataclasses.replace(sql_db.jobs.get("job2"), id="jobpt" + uuid.uuid4().hex[:6],
                                  project_id="p1", version_id=version.id, status="running")
        sql_db.jobs.create(job)
        return job

    def test_exit_3_is_a_partial_success(self, sql_db, version):
        import sys
        from api.services import pipeline_runner as pr
        job = self._job(sql_db, version)
        pr._init_state(job.id)
        assert pr._execute_subprocess(sql_db, job.id, [sys.executable, "-c", "raise SystemExit(3)"])
        assert sql_db.jobs.get(job.id).status == "running"          # not failed

    def test_any_other_exit_still_fails_the_job(self, sql_db, version):
        import sys
        from api.services import pipeline_runner as pr
        job = self._job(sql_db, version)
        pr._init_state(job.id)
        assert not pr._execute_subprocess(sql_db, job.id, [sys.executable, "-c", "raise SystemExit(1)"])
        assert sql_db.jobs.get(job.id).status == "failed"


# ---------------------------------------------------------------------------
# Web runs in the background (C4): followed through their log, process and exit code; followed
# again after an API restart; a stop keeps the version for `resume`.
# ---------------------------------------------------------------------------

_FAKE_RUN = """import json, sys, time
log, exit_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]
with open(log, "a", encoding="utf-8") as fh:
    for line in sys.argv[4:]:
        fh.write(line + "\\n")
        fh.flush()
if mode == "hang":
    time.sleep(120)
elif mode != "die":
    time.sleep(0.3)
    with open(exit_path, "w") as fh:
        json.dump({"exit_code": int(mode)}, fh)
"""


@pytest.fixture
def fast_follow(monkeypatch):
    from api.services import pipeline_runner as pr
    monkeypatch.setattr(pr, "DETACHED_POLL_SECONDS", 0.1)
    monkeypatch.setattr(pr, "_CANCEL_CHECK_SECONDS", 0.1)
    return pr


def _fake_run(run_dir, mode, *lines):
    """A stand-in for `analyzer.py ... --detach`'s background process (its name holds
    "analyzer.py", as `process_alive` asks): writes `lines` to its log, then its exit code
    (`mode`), or dies without one ("die"), or runs until stopped ("hang")."""
    import subprocess
    import sys
    run_dir.mkdir(parents=True, exist_ok=True)
    script = run_dir / "fake_analyzer.py"
    script.write_text(_FAKE_RUN, encoding="utf-8")
    log = run_dir / "run.log"
    log.touch()
    proc = subprocess.Popen([sys.executable, str(script), str(log),
                             str(run_dir / "exit.json"), mode, *lines])
    return proc, {"pid": proc.pid, "log_path": str(log), "run_dir": str(run_dir)}


def _bg_job(sql_db, version, **over):
    import dataclasses
    from api.models.domain import AnalysisPhase
    fields = dict(id="jobbg" + uuid.uuid4().hex[:6], project_id="p1", version_id=version.id,
                  status="running", mode="auto", phase=1,
                  phases=[AnalysisPhase(n, f"p{n}", "pending", None) for n in (1, 2, 3, 4)])
    fields.update(over)
    job = dataclasses.replace(sql_db.jobs.get("job2"), **fields)
    sql_db.jobs.create(job)
    return job


@pytest.fixture
def draft(sql_db):
    """A version a run has just reserved: nothing stored in it yet."""
    vid = "verdr" + uuid.uuid4().hex[:6]
    with sql_db._engine.begin() as cx:
        cx.execute(sa.insert(s.versions).values(
            id=vid, project_id="p1", version=vid, commit_sha="c" * 40, status="draft",
            created_at=datetime.datetime.now(datetime.timezone.utc)))
    return sql_db.versions.get(vid)


class TestFollowingABackgroundRun:
    def test_a_run_that_ends_well_is_a_success_with_its_output_followed(self, sql_db, version,
                                                                         tmp_path, fast_follow):
        pr = fast_follow
        job = _bg_job(sql_db, version)
        pr._init_state(job.id)
        proc, run = _fake_run(tmp_path, "0",
                              "[10:00:00] INFO orchestration: === Phase 3: Run views ===",
                              "rendering flowcharts for Layer1.Math")
        assert pr._follow_detached(sql_db, job.id, run, phase_start=1)
        proc.wait(timeout=30)
        lines, _ = pr.get_log_lines(job.id, 0)
        assert "rendering flowcharts for Layer1.Math" in lines
        got = sql_db.jobs.get(job.id)
        assert got.phase == 3 and got.status == "running"           # `_complete` is the caller's

    def test_exit_3_is_a_partial_success(self, sql_db, version, tmp_path, fast_follow):
        pr = fast_follow
        job = _bg_job(sql_db, version)
        pr._init_state(job.id)
        _, run = _fake_run(tmp_path, "3", "Components: Layer1.App failed")
        assert pr._follow_detached(sql_db, job.id, run, phase_start=1)
        assert any("others were made" in line for line in pr.get_log_lines(job.id, 0)[0])

    def test_a_run_that_died_fails_the_job_and_keeps_its_work(self, sql_db, version, tmp_path,
                                                              fast_follow):
        """Its process gone with no exit code: the machine restarted, someone killed it. The
        version holds work (`pipeline_status` past the parse), so it stays, for `resume`."""
        pr = fast_follow
        job = _bg_job(sql_db, version)
        pr._init_state(job.id)
        _, run = _fake_run(tmp_path, "die", "Phase 2: describing 41200 / 96000")
        assert not pr._follow_detached(sql_db, job.id, run, phase_start=1)
        got = sql_db.jobs.get(job.id)
        assert got.status == "failed" and got.error_message.startswith("Stopped:")
        assert "analyzer.py resume" in got.error_message
        assert sql_db.versions.get(version.id) is not None

    def test_a_run_that_died_before_storing_anything_frees_its_draft(self, sql_db, draft,
                                                                     tmp_path, fast_follow):
        pr = fast_follow
        job = _bg_job(sql_db, draft)
        pr._init_state(job.id)
        _, run = _fake_run(tmp_path, "die")
        assert not pr._follow_detached(sql_db, job.id, run, phase_start=1)
        assert sql_db.jobs.get(job.id).status == "failed"
        assert sql_db.versions.get(draft.id) is None                 # as a failed run always did

    def test_a_failed_run_says_why_and_keeps_its_work(self, sql_db, version, tmp_path,
                                                      fast_follow):
        pr = fast_follow
        job = _bg_job(sql_db, version)
        pr._init_state(job.id)
        _, run = _fake_run(tmp_path, "1", "RuntimeError: the database went away")
        assert not pr._follow_detached(sql_db, job.id, run, phase_start=1)
        got = sql_db.jobs.get(job.id)
        assert got.status == "failed" and "code 1" in got.error_message
        assert "the database went away" in got.error_message
        assert sql_db.versions.get(version.id) is not None

    def test_a_cancel_stops_the_run(self, sql_db, version, tmp_path, fast_follow):
        import threading
        import time
        pr = fast_follow
        job = _bg_job(sql_db, version)
        pr._init_state(job.id)
        proc, run = _fake_run(tmp_path, "hang", "working")

        def cancel():
            time.sleep(0.5)
            j = sql_db.jobs.get(job.id)
            j.status = "cancelled"
            sql_db.jobs.update(j)
        threading.Thread(target=cancel, daemon=True).start()
        try:
            assert not pr._follow_detached(sql_db, job.id, run, phase_start=1)
            assert proc.wait(timeout=30) is not None                  # stopped, not left running
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_the_launcher_s_answer_is_read(self, tmp_path):
        import os
        import sys
        from api.services import pipeline_runner as pr
        log = tmp_path / "runs" / "v" / "t" / "run.log"
        launcher = tmp_path / "launcher.py"
        launcher.write_text(
            "print('started in the background: pid 4242')\n"
            "print('  code      C:/x/code (frozen: later changes here do not reach this run)')\n"
            f"print('  log       ' + {str(log)!r})\n", encoding="utf-8")
        run = pr._launch_detached([sys.executable, str(launcher)], dict(os.environ))
        assert run["pid"] == 4242
        assert run["run_dir"] == str(log.parent)

    def test_a_launch_that_is_refused_says_why(self, tmp_path):
        import os
        import sys
        from api.services import pipeline_runner as pr
        launcher = tmp_path / "launcher.py"
        launcher.write_text("import sys\nprint('version v1 is being written by analyzer "
                            "generate pid 7 -- not started.', file=sys.stderr)\nsys.exit(2)\n",
                            encoding="utf-8")
        with pytest.raises(pr._LaunchFailed, match="being written"):
            pr._launch_detached([sys.executable, str(launcher)], dict(os.environ))

    def test_only_a_database_backed_api_runs_in_the_background(self, sql_db, monkeypatch):
        from api.db.in_memory import InMemoryDatabase
        from api.services import pipeline_runner as pr
        from api.services.settings import get_settings
        assert pr._detach_enabled(sql_db)
        assert not pr._detach_enabled(InMemoryDatabase())
        monkeypatch.setattr(get_settings(), "job_detach", False)
        assert not pr._detach_enabled(sql_db)


class TestAfterAnApiRestart:
    def test_a_job_whose_run_goes_on_is_followed_again_not_failed(self, sql_db, version, tmp_path,
                                                                   fast_follow, monkeypatch):
        """`fail_interrupted_jobs` failed every job a stopped server left -- and deleted its
        draft. A background run did not stop with the server: its job is followed again and
        ends when the run does (here it ended while the server was down)."""
        import json
        pr = fast_follow
        job = _bg_job(sql_db, version)
        stamp = tmp_path / "runs" / version.id / "20261002-090000"
        proc, run = _fake_run(stamp, "0",
                              "[10:00:00] INFO orchestration: === Phase 2: Derive model ===")
        proc.wait(timeout=30)
        (stamp / "run.json").write_text(json.dumps({"pid": run["pid"], "job_id": job.id,
                                                    "log_path": run["log_path"]}),
                                        encoding="utf-8")
        monkeypatch.setattr(pr, "_data_root", lambda: str(tmp_path))
        done = []
        monkeypatch.setattr(pr, "_complete", lambda db, job_id: done.append(job_id))
        monkeypatch.setattr(sql_db.jobs, "list_active", lambda: [sql_db.jobs.get(job.id)])
        assert pr.fail_interrupted_jobs(sql_db) == 0
        t = pr._job_threads.get(job.id)
        if t is not None:
            t.join(timeout=30)
        assert done == [job.id]
        got = sql_db.jobs.get(job.id)
        assert got.status == "running" and got.phase == 2           # caught up from the log

    def test_a_job_with_no_background_run_is_failed_as_before(self, sql_db, draft, tmp_path,
                                                              monkeypatch):
        from api.services import pipeline_runner as pr
        job = _bg_job(sql_db, draft)
        monkeypatch.setattr(pr, "_data_root", lambda: str(tmp_path))
        monkeypatch.setattr(sql_db.jobs, "list_active", lambda: [sql_db.jobs.get(job.id)])
        assert pr.fail_interrupted_jobs(sql_db) == 1
        assert sql_db.jobs.get(job.id).status == "failed"
        assert sql_db.versions.get(draft.id) is None


class TestResume:
    def _set_status(self, sql_db, version, status):
        with sql_db._engine.begin() as cx:
            cx.execute(sa.update(s.versions).where(s.versions.c.id == version.id)
                       .values(pipeline_status=status))

    def test_without_a_database_there_is_no_background_run_to_resume(self, sql_db, version):
        from api.db.in_memory import InMemoryDatabase
        from api.services import pipeline_runner as pr
        with pytest.raises(pr.ResumeRefused) as exc:
            pr.start_resume(InMemoryDatabase(), version)
        assert exc.value.code == "NO_BACKGROUND_RUNS"

    def test_a_complete_version_has_nothing_to_resume(self, sql_db, version):
        from api.services import pipeline_runner as pr
        self._set_status(sql_db, version, "complete")
        with pytest.raises(pr.ResumeRefused) as exc:
            pr.start_resume(sql_db, version)
        assert exc.value.code == "NOTHING_TO_RESUME"

    def test_a_stopped_web_run_is_resumed_by_its_own_job(self, sql_db, version, monkeypatch):
        """Its job is reopened, so the end of the resume finalises the version as the run's end
        would have."""
        from api.services import pipeline_runner as pr
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.Math", "Layer1.App"], "waiting")
        gen = _bg_job(sql_db, version, status="failed", error_message="Stopped: ...")
        seen, done = {}, []
        monkeypatch.setattr(pr, "_execute_detached",
                            lambda db, job_id, cmd, **kw: seen.update(cmd=cmd, kw=kw) or True)
        monkeypatch.setattr(pr, "_complete", lambda db, job_id: done.append(job_id))
        job = pr.start_resume(sql_db, version)
        assert job.id == gen.id
        t = pr._job_threads.get(job.id)
        if t is not None:
            t.join(timeout=30)
        assert seen["cmd"][2:] == ["resume", "--project-id", "p1", "--version-id", version.id]
        assert seen["kw"]["phase_start"] == 3                         # the documents are left
        assert done == [gen.id]
        assert sql_db.jobs.get(gen.id).error_message is None

    def test_a_version_with_no_unfinished_web_run_gets_a_job_of_its_own(self, sql_db, version,
                                                                        monkeypatch):
        from api.services import pipeline_runner as pr
        from core.version_run import mark_components
        mark_components(version.id, ["Layer2.Gpio"], "failed", error="exit 1")
        monkeypatch.setattr(pr, "_execute_detached", lambda db, job_id, cmd, **kw: True)
        job = pr.start_resume(sql_db, version)
        assert job.mode == "export" and [p.number for p in job.phases] == [3, 4]
        t = pr._reexport_threads.get(job.id)
        if t is not None:
            t.join(timeout=30)
        got = sql_db.jobs.get(job.id)
        assert got.status == "complete" and got.activity_detail.startswith("Resumed")

    def test_a_cli_resume_finishes_the_web_job_it_carried_on(self, sql_db, version, monkeypatch):
        """Until the web app has a Resume button, a stopped web run is resumed on the server. Its
        job is then finished as the API would have: the version leaves draft."""
        import analyzer
        from api.services import pipeline_runner as pr
        gen = _bg_job(sql_db, version, status="failed", error_message="Stopped: ...")
        done = []

        def complete(db, job_id):
            assert db.jobs.get(job_id).status == "running"           # `_complete` skips failed
            done.append(job_id)
        monkeypatch.setattr(pr, "_complete", complete)
        analyzer._finish_web_job("p1", version.id, db=sql_db)
        assert done == [gen.id]
        assert sql_db.jobs.get(gen.id).error_message is None

    @pytest.mark.parametrize("status", ["running", "complete", "cancelled"])
    def test_a_web_job_that_is_followed_or_done_is_left_alone(self, sql_db, version, monkeypatch,
                                                             status):
        import analyzer
        from api.services import pipeline_runner as pr
        _bg_job(sql_db, version, status=status)
        monkeypatch.setattr(pr, "_complete", lambda db, job_id: pytest.fail("finished"))
        analyzer._finish_web_job("p1", version.id, db=sql_db)
        analyzer._finish_web_job("p2", version.id, db=sql_db)        # not that project's

    def test_the_components_route_says_what_resume_would_do(self, client, sql_db, version):
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.Math"], "failed", error="exit 1")
        r = client.get(f"/api/v1/projects/p1/versions/{version.id}/components",
                       headers=_hdr(client, "bob"))
        assert r.status_code == 200, r.text
        assert r.json()["resume_action"] == "export"

    def test_only_an_admin_resumes(self, client, sql_db, version):
        r = client.post(f"/api/v1/projects/p1/versions/{version.id}/resume",
                        headers=_hdr(client, "bob"))
        assert r.status_code == 403

    def test_nothing_to_resume_is_409(self, client, sql_db, version):
        self._set_status(sql_db, version, "complete")
        r = client.post(f"/api/v1/projects/p1/versions/{version.id}/resume",
                        headers=_hdr(client, "alice"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NOTHING_TO_RESUME"
