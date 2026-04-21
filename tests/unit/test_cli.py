"""CLI tests for ``run.py``.

run.py executes argument parsing at module level (sys.argv scan), so we
cannot simply import it. For pure helper coverage, extract
``_resolve_group_name`` via the AST and compile it in isolation.

For end-to-end CLI behavior, run ``run.py`` as a subprocess against the
existing ``SampleCppProject`` fixture. These tests only target the
``Sample`` group so they regenerate the same shared artifacts as the
session pipeline fixture instead of changing the expected output shape.
"""
import ast
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUN_PY = os.path.join(PROJECT_ROOT, "run.py")
SAMPLE_PROJECT = os.path.join(PROJECT_ROOT, "SampleCppProject")


def _load_resolve_group():
    """Extract and compile _resolve_group_name from run.py without running module-level code."""
    src = open(_RUN_PY, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_group_name":
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            ns = {}
            exec(compile(module, _RUN_PY, "exec"), ns)
            return ns["_resolve_group_name"]
    raise RuntimeError("_resolve_group_name not found in run.py")


_resolve_group_name = _load_resolve_group()

GROUPS = {"Sample": {...}, "Full": {...}, "Support": {...}}


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, _RUN_PY, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def _output(result):
    return f"{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# _resolve_group_name
# ---------------------------------------------------------------------------

class TestResolveGroupName:
    def test_exact_match(self):
        assert _resolve_group_name(GROUPS, "Sample") == "Sample"

    def test_case_insensitive_match(self):
        assert _resolve_group_name(GROUPS, "sample") == "Sample"
        assert _resolve_group_name(GROUPS, "SAMPLE") == "Sample"
        assert _resolve_group_name(GROUPS, "sAmPlE") == "Sample"

    def test_no_match_returns_none(self):
        assert _resolve_group_name(GROUPS, "DoesNotExist") is None

    def test_none_requested_returns_none(self):
        assert _resolve_group_name(GROUPS, None) is None

    def test_empty_groups_returns_none(self):
        assert _resolve_group_name({}, "Sample") is None

    def test_none_groups_returns_none(self):
        assert _resolve_group_name(None, "Sample") is None

    def test_exact_match_preferred_over_casefold(self):
        groups = {"Sample": {}, "SAMPLE": {}}
        assert _resolve_group_name(groups, "Sample") == "Sample"
        assert _resolve_group_name(groups, "SAMPLE") == "SAMPLE"


class TestRunPyCli:
    def test_selected_group_requires_name(self):
        result = _run_cli("--selected-group")
        output = _output(result)

        assert result.returncode == 1
        assert "--selected-group requires a group name" in output

    def test_invalid_from_phase_rejected(self):
        result = _run_cli("--from-phase", "9", SAMPLE_PROJECT)
        output = _output(result)

        assert result.returncode == 1
        assert "--from-phase must be 1, 2, 3, or 4" in output

    def test_unknown_group_exits_2_and_lists_valid_groups(self):
        result = _run_cli("--selected-group", "DoesNotExist", SAMPLE_PROJECT)
        output = _output(result)

        assert result.returncode == 2
        assert "Unknown --selected-group 'DoesNotExist'" in output
        for expected in ("Sample", "Full", "Support", "Access", "Diag"):
            assert expected in output
