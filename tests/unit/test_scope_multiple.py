"""A scope naming several groups must generate ALL of them.

`--scope group:App,Math` produced App and silently dropped Math: `scope_to_args` mapped a group
scope to `["--selected-group", names[0]]`. The run succeeded, the reuse report looked healthy,
and the document simply had one group in it — no error, no warning.

Layers had the same shape, so `--scope layer:A,B` lost B the same way.

The planner was never the limitation: `target_groups` is a list and it already builds one plan
per group. Only the selection collapsed to a single name.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from incremental.generate import scope_to_args, _parse_scope   # noqa: E402


class TestScopeToArgs:
    def test_two_groups_produce_two_flags(self):
        args = scope_to_args({"type": "group", "names": ["App", "Math"]})
        assert args == ["--selected-group", "App", "--selected-group", "Math"]

    def test_two_layers_produce_two_flags(self):
        args = scope_to_args({"type": "layer", "names": ["L1", "L2"]})
        assert args == ["--selected-layer", "L1", "--selected-layer", "L2"]

    def test_components_were_already_correct(self):
        args = scope_to_args({"type": "component", "names": ["Uart", "Spi"]})
        assert args == ["--selected-component", "Uart", "--selected-component", "Spi"]

    def test_one_name_is_unchanged(self):
        assert scope_to_args({"type": "group", "names": ["App"]}) == ["--selected-group", "App"]

    def test_project_scope_passes_no_flags(self):
        assert scope_to_args({"type": "project"}) == []


class TestScopeParsing:
    @pytest.mark.parametrize("text,expected", [
        ("group:App,Math", {"type": "group", "names": ["App", "Math"]}),
        ("layer:Layer1", {"type": "layer", "names": ["Layer1"]}),
        ("component:Uart,Spi", {"type": "component", "names": ["Uart", "Spi"]}),
        ("project", {"type": "project"}),
        ("", {"type": "project"}),
    ])
    def test_forms(self, text, expected):
        assert _parse_scope(text) == expected

    def test_trailing_and_doubled_commas_are_ignored(self):
        assert _parse_scope("group:App,,Math,") == {"type": "group", "names": ["App", "Math"]}


class TestThePlannerHonoursEveryName:
    def _cfg(self):
        return {"layers": {"L1": {"path": ".", "groups": {
            "App": {"App": "src/app"}, "Math": {"Math": "src/math"},
            "Other": {"Other": "src/other"}}}}}

    def _plans(self, **kw):
        from core.group_planner import plan_runs
        return plan_runs(self._cfg(), project_path=".", use_model=True,
                         no_llm_summarize=True, filter_mode=None, **kw)

    def test_both_named_groups_get_a_plan(self):
        labels = [p.label for p in self._plans(selected_group=["App", "Math"])]
        assert any("App" in l for l in labels), labels
        assert any("Math" in l for l in labels), labels
        assert not any("Other" in l for l in labels), "an unnamed group was generated"

    def test_a_single_string_still_works(self):
        """Backwards compatible: every existing caller passes one name."""
        labels = [p.label for p in self._plans(selected_group="App")]
        assert any("App" in l for l in labels)
        assert not any("Math" in l for l in labels)

    def test_an_unknown_name_alongside_a_valid_one_raises(self):
        """A typo must not quietly yield the subset that happened to resolve."""
        with pytest.raises(ValueError, match="Nope"):
            self._plans(selected_group=["App", "Nope"])


class TestAComponentNameGetsAUsefulError:
    """`--scope group:App,Math` when App and Math are COMPONENTS.

    The message was "Unknown --selected-group 'App'. Valid groups: Access, Diag, Full, …" —
    accurate, and a dead end. App IS valid, as a component inside the group Support, and
    nothing said so. The caller is left comparing two lists by hand to work out that the flag
    was wrong rather than the name.
    """

    def _cfg(self):
        return {"layers": {"Layer1": {"path": ".", "groups": {
            "Support": {"Math": "math", "App": "app", "Outer": "outer"},
            "Access": {"Access": "access"}}}}}

    def _plan(self, groups):
        from core.group_planner import plan_runs
        return plan_runs(self._cfg(), project_path=".", selected_group=groups,
                         use_model=True, no_llm_summarize=True, filter_mode=None)

    def test_it_says_they_are_components_and_names_the_group(self):
        with pytest.raises(ValueError) as exc:
            self._plan(["App", "Math"])
        msg = str(exc.value)
        assert "COMPONENTS, not groups" in msg
        # The group id carries its layer, so the hint names WHICH Support - two
        # layers may each have one.
        assert "in group Layer1.Support" in msg

    def test_it_prints_the_corrected_command(self):
        with pytest.raises(ValueError) as exc:
            self._plan(["App", "Math"])
        assert '--scope "component:App,Math"' in str(exc.value)

    def test_a_genuinely_unknown_name_is_reported_separately(self):
        """Mixing a component and a typo must distinguish them — the fixes differ."""
        with pytest.raises(ValueError) as exc:
            self._plan(["App", "Nonsense"])
        msg = str(exc.value)
        assert "Nonsense" in msg
        assert "Not found at all" in msg

    def test_it_is_case_insensitive_like_group_resolution(self):
        with pytest.raises(ValueError) as exc:
            self._plan(["app"])
        assert "COMPONENTS, not groups" in str(exc.value)

    def test_valid_groups_are_still_listed(self):
        with pytest.raises(ValueError) as exc:
            self._plan(["App"])
        assert "Support" in str(exc.value) and "Access" in str(exc.value)


class TestOneRunMaySpanLayers:
    """Groups or components from DIFFERENT layers in one run.

    Every layer named has to reach the parse: the model is built once, and a layer
    left out of `--selected-layer` gets no include paths of its own, so its `#include`s
    fail and its definitions go missing from the model with nothing in the log tying
    the gap to the selection. Components across layers used to be refused outright;
    now that component ids carry their layer the model keeps them apart, so the
    restriction has no reason left.
    """

    CFG = {"layers": {
        "L1": {"path": "Layer1", "groups": {"Support": {"Math": "Math"}}},
        "L2": {"path": "Layer2", "groups": {"Platform": {"Gpio": "Gpio"},
                                            "Extra": {"Cache": "Cache"}}},
    }}

    def _parser_args(self, **kw):
        """The Phase-1 argv the planner would spawn."""
        from core.group_planner import plan_runs
        kw.setdefault("selected_group", None)
        plans = plan_runs(self.CFG, project_path=".", use_model=False,
                          no_llm_summarize=True, filter_mode=None, **kw)
        for p in plans:
            for ph in p.phases:
                if ph.script == "parser.py":
                    return ph.args
        raise AssertionError("no parser phase was planned")

    def _flag_values(self, args, flag):
        return [args[i + 1] for i, a in enumerate(args) if a == flag]

    def test_groups_from_two_layers_each_get_a_plan(self):
        from core.group_planner import plan_runs
        labels = [p.label for p in plan_runs(
            self.CFG, project_path=".", use_model=True, no_llm_summarize=True,
            filter_mode=None, selected_group=["L1.Support", "L2.Platform"])]
        assert any("L1.Support" in l for l in labels), labels
        assert any("L2.Platform" in l for l in labels), labels

    def test_a_cross_layer_group_scope_parses_both_layers(self):
        args = self._parser_args(selected_group=["L1.Support", "L2.Platform"])
        assert self._flag_values(args, "--selected-group") == ["L1.Support", "L2.Platform"]

    def test_two_layers_named_directly_both_reach_the_parser(self):
        """`--scope layer:L1,L2` mapped to one flag, so L2 was never parsed."""
        args = self._parser_args(selected_layer=["L1", "L2"])
        assert self._flag_values(args, "--selected-layer") == ["L1", "L2"]

    def test_a_single_layer_string_still_works(self):
        args = self._parser_args(selected_layer="L2")
        assert self._flag_values(args, "--selected-layer") == ["L2"]

    def test_components_from_two_layers_are_planned_together(self):
        """Refused outright before — 'All --selected-component names must be in the
        same layer'."""
        args = self._parser_args(selected_components=["L1.Math", "L2.Gpio", "L2.Cache"])
        assert self._flag_values(args, "--selected-layer") == ["L1", "L2"], args

    def test_a_layer_is_named_once_however_many_of_its_components_are_picked(self):
        args = self._parser_args(selected_components=["L2.Gpio", "L2.Cache"])
        assert self._flag_values(args, "--selected-layer") == ["L2"]

    def test_the_bundle_output_name_keeps_every_component(self):
        from core.group_planner import plan_runs
        plans = plan_runs(self.CFG, project_path=".", use_model=True,
                          no_llm_summarize=True, filter_mode=None, selected_group=None,
                          selected_components=["L1.Math", "L2.Gpio"])
        assert any("L1.Math" in p.label and "L2.Gpio" in p.label for p in plans), \
            [p.label for p in plans]


