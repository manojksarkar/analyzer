"""Adding a layer to a version: the component view lists the components of the version's
configuration that its model lacks (`in_model: False`, `layer_parsed: False`), which `export`
can then name; and the `stale` state -- documents older than the model -- is written and listed
(api/services/version_components.py, engine/core/version_run.py). SQL backend over SQLite."""
import datetime
import uuid

import pytest
import sqlalchemy as sa

from api.db.postgres import schema as s

LAYERS = {"Layer1": {"groups": {"G1": {"Math": ["Layer1/Math"], "App": ["Layer1/App"]}}},
          "Layer2": {"groups": {"G2": {"Gpio": ["Layer2/Gpio"], "Uart": ["Layer2/Uart"]}}}}


@pytest.fixture
def sql_db(db):
    if not hasattr(db, "_engine"):
        pytest.skip("rows of the SQL backend")
    return db


@pytest.fixture
def workspaces(tmp_path, monkeypatch):
    """No configuration file of this machine's workspaces reaches the view."""
    from api.services import doc_render
    monkeypatch.setattr(doc_render, "workspaces_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def version(sql_db, workspaces):
    """A version of p1 whose run parsed Layer1 only; its config has Layer1 and Layer2."""
    vid = "verxl" + uuid.uuid4().hex[:6]
    with sql_db._engine.begin() as cx:
        cx.execute(sa.insert(s.versions).values(
            id=vid, project_id="p1", version=vid, commit_sha="c" * 40, status="in_review",
            pipeline_status="complete", resolved_config={"layers": LAYERS},
            created_at=datetime.datetime.now(datetime.timezone.utc)))
        cx.execute(sa.insert(s.model_components), [
            {"version_id": vid, "name": n} for n in ("Layer1.Math", "Layer1.App")])
    return sql_db.versions.get(vid)


def _by_id(view):
    return {c["component"]: c for c in view}


class TestTheConfigsComponents:
    def test_the_config_names_every_component_layer_qualified(self, sql_db, version):
        from api.services.version_components import config_components
        assert config_components(sql_db, version) == [
            "Layer1.App", "Layer1.Math", "Layer2.Gpio", "Layer2.Uart"]

    def test_components_of_a_layer_the_model_lacks_are_listed(self, sql_db, version):
        from api.services.version_components import components_view, counts
        view = components_view(sql_db, version, alive=False)
        assert [c["component"] for c in view] == [
            "Layer1.App", "Layer1.Math", "Layer2.Gpio", "Layer2.Uart"]
        by = _by_id(view)
        assert by["Layer1.Math"]["in_model"] is True and by["Layer1.Math"]["layer_parsed"] is True
        gpio = by["Layer2.Gpio"]
        assert (gpio["in_model"], gpio["layer_parsed"], gpio["state"]) == (
            False, False, "not_requested")
        assert gpio["layer"] == "Layer2" and gpio["name"] == "Gpio" and gpio["documents"] == []
        assert counts(view) == {"not_requested": 4}

    def test_each_component_names_its_group_from_the_version_s_config(self, sql_db, version,
                                                                      workspaces):
        """`group` comes from the version's resolved_config -- not the project's current config
        nor a config file -- spelled as configured; a component it does not name has None."""
        import json
        own = workspaces / "p1" / "versions" / version.id / "config.json"
        own.parent.mkdir(parents=True)
        own.write_text(json.dumps({"layers": {
            "Layer1": {"groups": {"Renamed": {"Math": ["m"], "App": ["a"]}}},
            "Layer2": {"groups": {"Renamed": {"Gpio": ["g"], "Uart": ["u"]}}},
            "Layer9": {"groups": {"N": {"New": ["n"]}}}}}), encoding="utf-8")
        from api.services.version_components import components_view
        by = _by_id(components_view(sql_db, version, alive=False))
        assert {c: v["group"] for c, v in by.items()} == {
            "Layer1.App": "G1", "Layer1.Math": "G1", "Layer2.Gpio": "G2", "Layer2.Uart": "G2",
            "Layer9.New": None}

    def test_a_spaced_name_and_group_keep_their_spelling(self, sql_db, version):
        from api.services.version_components import config_groups
        version.resolved_config = {"layers": {"Layer1": {"groups": {"My Sample": {
            "Sample Core": ["c"]}}}, "Bad": "not a layer"}}
        assert config_groups(version) == {"Layer1.Sample-Core": "My Sample"}
        version.resolved_config = None
        assert config_groups(version) == {}

    def test_a_row_gives_its_state(self, sql_db, version):
        """An export that adds Layer2, cut short before the layer was in: its components wait."""
        from api.services.version_components import components_view
        from core.version_run import mark_components
        mark_components(version.id, ["Layer2.Gpio"], "waiting")
        gpio = _by_id(components_view(sql_db, version, alive=False))["Layer2.Gpio"]
        assert gpio["state"] == "stopped" and gpio["in_model"] is False

    def test_the_version_s_own_config_file_is_read(self, sql_db, version, workspaces):
        import json
        cfg = workspaces / "p1" / "versions" / version.id / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"layers": {"Layer3": {"groups": {"G3": {"Can Bus": ["x"]}}}}}),
                       encoding="utf-8")
        from api.services.version_components import components_view
        can = _by_id(components_view(sql_db, version))["Layer3.Can-Bus"]
        assert can["in_model"] is False and can["name"] == "Can-Bus"

    def test_only_the_config_the_export_runs_with(self, sql_db, version, workspaces):
        """The version's own config.json is what `export` runs with: a layer only the project
        names (added after the version was made) is not offered -- its parse would find nothing."""
        import json
        own = workspaces / "p1" / "versions" / version.id / "config.json"
        own.parent.mkdir(parents=True)
        own.write_text(json.dumps({"layers": {"Layer1": {"groups": {"G": {"Math": ["m"]}}},
                                              "Layer2": {"groups": {"P": {"Gpio": ["g"]}}}}}),
                       encoding="utf-8")
        (workspaces / "p1" / "config.json").write_text(json.dumps({"layers": {
            "Layer1": {"groups": {"G": {"Math": ["m"]}}}, "Layer2": {"groups": {"P": {"Gpio": ["g"]}}},
            "Layer9": {"groups": {"N": {"New": ["n"]}}}}}), encoding="utf-8")
        from api.services.version_components import config_components
        assert config_components(sql_db, version) == ["Layer1.Math", "Layer2.Gpio"]
        own.unlink()                                  # no config of its own: the project's
        assert "Layer9.New" in config_components(sql_db, version)

    def test_a_config_with_comments_and_trailing_commas_is_read(self, sql_db, version,
                                                                 workspaces):
        """The engine accepts them; a plain JSON read returned nothing and offered no layer."""
        own = workspaces / "p1" / "versions" / version.id / "config.json"
        own.parent.mkdir(parents=True)
        own.write_text('{\n  // the run config\n  "layers": {"Layer2": {"groups": {"P": '
                       '{"Gpio": ["g"],}}}},\n}\n', encoding="utf-8")
        from api.services.version_components import config_components
        assert config_components(sql_db, version) == ["Layer2.Gpio"]

    def test_a_config_that_cannot_be_read_leaves_the_view_as_it_was(self, sql_db, version,
                                                                     monkeypatch):
        from api.services import document_registry
        from api.services.version_components import components_view

        def broken(*a, **k):
            raise ValueError("unreadable")
        monkeypatch.setattr(document_registry, "component_dirs", broken)
        assert [c["component"] for c in components_view(sql_db, version)] == [
            "Layer1.App", "Layer1.Math"]

    def test_given_components_replace_the_config(self, sql_db, version):
        from api.services.version_components import components_view
        assert [c["component"] for c in components_view(sql_db, version, all_components=[])] == [
            "Layer1.App", "Layer1.Math"]

    def test_export_can_name_one_and_says_which_layer_it_adds(self, sql_db, version):
        from api.services import version_components as vc
        view = vc.components_view(sql_db, version)
        found, problems = vc.resolve(view, ["Gpio", "Layer1.App"])
        assert found == ["Layer2.Gpio", "Layer1.App"] and problems == []
        todo, skipped = vc.export_targets(view, found)
        assert todo == ["Layer2.Gpio", "Layer1.App"] and skipped == []
        assert vc._staged().layers_to_add(view, todo) == ["Layer2"]


