"""Inviting someone to a project: an unknown address, a repeat invite and a member.

All three were a 500 on the database backend. An unknown address was stored under a made-up user
id that the `users` foreign key refused, and a second invite for the same person -- the Team
page's "Resend" -- added a second row for a (project, user) pair that is unique.
"""

P = "/api/v1/projects/p2"          # alice (admin) and eve (developer); carol is not a member


def _pending(client, auth_header):
    r = client.get(f"{P}/members/pending", headers=auth_header)
    assert r.status_code == 200, r.text
    return r.json()["pending"]


class TestInvite:
    def test_an_address_without_an_account_is_refused_with_a_reason(self, client, auth_header):
        r = client.post(f"{P}/members/invite", headers=auth_header,
                        json={"email": "nobody.here@aspice.dev", "role": "developer"})
        assert r.status_code == 404, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "USER_NOT_FOUND"
        assert "nobody.here@aspice.dev" in detail["message"]

    def test_a_member_is_not_invited_again(self, client, auth_header):
        r = client.post(f"{P}/members/invite", headers=auth_header,
                        json={"email": "eve@aspice.dev", "role": "developer"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "ALREADY_MEMBER"

    def test_resending_an_invite_keeps_one_pending_row(self, client, auth_header):
        first = client.post(f"{P}/members/invite", headers=auth_header,
                            json={"email": "carol@aspice.dev", "role": "developer"})
        assert first.status_code == 201, first.text
        try:
            again = client.post(f"{P}/members/invite", headers=auth_header,
                                json={"email": "carol@aspice.dev", "role": "admin"})
            assert again.status_code == 201, again.text
            assert again.json()["invite"]["id"] == first.json()["invite"]["id"]
            assert again.json()["invite"]["role"] == "admin"

            carol = [m for m in _pending(client, auth_header) if m["email"] == "carol@aspice.dev"]
            assert len(carol) == 1
            assert carol[0]["role"] == "admin"
            assert carol[0]["name"] == "Carol Schmidt"
        finally:
            client.delete(f"{P}/members/pending/{first.json()['invite']['id']}", headers=auth_header)
        assert not [m for m in _pending(client, auth_header) if m["email"] == "carol@aspice.dev"]
