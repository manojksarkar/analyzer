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
_RUN_PY = os.path.join(PROJECT_ROOT, "engine", "run.py")
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
        # run.py validates the project path exists (exit 1) BEFORE resolving the
        # group (exit 2), so point at a real dir to reach the group check.
        result = _run_cli("--selected-group", "DoesNotExist", PROJECT_ROOT)
        output = _output(result)

        assert result.returncode == 2
        # The message names every unresolved name and separates "not a group at all" from
        # "that is a COMPONENT" — the two have different fixes, and the old single-line form
        # ("Unknown --selected-group 'X'. Valid groups: ...") left the caller to work out which
        # case they were in by comparing two lists.
        assert "Unknown group(s) in the scope: DoesNotExist" in output
        assert "Not found at all: DoesNotExist" in output
        for expected in ("Sample", "Full", "Support", "Access", "Diag"):
            assert expected in output

    def test_a_component_name_is_identified_as_such(self):
        """`App` is a real COMPONENT in the sample config, inside the group `Support`. Saying
        only "valid groups: ..." is accurate and a dead end."""
        result = _run_cli("--selected-group", "App", PROJECT_ROOT)
        output = _output(result)

        assert result.returncode == 2
        assert "COMPONENTS, not groups" in output
        assert "in group Support" in output
        assert '--scope "component:App"' in output
