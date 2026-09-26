"""The sample Swagger request bodies in engine/config stay usable.

`api_create_project.sample_full.example.json` (POST /api/v1/projects) and
`api_start_job.sample_full.example.json` (POST /api/v1/projects/{id}/jobs) run SampleCppProject's
"Full" group through the API the way `analyzer.py generate --scope group:Full` runs it with
config.defaults.json. They only help while they match the code, so this pins them to it: a change
to the default layers, or to either request model, fails here instead of in somebody's test run.

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


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)      # plain JSON, no comments: it is pasted into Swagger as is


def test_both_bodies_are_accepted_by_the_api():
    from api.routes.projects import CreateProjectRequest
    from api.routes.jobs import StartJobRequest
    CreateProjectRequest(**_load(PROJECT))
    StartJobRequest(**_load(JOB))


def test_the_architecture_is_the_default_layers():
    """What the API turns `architecture_layers` into is exactly config.defaults.json's `layers`,
    except `cores`, which the API's format has no field for."""
    from api.services.pipeline_runner import _convert_layers, _load_base_config
    want = copy.deepcopy(_load_base_config(os.path.join(CONFIG_DIR, "config.defaults.json"))
                         ["layers"])
    for layer in want.values():
        layer.pop("cores", None)
    assert _convert_layers(_load(PROJECT)["architecture_layers"]) == want


def test_the_job_scope_names_a_declared_group():
    groups = {g["name"] for layer in _load(PROJECT)["architecture_layers"]
              for g in layer["groups"]}
    scope = _load(JOB)["scope"]
    assert scope["type"] == "group"
    assert set(scope["names"]) <= groups


@pytest.mark.parametrize("folder", sorted({
    f for layer in _load(PROJECT)["architecture_layers"] for g in layer["groups"]
    for c in g["components"] for f in c["files"]}))
def test_every_component_folder_is_in_the_sample(folder):
    assert os.path.isdir(os.path.join(ROOT, "SampleCppProject", folder)), folder


def test_flowcharts_are_switched_on():
    """Off in the shipped defaults; the review feature needs them for label corrections."""
    views = _load(PROJECT)["build_config"]["views"]
    assert views["flowcharts"] is True and views["behaviourDiagram"] is True
