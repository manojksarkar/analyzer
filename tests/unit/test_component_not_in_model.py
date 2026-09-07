"""A --selected-component the stored model has never heard of must fail loudly.

Phase 1 parses whole LAYERS, so `reexport --from-phase 3 --scope "component:X"`
works for any component in a layer the original run selected — even one it did not
name. That is the useful half.

The other half was silent: a component from a layer that was NOT parsed has nothing
stored to render, and the run finished with **exit 0 and an empty document** — no
units, no entries, no warning. Reproduced against a Layer1-only model asked for
`Layer2.Gpio`.

Mark: unit (pure dict, no pipeline)
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from core.model_io import COMPONENTS            # noqa: E402
from run_views import _assert_components_in_model  # noqa: E402


def _model(*components):
    return {COMPONENTS: {c: {"units": []} for c in components}}


LAYER1_ONLY = _model("Layer1.Math", "Layer1.App", "Layer1.Sample Core")


class TestComponentNotInModel:

    def test_a_component_from_an_unparsed_layer_is_refused(self):
        with pytest.raises(SystemExit) as exc:
            _assert_components_in_model(LAYER1_ONLY, ["Layer2.Gpio"])
        msg = str(exc.value)
        assert "'Layer2.Gpio'" in msg and "not in this version's model" in msg

    def test_the_message_says_which_layers_the_model_does_cover(self):
        """So the fix — re-run generate with a wider scope — is obvious."""
        with pytest.raises(SystemExit) as exc:
            _assert_components_in_model(LAYER1_ONLY, ["Layer2.Gpio"])
        msg = str(exc.value)
        assert "Layer1" in msg and "3 component(s)" in msg
        assert "generate" in msg

    def test_one_missing_name_among_valid_ones_still_fails(self):
        """Rendering the subset that happened to resolve is what hands back a
        document quietly missing what the caller asked for."""
        with pytest.raises(SystemExit) as exc:
            _assert_components_in_model(LAYER1_ONLY, ["Layer1.Math", "Layer2.Gpio"])
        assert "'Layer2.Gpio'" in str(exc.value)
        assert "'Layer1.Math'" not in str(exc.value)

    def test_every_missing_name_is_listed(self):
        with pytest.raises(SystemExit) as exc:
            _assert_components_in_model(LAYER1_ONLY, ["Layer2.Gpio", "Layer2.Uart"])
        msg = str(exc.value)
        assert "'Layer2.Gpio'" in msg and "'Layer2.Uart'" in msg and " are " in msg

    def test_components_present_in_the_model_pass(self):
        _assert_components_in_model(LAYER1_ONLY, ["Layer1.Math", "Layer1.App"])

    def test_matching_folds_spaces_and_case_like_every_other_lookup(self):
        _assert_components_in_model(LAYER1_ONLY, ["layer1.sample-core", "LAYER1.MATH"])

    def test_a_model_with_no_component_index_says_nothing(self):
        """Nothing to check against — refusing on no evidence would be worse."""
        _assert_components_in_model({}, ["Layer2.Gpio"])
        _assert_components_in_model({COMPONENTS: {}}, ["Layer2.Gpio"])

    def test_no_selection_is_not_an_error(self):
        _assert_components_in_model(LAYER1_ONLY, [])
