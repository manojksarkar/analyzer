"""Adding someone to a project: a person with no account, an old pending invite, a member.

All three were a 500 on the database backend once: an unknown address was stored under a made-up
user id that the `users` foreign key refused, and a second invite for the same person added a second
row for a (project, user) pair that is unique. Then an unknown address was refused (nothing created
accounts) and an invite stayed `pending` for ever (nothing activated it), so a new person could not be
added at all. Now an invite makes an active member, creating the account when there is none.
"""
import uuid

from api.models.domain import ProjectMember

P = "/api/v1/projects/p2"          # alice (admin) and eve (developer); carol is not a member


def _pending(client, auth_header):
    r = client.get(f"{P}/members/pending", headers=auth_header)
    assert r.status_code == 200, r.text
    return r.json()["pending"]


def _members(client, auth_header):
    r = client.get(f"{P}/members", headers=auth_header)
    assert r.status_code == 200, r.text
    return r.json()["members"]


class TestInvite:
    def test_an_address_without_an_account_gets_one_and_can_sign_in(self, client, auth_header):
        email = "new.person.%s@aspice.dev" % uuid.uuid4().hex[:6]
        r = client.post(f"{P}/members/invite", headers=auth_header,
                        json={"email": email.upper(), "role": "developer"})
        assert r.status_code == 201, r.text
        body = r.json()
        temp = body["account"]["temporary_password"]
        assert body["account"]["created"] is True and len(temp) == 12
        assert body["invite"]["status"] == "active" and body["invite"]["email"] == email
        assert body["member"]["name"].startswith("New Person")
        assert email in {m["email"] for m in _members(client, auth_header)}     # active at once
        assert email not in {m["email"] for m in _pending(client, auth_header)}

        # the temporary password signs in -- the address in any case -- and is changed
        r = client.post("/api/v1/auth/signin", json={"email": email.title(), "password": temp})
        assert r.status_code == 200, r.text
        h = {"Authorization": "Bearer " + r.json()["access_token"]}
        r = client.post("/api/v1/auth/change-password", headers=h,
                        json={"current_password": "wrong", "new_password": "a-new-secret"})
        assert r.status_code == 403
        r = client.post("/api/v1/auth/change-password", headers=h,
                        json={"current_password": temp, "new_password": "short"})
        assert r.status_code == 422
        r = client.post("/api/v1/auth/change-password", headers=h,
                        json={"current_password": temp, "new_password": "a-new-secret"})
        assert r.status_code == 200, r.text
        assert client.post("/api/v1/auth/signin", json={"email": email, "password": temp}).status_code == 401
        assert client.post("/api/v1/auth/signin",
                           json={"email": email, "password": "a-new-secret"}).status_code == 200

    def test_an_existing_account_is_added_without_a_password(self, client, auth_header, db):
        r = client.post(f"{P}/members/invite", headers=auth_header,
                        json={"email": "carol@aspice.dev", "role": "developer"})
        assert r.status_code == 201, r.text
        try:
            assert r.json()["account"] == {"created": False, "temporary_password": None}
            assert "carol@aspice.dev" in {m["email"] for m in _members(client, auth_header)}
        finally:
            client.delete(f"{P}/members/u3", headers=auth_header)

    def test_an_address_that_is_not_one_is_refused(self, client, auth_header):
        r = client.post(f"{P}/members/invite", headers=auth_header,
                        json={"email": "not-an-address", "role": "developer"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_EMAIL"

    def test_a_member_is_not_invited_again(self, client, auth_header):
        r = client.post(f"{P}/members/invite", headers=auth_header,
                        json={"email": "eve@aspice.dev", "role": "developer"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "ALREADY_MEMBER"

    def test_an_old_pending_invite_becomes_the_active_membership(self, client, auth_header, db):
        # what an invite used to leave behind: a pending row nothing would ever activate
        db.members.add_member(ProjectMember("m" + uuid.uuid4().hex[:8], "p2", "u3", "developer",
                                            "pending", "u1", None, None))
        try:
            assert [m["email"] for m in _pending(client, auth_header)].count("carol@aspice.dev") == 1
            r = client.post(f"{P}/members/invite", headers=auth_header,
                            json={"email": "carol@aspice.dev", "role": "admin"})
            assert r.status_code == 201, r.text
            assert not [m for m in _pending(client, auth_header) if m["email"] == "carol@aspice.dev"]
            carol = [m for m in _members(client, auth_header) if m["email"] == "carol@aspice.dev"]
            assert len(carol) == 1 and carol[0]["role"] == "admin" and carol[0]["name"] == "Carol Schmidt"
        finally:
            client.delete(f"{P}/members/u3", headers=auth_header)
