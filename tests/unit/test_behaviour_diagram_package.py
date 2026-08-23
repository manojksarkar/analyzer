"""Regression tests for engine/behaviour_diagram/.

The package had no test coverage when the generator was replaced. These lock in
the behaviours that actually broke during that swap:

  * unit ids are slash-joined, because MermaidBuilder splits them on "/"
  * generate_all_diagrams() works in every filter mode (it raised IndexError)
  * get_selection_summary() returns a dict in every mode (it returned None, and
    the skip_within_unit selector called a method it does not own)
  * a call description describes the CALL, never the callee's own description
    (function description and behaviour description are different things)
"""

import json
import os
import sys

import pytest

_ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from behaviour_diagram import SequenceDiagramGenerator  # noqa: E402
from behaviour_diagram.llm_call_description import CallDescriptionGenerator  # noqa: E402

ALL_MODES = [
    "skip_within_unit",
    "single_per_function",
    "single_per_external_component",
    "all_callers",
    "multi_unit_functions",
]

TARGET = "CompA|Unit1|target"
CALLER = "CompX|UnitX|extCaller"

# CompX calls into CompA. Inside CompA the call crosses Unit1 -> Unit2 via an
# intra-unit hop (helper), which is what skip_within_unit has to bridge over.
COMPONENTS = {
    "CompA": {"units": ["CompA|Unit1", "CompA|Unit2"]},
    "CompX": {"units": ["CompX|UnitX"]},
}
UNITS = {
    "CompA|Unit1": {"name": "Unit1", "functionIds": ["CompA|Unit1|target", "CompA|Unit1|helper"]},
    "CompA|Unit2": {"name": "Unit2", "functionIds": ["CompA|Unit2|worker"]},
    "CompX|UnitX": {"name": "UnitX", "functionIds": [CALLER]},
}
FUNCTIONS = {
    CALLER: {"qualifiedName": "extCaller", "callsIds": [TARGET], "calledByIds": []},
    TARGET: {"qualifiedName": "target", "callsIds": ["CompA|Unit1|helper"],
             "calledByIds": [CALLER], "description": "Entry point"},
    "CompA|Unit1|helper": {"qualifiedName": "helper", "callsIds": ["CompA|Unit2|worker"],
                           "calledByIds": [TARGET]},
    "CompA|Unit2|worker": {"qualifiedName": "worker", "callsIds": [], "calledByIds": ["CompA|Unit1|helper"],
                           "description": "Does the work"},
}


@pytest.fixture
def model(tmp_path):
    """Write the fixture model to disk and return the three paths."""
    paths = []
    for name, data in (("components", COMPONENTS), ("units", UNITS), ("functions", FUNCTIONS)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        paths.append(str(p))
    return paths


def _generator(model, mode):
    cfg = {"views": {"sequenceDiagrams": {"filterMode": mode}}}
    return SequenceDiagramGenerator(*model, cfg)


@pytest.mark.parametrize("mode", ALL_MODES)
def test_generate_all_diagrams_runs_in_every_mode(model, tmp_path, mode):
    """Regression: this raised IndexError in all five modes."""
    gen = _generator(model, mode)
    mmd_paths, descriptions = gen.generate_all_diagrams(TARGET, str(tmp_path / mode))

    assert len(mmd_paths) == len(descriptions)
    for path in mmd_paths:
        assert os.path.isfile(path)
        assert path.endswith(".mmd")
        assert open(path, encoding="utf-8").read().startswith("sequenceDiagram")


@pytest.mark.parametrize("mode", ALL_MODES)
def test_descriptions_are_lists_of_strings(model, tmp_path, mode):
    """The docx table only renders bullets for a list, so the shape matters."""
    gen = _generator(model, mode)
    _, descriptions = gen.generate_all_diagrams(TARGET, str(tmp_path / mode))

    for per_diagram in descriptions:
        assert isinstance(per_diagram, list)
        assert all(isinstance(line, str) for line in per_diagram)


@pytest.mark.parametrize("mode", ALL_MODES)
def test_get_selection_summary_returns_a_dict(model, mode):
    """Regression: returned None, and skip_within_unit raised AttributeError."""
    summary = _generator(model, mode).get_selection_summary(TARGET)

    assert isinstance(summary, dict)
    assert summary["target_function"] == TARGET
    assert summary["filter_mode"] == mode


def test_unit_ids_are_slash_joined(model, tmp_path):
    """Regression: an underscore here made MermaidBuilder's split('/') IndexError."""
    gen = _generator(model, "all_callers")
    mmd_paths, _ = gen.generate_all_diagrams(TARGET, str(tmp_path))
    body = open(mmd_paths[0], encoding="utf-8").read()

    assert "CompA/Unit1" in body
    assert "CompA_Unit1" not in body


def test_skip_within_unit_bridges_over_the_intra_unit_hop(model, tmp_path):
    """helper is dropped, but target -> worker must survive as a bridged edge."""
    gen = _generator(model, "skip_within_unit")
    mmd_paths, _ = gen.generate_all_diagrams(TARGET, str(tmp_path))
    body = open(mmd_paths[0], encoding="utf-8").read()

    assert "helper()" not in body
    assert "CompA/Unit1->>CompA/Unit2: worker()" in body


def test_call_description_describes_the_call_not_the_callee():
    """A behaviour description is call-specific; it is not the callee's own
    function description, which the docx already shows elsewhere."""
    describer = CallDescriptionGenerator(None)  # no config -> no LLM
    name = lambda key: FUNCTIONS[key]["qualifiedName"]  # noqa: E731

    result = describer.get_call_description(TARGET, "CompA|Unit2|worker", name, FUNCTIONS)

    assert result == "target calls worker"
    assert FUNCTIONS["CompA|Unit2|worker"]["description"] not in result


def test_no_llm_configured_means_no_llm_call():
    """Offline/air-gapped runs must not attempt a network call."""
    assert CallDescriptionGenerator(None)._is_llm_available() is False
    assert CallDescriptionGenerator({})._is_llm_available() is False
