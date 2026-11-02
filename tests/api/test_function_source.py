"""A function's own lines of code beside its flowchart (BACKLOG NW-7):
`GET /projects/{p}/versions/{v}/functions/source?function_id=...`, read from the version's checkout,
never cloned in the request."""
import datetime
import subprocess
import types
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import Project, ProjectMember, Version

CODE = "\n".join([
    "#include \"util.h\"",
    "",
    "int scale(int a, int b) {",
    "    if (a > b) {",
    "        return a * 2;",
    "    }",
    "    return b;",
    "}",
    "",
]) + "\n"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@x", "PATH": __import__("os").environ["PATH"],
                        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})


@pytest.fixture
def version(db, tmp_path):
    """A project, a version at a real commit, its checkout in the workspaces, and the function
    `Math|Utils|scale` stored at lines 3-8 of src/util.cpp."""
    if not hasattr(db, "_engine"):
        pytest.skip("the model rows are the SQL backend's")
    from sqlalchemy import insert
    from api.db.postgres import schema as s
    now = datetime.datetime.now(datetime.timezone.utc)
    pid, vid = "psrc" + uuid.uuid4().hex[:6], "ver" + uuid.uuid4().hex[:8]
    repo = tmp_path / "seed"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "util.cpp").write_text(CODE, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "c")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                         text=True, check=True).stdout.strip()
    workspaces = tmp_path / "ws"
    (workspaces / pid).mkdir(parents=True)
    repo.rename(workspaces / pid / sha[:16])
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="", repo_provider="github", default_branch="main", build_config={},
        architecture_layers=[], status="not_run", created_by="u1", created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin", status="active",
        invited_by="u1", invited_at=now, joined_at=now))
    db.versions.create(Version(id=vid, project_id=pid, tag="v1", commit_sha=sha, branch="main",
                               description="", status="draft", docs_count=0, created_by="u1",
                               created_at=now))
    with db._engine.begin() as cx:
        eid = cx.execute(insert(s.entities).values(
            project_id=pid, entity_key="Math|Utils|scale", kind="function",
            qualified_name="scale")).inserted_primary_key[0]
        cx.execute(insert(s.entity_versions).values(
            version_id=vid, entity_id=eid, file="src/util.cpp", line=3, end_line=8))
    with patch("api.services.settings.get_settings",
               return_value=types.SimpleNamespace(workspaces=workspaces)):
        yield types.SimpleNamespace(pid=pid, vid=vid, sha=sha, workspaces=workspaces)


def _get(client, auth_header, v, fid="Math|Utils|scale"):
    return client.get(f"/api/v1/projects/{v.pid}/versions/{v.vid}/functions/source",
                      params={"function_id": fid}, headers=auth_header)


def test_the_functions_lines_come_from_its_checkout(client, auth_header, version):
    r = _get(client, auth_header, version)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file"] == "src/util.cpp"
    assert (body["start_line"], body["end_line"], body["truncated"]) == (3, 8, False)
    assert body["lines"][0] == "int scale(int a, int b) {" and body["lines"][-1] == "}"
    assert len(body["lines"]) == 6


def test_a_version_whose_code_is_not_here_says_so(client, auth_header, version):
    import shutil
    shutil.rmtree(version.workspaces / version.pid, ignore_errors=True)
    r = _get(client, auth_header, version)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "SOURCE_NOT_HERE"


def test_a_version_without_its_end_line_still_shows_the_body(client, auth_header, version, db):
    """Versions made before the parser stored a function's end have end_line == line: the body is
    found from the code, braces in comments and strings aside."""
    from sqlalchemy import update
    from api.db.postgres import schema as s
    with db._engine.begin() as cx:
        cx.execute(update(s.entity_versions).where(s.entity_versions.c.version_id == version.vid)
                   .values(line=3, end_line=3))
    body = _get(client, auth_header, version).json()
    assert (body["start_line"], body["end_line"]) == (3, 8)
    assert body["lines"][-1] == "}"


def test_the_body_end_skips_braces_in_comments_and_strings():
    from api.services.function_source import _body_end
    code = ["int f(int a) {", "  // a { in a comment", "  const char* s = \"}\";", "  if (a) { a++; }",
            "  return a;", "}", "int g();"]
    assert _body_end(code, 1) == 6
    assert _body_end(code, 7) == 7, "a declaration has no body"


def test_an_unknown_function_is_404(client, auth_header, version):
    assert _get(client, auth_header, version, fid="Math|Utils|nope").status_code == 404
