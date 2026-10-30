"""Deleting a project leaves nothing of it behind, and never pulls it from under a running job.

The rows went (they cascade from `projects`), but `job_functions` has no foreign key and kept
every function of every run, and `workspaces/<project_id>/` -- a checkout per commit plus every
version's documents and diagrams -- stayed on disk.
"""
import datetime
import types
import uuid
from unittest.mock import patch

import pytest

from api.models.domain import AnalysisJob, AnalysisPhase, Project, ProjectMember


def _project(db):
    pid = "pdel" + uuid.uuid4().hex[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config={}, architecture_layers=[], status="not_run", created_by="u1",
        created_at=now, updated_at=now))
    db.members.add_member(ProjectMember(
        id="m" + uuid.uuid4().hex[:8], project_id=pid, user_id="u1", role="admin",
        status="active", invited_by="u1", invited_at=now, joined_at=now))
    return pid


def _settings(root):
    return types.SimpleNamespace(workspaces=root)


def test_the_workspace_folder_goes_with_the_project(db, client, auth_header, tmp_path):
    pid = _project(db)
    ws = tmp_path / pid
    (ws / "0123456789abcdef" / ".git").mkdir(parents=True)
    pack = ws / "0123456789abcdef" / ".git" / "pack"
    pack.write_bytes(b"x")
    pack.chmod(0o444)                                  # git keeps its packs read-only
    (tmp_path / "another-project").mkdir()

    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)

    assert r.status_code == 204, r.text
    assert not ws.exists()
    assert (tmp_path / "another-project").is_dir(), "only that project's folder is removed"


def test_its_job_functions_rows_go_too(db, client, auth_header, tmp_path):
    if not hasattr(db, "_engine"):
        pytest.skip("job_functions is a SQL table")
    from sqlalchemy import insert, select, func
    from api.db.postgres import schema as s
    pid = _project(db)
    with db._engine.begin() as cx:
        cx.execute(insert(s.job_functions), [{"id": "f" + uuid.uuid4().hex[:8], "job_id": "jobx",
                                              "project_id": pid, "name": "fn", "is_visible": True}])

    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)

    assert r.status_code == 204, r.text
    with db._engine.connect() as cx:
        left = cx.execute(select(func.count()).select_from(s.job_functions)
                          .where(s.job_functions.c.project_id == pid)).scalar()
    assert left == 0


def _value(col, now):
    """A value of the column's type, for a NOT NULL column with no default."""
    try:
        t = col.type.python_type
    except NotImplementedError:
        return "x"
    return {str: "x", int: 0, bool: False, float: 0.0, dict: {}, list: [], bytes: b"x",
            datetime.datetime: now, datetime.date: now.date()}.get(t, "x")


def _fill_every_table(engine, pid):
    """One row in every table that hangs off the project -- through a foreign key, or a
    `project_id` / `version_id` column without one -- taken from the schema, so a table added later
    is filled (and checked) without editing this test. Returns ({table: primary key of its row},
    [tables no row could be made for], the project's version ids)."""
    from sqlalchemy import UniqueConstraint, insert, select
    from api.db.postgres import schema as s
    now = datetime.datetime.now(datetime.timezone.utc)
    owned, made, unfilled = {"projects"}, {}, []
    for t in s.metadata.sorted_tables:                       # parents before children
        cols = {c.name for c in t.columns}
        if t.name != "projects" and ({fk.column.table.name for fk in t.foreign_keys} & owned
                                     or cols & {"project_id", "version_id"}):
            owned.add(t.name)
    made["projects"] = {"id": pid}
    versions = []
    for t in s.metadata.sorted_tables:
        if t.name not in owned or t.name == "projects":
            continue
        # Columns of a unique rule (one name per project, ...): a fresh value each row.
        uniq = {c.name for k in t.constraints if isinstance(k, UniqueConstraint) for c in k.columns}
        uniq |= {c.name for i in t.indexes if i.unique for c in i.columns}
        for _ in range(2 if t.name == "versions" else 1):    # two versions: one the other's baseline
            row, ok = {}, True
            for c in t.columns:
                fk = next(iter(c.foreign_keys), None)
                if fk is not None:
                    ref = fk.column.table.name
                    if ref == t.name:                            # versions.baseline_version_id
                        row[c.name] = versions[0] if versions else None
                    elif ref in made:
                        row[c.name] = made[ref].get(fk.column.name)
                    else:
                        with engine.connect() as cx:
                            row[c.name] = cx.execute(select(fk.column).limit(1)).scalar()
                    if row[c.name] is None and not c.nullable:
                        ok = False
                elif c.name == "project_id":
                    row[c.name] = pid
                elif c.name == "version_id":
                    row[c.name] = versions[0] if versions else None
                elif c.primary_key or c.unique or (c.name in uniq and _value(c, now) == "x"):
                    if c.autoincrement is True or (c.primary_key and _value(c, now) == 0):
                        continue
                    row[c.name] = "t" + uuid.uuid4().hex[:12]
                elif not c.nullable and c.default is None and c.server_default is None:
                    row[c.name] = _value(c, now)
            if not ok:
                unfilled.append(t.name)
                break
            try:
                with engine.begin() as cx:
                    res = cx.execute(insert(t).values(**row))
                    pk = {c.name: (row.get(c.name) if c.name in row else res.inserted_primary_key[i])
                          for i, c in enumerate(t.primary_key.columns)}
            except Exception as exc:                       # noqa: BLE001 - reported below
                # The project already has its row here (its creator's membership): use that one.
                have = None
                if "project_id" in t.c:
                    with engine.connect() as cx:
                        have = cx.execute(select(t).where(t.c.project_id == pid).limit(1)).first()
                if have is None:
                    unfilled.append(f"{t.name}: {type(exc).__name__}: {str(exc).splitlines()[0][:120]}")
                    break
                row, pk = dict(have._mapping), {}
            made[t.name] = {**row, **pk}
            if t.name == "versions":
                versions.append(row["id"])
    return made, unfilled, versions


