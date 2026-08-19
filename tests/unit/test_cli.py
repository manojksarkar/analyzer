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


def _run_py_ast():
    return ast.parse(open(_RUN_PY, encoding="utf-8").read())


def _branch_flags():
    """Every flag literal the argv loop in run.py compares `a` against."""
    flags = set()
    for node in ast.walk(_run_py_ast()):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != "a":
            continue
        for comp in node.comparators:
            if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                flags.add(comp.value)
            elif isinstance(comp, ast.Tuple):
                flags.update(e.value for e in comp.elts
                             if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return flags


def _declared_flags():
    """The _KNOWN_FLAGS tuple run.py rejects unknown options against."""
    for node in _run_py_ast().body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_KNOWN_FLAGS" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise RuntimeError("_KNOWN_FLAGS not found in run.py")


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
        assert "Unknown --selected-group 'DoesNotExist'" in output
        for expected in ("Sample", "Full", "Support", "Access", "Diag"):
            assert expected in output


class TestStrictArgValidation:
    """Unknown options and stray positionals must stop the run, not be ignored.

    Previously anything unrecognised fell through to the positional list, so
    `run.py <proj> --phase 3` silently dropped both tokens and re-ran the whole
    pipeline from Phase 1. Every case here fails during the argv scan, before any
    phase starts, so none of these tests touch the pipeline.
    """

    def test_unknown_option_after_positional_rejected(self):
        result = _run_cli(SAMPLE_PROJECT, "--phase", "3")
        output = _output(result)

        assert result.returncode == 1
        assert "Unknown option: --phase" in output

    def test_unknown_option_before_positional_rejected(self):
        result = _run_cli("--clen", SAMPLE_PROJECT)
        output = _output(result)

        assert result.returncode == 1
        assert "Unknown option: --clen" in output

    def test_unknown_option_suggests_closest_flag(self):
        assert "--clean" in _output(_run_cli("--clen", SAMPLE_PROJECT))
        assert "--from-phase" in _output(_run_cli(SAMPLE_PROJECT, "--phase", "3"))

    def test_unrecognisable_option_reports_without_suggestion(self):
        result = _run_cli("--xyzzy", SAMPLE_PROJECT)
        output = _output(result)

        assert result.returncode == 1
        assert "Unknown option: --xyzzy" in output
        assert "did you mean" not in output

    def test_extra_positional_rejected(self):
        result = _run_cli(SAMPLE_PROJECT, "second_path")
        output = _output(result)

        assert result.returncode == 1
        assert "Unexpected extra argument(s): second_path" in output

    def test_clean_runs_only_after_project_path_is_validated(self):
        """`--clean <typo'd path>` must abort before deleting model/ and output/.

        Checked statically, not by running it: a functional version of this test
        would have to destroy the real model/ and output/ to detect a regression.
        """
        tree = _run_py_ast()
        rmtree_lines = [n.lineno for n in ast.walk(tree)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "rmtree"]
        guard_lines = [n.lineno for n in ast.walk(tree)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and "Project path not found" in n.value]
        assert rmtree_lines, "no shutil.rmtree call found in run.py"
        assert guard_lines, "project-path guard not found in run.py"
        assert min(rmtree_lines) > max(guard_lines)

    def test_known_flags_stays_in_sync_with_parse_branches(self):
        # _KNOWN_FLAGS drives both rejection and the did-you-mean hint; a flag with
        # a branch but no entry would be rejected despite working.
        assert _declared_flags() == _branch_flags()


class TestLayerScopedFlags:
    """The layer-scoped flags all take <layer> <path> and validate the layer.

    `--include-path-layer` had no coverage at all before 2026-08-18 — the AST check
    above only proves _KNOWN_FLAGS matches the parse branches, never that the flag
    behaves.
    """

    def test_include_path_layer_rejects_unknown_layer(self):
        result = _run_cli("--include-path-layer", "NoSuchLayer", PROJECT_ROOT, SAMPLE_PROJECT)

        assert result.returncode == 1
        assert "unknown layer" in _output(result).lower()

    def test_include_path_layer_rejects_missing_directory(self):
        result = _run_cli("--include-path-layer", "Layer1",
                          os.path.join(PROJECT_ROOT, "no_such_dir_xyz"), SAMPLE_PROJECT)

        assert result.returncode == 1
        assert "directory not found" in _output(result).lower()

    def test_include_path_layer_needs_two_arguments(self):
        result = _run_cli("--include-path-layer", "Layer1")

        assert result.returncode == 1
        assert "two arguments" in _output(result).lower()

    def test_old_include_path_name_is_rejected_with_a_suggestion(self):
        # Renamed 2026-08-18. No deprecation alias — the unknown-option handler's
        # difflib hint is what makes the rename self-correcting, so pin it.
        result = _run_cli("--include-path", "Layer1", PROJECT_ROOT, SAMPLE_PROJECT)

        out = _output(result)
        assert result.returncode == 1
        assert "unknown option" in out.lower()
        assert "--include-path-layer" in out

    def test_data_dictionary_layer_rejects_unknown_layer(self):
        result = _run_cli("--data-dictionary-layer", "NoSuchLayer",
                          os.path.join(PROJECT_ROOT, "engine", "config", "data_dictionary.csv"),
                          SAMPLE_PROJECT)

        assert result.returncode == 1
        assert "unknown layer" in _output(result).lower()

    def test_data_dictionary_layer_missing_file_exits_2(self):
        # Deliberately 2, matching --macros-layer. --include-path-layer uses 1 for a
        # missing dir; that inconsistency is known and recorded, not fixed here.
        result = _run_cli("--data-dictionary-layer", "Layer1",
                          os.path.join(PROJECT_ROOT, "no_such_dd.csv"), SAMPLE_PROJECT)

        assert result.returncode == 2


class TestHelp:
    def test_help_exits_zero_and_lists_options(self):
        result = _run_cli("--help")

        assert result.returncode == 0
        for flag in ("--clean", "--from-phase", "--selected-component", "--macros-layer",
                     "--data-dictionary-layer", "--include-path-layer"):
            assert flag in result.stdout

    def test_short_help_flag(self):
        assert _run_cli("-h").returncode == 0

    def test_help_needs_no_project_path(self):
        # --help is answered before the config load and path check, so it works
        # even when the rest of the command line is nonsense.
        assert _run_cli("--help", "--not-a-flag").returncode == 0


class TestFilterMode:
    def test_filter_mode_is_parsed_and_consumes_its_value(self):
        # Regression: --filter-mode had no parse branch, so it landed in the
        # positional list and became the project path.
        result = _run_cli("--filter-mode", "single_per_function", "___no_such_dir___")
        output = _output(result)

        assert result.returncode == 1
        assert "Unknown option" not in output
        assert "___no_such_dir___" in output

    def test_filter_mode_requires_a_value(self):
        result = _run_cli("--filter-mode")
        output = _output(result)

        assert result.returncode == 1
        assert "--filter-mode requires a mode argument" in output
