"""Unit tests for src/incremental/hashing.py — entity hashing (M1.2)."""
import hashlib
import os
import re
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from incremental.hashing import hash_cursor, hash_macro_text, hash_tokens


class TestHashTokens:
    def test_full_sha256_hex(self):
        h = hash_tokens(["int", "add", "(", ")"])
        assert re.fullmatch(r"[0-9a-f]{64}", h)

    def test_deterministic(self):
        toks = ["return", "a", "+", "b", ";"]
        assert hash_tokens(toks) == hash_tokens(list(toks))

    def test_different_tokens_differ(self):
        assert hash_tokens(["a", "+", "b"]) != hash_tokens(["a", "-", "b"])

    def test_separator_prevents_concatenation_collision(self):
        # "a","b" must not hash the same as "ab" — the separator guards this.
        assert hash_tokens(["a", "b"]) != hash_tokens(["ab"])

    def test_comment_prefix_changes_hash(self):
        toks = ["x", "=", "1"]
        assert hash_tokens(toks) != hash_tokens(toks, comment="// doc")

    def test_comment_value_matters(self):
        toks = ["x", "=", "1"]
        assert hash_tokens(toks, comment="// a") != hash_tokens(toks, comment="// b")

    def test_empty_comment_is_noop(self):
        toks = ["x"]
        assert hash_tokens(toks, comment="") == hash_tokens(toks)


class TestHashMacroText:
    def test_whitespace_insensitive(self):
        assert hash_macro_text("#define MAX  10") == hash_macro_text("#define   MAX 10")

    def test_indentation_and_newlines_collapse(self):
        assert hash_macro_text("#define A 1") == hash_macro_text("#define\tA\n   1")

    def test_line_continuation_collapses(self):
        # Same whitespace-separated tokens; only the \-continuation + indentation differ.
        one_line = "#define F(x) do { x; } while (0)"
        multi = "#define F(x) do { \\\n    x; \\\n } while (0)"
        assert hash_macro_text(one_line) == hash_macro_text(multi)

    def test_value_change_differs(self):
        assert hash_macro_text("#define MAX 10") != hash_macro_text("#define MAX 11")

    def test_full_sha256_hex_and_deterministic(self):
        h1 = hash_macro_text("#define K 42")
        h2 = hash_macro_text("#define K 42")
        assert h1 == h2 and re.fullmatch(r"[0-9a-f]{64}", h1)


class TestHashCursorNeverHashesNothing:
    """`sha256("")` must never be an entity's hash.

    libclang returns no tokens for some valid cursors (a declaration produced by a macro
    expansion is the common one) with no error and a correct extent. hash_cursor used to
    hash the empty token list, giving every such entity the SAME constant -- so each was
    classified unchanged in every comparison forever and kept the first version's
    flowchart and description. These tests pin the fallbacks that replaced that.
    """

    EMPTY = hashlib.sha256(b"").hexdigest()

    class _Loc:
        def __init__(self, path, line, offset):
            self.file = type("F", (), {"name": path})()
            self.line, self.offset = line, offset

    class _Extent:
        def __init__(self, start, end):
            self.start, self.end = start, end

    class _Cursor:
        """A cursor whose tokens are unavailable, as libclang really presents it: a
        valid extent and location, and an empty token iterator."""

        def __init__(self, path, lo, hi, *, raises=False, spelling="fn"):
            self._raises, self.spelling = raises, spelling
            loc = TestHashCursorNeverHashesNothing._Loc
            self.location = loc(path, 1, lo)
            self.extent = TestHashCursorNeverHashesNothing._Extent(
                loc(path, 1, lo), loc(path, 3, hi))

        def get_tokens(self):
            if self._raises:
                raise RuntimeError("libclang says no")
            return iter(())

    def _src(self, tmp_path, text, name="s.cpp"):
        """Write in BINARY and return (path, byte length).

        Text mode would translate newlines on Windows and shift every offset, so the
        extent this test hands the cursor would not be the extent libclang would give.
        """
        p = tmp_path / name
        data = text.encode("utf-8")
        p.write_bytes(data)
        return str(p), len(data)

    def _cursor_over(self, tmp_path, text, name="s.cpp", **kw):
        path, n = self._src(tmp_path, text, name)
        return self._Cursor(path, 0, n, **kw)

    def test_token_less_cursor_is_not_the_empty_hash(self, tmp_path):
        h = hash_cursor(self._cursor_over(tmp_path, "void f(void) { int x = 1; }"))
        assert h != self.EMPTY

    def test_token_less_cursors_with_different_bodies_differ(self, tmp_path):
        a = self._cursor_over(tmp_path, "void f(void) { int x = 1; }")
        b = self._cursor_over(tmp_path, "void f(void) { int x = 2; }", "t.cpp")
        assert hash_cursor(a) != hash_cursor(b)

    def test_reformatting_still_does_not_change_the_hash(self, tmp_path):
        one = "void f(void) { int x = 1; }"
        many = "void f(void) {\n    int x = 1;\n}"
        a = self._cursor_over(tmp_path, one)
        b = self._cursor_over(tmp_path, many, "t.cpp")
        # Whitespace-split keeps the reformat-insensitivity that made tokens attractive.
        assert hash_cursor(a) == hash_cursor(b)

    def test_get_tokens_raising_is_handled(self, tmp_path):
        c = self._cursor_over(tmp_path, "void f(void) { int x = 1; }", raises=True)
        assert hash_cursor(c) != self.EMPTY

    def test_unreadable_source_falls_back_to_identity_not_a_constant(self):
        c1 = self._Cursor("/no/such/file.cpp", 0, 10, spelling="alpha")
        c2 = self._Cursor("/no/such/file.cpp", 0, 10, spelling="beta")
        h1, h2 = hash_cursor(c1), hash_cursor(c2)
        assert h1 != self.EMPTY and h2 != self.EMPTY
        assert h1 != h2, "two unhashable entities must not collide onto one value"

    def test_fallback_use_is_counted(self, tmp_path):
        before = dict(hash_cursor.fallbacks)
        hash_cursor(self._cursor_over(tmp_path, "void f(void) { int x = 1; }"))
        assert hash_cursor.fallbacks["extent_text"] == before["extent_text"] + 1

    def test_normal_cursor_still_uses_tokens(self):
        class Tok:
            def __init__(self, s):
                self.spelling = s

        class Ok:
            def get_tokens(self):
                return iter([Tok("int"), Tok("x")])

        assert hash_cursor(Ok()) == hash_tokens(["int", "x"])
