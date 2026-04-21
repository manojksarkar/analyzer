"""
diagnose_assert.py - Diagnostic: what libclang location APIs are available
and which correctly identify ASSERT macro call sites.

Run from the flowchart directory:
    python tests/diagnose_assert.py
"""
import os
import sys
import tempfile
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import clang.cindex as ci

_ASSERT_RE = re.compile(
    r'^\s*(?:assert|static_assert|(?:[A-Z][A-Z0-9_]*_)*ASSERT)\s*\(',
    re.ASCII,
)

SRC_SIMPLE = (
    "#define SIMPLE_ASSERT(x)  if (!(x)) { __builtin_abort(); }\n"
    "\n"
    "void test_simple(int nrt) {\n"
    "    SIMPLE_ASSERT(nrt != 0);\n"
    "    int y = nrt + 1;\n"
    "}\n"
)

SRC_NESTED = (
    "#define INNER_ASSERT(x)   if (!(x)) { __builtin_abort(); }\n"
    "#define UTIL_DEBUG_ASSERT(x)  INNER_ASSERT(x)\n"
    "\n"
    "void test_nested(int nrt) {\n"
    "    UTIL_DEBUG_ASSERT(nrt != 0);\n"
    "    int y = nrt + 1;\n"
    "}\n"
)


def _check(line_1, col_1, src_lines):
    if line_1 < 1 or col_1 < 1:
        return False
    idx = line_1 - 1
    if 0 <= idx < len(src_lines):
        return bool(_ASSERT_RE.match(src_lines[idx][col_1 - 1:]))
    return False


def diagnose(label, src):
    print("\n" + "=" * 60)
    print("TEST: " + label)
    print("=" * 60)

    src_lines = src.splitlines(keepends=True)
    print("Source:")
    for i, ln in enumerate(src_lines, 1):
        print("  %2d: %s" % (i, ln.rstrip()))
    print()

    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w",
                                     delete=False, encoding="utf-8") as f:
        f.write(src)
        tmp_path = f.name

    try:
        index = ci.Index.create()
        tu = index.parse(
            tmp_path,
            args=["-std=c++14", "-x", "c++"],
            options=(
                ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
                | ci.TranslationUnit.PARSE_INCOMPLETE
            ),
        )

        def visit(cursor, depth=0):
            indent = "  " * depth
            if cursor.kind == ci.CursorKind.COMPOUND_STMT:
                for child in cursor.get_children():
                    print(indent + "Child: kind=%s" % child.kind.name)

                    # A: extent.start.get_expansion_location()
                    try:
                        fa, la, ca, oa = child.extent.start.get_expansion_location()
                        snippet = src_lines[la-1][ca-1:] if 0 < la <= len(src_lines) else "OOB"
                        print(indent + "  [A] extent.start.get_expansion_location() "
                              "line=%d col=%d  snippet=%r  MATCH=%s" %
                              (la, ca, snippet[:50], _check(la, ca, src_lines)))
                    except Exception as e:
                        print(indent + "  [A] EXCEPTION: %s" % e)

                    # B: cursor.location.get_expansion_location()
                    try:
                        fb, lb, cb, ob = child.location.get_expansion_location()
                        snippet = src_lines[lb-1][cb-1:] if 0 < lb <= len(src_lines) else "OOB"
                        print(indent + "  [B] cursor.location.get_expansion_location() "
                              "line=%d col=%d  snippet=%r  MATCH=%s" %
                              (lb, cb, snippet[:50], _check(lb, cb, src_lines)))
                    except Exception as e:
                        print(indent + "  [B] EXCEPTION: %s" % e)

                    # C: extent.start .line / .column
                    try:
                        lc = child.extent.start.line
                        cc = child.extent.start.column
                        snippet = src_lines[lc-1][cc-1:] if 0 < lc <= len(src_lines) else "OOB"
                        print(indent + "  [C] extent.start.line/column "
                              "line=%d col=%d  snippet=%r  MATCH=%s" %
                              (lc, cc, snippet[:50], _check(lc, cc, src_lines)))
                    except Exception as e:
                        print(indent + "  [C] EXCEPTION: %s" % e)

                    # D: cursor.location .line / .column
                    try:
                        ld = child.location.line
                        cd = child.location.column
                        snippet = src_lines[ld-1][cd-1:] if 0 < ld <= len(src_lines) else "OOB"
                        print(indent + "  [D] cursor.location.line/column "
                              "line=%d col=%d  snippet=%r  MATCH=%s" %
                              (ld, cd, snippet[:50], _check(ld, cd, src_lines)))
                    except Exception as e:
                        print(indent + "  [D] EXCEPTION: %s" % e)

                    print()
                return
            for child in cursor.get_children():
                visit(child, depth)

        for cursor in tu.cursor.get_children():
            if cursor.kind in (ci.CursorKind.FUNCTION_DECL,
                               ci.CursorKind.CXX_METHOD):
                print("Function: " + cursor.spelling)
                visit(cursor)
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    diagnose("Single-level ASSERT", SRC_SIMPLE)
    diagnose("Two-level nested ASSERT (UTIL_DEBUG_ASSERT -> INNER_ASSERT)", SRC_NESTED)
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
