"""`tools/create_users.py`: accounts for development and demos, added to a project in one go."""
import dataclasses
import os
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import create_users  # noqa: E402


@pytest.fixture
def sql_db(db):
    if not hasattr(db, "_engine"):
        pytest.skip("the tool writes through the SQL backend")
    return db


@pytest.fixture
def project(sql_db):
    pid = "pcu" + uuid.uuid4().hex[:6]
    sql_db.projects.create(dataclasses.replace(sql_db.projects.get("p1"), id=pid, name=pid))
    return pid


def _signin(client, email, password):
    return client.post("/api/v1/auth/signin", json={"email": email, "password": password}).status_code


def test_the_demo_team_is_created_added_and_can_sign_in(client, sql_db, project, capsys):
    assert create_users.main(["--project-id", project]) == 0          # no --file/--email: the default team
    out = capsys.readouterr().out
    assert "dev5@aspice.dev" in out and "password: demo1234" in out
    members = {m.user_id: m for m in sql_db.members.list_members(project)}
    admin = sql_db.users.get_by_email("admin@aspice.dev")
    dev1 = sql_db.users.get_by_email("dev1@aspice.dev")
    assert members[admin.id].role == "admin" and members[dev1.id].role == "developer"
    assert len(members) == 6 and all(m.status == "active" for m in members.values())
    assert _signin(client, "dev1@aspice.dev", "demo1234") == 200

    # again: nobody twice, no password changed, memberships unchanged
    assert create_users.main(["--demo", "--project-id", project]) == 0
    assert "exists" in capsys.readouterr().out
    assert len([u for u in sql_db.users.search("dev1@aspice")]) == 1


def test_a_csv_with_roles_and_a_reset(client, sql_db, project, tmp_path, capsys):
    tag = uuid.uuid4().hex[:6]
    f = tmp_path / "team.csv"
    f.write_text("email,name,password,role\n"
                 f"dev.{tag}@x.dev,Dev One,first-pass,\n"
                 f"rev.{tag}@x.dev,,,reviewer\n", encoding="utf-8")
    assert create_users.main(["--file", str(f), "--project-id", project]) == 0
    out = capsys.readouterr().out
    assert "password: first-pass" in out
    rev = sql_db.users.get_by_email(f"rev.{tag}@x.dev")
    assert rev.name == "Rev %s" % tag.capitalize()                      # from the address
    assert sql_db.members.get_member(project, rev.id).role == "reviewer"
    assert _signin(client, f"dev.{tag}@x.dev", "first-pass") == 200

    assert create_users.main(["--email", f"dev.{tag}@x.dev", "--reset", "--password", "second-pass"]) == 0
    assert _signin(client, f"dev.{tag}@x.dev", "second-pass") == 200


def test_a_project_that_does_not_exist_is_refused(sql_db, capsys):
    assert create_users.main(["--demo", "--project-id", "no-such-project"]) == 2
