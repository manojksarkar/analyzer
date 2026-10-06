"""A re-export is a job of its own, addressed by version.

Two defects this replaces, both found testing the review feature's export step:

  * a re-export reused the version's GENERATION job and never changed its status, which stayed
    `complete` -- so polling it, or its live stream, said "finished" before anything ran, a
    failure was never recorded, and nothing stopped a second one starting on the same folder;
  * it was addressed by job id, and a client could find only the project's NEWEST job, so older
    versions could not be re-exported at all.

The engine step (`_do_reexport`) is replaced by a stand-in the test controls: what is under test
is the job's lifecycle, the one-at-a-time guard and the addressing, not the pipeline.
"""
import datetime
import threading
import uuid

import pytest

from api.models.domain import (AnalysisJob, AnalysisPhase, Project, ProjectMember, Version,
                               REEXPORT_MODE)
from api.services import pipeline_runner as pr

UTC = datetime.timezone.utc


def _uid(prefix):
    return prefix + uuid.uuid4().hex[:6]


def _project(db):
    pid = _uid("prx")
    now = datetime.datetime.now(UTC)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="C:/repo", repo_provider="github", default_branch="main", build_config={},
        architecture_layers=[{"name": "L1", "groups": ["G1"]}], status="in_review",
        created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id=_uid("m"), project_id=pid, user_id="u1", role="admin", status="active",
        invited_by="u1", invited_at=now, joined_at=now))
    db.members.add_member(ProjectMember(
        id=_uid("m"), project_id=pid, user_id="u2", role="developer", status="active",
        invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _version(db, pid, tag="v1", *, generation="complete", minutes_ago=0):
    """A version and, unless `generation` is None, the web-app job that generated it."""
    now = datetime.datetime.now(UTC) - datetime.timedelta(minutes=minutes_ago)
    vid = _uid("ver")
    db.versions.create(Version(
        id=vid, project_id=pid, tag=tag, commit_sha="a" * 40, branch="main",
        description="", status="in_review", docs_count=1, created_by="u1", created_at=now))
    if generation is not None:
        db.jobs.create(AnalysisJob(
            id=_uid("jobgen"), project_id=pid, commit_sha="a" * 40, version_id=vid,
            reference_version_id=None, status=generation, pause_after_phase1=False,
            layer_filter=None, phase=4, phase_pct=100, current_activity="Done",
            activity_detail="", elapsed_seconds=60, eta_seconds=0,
            phases=[AnalysisPhase(n, "p%d" % n, "done", 1) for n in (1, 2, 3, 4)],
            started_at=now, completed_at=now, error_message=None, branch="main",
            version_tag=tag, mode="full", scope={"type": "group", "names": ["G1"]},
            no_llm=True, data_dict_id=None, narrowed_parse=True))
    return vid


def _documents(db, pid, vid, groups, *, reviewer=None, status="in_review"):
    """A SWE.3 and a SWE.4 document per component; `reviewer` reviews them all."""
    from api.models.domain import Document, DocumentAssignment
    now = datetime.datetime.now(UTC)
    out = []
    for g in groups:
        for process in ("SWE.3", "SWE.4"):
            d = Document(id=_uid("doc"), project_id=pid, version_id=vid, process=process,
                         name=g.split(".", 1)[-1], subtitle="", layer="L1", group=g,
                         status=status, due_date=None, created_at=now, updated_at=now)
            db.documents.update(d)
            if reviewer:
                db.assignments.set_reviewer(DocumentAssignment(_uid("a"), d.id, reviewer, "u1", now))
            out.append(d)
    return out


class _Engine:
    """Stands in for `_do_reexport`: holds until released, then succeeds, fails or raises."""

    def __init__(self, monkeypatch, outcome="ok"):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.outcome = outcome

        def fake(db, job_id):
            self.entered.set()
            self.release.wait(20)
            if self.outcome == "raise":
                raise RuntimeError("engine blew up")
            if self.outcome == "fail":
                pr._mark_failed(db, job_id, "run.py exited with code 2.")
                return False
            return True
        monkeypatch.setattr(pr, "_do_reexport", fake)

    def finish(self, job_id):
        t = pr._reexport_threads.get(job_id)
        self.release.set()
        if t is not None:
            t.join(20)
            assert not t.is_alive(), "the re-export thread did not finish"


def _start(client, auth_header, pid, vid):
    return client.post(f"/api/v1/projects/{pid}/versions/{vid}/reexport", headers=auth_header)


def _job(client, auth_header, pid, job_id):
    return client.get(f"/api/v1/projects/{pid}/jobs/{job_id}", headers=auth_header).json()["job"]


class TestItIsAJobOfItsOwn:
    def test_it_answers_at_once_with_a_new_job(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["version_id"] == vid and body["status"] == "queued"
        generation = [j for j in db.jobs.list_for_version(vid) if j.mode != REEXPORT_MODE][0]
        assert body["job_id"] != generation.id
        job = _job(client, auth_header, pid, body["job_id"])
        assert job["mode"] == REEXPORT_MODE and job["version_id"] == vid
        assert [p["number"] for p in job["phases"]] == [3, 4]
        engine.finish(body["job_id"])

    def test_its_status_moves_the_way_a_client_already_follows(self, client, db, auth_header,
                                                               monkeypatch):
        """THE POINT of #1: queued/running while it works, complete when it is done -- the
        states the web app's polling and live stream wait for."""
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        assert engine.entered.wait(10)
        assert _job(client, auth_header, pid, job_id)["status"] == "running"
        engine.finish(job_id)
        job = _job(client, auth_header, pid, job_id)
        assert job["status"] == "complete" and job["completed_at"]
        assert all(p["status"] == "done" for p in job["phases"])

    def test_a_failure_is_recorded_with_its_reason(self, client, db, auth_header, monkeypatch):
        """It used to be lost: the failure path skipped a job that was already `complete`."""
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch, outcome="fail")
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(job_id)
        job = _job(client, auth_header, pid, job_id)
        assert job["status"] == "failed" and "exited with code 2" in job["error_message"]

    def test_an_unexpected_error_is_recorded_too(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch, outcome="raise")
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(job_id)
        job = _job(client, auth_header, pid, job_id)
        assert job["status"] == "failed" and "engine blew up" in job["error_message"]

    def test_the_generation_job_is_left_alone(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch, outcome="fail")
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(job_id)
        generation = [j for j in db.jobs.list_for_version(vid) if j.mode != REEXPORT_MODE][0]
        assert generation.status == "complete" and generation.error_message is None

    def test_it_is_never_the_projects_current_job(self, client, db, auth_header, monkeypatch):
        """`GET /jobs/current` is the project's latest RUN; the project page reads it.

        The generation is minutes older on purpose: the re-export must be the NEWER job, or
        "latest wins" would return the generation for the wrong reason. Windows clocks can hand
        two jobs created milliseconds apart the same timestamp."""
        pid = _project(db)
        vid = _version(db, pid, minutes_ago=5)
        engine = _Engine(monkeypatch)
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        current = client.get(f"/api/v1/projects/{pid}/jobs/current",
                             headers=auth_header).json()["job"]
        assert current["id"] != job_id and current["mode"] != REEXPORT_MODE
        engine.finish(job_id)

    def test_a_cancel_is_not_overwritten_by_the_finish(self, client, db, auth_header,
                                                       monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        job_id = _start(client, auth_header, pid, vid).json()["job_id"]
        assert engine.entered.wait(10)
        assert client.post(f"/api/v1/projects/{pid}/jobs/{job_id}/cancel",
                           headers=auth_header).status_code == 200
        engine.finish(job_id)
        assert _job(client, auth_header, pid, job_id)["status"] == "cancelled"


class TestOneAtATime:
    def test_a_second_request_the_running_one_covers_joins_it(self, client, db, auth_header,
                                                               monkeypatch):
        """No queue (WORD_FILE_UPDATES D6): the same request again follows the running job."""
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        first = _start(client, auth_header, pid, vid).json()["job_id"]
        assert engine.entered.wait(10)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 200, r.text
        assert r.json()["job_id"] == first and r.json()["joined"] is True
        assert len([j for j in db.jobs.list_for_version(vid) if j.mode == REEXPORT_MODE]) == 1
        engine.finish(first)

    def test_one_it_does_not_cover_is_refused_naming_the_running_job(self, client, db,
                                                                      auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A", "L1.B"])
        engine = _Engine(monkeypatch)
        first = client.post(f"/api/v1/projects/{pid}/versions/{vid}/reexport", headers=auth_header,
                            json={"scope": "all", "components": ["L1.A"]}).json()["job_id"]
        assert engine.entered.wait(10)
        r = client.post(f"/api/v1/projects/{pid}/versions/{vid}/reexport", headers=auth_header,
                        json={"scope": "all", "components": ["L1.B"]})
        assert r.status_code == 409, r.text
        d = r.json()["detail"]
        assert (d["code"], d["job_id"], d["components"], d["scope"]) == \
            ("REEXPORT_RUNNING", first, ["L1.A"], "all")
        engine.finish(first)

    def test_once_it_has_finished_another_may_start(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        engine = _Engine(monkeypatch)
        engine.release.set()
        first = _start(client, auth_header, pid, vid).json()["job_id"]
        engine.finish(first)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        engine.finish(r.json()["job_id"])

    def test_a_row_left_running_by_a_stopped_server_does_not_block(self, client, db,
                                                                   auth_header, monkeypatch):
        """Nothing in this process is running it, so nothing will ever finish it."""
        pid = _project(db)
        vid = _version(db, pid)
        stale = _uid("jobstale")
        db.jobs.create(AnalysisJob(
            id=stale, project_id=pid, commit_sha="a" * 40, version_id=vid,
            reference_version_id=None, status="running", pause_after_phase1=False,
            layer_filter=None, phase=3, phase_pct=0, current_activity="", activity_detail="",
            elapsed_seconds=0, eta_seconds=None,
            phases=[AnalysisPhase(3, "Run Views", "running", None),
                    AnalysisPhase(4, "Export DOCX", "pending", None)],
            started_at=datetime.datetime.now(UTC), completed_at=None, error_message=None,
            branch="main", version_tag="v1", mode=REEXPORT_MODE))
        engine = _Engine(monkeypatch)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        old = db.jobs.get(stale)
        assert old.status == "failed" and "Interrupted" in old.error_message
        engine.finish(r.json()["job_id"])


class TestAnyVersion:
    def test_an_older_version_can_be_re_exported(self, client, db, auth_header, monkeypatch):
        """THE POINT of #2. v1 is not the project's newest version, nor its current job's."""
        pid = _project(db)
        older = _version(db, pid, "v1", minutes_ago=30)
        _version(db, pid, "v2")
        engine = _Engine(monkeypatch)
        r = _start(client, auth_header, pid, older)
        assert r.status_code == 202, r.text
        assert _job(client, auth_header, pid, r.json()["job_id"])["version_id"] == older
        engine.finish(r.json()["job_id"])

    def test_the_job_addressed_endpoint_starts_the_same_kind_of_job(self, client, db,
                                                                    auth_header, monkeypatch):
        """Kept for existing callers. Its `job_id` is now the NEW job, the one to follow."""
        pid = _project(db)
        vid = _version(db, pid)
        generation = db.jobs.list_for_version(vid)[0].id
        engine = _Engine(monkeypatch)
        r = client.post(f"/api/v1/projects/{pid}/jobs/{generation}/reexport",
                        headers=auth_header)
        assert r.status_code == 200, r.text
        new = r.json()["job_id"]
        assert new != generation
        assert _job(client, auth_header, pid, new)["mode"] == REEXPORT_MODE
        engine.finish(new)


class TestRefusals:
    def test_a_version_still_being_generated(self, client, db, auth_header, monkeypatch):
        _Engine(monkeypatch)
        pid = _project(db)
        vid = _version(db, pid, generation="running")
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_NOT_READY"

    def test_a_cli_version_with_no_documents_yet(self, client, db, auth_header, monkeypatch):
        """A command-line version has no generation job; it is re-exported like any other once
        it has documents (tests/api/test_staged_generation_db.py) -- until then, refused."""
        _Engine(monkeypatch)
        pid = _project(db)
        vid = _version(db, pid, generation=None)
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_DOCUMENTS"

    def test_another_projects_version(self, client, db, auth_header, monkeypatch):
        _Engine(monkeypatch)
        pid, other = _project(db), _project(db)
        vid = _version(db, other)
        assert _start(client, auth_header, pid, vid).status_code == 404

    def test_a_member_who_is_not_an_admin(self, client, db, dev_header, monkeypatch):
        _Engine(monkeypatch)
        pid = _project(db)
        vid = _version(db, pid)
        assert _start(client, dev_header, pid, vid).status_code == 403

    def test_a_generation_cannot_be_asked_to_be_a_reexport(self, client, db, auth_header):
        pid = _project(db)
        r = client.post(f"/api/v1/projects/{pid}/jobs", headers=auth_header,
                        json={"commit_sha": "a" * 40, "version_tag": "vx", "mode": REEXPORT_MODE})
        assert r.status_code == 400


class TestAReexportRegistersMissingDocuments:
    """A version generated while `_make_documents` matched output dirs by the bare component
    name has its DOCX files on disk and no `documents` rows -- since 1df3016 every web-app run.
    Re-exporting it is how it gets its document list back."""

    LAYERS = [{"name": "L1", "groups": [{"name": "G1", "components": [{"name": "Comp A"}]}]}]

    def _setup(self, db, monkeypatch, tmp_path):
        pid = _project(db)
        project = db.projects.get(pid)
        project.architecture_layers = self.LAYERS
        db.projects.update(project)
        vid = _version(db, pid)
        comp_dir = tmp_path / "output" / "L1.Comp-A"
        comp_dir.mkdir(parents=True)
        (comp_dir / "software_detailed_design_L1.Comp-A.docx").write_bytes(b"PK")
        monkeypatch.setattr(pr.doc_render, "commit_output_root",
                            lambda *a, **k: tmp_path / "output")
        return pid, vid

    def _reexport(self, client, auth_header, monkeypatch, pid, vid):
        engine = _Engine(monkeypatch)
        engine.release.set()
        r = _start(client, auth_header, pid, vid)
        assert r.status_code == 202, r.text
        engine.finish(r.json()["job_id"])
        return _job(client, auth_header, pid, r.json()["job_id"])

    def test_they_are_registered(self, client, db, auth_header, monkeypatch, tmp_path):
        pid, vid = self._setup(db, monkeypatch, tmp_path)
        job = self._reexport(client, auth_header, monkeypatch, pid, vid)
        assert job["status"] == "complete"
        docs, total = db.documents.list_for_project(pid, version_id=vid, per_page=50)
        assert total == 1
        assert (docs[0].name, docs[0].layer, docs[0].group) == ("Comp A", "L1", "L1.Comp-A")
        assert db.versions.get(vid).docs_count == 1

    def test_a_second_reexport_registers_nothing_twice(self, client, db, auth_header,
                                                       monkeypatch, tmp_path):
        pid, vid = self._setup(db, monkeypatch, tmp_path)
        self._reexport(client, auth_header, monkeypatch, pid, vid)
        self._reexport(client, auth_header, monkeypatch, pid, vid)
        assert db.documents.list_for_project(pid, version_id=vid, per_page=50)[1] == 1

    def test_a_failed_reexport_registers_nothing(self, client, db, auth_header, monkeypatch,
                                                 tmp_path):
        pid, vid = self._setup(db, monkeypatch, tmp_path)
        engine = _Engine(monkeypatch, outcome="fail")
        engine.release.set()
        r = _start(client, auth_header, pid, vid)
        engine.finish(r.json()["job_id"])
        assert db.documents.list_for_project(pid, version_id=vid, per_page=50)[1] == 0


# ---------------------------------------------------------------------------
# Word file updates (docs/design/WORD_FILE_UPDATES.md §4.1): the scope, who, the job's starter
# ---------------------------------------------------------------------------
def _out_of_date(monkeypatch, groups):
    """Make these components' documents out of date (the rule itself: tests/unit/test_word_files.py)."""
    import os
    import sys
    eng = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    from review.word_files import FileState, UP_TO_DATE
    from api.services import word_files

    def states(db, version, docs=None, **k):
        docs = word_files.version_documents(db, version) if docs is None else docs
        return {d.id: (FileState(True, ("corrections",), 2, 0, None)
                       if d.group in groups else UP_TO_DATE) for d in docs}
    monkeypatch.setattr(word_files, "file_states", states)


def _update(client, header, pid, vid, **body):
    return client.post(f"/api/v1/projects/{pid}/versions/{vid}/reexport", headers=header, json=body)


class TestTheUpdateScope:
    def test_nothing_out_of_date_starts_nothing(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"])
        _out_of_date(monkeypatch, set())
        _Engine(monkeypatch)
        r = _update(client, auth_header, pid, vid, scope="out_of_date")
        assert r.status_code == 200, r.text
        assert r.json() == {"job_id": None, "status": "up_to_date", "version_id": vid,
                            "scope": "out_of_date", "components": [], "joined": False}
        assert not [j for j in db.jobs.list_for_version(vid) if j.mode == REEXPORT_MODE]

    def test_an_admin_updates_what_is_out_of_date_and_is_its_starter(self, client, db,
                                                                      auth_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A", "L1.B", "L1.C"])
        _out_of_date(monkeypatch, {"L1.A", "L1.C"})
        engine = _Engine(monkeypatch)
        r = _update(client, auth_header, pid, vid, scope="out_of_date")
        assert r.status_code == 202, r.text
        body = r.json()
        assert (body["scope"], body["components"], body["joined"]) == \
            ("out_of_date", ["L1.A", "L1.C"], False)
        job = _job(client, auth_header, pid, body["job_id"])
        assert job["reason"] == "update" and job["started_by"]["user_id"] == "u1"
        assert job["scope"]["names"] == ["L1.A", "L1.C"]
        engine.finish(body["job_id"])

    def test_a_developer_updates_the_documents_they_review(self, client, db, dev_header,
                                                          monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"], reviewer="u2")
        _documents(db, pid, vid, ["L1.B"], reviewer="u3")
        _out_of_date(monkeypatch, {"L1.A", "L1.B"})
        engine = _Engine(monkeypatch)
        r = _update(client, dev_header, pid, vid, scope="out_of_date")
        assert r.status_code == 202, r.text
        assert r.json()["components"] == ["L1.A"]
        engine.finish(r.json()["job_id"])

    def test_and_the_one_they_have_open(self, client, db, dev_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        other = _documents(db, pid, vid, ["L1.B"], reviewer="u3")
        _out_of_date(monkeypatch, {"L1.B"})
        engine = _Engine(monkeypatch)
        r = _update(client, dev_header, pid, vid, scope="out_of_date", components=["L1.B"],
                    document_id=other[0].id)
        assert r.status_code == 202, r.text
        assert r.json()["components"] == ["L1.B"]
        engine.finish(r.json()["job_id"])

    def test_not_others(self, client, db, dev_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"], reviewer="u2")
        _documents(db, pid, vid, ["L1.B"], reviewer="u3")
        _out_of_date(monkeypatch, {"L1.A", "L1.B"})
        _Engine(monkeypatch)
        r = _update(client, dev_header, pid, vid, scope="out_of_date", components=["L1.A", "L1.B"])
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "NOT_YOUR_DOCUMENTS"
        assert r.json()["detail"]["components"] == ["L1.B"]

    @pytest.mark.parametrize("header", ["auth_header", "dev_header"])
    def test_a_component_with_no_documents_is_said_not_filtered_away(self, client, db, request,
                                                                     header, monkeypatch):
        """A misspelt name ("L1.Nope", spaces for hyphens, a bare name) answered 200
        `up_to_date` with no components (admin) or a 403 (developer). The `all` scope said 422."""
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"], reviewer="u2")
        _out_of_date(monkeypatch, {"L1.A"})
        _Engine(monkeypatch)
        r = _update(client, request.getfixturevalue(header), pid, vid, scope="out_of_date",
                    components=["L1.A", "L1.Nope"])
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "INVALID_COMPONENTS"
        assert r.json()["detail"]["components"] == ["L1.Nope"]
        assert not [j for j in db.jobs.list_for_version(vid) if j.mode == REEXPORT_MODE]

    @pytest.mark.parametrize("spelt", ["L1.My Comp", "l1.my-comp", "L1.My-Comp"])
    def test_a_component_as_the_config_spells_it_is_its_documents_group(self, client, db,
                                                                        auth_header, monkeypatch,
                                                                        spelt):
        """The config says "Layer1.Sample Core", the documents' group "Layer1.Sample-Core":
        R11 and the job scope take either, and so does the update (it answered `up_to_date`)."""
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.My-Comp"])
        _out_of_date(monkeypatch, {"L1.My-Comp"})
        engine = _Engine(monkeypatch)
        r = _update(client, auth_header, pid, vid, scope="out_of_date", components=[spelt])
        assert r.status_code == 202, r.text
        assert r.json()["components"] == ["L1.My-Comp"]
        engine.finish(r.json()["job_id"])

    def test_rebuild_all_is_for_admins(self, client, db, dev_header, monkeypatch):
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"], reviewer="u2")
        _Engine(monkeypatch)
        assert _update(client, dev_header, pid, vid, scope="all").status_code == 403
        assert _update(client, dev_header, pid, vid).status_code == 403     # absent = all

    def test_a_document_of_another_version_is_404(self, client, db, auth_header, monkeypatch):
        pid = _project(db)
        vid, other = _version(db, pid, "v1"), _version(db, pid, "v2")
        doc = _documents(db, pid, other, ["L1.A"])[0]
        _Engine(monkeypatch)
        r = _update(client, auth_header, pid, vid, scope="out_of_date", document_id=doc.id)
        assert r.status_code == 404

    def test_a_writer_holding_the_version_is_named(self, client, db, auth_header, monkeypatch):
        """S5b: VERSION_BUSY says what holds the version."""
        from api.services import word_files
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"])
        _out_of_date(monkeypatch, {"L1.A"})
        _Engine(monkeypatch)
        monkeypatch.setattr(pr, "version_writer_busy", lambda db, v: "analyzer generate")
        held = {"kind": "generation", "job_id": None, "command": "generate"}
        monkeypatch.setattr(word_files, "writer", lambda db, v, snake=False: held)
        r = _update(client, auth_header, pid, vid, scope="out_of_date")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_BUSY"
        assert r.json()["detail"]["writer"] == held


class TestTheStarterIsTold:
    def _finished(self, client, db, header, monkeypatch, outcome):
        pid = _project(db)
        vid = _version(db, pid)
        docs = _documents(db, pid, vid, ["L1.Brake"], reviewer="u2")
        _out_of_date(monkeypatch, {"L1.Brake"})
        engine = _Engine(monkeypatch, outcome=outcome)
        engine.release.set()
        r = _update(client, header, pid, vid, scope="out_of_date", document_id=docs[0].id)
        assert r.status_code == 202, r.text
        engine.finish(r.json()["job_id"])
        return docs[0]

    def test_a_finished_update(self, client, db, dev_header, monkeypatch):
        doc = self._finished(client, db, dev_header, monkeypatch, "ok")
        mine = [n for n in db.notifications.list_unread("u2") if n.document_id == doc.id]
        assert [n.type for n in mine] == ["word_files_updated"]
        assert mine[0].message == "Word files updated: Brake in v1."

    def test_a_failed_one(self, client, db, dev_header, monkeypatch):
        doc = self._finished(client, db, dev_header, monkeypatch, "fail")
        mine = [n for n in db.notifications.list_unread("u2") if n.document_id == doc.id]
        assert [n.type for n in mine] == ["word_files_update_failed"]
        assert mine[0].message == "Update failed: Brake in v1 \u2014 run.py exited with code 2."
        assert not [n for n in db.notifications.list_unread("u1") if n.document_id == doc.id], \
            "a button's update tells only its starter"


class TestAStaleComponentIsMadeAgainFromItsViews:
    """SA: the in-process re-export (no background runs) went to Phase 4 alone for a component a
    layer added since had made stale -- printing its old views again."""

    def test_its_scope_is_asked(self, db, monkeypatch):
        from types import SimpleNamespace
        from api.services import version_components
        monkeypatch.setattr(version_components, "state_rows", lambda eng, vid: {
            "L1.A": {"state": "stale"}, "L1.B": {"state": "generated"}})
        job = lambda names: SimpleNamespace(version_id="v", scope={"type": "component",
                                                                   "names": names})
        assert pr._stale_in_scope(db, job(["L1.A"])) is True
        assert pr._stale_in_scope(db, job(["L1.B"])) is False
        assert pr._stale_in_scope(db, SimpleNamespace(version_id="v", scope=None)) is True

    def test_the_in_process_path_asks_it(self):
        import inspect
        src = inspect.getsource(pr._do_reexport)
        assert "if from_phase > 3 and _stale_in_scope(db, job):" in src


class TestR9SaysWhatHoldsTheVersion:
    def test_an_update_at_work(self, client, db, auth_header, monkeypatch):
        if not hasattr(db, "_engine"):
            pytest.skip("R9 finds the version in the engine database, which the in-memory "
                        "backend leaves empty")
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A", "L1.B"])
        _out_of_date(monkeypatch, {"L1.A"})
        engine = _Engine(monkeypatch)
        job_id = _update(client, auth_header, pid, vid, scope="out_of_date").json()["job_id"]
        assert engine.entered.wait(10)
        body = client.get(f"/api/v1/projects/{pid}/versions/{vid}/export-readiness",
                          headers=auth_header).json()
        w = body["writer"]
        assert (w["kind"], w["jobId"], w["components"], w["componentsTotal"]) ==             ("update", job_id, ["L1.A"], 1)
        assert w["startedBy"]["userId"] == "u1"
        assert [e["updating"] for e in body["outOfDate"]] == [True, True]   # its SWE.3 and SWE.4
        rx = body["reexport"]
        assert (rx["jobId"], rx["scope"], rx["reason"], rx["components"]) ==             (job_id, "out_of_date", "update", ["L1.A"])
        engine.finish(job_id)
        body = client.get(f"/api/v1/projects/{pid}/versions/{vid}/export-readiness",
                          headers=auth_header).json()
        assert body["writer"] is None and body["reexport"]["status"] == "complete"


# ---------------------------------------------------------------------------
# The review of 2026-10-06: findings 7, 8b, 8c
# ---------------------------------------------------------------------------
def _states_after_the_run(monkeypatch, failed):
    """`version_components` as run.py leaves it: `failed` components failed just now."""
    from api.services import word_files

    def rows(db, version_id):
        now = datetime.datetime.now(UTC)
        return {c: {"state": "failed", "finished_at": now, "error": "%s: render failed" % c}
                for c in failed}
    monkeypatch.setattr(word_files, "_state_rows", rows)


class TestAFailedComponentIsNotUpdated:
    """Finding 7. run.py exits 3 when a component fails and goes on with the others: the job
    was `complete` and the starter told "Word files updated" for a file never written."""

    def _run(self, client, db, header, monkeypatch, groups, failed):
        pid = _project(db)
        vid = _version(db, pid)
        docs = _documents(db, pid, vid, groups, reviewer="u2")
        _out_of_date(monkeypatch, set(groups))
        _states_after_the_run(monkeypatch, failed)
        engine = _Engine(monkeypatch)
        engine.release.set()
        r = _update(client, header, pid, vid, scope="out_of_date", document_id=docs[0].id)
        assert r.status_code == 202, r.text
        engine.finish(r.json()["job_id"])
        notes = [n for n in db.notifications.list_unread("u2") if n.document_id == docs[0].id]
        return _job(client, header, pid, r.json()["job_id"]), notes

    def test_when_every_one_failed_the_update_failed(self, client, db, dev_header, monkeypatch):
        job, notes = self._run(client, db, dev_header, monkeypatch, ["L1.Brake"], ["L1.Brake"])
        assert job["status"] == "failed" and "L1.Brake" in job["error_message"]
        assert [(n.type, n.message) for n in notes] == [
            ("word_files_update_failed",
             "Update failed: Brake in v1 \u2014 L1.Brake: render failed.")]

    def test_when_some_failed_each_is_told_as_it_ended(self, client, db, dev_header, monkeypatch):
        job, notes = self._run(client, db, dev_header, monkeypatch, ["L1.A", "L1.B"], ["L1.B"])
        assert job["status"] == "complete" and "failed: L1.B" in job["activity_detail"]
        assert sorted((n.type, n.message) for n in notes) == [
            ("word_files_update_failed", "Update failed: B in v1 \u2014 L1.B: render failed."),
            ("word_files_updated", "Word files updated: A in v1.")]


class TestARunningExportOrResumeIsNamedAsSuch:
    """Finding 8: a running export or resume was refused as an update, `scope: out_of_date`."""

    def test_an_export_at_work(self, client, db, auth_header, monkeypatch):
        import threading
        pid = _project(db)
        vid = _version(db, pid)
        _documents(db, pid, vid, ["L1.A"])
        _out_of_date(monkeypatch, {"L1.A"})
        _Engine(monkeypatch)
        db.jobs.create(AnalysisJob(
            id=_uid("jobexp"), project_id=pid, commit_sha="a" * 40, version_id=vid,
            reference_version_id=None, status="running", pause_after_phase1=False,
            layer_filter=None, phase=3, phase_pct=0, current_activity="", activity_detail="",
            elapsed_seconds=0, eta_seconds=None, phases=[], started_at=datetime.datetime.now(UTC),
            completed_at=None, error_message=None, branch="main", version_tag="v1",
            mode="export", scope={"type": "component", "names": ["L1.New"]}, reason="export"))
        export = [j for j in db.jobs.list_for_version(vid) if j.mode == "export"][0]
        hold = threading.Event()
        t = threading.Thread(target=hold.wait, args=(20,), daemon=True)
        t.start()
        pr._reexport_threads[export.id] = t
        try:
            r = _update(client, auth_header, pid, vid, scope="out_of_date")
            assert r.status_code == 409, r.text
            d = r.json()["detail"]
            assert (d["code"], d["scope"], d["kind"], d["job_id"], d["components"]) == \
                ("REEXPORT_RUNNING", "export", "export", export.id, ["L1.New"])
            assert "rendered by an export" in d["message"]
        finally:
            hold.set()
            pr._reexport_threads.pop(export.id, None)


class TestUnreadableStatesFailClosed:
    """Finding 8: an error reading `version_components` read as "nothing stale, nothing held"."""

    def test_the_word_file_rule_raises(self, db, monkeypatch):
        from api.services import version_components, word_files

        def broken(engine, version_id):
            raise RuntimeError("database gone")
        monkeypatch.setattr(version_components, "state_rows", broken)
        with pytest.raises(RuntimeError):
            word_files.stale_layers(db, "v")

    def test_the_in_process_reexport_makes_the_views_again(self, db, monkeypatch):
        from types import SimpleNamespace
        from api.services import version_components

        def broken(engine, version_id):
            raise RuntimeError("database gone")
        monkeypatch.setattr(version_components, "state_rows", broken)
        assert pr._stale_in_scope(db, SimpleNamespace(version_id="v", scope=None)) is True
