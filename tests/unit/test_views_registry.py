"""Unit tests for src/views/registry.py and src/views/__init__.py (run_views logic)."""
import os
import sys
import types

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))


# ---------------------------------------------------------------------------
# Helpers: load registry module in isolation (fresh copy each test class)
# ---------------------------------------------------------------------------

def _load_registry():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_test_registry",
        os.path.join(PROJECT_ROOT, "src", "views", "registry.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# views/registry.py
# ---------------------------------------------------------------------------

class TestViewRegistry:
    def setup_method(self):
        self.reg = _load_registry()

    def test_register_adds_to_registry(self):
        @self.reg.register("myView")
        def my_run():
            pass
        assert "myView" in self.reg.VIEW_REGISTRY

    def test_register_stores_original_function(self):
        sentinel = object()

        @self.reg.register("sentinelView")
        def fn():
            return sentinel

        assert self.reg.VIEW_REGISTRY["sentinelView"]() is sentinel

    def test_register_returns_original_function_unchanged(self):
        def original():
            return 42

        result = self.reg.register("view42")(original)
        assert result is original

    def test_multiple_views_registered(self):
        self.reg.register("v1")(lambda: None)
        self.reg.register("v2")(lambda: None)
        assert "v1" in self.reg.VIEW_REGISTRY
        assert "v2" in self.reg.VIEW_REGISTRY

    def test_registry_starts_empty(self):
        fresh = _load_registry()
        assert fresh.VIEW_REGISTRY == {}


# ---------------------------------------------------------------------------
# views/flowcharts.py — _resolve_script (the only pure function)
# ---------------------------------------------------------------------------

def _load_flowcharts_resolve_script():
    """Load only _resolve_script without triggering @register side-effects."""
    import importlib.util

    # Stub views package
    views_pkg = types.ModuleType("_fc_views")
    views_pkg.__path__ = [os.path.join(PROJECT_ROOT, "src", "views")]
    views_pkg.__package__ = "_fc_views"
    registry_mod = types.ModuleType("_fc_views.registry")
    registry_mod.register = lambda name: (lambda fn: fn)
    views_pkg.registry = registry_mod
    sys.modules["_fc_views"] = views_pkg
    sys.modules["_fc_views.registry"] = registry_mod

    spec = importlib.util.spec_from_file_location(
        "_fc_views.flowcharts",
        os.path.join(PROJECT_ROOT, "src", "views", "flowcharts.py"),
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "_fc_views"
    spec.loader.exec_module(mod)
    return mod._resolve_script


class TestResolveScript:
    def setup_method(self):
        self._resolve_script = _load_flowcharts_resolve_script()

    def test_empty_script_path_returns_default(self):
        result = self._resolve_script("/project", "")
        assert result == os.path.join("/project", "fake_flowchart_generator.py")

    def test_none_script_path_returns_default(self):
        result = self._resolve_script("/project", None)
        assert result == os.path.join("/project", "fake_flowchart_generator.py")

    def test_absolute_path_returned_as_is(self):
        abs_path = "/absolute/path/to/generator.py"
        result = self._resolve_script("/project", abs_path)
        assert result == abs_path

    def test_relative_path_joined_to_project_root(self):
        result = self._resolve_script("/project", "scripts/gen.py")
        assert result == os.path.join("/project", "scripts/gen.py")
