"""Regression: a macro #defined once per #if/#else branch must surface only the
branch libclang's preprocessor actually took — not both.

This drives the real parser (`parse_file` -> `_collect_macro_defs`, then
`_scan_defines`). It needs libclang, so it *skips* if `parser` can't be imported
(no libclang in this environment) — which is why the rest of the suite avoids
importing the parser module directly.
"""
import os
import sys
import shutil
import tempfile

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py with a throwaway project dir as its base (set via argv,
    which the module reads at import). Skips if libclang is unavailable."""
    base = tempfile.mkdtemp(prefix="anlz_cond_")
    old_argv = sys.argv
    sys.argv = ["parser.py", base]
    if _ENGINE not in sys.path:
        sys.path.insert(0, _ENGINE)
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        shutil.rmtree(base, ignore_errors=True)
        sys.argv = old_argv
        pytest.skip(f"parser/libclang unavailable: {e}")
    P._TEST_BASE = base
    yield P
    sys.argv = old_argv
    shutil.rmtree(base, ignore_errors=True)


def _somesome_values(P):
    return sorted(
        v["value"] for v in P.data_dictionary.values()
        if v.get("kind") == "define" and v.get("name") == "SOMESOME"
    )


def test_if_else_define_keeps_only_active_branch(parser_mod):
    P = parser_mod
    base = P._TEST_BASE
    with open(os.path.join(base, "defs.h"), "w") as f:
        f.write(
            "#define ALWAYS 1\n"
            "#if defined(SOMETHING)\n"
            "#define SOMESOME value1\n"
            "#else\n"
            "#define SOMESOME value2\n"
            "#endif\n"
        )
    cpp = os.path.join(base, "unit.cpp")
    with open(cpp, "w") as f:
        f.write('#include "defs.h"\nint f(){ return SOMESOME + ALWAYS; }\n')

    P.parse_file(cpp)          # collects the active macro line via libclang
    P._scan_defines()          # picks the active #define branch

    # SOMETHING is not defined -> only the #else branch survives, exactly once.
    assert _somesome_values(P) == ["value2"]
    # a non-conditional macro in the same file is unaffected
    assert any(v.get("name") == "ALWAYS" for v in P.data_dictionary.values())
