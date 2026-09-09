"""The LLM must never be disabled unless someone asked for it.

`--no-llm` is a deliberate escape hatch: it produces a document with mechanical prose and
mechanical flowchart labels. If it ever became a default — on any command, or through a
parameter default deeper in — a run would look successful and quietly produce a worse document,
which is the hardest kind of regression to notice. The 2062-second incident was the same shape:
the pipeline reported success while every label came back mechanical.

These are cheap structural guards, not behaviour tests.
"""
import argparse
import ast
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine")]

import analyzer as A  # noqa: E402


def _subparsers():
    for act in A.build_parser()._actions:
        if isinstance(act, argparse._SubParsersAction):
            return act.choices
    raise AssertionError("the CLI has no subcommands")


class TestTheFlag:
    def test_only_generate_offers_it(self):
        """Turning the LLM off is a property of PRODUCING a version. A re-export reuses the
        settings the version was generated with; offering the flag there would invite someone
        to re-export a good version into a mechanical one."""
        owners = [name for name, sp in _subparsers().items()
                  for a in sp._actions if "--no-llm" in a.option_strings]
        assert owners == ["generate"], f"--no-llm should live only on generate, found {owners}"

    def test_it_defaults_to_off(self):
        sp = _subparsers()["generate"]
        act = next(a for a in sp._actions if "--no-llm" in a.option_strings)
        assert act.default is False, "--no-llm must be opt-in"
        assert act.nargs == 0, "--no-llm must be a switch, not a value that could be mis-set"

    def test_no_command_passes_it_implicitly(self):
        """Nothing may hand no_llm=True to the orchestrators except the flag itself."""
        src = open(os.path.join(ROOT, "analyzer.py"), encoding="utf-8").read()
        assert "no_llm=True" not in src
        assert "no_llm=a.no_llm" in src, "the flag is the only thing that may set it"


class TestTheEngine:
    @pytest.mark.parametrize("rel,fn", [
        (os.path.join("engine", "incremental", "generate.py"), "generate_full"),
        (os.path.join("engine", "incremental", "engine.py"), "generate_incremental"),
    ])
    def test_the_orchestrator_parameter_defaults_to_off(self, rel, fn):
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == fn)
        args = node.args.args + node.args.kwonlyargs
        defaults = ([None] * (len(node.args.args) - len(node.args.defaults))
                    + list(node.args.defaults) + list(node.args.kw_defaults))
        idx = next(i for i, a in enumerate(args) if a.arg == "no_llm")
        d = defaults[idx]
        assert isinstance(d, ast.Constant) and d.value is False, \
            f"{fn}(no_llm=...) must default to False"

    def test_apply_no_llm_is_only_reachable_behind_the_flag(self):
        """It rewrites the config to disable every LLM path. An unconditional call would
        disable the LLM for runs that never asked."""
        src = open(os.path.join(ROOT, "engine", "incremental", "generate.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "apply_no_llm"):
                continue
            line = src.splitlines()[node.lineno - 2].strip()
            assert line.startswith("if no_llm"), \
                f"apply_no_llm() at line {node.lineno} is not guarded by `if no_llm`"


class TestTheShippedConfig:
    def test_descriptions_and_labels_are_on(self):
        """A fresh project must generate real prose, not fall back silently."""
        from core.config import _strip_json_comments, _strip_trailing_commas
        import json
        raw = open(os.path.join(ROOT, "engine", "config", "config.defaults.json"),
                   encoding="utf-8").read()
        llm = json.loads(_strip_trailing_commas(_strip_json_comments(raw))).get("llm") or {}
        assert llm.get("descriptions") is True
        assert llm.get("behaviourNames") is True
