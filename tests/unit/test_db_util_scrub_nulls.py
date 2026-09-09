"""No NUL character may reach the database.

PostgreSQL has no representation for one in `text` or in `jsonb`, so the driver raises
instead of truncating:

    psycopg.errors.UntranslatableCharacter: unsupported Unicode escape sequence
    DETAIL:  \\u0000 cannot be converted to text.

Python strings and JSON files hold one happily, so a NUL arriving in a doc comment, a
`returnExpr` sliced out of source, or an LLM response crosses the whole pipeline unnoticed
and kills the run on the final INSERT — after the parse and every LLM call are paid for.
Measured on a real project: 17 minutes, 3.7M tokens, then Phase 2 died on
`INSERT INTO content_blobs` because one description carried one NUL.

These tests pin the removal, and the two properties that make it safe to do it in the
bulk-insert helpers: the content hash is taken on the scrubbed payload (so a
content-addressed blob is still keyed on its own content), and a row with nothing to fix
is passed through untouched rather than rebuilt.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.db_util import _scrubbed, scrub_nulls, scrub_stats

NUL = "\x00"


def _has_nul(value):
    """True if a NUL survives anywhere inside a JSON-ish value."""
    if isinstance(value, str):
        return NUL in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


class TestScrubNulls:
    def test_removes_a_nul_from_a_plain_string(self):
        assert scrub_nulls("head index" + NUL + " wrapped") == "head index wrapped"

    def test_reaches_into_a_nested_payload(self):
        payload = {"description": "logged the RPM task" + NUL,
                   "phases": ["read" + NUL + " entry", "return"],
                   "parameters": [{"name": "idx" + NUL, "type": "UINT32"}]}
        assert not _has_nul(scrub_nulls(payload))

    def test_scrubs_dict_keys_too(self):
        got = scrub_nulls({"na" + NUL + "me": "x"})
        assert got == {"name": "x"} and not _has_nul(got)

    def test_leaves_non_strings_alone(self):
        payload = {"line": 42, "isVisible": True, "value": None, "ratio": 1.5}
        assert scrub_nulls(payload) == payload

    def test_a_clean_value_is_returned_UNCHANGED_not_rebuilt(self):
        # The scrub runs on every bulk insert, so the common case must not copy.
        payload = {"description": "ordinary text", "phases": ["a", "b"]}
        assert scrub_nulls(payload) is payload

    def test_counts_what_it_repaired(self):
        before = scrub_stats["strings"]
        scrub_nulls({"a": "x" + NUL, "b": "y" + NUL, "c": "clean"})
        assert scrub_stats["strings"] == before + 2, "silent repair is how this went unnoticed"

    def test_only_the_nul_goes(self):
        # Tabs, newlines and non-ASCII are all storable -- do not over-clean.
        s = "line1\n\tvalue é 中" + NUL
        assert scrub_nulls(s) == "line1\n\tvalue é 中"


class TestScrubbedRows:
    def test_rows_are_cleaned(self):
        rows = [{"payload": {"description": "bad" + NUL}}, {"payload": {"description": "ok"}}]
        assert not _has_nul(_scrubbed(rows))

    def test_clean_rows_pass_through_as_the_same_list(self):
        rows = [{"payload": {"description": "ok"}}]
        assert _scrubbed(rows) is rows

    def test_untouched_rows_keep_their_identity(self):
        clean = {"payload": {"description": "ok"}}
        rows = [{"payload": {"description": "bad" + NUL}}, clean]
        assert _scrubbed(rows)[1] is clean


class TestContentHashMatchesWhatIsStored:
    """The hash must describe the payload the database ends up holding.

    `content_blobs` is content-addressed: hashing the pre-scrub payload would key a row on
    bytes the row does not contain, and the same function would hash differently depending
    on whether its NUL had been removed yet -- so the reuse index would never match it.
    """

    def test_hash_ignores_a_nul(self):
        from core.model_store import _content_hash
        assert (_content_hash({"description": "wrapped head index" + NUL})
                == _content_hash({"description": "wrapped head index"}))

    def test_hash_still_distinguishes_real_differences(self):
        from core.model_store import _content_hash
        assert _content_hash({"description": "a"}) != _content_hash({"description": "b"})