def test_every_row_of_the_project_goes(db, client, auth_header, tmp_path):
    """NW-4: a row in EVERY table that hangs off the project -- versions, the model, view output,
    documents, corrections, reviews, jobs, notifications ... -- and none is left after the delete."""
    if not hasattr(db, "_engine"):
        pytest.skip("the tables are the SQL backend's")
    from sqlalchemy import select, func
    from api.db.postgres import schema as s
    pid = _project(db)
    made, unfilled, versions = _fill_every_table(db._engine, pid)
    assert not unfilled, f"no row could be made for: {unfilled}"
    assert len(made) > 30, sorted(made)

    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)), \
            patch("api.routes.projects._runs_root", return_value=tmp_path / "runs"):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)
    assert r.status_code == 204, r.text

    left = []
    with db._engine.connect() as cx:
        for name, row in made.items():
            t = s.metadata.tables[name]
            where = [t.c[k] == v for k, v in row.items() if k in {c.name for c in t.primary_key.columns}]
            if where and cx.execute(select(func.count()).select_from(t).where(*where)).scalar():
                left.append(name)
        for t in s.metadata.sorted_tables:                 # and nothing else names the project
            for col, ids in (("project_id", [pid]), ("version_id", versions)):
                if col in t.c and ids and cx.execute(select(func.count()).select_from(t)
                                                     .where(t.c[col].in_(ids))).scalar():
                    left.append(f"{t.name}.{col}")
    assert not left, f"left behind: {sorted(set(left))}"


def test_the_versions_run_folders_go_and_never_what_they_link_to(db, client, auth_header, tmp_path):
    """`runs/<version id>/<stamp>/code` is a frozen copy of the code; its `node_modules` is a
    link to the installation's own. The folder goes with the project; the link's target stays."""
    if not hasattr(db, "_engine"):
        pytest.skip("versions are listed from the SQL backend here")
    pid = _project(db)
    _made, _unfilled, versions = _fill_every_table(db._engine, pid)
    real = tmp_path / "installation" / "node_modules"
    (real / "pkg").mkdir(parents=True)
    (real / "pkg" / "index.js").write_text("x")
    runs = tmp_path / "runs"
    for vid in versions:
        code = runs / vid / "20261031-090000" / "code"
        code.mkdir(parents=True)
        (code / "run.py").write_text("x")
        link = code / "node_modules"
        try:
            import _winapi
            _winapi.CreateJunction(str(real), str(link))
        except ImportError:
            link.symlink_to(real, target_is_directory=True)
    (runs / "another-version").mkdir()

    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path / "ws")), \
            patch("api.routes.projects._runs_root", return_value=runs):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)

    assert r.status_code == 204, r.text
    assert versions and not any((runs / v).exists() for v in versions)
    assert (real / "pkg" / "index.js").read_text() == "x", "the link's target is untouched"
    assert (runs / "another-version").is_dir(), "only the project's versions' folders go"


def test_a_project_with_a_live_run_is_not_deleted(db, client, auth_header, tmp_path):
    pid = _project(db)
    now = datetime.datetime.now(datetime.timezone.utc)
    db.jobs.create(AnalysisJob(
        id="job" + uuid.uuid4().hex[:8], project_id=pid, commit_sha="0" * 40, version_id=None,
        reference_version_id=None, status="running", pause_after_phase1=False, layer_filter=None,
        phase=2, phase_pct=0, current_activity="", activity_detail="", elapsed_seconds=0,
        eta_seconds=None, phases=[AnalysisPhase(2, "Derive Model", "running", None)],
        started_at=now, completed_at=None, error_message=None))

    with patch("api.services.pipeline_runner.job_alive", return_value=True):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "JOB_RUNNING"
    assert db.projects.get(pid) is not None

    # The same row left behind by a server that stopped mid-run blocks nothing.
    with patch("api.services.settings.get_settings", return_value=_settings(tmp_path)):
        r = client.delete(f"/api/v1/projects/{pid}", headers=auth_header)
    assert r.status_code == 204, r.text
