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


# ---------------------------------------------------------------------------
# A call bullet the LLM did not write is not left that way silently (review SWE3-030)
# ---------------------------------------------------------------------------

_LLM_CFG = {"llm": {"descriptions": True}}


@pytest.fixture
def describer(monkeypatch):
    """A CallDescriptionGenerator whose LLM answers from `answers` (None = no answer), with
    no cache in between and no waiting."""
    import llm_enrichment as le
    monkeypatch.setattr(le, "_cached_desc", lambda config, material, generate: generate())
    monkeypatch.setattr(le, "llm_provider_reachable", lambda config: True)
    monkeypatch.setattr(CallDescriptionGenerator, "WAIT_SECONDS", 0)
    answers, asked = [], []

    class Client:
        def generate(self, system, prompt):
            asked.append(prompt)
            return answers.pop(0) if answers else None

    gen = CallDescriptionGenerator(_LLM_CFG)
    gen._llm_available, gen._llm_client = True, Client()
    return gen, answers, asked


def _name(key):
    return FUNCTIONS[key]["qualifiedName"]


def test_a_call_is_tried_three_times_before_it_falls_back(describer):
    gen, answers, asked = describer
    answers.extend([None, None, "target calls worker to do the work"])
    assert gen.get_call_description(TARGET, "CompA|Unit2|worker", _name, FUNCTIONS) == \
        "target calls worker to do the work"
    assert len(asked) == 3 and gen.fell_back == []


def test_a_call_that_fell_back_is_written_in_the_second_round(describer):
    gen, answers, asked = describer
    assert gen.get_call_description(TARGET, "CompA|Unit2|worker", _name, FUNCTIONS) == \
        "target calls worker"                            # three tries, no answer
    assert len(asked) == 3
    # the server is rested: the next call falls back at once, without asking
    assert gen.get_call_description(CALLER, TARGET, _name, FUNCTIONS) == "extCaller calls target"
    assert len(asked) == 3
    answers.extend(["target calls worker to do the work", "extCaller calls target to start"])
    done = gen.retry_fallbacks(_name, FUNCTIONS)
    assert done == {(TARGET, "CompA|Unit2|worker"): "target calls worker to do the work",
                    (CALLER, TARGET): "extCaller calls target to start"}
    line, short = gen.summary()
    assert (line, short) == ("behaviour descriptions: 2 call bullet(s) written by the LLM "
                             "(2 of them in a second round)", False)


def test_a_server_that_stays_down_is_reported(describer):
    gen, _answers, _asked = describer
    for _ in range(2):
        gen.get_call_description(TARGET, "CompA|Unit2|worker", _name, FUNCTIONS)
    assert gen.retry_fallbacks(_name, FUNCTIONS) == {}
    line, short = gen.summary()
    assert short is True
    assert "0 call bullet(s) written by the LLM, 2 without it: " in line


def test_one_failed_server_check_is_not_final(monkeypatch):
    import llm_enrichment as le
    clock = {"now": 1000.0}
    monkeypatch.setattr("behaviour_diagram.llm_call_description.time.monotonic", lambda: clock["now"])
    up = {"server": False}
    monkeypatch.setattr(le, "llm_provider_reachable", lambda config: up["server"])
    monkeypatch.setattr("llm_core.client.from_config", lambda cfg: object())
    monkeypatch.setattr("core.config.load_llm_config", lambda cfg: {})
    gen = CallDescriptionGenerator(_LLM_CFG)
    assert gen._is_llm_available() is False
    up["server"] = True
    clock["now"] += 5
    assert gen._is_llm_available() is False                  # too soon to ask again
    clock["now"] += CallDescriptionGenerator.RECHECK_SECONDS
    assert gen._is_llm_available() is True                   # asked again, and it is back


def test_with_no_description_the_llm_reads_the_two_functions_code(describer, tmp_path):
    gen, answers, asked = describer
    (tmp_path / "a.cpp").write_text("int run() {\n    return compute(1, 2);\n}\n"
                                    "int compute(int a, int b) {\n    return a + b;\n}\n")
    gen._base_path = str(tmp_path)
    functions = {"A|U|run|": {"qualifiedName": "run",
                              "location": {"file": "a.cpp", "line": 1, "endLine": 3}},
                 "A|V|compute|": {"qualifiedName": "compute",
                                  "location": {"file": "a.cpp", "line": 4, "endLine": 6}}}
    answers.append("run calls compute to add two numbers")
    name = lambda k: functions[k]["qualifiedName"]  # noqa: E731
    assert gen.get_call_description("A|U|run|", "A|V|compute|", name, functions) == \
        "run calls compute to add two numbers"
    assert "return compute(1, 2);" in asked[0] and "return a + b;" in asked[0]


def test_with_the_llm_off_nothing_is_asked_or_queued():
    gen = CallDescriptionGenerator({"llm": {"descriptions": False}})
    assert gen.get_call_description(TARGET, "CompA|Unit2|worker", _name, FUNCTIONS) == \
        "target calls worker"
    assert gen.fell_back == [] and gen.retry_fallbacks(_name, FUNCTIONS) == {}
    line, short = gen.summary()
    assert short is False and "written without the LLM -- the LLM is off" in line


def test_the_view_puts_the_second_round_into_its_rows(monkeypatch):
    from views import behaviour_diagram as view
    said = []
    monkeypatch.setattr(view, "log", lambda msg, **kw: said.append(msg))

    class Gen:
        def retry_call_descriptions(self):
            return {"extCaller calls target": "extCaller calls target to start"}

        def call_description_summary(self):
            return "behaviour descriptions: 3 call bullet(s) written by the LLM", False

    rows = {"CompA": {"Unit1": [{"behaviorDescription": [
        "extCaller calls target", "target calls worker to do the work", "worker returns to target"]}]}}
    assert view._second_round(Gen(), rows) == 1
    assert rows["CompA"]["Unit1"][0]["behaviorDescription"] == [
        "extCaller calls target to start", "target calls worker to do the work",
        "worker returns to target"]
    assert said == ["behaviour descriptions: 3 call bullet(s) written by the LLM"]
