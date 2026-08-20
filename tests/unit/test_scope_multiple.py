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
        assert "in group Support" in msg

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
