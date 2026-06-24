"""Unit tests for cross-version reuse-index lookup (M3.7).

carry_forward_from_index copies an impacted entity's stored output from a PRIOR version
when its content fingerprint already exists in the reuse index (a revert, or code
identical to another branch) — instead of regenerating it."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.engine import carry_forward_from_index

_FIELDS = ("description", "behaviourInputName", "behaviourOutputName")


def _src_loader(by_version):
    """Return a loader(version_id) -> {entityKey: entity} from a {vid: {...}} dict."""
    return lambda vid: by_version.get(vid, {})


class TestCarryForwardFromIndex:
    def test_revert_copies_from_prior_version(self):
        target = {"C|U|a|": {"qualifiedName": "a"}}
        fps = {"C|U|a|": "fp_a"}
        index = {"fp_a": {"versionId": "v1", "entityKey": "C|U|a|"}}
        src = {"v1": {"C|U|a|": {"description": "desc-from-v1", "behaviourInputName": "in"}}}
        reused = carry_forward_from_index(["C|U|a|"], fps, target, index, "v3",
                                          _src_loader(src), _FIELDS)
        assert reused == {"C|U|a|": "v1"}
        assert target["C|U|a|"]["description"] == "desc-from-v1"
        assert target["C|U|a|"]["behaviourInputName"] == "in"

    def test_no_index_hit_is_skipped(self):
        target = {"C|U|a|": {}}
        reused = carry_forward_from_index(["C|U|a|"], {"C|U|a|": "fp_a"}, target, {}, "v3",
                                          _src_loader({}), _FIELDS)
        assert reused == {} and "description" not in target["C|U|a|"]

    def test_hit_on_current_version_is_skipped(self):
        # a fingerprint that resolves to the version being produced must NOT self-copy
        target = {"C|U|a|": {}}
        index = {"fp_a": {"versionId": "v3", "entityKey": "C|U|a|"}}
        src = {"v3": {"C|U|a|": {"description": "self"}}}
        reused = carry_forward_from_index(["C|U|a|"], {"C|U|a|": "fp_a"}, target, index, "v3",
                                          _src_loader(src), _FIELDS)
        assert reused == {} and "description" not in target["C|U|a|"]

    def test_cross_entity_identical_content_copies_from_entityKey(self):
        # two different keys with identical content+deps share a fingerprint; the index
        # points at the FIRST entity. Copy that entity's output to the target key.
        target = {"C|U|b|": {"qualifiedName": "b"}}
        fps = {"C|U|b|": "fp_shared"}
        index = {"fp_shared": {"versionId": "v1", "entityKey": "C|U|a|"}}
        src = {"v1": {"C|U|a|": {"description": "shared-desc"}}}
        reused = carry_forward_from_index(["C|U|b|"], fps, target, index, "v3",
                                          _src_loader(src), _FIELDS)
        assert reused == {"C|U|b|": "v1"}
        assert target["C|U|b|"]["description"] == "shared-desc"

    def test_missing_source_entity_is_skipped(self):
        target = {"C|U|a|": {}}
        index = {"fp_a": {"versionId": "v1", "entityKey": "C|U|gone|"}}
        reused = carry_forward_from_index(["C|U|a|"], {"C|U|a|": "fp_a"}, target, index, "v3",
                                          _src_loader({"v1": {}}), _FIELDS)
        assert reused == {} and target["C|U|a|"] == {}

    def test_no_fingerprint_for_key_is_skipped(self):
        target = {"C|U|a|": {}}
        index = {"fp_a": {"versionId": "v1", "entityKey": "C|U|a|"}}
        reused = carry_forward_from_index(["C|U|a|"], {}, target, index, "v3",
                                          _src_loader({"v1": {"C|U|a|": {"description": "x"}}}), _FIELDS)
        assert reused == {}

    def test_globals_single_field(self):
        target = {"C|U|g": {"qualifiedName": "g"}}
        index = {"fp_g": {"versionId": "v2", "entityKey": "C|U|g"}}
        src = {"v2": {"C|U|g": {"description": "global-desc"}}}
        reused = carry_forward_from_index(["C|U|g"], {"C|U|g": "fp_g"}, target, index, "v5",
                                          _src_loader(src), ("description",))
        assert reused == {"C|U|g": "v2"} and target["C|U|g"]["description"] == "global-desc"
