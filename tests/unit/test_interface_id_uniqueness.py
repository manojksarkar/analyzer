"""An interface id must identify exactly one entry.

`_id_seg` keeps only A-Z, dropping digits and underscores, so `UHP_HmacCom` and
`UHP_Hmac_Com2` both encode as UHPHMACCOM. Numbering was bucketed by the UNIT KEY, which
still tells those two apart -- so each was numbered independently and both emitted _01,
_02, _03. Measured on a real project: four ids each used by two functions.

In an ASPICE traceability matrix a duplicate id makes two entries indistinguishable, so
this is a document defect, not a cosmetic one.

The same mistake has now been made twice at different granularities -- first numbering by
FILE while the id encoded the unit, then by UNIT while the id encoded a lossy code of it.
Both are fixed by deriving the bucket and the id from ONE expression, which is what
`_iface_scope_key` is for.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import model_deriver as md


def _fn(component, unit_file, line, name):
    """A function in <component>/<unit_file>, as Phase 1 records one."""
    return {"qualifiedName": name, "parameters": [],
            "location": {"file": "%s/%s" % (component, unit_file), "line": line}}


class TestUnitsThatEncodeAlike:
    """Two units whose names differ only in digits or underscores share an id prefix."""

    BASE = "/proj"

    def _ids(self, functions):
        idx = md._build_interface_index(self.BASE, functions, {}, "Proj", None)
        md._enrich_interfaces(self.BASE, "Proj", functions, {}, idx, None)
        return [f["interfaceId"] for f in functions.values()]

    def test_two_units_encoding_alike_do_not_collide(self, monkeypatch):
        # `_fn_is_private` reads the whole model and the filesystem; visibility is not what
        # is under test here, so pin it.
        monkeypatch.setattr(md, "_fn_is_private", lambda *a, **k: False)
        functions = {
            "C|HmacCom|a|": _fn("C", "UHP_HmacCom.cpp", 10, "a"),
            "C|HmacCom|b|": _fn("C", "UHP_HmacCom.cpp", 20, "b"),
            "C|HmacCom2|c|": _fn("C", "UHP_Hmac_Com2.cpp", 10, "c"),
            "C|HmacCom2|d|": _fn("C", "UHP_Hmac_Com2.cpp", 20, "d"),
        }
        ids = self._ids(functions)
        assert len(set(ids)) == len(ids), (
            "two units encoding to the same code were numbered independently: %s" % ids)

    def test_a_single_unit_still_numbers_from_01(self, monkeypatch):
        monkeypatch.setattr(md, "_fn_is_private", lambda *a, **k: False)
        functions = {
            "C|U|a|": _fn("C", "U.cpp", 10, "a"),
            "C|U|b|": _fn("C", "U.cpp", 20, "b"),
        }
        ids = sorted(self._ids(functions))
        assert ids[0].endswith("_01") and ids[1].endswith("_02"), ids

    def test_public_and_private_number_separately(self, monkeypatch):
        # IF and PIF are different id spaces, so both may legitimately hold an _01.
        private = {"C|U|b|"}
        monkeypatch.setattr(md, "_fn_is_private",
                            lambda f, *a, **k: f.get("qualifiedName") == "b")
        functions = {
            "C|U|a|": _fn("C", "U.cpp", 10, "a"),
            "C|U|b|": _fn("C", "U.cpp", 20, "b"),
        }
        ids = self._ids(functions)
        assert len(set(ids)) == 2, ids
        assert any(i.startswith("IF_") for i in ids) and any(i.startswith("PIF_") for i in ids)


class TestScopeKeyIsTheIdsOwnKey:
    def test_the_bucket_key_matches_what_the_id_encodes(self):
        """If these ever diverge again the numbering silently collides, so assert the
        helper returns exactly the three codes the id is built from."""
        a = md._iface_scope_key(_fn("C", "UHP_HmacCom.cpp", 1, "x"), "/proj", "Proj", None)
        b = md._iface_scope_key(_fn("C", "UHP_Hmac_Com2.cpp", 1, "y"), "/proj", "Proj", None)
        assert a == b, (
            "these two units encode identically in an interface id, so they MUST share a "
            "numbering bucket: %s vs %s" % (a, b))
