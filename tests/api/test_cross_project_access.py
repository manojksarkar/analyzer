"""An admin of one project cannot reach into another through ids in its own paths.

Every route checks that the caller administers the project in the PATH; three then acted on a row
by id without checking that it belonged to that project. Anyone can create a project -- and so
administer one -- so each was a way into every other project: deleting its memberships (admins
included), flipping its functions' visibility, resolving its access requests.
"""
import datetime
import uuid

from api.models.domain import AccessRequest, Function, Project, ProjectMember

P2 = "/api/v1/projects/p2"        # alice administers p2 (seed); she has no role in the victim


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _victim(db):
    """A project alice is not a member of, with an active member and a pending invite."""
    pid = "pvic" + uuid.uuid4().hex[:6]
    db.projects.create(Project(
        id=pid, org_id="org1", name=pid, client="c", compliance_standard="ASPICE_L2",
        repo_url="https://example.invalid/r.git", repo_provider="github", default_branch="main",
        build_config={}, architecture_layers=[], status="not_run", created_by="u2",
        created_at=_now(), updated_at=_now()))
    ids = {}
    for user, status in (("u2", "active"), ("u4", "pending")):
        mid = "m" + uuid.uuid4().hex[:8]
        db.members.add_member(ProjectMember(
            id=mid, project_id=pid, user_id=user, role="admin" if user == "u2" else "developer",
            status=status, invited_by="u2", invited_at=_now(),
            joined_at=_now() if status == "active" else None))
        ids[user] = mid
    return pid, ids


class TestCancelInvite:
    def test_another_projects_memberships_are_out_of_reach(self, db, client, auth_header):
        pid, ids = _victim(db)
        for mid in ids.values():
            r = client.delete(f"{P2}/members/pending/{mid}", headers=auth_header)
            assert r.status_code == 204, r.text
        assert db.members.get_member(pid, "u2") is not None, "its admin is still there"
        assert db.members.get_member(pid, "u4") is not None, "its invite is still there"

    def test_only_a_pending_invite_is_cancelled(self, db, client, auth_header):
        # The pending route never removes an ACTIVE member of the admin's own project either.
        mid = "m" + uuid.uuid4().hex[:8]
        db.members.add_member(ProjectMember(
            id=mid, project_id="p2", user_id="u3", role="developer", status="active",
            invited_by="u1", invited_at=_now(), joined_at=_now()))
        try:
            client.delete(f"{P2}/members/pending/{mid}", headers=auth_header)
            assert db.members.get_member("p2", "u3") is not None
        finally:
            db.members.remove_member("p2", "u3")


class TestBulkVisibility:
    def test_another_projects_functions_are_out_of_reach(self, db, client, auth_header):
        pid, _ = _victim(db)
        fid = "f" + uuid.uuid4().hex[:8]
        db.functions.load_from_pipeline({"job" + uuid.uuid4().hex[:8]: [Function(
            id=fid, project_id=pid, version_id="v", name="secret", file_path="a.cpp",
            layer="L", group="G", is_visible=True, is_new=False, description="")]})

        r = client.patch(f"{P2}/functions", headers=auth_header,
                         json={"function_ids": [fid], "is_visible": False})

        assert r.status_code == 200, r.text
        assert r.json()["updated_count"] == 0
        assert db.functions.get(fid).is_visible is True


class TestAccessRequests:
    def test_another_projects_request_is_not_found(self, db, client, auth_header):
        pid, _ = _victim(db)
        rid = "ar" + uuid.uuid4().hex[:8]
        db.access_reqs.create(AccessRequest(id=rid, project_id=pid, user_id="u3",
                                            requested_at=_now(), status="pending",
                                            resolved_by=None, resolved_at=None))

        r = client.patch(f"{P2}/access-requests/{rid}", headers=auth_header, json={"action": "approve"})

        assert r.status_code == 404, r.text
        assert db.access_reqs.get(rid).status == "pending"
        assert db.members.get_member("p2", "u3") is None, "the requester was not added to p2"

    def test_a_request_is_resolved_once(self, db, client, auth_header):
        rid = "ar" + uuid.uuid4().hex[:8]
        db.access_reqs.create(AccessRequest(id=rid, project_id="p2", user_id="u3",
                                            requested_at=_now(), status="pending",
                                            resolved_by=None, resolved_at=None))
        try:
            first = client.patch(f"{P2}/access-requests/{rid}", headers=auth_header, json={"action": "approve"})
            assert first.status_code == 200, first.text
            again = client.patch(f"{P2}/access-requests/{rid}", headers=auth_header, json={"action": "approve"})
            assert again.status_code == 409, again.text
            assert again.json()["detail"]["code"] == "ACCESS_REQUEST_RESOLVED"
        finally:
            db.members.remove_member("p2", "u3")
