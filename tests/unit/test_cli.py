"""Unit tests for run.py — _resolve_group_name extracted via AST.

run.py executes argument parsing at module level (sys.argv scan), so we
cannot simply import it. Instead we extract _resolve_group_name via the
AST and compile it in isolation — no side effects, no sys.exit calls.
"""
import ast
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUN_PY = os.path.join(PROJECT_ROOT, "run.py")


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
