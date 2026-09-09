"""tools/verify_db_rebuild.py — the end-to-end "is this version rebuildable?" gate.

Every piece of the migration has been verified in isolation; this tool checks the promise the
whole thing exists for — that a version's work survives independently of the machine that
produced it. These tests drive it against a real (SQLite) database so the tool itself is
trustworthy: a check that silently passes is worse than no check, which is exactly how the
unwritten `pipeline_status` went unnoticed.
"""
import datetime
import json
import os
import runpy
import sys

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from api.db.postgres import schema as s          # noqa: E402
from incremental.store import PgStore            # noqa: E402

UTC = datetime.timezone.utc
PID = "proj-rebuild"


def _engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(insert(s.projects), {"id": PID, "name": "P",
                                        "created_at": datetime.datetime.now(UTC)})
    return eng


def _version(eng, vid, *, pipeline_status="complete"):
    with eng.begin() as cx:
        cx.execute(insert(s.versions), {
            "id": vid, "project_id": PID, "version": vid, "commit_sha": "a" * 40,
            "branch": "main", "pipeline_status": pipeline_status,
            "created_at": datetime.datetime.now(UTC)})


def _model_dir(tmp_path, name="m"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "functions.json").write_text(json.dumps(
        {"App|Main|calc|int": {"qualifiedName": "calc", "description": "d"}}), encoding="utf-8")
    (d / "hashes.json").write_text(json.dumps({"App|Main|calc|int": "aaa"}), encoding="utf-8")
    (d / "globalVariables.json").write_text(json.dumps({}), encoding="utf-8")
    return str(d)


def _run_tool(monkeypatch, eng, argv):
    """Run the tool against `eng`, capturing its exit code."""
    import core.db as coredb
    monkeypatch.setattr(coredb, "is_database_configured", lambda: True)
    monkeypatch.setattr(coredb, "get_engine", lambda: eng)
    monkeypatch.setattr(sys, "argv", ["verify_db_rebuild.py"] + argv)

    from incremental import store as store_mod
    monkeypatch.setattr(store_mod, "make_store",
                        lambda pid, workspaces_root=None: PgStore(pid, eng,
                                                                  workspaces_root="unused"))
    try:
        runpy.run_path(os.path.join(ROOT, "tools", "verify_db_rebuild.py"),
                       run_name="__main__")
        return 0
    except SystemExit as e:
        return e.code or 0


class TestVerifyDbRebuild:
    def test_passes_for_a_complete_version(self, tmp_path, monkeypatch, capsys):
        eng = _engine()
        _version(eng, "v1")
        store = PgStore(PID, eng, workspaces_root="unused")
        store.write_model("v1", _model_dir(tmp_path))
        with eng.begin() as cx:
            cx.execute(insert(s.version_output_files), {
                "version_id": "v1", "rel_path": "App/interface_tables.json",
                "content": "{}", "group_name": "App"})

        assert _run_tool(monkeypatch, eng, ["v1"]) == 0
        assert "OK" in capsys.readouterr().out

    def test_catches_a_version_stranded_mid_phase(self, tmp_path, monkeypatch, capsys):
        """The exact failure that caused 0% reuse: a finished run left at 'exporting' is
        never offered as a baseline, and nothing surfaced that."""
        eng = _engine()
        _version(eng, "v1", pipeline_status="exporting")
        PgStore(PID, eng, workspaces_root="unused").write_model("v1", _model_dir(tmp_path))
        with eng.begin() as cx:
            cx.execute(insert(s.version_output_files), {
                "version_id": "v1", "rel_path": "App/x.json", "content": "{}",
                "group_name": "App"})

        assert _run_tool(monkeypatch, eng, ["v1"]) == 1
        out = capsys.readouterr().out
        assert "not baseline-eligible" in out

    def test_catches_an_empty_model(self, tmp_path, monkeypatch, capsys):
        """A version whose model did not round-trip would produce an empty document."""
        eng = _engine()
        _version(eng, "v1")
        empty = tmp_path / "empty"; empty.mkdir()
        (empty / "functions.json").write_text("{}", encoding="utf-8")
        (empty / "hashes.json").write_text("{}", encoding="utf-8")
        PgStore(PID, eng, workspaces_root="unused").write_model("v1", str(empty))

        assert _run_tool(monkeypatch, eng, ["v1"]) == 1
        out = capsys.readouterr().out
        assert "no functions" in out and "no hashes" in out

    def test_catches_missing_view_outputs(self, tmp_path, monkeypatch, capsys):
        """Without stored views the rendered document silently falls back to local disk."""
        eng = _engine()
        _version(eng, "v1")
        PgStore(PID, eng, workspaces_root="unused").write_model("v1", _model_dir(tmp_path))

        assert _run_tool(monkeypatch, eng, ["v1"]) == 1
        assert "no view outputs stored" in capsys.readouterr().out

    def test_reports_missing_version(self, monkeypatch, capsys):
        eng = _engine()
        assert _run_tool(monkeypatch, eng, ["nope"]) == 1
        assert "no version" in capsys.readouterr().out

    def test_no_database_is_not_a_failure(self, monkeypatch, capsys):
        """A DB-less deployment has nothing to verify — that must not read as broken."""
        import core.db as coredb
        monkeypatch.setattr(coredb, "is_database_configured", lambda: False)
        monkeypatch.setattr(sys, "argv", ["verify_db_rebuild.py"])
        try:
            runpy.run_path(os.path.join(ROOT, "tools", "verify_db_rebuild.py"),
                           run_name="__main__")
            code = 0
        except SystemExit as e:
            code = e.code or 0
        assert code == 0
        assert "nothing to verify" in capsys.readouterr().out
