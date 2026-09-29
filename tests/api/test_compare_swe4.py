"""Compare counts a component's SWE.4 document beside its SWE.3 one.

Every run makes both documents of a component, and they share its output dir (`group`). Compare
keyed documents by group alone, so one of the two silently replaced the other. Now SWE.3 is
compared as before and SWE.4 by what it is made from: the component's test_specs.json.
"""
import datetime
import json
import uuid

from api.models.domain import Document, Project, Version
from api.services import compare_engine as ce

NOW = datetime.datetime.now(datetime.timezone.utc)


def _project(db):
    pid = "pcmp" + uuid.uuid4().hex[:6]
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config={}, architecture_layers=[], status="in_review", created_by="u1",
        created_at=NOW, updated_at=NOW))
    return pid


def _version(db, pid, tag, sha):
    v = Version(id="ver" + uuid.uuid4().hex[:8], project_id=pid, tag=tag, commit_sha=sha,
                branch="main", description="", status="in_review", docs_count=0,
                created_by="u1", created_at=NOW)
    db.versions.create(v)
    return v


def _docs(db, pid, ver, groups):
    for g in groups:
        for process in ("SWE.3", "SWE.4"):
            db.documents.update(Document(
                id="doc" + uuid.uuid4().hex[:8], project_id=pid, version_id=ver.id,
                process=process, name=g.split(".")[-1], subtitle="", layer="Layer1", group=g,
                status="in_review", due_date=None, created_at=NOW, updated_at=NOW))


def _output(root, pid, ver, group, specs):
    d = root / "workspaces" / pid / "versions" / ver.id / "output" / group
    d.mkdir(parents=True)
    (d / "interface_tables.json").write_text(json.dumps({"unitNames": {}}), encoding="utf-8")
    (d / "test_specs.json").write_text(json.dumps(specs), encoding="utf-8")


def test_swe4_documents_are_compared_by_their_test_specs(db, tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_REPO_ROOT", tmp_path)
    pid = _project(db)
    v1 = _version(db, pid, "v1", "a" * 40)
    v2 = _version(db, pid, "v2", "b" * 40)
    _docs(db, pid, v1, ["Layer1.Lib", "Layer1.Math"])
    _docs(db, pid, v2, ["Layer1.Lib", "Layer1.Math", "Layer1.Util"])
    _output(tmp_path, pid, v1, "Layer1.Lib", {"u": {"functions": [{"name": "f", "returnType": "int"}]}})
    _output(tmp_path, pid, v2, "Layer1.Lib", {"u": {"functions": [{"name": "f", "returnType": "long"}]}})
    _output(tmp_path, pid, v1, "Layer1.Math", {"u": {"functions": []}})
    _output(tmp_path, pid, v2, "Layer1.Math", {"u": {"functions": []}})
    _output(tmp_path, pid, v2, "Layer1.Util", {})

    r = ce.compute_compare(db, pid, v2.id, v1.id)
    swe4 = {(d["name"], d["diff_type"]) for d in r["changed_documents"] if d["process"] == "SWE.4"}
    assert swe4 == {("Lib", "changed"), ("Util", "added")}
    swe3 = {(d["name"], d["diff_type"]) for d in r["changed_documents"] if d["process"] == "SWE.3"}
    assert ("Util", "added") in swe3
    # SWE.3: Util added, Lib + Math unchanged. SWE.4: Util added, Lib changed, Math unchanged.
    assert r["summary"] == {"added": 2, "changed": 1, "removed": 0, "unchanged": 3}


def test_without_output_both_documents_of_a_component_count(db, tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_REPO_ROOT", tmp_path)       # no snapshots at all -> DB fallback
    pid = _project(db)
    v1 = _version(db, pid, "v1", "c" * 40)
    v2 = _version(db, pid, "v2", "d" * 40)
    _docs(db, pid, v1, ["Layer1.Lib"])
    _docs(db, pid, v2, ["Layer1.Lib", "Layer1.Util"])
    r = ce.compute_compare(db, pid, v2.id, v1.id)
    assert r["summary"] == {"added": 2, "changed": 0, "removed": 0, "unchanged": 2}
    assert sorted(d["process"] for d in r["changed_documents"]) == ["SWE.3", "SWE.4"]