class TestAComponentScopeSplitsPerComponent:
    """`--scope "component:A,B"` returns one document PER component.

    It was the only scope that did not. project / layer / group all get
    `--component-per-docx` from `per_component_docx_args`, but a component scope was
    skipped because run.py REFUSED the flag alongside --selected-component — so
    naming three components produced a single bundled `A_B_C` document while naming
    the group they live in produced three. The model build is shared either way; only
    the view+export step repeats.
    """

    CFG = {"layers": {
        "L1": {"path": "Layer1", "groups": {"Support": {"Math": "Math"}}},
        "L2": {"path": "Layer2", "groups": {"Platform": {"Gpio": "Gpio", "Uart": "Uart"}}},
    }}
    COMPS = ["L1.Math", "L2.Gpio", "L2.Uart"]

    def _plans(self, per_docx, **kw):
        from core.group_planner import plan_runs
        return plan_runs(self.CFG, project_path=".", use_model=True, no_llm_summarize=True,
                         filter_mode=None, selected_group=None,
                         selected_components=self.COMPS, component_per_docx=per_docx, **kw)

    def _labels(self, plans):
        return [p.label for p in plans if p.label.startswith("Components:")]

    def test_the_flag_gives_one_plan_per_component(self):
        assert self._labels(self._plans(True)) == [
            "Components: L1.Math", "Components: L2.Gpio", "Components: L2.Uart"]

    def test_without_the_flag_they_are_still_bundled(self):
        """Backwards compatible: the bundle is still reachable."""
        assert self._labels(self._plans(False)) == ["Components: L1.Math, L2.Gpio, L2.Uart"]

    def test_components_from_different_layers_split_the_same_way(self):
        """L1.Math and L2.Gpio in one run, one document each."""
        labels = self._labels(self._plans(True))
        assert "Components: L1.Math" in labels and "Components: L2.Gpio" in labels

    def test_every_scope_type_now_asks_for_per_component_documents(self):
        from incremental.generate import per_component_docx_args
        for scope in ({"type": "project"},
                      {"type": "layer", "names": ["L1"]},
                      {"type": "group", "names": ["L1.Support"]},
                      {"type": "component", "names": ["L1.Math", "L2.Gpio"]}):
            assert per_component_docx_args(scope) == ["--component-per-docx"], scope

    def test_an_output_name_is_ignored_when_splitting(self):
        """It names ONE output; several documents cannot share it without one
        overwriting the others, so the component's own name keys them instead."""
        labels = self._labels(self._plans(True, output_name="Bundle Name"))
        assert labels == ["Components: L1.Math", "Components: L2.Gpio", "Components: L2.Uart"]

    def test_an_output_name_still_applies_to_a_bundle(self):
        plans = self._plans(False, output_name="Bundle Name")
        docx = [a for p in plans for ph in p.phases for a in ph.args if a.endswith(".docx")]
        assert any("Bundle-Name" in a for a in docx), docx
