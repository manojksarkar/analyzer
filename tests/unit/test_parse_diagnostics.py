"""Phase 1 parse diagnostics — the trail for "why is my function missing?".

Covers the pieces that decide what the end-of-phase log block says:
  - the function-definition text scan (the only way to see a definition libclang
    never reported, e.g. one inside an inactive #if branch)
  - drop-reason counting and its sample cap
  - is_project_file memoization agreeing with the uncached computation

Follows the import pattern in test_define_conditional.py: parser.py reads argv at
import and needs libclang, so the module is imported behind a fixture that skips
when libclang is unavailable.
"""
import os
import shutil
import sys
import tempfile

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")


def _clear_path_caches(mod):
    """Drop parser's path caches. Reaching into module state directly rather than asking
    parser.py for a reset helper: nothing in the pipeline ever reassigns MODULE_BASE_PATH,
    so such a helper would be dead production code that exists only for these tests."""
    mod._project_file_cache.clear()
    mod._under_base_cache.clear()


@pytest.fixture(scope="module")
def P():
    """Import parser.py against a throwaway base dir. Skips without libclang."""
    base = tempfile.mkdtemp(prefix="anlz_diag_")
    old_argv = sys.argv
    sys.argv = ["parser.py", base]
    if _ENGINE not in sys.path:
        sys.path.insert(0, _ENGINE)
    try:
        import parser as mod
    except Exception as exc:  # libclang missing / load failure
        shutil.rmtree(base, ignore_errors=True)
        sys.argv = old_argv
        pytest.skip(f"parser/libclang unavailable: {exc}")
    saved = mod.MODULE_BASE_PATH
    mod.MODULE_BASE_PATH = base
    _clear_path_caches(mod)  # base changed -> cached verdicts are stale
    yield mod
    mod.MODULE_BASE_PATH = saved
    _clear_path_caches(mod)
    sys.argv = old_argv
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_diag(P):
    """Diagnostics state is module-global; reset it around every test."""
    P._diag_unrecorded.clear()
    P._diag_recorded_names.clear()
    P._diag_counts.clear()
    P._diag_drop_samples.clear()
    yield
    P._diag_unrecorded.clear()
    P._diag_recorded_names.clear()
    P._diag_counts.clear()
    P._diag_drop_samples.clear()


# ---------------------------------------------------------------------------
# The text scan
# ---------------------------------------------------------------------------

class TestScanUnrecordedFunctions:
    def test_flags_a_definition_absent_from_the_model(self, P):
        """The whole point: a definition present in the text but not in the model.
        This is the inactive-#if case — libclang never produced a cursor for it."""
        lines = ["PRIVATE int gatedFunction(int a) {\n", "    return a;\n", "}\n"]
        P._scan_unrecorded_functions("Layer1/Diag/Gated.cpp", lines)
        assert [(f, n) for f, _, n in P._diag_unrecorded] == [
            ("Layer1/Diag/Gated.cpp", "gatedFunction")
        ]

    def test_recorded_functions_are_not_flagged(self, P):
        """A definition that DID reach the model must stay silent, or the hint list
        is just a list of every function in the project."""
        P._diag_recorded_names.add("presentFunction")
        P._scan_unrecorded_functions(
            "a.cpp", ["PUBLIC void presentFunction(void) {\n", "}\n"]
        )
        assert P._diag_unrecorded == []

    @pytest.mark.parametrize("line", [
        "if (x > 0) {",
        "while (running) {",
        "for (int i = 0; i < n; i++) {",
        "switch (kind) {",
        "return compute(a, b);",
        "// int commentedOut(void) {",
        "#define MACRO_CALL(a) do_something(a)",
        "  * doxygen(void) {",
    ])
    def test_non_definitions_are_skipped(self, P, line):
        """Control flow, comments and preprocessor lines share the shape but are not
        definitions. False positives here would make the block useless."""
        P._scan_unrecorded_functions("a.cpp", [line + "\n"])
        assert P._diag_unrecorded == []

    def test_declaration_with_semicolon_is_not_a_definition(self, P):
        P._scan_unrecorded_functions("a.h", ["int justDeclared(int a);\n"])
        assert P._diag_unrecorded == []

    def test_sample_list_is_capped(self, P):
        """Bounded output: the log must not balloon on a pathological project."""
        lines = [f"PRIVATE int fn{i}(void) {{\n" for i in range(P._DIAG_SAMPLE_CAP * 5)]
        P._scan_unrecorded_functions("many.cpp", lines)
        assert len(P._diag_unrecorded) == P._DIAG_SAMPLE_CAP

    def test_absurdly_long_line_is_ignored(self, P):
        """Length guard: a generated/minified line is not worth the regex risk."""
        P._scan_unrecorded_functions(
            "gen.cpp", ["int f(" + "int a," * 200 + "int z) {\n"]
        )
        assert P._diag_unrecorded == []


