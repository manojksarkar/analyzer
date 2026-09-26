"""How long a sign-in lasts, and where that is set.

The access token lived 15 minutes. That cost the web app nothing -- it renews with its refresh
token on a 401 -- but anyone testing through Swagger had to sign in and re-paste the token every
quarter of an hour ("401 Signature has expired"). It lasts a working day now, and is a machine
setting: `auth.accessTokenMinutes` in engine/config/config.local.json.
"""
import datetime
import json
import os
import shutil
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import HTTPException  # noqa: E402
from jose import jwt  # noqa: E402

from api.middleware import auth as A  # noqa: E402

UTC = datetime.timezone.utc


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    """config.local.json pointed at a scratch file. Returns a function that writes it.

    The MODULE, fetched by name: `core` re-exports a function called `paths`, which hides the
    submodule of the same name from `import core.paths`."""
    import importlib
    paths_module = importlib.import_module("core.paths")
    path = tmp_path / "config.local.json"
    monkeypatch.setattr(paths_module, "paths",
                        lambda *a, **k: SimpleNamespace(config_local_path=str(path)))
    return lambda text: path.write_text(text, encoding="utf-8")


class TestWhereTheLifetimeComesFrom:
    def test_the_default_is_a_working_day(self, local_config):
        assert A.DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES == 8 * 60
        assert A._configured_access_token_minutes() == 8 * 60      # no config.local.json at all

    def test_a_file_without_the_section_keeps_the_default(self, local_config):
        local_config('{"db": {"url": "sqlite:///x.db"}}')
        assert A._configured_access_token_minutes() == 8 * 60

    def test_the_setting_is_honoured(self, local_config):
        local_config('{"auth": {"accessTokenMinutes": 720}}')
        assert A._configured_access_token_minutes() == 720

    def test_the_file_may_carry_comments_and_trailing_commas(self, local_config):
        """config.local.json is written by hand, like the example it is copied from."""
        local_config('{\n  // a whole shift\n  "auth": {"accessTokenMinutes": 600,},\n}\n')
        assert A._configured_access_token_minutes() == 600

    @pytest.mark.parametrize("bad", ['"8h"', "0", "-5", "true", "3.5"])
    def test_a_bad_value_is_reported_and_ignored(self, local_config, capsys, bad):
        local_config('{"auth": {"accessTokenMinutes": %s}}' % bad)
        assert A._configured_access_token_minutes() == 8 * 60
        assert "positive whole number" in capsys.readouterr().err

    def test_an_unreadable_file_never_breaks_sign_in(self, local_config, capsys):
        local_config('{"auth": {"accessTokenMinutes": 720')           # truncated
        assert A._configured_access_token_minutes() == 8 * 60
        assert "could not read" in capsys.readouterr().err


class TestTheTokensThemselves:
    def test_a_new_token_lasts_the_configured_time(self):
        claims = jwt.get_unverified_claims(A.create_access_token("u1"))
        left = claims["exp"] - datetime.datetime.now(UTC).timestamp()
        assert abs(left - A.ACCESS_TOKEN_EXPIRE_MINUTES * 60) < 60

    def test_sign_in_hands_out_such_a_token(self, client):
        r = client.post("/api/v1/auth/signin",
                        json={"email": "alice@aspice.dev", "password": "secret"})
        assert r.status_code == 200, r.text
        claims = jwt.get_unverified_claims(r.json()["access_token"])
        left = claims["exp"] - datetime.datetime.now(UTC).timestamp()
        assert left > 60 * 60, "a sign-in should outlast an hour of testing"

    def test_an_expired_token_is_still_refused(self):
        """Longer is not never: expiry must still be enforced."""
        past = datetime.datetime.now(UTC) - datetime.timedelta(minutes=1)
        token = jwt.encode({"sub": "u1", "exp": past, "type": "access"},
                           A.SECRET_KEY, algorithm=A.ALGORITHM)
        with pytest.raises(HTTPException) as exc:
            A.decode_token(token)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail["message"].lower()


def test_the_api_setting_stays_out_of_project_configs(tmp_path, monkeypatch):
    """The runner copies config.local.json into each project's runtime config, minus `db`.
    `auth` is the API server's own setting too -- no engine reads it -- so it is left out."""
    from api.services import pipeline_runner as pr
    cfg_dir = tmp_path / "engine" / "config"
    cfg_dir.mkdir(parents=True)
    shutil.copy(os.path.join(PROJECT_ROOT, "engine", "config", "config.defaults.json"), cfg_dir)
    (cfg_dir / "config.local.json").write_text(
        '{"auth": {"accessTokenMinutes": 720}, "llm": {"baseUrl": "http://gateway.test"}}',
        encoding="utf-8")
    monkeypatch.setattr(pr, "get_settings", lambda: SimpleNamespace(repo_root=tmp_path))
    project = SimpleNamespace(build_config={},
                              architecture_layers=[{"name": "L1", "groups": ["G1"]}])
    path, _ = pr._write_project_config(project, tmp_path / "ws")
    cfg = json.loads(open(path, encoding="utf-8").read())
    assert "auth" not in cfg
    assert cfg["llm"]["baseUrl"] == "http://gateway.test"      # the rest still comes through
