"""Unit tests for unit-diagram incremental reuse (M3.10).

_affected_units = units of the impacted functions + their 1-hop cross-unit neighbours
(over-approximation, never stale). _apply_incremental_unit_plan carries the baseline
diagrams forward, prunes orphans, and returns the units to regenerate."""
import importlib.util
import json
import os
import sys
import types

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

# Stub the `views` package so the module's relative `from .registry import register` resolves.
_views_pkg = types.ModuleType("views")
_views_pkg.__path__ = [os.path.join(PROJECT_ROOT, "src", "views")]
_views_pkg.__package__ = "views"
_registry_mod = types.ModuleType("views.registry")
_registry_mod.register = lambda name: (lambda fn: fn)
_views_pkg.registry = _registry_mod
sys.modules.setdefault("views", _views_pkg)
sys.modules.setdefault("views.registry", _registry_mod)

_spec = importlib.util.spec_from_file_location(
    "views.unit_diagrams",
    os.path.join(PROJECT_ROOT, "src", "views", "unit_diagrams.py"),
    submodule_search_locations=[],
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = "views"
_spec.loader.exec_module(_mod)

_affected_units = _mod._affected_units
_apply = _mod._apply_incremental_unit_plan


class TestAffectedUnits:
    # functions: A1,A2 in unit A ; B1 in unit B ; C1 in unit C ; D1 in unit D (untouched)
    FUNCS = {
        "A1": {"callsIds": ["B1"], "calledByIds": []},
        "A2": {"callsIds": [], "calledByIds": ["C1"]},
        "B1": {"callsIds": [], "calledByIds": ["A1"]},
        "C1": {"callsIds": ["A2"], "calledByIds": []},
        "D1": {"callsIds": [], "calledByIds": []},
    }
    FID2U = {"A1": "A", "A2": "A", "B1": "B", "C1": "C", "D1": "D"}

    def test_impacted_unit_and_callee_neighbour(self):
        # A1 (unit A) changed; it calls B1 (unit B) -> A and B affected, not D
        out = _affected_units({"A1"}, self.FUNCS, self.FID2U)
        assert out == {"A", "B"}

    def test_caller_neighbour_included(self):
        # A2 (unit A) changed; called by C1 (unit C) -> A and C affected
        out = _affected_units({"A2"}, self.FUNCS, self.FID2U)
        assert out == {"A", "C"}

    def test_untouched_unit_excluded(self):
        assert "D" not in _affected_units({"A1", "A2"}, self.FUNCS, self.FID2U)

    def test_empty_impact(self):
        assert _affected_units(set(), self.FUNCS, self.FID2U) == set()


class TestApplyIncrementalUnitPlan:
    def _setup(self, tmp_path, plan):
        model_dir = tmp_path / "model"; model_dir.mkdir()
        out_dir = tmp_path / "output" / "unit_diagrams"; out_dir.mkdir(parents=True)
        (model_dir / "incremental_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        return str(model_dir), str(out_dir)

    def test_no_plan_returns_none(self, tmp_path):
        model_dir = tmp_path / "model"; model_dir.mkdir()
        out_dir = tmp_path / "out"; out_dir.mkdir()
        assert _apply(str(model_dir), str(out_dir), {}, {}, []) is None

    def test_carry_forward_prune_and_restrict(self, tmp_path):
        # baseline version output with 3 unit diagrams; one unit ("Old") is now gone
        base = tmp_path / "versions" / "v1" / "output" / "unit_diagrams"
        base.mkdir(parents=True)
        for u in ("A", "B", "Old"):
            (base / f"{u}.mmd").write_text("x", encoding="utf-8")
            (base / f"{u}.png").write_bytes(b"p")
        plan = {"baselineVersionDir": str(tmp_path / "versions" / "v1"),
                "impactFids": ["A1"]}
        model_dir, out_dir = self._setup(tmp_path, plan)
        funcs = {"A1": {"callsIds": ["B1"], "calledByIds": []}, "B1": {}}
        fid2u = {"A1": "A", "B1": "B"}
        cpp_units = ["A", "B"]   # "Old" no longer exists -> orphan

        affected = _apply(model_dir, out_dir, funcs, fid2u, cpp_units)
        files = set(os.listdir(out_dir))
        assert affected == {"A", "B"}                       # A impacted + B (callee neighbour)
        assert "A.mmd" in files and "B.png" in files        # carried forward
        assert "Old.mmd" not in files and "Old.png" not in files  # orphan pruned
