"""Unit tests for src/core/group_planner.py — plan_runs dispatch shapes."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.group_planner import _resolve_group_name, plan_runs

_FAKE_PATHS = SimpleNamespace(
    project_root=PROJECT_ROOT,
    output_dir=os.path.join(PROJECT_ROOT, "output"),
)

def _run(cfg, **kwargs):
    defaults = dict(project_path="/project", selected_group=None,
                    use_model=False, no_llm_summarize=False, from_phase=1, filter_mode=None)
    defaults.update(kwargs)
    with patch("core.group_planner.paths", return_value=_FAKE_PATHS):
        return plan_runs(cfg, **defaults)

def _groups(*names):
    return {"layers": {"L": {"path": "", "groups": {n: {} for n in names}}}}


class TestResolveGroupName:
    def test_exact_and_case_insensitive(self):
        assert _resolve_group_name({"Sample": {}}, "Sample") == "Sample"
        assert _resolve_group_name({"Sample": {}}, "sample") == "Sample"

    def test_missing_returns_none(self):
        assert _resolve_group_name({"Sample": {}}, "Other") is None
        assert _resolve_group_name({}, "Sample") is None


class TestPlanRuns:
    def test_no_groups_produces_single_four_phase_plan(self):
        plans = _run({})
        assert len(plans) == 1
        assert len(plans[0].phases) == 4

    def test_from_phase_passed_through_on_single_plan(self):
        assert _run({}, from_phase=3)[0].runner_from_phase == 3

    def test_no_llm_summarize_omits_flag_from_phase2(self):
        plans = _run({}, no_llm_summarize=True)
        assert "--llm-summarize" not in plans[0].phases[1].args

    def test_use_model_skips_to_two_phase_plan(self):
        plans = _run({}, use_model=True)
        assert len(plans[0].phases) == 2

    def test_groups_produce_build_plan_plus_one_per_group(self):
        plans = _run(_groups("Alpha", "Beta"))
        assert len(plans) == 3  # build + 2 groups
        assert "Build" in plans[0].label

    def test_from_phase_3_suppresses_build_plan(self):
        plans = _run(_groups("Alpha"), from_phase=3)
        assert all("Build" not in p.label for p in plans)

    def test_selected_group_produces_build_plus_one(self):
        plans = _run(_groups("Alpha", "Beta"), selected_group="Alpha")
        assert len(plans) == 2
        assert "Alpha" in plans[1].label

    def test_selected_group_case_insensitive(self):
        plans = _run(_groups("Alpha"), selected_group="alpha")
        assert "Alpha" in plans[1].label

    def test_unknown_group_raises(self):
        with pytest.raises(ValueError, match="DoesNotExist"):
            _run(_groups("Alpha"), selected_group="DoesNotExist")

    def test_filter_mode_forwarded_to_views(self):
        plans = _run({}, filter_mode="public")
        assert "--filter-mode" in plans[0].phases[2].args


class TestPlanComponents:
    """Each document plan names the components it makes -- the folder its document lands in,
    which is also `documents.group` -- so run.py can mark them generating / generated / failed
    (staged generation). The model plan names none."""

    CFG = {"layers": {"L": {"path": "", "groups": {"G": {"Math": {}, "App": {}}}}}}

    @staticmethod
    def _out_dirs(plan):
        exporter = next(ph for ph in plan.phases if ph.script.endswith("docx_exporter.py"))
        return [os.path.basename(os.path.dirname(exporter.args[1]))]

    def test_per_component_documents_name_their_component(self):
        plans = _run(self.CFG, component_per_docx=True)
        assert plans[0].components == []                     # the model
        assert len(plans) == 3
        for p in plans[1:]:
            assert p.components == self._out_dirs(p)

    def test_a_group_document_names_its_group_folder(self):
        plans = _run(self.CFG)
        assert plans[1].components == self._out_dirs(plans[1])

    def test_a_component_scope_names_each_component(self):
        plans = _run(self.CFG, selected_components=["Math", "App"], component_per_docx=True)
        assert [p.components for p in plans[1:]] == [["Math"], ["App"]]
