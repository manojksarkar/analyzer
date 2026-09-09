"""Assignment detection: parser `_is_assign_op`.

`_is_assign_op` must find the operator past the LHS extent, not at a fixed token
index: a multi-token LHS (`w->id = x`, `g_a[i] = x`) is the common case in real
code, and a missed assignment is recorded as a READ, which corrupts
writesGlobalIds and the In/Out direction derived from it.
"""
import os
import sys

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


class _Tok:
    def __init__(self, spelling, start):
        self.spelling = spelling
        self.extent = type("E", (), {"start": type("P", (), {"offset": start})()})()


class _Child:
    def __init__(self, end):
        self.extent = type("E", (), {"end": type("P", (), {"offset": end})()})()


class _Cursor:
    """Minimal stand-in: a BINARY_OPERATOR with a known LHS extent and tokens."""
    def __init__(self, kind, lhs_end, tokens):
        self.kind = kind
        self._lhs_end = lhs_end
        self._tokens = tokens

    def get_children(self):
        return [_Child(self._lhs_end), _Child(self._lhs_end)]

    def get_tokens(self):
        return list(self._tokens)


def _binop(lhs_end, spellings_with_offsets):
    from parser import cindex
    toks = [_Tok(s, o) for s, o in spellings_with_offsets]
    return _Cursor(cindex.CursorKind.BINARY_OPERATOR, lhs_end, toks)


def test_single_token_lhs_is_a_write():
    from parser import _is_assign_op
    # g_count = 5
    cur = _binop(7, [("g_count", 0), ("=", 8), ("5", 10)])
    assert _is_assign_op(cur) == (True, False)


def test_multi_token_lhs_is_still_a_write():
    from parser import _is_assign_op
    # w->id = id   -- the regression: tokens[1] is "->", not "="
    cur = _binop(5, [("w", 0), ("->", 1), ("id", 3), ("=", 6), ("id", 8)])
    assert _is_assign_op(cur) == (True, False)


def test_subscripted_lhs_is_still_a_write():
    from parser import _is_assign_op
    # g_a[i] = 5
    cur = _binop(6, [("g_a", 0), ("[", 3), ("i", 4), ("]", 5), ("=", 7), ("5", 9)])
    assert _is_assign_op(cur) == (True, False)


def test_compound_assignment_on_multi_token_lhs_is_read_and_write():
    from parser import _is_assign_op
    # s->n += 1
    cur = _binop(4, [("s", 0), ("->", 1), ("n", 3), ("+=", 5), ("1", 8)])
    assert _is_assign_op(cur) == (True, True)


def test_comparison_is_not_a_write():
    from parser import _is_assign_op
    # e.lba == lba   -- must not be mistaken for an assignment
    cur = _binop(5, [("e", 0), (".", 1), ("lba", 2), ("==", 6), ("lba", 9)])
    assert _is_assign_op(cur) == (False, False)
