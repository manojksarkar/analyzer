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


class TestDocType:
    """--doc-type dispatch: view-set flag + per-doc-type exporter(s)."""

    def _export_phases(self, plan):
        return [ph for ph in plan.phases
                if ph.script in ("docx_exporter.py", "swe4_exporter.py")]

    def test_default_swe3_uses_docx_exporter_only(self):
        # No flag: unchanged SWE.3 pipeline — single docx_exporter, no swe4.
        exporters = self._export_phases(_run(_groups("Alpha"))[1])
        assert [e.script for e in exporters] == ["docx_exporter.py"]

    def test_default_passes_doc_type_swe3_to_views(self):
        views = _run(_groups("Alpha"))[1].phases[0]
        assert views.script == "run_views.py"
        assert views.args[views.args.index("--doc-type") + 1] == "swe3"

    def test_swe4_uses_swe4_exporter_and_view_flag(self):
        plan = _run(_groups("Alpha"), doc_type="swe4")[1]
        exporters = self._export_phases(plan)
        assert [e.script for e in exporters] == ["swe4_exporter.py"]
        views = plan.phases[0]
        assert views.args[views.args.index("--doc-type") + 1] == "swe4"

    def test_all_emits_both_exporters(self):
        exporters = self._export_phases(_run(_groups("Alpha"), doc_type="all")[1])
        assert [e.script for e in exporters] == ["docx_exporter.py", "swe4_exporter.py"]

    def test_swe4_exporter_gets_test_specs_json(self):
        exporters = self._export_phases(_run(_groups("Alpha"), doc_type="swe4")[1])
        assert any(a.endswith("test_specs.json") for a in exporters[0].args)