# ---------------------------------------------------------------------------
# Drop-reason accounting
# ---------------------------------------------------------------------------

class TestDiagDrop:
    def test_counter_increments_without_a_cursor(self, P):
        for _ in range(3):
            P._diag_drop("dedup-hit")
        assert P._diag_counts["dedup-hit"] == 3

    def test_counter_keeps_counting_past_the_sample_cap(self, P):
        """The count must stay exact even once sampling stops — the tally is what
        tells you the scale of the problem."""
        total = P._DIAG_SAMPLE_CAP * 3
        for _ in range(total):
            P._diag_drop("not-project-file", cursor=None)
        assert P._diag_counts["not-project-file"] == total
        assert len(P._diag_drop_samples["not-project-file"]) == 0

    def test_a_broken_cursor_does_not_raise(self, P):
        """Diagnostics are never allowed to break a parse. A cursor whose location
        explodes must be counted and otherwise ignored."""
        class Boom:
            @property
            def location(self):
                raise RuntimeError("no location")

        P._diag_drop("kind=FUNCTION_TEMPLATE", cursor=Boom())
        assert P._diag_counts["kind=FUNCTION_TEMPLATE"] == 1


# ---------------------------------------------------------------------------
# Memoization
# ---------------------------------------------------------------------------

class TestIsProjectFileCache:
    def test_cached_result_matches_uncached(self, P):
        """The cache must be a pure speedup. Same answer, every path."""
        candidates = [
            os.path.join(P.MODULE_BASE_PATH, "Layer1", "a.cpp"),
            os.path.join(P.MODULE_BASE_PATH, "emulator_stub.cpp"),
            os.path.join(os.sep, "usr", "include", "stdio.h"),
            "",
        ]
        expected = [P._compute_is_project_file(c) for c in candidates]
        _clear_path_caches(P)
        assert [P.is_project_file(c) for c in candidates] == expected
        # Second pass now served from cache — must not change.
        assert [P.is_project_file(c) for c in candidates] == expected

    def test_repeated_calls_compute_once(self, P):
        path = os.path.join(P.MODULE_BASE_PATH, "Layer1", "b.cpp")
        _clear_path_caches(P)
        calls = {"n": 0}
        original = P._compute_is_project_file

        def counting(fp):
            calls["n"] += 1
            return original(fp)

        P._compute_is_project_file = counting
        try:
            for _ in range(25):
                P.is_project_file(path)
        finally:
            P._compute_is_project_file = original
        assert calls["n"] == 1

    def test_verdict_is_stored_under_the_raw_path(self, P):
        """The cache key is the path as passed in, not a normalized form — callers hand
        in whatever libclang reported, and a mismatch here would silently disable the
        cache (correct results, no speedup, and nothing to notice it)."""
        path = os.path.join(P.MODULE_BASE_PATH, "Layer1", "c.cpp")
        _clear_path_caches(P)
        verdict = P.is_project_file(path)
        assert P._project_file_cache[path] is verdict
