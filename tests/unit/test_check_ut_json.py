"""Unit tests for `tools/check_ut_json.py`.

The templates under docs/spec/ut_templates/ ARE the schema, so these tests run against
the real templates: each must pass its own check, and each way a file goes wrong is
planted into a copy of one and must be named. A template change that breaks a test
here changed what the check enforces -- look at the template before the test.
"""
import copy
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(PROJECT_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import check_ut_json as T  # noqa: E402  (tools/ must be on sys.path first)


def _template(name):
    return T.load(T.template_path(name))


def _found(out):
    """{(severity, kind, schema path)} -- the stable part of each finding row."""
    return {(s, k, p) for s, k, p, _d, _n, _w in out.rows()}


@pytest.mark.parametrize("name", ["testcase", "hierarchy"])
def test_each_template_passes_its_own_check(name):
    t = _template(name)
    out = T.run(t, t, allow_placeholders=True)
    assert out.count("ERROR") == 0 and out.count("WARN") == 0, T.render(out, name, name)


def test_planted_mistakes_are_named():
    t = _template("testcase")
    doc = copy.deepcopy(t)
    case = doc["cases"][0]
    case["review"]["reviwer"] = case["review"].pop("reviewer")  # a typo in a key
    doc["environment"]["probepoint"][0]["line"] = "212"         # a number written as text
    case["stubs"][0]["mode"] = "fake"                           # outside the closed set

    found = _found(T.run(doc, t, allow_placeholders=True))

    assert ("ERROR", "unknown-key", "cases[].review.reviwer") in found
    assert ("ERROR", "missing", "cases[].review.reviewer") in found
    assert ("ERROR", "type", "environment.probepoint[].line") in found
    assert ("WARN", "enum", "cases[].stubs[].mode") in found


def test_project_names_are_free_form():
    """Layer, section, environment AND core names are the project's own -- the Sample's
    `Core1` is as valid as the sample's `FCore`, in `Macros` keys and in `CoreType`."""
    env = {"EnvironmentId": "FTL1", "EnvironmentName": "FTL_MAP_FTLMAP_TS",
           "Filename": "FtlMap.cpp", "FilePath": "", "CoreType": "Core1", "IsHeader": False,
           "Probepoint": [], "usercode": [], "Testcase": "FTL_MAP_FTLMAP_TS.json"}
    section = {"SectionID": "MAP1", "SectionName": "Map",
               "TestEnvironments": {"FTL_MAP_FTLMAP_TS": env}}
    doc = {"Macros": {"Core1Macros": ["FTL_DEBUG=1"], "Core2Macros": []},
           "LayerMapping": {"FTL": {"searchdirectories": ["C:\\fw\\Src\\FTL"],
                                    "Librarydirectories": [],
                                    "Sections": {"Map": section}}}}

    out = T.run(doc, _template("hierarchy"))

    assert out.count("ERROR") == 0 and out.count("WARN") == 0, T.render(out, "doc", "hierarchy")


def test_it_cases_are_skipped_not_checked():
    t = _template("testcase")
    doc = copy.deepcopy(t)
    doc["cases"].append({"id": "IT-1", "level": "IT", "anything": "goes"})

    out = T.run(doc, t, allow_placeholders=True)

    assert ("INFO", "skipped", "cases[]") in _found(out)
    assert out.count("ERROR") == 0, T.render(out, "doc", "testcase")


def test_placeholder_left_in_a_real_file_is_reported():
    t = _template("testcase")
    out = T.run(copy.deepcopy(t), t)  # placeholders not allowed: the template is full of them
    assert ("INFO", "placeholder", "cases[].trace") in _found(out)


def test_file_kind_is_picked_from_its_keys():
    assert T.pick_template({"format_version": "1.0", "cases": []}) == "testcase"
    assert T.pick_template({"LayerMapping": {}}) == "hierarchy"
    assert T.pick_template({"something": 1}) is None


def test_main_exit_codes(tmp_path):
    template = T.template_path("hierarchy")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format_version": "1.0", "environment": {}, "cases": []}),
                   encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    assert T.main([template, "--allow-placeholders"]) == 0
    assert T.main([str(bad)]) == 1     # environment lacks every key
    assert T.main([str(broken)]) == 1  # not JSON: reported, not a traceback
    assert T.main([template, "--template", "nope"]) == 2
