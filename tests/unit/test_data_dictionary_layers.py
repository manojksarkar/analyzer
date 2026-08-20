"""Per-layer data dictionaries: layers partition, they do not inherit from each other.

The governing rule, decided with the user and applied to every per-layer input:

    Resolving anything for layer L uses **global + L only**.
    Another layer's entries are never consulted.

For the data dictionary that means the lookup has three tiers — the layer's own
entry, then the global tier (libclang builtins + the project-wide CSV), then the
primitive fallback / "NA". Two layers defining one type name are two different
types, not a conflict to reconcile.

`utils.get_range` is pure and needs no libclang, so the lookup tests run
everywhere. The merge tests import `parser` and skip without libclang, mirroring
test_data_dictionary_csv.py.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(PROJECT_ROOT, "engine")

if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from utils import get_range  # noqa: E402  (engine/ must be on sys.path first)


# ---------------------------------------------------------------------------
# The lookup rule (utils.get_range) — pure, no libclang
# ---------------------------------------------------------------------------

class TestLayerIsolation:
    """`ABC` used in Layer2, absent from Layer2's dictionary, present in Layer1's.

    Layer2 must resolve to the global/parsed value or NA — never Layer1's. Asserted
    once per lookup path, because a test that only covers the direct hit passes
    while the qualifiedName scan and the alias recursion still leak.
    """

    def test_direct_hit_is_refused(self):
        # Path 1: Layer1 wrote the bare key (no collision at parse time).
        dd = {"ABC": {"kind": "typedef", "range": "0-7", "layer": "Layer1"}}
        assert get_range("ABC", dd, "Layer1") == "0-7"
        assert get_range("ABC", dd, "Layer2") == "NA"

    def test_qualified_name_scan_is_refused(self):
        # Path 2: the entry is keyed by something else, so only the qualifiedName
        # sweep can reach it. This is the side door that a direct-hit-only guard
        # leaves wide open.
        dd = {
            "typedef@ABC:Layer1/Types.h:4": {
                "kind": "typedef", "qualifiedName": "ABC",
                "range": "0-7", "layer": "Layer1",
            }
        }
        assert get_range("ABC", dd, "Layer1") == "0-7"
        assert get_range("ABC", dd, "Layer2") == "NA"

    def test_alias_chain_is_refused(self):
        # Path 3: ABC -> Handle_t. Resolving the alias must carry the layer, or the
        # recursion picks up another layer's Handle_t one hop down.
        dd = {
            "ABC": {"kind": "typedef", "underlyingType": "Handle_t",
                    "range": "NA", "layer": "Layer2"},
            "Handle_t": {"kind": "typedef", "range": "0-31", "layer": "Layer1"},
        }
        assert get_range("ABC", dd, "Layer2") == "NA"
        # Same chain inside Layer1 resolves, proving the chain itself works.
        dd["ABC"]["layer"] = "Layer1"
        assert get_range("ABC", dd, "Layer1") == "0-31"

    def test_global_tier_answers_every_layer(self):
        # layer None = global (builtins, project-wide CSV): visible to everyone.
        dd = {"ABC": {"kind": "typedef", "range": "0-9", "layer": None}}
        assert get_range("ABC", dd, "Layer1") == "0-9"
        assert get_range("ABC", dd, "Layer2") == "0-9"

    def test_layer_overrides_global(self):
        dd = {
            "ABC": {"kind": "typedef", "range": "0-9", "layer": None},
            "ABC@Layer2": {"kind": "typedef", "range": "0-500", "layer": "Layer2"},
        }
        assert get_range("ABC", dd, "Layer2") == "0-500"   # own entry wins
        assert get_range("ABC", dd, "Layer1") == "0-9"     # falls to global
        assert get_range("ABC", dd) == "0-9"               # no layer -> unscoped


class TestSameNameTwoLayers:
    """A name defined in two layers is two answers, not a conflict."""

    def test_each_layer_gets_its_own(self):
        dd = {
            "BufferSize_t": {"kind": "typedef", "range": "0-1023", "layer": "Layer1"},
            "BufferSize_t@Layer2": {"kind": "typedef", "range": "0-65535", "layer": "Layer2"},
        }
        assert get_range("BufferSize_t", dd, "Layer1") == "0-1023"
        assert get_range("BufferSize_t", dd, "Layer2") == "0-65535"

    def test_third_layer_sees_neither(self):
        dd = {
            "BufferSize_t": {"kind": "typedef", "range": "0-1023", "layer": "Layer1"},
            "BufferSize_t@Layer2": {"kind": "typedef", "range": "0-65535", "layer": "Layer2"},
        }
        assert get_range("BufferSize_t", dd, "Layer3") == "NA"


class TestUnscopedBehaviourUnchanged:
    """layer=None keeps exactly the pre-layer behaviour for every existing caller."""

    def test_entries_without_a_layer_field_still_resolve(self):
        # Nothing stamped: a dictionary written before this change, or a hand-built
        # one in another test module.
        dd = {"Speed": {"kind": "typedef", "range": "0-255"}}
        assert get_range("Speed", dd) == "0-255"
        assert get_range("Speed", dd, "Layer1") == "0-255"

    def test_no_layer_argument_ignores_the_stamp(self):
        dd = {"ABC": {"kind": "typedef", "range": "0-7", "layer": "Layer1"}}
        assert get_range("ABC", dd) == "0-7"


# ---------------------------------------------------------------------------
# The merge rule (parser) — needs libclang
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (it reads argv at import). Skips if libclang is unavailable."""
    old_argv = sys.argv
    sys.argv = ["parser.py", PROJECT_ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


@pytest.fixture
def dd(parser_mod):
    """Clean parser.data_dictionary per test, restored afterwards."""
    saved = dict(parser_mod.data_dictionary)
    saved_files = dict(parser_mod.entity_files)
    parser_mod.data_dictionary.clear()
    yield parser_mod.data_dictionary
    parser_mod.data_dictionary.clear()
    parser_mod.data_dictionary.update(saved)
    parser_mod.entity_files.clear()
    parser_mod.entity_files.update(saved_files)


def _csv(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestPerLayerMerge:

    def test_two_layers_same_name_both_survive(self, parser_mod, dd, tmp_path):
        one = _csv(tmp_path, "l1.csv",
                   "Name,Kind,EntryName,Range,Comment\nBufferSize_t,typedef,,0-1023,L1\n")
        two = _csv(tmp_path, "l2.csv",
                   "Name,Kind,EntryName,Range,Comment\nBufferSize_t,typedef,,0-65535,L2\n")
        parser_mod._merge_dd_rows(one, "Layer1")
        parser_mod._merge_dd_rows(two, "Layer2")
        # Pre-change this was one entry and the second silently won for everyone.
        assert get_range("BufferSize_t", dd, "Layer1") == "0-1023"
        assert get_range("BufferSize_t", dd, "Layer2") == "0-65535"

    def test_layer_rows_do_not_touch_the_global_entry(self, parser_mod, dd, tmp_path):
        dd["Speed_t"] = {"kind": "typedef", "range": "0-9", "layer": None}
        path = _csv(tmp_path, "l1.csv",
                    "Name,Kind,EntryName,Range,Comment\nSpeed_t,typedef,,0-4000,L1\n")
        parser_mod._merge_dd_rows(path, "Layer1")
        assert dd["Speed_t"]["range"] == "0-9"          # global untouched
        assert get_range("Speed_t", dd, "Layer1") == "0-4000"
        assert get_range("Speed_t", dd, "Layer2") == "0-9"

    def test_same_layer_twice_is_last_wins(self, parser_mod, dd, tmp_path):
        a = _csv(tmp_path, "a.csv",
                 "Name,Kind,EntryName,Range,Comment\nTag_t,typedef,,0-1,first\n")
        b = _csv(tmp_path, "b.csv",
                 "Name,Kind,EntryName,Range,Comment\nTag_t,typedef,,0-2,second\n")
        parser_mod._merge_dd_rows(a, "Layer1")
        parser_mod._merge_dd_rows(b, "Layer1")
        assert get_range("Tag_t", dd, "Layer1") == "0-2"

    def test_project_wide_merge_is_unscoped(self, parser_mod, dd, tmp_path):
        path = _csv(tmp_path, "g.csv",
                    "Name,Kind,EntryName,Range,Comment\nGlobal_t,typedef,,0-3,g\n")
        parser_mod._merge_external_data_dictionary(path)
        assert dd["Global_t"]["layer"] is None
        assert get_range("Global_t", dd, "Layer1") == "0-3"
        assert get_range("Global_t", dd, "Layer9") == "0-3"

    def test_child_rows_attach_to_the_layer_entry(self, parser_mod, dd, tmp_path):
        dd["Mode"] = {"kind": "enum", "range": "0-1", "layer": None,
                      "enumerators": [{"name": "GLOBAL_ONLY", "value": 0}]}
        path = _csv(tmp_path, "l1.csv",
                    "Name,Kind,EntryName,Range,Comment\n"
                    "Mode,enum,,0-2,L1 mode\n"
                    ",enumerator,MODE_IDLE,0,idle\n"
                    ",enumerator,MODE_BUSY,1,busy\n")
        parser_mod._merge_dd_rows(path, "Layer1")
        names = [e["name"] for e in dd["Mode@Layer1"]["enumerators"]]
        assert names == ["MODE_IDLE", "MODE_BUSY"]
        # The global entry keeps its own enumerator list.
        assert [e["name"] for e in dd["Mode"]["enumerators"]] == ["GLOBAL_ONLY"]

    def test_missing_layer_file_exits_2(self, parser_mod):
        with pytest.raises(SystemExit) as exc:
            parser_mod._merge_dd_rows(os.path.join(PROJECT_ROOT, "no_such_dd.csv"), "Layer1")
        assert exc.value.code == 2


class TestCollisionKeyBookkeeping:
    """The disambiguated key must stay resolvable by the narrowed-parse merge."""

    def test_layer_key_registers_its_real_file(self, parser_mod, dd):
        loc1 = {"file": "Layer1/Types.h", "line": 4}
        loc2 = {"file": "Layer2/Types.h", "line": 9}
        parser_mod._dd_store("Status", {"kind": "enum", "range": "0-1"}, "Layer1", loc1)
        key = parser_mod._dd_store("Status", {"kind": "enum", "range": "0-5"}, "Layer2", loc2)
        assert key == "Status@Layer2"
        # parse_merge._file_of falls back to the text after "@" when entity_files has
        # no entry — for `Status@Layer2` that would be the LAYER name, which matches no
        # dropped file, so the entry would never refresh. The real file must be recorded.
        assert parser_mod.entity_files["Status@Layer2"] == "Layer2/Types.h"

    def test_same_layer_redefinition_keeps_the_bare_key(self, parser_mod, dd):
        loc = {"file": "Layer1/Types.h", "line": 4}
        parser_mod._dd_store("Status", {"kind": "enum", "range": "0-1"}, "Layer1", loc)
        key = parser_mod._dd_store("Status", {"kind": "enum", "range": "0-5"}, "Layer1", loc)
        assert key == "Status"
        assert dd["Status"]["range"] == "0-5"

    def test_collision_is_recorded_for_the_log(self, parser_mod, dd):
        parser_mod._dd_collisions.clear()
        parser_mod._dd_store("Status", {"kind": "enum"}, "Layer1", {"file": "a.h", "line": 1})
        parser_mod._dd_store("Status", {"kind": "enum"}, "Layer2", {"file": "b.h", "line": 1})
        assert parser_mod._dd_collisions["Status"] == {"Layer1", "Layer2"}
        parser_mod._dd_collisions.clear()
