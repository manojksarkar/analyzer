"""The sample Swagger request bodies in engine/config stay usable.

`api_create_project.sample_full.example.json` (POST /api/v1/projects) and
`api_start_job.sample_full.example.json` (POST /api/v1/projects/{id}/jobs) run SampleCppProject's
"Full" group through the API the way `analyzer.py generate --scope group:Layer1.Full` runs it with
config.defaults.json; `api_start_job.sample_core.example.json` runs component Layer1.Sample Core of
the same project. They only help while they match the code, so this pins them to it: a change to
the default layers, to either request model or to the scope check, fails here instead of in
somebody's test run.

Every scope names its group or component by the LAYER-QUALIFIED id. The sample's two layers both
have a group `My Sample` holding a component `Sample Core`, so the bare names are ambiguous, and
`POST /jobs` refuses them (400 INVALID_SCOPE).

Before use, replace `repo_url` with a git repository of SampleCppProject (the folder inside this
repo is not one) and `commit_sha` with a commit in it.
"""
import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

CONFIG_DIR = os.path.join(ROOT, "engine", "config")
PROJECT = os.path.join(CONFIG_DIR, "api_create_project.sample_full.example.json")
JOB = os.path.join(CONFIG_DIR, "api_start_job.sample_full.example.json")
CORE_JOB = os.path.join(CONFIG_DIR, "api_start_job.sample_core.example.json")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)      # plain JSON, no comments: it is pasted into Swagger as is


def test_both_bodies_are_accepted_by_the_api():
    from api.routes.projects import CreateProjectRequest
    from api.routes.jobs import StartJobRequest
    CreateProjectRequest(**_load(PROJECT))
    StartJobRequest(**_load(JOB))
    StartJobRequest(**_load(CORE_JOB))


def test_the_architecture_is_the_default_layers():
    """What the API turns `architecture_layers` into is exactly config.defaults.json's `layers`,
    except `cores`, which the API's format has no field for."""
    from api.services.pipeline_runner import _convert_layers, _load_base_config
    want = copy.deepcopy(_load_base_config(os.path.join(CONFIG_DIR, "config.defaults.json"))
                         ["layers"])
    for layer in want.values():
        layer.pop("cores", None)
    assert _convert_layers(_load(PROJECT)["architecture_layers"]) == want


def test_the_job_scope_names_a_declared_group_by_its_layer():
    groups = {"%s.%s" % (layer["name"], g["name"])
              for layer in _load(PROJECT)["architecture_layers"] for g in layer["groups"]}
    scope = _load(JOB)["scope"]
    assert scope == {"type": "group", "names": ["Layer1.Full"]}
    assert set(scope["names"]) <= groups


def test_the_core_job_names_the_component_by_its_layer():
    """Layer2 has a `Sample Core` too: the bare name is what the user sent, and was refused."""
    scope = _load(CORE_JOB)["scope"]
    assert scope == {"type": "component", "names": ["Layer1.Sample Core"]}


@pytest.mark.parametrize("job,project", [
    ("api_start_job.sample_full.example.json", "api_create_project.sample_full.example.json"),
    ("api_start_job.sample_core.example.json", "api_create_project.sample_full.example.json"),
    ("api_start_job.sample_behaviour.example.json",
     "api_create_project.sample_behaviour.example.json"),
])
def test_every_example_job_passes_the_scope_check(job, project):
    """What POST /jobs asks before it reserves anything (`pipeline_runner.scope_problem`)."""
    from api.services.pipeline_runner import scope_problem
    layers = _load(os.path.join(CONFIG_DIR, project))["architecture_layers"]
    assert scope_problem(layers, _load(os.path.join(CONFIG_DIR, job))["scope"]) is None


def test_every_example_job_body_is_listed_here():
    """A new example is paired with its project above, or it is never checked."""
    listed = {"api_start_job.sample_full.example.json", "api_start_job.sample_core.example.json",
              "api_start_job.sample_behaviour.example.json"}
    assert {f for f in os.listdir(CONFIG_DIR) if f.startswith("api_start_job.")} == listed


@pytest.mark.parametrize("folder", sorted({
    f for layer in _load(PROJECT)["architecture_layers"] for g in layer["groups"]
    for c in g["components"] for f in c["files"]}))
def test_every_component_folder_is_in_the_sample(folder):
    assert os.path.isdir(os.path.join(ROOT, "SampleCppProject", folder)), folder


def test_flowcharts_are_switched_on():
    """Off in the shipped defaults; the review feature needs them for label corrections."""
    views = _load(PROJECT)["build_config"]["views"]
    assert views["flowcharts"] is True and views["behaviourDiagram"] is True


# ---------------------------------------------------------------------------
# The Dynamic Behaviour pair: the "Full" group draws no behaviour row on the sample -- develop's
# default filter (`skip_within_unit`) wants a call chain across two units of ONE component, and
# only Sample Core's CoreGateway has one (2 rows, in group Layer1.My Sample) -- so a behaviour
# correction (R6) cannot be tried there. This pair runs group Layer1.My Sample with one diagram
# per external caller: the 2 gateway rows and every other external call besides.
# ---------------------------------------------------------------------------
BEH_PROJECT = os.path.join(CONFIG_DIR, "api_create_project.sample_behaviour.example.json")
BEH_JOB = os.path.join(CONFIG_DIR, "api_start_job.sample_behaviour.example.json")


def test_the_behaviour_bodies_are_accepted_by_the_api():
    from api.routes.projects import CreateProjectRequest
    from api.routes.jobs import StartJobRequest
    CreateProjectRequest(**_load(BEH_PROJECT))
    StartJobRequest(**_load(BEH_JOB))


def test_the_behaviour_project_is_the_full_one_but_for_its_views():
    """Same layers -- so the default-layers check above covers it too -- and a different name, so
    both can live in one database."""
    full, beh = _load(PROJECT), _load(BEH_PROJECT)
    assert beh["architecture_layers"] == full["architecture_layers"]
    assert beh["name"] != full["name"]


def test_the_behaviour_project_draws_a_row_per_caller():
    views = _load(BEH_PROJECT)["build_config"]["views"]
    assert views["behaviourDiagram"] is True and views["flowcharts"] is True
    assert views["sequenceDiagrams"]["filterMode"] == "all_callers"


def test_the_behaviour_job_names_the_group_by_its_layer():
    """`My Sample` is a group in Layer1 AND Layer2, so the bare name is ambiguous; the layer-
    qualified id is what the planner resolves."""
    qualified = {"%s.%s" % (layer["name"], g["name"])
                 for layer in _load(BEH_PROJECT)["architecture_layers"] for g in layer["groups"]}
    scope = _load(BEH_JOB)["scope"]
    assert scope == {"type": "group", "names": ["Layer1.My Sample"]}
    assert set(scope["names"]) <= qualified
