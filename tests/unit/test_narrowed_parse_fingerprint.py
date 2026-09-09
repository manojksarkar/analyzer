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
from incremental.fingerprint import parse_fingerprint as _pf       # noqa: E402

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


class TestTheCheckoutRootIsNotPartOfTheFingerprint:
    """The bug that made narrowed parse inert for the life of the feature.

    `parse_fingerprint` hashes the clang args, which include `-I` paths. Every commit is checked
    out to its OWN directory (`workspaces/<pid>/<commit[:16]>`), so those paths differ between
    any two commits — the fingerprint differed on every run, the gate concluded "flags changed",
    and narrowed parse fell back to a full parse **100% of the time**. Correct output, none of
    the saving, and no error to say why.

    It was invisible because falling back is the safe branch: nothing failed, runs were just as
    slow as before. Found by `tools/verify_narrowed_parse.py` on its first successful run.
    """

    def test_two_checkouts_of_the_same_project_agree(self):
        pf = _pf
        a = pf(["-I/ws/proj/aaaaaaaaaaaaaaaa/src", "-DFOO=1"], base_path="/ws/proj/aaaaaaaaaaaaaaaa")
        b = pf(["-I/ws/proj/bbbbbbbbbbbbbbbb/src", "-DFOO=1"], base_path="/ws/proj/bbbbbbbbbbbbbbbb")
        assert a == b, "the checkout directory must not change the fingerprint"

    def test_windows_and_posix_separators_agree(self):
        """The checkout root arrives with backslashes while some args are built with forward
        ones, so a separator-sensitive comparison would trip on Windows only."""
        pf = _pf
        a = pf([r"-IC:\ws\proj\aaaa\src"], base_path=r"C:\ws\proj\aaaa")
        b = pf(["-IC:/ws/proj/aaaa/src"], base_path="C:/ws/proj/aaaa")
        assert a == b

    def test_a_real_flag_change_still_trips_the_gate(self):
        """The guard must keep guarding: a different define or include really is unsafe to
        merge against, and must still force a full parse."""
        pf = _pf
        base = "/ws/proj/aaaa"
        assert pf(["-I/ws/proj/aaaa/src", "-DFOO=1"], base_path=base) != \
               pf(["-I/ws/proj/aaaa/src", "-DFOO=2"], base_path=base)
        assert pf(["-I/ws/proj/aaaa/src"], base_path=base) != \
               pf(["-I/ws/proj/aaaa/src", "-I/opt/extra"], base_path=base)

    def test_include_order_still_matters(self):
        """Include order changes which header wins, so it must stay in the hash."""
        pf = _pf
        base = "/ws/proj/aaaa"
        assert pf(["-I/a", "-I/b"], base_path=base) != pf(["-I/b", "-I/a"], base_path=base)

    def test_toolchain_still_counts(self):
        pf = _pf
        assert pf(["-I/a"], toolchain="libclang-17") != pf(["-I/a"], toolchain="libclang-18")

    def test_no_base_path_is_tolerated(self):
        """Callers without a checkout root must still get a stable value, not a crash."""
        pf = _pf
        assert pf(["-I/a"], base_path="") == pf(["-I/a"])