class TestStale:
    def test_stale_is_written_keeping_when_the_documents_were_made(self, sql_db, version):
        from core.version_run import component_rows, mark_components
        mark_components(version.id, ["Layer1.Math"], "generated")
        made = component_rows(version.id)["Layer1.Math"]["finished_at"]
        mark_components(version.id, ["Layer1.Math"], "stale")
        row = component_rows(version.id)["Layer1.Math"]
        assert row["state"] == "stale" and row["finished_at"] == made and not row["error"]

    def test_stale_is_listed_and_counted(self, sql_db, version):
        from api.services.version_components import components_view, counts, default_reexport
        from core.version_run import generated_components, mark_components
        mark_components(version.id, ["Layer1.Math"], "stale")
        view = components_view(sql_db, version, alive=False)
        assert _by_id(view)["Layer1.Math"]["state"] == "stale"
        assert counts(view)["stale"] == 1
        assert default_reexport(view) == ["Layer1.Math"]
        assert generated_components(version.id) == ["Layer1.Math"]

    def test_a_reexport_clears_it(self, sql_db, version):
        """run.py marks what it makes waiting -> generating -> generated."""
        from api.services.version_components import components_view
        from core.version_run import mark_components
        mark_components(version.id, ["Layer1.Math"], "stale")
        for state in ("waiting", "generating", "generated"):
            mark_components(version.id, ["Layer1.Math"], state)
        assert _by_id(components_view(sql_db, version))["Layer1.Math"]["state"] == "generated"
