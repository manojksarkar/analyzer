"""The narrowed-parse fingerprint gate (M4.6) — where the BASELINE's fingerprint comes from.

If the clang flags / std / toolchain changed since the baseline was parsed, its skeleton was built
differently and merging a partial parse into it would be unsound, so the run must fall back to a
full parse. The baseline's fingerprint now comes from the store (versions.parse_fingerprint, doc
07 §3) rather than the baseline's parse-dir metadata.json.

Narrowed parse is opt-in (`--narrowed-parse`) and has no end-to-end coverage, so this pins at
least the source-precedence rule the storage migration changed.
"""
import os
import sys

import pytest

_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from incremental.engine import _baseline_parse_fingerprint as fp   # noqa: E402

pytestmark = pytest.mark.unit


def test_store_value_wins():
    """The DB is authoritative: a stale parse-dir snapshot must not override it."""
    assert fp("from-db", {"metadata": {"parseFingerprint": "from-file"}}) == "from-db"


def test_falls_back_to_the_parse_dir_snapshot():
    """Versions written before versions.parse_fingerprint was populated still gate correctly."""
    assert fp(None, {"metadata": {"parseFingerprint": "from-file"}}) == "from-file"


@pytest.mark.parametrize("base_fingerprint, base_model", [
    (None, {}),                                   # nothing anywhere
    (None, {"metadata": {}}),                     # metadata present but no fingerprint
    (None, {"metadata": None}),                   # metadata explicitly null
    ("", {"metadata": {"parseFingerprint": ""}}),  # blank both sides
])
def test_missing_everywhere_is_none(base_fingerprint, base_model):
    """No fingerprint disables the gate (the caller only compares when BOTH sides have one) —
    it must not raise, which would abort an otherwise valid narrowed parse."""
    assert fp(base_fingerprint, base_model) is None or fp(base_fingerprint, base_model) == ""


def test_none_model_is_tolerated():
    assert fp(None, None) is None
