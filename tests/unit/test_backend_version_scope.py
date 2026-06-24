"""Backend tests for M3.8 (branch/commit endpoints) + M3.9 (version-scoped reads).

M3.9 is tested fully synthetically (a temp workspace with two versions that hold
DIFFERENT model/output) so it is portable. M3.8 needs a real clone with origin/*
refs, so it runs only when the samplecpp workspace is seeded.

NOTE: backend/main.py self-bootstraps sys.path and imports the bare module name
`models` (backend/models.py), which would shadow the flowchart tests' `models`
(src/flowchart/models.py) if imported at COLLECTION time. So we import the backend
lazily, inside fixtures/tests (run time), via `_load_backend()`."""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SAMPLE_REPO = os.path.join(PROJECT_ROOT, "workspaces", "samplecpp", "repo")
P = "/api/v1"

_BACKEND_CACHE = {}


def _load_backend():
    """Import backend.main + TestClient at run time. Skips if fastapi/httpx absent."""
    if "mod" not in _BACKEND_CACHE:
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        try:
            from fastapi.testclient import TestClient
            import backend.main as backend_main  # triggers backend's own sys.path bootstrap
        except Exception as exc:  # pragma: no cover - env without fastapi/httpx
            pytest.skip(f"backend import unavailable: {exc}")
        _BACKEND_CACHE["mod"] = backend_main
        _BACKEND_CACHE["client_cls"] = TestClient
    return _BACKEND_CACHE["mod"], _BACKEND_CACHE["client_cls"]


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _make_version(versions_dir, vid, functions, flowcharts_by_unit):
    vdir = os.path.join(versions_dir, vid)
    _write(os.path.join(vdir, "model", "functions.json"), functions)
    _write(os.path.join(vdir, "model", "metadata.json"), {"basePath": vdir})
    _write(os.path.join(vdir, "config.json"), {"layers": {}})
    _write(os.path.join(vdir, "manifest.json"),
           {"versionId": vid, "status": "complete", "decision": "full"})
    for unit, entries in flowcharts_by_unit.items():
        # scoped layout: output/<scope>/flowcharts/<unit>.json
        _write(os.path.join(vdir, "output", "Grp", "flowcharts", f"{unit}.json"), entries)


@pytest.fixture
def scoped_client(tmp_path, monkeypatch):
    """A TestClient over a temp workspace 'tp' with two distinct versions."""
    backend_main, TestClient = _load_backend()
    root = str(tmp_path / "workspaces")
    versions = os.path.join(root, "tp", "versions")
    os.makedirs(os.path.join(root, "tp", "repo"))  # repo dir present (unused by M3.9)
    _write(os.path.join(versions, "index.json"), [{"versionId": "v2"}, {"versionId": "v1"}])

    # v1 has onlyV1 + shared; v2 has only shared. Flowchart for `shared` differs.
    _make_version(versions, "v1",
                  {"C|U|onlyV1|": {"qualifiedName": "onlyV1", "location": {"file": "U.cpp", "line": 1}},
                   "C|U|shared|": {"qualifiedName": "shared", "location": {"file": "U.cpp", "line": 9}}},
                  {"U": [{"name": "shared", "flowchart": "FLOW_V1"}]})
    _make_version(versions, "v2",
                  {"C|U|shared|": {"qualifiedName": "shared", "location": {"file": "U.cpp", "line": 9}}},
                  {"U": [{"name": "shared", "flowchart": "FLOW_V2"}]})

    monkeypatch.setattr("incremental.stores.default_workspaces_root", lambda: root)
    return TestClient(backend_main.app)


class TestM39VersionScopedReads:
    def test_function_isolation_between_versions(self, scoped_client):
        # onlyV1 exists in v1, not in v2 -> proves reads hit the right snapshot
        r1 = scoped_client.get(f"{P}/functions/C|U|onlyV1|", params={"projectId": "tp", "versionId": "v1"})
        r2 = scoped_client.get(f"{P}/functions/C|U|onlyV1|", params={"projectId": "tp", "versionId": "v2"})
        assert r1.status_code == 200 and r1.json()["name"] == "onlyV1"
        assert r2.status_code == 404

    def test_flowchart_is_version_specific(self, scoped_client):
        r1 = scoped_client.get(f"{P}/flowcharts/C|U|shared|", params={"projectId": "tp", "versionId": "v1"})
        r2 = scoped_client.get(f"{P}/flowcharts/C|U|shared|", params={"projectId": "tp", "versionId": "v2"})
        assert r1.status_code == 200 and r1.json()["code"] == "FLOW_V1"
        assert r2.status_code == 200 and r2.json()["code"] == "FLOW_V2"

    def test_function_flowchart_field_version_specific(self, scoped_client):
        r = scoped_client.get(f"{P}/functions/C|U|shared|", params={"projectId": "tp", "versionId": "v2"})
        assert r.status_code == 200 and r.json()["flowchart"] == "FLOW_V2"

    def test_unknown_version_404(self, scoped_client):
        r = scoped_client.get(f"{P}/components", params={"projectId": "tp", "versionId": "v9"})
        assert r.status_code == 404

    def test_components_version_scoped_ok(self, scoped_client):
        r = scoped_client.get(f"{P}/components", params={"projectId": "tp", "versionId": "v1"})
        assert r.status_code == 200

    def test_unknown_project_404(self, scoped_client):
        r = scoped_client.get(f"{P}/functions/C|U|shared|", params={"projectId": "nope", "versionId": "v1"})
        assert r.status_code == 404


@pytest.mark.skipif(not os.path.isdir(_SAMPLE_REPO), reason="samplecpp workspace not seeded")
class TestM38BranchCommitEndpoints:
    def test_list_branches(self):
        backend_main, TestClient = _load_backend()
        r = TestClient(backend_main.app).get(f"{P}/projects/samplecpp/branches")
        assert r.status_code == 200
        assert "main" in [b["name"] for b in r.json()] and all("lastCommit" in b for b in r.json())

    def test_list_commits_paged(self):
        backend_main, TestClient = _load_backend()
        r = TestClient(backend_main.app).get(f"{P}/projects/samplecpp/branches/main/commits",
                                             params={"limit": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["branch"] == "main" and body["total"] >= 1
        assert len(body["commits"]) <= 2 and all("sha" in cm for cm in body["commits"])

    def test_unknown_branch_404(self):
        backend_main, TestClient = _load_backend()
        r = TestClient(backend_main.app).get(f"{P}/projects/samplecpp/branches/no-such-branch/commits")
        assert r.status_code == 404

    def test_unknown_project_404(self):
        backend_main, TestClient = _load_backend()
        r = TestClient(backend_main.app).get(f"{P}/projects/nope/branches")
        assert r.status_code == 404
