"""Unit tests for src/incremental/hashing.py — entity hashing (M1.2)."""
import os
import re
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.hashing import hash_tokens, hash_macro_text


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
